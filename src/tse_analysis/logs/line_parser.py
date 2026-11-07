"""Parser estrutural linha-a-linha dos logs do Ecossistema da Urna com ordem canônica file_seq."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tse_analysis.logs.event_catalog import (
    MALFORMED_LINE_CODE,
    EventCatalog,
    classify_log_message,
)

_HEX_MAC_RE = re.compile(r"^[0-9A-Fa-f]{6,64}$")
_DATE_ONLY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME_ONLY_RE = re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?$")
_KNOWN_LEVELS: frozenset[str] = frozenset(
    {"INFO", "WARN", "WARNING", "ERRO", "ERROR", "DEBUG", "FATAL", "CRIT"}
)


@dataclass(frozen=True, slots=True)
class ParsedLogEvent:
    """Evento estruturado e sanitizado extraído de uma linha de log da urna.

    Por construção, jamais retém message_text bruto nem o autenticador mac_code.
    """

    file_seq: int
    raw_timestamp: datetime | None
    has_timestamp_regression: bool
    urna_serial: str
    application: str
    log_level: str
    event_code: str
    biometric_attempt_num: int | None = None

    def to_fact_record(
        self,
        *,
        election_year: int,
        turn: int,
        uf: str,
        municipio_code: int,
        zone_num: int,
        section_num: int,
    ) -> dict[str, Any]:
        """Converte o evento para registro compatível com FACT_URNA_EVENT_SCHEMA."""
        return {
            "election_year": int(election_year),
            "turn": int(turn),
            "uf": str(uf).strip().upper(),
            "municipio_code": int(municipio_code),
            "zone_num": int(zone_num),
            "section_num": int(section_num),
            "urna_serial": self.urna_serial,
            "file_seq": int(self.file_seq),
            "raw_timestamp": self.raw_timestamp,
            "has_timestamp_regression": bool(self.has_timestamp_regression),
            "application": self.application,
            "log_level": self.log_level,
            "event_code": self.event_code,
            "biometric_attempt_num": self.biometric_attempt_num,
        }


def decode_log_line(raw_line: bytes | str) -> str:
    """Decodifica uma linha de log de bytes para str tentando UTF-8 estrito com fallback Latin-1."""
    if isinstance(raw_line, str):
        return raw_line.rstrip("\r\n")
    try:
        decoded = raw_line.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        decoded = raw_line.decode("latin1")
    return decoded.rstrip("\r\n")


def _parse_timestamp(ts_str: str) -> datetime | None:
    cleaned = ts_str.strip().replace(",", ".")
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _strip_mac_and_extract_message(tail_fields: list[str]) -> str | None:
    """Remove o código MAC hexadecimal final e retorna apenas o corpo da mensagem."""
    if not tail_fields:
        return None

    if len(tail_fields) >= 2 and _HEX_MAC_RE.fullmatch(tail_fields[-1].strip()):
        msg_parts = tail_fields[:-1]
    else:
        # Caso o MAC não esteja separado por tab ou haja apenas um campo final
        msg_parts = tail_fields

    message = " ".join(part.strip() for part in msg_parts if part.strip()).strip()
    if not message:
        return None
    return message


def _build_malformed_event(
    *,
    file_seq: int,
    default_urna_serial: str = "UNKNOWN",
    malformed_code: str = MALFORMED_LINE_CODE,
) -> ParsedLogEvent:
    return ParsedLogEvent(
        file_seq=file_seq,
        raw_timestamp=None,
        has_timestamp_regression=False,
        urna_serial=default_urna_serial,
        application="UNKNOWN",
        log_level="UNKNOWN",
        event_code=malformed_code,
        biometric_attempt_num=None,
    )


def parse_log_line(
    raw_line: bytes | str,
    *,
    file_seq: int = 1,
    previous_valid_timestamp: datetime | None = None,
    default_urna_serial: str = "UNKNOWN",
    catalog: EventCatalog | None = None,
) -> ParsedLogEvent:
    """Realiza o parsing estrutural e classificação semântica de uma única linha de log.

    Suporta:
    - Formato tabulado de 7 campos: DD/MM/YYYY \\t HH:MM:SS \\t LEVEL \\t SERIAL \\t APP \\t MSG \\t MAC
    - Formato tabulado de 6 campos: DD/MM/YYYY HH:MM:SS \\t LEVEL \\t SERIAL \\t APP \\t MSG \\t MAC
    Descarta imediatamente o mac_code e o texto livre da mensagem após a classificação.
    """  # noqa: E501
    if file_seq < 1:
        raise ValueError(f"file_seq deve ser >= 1 (recebido: {file_seq}).")

    malformed_code = catalog.malformed_event_code if catalog is not None else MALFORMED_LINE_CODE
    line_text = decode_log_line(raw_line)
    if not line_text.strip():
        return _build_malformed_event(
            file_seq=file_seq,
            default_urna_serial=default_urna_serial,
            malformed_code=malformed_code,
        )

    parts = line_text.split("\t")
    if len(parts) < 5:
        return _build_malformed_event(
            file_seq=file_seq,
            default_urna_serial=default_urna_serial,
            malformed_code=malformed_code,
        )

    first = parts[0].strip()
    second = parts[1].strip()

    if _DATE_ONLY_RE.fullmatch(first) and _TIME_ONLY_RE.fullmatch(second):
        if len(parts) < 5:
            return _build_malformed_event(
                file_seq=file_seq,
                default_urna_serial=default_urna_serial,
                malformed_code=malformed_code,
            )
        raw_ts = _parse_timestamp(f"{first} {second}")
        log_level = parts[2].strip().upper()
        urna_serial = parts[3].strip()
        candidate_app = parts[4].strip()
        if len(parts) >= 6 and " " not in candidate_app and len(candidate_app) <= 24:
            application = candidate_app
            tail_fields = parts[5:]
        else:
            application = "SYSTEM"
            tail_fields = parts[4:]
    else:
        raw_ts = _parse_timestamp(first)
        log_level = parts[1].strip().upper()
        urna_serial = parts[2].strip()
        candidate_app = parts[3].strip()
        if len(parts) >= 5 and " " not in candidate_app and len(candidate_app) <= 24:
            application = candidate_app
            tail_fields = parts[4:]
        else:
            application = "SYSTEM"
            tail_fields = parts[3:]

    if (
        raw_ts is None
        or log_level not in _KNOWN_LEVELS
        or not urna_serial
        or not application
    ):
        return _build_malformed_event(
            file_seq=file_seq,
            default_urna_serial=default_urna_serial,
            malformed_code=malformed_code,
        )

    ephemeral_message = _strip_mac_and_extract_message(tail_fields)
    if ephemeral_message is None:
        return _build_malformed_event(
            file_seq=file_seq,
            default_urna_serial=urna_serial or default_urna_serial,
            malformed_code=malformed_code,
        )

    has_regression = (
        previous_valid_timestamp is not None and raw_ts < previous_valid_timestamp
    )
    classification = classify_log_message(
        ephemeral_message,
        application=application,
        catalog=catalog,
    )

    return ParsedLogEvent(
        file_seq=file_seq,
        raw_timestamp=raw_ts,
        has_timestamp_regression=has_regression,
        urna_serial=urna_serial,
        application=application,
        log_level=log_level,
        event_code=classification.event_code,
        biometric_attempt_num=classification.biometric_attempt_num,
    )


def iter_parsed_log_lines(
    lines: Iterable[bytes | str],
    *,
    start_seq: int = 1,
    initial_last_timestamp: datetime | None = None,
    default_urna_serial: str = "UNKNOWN",
    catalog: EventCatalog | None = None,
) -> Iterator[ParsedLogEvent]:
    """Itera sobre uma sequência de linhas preservando file_seq monotônico e regressão temporal."""
    if start_seq < 1:
        raise ValueError(f"start_seq deve ser >= 1 (recebido: {start_seq}).")

    current_seq = start_seq
    last_valid_ts = initial_last_timestamp

    for raw_line in lines:
        event = parse_log_line(
            raw_line,
            file_seq=current_seq,
            previous_valid_timestamp=last_valid_ts,
            default_urna_serial=default_urna_serial,
            catalog=catalog,
        )
        if event.raw_timestamp is not None:
            last_valid_ts = event.raw_timestamp
        yield event
        current_seq += 1


def parse_log_lines(
    lines: Iterable[bytes | str],
    *,
    start_seq: int = 1,
    initial_last_timestamp: datetime | None = None,
    default_urna_serial: str = "UNKNOWN",
    catalog: EventCatalog | None = None,
) -> list[ParsedLogEvent]:
    """Processa uma coleção de linhas de log retornando a lista ordenada por file_seq."""
    return list(
        iter_parsed_log_lines(
            lines,
            start_seq=start_seq,
            initial_last_timestamp=initial_last_timestamp,
            default_urna_serial=default_urna_serial,
            catalog=catalog,
        )
    )
