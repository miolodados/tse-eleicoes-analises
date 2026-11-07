"""Testes unitários do extrator em memória/streaming de pacotes .jez (jez_reader.py)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import py7zr

from tse_analysis.logs.jez_reader import (
    SEVEN_ZIP_MAGIC,
    ZIP_MAGIC,
    SectionTurnContext,
    detect_jez_container_format,
    extract_jez_events,
    extract_section_bundle_events,
    read_jez_log_lines,
    sort_log_member_names,
)


def _build_7z_jez_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, mode="w") as archive:
        for filename, content in members.items():
            archive.writestr(content, filename)
    return buf.getvalue()


def _build_zip_jez_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, content in members.items():
            zf.writestr(filename, content)
    return buf.getvalue()


def test_sort_log_member_names_orders_oldest_rotated_to_current_logd() -> None:
    """Valida ordenação determinística: logd.dat.2 -> logd.dat.1 -> logd.dat."""
    unordered = ["logd.dat", "readme.txt", "logd.dat.1", "logd.dat.2"]
    ordered = sort_log_member_names(unordered)
    assert ordered == ("logd.dat.2", "logd.dat.1", "logd.dat")


def test_read_7z_jez_with_rotated_segments_in_memory() -> None:
    """Cenário: .jez 7z com logd.dat.2 (2 linhas), logd.dat.1 (3 linhas) e logd.dat (4 linhas)."""
    logd_2 = (
        "04/10/2026\t07:00:01\tINFO\t11112222\tscue\tInício das operações do logd\tAAA111\r\n"
        "04/10/2026\t07:30:00\tINFO\t11112222\tVOTA\tEmissão da Zerésima\tAAA112\r\n"
    ).encode("latin1")
    logd_1 = (
        "04/10/2026\t08:00:00\tINFO\t11112222\tVOTA\tUrna pronta para receber votos\tAAA113\r\n"
        "04/10/2026\t08:01:00\tINFO\t11112222\tVOTA\tEleitor foi habilitado\tAAA114\r\n"
        "04/10/2026\t08:01:05\tINFO\t11112222\tVOTA\t"
        "Tentativa de reconhecimento biométrico 1\tAAA115\r\n"
    ).encode("latin1")
    logd_current = (
        "04/10/2026\t08:01:08\tINFO\t11112222\tVOTA\tBiometria reconhecida\tAAA116\r\n"
        "04/10/2026\t08:01:25\tINFO\t11112222\tVOTA\tVoto confirmado para o cargo\tAAA117\r\n"
        "04/10/2026\t08:01:40\tINFO\t11112222\tVOTA\tO voto do eleitor foi computado\tAAA118\r\n"
        "04/10/2026\t17:00:00\tINFO\t11112222\tVOTA\tEncerramento da votação\tAAA119\r\n"
    ).encode("latin1")

    jez_bytes = _build_7z_jez_bytes(
        {
            "logd.dat": logd_current,
            "logd.dat.1": logd_1,
            "logd.dat.2": logd_2,
        }
    )
    assert jez_bytes.startswith(SEVEN_ZIP_MAGIC)
    assert detect_jez_container_format(jez_bytes) == "7z"

    stream_lines = list(read_jez_log_lines(jez_bytes))
    assert len(stream_lines) == 9
    assert [line.file_seq for line in stream_lines] == list(range(1, 10))
    assert stream_lines[0].source_member == "logd.dat.2"
    assert stream_lines[2].source_member == "logd.dat.1"
    assert stream_lines[5].source_member == "logd.dat"

    ctx = SectionTurnContext(
        election_year=2026,
        turn=1,
        uf="SP",
        municipio_code=71072,
        zone_num=1,
        section_num=101,
    )
    result = extract_jez_events(jez_bytes, section_context=ctx)
    assert result.availability_status == "LOCAL_FIXTURE"
    assert result.container_format == "7z"
    assert result.rotated_files_count == 2
    assert result.observed_urna_serials == ("11112222",)
    assert result.has_contingency_indicator is False
    assert result.events is not None
    assert len(result.events) == 9
    assert [e.file_seq for e in result.events] == list(range(1, 10))
    assert [e.event_code for e in result.events] == [
        "LOGD_STARTED",
        "SECTION_OPENED",
        "SECTION_OPENED",
        "VOTER_ENABLED",
        "BIOMETRIC_READ_ATTEMPT",
        "BIOMETRIC_RECOGNIZED",
        "CARGO_VOTE_RECORDED",
        "VOTER_VOTE_COMPUTED",
        "SECTION_CLOSED",
    ]


def test_read_zip_formatted_jez_in_memory() -> None:
    """Cenário: pacote .jez empacotado com assinatura ZIP contendo logd.dat."""
    logd_bytes = (
        b"04/10/2026\t08:00:00\tINFO\t99887766\tVOTA\tUrna pronta para receber votos\tABCDEF12\n"
        b"04/10/2026\t08:02:00\tINFO\t99887766\tVOTA\tEleitor foi habilitado\tABCDEF13\n"
    )
    zip_jez = _build_zip_jez_bytes({"logd.dat": logd_bytes})
    assert zip_jez.startswith(ZIP_MAGIC)
    assert detect_jez_container_format(zip_jez) == "zip"

    result = extract_jez_events(zip_jez)
    assert result.container_format == "zip"
    assert result.events is not None
    assert len(result.events) == 2
    assert result.events[0].event_code == "SECTION_OPENED"
    assert result.events[1].event_code == "VOTER_ENABLED"


def test_missing_jez_returns_explicit_unavailable_and_none_events(
    tmp_path: Path,
    zip_totalizacao_without_jez: Path,
) -> None:
    """Garante que ausência física de .jez retorna UNAVAILABLE e events=None."""
    non_existent = tmp_path / "inexistente.jez"
    res_missing_file = extract_jez_events(non_existent)
    assert res_missing_file.availability_status == "UNAVAILABLE"
    assert res_missing_file.events is None
    assert res_missing_file.to_fact_records() == []

    res_bundle_no_jez = extract_section_bundle_events(zip_totalizacao_without_jez)
    assert res_bundle_no_jez.availability_status == "UNAVAILABLE"
    assert res_bundle_no_jez.events is None


def test_section_bundle_detects_contingency_multiple_urna_serials() -> None:
    """Detecta contingência quando pacote de seção contém múltiplos seriais ou múltiplos .jez."""
    jez_1 = _build_7z_jez_bytes(
        {
            "logd.dat": (
                "04/10/2026\t08:00:00\tINFO\t10000001\tVOTA\t"
                "Urna pronta para receber votos\tAA1122\n"
                "04/10/2026\t09:30:00\tWARN\t10000001\tVOTA\tVotação suspensa\tAA1123\n"
            ).encode("latin1")
        }
    )
    jez_2 = _build_7z_jez_bytes(
        {
            "logd.dat": (
                "04/10/2026\t09:45:00\tINFO\t20000002\tGAP\tSubstituição de urna\tBB1122\n"
                "04/10/2026\t09:50:00\tINFO\t20000002\tVOTA\tVotação retomada\tBB1123\n"
            ).encode("latin1")
        }
    )

    bundle_buf = io.BytesIO()
    with zipfile.ZipFile(bundle_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o00407-0139200010010.jez", jez_1)
        zf.writestr("o00407-0139200010010_contingencia.jez", jez_2)

    result = extract_section_bundle_events(
        bundle_buf.getvalue(),
        section_context=SectionTurnContext(election_year=2026, turn=1, uf="AC"),
    )
    assert result.availability_status == "LOCAL_FIXTURE"
    assert result.municipio_code == 1392
    assert result.zone_num == 1
    assert result.section_num == 10
    assert result.jez_files_count == 2
    assert result.observed_urna_serials == ("10000001", "20000002")
    assert result.has_contingency_indicator is True
    assert result.events is not None
    assert len(result.events) == 4
    # Preserva file_seq por arquivo .jez processado e urna_serial específico de cada linha
    assert [(e.urna_serial, e.file_seq, e.event_code) for e in result.events] == [
        ("10000001", 1, "SECTION_OPENED"),
        ("10000001", 2, "VOTING_SUSPENDED"),
        ("20000002", 1, "CONTINGENCY_EVENT"),
        ("20000002", 2, "VOTING_RESUMED"),
    ]
