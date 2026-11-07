"""Golden test sintético ponta a ponta do pipeline .jez -> fact_urna_event Parquet ZSTD."""

from __future__ import annotations

import io
import json
from pathlib import Path

import polars as pl
import py7zr
import pyarrow.parquet as pq

from tse_analysis.config import ExecutionConfig
from tse_analysis.logs.jez_reader import SectionTurnContext, extract_jez_events
from tse_analysis.logs.materializer import (
    FACT_URNA_EVENT_ARROW_SCHEMA,
    FACT_URNA_EVENT_POLARS_SCHEMA,
    events_to_polars,
    events_to_pyarrow,
    process_uf_staging_batch,
    write_fact_urna_event_partition,
)


def _create_golden_7z_jez_bytes(
    *,
    pii_cpf: str,
    pii_titulo: str,
    pii_mesario: str,
    secret_mac: str,
) -> bytes:
    logd_rotated_1 = (
        f"04/10/2026\t07:00:00\tINFO\t55443322\tscue\t"
        f"Início das operações do logd\t{secret_mac}\r\n"
        f"04/10/2026\t07:30:00\tINFO\t55443322\tVOTA\t"
        f"Emissão da Zerésima\t{secret_mac}\r\n"
        f"04/10/2026\t08:00:00\tINFO\t55443322\tVOTA\t"
        f"Urna pronta para receber votos\t{secret_mac}\r\n"
    ).encode("latin1")

    logd_current = (
        f"04/10/2026\t08:01:10\tINFO\t55443322\tVOTA\tEleitor foi habilitado\t{secret_mac}\r\n"
        f"04/10/2026\t08:01:15\tINFO\t55443322\tVOTA\t"
        f"Tentativa de reconhecimento biométrico 1\t{secret_mac}\r\n"
        f"04/10/2026\t08:01:18\tWARN\t55443322\tVOTA\tDigital não reconhecida\t{secret_mac}\r\n"
        f"04/10/2026\t08:01:25\tINFO\t55443322\tVOTA\t"
        f"Tentativa de reconhecimento biométrico 2\t{secret_mac}\r\n"
        f"04/10/2026\t08:01:28\tINFO\t55443322\tVOTA\tBiometria reconhecida\t{secret_mac}\r\n"
        f"04/10/2026\t08:02:13\tWARN\t55443322\tVOTA\tInatividade de 45 segundos\t{secret_mac}\r\n"
        f"04/10/2026\t08:02:20\tWARN\t55443322\tVOTA\tTecla indevida pressionada\t{secret_mac}\r\n"
        # Linha com regressão de relógio (08:01:59 < 08:02:20)
        f"04/10/2026\t08:01:59\tINFO\t55443322\tVOTA\t"
        f"Voto confirmado para o cargo\t{secret_mac}\r\n"
        f"04/10/2026\t08:02:35\tINFO\t55443322\tVOTA\t"
        f"O voto do eleitor foi computado\t{secret_mac}\r\n"
        # Linha fora da allowlist contendo PII simulado (CPF, título, mesário)
        f"04/10/2026\t08:03:00\tINFO\t55443322\tVOTA\t"
        f"Diagnóstico interno CPF {pii_cpf} Titulo {pii_titulo} "
        f"Mesario {pii_mesario}\t{secret_mac}\r\n"
        f"04/10/2026\t17:00:00\tINFO\t55443322\tVOTA\tEncerramento da votação\t{secret_mac}\r\n"
    ).encode("latin1")

    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, mode="w") as archive:
        archive.writestr(logd_current, "logd.dat")
        archive.writestr(logd_rotated_1, "logd.dat.1")
    return buf.getvalue()


def test_end_to_end_golden_jez_to_fact_urna_event_parquet_zero_pii(tmp_path: Path) -> None:
    """Golden test: .jez 7z rotacionado -> fact_urna_event Parquet ZSTD sem PII/MAC."""
    pii_cpf = "98765432100"
    pii_titulo = "123456780199"
    pii_mesario = "MESARIO_SECRET_778899"
    secret_mac = "DEADBEEFCAFEBABE1234567890ABCDEF"

    jez_bytes = _create_golden_7z_jez_bytes(
        pii_cpf=pii_cpf,
        pii_titulo=pii_titulo,
        pii_mesario=pii_mesario,
        secret_mac=secret_mac,
    )

    section_ctx = SectionTurnContext(
        election_year=2026,
        turn=1,
        uf="SP",
        municipio_code=71072,
        zone_num=1,
        section_num=42,
    )
    extraction = extract_jez_events(
        jez_bytes,
        section_context=section_ctx,
        availability_status="AVAILABLE",
    )
    assert extraction.rotated_files_count == 1
    assert extraction.events is not None
    assert len(extraction.events) == 14

    df = events_to_polars([extraction])
    arrow_tbl = events_to_pyarrow([extraction])

    assert df.schema == FACT_URNA_EVENT_POLARS_SCHEMA
    assert arrow_tbl.schema.equals(FACT_URNA_EVENT_ARROW_SCHEMA)
    assert "message_text" not in df.columns
    assert "mac_code" not in df.columns

    # Valida monotonicidade de file_seq (1..14) e códigos canônicos
    assert df["file_seq"].to_list() == list(range(1, 15))
    assert df["event_code"].to_list() == [
        "LOGD_STARTED",
        "SECTION_OPENED",
        "SECTION_OPENED",
        "VOTER_ENABLED",
        "BIOMETRIC_READ_ATTEMPT",
        "BIOMETRIC_NOT_RECOGNIZED",
        "BIOMETRIC_READ_ATTEMPT",
        "BIOMETRIC_RECOGNIZED",
        "INACTIVITY_TIMEOUT_45S",
        "INVALID_KEY_PRESSED",
        "CARGO_VOTE_RECORDED",
        "VOTER_VOTE_COMPUTED",
        "UNKNOWN_EVENT",
        "SECTION_CLOSED",
    ]
    assert df["biometric_attempt_num"].to_list() == [
        None,
        None,
        None,
        None,
        1,
        None,
        2,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ]

    # Valida detecção exata da regressão de relógio no file_seq == 11 sem reordenação
    regressions = [
        row["file_seq"]
        for row in df.iter_rows(named=True)
        if row["has_timestamp_regression"]
    ]
    assert regressions == [11]

    # Persiste em Parquet ZSTD particionado em election_year=2026/turn=1/uf=SP/
    cfg = ExecutionConfig(
        election_year=2026,
        turn=1,
        uf="SP",
        data_dir=tmp_path / "data",
    )
    parquet_path = write_fact_urna_event_partition(df, config=cfg)
    assert parquet_path.exists()
    assert "election_year=2026/turn=1/uf=SP" in parquet_path.as_posix()

    # Inspeciona metadados e conteúdo do Parquet gerado e faz varredura binária/textual contra PII
    parquet_meta = pq.read_metadata(parquet_path)
    assert parquet_meta.num_rows == 14
    assert parquet_meta.row_group(0).column(0).compression.upper() == "ZSTD"

    reloaded_df = pl.read_parquet(parquet_path)
    assert reloaded_df.schema == FACT_URNA_EVENT_POLARS_SCHEMA

    raw_parquet_bytes = parquet_path.read_bytes()
    json_dump = json.dumps(reloaded_df.to_dicts(), default=str)
    for forbidden_secret in (
        pii_cpf,
        pii_titulo,
        pii_mesario,
        secret_mac,
        "Diagnóstico interno",
        "Eleitor foi habilitado",
    ):
        assert forbidden_secret not in json_dump
        assert forbidden_secret.encode("utf-8") not in raw_parquet_bytes
        assert forbidden_secret.encode("latin1") not in raw_parquet_bytes


def test_process_uf_staging_batch_cleans_ephemeral_staging_and_updates_manifest(
    tmp_path: Path,
) -> None:
    """Valida execução em batch por UF com limpeza de staging efêmero e checkpoint manifest."""
    data_dir = tmp_path / "data"
    cfg_ac = ExecutionConfig(election_year=2026, turn=1, uf="AC", data_dir=data_dir)
    staging_ac = data_dir / "staging" / cfg_ac.partition_path
    staging_ac.mkdir(parents=True, exist_ok=True)

    jez_bytes = _create_golden_7z_jez_bytes(
        pii_cpf="11122233344",
        pii_titulo="555666777888",
        pii_mesario="MESARIO_001",
        secret_mac="ABCDEF0011223344",
    )
    (staging_ac / "o00407-0139200010010.jez").write_bytes(jez_bytes)

    report = process_uf_staging_batch(config=cfg_ac, cleanup_staging=True)
    assert report.availability_status == "AVAILABLE"
    assert report.packages_processed == 1
    assert report.events_count == 14
    assert report.parquet_path is not None and report.parquet_path.exists()
    assert report.staging_cleaned is True
    assert not staging_ac.exists()

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    ac_entry = manifest["fact_urna_event"]["election_year=2026/turn=1/uf=AC"]
    assert ac_entry["availability_status"] == "AVAILABLE"
    assert ac_entry["events_count"] == 14
    assert ac_entry["municipio_code" if "municipio_code" in ac_entry else "uf"] == "AC"

    # Testa UF sem artefatos .jez -> UNAVAILABLE explícito e events_count = None
    cfg_rr = ExecutionConfig(election_year=2026, turn=1, uf="RR", data_dir=data_dir)
    report_rr = process_uf_staging_batch(config=cfg_rr, cleanup_staging=True)
    assert report_rr.availability_status == "UNAVAILABLE"
    assert report_rr.events_count is None
    assert report_rr.parquet_path is None
