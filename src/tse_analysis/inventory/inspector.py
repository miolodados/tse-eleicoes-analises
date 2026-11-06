"""Inspeção em streaming/leitura parcial de pacotes ZIP e arquivos CSV do TSE."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import httpx

from tse_analysis.config import DEFAULT_ELECTION_YEAR
from tse_analysis.inventory.catalog import SourceEntry

MAX_HEADER_SAMPLE_BYTES: int = 65536  # 64 KiB

CANONICAL_TO_TSE_COLUMNS: dict[str, tuple[str, ...]] = {
    "election_year": ("ANO_ELEICAO",),
    "turn": ("NR_TURNO",),
    "uf": ("SG_UF",),
    "municipio_code": ("CD_MUNICIPIO",),
    "zone_num": ("NR_ZONA",),
    "section_num": ("NR_SECAO",),
    "cargo_code": ("CD_CARGO_PERGUNTA", "CD_CARGO"),
    "votavel_num": ("NR_VOTAVEL",),
    "gender_code": ("CD_GENERO",),
    "age_group_code": ("CD_FAIXA_ETARIA",),
    "education_level_code": ("CD_GRAU_ESCOLARIDADE",),
    "urna_serial_expected": ("NR_URNA_ESPERADA",),
    "urna_serial_effective": ("NR_URNA_EFETIVADA",),
}


@dataclass(frozen=True, slots=True)
class HeaderInspectionResult:
    """Resultado estruturado e sanitizado (sem dados de linhas) da inspeção de uma fonte."""

    source_id: str
    election_year: int
    turn: int
    uf: str
    availability_status: str
    file_format: str
    detected_encoding: str | None
    detected_delimiter: str | None
    member_count: int | None
    has_log_jez: bool | None
    header_columns: tuple[str, ...] = field(default_factory=tuple)
    missing_natural_keys: tuple[str, ...] = field(default_factory=tuple)
    extra_columns: tuple[str, ...] = field(default_factory=tuple)
    is_valid_key_set: bool | None = None
    license_status: str = "open_documented"
    redistribution_allowed: bool = True
    member_names: tuple[str, ...] = field(default_factory=tuple)
    extension_counts: dict[str, int] = field(default_factory=dict)

    @property
    def encoding(self) -> str | None:
        """Alias para detected_encoding."""
        return self.detected_encoding

    @property
    def delimiter(self) -> str | None:
        """Alias para detected_delimiter."""
        return self.detected_delimiter

    @property
    def missing_keys(self) -> tuple[str, ...]:
        """Alias para missing_natural_keys."""
        return self.missing_natural_keys

    def to_record(self) -> dict[str, object]:
        """Converte o resultado em dicionário compatível com INVENTORY_INSPECTION_SCHEMA.

        Garante retenção exclusiva de metadados estruturais (zero linhas de dados).
        """
        return {
            "source_id": self.source_id,
            "election_year": self.election_year,
            "turn": self.turn,
            "uf": self.uf,
            "availability_status": self.availability_status,
            "file_format": self.file_format,
            "detected_encoding": self.detected_encoding,
            "detected_delimiter": self.detected_delimiter,
            "member_count": self.member_count,
            "has_log_jez": self.has_log_jez,
            "header_columns": list(self.header_columns),
            "missing_natural_keys": list(self.missing_natural_keys),
            "is_valid_key_set": self.is_valid_key_set,
            "license_status": self.license_status,
            "redistribution_allowed": self.redistribution_allowed,
        }


def detect_encoding_and_extract_header(
    raw_bytes: bytes,
    default_delimiter: str = ";",
) -> tuple[str, str, tuple[str, ...]]:
    """Detecta o encoding ('utf-8' ou 'latin1'), delimitador e extrai apenas a linha de cabeçalho.

    Descarta imediatamente todas as linhas subsequentes do buffer para evitar vazamento
    de dados pessoais, votos ou texto livre.
    """
    sample = raw_bytes[:MAX_HEADER_SAMPLE_BYTES]
    if not sample:
        return "utf-8", default_delimiter, ()

    # Tenta decodificar o cabeçalho (primeira linha) em UTF-8 estrito; fallback para Latin-1
    first_raw_line = sample.splitlines()[0]
    try:
        first_line = first_raw_line.decode("utf-8-sig", errors="strict")
        detected_encoding = "utf-8"
    except UnicodeDecodeError:
        first_line = first_raw_line.decode("latin1")
        detected_encoding = "latin1"

    first_line = first_line.strip("\r\n")
    if not first_line.strip():
        return detected_encoding, default_delimiter, ()

    if ";" in first_line:
        detected_delimiter = ";"
    elif "\t" in first_line:
        detected_delimiter = "\t"
    elif "," in first_line:
        detected_delimiter = ","
    else:
        detected_delimiter = default_delimiter

    reader = csv.reader([first_line], delimiter=detected_delimiter, quotechar='"')
    parsed_row = next(reader, [])
    columns = tuple(col.strip().strip('"').strip() for col in parsed_row if col.strip())
    return detected_encoding, detected_delimiter, columns


def validate_header_keys(
    header_columns: Sequence[str],
    expected_keys: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """Compara o cabeçalho inspecionado com as chaves/colunas esperadas.

    Suporta tanto nomes físicos do TSE (ex.: 'ANO_ELEICAO', 'CD_MUNICIPIO') quanto
    chaves lógicas canônicas (ex.: 'election_year', 'municipio_code').
    Retorna (missing_keys, extra_columns, is_valid_key_set).
    """
    header_upper_map = {col.upper(): col for col in header_columns}
    matched_header_upper: set[str] = set()
    missing: list[str] = []

    for key in expected_keys:
        key_upper = key.upper()
        if key_upper in header_upper_map:
            matched_header_upper.add(key_upper)
            continue

        aliases = CANONICAL_TO_TSE_COLUMNS.get(key, ())
        matched_alias = next((alias for alias in aliases if alias in header_upper_map), None)
        if matched_alias is not None:
            matched_header_upper.add(matched_alias)
        else:
            missing.append(key)

    extra = tuple(col for col in header_columns if col.upper() not in matched_header_upper)
    is_valid = len(missing) == 0 and len(header_columns) > 0
    return tuple(missing), extra, is_valid


def build_unavailable_result(
    *,
    source_id: str,
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    file_format: str = "zip_csv",
    license_status: str = "open_documented",
    redistribution_allowed: bool = True,
) -> HeaderInspectionResult:
    """Cria um resultado explícito de recurso indisponível sem assumir zero ocorrências."""
    return HeaderInspectionResult(
        source_id=source_id,
        election_year=election_year,
        turn=turn,
        uf=uf.upper(),
        availability_status="UNAVAILABLE",
        file_format=file_format,
        detected_encoding=None,
        detected_delimiter=None,
        member_count=None,
        has_log_jez=None,
        header_columns=(),
        missing_natural_keys=(),
        extra_columns=(),
        is_valid_key_set=None,
        license_status=license_status,
        redistribution_allowed=redistribution_allowed,
        member_names=(),
        extension_counts={},
    )


def _resolve_expected_keys(
    source_entry: SourceEntry | None,
    expected_keys: Sequence[str] | None,
) -> Sequence[str]:
    if expected_keys is not None:
        return expected_keys
    if source_entry is not None:
        if source_entry.expected_columns:
            return source_entry.expected_columns
        return source_entry.natural_keys
    return ()


def inspect_csv_stream(
    stream: BinaryIO,
    *,
    source_id: str = "csv_source",
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    expected_keys: Sequence[str] | None = None,
    source_entry: SourceEntry | None = None,
    availability_status: str = "LOCAL_FIXTURE",
) -> HeaderInspectionResult:
    """Inspeciona apenas os primeiros 64 KiB de um stream CSV sem carregar o arquivo inteiro."""
    effective_source_id = source_entry.source_id if source_entry is not None else source_id
    license_status = source_entry.license_status if source_entry is not None else "open_documented"
    redistribution_allowed = (
        source_entry.redistribution_allowed if source_entry is not None else True
    )
    default_delimiter = (
        source_entry.delimiter
        if (source_entry is not None and source_entry.delimiter)
        else ";"
    )

    raw_sample = stream.read(MAX_HEADER_SAMPLE_BYTES)
    encoding, delimiter, columns = detect_encoding_and_extract_header(
        raw_sample,
        default_delimiter=default_delimiter,
    )

    keys_to_check = _resolve_expected_keys(source_entry, expected_keys)
    if keys_to_check:
        missing, extra, is_valid = validate_header_keys(columns, keys_to_check)
    else:
        missing, extra, is_valid = (), columns, len(columns) > 0

    return HeaderInspectionResult(
        source_id=effective_source_id,
        election_year=election_year,
        turn=turn,
        uf=uf.upper(),
        availability_status=availability_status,
        file_format=source_entry.file_format if source_entry is not None else "csv",
        detected_encoding=encoding,
        detected_delimiter=delimiter,
        member_count=1,
        has_log_jez=False,
        header_columns=columns,
        missing_natural_keys=missing,
        extra_columns=extra,
        is_valid_key_set=is_valid,
        license_status=license_status,
        redistribution_allowed=redistribution_allowed,
        member_names=(),
        extension_counts={".csv": 1},
    )


def inspect_csv_file(
    csv_path: str | Path,
    *,
    source_id: str = "csv_source",
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    expected_keys: Sequence[str] | None = None,
    source_entry: SourceEntry | None = None,
    availability_status: str = "LOCAL_FIXTURE",
) -> HeaderInspectionResult:
    """Inspeciona os bytes iniciais de um arquivo CSV local ou retorna UNAVAILABLE se ausente."""
    path = Path(csv_path)
    effective_source_id = source_entry.source_id if source_entry is not None else source_id
    if not path.exists():
        return build_unavailable_result(
            source_id=effective_source_id,
            election_year=election_year,
            turn=turn,
            uf=uf,
            file_format=source_entry.file_format if source_entry is not None else "csv",
            license_status=(
                source_entry.license_status if source_entry is not None else "open_documented"
            ),
            redistribution_allowed=(
                source_entry.redistribution_allowed if source_entry is not None else True
            ),
        )

    with path.open("rb") as fh:
        return inspect_csv_stream(
            fh,
            source_id=effective_source_id,
            election_year=election_year,
            turn=turn,
            uf=uf,
            expected_keys=expected_keys,
            source_entry=source_entry,
            availability_status=availability_status,
        )


def inspect_zip_stream(
    stream: BinaryIO,
    *,
    source_id: str = "zip_source",
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    expected_keys: Sequence[str] | None = None,
    source_entry: SourceEntry | None = None,
    availability_status: str = "LOCAL_FIXTURE",
) -> HeaderInspectionResult:
    """Inspeciona o diretório central de um pacote ZIP e o cabeçalho do primeiro CSV interno.

    Não realiza extração de arquivos em disco.
    """
    effective_source_id = source_entry.source_id if source_entry is not None else source_id
    license_status = source_entry.license_status if source_entry is not None else "open_documented"
    redistribution_allowed = (
        source_entry.redistribution_allowed if source_entry is not None else True
    )
    file_format = source_entry.file_format if source_entry is not None else "zip"

    with zipfile.ZipFile(stream, mode="r") as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        member_names = tuple(info.filename for info in infos)
        ext_counter: Counter[str] = Counter(
            Path(info.filename).suffix.lower() for info in infos
        )
        extension_counts = dict(sorted(ext_counter.items()))
        has_log_jez = extension_counts.get(".jez", 0) > 0

        csv_members = [
            info.filename
            for info in infos
            if Path(info.filename).suffix.lower() == ".csv"
        ]

        if csv_members:
            with zf.open(csv_members[0], mode="r") as csv_fh:
                raw_sample = csv_fh.read(MAX_HEADER_SAMPLE_BYTES)
            default_delimiter = (
                source_entry.delimiter
                if (source_entry is not None and source_entry.delimiter)
                else ";"
            )
            encoding, delimiter, columns = detect_encoding_and_extract_header(
                raw_sample,
                default_delimiter=default_delimiter,
            )
            keys_to_check = _resolve_expected_keys(source_entry, expected_keys)
            if keys_to_check:
                missing, extra, is_valid = validate_header_keys(columns, keys_to_check)
            else:
                missing, extra, is_valid = (), columns, len(columns) > 0
        else:
            encoding = source_entry.expected_encoding if source_entry is not None else None
            delimiter = source_entry.delimiter if source_entry is not None else None
            columns = ()
            missing = ()
            extra = ()
            # Para pacotes de totalização (.jez/.bu sem CSV), valida presença de membros internos
            is_valid = len(infos) > 0

    return HeaderInspectionResult(
        source_id=effective_source_id,
        election_year=election_year,
        turn=turn,
        uf=uf.upper(),
        availability_status=availability_status,
        file_format=file_format,
        detected_encoding=encoding,
        detected_delimiter=delimiter,
        member_count=len(member_names),
        has_log_jez=has_log_jez,
        header_columns=columns,
        missing_natural_keys=missing,
        extra_columns=extra,
        is_valid_key_set=is_valid,
        license_status=license_status,
        redistribution_allowed=redistribution_allowed,
        member_names=member_names,
        extension_counts=extension_counts,
    )


def inspect_zip_file(
    zip_path: str | Path,
    *,
    source_id: str = "zip_source",
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    expected_keys: Sequence[str] | None = None,
    source_entry: SourceEntry | None = None,
    availability_status: str = "LOCAL_FIXTURE",
) -> HeaderInspectionResult:
    """Inspeciona um arquivo ZIP local em streaming ou retorna UNAVAILABLE se ausente."""
    path = Path(zip_path)
    effective_source_id = source_entry.source_id if source_entry is not None else source_id
    if not path.exists():
        return build_unavailable_result(
            source_id=effective_source_id,
            election_year=election_year,
            turn=turn,
            uf=uf,
            file_format=source_entry.file_format if source_entry is not None else "zip",
            license_status=(
                source_entry.license_status if source_entry is not None else "open_documented"
            ),
            redistribution_allowed=(
                source_entry.redistribution_allowed if source_entry is not None else True
            ),
        )

    with path.open("rb") as fh:
        return inspect_zip_stream(
            fh,
            source_id=effective_source_id,
            election_year=election_year,
            turn=turn,
            uf=uf,
            expected_keys=expected_keys,
            source_entry=source_entry,
            availability_status=availability_status,
        )


def inspect_remote_source(
    source_entry: SourceEntry,
    *,
    election_year: int = DEFAULT_ELECTION_YEAR,
    turn: int = 1,
    uf: str = "BR",
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> HeaderInspectionResult:
    """Verifica disponibilidade remota via HTTP HEAD/Range sem assumir zero ocorrências em 404."""
    url = source_entry.resolve_url(election_year=election_year, turn=turn, uf=uf)
    owns_client = client is None
    http_client = client if client is not None else httpx.Client(timeout=timeout)
    try:
        response = http_client.head(url, follow_redirects=True)
        if response.status_code == 404 or response.status_code >= 400:
            return build_unavailable_result(
                source_id=source_entry.source_id,
                election_year=election_year,
                turn=turn,
                uf=uf,
                file_format=source_entry.file_format,
                license_status=source_entry.license_status,
                redistribution_allowed=source_entry.redistribution_allowed,
            )

        if source_entry.file_format == "csv":
            range_resp = http_client.get(
                url,
                headers={"Range": f"bytes=0-{MAX_HEADER_SAMPLE_BYTES - 1}"},
                follow_redirects=True,
            )
            if range_resp.status_code < 400 and range_resp.content:
                return inspect_csv_stream(
                    io.BytesIO(range_resp.content),
                    source_entry=source_entry,
                    election_year=election_year,
                    turn=turn,
                    uf=uf,
                    availability_status="AVAILABLE",
                )

        return HeaderInspectionResult(
            source_id=source_entry.source_id,
            election_year=election_year,
            turn=turn,
            uf=uf.upper(),
            availability_status="AVAILABLE",
            file_format=source_entry.file_format,
            detected_encoding=source_entry.expected_encoding,
            detected_delimiter=source_entry.delimiter,
            member_count=None,
            has_log_jez=None,
            header_columns=source_entry.expected_columns,
            missing_natural_keys=(),
            extra_columns=(),
            is_valid_key_set=True,
            license_status=source_entry.license_status,
            redistribution_allowed=source_entry.redistribution_allowed,
        )
    except httpx.HTTPError:
        return build_unavailable_result(
            source_id=source_entry.source_id,
            election_year=election_year,
            turn=turn,
            uf=uf,
            file_format=source_entry.file_format,
            license_status=source_entry.license_status,
            redistribution_allowed=source_entry.redistribution_allowed,
        )
    finally:
        if owns_client:
            http_client.close()
