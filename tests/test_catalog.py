"""Testes unitários para o catálogo de fontes CKAN do TSE, licenças e consistência documental."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tse_analysis.config import ExecutionConfig
from tse_analysis.inventory.catalog import (
    REQUIRED_SOURCE_IDS,
    CatalogValidationError,
    LicenseRestrictionError,
    SourceCatalog,
    assert_redistribution_allowed,
    load_source_catalog,
)


def test_load_source_catalog_contains_all_7_required_families(
    catalog: SourceCatalog,
) -> None:
    assert catalog.default_election_year == 2026
    assert set(REQUIRED_SOURCE_IDS).issubset(set(catalog.sources.keys()))
    assert len(catalog.sources) == 7

    for source_id in REQUIRED_SOURCE_IDS:
        entry = catalog.get(source_id)
        assert entry.source_id == source_id
        assert entry.title
        assert entry.ckan_dataset_slug
        assert entry.url_template.startswith(
            (
                "https://cdn.tse.jus.br/",
                "https://www.tse.jus.br/",
                "https://dadosabertos.tse.jus.br/",
            )
        )
        assert 2026 in entry.supported_years
        assert entry.native_grain
        assert entry.target_table
        assert len(entry.natural_keys) > 0


def test_totalizacao_source_preserves_native_grain_and_totalizado_filter(
    catalog: SourceCatalog,
) -> None:
    entry = catalog.get("totalizacao_arquivos_transmitidos")
    assert entry.native_grain == "urna_transmission_package"
    assert entry.filter_rules.get("situacao") == "Totalizado"
    assert ".jez" in entry.inner_artifacts
    assert set(
        ("election_year", "turn", "uf", "municipio_code", "zone_num", "section_num")
    ).issubset(set(entry.natural_keys))


def test_url_resolution_for_2026_and_previous_elections(
    catalog: SourceCatalog,
) -> None:
    bu_2026 = catalog.resolve_url(
        "resultados_boletim_urna", election_year=2026, turn=1, uf="AC"
    )
    assert "resultados-2026-boletim-de-urna" in bu_2026
    assert "turn=1" in bu_2026 and "uf=AC" in bu_2026

    doc_2026 = catalog.resolve_url("ecossistema_urna_log_docs", election_year=2026)
    assert doc_2026 == (
        "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/"
        "log-do-ecossistema/@@display-file/file/log-do-ecossistema.pdf"
    )

    tot_2022 = catalog.resolve_url(
        "totalizacao_arquivos_transmitidos", election_year=2022, turn=2, uf="SP"
    )
    assert "eleicoes2022/arqurnatot/" in tot_2022
    assert "2022_2t_SP.zip" in tot_2022

    cfg = ExecutionConfig(election_year=2024, turn=1, uf="RJ")
    entry = catalog.get("correspondencias_esperadas_efetivadas")
    assert "resultados-2024-correspondencias-esperadas-e-efetivadas-1-turno" in (
        entry.resolve_for_config(cfg)
    )
    assert (
        entry.resolve_ckan_slug(2026, turn=1)
        == "resultados-2026-correspondencias-esperadas-e-efetivadas-1-turno"
    )


def test_comparecimento_abstencao_license_and_redistribution_guard(
    catalog: SourceCatalog,
) -> None:
    from dataclasses import replace

    elo_entry = catalog.get("comparecimento_abstencao")
    assert elo_entry.license_status == "open_documented"
    assert elo_entry.redistribution_allowed is True
    assert "Nenhuma Licença Fornecida" in elo_entry.license_notes
    assert_redistribution_allowed(elo_entry)

    # Verifica que o guarda bloqueia entradas marcadas com redistribution_allowed=False
    restricted_entry = replace(
        elo_entry,
        license_status="unspecified_no_license",
        redistribution_allowed=False,
    )
    with pytest.raises(LicenseRestrictionError, match="comparecimento_abstencao"):
        assert_redistribution_allowed(restricted_entry)

    # Fontes com licença aberta documentada não devem ser bloqueadas
    bu_entry = catalog.get("resultados_boletim_urna")
    assert_redistribution_allowed(bu_entry)


@pytest.mark.parametrize("missing_field", ["native_grain", "natural_keys", "license_status"])
def test_catalog_rejects_entry_missing_mandatory_field(
    repo_root: Path, tmp_path: Path, missing_field: str
) -> None:
    raw = yaml.safe_load((repo_root / "configs" / "sources.yml").read_text(encoding="utf-8"))
    del raw["sources"]["resultados_boletim_urna"][missing_field]

    broken_path = tmp_path / "broken_sources.yml"
    broken_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(CatalogValidationError, match=missing_field):
        load_source_catalog(broken_path)


def test_documentation_consistency_with_sources_catalog(
    repo_root: Path, catalog: SourceCatalog
) -> None:
    inventory_doc = (repo_root / "docs" / "source_inventory.md").read_text(encoding="utf-8")
    dictionary_doc = (repo_root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")

    for source_id, entry in catalog.sources.items():
        assert source_id in inventory_doc, f"source_id '{source_id}' ausente em source_inventory.md"
        assert entry.target_table in inventory_doc
        assert (
            entry.target_table in dictionary_doc
        ), f"target_table '{entry.target_table}' ausente em data_dictionary.md"

    # Verifica presença explícita da nota sobre licença do Sistema ELO e parametrização
    assert "Nenhuma Licença Fornecida" in inventory_doc
    assert "election_year" in inventory_doc

    # Verifica presença de todas as tabelas 1:1 (fatos, pontes e dimensões) no dicionário de dados
    expected_tables = [
        "fact_urna_logs",
        "fact_boletim_urna",
        "fact_votacao_secao",
        "fact_detalhe_votacao_secao",
        "fact_eleitorado_perfil_secao",
        "fact_eleitorado_deficiencia",
        "fact_transferencia_temporaria_secao",
        "fact_comparecimento_abstencao",
        "fact_comparecimento_abstencao_pcd",
        "fact_comparecimento_abstencao_tte",
        "bridge_correspondencia_esperada",
        "bridge_correspondencia_efetivada",
        "dim_local_votacao_secao",
        "dim_candidato_munzona",
        "dim_partido_munzona",
    ]
    for table_name in expected_tables:
        assert table_name in dictionary_doc, f"Tabela '{table_name}' ausente em data_dictionary.md"


@pytest.mark.parametrize(
    "forbidden_token",
    [
        "formato_arquivos_log_urna",
        "arqtranstot",
        "corresp/corresp_",
        "bweb_1t_AC_2026.zip",
    ],
)
def test_adversarial_no_invented_or_legacy_urls_in_configs_and_docs(
    repo_root: Path, forbidden_token: str
) -> None:
    """Garante que nenhuma URL inventada/antiga reapareça no catálogo ou na documentação."""
    monitored_files = [
        repo_root / "configs" / "sources.yml",
        repo_root / "configs" / "event_catalog.yml",
        repo_root / "docs" / "source_inventory.md",
        repo_root / "docs" / "data_dictionary.md",
    ]
    for file_path in monitored_files:
        content = file_path.read_text(encoding="utf-8")
        assert forbidden_token not in content, (
            f"Token proibido/URL inventada '{forbidden_token}' encontrado em {file_path.name}"
        )


def test_adversarial_real_log_ecossistema_pdf_url_present_across_catalog_and_docs(
    repo_root: Path, catalog: SourceCatalog
) -> None:
    """Garante que o link oficial real de 2026 do log do ecossistema está presente e testado."""
    real_pdf_url = (
        "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/"
        "log-do-ecossistema/@@display-file/file/log-do-ecossistema.pdf"
    )
    assert catalog.resolve_url("ecossistema_urna_log_docs", election_year=2026) == real_pdf_url

    for rel_path in (
        Path("configs/sources.yml"),
        Path("docs/source_inventory.md"),
        Path("docs/data_dictionary.md"),
    ):
        content = (repo_root / rel_path).read_text(encoding="utf-8")
        assert real_pdf_url in content, f"URL real {real_pdf_url} ausente em {rel_path}"


def test_adversarial_no_bronze_prefix_and_schema_policies_enforced(
    repo_root: Path, catalog: SourceCatalog
) -> None:
    """Garante ausência do prefixo bronze_ e conformidade estrita dos schemas 1:1."""
    for source_id, entry in catalog.sources.items():
        assert not entry.target_table.startswith("bronze_"), (
            f"target_table '{entry.target_table}' de '{source_id}' não pode ter prefixo bronze_"
        )

    monitored_paths = [
        repo_root / "configs" / "sources.yml",
        repo_root / "docs" / "source_inventory.md",
        repo_root / "docs" / "data_dictionary.md",
        repo_root / "notebooks" / "01_urna_logs_poc" / "01_urna_logs_poc.ipynb",
    ]
    for path in monitored_paths:
        text = path.read_text(encoding="utf-8")
        assert "bronze_" not in text, f"Prefixo proibido 'bronze_' encontrado em {path}"

    # fact_urna_logs mantém message_text (IDs 5+ dígitos mascarados) e sem mac_code
    log_doc_entry = catalog.get("ecossistema_urna_log_docs")
    tot_entry = catalog.get("totalizacao_arquivos_transmitidos")
    assert log_doc_entry.target_table == "fact_urna_logs"
    assert tot_entry.target_table == "fact_urna_logs"
    assert "message_text" in log_doc_entry.expected_columns
    assert "mac_code" not in log_doc_entry.expected_columns

    dictionary_doc = (repo_root / "docs" / "data_dictionary.md").read_text(encoding="utf-8")
    notebook_text = (
        repo_root / "notebooks" / "01_urna_logs_poc" / "01_urna_logs_poc.ipynb"
    ).read_text(encoding="utf-8")
    assert "<ID_REDACTED>" in dictionary_doc
    assert "<ID_REDACTED>" in notebook_text

    # comparecimento_abstencao (redistribution_allowed: true)
    elo_entry = catalog.get("comparecimento_abstencao")
    assert elo_entry.target_table == "fact_comparecimento_abstencao"
    assert elo_entry.redistribution_allowed is True

