"""Testes unitários do parser estrutural linha-a-linha dos logs da urna (line_parser.py)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from tse_analysis.logs.event_catalog import MALFORMED_LINE_CODE
from tse_analysis.logs.line_parser import (
    decode_log_line,
    parse_log_line,
    parse_log_lines,
)


def test_parse_standard_tabulated_vota_line_7_fields_and_discard_mac() -> None:
    """Valida parsing de linha tabulada de 7 campos do VOTA e descarte total do mac_code."""
    raw = (
        "04/10/2026\t08:00:05\tINFO\t67890123\tVOTA\t"
        "Eleitor foi habilitado\t9A8B7C6D5E4F3A2B\r\n"
    )
    event = parse_log_line(raw, file_seq=10)
    assert event.file_seq == 10
    assert event.raw_timestamp == datetime(2026, 10, 4, 8, 0, 5)
    assert event.has_timestamp_regression is False
    assert event.log_level == "INFO"
    assert event.urna_serial == "67890123"
    assert event.application == "VOTA"
    assert event.event_code == "VOTER_ENABLED"
    assert event.biometric_attempt_num is None

    serialized = str(asdict(event))
    assert "9A8B7C6D5E4F3A2B" not in serialized
    assert "Eleitor foi habilitado" not in serialized


def test_parse_standard_tabulated_line_6_fields_combined_timestamp() -> None:
    """Valida parsing de linha tabulada de 6 campos (data e hora no primeiro campo)."""
    raw = (
        "04/10/2026 08:01:12\tINFO\t67890123\tVOTA\t"
        "Tentativa de reconhecimento biométrico 2\tA1B2C3D4E5F60718\n"
    )
    event = parse_log_line(raw, file_seq=11)
    assert event.file_seq == 11
    assert event.raw_timestamp == datetime(2026, 10, 4, 8, 1, 12)
    assert event.event_code == "BIOMETRIC_READ_ATTEMPT"
    assert event.biometric_attempt_num == 2
    assert "A1B2C3D4E5F60718" not in str(asdict(event))


def test_decode_and_parse_latin1_and_utf8_accented_lines() -> None:
    """Garante decodificação resiliente de acentuação tanto em ISO-8859-1 quanto em UTF-8."""
    latin1_bytes = (
        "04/10/2026\t07:00:00\tINFO\t67890123\tscue\t"
        "Início das operações do logd\t1122334455667788\r\n"
    ).encode("latin1")
    utf8_bytes = (
        "04/10/2026\t08:05:10\tWARN\t67890123\tVOTA\t"
        "Não há biometria cadastrada para o eleitor\t8877665544332211\n"
    ).encode()

    decoded_latin1 = decode_log_line(latin1_bytes)
    assert "Início das operações do logd" in decoded_latin1

    events = parse_log_lines([latin1_bytes, utf8_bytes])
    assert len(events) == 2
    assert events[0].event_code == "LOGD_STARTED"
    assert events[0].application == "scue"
    assert events[1].event_code == "NO_BIOMETRIC_REGISTERED"
    assert events[1].log_level == "WARN"


def test_timestamp_regression_detection_preserves_canonical_file_seq() -> None:
    """Valida detecção de regressão de relógio sem reordenar registros por raw_timestamp."""
    lines = [
        "04/10/2026\t09:15:30\tINFO\t67890123\tVOTA\tEleitor foi habilitado\tABCDEF0123456789",
        "04/10/2026\t09:14:55\tINFO\t67890123\tVOTA\tBiometria reconhecida\tABCDEF0123456780",
        (
            "04/10/2026\t09:15:10\tINFO\t67890123\tVOTA\t"
            "O voto do eleitor foi computado\tABCDEF0123456781"
        ),
    ]
    events = parse_log_lines(lines, start_seq=41)
    assert [e.file_seq for e in events] == [41, 42, 43]
    assert events[0].raw_timestamp == datetime(2026, 10, 4, 9, 15, 30)
    assert events[0].has_timestamp_regression is False

    assert events[1].raw_timestamp == datetime(2026, 10, 4, 9, 14, 55)
    assert events[1].has_timestamp_regression is True

    assert events[2].raw_timestamp == datetime(2026, 10, 4, 9, 15, 10)
    assert events[2].has_timestamp_regression is False


def test_malformed_line_handling_and_regression_across_null_timestamp() -> None:
    """Valida tratamento seguro de linha corrompida e comparação de timestamp após linha nula."""
    corrupted_secret = "LINHA_CORROMPIDA_COM_CPF_99988877766_TRUNCADA"
    lines = [
        "04/10/2026\t10:00:00\tINFO\t67890123\tVOTA\tEleitor foi habilitado\tABCDEF0123456789",
        corrupted_secret,
        "04/10/2026\t09:59:50\tWARN\t67890123\tGAP\tModo de contingência\tABCDEF0123456780",
    ]
    events = parse_log_lines(lines, start_seq=1)
    assert [e.file_seq for e in events] == [1, 2, 3]

    # Linha malformada (file_seq = 2)
    assert events[1].raw_timestamp is None
    assert events[1].has_timestamp_regression is False
    assert events[1].log_level == "UNKNOWN"
    assert events[1].application == "UNKNOWN"
    assert events[1].event_code == MALFORMED_LINE_CODE
    assert corrupted_secret not in str(asdict(events[1]))
    assert "99988877766" not in str(asdict(events[1]))

    # Linha seguinte (file_seq = 3) comparada contra o último timestamp válido (file_seq = 1)
    assert events[2].raw_timestamp == datetime(2026, 10, 4, 9, 59, 50)
    assert events[2].has_timestamp_regression is True
    assert events[2].event_code == "CONTINGENCY_EVENT"
