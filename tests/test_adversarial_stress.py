"""Testes adversariais e de estresse para o pipeline de logs da urna (Fase 1)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import py7zr
import pytest

from tse_analysis.config import ExecutionConfig
from tse_analysis.logs.event_catalog import UNKNOWN_EVENT_CODE, classify_log_message
from tse_analysis.logs.jez_reader import (
    SectionTurnContext,
    extract_jez_events,
    extract_section_bundle_events,
)
from tse_analysis.logs.line_parser import parse_log_line, parse_log_lines
from tse_analysis.logs.materializer import (
    FACT_URNA_EVENT_ARROW_SCHEMA,
    FACT_URNA_EVENT_POLARS_SCHEMA,
    events_to_polars,
     events_to_pyarrow,
    process_uf_staging_batch,
)


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_attempt"),
    [
        ("Solicita digital. Tentativa [1]", "BIOMETRIC_READ_ATTEMPT", 1),
        ("Solicita digital. Tentativa 2", "BIOMETRIC_READ_ATTEMPT", 2),
        ("Solicitando digital: tentativa (4)", "BIOMETRIC_READ_ATTEMPT", 4),
        ("Número de tentativas de reconhecimento do dedo: 3", "BIOMETRIC_READ_ATTEMPT", 3),
        ("Número de tentativas de reconhecimento do dedo [2]", "BIOMETRIC_READ_ATTEMPT", 2),
        ("Eleitor sem atividade por 45 segundos", "INACTIVITY_TIMEOUT_45S", None),
        ("Sem atividade por 45s", "INACTIVITY_TIMEOUT_45S", None),
        ("Voto confirmado para [Deputado Federal]", "CARGO_VOTE_RECORDED", None),
        ("Eleitor habilitado sem biometria", "MANUAL_ENABLE_PATH", None),
        ("Código de habilitação digitado pelo mesário", "MANUAL_ENABLE_PATH", None),
    ],
)
def test_adversarial_official_tse_guide_exact_messages(
    message: str,
    expected_code: str,
    expected_attempt: int | None,
) -> None:
    """Garante reconhecimento exato das mensagens literais do guia técnico do TSE."""
    res = classify_log_message(message, application="VOTA")
    assert res.event_code == expected_code
    assert res.biometric_attempt_num == expected_attempt


@pytest.mark.parametrize(
    "poll_worker_or_test_msg",
    [
        "Solicitação de digital do mesário",
        "Tentativa de leitura biométrica 1 do mesário",
        "Biometria do mesário reconhecida",
        "Digital do presidente não reconhecida",
        "Teste de sensor biométrico reconhecido",
        "Autoteste de biometria reconhecida",
    ],
)
def test_adversarial_poll_worker_and_sensor_test_never_contaminate_voter_biometrics(
    poll_worker_or_test_msg: str,
) -> None:
    """Impede que biometria de mesário/presidente ou autoteste contamine métricas do eleitor."""
    res = classify_log_message(poll_worker_or_test_msg, application="VOTA")
    assert res.event_code not in {
        "BIOMETRIC_READ_ATTEMPT",
        "BIOMETRIC_RECOGNIZED",
        "BIOMETRIC_NOT_RECOGNIZED",
        "NO_BIOMETRIC_REGISTERED",
    }
    assert res.biometric_attempt_num is None


def test_adversarial_out_of_range_biometric_attempt_clamped_to_none() -> None:
    """Garante que números de tentativa fora do intervalo Int8 (1..127) não causem overflow."""
    res_zero = classify_log_message("Solicita digital. Tentativa 0", application="VOTA")
    assert res_zero.event_code == "BIOMETRIC_READ_ATTEMPT"
    assert res_zero.biometric_attempt_num is None

    res_overflow = classify_log_message("Solicita digital. Tentativa 250", application="VOTA")
    assert res_overflow.event_code == "BIOMETRIC_READ_ATTEMPT"
    assert res_overflow.biometric_attempt_num is None


def test_adversarial_millisecond_timestamps_and_5_field_system_lines() -> None:
    """Suporta timestamps com milissegundos (.fff ou ,fff) e linhas de daemon sem coluna APP."""
    line_ms = (
        "04/10/2026\t08:01:10,456\tINFO\t12345678\tVOTA\t"
        "Solicita digital. Tentativa [2]\tA1B2C3D4E5F60718"
    )
    ev_ms = parse_log_line(line_ms, file_seq=1)
    assert ev_ms.event_code == "BIOMETRIC_READ_ATTEMPT"
    assert ev_ms.biometric_attempt_num == 2
    assert ev_ms.raw_timestamp is not None
    assert ev_ms.raw_timestamp.microsecond == 456000

    # Linha de 5 campos (sem coluna APP explícita entre SERIAL e MSG)
    line_no_app = (
        "04/10/2026\t07:00:05.120\tINFO\t12345678\t"
        "Início das operações do logd\tA1B2C3D4E5F60718"
    )
    ev_sys = parse_log_line(line_no_app, file_seq=2)
    assert ev_sys.application == "SYSTEM"
    assert ev_sys.event_code == "LOGD_STARTED"


def test_adversarial_nested_rotated_archives_inside_jez() -> None:
    """Testa pacote .jez contendo arquivos rotacionados aninhados (.jez/.zip internos)."""
    inner_rot_2_buf = io.BytesIO()
    with zipfile.ZipFile(inner_rot_2_buf, mode="w") as zf:
        zf.writestr(
            "logd.dat",
            (
                b"04/10/2026\t07:00:00\tINFO\t99001122\tscue\t"
                b"In\xedcio das opera\xe7\xf5es do logd\tAA112233\n"
            ),
        )

    inner_rot_1_buf = io.BytesIO()
    with py7zr.SevenZipFile(inner_rot_1_buf, mode="w") as sz:
        sz.writestr(
            (
                b"04/10/2026\t08:00:00\tINFO\t99001122\tVOTA\t"
                b"Urna pronta para receber votos\tAA112234\n"
            ),
            "logd.dat",
        )

    outer_jez_buf = io.BytesIO()
    with py7zr.SevenZipFile(outer_jez_buf, mode="w") as outer:
        outer.writestr(
            b"04/10/2026\t08:05:00\tINFO\t99001122\tVOTA\tEleitor foi habilitado\tAA112235\n",
            "logd.dat",
        )
        outer.writestr(inner_rot_1_buf.getvalue(), "logd.dat.1.jez")
        outer.writestr(inner_rot_2_buf.getvalue(), "logd.dat.2.zip")

    res = extract_jez_events(outer_jez_buf.getvalue())
    assert res.events is not None
    assert len(res.events) == 3
    assert [e.file_seq for e in res.events] == [1, 2, 3]
    assert [e.event_code for e in res.events] == [
        "LOGD_STARTED",
        "SECTION_OPENED",
        "VOTER_ENABLED",
    ]


def test_adversarial_contingency_clock_offset_per_serial_and_bundle_monotonic_seq() -> None:
    """Garante isolamento de relógio por urna_serial e file_seq monotônico em contingência."""
    jez_1_buf = io.BytesIO()
    with zipfile.ZipFile(jez_1_buf, mode="w") as zf:
        zf.writestr(
            "logd.dat",
            (
                "04/10/2026\t09:30:00\tINFO\tURNA_A\tVOTA\tEleitor foi habilitado\tAABBCCDD\n"
                "04/10/2026\t09:31:00\tWARN\tURNA_A\tVOTA\tVotação suspensa\tAABBCCDE\n"
            ).encode(),
        )

    # Urna B substituta inicia em 09:30:20 (< 09:31:00 da Urna A), seguido de recuo real 09:30:10
    jez_2_buf = io.BytesIO()
    with zipfile.ZipFile(jez_2_buf, mode="w") as zf:
        zf.writestr(
            "logd.dat",
            (
                "04/10/2026\t09:30:20\tINFO\tURNA_B\tGAP\tModo de contingência\tAABBCCDF\n"
                "04/10/2026\t09:30:10\tINFO\tURNA_B\tVOTA\tVotação retomada\tAABBCCE0\n"
            ).encode(),
        )

    bundle_buf = io.BytesIO()
    with zipfile.ZipFile(bundle_buf, mode="w") as bundle:
        bundle.writestr("o00407-7107200010101-a.jez", jez_1_buf.getvalue())
        bundle.writestr("o00407-7107200010101-b.jez", jez_2_buf.getvalue())

    res = extract_section_bundle_events(bundle_buf.getvalue())
    assert res.events is not None
    assert len(res.events) == 4
    # file_seq monotônico por urna_serial (URNA_A: 1, 2; URNA_B: 1, 2)
    assert [(e.urna_serial, e.file_seq) for e in res.events] == [
        ("URNA_A", 1),
        ("URNA_A", 2),
        ("URNA_B", 1),
        ("URNA_B", 2),
    ]
    # O primeiro evento da URNA_B NÃO deve ter regressão contra a URNA_A;
    # apenas o segundo evento da URNA_B (09:30:10 < 09:30:20) tem regressão!
    assert [e.has_timestamp_regression for e in res.events] == [False, False, False, True]


def test_adversarial_corrupted_archives_handled_gracefully(tmp_path: Path) -> None:
    """Garante que arquivos .jez ou .zip truncados/corrompidos retornam CORRUPTED_ARCHIVE."""
    corrupted_7z = b"7z\xbc\xaf\x27\x1cCORRUPTED_TRUNCATED_PAYLOAD"
    res_7z = extract_jez_events(corrupted_7z)
    assert res_7z.availability_status == "CORRUPTED_ARCHIVE"
    assert res_7z.events is None

    corrupted_zip = b"PK\x03\x04CORRUPTED_ZIP_HEADER"
    res_bundle = extract_section_bundle_events(corrupted_zip)
    assert res_bundle.availability_status == "CORRUPTED_ARCHIVE"
    assert res_bundle.events is None


def test_adversarial_stress_10k_lines_and_duplicate_staging_deduplication(
    tmp_path: Path,
) -> None:
    """Teste de estresse com 10.000 linhas, lixo binário e deduplicação de seção no batch UF."""
    lines: list[str] = []
    for i in range(1, 10001):
        sec = i % 60
        minute = (i // 60) % 60
        hour = 8 + ((i // 3600) % 9)
        if i % 500 == 0:
            lines.append(f"LINHA_CORROMPIDA_SEM_TABS_{i}\x00\xff")
        elif i % 100 == 0:
            lines.append(
                f"04/10/2026\t{hour:02d}:{minute:02d}:{sec:02d}\tINFO\t88889999\tVOTA\t"
                f"Mensagem desconhecida CPF 11122233344 Titulo 999888777666\tABCDEF123456"
            )
        elif i % 5 == 0:
            attempt = (i % 4) + 1
            lines.append(
                f"04/10/2026\t{hour:02d}:{minute:02d}:{sec:02d}\tINFO\t88889999\tVOTA\t"
                f"Solicita digital. Tentativa [{attempt}]\tABCDEF123456"
            )
        else:
            lines.append(
                f"04/10/2026\t{hour:02d}:{minute:02d}:{sec:02d}\tINFO\t88889999\tVOTA\t"
                f"O voto do eleitor foi computado\tABCDEF123456"
            )

    parsed = parse_log_lines(lines)
    assert len(parsed) == 10000
    assert parsed[0].file_seq == 1
    assert parsed[-1].file_seq == 10000

    ctx = SectionTurnContext(
        election_year=2026,
        turn=1,
        uf="SP",
        municipio_code=71072,
        zone_num=1,
        section_num=202,
    )
    df = events_to_polars(parsed, section_context=ctx)
    arrow_tbl = events_to_pyarrow(parsed, section_context=ctx)
    assert df.height == 10000
    assert df.schema == FACT_URNA_EVENT_POLARS_SCHEMA
    assert arrow_tbl.schema.equals(FACT_URNA_EVENT_ARROW_SCHEMA)
    assert df.filter(df["event_code"] == UNKNOWN_EVENT_CODE).height == 80
    assert df.filter(df["event_code"] == "MALFORMED_LINE").height == 20

    # Testa deduplicação quando staging possui tanto o .jez solto quanto o .zip da mesma seção
    cfg = ExecutionConfig(election_year=2026, turn=1, uf="SP", data_dir=tmp_path)
    staging_dir = tmp_path / "staging" / cfg.partition_path
    staging_dir.mkdir(parents=True, exist_ok=True)

    small_jez_buf = io.BytesIO()
    with zipfile.ZipFile(small_jez_buf, mode="w") as zf:
        zf.writestr(
            "logd.dat",
            b"04/10/2026\t08:00:00\tINFO\t88889999\tVOTA\tEleitor foi habilitado\tABCDEF12\n",
        )
    jez_bytes = small_jez_buf.getvalue()

    # Grava .jez avulso e .zip contendo o mesmo .jez para a seção 71072-0001-0202
    (staging_dir / "o00407-7107200010202.jez").write_bytes(jez_bytes)
    with zipfile.ZipFile(staging_dir / "bundle_secao.zip", mode="w") as zf:
        zf.writestr("o00407-7107200010202.jez", jez_bytes)

    report = process_uf_staging_batch(config=cfg)
    assert report.packages_processed == 1
    assert report.events_count == 1
    assert report.staging_cleaned is True
