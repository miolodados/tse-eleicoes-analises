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
        assert entry.url_template.startswith("https://cdn.tse.jus.br/")
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
    assert "eleicoes2026" in bu_2026
    assert "bweb_1t_AC_2026.zip" in bu_2026

    tot_2022 = catalog.resolve_url(
        "totalizacao_arquivos_transmitidos", election_year=2022, turn=2, uf="SP"
    )
    assert "eleicoes2022" in tot_2022
    assert "2022_2t_SP.zip" in tot_2022

    cfg = ExecutionConfig(election_year=2024, turn=1, uf="RJ")
    entry = catalog.get("correspondencias_esperadas_efetivadas")
    assert "2024_1t_RJ.zip" in entry.resolve_for_config(cfg)
    assert (
        entry.resolve_ckan_slug(2026)
        == "resultados-2026-correspondencias-esperadas-e-efetivadas"
    )


def test_comparecimento_abstencao_license_restriction_guard(
    catalog: SourceCatalog,
) -> None:
    elo_entry = catalog.get("comparecimento_abstencao")
    assert elo_entry.license_status == "unspecified_no_license"
    assert elo_entry.redistribution_allowed is False
    assert "Nenhuma Licença Fornecida" in elo_entry.license_notes

    with pytest.raises(LicenseRestrictionError, match="comparecimento_abstencao"):
        assert_redistribution_allowed(elo_entry)

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

    # Verifica presença explícita da restrição de licença do Sistema ELO e parametrização
    assert "unspecified_no_license" in inventory_doc
    assert "Nenhuma Licença Fornecida" in inventory_doc
    assert "election_year" in inventory_doc

    # Verifica presença de todas as tabelas fato, agregadas e dimensões no dicionário de dados
    expected_tables = [
        "fact_urna_event",
        "fact_voting_session",
        "agg_voting_session_metrics",
        "fact_bu_record",
        "fact_result_section",
        "fact_electorate_profile",
        "fact_turnout_profile",
        "bridge_urna_section",
        "dim_geography",
        "dim_section",
        "dim_time",
        "dim_candidate",
        "dim_party",
    ]
    for table_name in expected_tables:
        assert table_name in dictionary_doc, f"Tabela '{table_name}' ausente em data_dictionary.md"
