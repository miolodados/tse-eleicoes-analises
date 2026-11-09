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
    nb_raw = nb_path.read_text(encoding="utf-8")
    nb_data = json.loads(nb_raw)

    # Garante ausência de prefixo proibido ou jargões internos em todo o notebook
    forbidden_prefix = "bronze" + "_"
    assert forbidden_prefix not in nb_raw
    assert "Decisão A1" not in nb_raw
    assert "Decisão A2" not in nb_raw

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

    urna_matches = [m for m in matches if "fact_urna_logs/" in m[0]]
    assert len(urna_matches) == 2
    urna_sizes = [int(m[3].replace(",", "")) for m in urna_matches]

    subtotal_match = re.search(
        r"SUBTOTAL EM DISCO fact_urna_logs \(\d+ arquivos Parquet ZSTD\):\s+"
        r"([\d,]+)\s+bytes\s+\(([\d,.]+)\s+KB\s+/\s+([\d.]+)\s+MB\)",
        executed_stdout,
    )
    assert subtotal_match is not None
    assert int(subtotal_match.group(1).replace(",", "")) == sum(urna_sizes)

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


def test_adversarial_binary_absence_of_mac_code_and_unredacted_ids_in_parquet(
    nb03_ns: dict[str, Any], repo_root: Path, tmp_path: Path
) -> None:
    """Stress test: valida ausência binária de mac_code e de IDs de 5+ dígitos no Parquet ZSTD."""
    ingest_partition = nb03_ns["ingest_uf_turn_partition"]

    secret_macs = [
        "CAFEBABE11223344",
        "DEADBEEF55667788",
        "FACEFEED99AABBCC",
        "0123456789ABCDEF",
        "F0E1D2C3B4A59687",
    ]
    secret_ids_5plus = [
        "12345",
        "98765432100",
        "014429582429",
        "55566677788",
        "99887766",
    ]

    # Inclui linhas de 6 campos, 7 campos (data\thora), 5 campos sem APP, multi-tab e linha truncada
    adv_logd = (
        f"04/10/2026 07:00:00\tINFO\t02263093\tLOGD\t"
        f"Início com ID_5_DIGITOS {secret_ids_5plus[0]} e 4 dígitos 4321\t{secret_macs[0]}\r\n"
        f"04/10/2026\t07:05:10,250\tINFO\t02263093\tVOTA\t"
        f"CPF {secret_ids_5plus[1]} e Titulo_{secret_ids_5plus[2]}\t{secret_macs[1]}\r\n"
        f"04/10/2026 07:10:00\tINFO\t02263093\t"
        f"Linha de sistema 5 campos sem APP {secret_ids_5plus[3]}\t{secret_macs[2]}\n"
        f"04/10/2026 07:15:00\tALERTA\t02263093\tVOTA\t"
        f"Mensagem\tcom\ttab\tinterno\t{secret_ids_5plus[4]}\t{secret_macs[3]}\n"
        f"04/10/2026 07:20:00\tERRO\tLinha truncada {secret_ids_5plus[0]}\t{secret_macs[4]}\n"
    ).encode("latin1")

    jez_payload = _build_synthetic_7z_jez({"logd.dat": adv_logd})
    staging_dir = tmp_path / "staging"
    exports_dir = tmp_path / "exports"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    part_staging = staging_dir / "election_year=2026" / "turn=1" / "uf=AC"
    part_staging.mkdir(parents=True, exist_ok=True)
    local_zip = part_staging / "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip"
    with zipfile.ZipFile(local_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o03220ac0101500020088-log.jez", jez_payload)

    res = ingest_partition(
        election_year=2026,
        turn=1,
        uf="AC",
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        max_jez_files=None,
        skip_existing=False,
        force_refresh=True,
    )
    out_pq = Path(res["parquet_path"])
    raw_pq_bytes = out_pq.read_bytes()
    df_pq = pl.read_parquet(out_pq)

    assert b"mac_code" not in raw_pq_bytes
    for mac in secret_macs:
        assert mac.encode("utf-8") not in raw_pq_bytes
        assert mac.encode("latin1") not in raw_pq_bytes
        assert mac not in json.dumps(df_pq.to_dicts(), ensure_ascii=False)

    for pii_num in secret_ids_5plus:
        assert pii_num.encode("utf-8") not in raw_pq_bytes
        assert pii_num.encode("latin1") not in raw_pq_bytes
        assert pii_num not in json.dumps(df_pq["message_text"].to_list(), ensure_ascii=False)

    for msg in df_pq["message_text"].to_list():
        assert re.search(r"\b\d{5,}\b", msg) is None, f"Número de 5+ dígitos não mascarado: {msg}"

    # Verifica também as partições reais geradas em data/exports/fact_urna_logs/
    real_urna_dir = repo_root / "data" / "exports" / "fact_urna_logs"
    if real_urna_dir.exists():
        real_parquets = sorted(real_urna_dir.rglob("*.parquet"))
        assert len(real_parquets) >= 2
        for real_pq in real_parquets:
            real_bytes = real_pq.read_bytes()
            assert b"mac_code" not in real_bytes
            real_df = pl.read_parquet(real_pq)
            assert real_df.columns == nb03_ns["FACT_URNA_LOGS_COLUMNS"]
            unredacted = [
                m for m in real_df["message_text"].to_list() if re.search(r"\b\d{5,}\b", m)
            ]
            assert unredacted == []


def test_adversarial_batch_idempotency_no_rewrite_no_row_duplication(
    nb03_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Stress test: 2ª execução com skip_existing=True não reescreve nem duplica linhas."""
    ingest_batch = nb03_ns["ingest_urna_logs_batch"]
    load_manifest = nb03_ns["load_manifest"]

    staging_dir = tmp_path / "staging"
    exports_dir = tmp_path / "exports"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"

    for turn in (1, 2):
        p_dir = staging_dir / "election_year=2026" / f"turn={turn}" / "uf=AC"
        p_dir.mkdir(parents=True, exist_ok=True)
        z_path = p_dir / f"bu_imgbu_logjez_rdv_vscmr_2026_{turn}t_AC.zip"
        jez_bytes = _build_synthetic_7z_jez(
            {
                "logd.dat": (
                    f"04/10/2026 08:00:00\tINFO\t02263093\tVOTA\t"
                    f"Turno {turn} eleitor 12345678901\tAABBCCDDEEFF0011\n"
                    f"04/10/2026 17:00:00\tINFO\t02263093\tVOTA\t"
                    f"Encerramento turno {turn}\tAABBCCDDEEFF0022\n"
                ).encode("latin1")
            }
        )
        with zipfile.ZipFile(z_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"o0322{turn - 1}ac0101500020088-log.jez", jez_bytes)

    batch_1 = ingest_batch(
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        max_jez_files=5,
        skip_existing=True,
        force_refresh=False,
    )
    assert batch_1["processed_jez_count"] == 2
    assert batch_1["target_jez_count"] == 2
    assert batch_1["physical_logd_lines_count"] == 4
    assert batch_1["parquet_row_count"] == 4
    assert all(p["cached"] is False for p in batch_1["partitions"])

    pq_files = sorted(exports_dir.rglob("*.parquet"))
    assert len(pq_files) == 2
    mtimes_before = {p: p.stat().st_mtime_ns for p in pq_files}
    bytes_before = {p: p.read_bytes() for p in pq_files}

    # Insere arquivo órfão em staging e usa cliente HTTP proibido de fazer chamadas de rede
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "orphan_file.tmp").write_bytes(b"leftover")

    class _ForbidNetworkClient:
        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Nenhuma requisição HTTP deve ocorrer em cache hit idempotente!")

        def head(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Nenhuma requisição HEAD deve ocorrer em cache hit idempotente!")

        def close(self) -> None:
            pass

    batch_2 = ingest_batch(
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        max_jez_files=5,
        skip_existing=True,
        force_refresh=False,
        client=_ForbidNetworkClient(),
    )
    assert batch_2["processed_jez_count"] == 2
    assert batch_2["target_jez_count"] == 2
    assert batch_2["physical_logd_lines_count"] == 4
    assert batch_2["parquet_row_count"] == 4
    assert all(p["cached"] is True for p in batch_2["partitions"])
    assert list(staging_dir.glob("*")) == []

    for p in pq_files:
        assert p.stat().st_mtime_ns == mtimes_before[p]
        assert p.read_bytes() == bytes_before[p]
        assert pl.read_parquet(p).height == 2

    manifest = load_manifest(manifest_path)
    assert manifest["tables_summary"]["fact_urna_logs"]["parquet_row_count"] == 4


def test_adversarial_reconciliation_nested_rotations_and_corrupted_jez_rollback(
    nb03_ns: dict[str, Any], tmp_path: Path
) -> None:
    """Stress test: reconciliação estrita com aninhamento e rollback atômico se .jez corrompido."""
    ingest_partition = nb03_ns["ingest_uf_turn_partition"]
    load_manifest = nb03_ns["load_manifest"]

    # 1) Testa múltiplos .jez com chunk_jez_size=1 e rotação aninhada
    nested_rot_2 = _build_synthetic_zip_jez(
        {
            "logd.dat": (
                b"04/10/2026 06:00:00\tINFO\t02263093\tLOGD\tRotacao 2 linha 1\tAA11223344556677\n"
                b"\n"
                b"04/10/2026 06:01:00\tINFO\t02263093\tLOGD\tRotacao 2 linha 2\tAA11223344556678\n"
            )
        }
    )
    nested_rot_1 = _build_synthetic_7z_jez(
        {
            "logd.dat": (
                b"04/10/2026 07:00:00\tINFO\t02263093\tSCUE\tRotacao 1 linha 1\tBB11223344556677\n"
            )
        }
    )
    outer_jez_a = _build_synthetic_7z_jez(
        {
            "logd.dat": (
                b"04/10/2026 08:00:00\tINFO\t02263093\tVOTA\tAtivo linha 1\tCC11223344556677\n"
            ),
            "logd.dat.1.jez": nested_rot_1,
            "logd.dat.2.zip": nested_rot_2,
        }
    )
    outer_jez_b = _build_synthetic_zip_jez(
        {
            "logd.dat": (
                b"04/10/2026 08:10:00\tINFO\t02269999\tVOTA\tSecao 2 linha 1\tDD11223344556677\n"
                b"04/10/2026 08:11:00\tINFO\t02269999\tVOTA\tSecao 2 linha 2\tDD11223344556678\n"
            )
        }
    )

    staging_ok = tmp_path / "staging_ok"
    exports_ok = tmp_path / "exports_ok"
    manifest_ok = exports_ok / "_checkpoints" / "manifest.json"
    part_dir_ok = staging_ok / "election_year=2026" / "turn=1" / "uf=AC"
    part_dir_ok.mkdir(parents=True, exist_ok=True)
    zip_ok = part_dir_ok / "bu_imgbu_logjez_rdv_vscmr_2026_1t_AC.zip"
    with zipfile.ZipFile(zip_ok, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o03220ac0101500020001-log.jez", outer_jez_a)
        zf.writestr("o03220ac0101500020002-log.jez", outer_jez_b)

    res_ok = ingest_partition(
        election_year=2026,
        turn=1,
        uf="AC",
        staging_dir=staging_ok,
        exports_dir=exports_ok,
        manifest_path=manifest_ok,
        max_jez_files=None,
        skip_existing=False,
        force_refresh=True,
        chunk_jez_size=1,
    )
    assert res_ok["processed_jez_count"] == res_ok["target_jez_count"] == 2
    assert res_ok["physical_logd_lines_count"] == res_ok["parquet_row_count"] == 6
    df_ok = pl.read_parquet(res_ok["parquet_path"])
    df_sec1 = df_ok.filter(pl.col("nr_secao") == 1)
    assert df_sec1["file_seq"].to_list() == [1, 2, 3, 4]
    assert df_sec1["source_log_member"].to_list() == [
        "logd.dat.2",
        "logd.dat.2",
        "logd.dat.1",
        "logd.dat",
    ]

    # 2) .jez com bytes corrompidos dentro do ZIP aborta escrita, limpa staging e não suja manifesto
    staging_bad = tmp_path / "staging_bad"
    exports_bad = tmp_path / "exports_bad"
    manifest_bad = exports_bad / "_checkpoints" / "manifest.json"
    part_dir_bad = staging_bad / "election_year=2026" / "turn=1" / "uf=RR"
    part_dir_bad.mkdir(parents=True, exist_ok=True)
    zip_bad = part_dir_bad / "bu_imgbu_logjez_rdv_vscmr_2026_1t_RR.zip"
    with zipfile.ZipFile(zip_bad, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("o03220rr0301800010001-log.jez", b"INVALID_MAGIC_BYTES_CORRUPTED")

    with pytest.raises(ValueError, match="Assinatura mágica desconhecida"):
        ingest_partition(
            election_year=2026,
            turn=1,
            uf="RR",
            staging_dir=staging_bad,
            exports_dir=exports_bad,
            manifest_path=manifest_bad,
            max_jez_files=None,
            skip_existing=False,
            force_refresh=True,
        )

    assert list(staging_bad.glob("*")) == []
    assert list(exports_bad.rglob("*.parquet")) == []
    assert list(exports_bad.rglob("*.tmp")) == []
    assert load_manifest(manifest_bad)["partitions"] == {}

