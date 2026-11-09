"""Testes unitários para o pipeline autocontido de ingestão das 17 tabelas eleitorais (Fase 1)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from tse_analysis.inventory.catalog import assert_redistribution_allowed, load_source_catalog


def _load_notebook_namespace(repo_root: Path) -> dict[str, Any]:
    """Carrega as definições declarativas e funções das células 1 a 3 do notebook 02."""
    nb_path = (
        repo_root
        / "notebooks"
        / "02_ingest_electoral_tables"
        / "02_ingest_electoral_tables.ipynb"
    )
    nb_data = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [c for c in nb_data["cells"] if c.get("cell_type") == "code"]
    namespace: dict[str, Any] = {}
    # Executa as 3 células de definição (catálogo, CKAN/SHA-512/ZIP e motor de ingestão/manifesto)
    for cell in code_cells[:3]:
        source_code = "".join(cell.get("source", []))
        exec(compile(source_code, str(nb_path), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def nb_ns(repo_root: Path) -> dict[str, Any]:
    return _load_notebook_namespace(repo_root)


def test_electoral_tables_catalog_17_tables_and_exact_column_counts(
    nb_ns: dict[str, Any],
) -> None:
    catalog: dict[str, dict[str, Any]] = nb_ns["ELECTORAL_TABLES_CATALOG"]
    expected_counts = {
        "fact_boletim_urna": 45,
        "fact_votacao_secao": 26,
        "fact_detalhe_votacao_secao": 37,
        "fact_detalhe_votacao_munzona": 47,
        "dim_candidato_munzona": 50,
        "dim_partido_munzona": 38,
        "fact_eleitorado_perfil_secao": 30,
        "fact_eleitorado_perfil_munzona": 27,
        "dim_local_votacao_secao": 41,
        "fact_eleitorado_deficiencia": 30,
        "fact_transferencia_temporaria_secao": 17,
        "fact_transferencia_temporaria_mun": 13,
        "fact_comparecimento_abstencao": 45,
        "fact_comparecimento_abstencao_pcd": 20,
        "fact_comparecimento_abstencao_tte": 25,
        "bridge_correspondencia_esperada": 21,
        "bridge_correspondencia_efetivada": 36,
    }
    assert list(catalog.keys()) == list(expected_counts.keys())
    assert len(catalog) == 17

    forbidden_prefix = "bronze" + "_"
    for table_name, spec in catalog.items():
        assert not table_name.startswith(forbidden_prefix)
        assert spec["expected_cols"] == expected_counts[table_name]
        assert spec["partition_cols"] == ["election_year", "turn", "uf"]
        if spec["family"] in ("eleitorado", "correspondencias"):
            assert spec["year_col"] == "AA_ELEICAO"
        else:
            assert spec["year_col"] == "ANO_ELEICAO"


def test_verify_sha512_success_and_tamper_rejection(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    verify_sha512 = nb_ns["verify_sha512"]
    payload = b"PK\x03\x04conteudo-oficial-boletim-urna-2026-AC"
    expected_hex = hashlib.sha512(payload).hexdigest()

    zip_file = tmp_path / "bweb_1t_AC_051020261403.zip"
    zip_file.write_bytes(payload)
    sha_file = tmp_path / "bweb_1t_AC_051020261403.zip.sha512"
    sha_file.write_text(f"{expected_hex}  bweb_1t_AC_051020261403.zip\n", encoding="latin1")

    assert verify_sha512(payload, f"{expected_hex}  bweb_1t_AC_051020261403.zip\n") == expected_hex
    assert verify_sha512(zip_file, sha_file) == expected_hex

    tampered = payload + b"X"
    with pytest.raises(ValueError, match="SHA-512"):
        verify_sha512(tampered, sha_file)

    with pytest.raises(ValueError, match="inválido"):
        verify_sha512(payload, "hash_invalido_curto  arquivo.zip")


def test_select_csv_members_excludes_brasil_when_uf_files_exist(
    nb_ns: dict[str, Any],
) -> None:
    select_csv_members = nb_ns["select_csv_members"]
    members_with_brasil = [
        "leiame.pdf",
        "detalhe_votacao_secao_2026_AC.csv",
        "detalhe_votacao_secao_2026_SP.csv",
        "detalhe_votacao_secao_2026_BRASIL.csv",
    ]
    selected_ac = select_csv_members(members_with_brasil, target_ufs=["AC"])
    assert selected_ac == ["detalhe_votacao_secao_2026_AC.csv"]

    selected_all_ufs = select_csv_members(members_with_brasil, target_ufs=None)
    assert "detalhe_votacao_secao_2026_BRASIL.csv" not in selected_all_ufs
    assert selected_all_ufs == [
        "detalhe_votacao_secao_2026_AC.csv",
        "detalhe_votacao_secao_2026_SP.csv",
    ]

    # Quando há apenas um CSV nacional único sem sufixo de UF, preserva o membro único
    single_national = ["leiame.pdf", "transferencia_temporaria_2026.csv"]
    assert select_csv_members(single_national, target_ufs=["AC"]) == [
        "transferencia_temporaria_2026.csv"
    ]

    # Em pacotes CESP, prioriza csec_ (seção, 21 colunas) sobre ccont_ (contingência, 19 colunas)
    cesp_members = ["ccont_1t_AC_041020261259.csv", "csec_1t_AC_041020261259.csv"]
    assert select_csv_members(cesp_members, target_ufs=["AC"]) == [
        "csec_1t_AC_041020261259.csv"
    ]


def test_executed_notebook_outputs_contain_17_tables_head_tail_and_disk_sum(
    repo_root: Path, nb_ns: dict[str, Any]
) -> None:
    nb_path = (
        repo_root
        / "notebooks"
        / "02_ingest_electoral_tables"
        / "02_ingest_electoral_tables.ipynb"
    )
    nb_text = nb_path.read_text(encoding="utf-8")
    for table_name in nb_ns["ELECTORAL_TABLES_CATALOG"]:
        assert f"--- {table_name} : HEAD(5) ---" in nb_text
        assert f"--- {table_name} : TAIL(5) ---" in nb_text
    assert "RELATÓRIO DE ARMAZENAMENTO PARQUET ZSTD POR ARQUIVO GERADO" in nb_text
    assert "SOMA TOTAL EM DISCO (" in nb_text
    assert "Auditoria concluída com 100% de sucesso" in nb_text


def test_csv_to_parquet_reconciliation_idempotency_and_storage_report(
    nb_ns: dict[str, Any], tmp_path: Path
) -> None:
    ingest_single_table = nb_ns["ingest_single_table"]
    compute_parquet_storage_report = nb_ns["compute_parquet_storage_report"]
    load_manifest = nb_ns["load_manifest"]

    # Monta um CSV sintético de 13 colunas para fact_transferencia_temporaria_mun
    cols = [
        "DT_GERACAO",
        "HH_GERACAO",
        "AA_ELEICAO",
        "NR_TURNO",
        "TP_TTE",
        "TP_ABRANGENCIA_TTE",
        "SG_UF_ORIGEM",
        "CD_MUNICIPIO_ORIGEM",
        "NM_MUNICIPIO_ORIGEM",
        "SG_UF_DESTINO",
        "CD_MUNICIPIO_DESTINO",
        "NM_MUNICIPIO_DESTINO",
        "QT_ELEITOR",
    ]
    rows = [
        (
            '"08/11/2026";"06:30:09";2026;1;"Voto em Trânsito";"Federal";'
            '"SP";"71072";"SÃO PAULO";"AC";"01392";"RIO BRANCO";4'
        ),
        (
            '"08/11/2026";"06:30:09";2026;1;"Voto em Trânsito";"Federal";'
            '"AM";"02550";"MANAUS";"AC";"01074";"CRUZEIRO DO SUL";2'
        ),
        (
            '"08/11/2026";"06:30:09";2026;2;"Voto em Trânsito";"Federal";'
            '"SP";"71072";"SÃO PAULO";"AC";"01392";"RIO BRANCO";3'
        ),
    ]
    csv_bytes = (";".join(f'"{c}"' for c in cols) + "\n" + "\n".join(rows) + "\n").encode("latin1")

    zip_path = tmp_path / "source_tte.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("transferencia_temporaria_2026_AC.csv", csv_bytes)
        zf.writestr(
            "transferencia_temporaria_2026_BRASIL.csv",
            csv_bytes + rows[0].encode("latin1") + b"\n",
        )

    class _MockStreamResponse:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def __enter__(self) -> _MockStreamResponse:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self, chunk_size: int = 1024):
            yield self._data

    class _MockHttpClient:
        def __init__(self, zip_bytes: bytes) -> None:
            self.zip_bytes = zip_bytes
            self.download_calls = 0

        def stream(self, method: str, url: str) -> _MockStreamResponse:
            self.download_calls += 1
            return _MockStreamResponse(self.zip_bytes)

        def close(self) -> None:
            pass

    mock_client = _MockHttpClient(zip_path.read_bytes())
    staging_dir = tmp_path / "staging"
    exports_dir = tmp_path / "exports"
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    spec = dict(nb_ns["ELECTORAL_TABLES_CATALOG"]["fact_transferencia_temporaria_mun"])

    summary_1 = ingest_single_table(
        table_name="fact_transferencia_temporaria_mun",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=mock_client,
    )

    assert summary_1["csv_row_count"] == 3
    assert summary_1["parquet_row_count"] == 3
    assert summary_1["column_count"] == 13
    assert summary_1["partitions_count"] == 2
    assert mock_client.download_calls == 1
    assert list(staging_dir.glob("*")) == []
    assert manifest_path.exists()

    manifest = load_manifest(manifest_path)
    assert len(manifest["partitions"]) == 2

    # Segunda execução idempotente (SKIP_EXISTING=True): não deve realizar novo download
    summary_2 = ingest_single_table(
        table_name="fact_transferencia_temporaria_mun",
        spec=spec,
        election_year=2026,
        turns=[1, 2],
        target_ufs=["AC"],
        staging_dir=staging_dir,
        exports_dir=exports_dir,
        manifest_path=manifest_path,
        skip_existing=True,
        force_refresh=False,
        stream_range_max_bytes=None,
        client=mock_client,
    )
    assert mock_client.download_calls == 1
    assert summary_2["parquet_row_count"] == 3

    # Verifica cálculo de tamanho por arquivo Parquet ZSTD e soma total
    files_report, total_bytes = compute_parquet_storage_report(exports_dir)
    assert len(files_report) == 2
    assert total_bytes > 0
    assert total_bytes == sum(f["size_bytes"] for f in files_report)
    assert sum(f["row_count"] for f in files_report) == 3
    for f_info in files_report:
        assert f_info["column_count"] == 13
        assert f_info["size_bytes"] > 0
        assert pl.read_parquet(f_info["parquet_path"]).width == 13


def test_comparecimento_abstencao_license_policy_in_catalog(repo_root: Path) -> None:
    catalog = load_source_catalog(repo_root / "configs" / "sources.yml")
    entry = catalog.get("comparecimento_abstencao")
    assert entry.license_status == "open_documented"
    assert entry.redistribution_allowed is True
    assert_redistribution_allowed(entry)
