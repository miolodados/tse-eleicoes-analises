"""Testes automatizados da Fase 3 (04_dataset_integrity_and_release.ipynb)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

NB_PATH = (
    Path(__file__).resolve().parents[1]
    / "notebooks"
    / "04_dataset_integrity_and_release"
    / "04_dataset_integrity_and_release.ipynb"
)


def _load_nb04_namespace() -> dict[str, Any]:
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))
    ns: dict[str, Any] = {"__name__": "nb04_test_module"}
    for cell in nb["cells"]:
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if "if __name__ ==" in src:
            continue
        exec(compile(src, str(NB_PATH), "exec"), ns)
    return ns


NB04 = _load_nb04_namespace()
TABLE_CATALOG_18 = NB04["TABLE_CATALOG_18"]
PrivacyAuditError = NB04["PrivacyAuditError"]
audit_partitions_and_manifest = NB04["audit_partitions_and_manifest"]
reconcile_section_votes_and_turnout = NB04["reconcile_section_votes_and_turnout"]
cross_check_urna_serial_and_log_coverage = NB04["cross_check_urna_serial_and_log_coverage"]
audit_electorate_and_turnout_consistency = NB04["audit_electorate_and_turnout_consistency"]
audit_urna_logs_privacy = NB04["audit_urna_logs_privacy"]
compute_zstd_storage_budget_and_generate_metadata = NB04[
    "compute_zstd_storage_budget_and_generate_metadata"
]
verify_kaggle_release_package_readiness = NB04["verify_kaggle_release_package_readiness"]
run_full_phase3_integrity_audit = NB04["run_full_phase3_integrity_audit"]


def _build_18_table_fixture(base_dir: Path) -> Path:
    """Cria uma fixture Parquet ZSTD completa das 18 tabelas com 2 seções em AC (turno 1)."""
    exports_dir = base_dir / "exports"
    manifest_partitions: dict[str, dict[str, Any]] = {}

    for tbl_name, spec in TABLE_CATALOG_18.items():
        cols: list[str] = spec["expected_columns"]
        rows: list[dict[str, Any]] = []

        if tbl_name == "fact_urna_logs":
            # Seção 0101 com log .jez; seção 0102 sem log (missing_log / NULL)
            rows = [
                {
                    "election_year": 2026,
                    "turn": 1,
                    "uf": "AC",
                    "cd_pleito": "00407",
                    "cd_municipio": "01392",
                    "nr_zona": "0001",
                    "nr_secao": "0101",
                    "source_jez_file": "o00407-0139200010101.logjez",
                    "source_log_member": "logd.dat",
                    "file_seq": 1,
                    "raw_timestamp": "04/10/2026 08:00:00",
                    "log_level": "INFO",
                    "urna_serial": "02206123",
                    "application": "VOTA",
                    "message_text": "Eleitor <ID_REDACTED> habilitado na secao",
                },
                {
                    "election_year": 2026,
                    "turn": 1,
                    "uf": "AC",
                    "cd_pleito": "00407",
                    "cd_municipio": "01392",
                    "nr_zona": "0001",
                    "nr_secao": "0101",
                    "source_jez_file": "o00407-0139200010101.logjez",
                    "source_log_member": "logd.dat",
                    "file_seq": 2,
                    "raw_timestamp": "04/10/2026 17:00:00",
                    "log_level": "INFO",
                    "urna_serial": "02206123",
                    "application": "VOTA",
                    "message_text": "Encerramento assinado pelo mesario <ID_REDACTED>",
                },
            ]
        elif tbl_name == "fact_boletim_urna":
            # Seção 0101 (sem troca) e Seção 0102 (troca de urna e sem log .jez)
            for sec, urna_efet, votes in [("0101", "2206123", 150), ("0102", "9999999", 120)]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "ANO_ELEICAO": 2026,
                        "NR_TURNO": 1,
                        "SG_UF": "AC",
                        "CD_PLEITO": "407",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "CD_CARGO_PERGUNTA": 1,
                        "NR_VOTAVEL": "13",
                        "QT_VOTOS": votes,
                        "QT_APTOS": 200,
                        "QT_COMPARECIMENTO": votes,
                        "QT_ABSTENCOES": 200 - votes,
                        "NR_URNA_EFETIVADA": urna_efet,
                        "DS_SECOES_AGREGADAS": "#NULO#",
                    }
                )
                rows.append(row)
        elif tbl_name == "fact_votacao_secao":
            for sec, votes in [("0101", 150), ("0102", 120)]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "ANO_ELEICAO": 2026,
                        "NR_TURNO": 1,
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "CD_CARGO": 1,
                        "NR_VOTAVEL": "13",
                        "QT_VOTOS": votes,
                    }
                )
                rows.append(row)
        elif tbl_name == "fact_detalhe_votacao_secao":
            for sec, votes in [("0101", 150), ("0102", 120)]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "ANO_ELEICAO": 2026,
                        "NR_TURNO": 1,
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "CD_CARGO": 1,
                        "QT_APTOS": 200,
                        "QT_COMPARECIMENTO": votes,
                        "QT_ABSTENCOES": 200 - votes,
                        "QT_VOTOS_NOMINAIS": votes,
                        "QT_VOTOS_BRANCOS": 0,
                        "QT_VOTOS_NULOS": 0,
                        "QT_VOTOS_LEGENDA": 0,
                        "QT_VOTOS_ANULADOS_APU_SEP": 0,
                        "ST_SECAO_ANULADA": "N",
                    }
                )
                rows.append(row)
        elif tbl_name == "bridge_correspondencia_efetivada":
            for sec, esp, efet in [("0101", "2206123", "2206123"), ("0102", "8888888", "9999999")]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "AA_ELEICAO": 2026,
                        "CD_PLEITO": "407",
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "NR_URNA_ESPERADA": esp,
                        "NR_URNA_EFETIVADA": efet,
                    }
                )
                rows.append(row)
        elif tbl_name == "bridge_correspondencia_esperada":
            for sec, esp in [("0101", "2206123"), ("0102", "8888888")]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "AA_ELEICAO": 2026,
                        "CD_PLEITO": "407",
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "NR_URNA_ESPERADA": esp,
                    }
                )
                rows.append(row)
        elif tbl_name == "fact_eleitorado_perfil_secao":
            for sec in ["0101", "0102"]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "AA_ELEICAO": 2026,
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "CD_GENERO": "2",
                        "CD_FAIXA_ETARIA": "3034",
                        "CD_GRAU_ESCOLARIDADE": "6",
                        "QT_ELEITORES": 200,
                    }
                )
                rows.append(row)
        elif tbl_name == "dim_local_votacao_secao":
            for sec in ["0101", "0102"]:
                row = {c: "0" for c in cols}
                row.update(
                    {
                        "AA_ELEICAO": 2026,
                        "NR_TURNO": 1,
                        "SG_UF": "AC",
                        "CD_MUNICIPIO": "01392",
                        "NR_ZONA": "0001",
                        "NR_SECAO": sec,
                        "NR_LOCAL_VOTACAO": "1015",
                        "NR_SECAO_PRINCIPAL": sec,
                        "QT_ELEITOR_SECAO": 200,
                    }
                )
                rows.append(row)
        elif tbl_name == "fact_comparecimento_abstencao":
            row = {c: "0" for c in cols}
            row.update(
                {
                    "ANO_ELEICAO": 2026,
                    "NR_TURNO": 1,
                    "SG_UF": "AC",
                    "CD_MUNICIPIO": "01392",
                    "NR_ZONA": "0001",
                    "CD_GENERO": "2",
                    "CD_FAIXA_ETARIA": "3034",
                    "CD_GRAU_INSTRUCAO": "6",
                    "QT_APTOS": 400,
                    "QT_COMPARECIMENTO": 270,
                    "QT_ABSTENCAO": 130,
                }
            )
            rows.append(row)
        else:
            row = {c: "0" for c in cols}
            if "ANO_ELEICAO" in cols:
                row["ANO_ELEICAO"] = 2026
            if "AA_ELEICAO" in cols:
                row["AA_ELEICAO"] = 2026
            if "NR_TURNO" in cols:
                row["NR_TURNO"] = 1
            if "SG_UF" in cols:
                row["SG_UF"] = "AC"
            if "SG_UF_DESTINO" in cols:
                row["SG_UF_DESTINO"] = "AC"
            if "QT_ELEITOR" in cols:
                row["QT_ELEITOR"] = 5
            rows.append(row)

        df = pl.DataFrame(rows).select(cols)
        part_dir = exports_dir / tbl_name / "election_year=2026" / "turn=1" / "uf=AC"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_pq = part_dir / "part-0.parquet"
        df.write_parquet(out_pq, compression="zstd", compression_level=5)

        part_key = f"{tbl_name}/election_year=2026/turn=1/uf=AC"
        manifest_partitions[part_key] = {
            "table_name": tbl_name,
            "election_year": 2026,
            "turn": 1,
            "uf": "AC",
            "column_count": len(cols),
            "parquet_row_count": df.height,
            "size_bytes": out_pq.stat().st_size,
            "parquet_path": str(out_pq),
            "sha512_verified": True if spec["requires_sha512"] else False,
            "status": "completed",
        }

    ckpt_dir = exports_dir / "_checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    (ckpt_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "partitions": manifest_partitions,
                "source_coverage": {
                    "dim_partido_munzona": [{"turn": 1, "uf": "AC", "row_count": 1}]
                },
                "source_coverage_scope": {
                    "dim_partido_munzona": {
                        "election_year": 2026,
                        "target_ufs": [
                            "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
                            "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
                            "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"
                        ],
                        "turns": [1, 2]
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return exports_dir


def test_kernel_metadata_and_notebook_structure() -> None:
    meta_path = NB_PATH.parent / "kernel-metadata.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["id"] == "daniellmattos/tse-analysis-04-dataset-integrity-and-release"
    assert meta["code_file"] == "04_dataset_integrity_and_release.ipynb"
    assert meta["enable_internet"] is True
    assert len(TABLE_CATALOG_18) == 18


def test_audit_partitions_and_manifest_success_and_failures(tmp_path: Path) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    res = audit_partitions_and_manifest(exports_dir, strict=True)
    assert res["passed"] is True
    assert res["total_tables_found"] == 18
    assert res["total_partitions_audited"] == 18

    # Testar rejeição de chave de partição proibida (ex.: section_num=0101)
    forbidden_dir = (
        exports_dir
        / "fact_urna_logs"
        / "election_year=2026"
        / "turn=1"
        / "uf=AC"
        / "section_num=0101"
    )
    forbidden_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match="forbidden_partition_keys"):
        audit_partitions_and_manifest(exports_dir, strict=True)
    forbidden_dir.rmdir()

    # Testar detecção de divergência de row_count no manifesto
    m_path = exports_dir / "_checkpoints" / "manifest.json"
    m_data = json.loads(m_path.read_text(encoding="utf-8"))
    m_data["partitions"]["fact_boletim_urna/election_year=2026/turn=1/uf=AC"][
        "parquet_row_count"
    ] = 999
    m_path.write_text(json.dumps(m_data), encoding="utf-8")
    with pytest.raises(ValueError, match="row_count_mismatches"):
        audit_partitions_and_manifest(exports_dir, strict=True)


def test_duckdb_referential_integrity_and_missing_log_null_semantics(tmp_path: Path) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)

    # 1. Reconciliação BU vs votacao_secao vs detalhe_votacao_secao
    rec = reconcile_section_votes_and_turnout(exports_dir)
    assert rec["total_slices"] == 2
    assert rec["exact_match_slices"] == 2
    assert rec["unexplained_divergence_slices"] == 0

    # 2. Cobertura explícita de logs e seção sem .jez como missing_log / NULL
    cov = cross_check_urna_serial_and_log_coverage(exports_dir)
    assert cov["total_bu_sections"] == 2
    assert cov["sections_with_logs"] == 1
    assert cov["missing_log_sections"] == 1
    assert cov["overall_log_coverage_pct"] == 50.0
    assert cov["exact_serial_match_count"] == 1
    assert cov["contingency_urna_swap_count"] == 1

    by_sec = {s["nr_secao"]: s for s in cov["sample_sections"]}
    assert by_sec["0101"]["coverage_status"] == "covered"
    assert by_sec["0101"]["log_event_count"] == 2
    assert by_sec["0102"]["coverage_status"] == "missing_log"
    assert by_sec["0102"]["log_event_count"] is None

    # 3. Consistência eleitorado vs local_votacao vs comparecimento_abstencao
    elec = audit_electorate_and_turnout_consistency(exports_dir)
    assert elec["accounting_identity_violations"] == 0
    assert elec["by_uf"][0]["eps_eleitores"] == 400
    assert elec["by_uf"][0]["lvs_eleitores_t1"] == 400
    assert elec["by_uf"][0]["ca_aptos_t1"] == 400


def test_privacy_audit_blocks_mac_code_and_unmasked_digits(tmp_path: Path) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    priv = audit_urna_logs_privacy(exports_dir)
    assert priv["passed"] is True
    assert priv["has_mac_code_column"] is False
    assert priv["unmasked_5plus_digit_rows"] == 0
    assert priv["redacted_token_rows"] == 2

    # Injetar linha com número de 5+ dígitos desmascarado -> deve lançar PrivacyAuditError
    pq_path = (
        exports_dir
        / "fact_urna_logs"
        / "election_year=2026"
        / "turn=1"
        / "uf=AC"
        / "part-0.parquet"
    )
    df_bad = pl.read_parquet(pq_path).with_columns(
        pl.lit("Titulo eleitoral 123456789012 exposto").alias("message_text")
    )
    df_bad.write_parquet(pq_path, compression="zstd", compression_level=5)
    with pytest.raises(PrivacyAuditError, match="5\\+ dígitos"):
        audit_urna_logs_privacy(exports_dir)

    # Injetar coluna mac_code -> deve lançar PrivacyAuditError
    df_mac = df_bad.with_columns(
        pl.lit("Eleitor <ID_REDACTED>").alias("message_text"),
        pl.lit("ABCDEF1234567890").alias("mac_code"),
    )
    df_mac.write_parquet(pq_path, compression="zstd", compression_level=5)
    with pytest.raises(PrivacyAuditError, match="mac_code"):
        audit_urna_logs_privacy(exports_dir)


def test_full_phase3_pipeline_and_package_readiness(tmp_path: Path) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    report = run_full_phase3_integrity_audit(exports_dir=exports_dir, output_dir=exports_dir)
    assert report["partition_and_manifest_audit"]["passed"] is True
    assert report["privacy_audit"]["passed"] is True
    assert report["release_package_readiness"]["ready_for_manual_publish"] is True
    assert (exports_dir / "dataset-metadata.json").exists()
    assert (exports_dir / "integrity_audit_report.json").exists()


def test_party_dimension_source_coverage_is_audited(tmp_path: Path) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"

    passed = audit_partitions_and_manifest(exports_dir, strict=True)
    assert passed["source_coverage_missing"] == []
    assert passed["missing_source_coverage_partitions"] == []
    assert passed["source_coverage_row_count_mismatches"] == []

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_coverage"]["dim_partido_munzona"].append(
        {"turn": 2, "uf": "AC", "row_count": 3}
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="missing_source_coverage_partitions"):
        audit_partitions_and_manifest(exports_dir, strict=True)


def test_party_dimension_audit_rejects_legacy_manifest_without_source_coverage(
    tmp_path: Path,
) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("source_coverage", None)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="source_coverage_missing"):
        audit_partitions_and_manifest(exports_dir, strict=True)

def test_party_dimension_source_coverage_rejects_entries_outside_declared_scope(
    tmp_path: Path,
) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_coverage"]["dim_partido_munzona"].append(
        {"turn": 3, "uf": "AC", "row_count": 1}
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="entry_outside_scope"):
        audit_partitions_and_manifest(exports_dir, strict=True)


def test_party_dimension_source_coverage_rejects_invalid_scope_values(
    tmp_path: Path,
) -> None:
    exports_dir = _build_18_table_fixture(tmp_path)
    manifest_path = exports_dir / "_checkpoints" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_coverage_scope"]["dim_partido_munzona"]["target_ufs"].append("BR")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid_scope_values"):
        audit_partitions_and_manifest(exports_dir, strict=True)

