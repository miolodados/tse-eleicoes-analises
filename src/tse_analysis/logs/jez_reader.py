"""Extrator não-destrutivo em memória/streaming de pacotes .jez (7z/LZMA e ZIP) da urna."""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx
import py7zr
import py7zr.io

from tse_analysis.config import DEFAULT_ELECTION_YEAR
from tse_analysis.logs.event_catalog import EventCatalog
from tse_analysis.logs.line_parser import (
    ParsedLogEvent,
    decode_log_line,
    parse_log_line,
)

SEVEN_ZIP_MAGIC: bytes = b"7z\xbc\xaf\x27\x1c"
ZIP_MAGIC: bytes = b"PK\x03\x04"
MAX_IN_MEMORY_LOG_BYTES: int = 256 * 1024 * 1024  # 256 MiB limite de segurança por membro
MAX_ARCHIVE_NESTING_DEPTH: int = 3

_ROTATED_DOT_RE = re.compile(r"^logd\.dat\.(\d+)(?:\.(?:jez|zip|7z))?$", re.IGNORECASE)
_ROTATED_PREFIX_RE = re.compile(r"^logd?[_.-]?(\d+)(?:\.dat)?(?:\.(?:jez|zip|7z))?$", re.IGNORECASE)
_CURRENT_LOG_RE = re.compile(r"^logd\.dat$", re.IGNORECASE)
_NESTED_ARCHIVE_SUFFIXES: frozenset[str] = frozenset({".jez", ".zip", ".7z"})
_TSE_FILENAME_RE = re.compile(
    r"(?:^|[-_/]|o\d{5}(?P<uf_prefix>[a-z]{2}))(?P<mun>\d{5})(?P<zone>\d{4})(?P<sec>\d{4})(?:[-_][a-z0-9]+)?\.jez$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SectionTurnContext:
    """Contexto de chaves naturais da unidade section_turn associada ao pacote de log."""

    election_year: int = DEFAULT_ELECTION_YEAR
    turn: int = 1
    uf: str = "BR"
    municipio_code: int = 0
    zone_num: int = 0
    section_num: int = 0
    situacao: str = "Totalizado"


@dataclass(frozen=True, slots=True)
class JezLogLine:
    """Linha decodificada em streaming a partir de um pacote .jez com file_seq monotônico."""

    file_seq: int
    source_member: str
    decoded_line: str


@dataclass(frozen=True, slots=True)
class JezExtractionResult:
    """Resultado estruturado da extração e parsing de logs .jez de uma seção eleitoral."""

    election_year: int
    turn: int
    uf: str
    municipio_code: int
    zone_num: int
    section_num: int
    availability_status: str
    container_format: str | None
    source_members: tuple[str, ...]
    rotated_files_count: int
    jez_files_count: int
    observed_urna_serials: tuple[str, ...]
    has_contingency_indicator: bool
    events: tuple[ParsedLogEvent, ...] | None

    def to_fact_records(self) -> list[dict[str, Any]]:
        """Converte os eventos extraídos para registros compatíveis com fact_urna_event."""
        if self.events is None:
            return []
        return [
            event.to_fact_record(
                election_year=self.election_year,
                turn=self.turn,
                uf=self.uf,
                municipio_code=self.municipio_code,
                zone_num=self.zone_num,
                section_num=self.section_num,
            )
            for event in self.events
        ]


def build_unavailable_jez_result(
    section_context: SectionTurnContext | None = None,
    *,
    availability_status: str = "UNAVAILABLE",
) -> JezExtractionResult:
    """Constrói resultado explícito quando .jez está ausente (events=None, nunca zero eventos)."""
    ctx = section_context if section_context is not None else SectionTurnContext()
    return JezExtractionResult(
        election_year=ctx.election_year,
        turn=ctx.turn,
        uf=ctx.uf.strip().upper(),
        municipio_code=ctx.municipio_code,
        zone_num=ctx.zone_num,
        section_num=ctx.section_num,
        availability_status=availability_status,
        container_format=None,
        source_members=(),
        rotated_files_count=0,
        jez_files_count=0,
        observed_urna_serials=(),
        has_contingency_indicator=False,
        events=None,
    )


def parse_section_keys_from_filename(
    filename: str,
    *,
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    situacao: str = "Totalizado",
) -> SectionTurnContext | None:
    """Extrai chaves de seção de 'o00407-MMMMMZZZZSSSS.jez' ou 'o03220acMMMMMZZZZSSSS-log.jez'."""
    match = _TSE_FILENAME_RE.search(Path(filename).name)
    if match is None:
        return None
    inferred_uf = match.group("uf_prefix") or uf
    return SectionTurnContext(
        election_year=election_year,
        turn=turn,
        uf=inferred_uf.strip().upper(),
        municipio_code=int(match.group("mun")),
        zone_num=int(match.group("zone")),
        section_num=int(match.group("sec")),
        situacao=situacao,
    )


def detect_jez_container_format(raw_bytes: bytes) -> str:
    """Identifica o formato físico do contêiner .jez pelos magic bytes (7z/LZMA ou ZIP)."""
    if raw_bytes.startswith(SEVEN_ZIP_MAGIC):
        return "7z"
    if raw_bytes.startswith(ZIP_MAGIC):
        return "zip"
    raise ValueError(
        "Assinatura mágica inválida no pacote .jez: esperado contêiner 7z/LZMA "
        "(37 7A BC AF 27 1C) ou ZIP (50 4B 03 04)."
    )


def _classify_log_member_rotation(member_name: str) -> int | None:
    """Retorna o índice de rotação (0 para logd.dat ativo, >=1 para rotacionados) ou None."""
    basename = Path(member_name).name.strip()
    if _CURRENT_LOG_RE.fullmatch(basename):
        return 0
    m_dot = _ROTATED_DOT_RE.fullmatch(basename)
    if m_dot is not None:
        return int(m_dot.group(1))
    m_prefix = _ROTATED_PREFIX_RE.fullmatch(basename)
    if m_prefix is not None:
        return int(m_prefix.group(1))
    return None


def sort_log_member_names(member_names: Sequence[str]) -> tuple[str, ...]:
    """Ordena determinísticamente os membros de log do mais antigo rotacionado ao logd.dat atual.

    Exemplo: ['logd.dat', 'logd.dat.1', 'logd.dat.2'] -> ('logd.dat.2', 'logd.dat.1', 'logd.dat').
    """
    classified: list[tuple[int, str]] = []
    for name in member_names:
        rot = _classify_log_member_rotation(name)
        if rot is not None:
            classified.append((rot, name))

    # Ordena em ordem decrescente de rotação (2 -> 1 -> 0)
    classified.sort(key=lambda item: (-item[0], item[1]))
    return tuple(name for _, name in classified)


def count_rotated_log_members(member_names: Sequence[str]) -> int:
    """Conta quantos membros internos correspondem a arquivos rotacionados (índice >= 1)."""
    count = 0
    for name in member_names:
        rot = _classify_log_member_rotation(name)
        if rot is not None and rot > 0:
            count += 1
    return count


def _read_raw_bytes_from_source(source: str | Path | bytes | BinaryIO) -> bytes | None:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            return None
        return path.read_bytes()
    return source.read()


def _extract_7z_members_in_memory(raw_bytes: bytes) -> dict[str, bytes]:
    buffer = io.BytesIO(raw_bytes)
    with py7zr.SevenZipFile(buffer, mode="r") as archive:
        if hasattr(py7zr.io, "BytesIOFactory"):
            factory = py7zr.io.BytesIOFactory(limit=MAX_IN_MEMORY_LOG_BYTES)
            archive.extract(factory=factory)
            result: dict[str, bytes] = {}
            for name, bio in factory.products.items():
                bio.seek(0)
                result[name] = bio.read()
            return result

        # Fallback compatível com versões legadas do py7zr (< 1.0)
        read_fn = getattr(archive, "read", None) or getattr(archive, "readall", None)
        if read_fn is not None:
            raw_map = read_fn()
            return {name: bio.read() for name, bio in raw_map.items()}
        raise RuntimeError("Versão de py7zr incompatível para extração em memória.")


def _extract_zip_members_in_memory(raw_bytes: bytes) -> dict[str, bytes]:
    buffer = io.BytesIO(raw_bytes)
    result: dict[str, bytes] = {}
    with zipfile.ZipFile(buffer, mode="r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info.filename, mode="r") as member_fh:
                result[info.filename] = member_fh.read(MAX_IN_MEMORY_LOG_BYTES)
    return result


def read_jez_member_bytes(
    source: str | Path | bytes | BinaryIO,
    *,
    _depth: int = 0,
) -> tuple[str, dict[str, bytes]]:
    """Descompacta em memória um pacote .jez (7z/LZMA ou ZIP) e retorna (formato, mapa_bytes).

    Suporta pacotes rotacionados aninhados (ex.: logd.dat.1.jez ou log1.zip dentro de .jez)
    com limite de profundidade MAX_ARCHIVE_NESTING_DEPTH.
    """
    raw_bytes = _read_raw_bytes_from_source(source)
    if raw_bytes is None or not raw_bytes:
        raise FileNotFoundError("Pacote .jez inexistente ou vazio.")

    fmt = detect_jez_container_format(raw_bytes)
    if fmt == "7z":
        raw_members = _extract_7z_members_in_memory(raw_bytes)
    else:
        raw_members = _extract_zip_members_in_memory(raw_bytes)

    flattened: dict[str, bytes] = {}
    for member_name, payload in raw_members.items():
        suffix = Path(member_name).suffix.lower()
        if (
            _depth < MAX_ARCHIVE_NESTING_DEPTH
            and suffix in _NESTED_ARCHIVE_SUFFIXES
            and (payload.startswith(SEVEN_ZIP_MAGIC) or payload.startswith(ZIP_MAGIC))
        ):
            _, inner_members = read_jez_member_bytes(payload, _depth=_depth + 1)
            parent_rot = _classify_log_member_rotation(member_name)
            for inner_name, inner_bytes in inner_members.items():
                inner_rot = _classify_log_member_rotation(inner_name)
                if parent_rot is not None and parent_rot > 0 and inner_rot == 0:
                    synthetic_name = f"logd.dat.{parent_rot}"
                else:
                    synthetic_name = inner_name
                flattened[synthetic_name] = inner_bytes
        else:
            flattened[member_name] = payload

    return fmt, flattened


def read_jez_log_lines(
    source: str | Path | bytes | BinaryIO,
    *,
    start_seq: int = 1,
) -> Iterator[JezLogLine]:
    """Itera em streaming pelas linhas de log de um .jez em ordem cronológica de segmentos."""
    if start_seq < 1:
        raise ValueError(f"start_seq deve ser >= 1 (recebido: {start_seq}).")

    _, members = read_jez_member_bytes(source)
    ordered_names = sort_log_member_names(tuple(members.keys()))

    current_seq = start_seq
    for member_name in ordered_names:
        payload = members[member_name]
        for raw_line in payload.splitlines():
            if not raw_line.strip():
                continue
            yield JezLogLine(
                file_seq=current_seq,
                source_member=member_name,
                decoded_line=decode_log_line(raw_line),
            )
            current_seq += 1


def extract_jez_events(
    source: str | Path | bytes | BinaryIO,
    *,
    section_context: SectionTurnContext | None = None,
    catalog: EventCatalog | None = None,
    availability_status: str = "LOCAL_FIXTURE",
    start_seq: int = 1,
    deduplicate_lines: bool = False,
) -> JezExtractionResult:
    """Extrai e classifica todos os eventos de um pacote .jez em memória sem tocar o disco."""
    ctx = section_context if section_context is not None else SectionTurnContext()
    if ctx.situacao != "Totalizado":
        return build_unavailable_jez_result(
            ctx,
            availability_status="SKIPPED_NOT_TOTALIZADO",
        )

    raw_bytes = _read_raw_bytes_from_source(source)
    if raw_bytes is None or not raw_bytes:
        return build_unavailable_jez_result(ctx, availability_status="UNAVAILABLE")

    try:
        fmt, members = read_jez_member_bytes(raw_bytes)
    except (zipfile.BadZipFile, py7zr.Bad7zFile, EOFError, ValueError):
        return build_unavailable_jez_result(
            ctx,
            availability_status="CORRUPTED_ARCHIVE",
        )

    ordered_names = sort_log_member_names(tuple(members.keys()))
    if not ordered_names:
        return build_unavailable_jez_result(ctx, availability_status="UNAVAILABLE")

    rotated_count = count_rotated_log_members(ordered_names)
    events: list[ParsedLogEvent] = []
    observed_serials: list[str] = []
    seen_serials: set[str] = set()
    seen_raw_lines: set[bytes] = set()

    current_seq = start_seq
    last_valid_ts_by_serial: dict[str, datetime] = {}
    global_last_ts: datetime | None = None

    for member_name in ordered_names:
        payload = members[member_name]
        for raw_line in payload.splitlines():
            stripped_raw = raw_line.strip()
            if not stripped_raw:
                continue
            if deduplicate_lines:
                if stripped_raw in seen_raw_lines:
                    continue
                seen_raw_lines.add(stripped_raw)

            default_serial = observed_serials[-1] if observed_serials else "UNKNOWN"
            # Peek serial from raw line if present to compare timestamp per urna_serial
            line_parts = stripped_raw.split(b"\t")
            candidate_serial: str | None = None
            if len(line_parts) >= 5:
                # 7-field (date, time, level, serial, ...) vs 6-field (datetime, level, serial, ...)
                if len(line_parts[0].strip()) == 10 and b":" in line_parts[1]:
                    candidate_serial = line_parts[3].strip().decode("latin1")
                else:
                    candidate_serial = line_parts[2].strip().decode("latin1")
            prev_ts = (
                last_valid_ts_by_serial.get(candidate_serial)
                if candidate_serial
                else global_last_ts
            )

            event = parse_log_line(
                raw_line,
                file_seq=current_seq,
                previous_valid_timestamp=prev_ts,
                default_urna_serial=default_serial,
                catalog=catalog,
            )
            if event.raw_timestamp is not None:
                last_valid_ts_by_serial[event.urna_serial] = event.raw_timestamp
                global_last_ts = event.raw_timestamp
            if event.urna_serial != "UNKNOWN" and event.urna_serial not in seen_serials:
                seen_serials.add(event.urna_serial)
                observed_serials.append(event.urna_serial)
            events.append(event)
            current_seq += 1

    has_contingency = len(observed_serials) > 1 or any(
        e.event_code == "CONTINGENCY_EVENT" for e in events
    )

    return JezExtractionResult(
        election_year=ctx.election_year,
        turn=ctx.turn,
        uf=ctx.uf.strip().upper(),
        municipio_code=ctx.municipio_code,
        zone_num=ctx.zone_num,
        section_num=ctx.section_num,
        availability_status=availability_status,
        container_format=fmt,
        source_members=ordered_names,
        rotated_files_count=rotated_count,
        jez_files_count=1,
        observed_urna_serials=tuple(observed_serials),
        has_contingency_indicator=has_contingency,
        events=tuple(events),
    )


def extract_section_bundle_events(
    zip_source: str | Path | bytes | BinaryIO,
    *,
    section_context: SectionTurnContext | None = None,
    catalog: EventCatalog | None = None,
    availability_status: str = "LOCAL_FIXTURE",
) -> JezExtractionResult:
    """Extrai eventos de um ou mais arquivos .jez aninhados em um pacote ZIP de seção/totalização.

    Se o pacote ZIP não existir ou não contiver artefatos .jez, retorna
    availability_status = 'UNAVAILABLE' e events = None.
    """
    ctx = section_context if section_context is not None else SectionTurnContext()
    if ctx.situacao != "Totalizado":
        return build_unavailable_jez_result(
            ctx,
            availability_status="SKIPPED_NOT_TOTALIZADO",
        )

    raw_zip = _read_raw_bytes_from_source(zip_source)
    if raw_zip is None or not raw_zip:
        return build_unavailable_jez_result(ctx, availability_status="UNAVAILABLE")

    try:
        zf_ctx = zipfile.ZipFile(io.BytesIO(raw_zip), mode="r")
    except zipfile.BadZipFile:
        return build_unavailable_jez_result(ctx, availability_status="CORRUPTED_ARCHIVE")

    with zf_ctx as zf:
        jez_members = sorted(
            info.filename
            for info in zf.infolist()
            if not info.is_dir() and Path(info.filename).suffix.lower() == ".jez"
        )
        if not jez_members:
            return build_unavailable_jez_result(ctx, availability_status="UNAVAILABLE")

        # Se section_context não especificou município/zona/seção, infere do nome do primeiro .jez
        effective_ctx = ctx
        if ctx.municipio_code == 0 and ctx.zone_num == 0 and ctx.section_num == 0:
            inferred = parse_section_keys_from_filename(
                jez_members[0],
                election_year=ctx.election_year,
                turn=ctx.turn,
                uf=ctx.uf,
                situacao=ctx.situacao,
            )
            if inferred is not None:
                effective_ctx = inferred

        all_events: list[ParsedLogEvent] = []
        all_source_members: list[str] = []
        observed_serials: list[str] = []
        seen_serials: set[str] = set()
        next_seq_by_serial: dict[str, int] = {}
        total_rotated = 0
        detected_formats: set[str] = set()

        for jez_name in jez_members:
            with zf.open(jez_name, mode="r") as jez_fh:
                jez_bytes = jez_fh.read()

            sub_result = extract_jez_events(
                jez_bytes,
                section_context=effective_ctx,
                catalog=catalog,
                availability_status=availability_status,
                start_seq=1,
            )
            if sub_result.events is None:
                continue
            if sub_result.container_format is not None:
                detected_formats.add(sub_result.container_format)
            total_rotated += sub_result.rotated_files_count
            all_source_members.extend(
                f"{Path(jez_name).name}:{m}" for m in sub_result.source_members
            )
            for serial in sub_result.observed_urna_serials:
                if serial not in seen_serials:
                    seen_serials.add(serial)
                    observed_serials.append(serial)
            for ev in sub_result.events:
                seq_for_serial = next_seq_by_serial.get(ev.urna_serial, 1)
                next_seq_by_serial[ev.urna_serial] = seq_for_serial + 1
                if ev.file_seq != seq_for_serial:
                    ev = ParsedLogEvent(
                        file_seq=seq_for_serial,
                        raw_timestamp=ev.raw_timestamp,
                        has_timestamp_regression=ev.has_timestamp_regression,
                        urna_serial=ev.urna_serial,
                        application=ev.application,
                        log_level=ev.log_level,
                        event_code=ev.event_code,
                        biometric_attempt_num=ev.biometric_attempt_num,
                    )
                all_events.append(ev)

    if not all_events and not all_source_members:
        return build_unavailable_jez_result(effective_ctx, availability_status="UNAVAILABLE")

    has_contingency = (
        len(jez_members) > 1
        or len(observed_serials) > 1
        or any(e.event_code == "CONTINGENCY_EVENT" for e in all_events)
    )
    fmt_summary = "+".join(sorted(detected_formats)) if detected_formats else "zip_bundle"

    return JezExtractionResult(
        election_year=effective_ctx.election_year,
        turn=effective_ctx.turn,
        uf=effective_ctx.uf.strip().upper(),
        municipio_code=effective_ctx.municipio_code,
        zone_num=effective_ctx.zone_num,
        section_num=effective_ctx.section_num,
        availability_status=availability_status,
        container_format=fmt_summary,
        source_members=tuple(all_source_members),
        rotated_files_count=total_rotated,
        jez_files_count=len(jez_members),
        observed_urna_serials=tuple(observed_serials),
        has_contingency_indicator=has_contingency,
        events=tuple(all_events),
    )


def fetch_remote_jez_by_range(
    zip_url: str,
    *,
    jez_index: int = 0,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> tuple[str, bytes]:
    """Baixa apenas um único arquivo .jez de um pacote ZIP remoto do TSE via HTTP Range.

    Lê o Central Directory no final do ZIP (sem baixar centenas de megabytes) e extrai
    em memória o membro .jez solicitado, retornando (member_filename, jez_bytes).
    """
    owns_client = client is None
    http_client = (
        client
        if client is not None
        else httpx.Client(timeout=timeout, follow_redirects=True)
    )
    try:
        head_resp = http_client.head(zip_url)
        head_resp.raise_for_status()
        total_size = int(head_resp.headers["content-length"])
        tail_len = min(total_size, 2 * 1024 * 1024)
        tail_resp = http_client.get(
            zip_url,
            headers={"Range": f"bytes={total_size - tail_len}-{total_size - 1}"},
        )
        tail_resp.raise_for_status()
        tail_bytes = tail_resp.content

        eocd_pos = tail_bytes.rfind(b"PK\x05\x06")
        if eocd_pos < 0:
            raise ValueError("Assinatura EOCD (PK\\x05\\x06) não encontrada no ZIP remoto.")
        cd_size, cd_offset = struct.unpack(
            "<II", tail_bytes[eocd_pos + 12 : eocd_pos + 20]
        )

        cd_resp = http_client.get(
            zip_url,
            headers={"Range": f"bytes={cd_offset}-{cd_offset + cd_size - 1}"},
        )
        cd_resp.raise_for_status()
        cd_bytes = cd_resp.content

        pos = 0
        found_jez: list[tuple[str, int, int, int]] = []
        while pos + 46 <= len(cd_bytes):
            if cd_bytes[pos : pos + 4] != b"PK\x01\x02":
                break
            comp_method = struct.unpack("<H", cd_bytes[pos + 10 : pos + 12])[0]
            comp_size, _, fn_len, extra_len, comment_len = struct.unpack(
                "<IIHHH", cd_bytes[pos + 20 : pos + 34]
            )
            local_hdr_offset = struct.unpack("<I", cd_bytes[pos + 42 : pos + 46])[0]
            fname = cd_bytes[pos + 46 : pos + 46 + fn_len].decode("latin1")
            pos += 46 + fn_len + extra_len + comment_len
            if fname.lower().endswith(".jez"):
                found_jez.append((fname, comp_method, comp_size, local_hdr_offset))
                if len(found_jez) > jez_index:
                    break

        if len(found_jez) <= jez_index:
            raise FileNotFoundError(
                f"Índice .jez {jez_index} não encontrado no pacote remoto {zip_url}."
            )

        target_name, comp_method, comp_size, lhoff = found_jez[jez_index]
        end_byte = lhoff + 30 + len(target_name) + 256 + comp_size
        entry_resp = http_client.get(
            zip_url,
            headers={"Range": f"bytes={lhoff}-{end_byte}"},
        )
        entry_resp.raise_for_status()
        raw_entry = entry_resp.content
        fn_l, ex_l = struct.unpack("<HH", raw_entry[26:30])
        data_start = 30 + fn_l + ex_l
        comp_data = raw_entry[data_start : data_start + comp_size]
        if comp_method == 8:
            jez_bytes = zlib.decompress(comp_data, -zlib.MAX_WBITS)
        elif comp_method == 0:
            jez_bytes = comp_data
        else:
            raise ValueError(f"Método de compressão ZIP não suportado: {comp_method}")

        return target_name, jez_bytes
    finally:
        if owns_client:
            http_client.close()
