"""Testes automatizados para a ingestão incremental em batch de fact_urna_logs (Fase 2)."""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import py7zr
import pyarrow.parquet as pq
import pytest


def _load_notebook_03_namespace(repo_root: Path) -> dict[str, Any]:
    """Carrega as definições declarativas e funções das células 1 a 3 do notebook 03."""
    nb_path = (
        repo_root
        / "notebooks"
        / "03_ingest_urna_logs_batch"
        / "03_ingest_urna_logs_batch.ipynb"
    )
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [c for c in nb_data["cells"] if c.get("cell_type") == "code"]
    namespace: dict[str, Any] = {}
    for cell in code_cells[:3]:
        source_code = "".join(cell.get("source", []))
        exec(compile(source_code, str(nb_path), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def nb03_ns(repo_root: Path) -> dict[str, Any]:
    return _load_notebook_03_namespace(repo_root)


def _build_synthetic_7z_jez(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, mode="w") as archive:
        for fname, content in members.items():
            archive.writestr(content, fname)
    return buf.getvalue()


def _build_synthetic_zip_jez(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, content in members.items():
            zf.writestr(fname, content)
    return buf.getvalue()


def test_schema_15_columns_and_source_config_definitions(nb03_ns: dict[str, Any]) -> None:
    """Valida contrato estrito de 15 colunas de fact_urna_logs e leitura de configs/sources.yml."""
    expected_columns = [
        "election_year",
        "turn",
        "uf",
        "cd_pleito",
        "cd_municipio",
        "nr_zona",
        "nr_secao",
        "source_jez_file",
        "source_log_member",
        "file_seq",
        "raw_timestamp",
        "log_level",
        "urna_serial",
        "application",
        "message_text",
    ]
    assert nb03_ns["FACT_URNA_LOGS_COLUMNS"] == expected_columns
    assert list(nb03_ns["FACT_URNA_LOGS_SCHEMA"].keys()) == expected_columns
    assert nb03_ns["FACT_URNA_LOGS_ARROW_SCHEMA"].names == expected_columns
    assert len(expected_columns) == 15
    assert "mac_code" not in expected_columns
    assert "event_code" not in expected_columns

    assert nb03_ns["ELECTION_YEAR"] == 2026
    assert nb03_ns["TARGET_TURNS"] == [1, 2]
    assert len(nb03_ns["ALL_UFS"]) == 28
    assert nb03_ns["REQUIRED_SITUACAO"] == "Totalizado"
    assert "log-do-ecossistema.pdf" in nb03_ns["LOG_DOCS_URL"]


def test_central_directory_inspection_and_jez_metadata_extraction(
    nb03_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Valida inspeção do Central Directory e extração de metadados de entradas *-log.jez."""
    inspect_local = nb03_ns["inspect_local_zip_central_directory"]
    parse_meta = nb03_ns["parse_jez_entry_metadata"]

    meta = parse_meta("sub/o03220ac0101500020088-log.jez")
    assert meta is not None
    assert meta["source_jez_file"] == "o03220ac0101500020088-log.jez"
    assert meta["cd_pleito"] == 3220
    assert meta["uf"] == "AC"
    assert meta["cd_municipio"] == 1015
    assert meta["nr_zona"] == 2
    assert meta["nr_secao"] == 88

    assert parse_meta("o03220ac0101500020088.bu") is None
    assert parse_meta("leiame.pdf") is None

    zip_path = tmp_path / "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip"
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o03220ac0139200010010-log.jez", b"PK\x03\x04dummy")
        zf.writestr("o03220ac0101500020088-log.jez", b"7z\xbc\xaf\x27\x1cdummy")
        zf.writestr("o03220ac0101500020088.bu", b"bu-binary")
        zf.writestr("o03220ac0101500020088.rdv", b"rdv-binary")

    entries = inspect_local(zip_path)
    assert len(entries) == 2
    assert [e["source_jez_file"] for e in entries] == [
        "o03220ac0101500020088-log.jez",
        "o03220ac0139200010010-log.jez",
    ]


def test_in_memory_jez_extractor_7z_and_zip_and_rotated_ordering(
    nb03_ns: dict[str, Any],
) -> None:
    """Testa .jez sintéticos (7z/LZMA e ZIP), ordenação logd.dat.2 -> logd.dat.1 -> logd.dat."""
    detect_fmt = nb03_ns["detect_jez_container_format"]
    sort_rotated = nb03_ns["sort_rotated_log_members"]
    parse_jez_rows = nb03_ns["parse_jez_bytes_to_fact_rows"]

    unordered = ["logd.dat", "leiame.txt", "logd.dat.1", "logd.dat.2"]
    assert sort_rotated(unordered) == ["logd.dat.2", "logd.dat.1", "logd.dat"]

    logd_2 = (
        "04/10/2026 07:00:01\tINFO\t02263093\tLOGD\t"
        "Início das operações do logd\tAAA1111111111111\r\n"
        "04/10/2026 07:05:00\tINFO\t02263093\tSCUE\t"
        "Iniciando aplicação - 1º turno\tAAA2222222222222\r\n"
    ).encode("latin1")
    logd_1 = (
        "04/10/2026 08:00:00\tINFO\t02263093\tVOTA\t"
        "Urna pronta para receber votos\tBBB1111111111111\r\n"
        "04/10/2026 08:01:12\tALERTA\t02263093\tVOTA\t"
        "Mesário 014429582429 habilitou eleitor 98765432100\tBBB2222222222222\r\n"
    ).encode("latin1")
    logd_0 = (
        "04/10/2026 08:02:00\tINFO\t02263093\tVOTA\t"
        "Voto confirmado para [Governador]\tCCC1111111111111\n"
        "04/10/2026 17:00:00\tINFO\t02263093\tVOTA\t"
        "Encerramento da votação\tCCC2222222222222\n"
    ).encode()

    jez_7z = _build_synthetic_7z_jez(
        {"logd.dat": logd_0, "logd.dat.1": logd_1, "logd.dat.2": logd_2}
    )
    jez_zip = _build_synthetic_zip_jez(
        {"logd.dat": logd_0, "logd.dat.1": logd_1, "logd.dat.2": logd_2}
    )

    assert detect_fmt(jez_7z) == "7z"
    assert detect_fmt(jez_zip) == "zip"

    jez_meta = {
        "source_jez_file": "o03220ac0101500020088-log.jez",
        "cd_pleito": 3220,
        "uf": "AC",
        "cd_municipio": 1015,
        "nr_zona": 2,
        "nr_secao": 88,
    }

    for expected_fmt, payload in (("7z", jez_7z), ("zip", jez_zip)):
        rows, phys_lines, fmt, members = parse_jez_rows(
            payload, jez_meta, election_year=2026, turn=1
        )
        assert fmt == expected_fmt
        assert members == ["logd.dat.2", "logd.dat.1", "logd.dat"]
        assert phys_lines == 6
        assert len(rows) == 6
        assert [r["file_seq"] for r in rows] == [1, 2, 3, 4, 5, 6]
        assert [r["source_log_member"] for r in rows] == [
            "logd.dat.2",
            "logd.dat.2",
            "logd.dat.1",
            "logd.dat.1",
            "logd.dat",
            "logd.dat",
        ]
        # Verifica mascaramento <ID_REDACTED> de números de 5+ dígitos e omissão total do mac_code
        assert (
            rows[3]["message_text"]
            == "Mesário <ID_REDACTED> habilitou eleitor <ID_REDACTED>"
        )
        serialized = json.dumps(rows, ensure_ascii=False)
        assert "014429582429" not in serialized
        assert "98765432100" not in serialized
        assert "AAA1111111111111" not in serialized
        assert "BBB2222222222222" not in serialized
        assert "CCC2222222222222" not in serialized


def test_end_to_end_partition_reconciliation_staging_cleanup_manifest_and_storage_report(
    nb03_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Valida Parquet ZSTD, reconciliação física, limpeza de staging, manifest.json e disco."""
    ingest_partition = nb03_ns["ingest_uf_turn_partition"]
    compute_report = nb03_ns["compute_parquet_storage_report"]
    load_manifest = nb03_ns["load_manifest"]

    jez_1 = _build_synthetic_7z_jez(
        {
            "logd.dat.1": (
                "04/10/2026 07:00:00\tINFO\t02263093\tLOGD\t"
                "Início das operações do logd\t1111222233334444\n"
            ).encode("latin1"),
            "logd.dat": (
                "04/10/2026 08:00:00\tINFO\t02263093\tVOTA\t"
                "Eleitor 12345678901 habilitado\t5555666677778888\n"
                "04/10/2026 15:00:00\tINFO\t02263093\tVOTA\t"
                "Encerramento da votação\t9999AAAABBBBCCCC\n"
            ).encode("latin1"),
        }
    )
    jez_2 = _build_synthetic_zip_jez(
        {
            "logd.dat": (
                "04/10/2026 07:10:00\tINFO\t02269999\tSCUE\t"
                "Teste de seção 4 dígitos 1015 mantido e 5 dígitos 54321 mascarado\t"
                "DDDDEEEEFFFF0000\n"
                "04/10/2026 15:05:00\tINFO\t02269999\tVOTA\t"
                "Gerando arquivo de resultado [log.jez] + [Início]\t123456789ABCDEF0\n"
            ).encode(),
        }
    )

    staging_dir = tmp_path / "staging"
    exports_dir = tmp_path / "exports"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"

    part_staging = staging_dir / "election_year=2026" / "turn=1" / "uf=AC"
    part_staging.mkdir(parents=True, exist_ok=True)
    local_zip = part_staging / "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip"
    with zipfile.ZipFile(local_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o03220ac0101500020088-log.jez", jez_1)
        zf.writestr("o03220ac0139200010010-log.jez", jez_2)
        zf.writestr("o03220ac0139200010010.bu", b"ignored-bu")

    res_1 = ingest_partition(
        election_year=2026,
        turn=1,
        uf="AC",
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        max_jez_files=None,
        skip_existing=True,
        force_refresh=False,
    )

    assert res_1["central_directory_jez_count"] == 2
    assert res_1["target_jez_count"] == 2
    assert res_1["processed_jez_count"] == 2
    assert res_1["physical_logd_lines_count"] == 5
    assert res_1["parquet_row_count"] == 5
    assert res_1["cached"] is False

    # Limpeza imediata de data/staging/
    assert list(staging_dir.glob("*")) == []
    assert list(exports_dir.rglob("*.tmp")) == []

    out_pq = Path(res_1["parquet_path"])
    assert out_pq.exists()
    assert out_pq.name == "part-0.parquet"
    pq_meta = pq.read_metadata(out_pq)
    assert pq_meta.num_rows == 5
    assert pq_meta.num_columns == 15
    assert pq_meta.row_group(0).column(0).compression.upper() == "ZSTD"

    df_written = pl.read_parquet(out_pq)
    assert df_written.columns == nb03_ns["FACT_URNA_LOGS_COLUMNS"]
    assert "<ID_REDACTED>" in df_written["message_text"].to_list()[1]
    assert "12345678901" not in json.dumps(df_written.to_dicts())
    assert "5555666677778888" not in json.dumps(df_written.to_dicts())
    # Números de 4 dígitos (ex: 1015) são preservados; 5+ dígitos (54321) são mascarados
    msg_row_3 = df_written["message_text"].to_list()[3]
    assert "1015 mantido e 5 dígitos <ID_REDACTED> mascarado" in msg_row_3

    # Manifesto atualizado atomicamente
    manifest = load_manifest(manifest_path)
    part_key = "fact_urna_logs/election_year=2026/turn=1/uf=AC"
    assert manifest["partitions"][part_key]["status"] == "completed"
    assert manifest["partitions"][part_key]["parquet_row_count"] == 5

    # Segunda execução idempotente (SKIP_EXISTING=True): usa cache sem tocar no Parquet
    mtime_1 = out_pq.stat().st_mtime_ns
    res_2 = ingest_partition(
        election_year=2026,
        turn=1,
        uf="AC",
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        max_jez_files=None,
        skip_existing=True,
        force_refresh=False,
    )
    assert res_2["cached"] is True
    assert out_pq.stat().st_mtime_ns == mtime_1

    # Relatório de tamanho em disco por arquivo Parquet e soma total
    files_report, total_bytes = compute_report(exports_dir)
    assert len(files_report) == 1
    assert total_bytes == files_report[0]["size_bytes"]
    assert total_bytes > 0
    assert files_report[0]["row_count"] == 5
    assert files_report[0]["column_count"] == 15


def test_executed_notebook_03_outputs_head_tail_and_disk_sizes(
    repo_root: Path,
) -> None:
    """Verifica que o notebook 03 imprimiu HEAD(5), TAIL(5), tamanho por Parquet e SOMA TOTAL."""
    nb_path = (
        repo_root
        / "notebooks"
        / "03_ingest_urna_logs_batch"
        / "03_ingest_urna_logs_batch.ipynb"
    )
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [c for c in nb_data["cells"] if c.get("cell_type") == "code"]
    assert len(code_cells) >= 4
    for cell in code_cells:
        assert cell.get("execution_count") is not None, (
            "Todas as células de código devem estar executadas"
        )

    executed_stdout = "".join(
        "".join(out.get("text", []))
        for cell in code_cells
        for out in cell.get("outputs", [])
        if out.get("output_type") == "stream" and out.get("name") == "stdout"
    )

    assert "--- fact_urna_logs (turn=1, uf=AC) : HEAD(5) ---" in executed_stdout
    assert "--- fact_urna_logs (turn=1, uf=AC) : TAIL(5) ---" in executed_stdout
    assert "--- fact_urna_logs (turn=2, uf=AC) : HEAD(5) ---" in executed_stdout
    assert "--- fact_urna_logs (turn=2, uf=AC) : TAIL(5) ---" in executed_stdout
    assert "RELATÓRIO DE ARMAZENAMENTO PARQUET ZSTD POR ARQUIVO GERADO" in executed_stdout

    file_regex = re.compile(
        r"^\d+\.\s+(data/exports/\S+\.parquet)\s+\|\s+rows=([\d,]+)\s+\|\s+cols=(\d+)\s+\|\s+"
        r"size=([\d,]+)\s+bytes\s+\(([\d.]+)\s+KB\s+/\s+([\d.]+)\s+MB\)$",
        re.MULTILINE,
    )
    matches = file_regex.findall(executed_stdout)
    assert len(matches) >= 2, (
        f"Esperados >= 2 arquivos Parquet listados, encontrados {len(matches)}"
    )

    individual_sizes = [int(m[3].replace(",", "")) for m in matches]
    assert all(sz > 0 for sz in individual_sizes)

    sum_match = re.search(
        r"SOMA TOTAL EM DISCO \(\d+ arquivos Parquet ZSTD, \d+ tabelas\):\s+"
        r"([\d,]+)\s+bytes\s+\(([\d,.]+)\s+KB\s+/\s+([\d.]+)\s+MB\)",
        executed_stdout,
    )
    assert sum_match is not None, (
        "Linha de SOMA TOTAL EM DISCO não encontrada no output do notebook"
    )
    printed_total_bytes = int(sum_match.group(1).replace(",", ""))
    assert printed_total_bytes == sum(individual_sizes)
    assert "Auditoria concluída com 100% de sucesso" in executed_stdout
