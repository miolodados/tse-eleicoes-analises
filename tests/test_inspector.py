"""Testes unitários para o inspetor em streaming de ZIP/CSV e schemas Polars/PyArrow."""

from __future__ import annotations

from pathlib import Path

import httpx
import pyarrow as pa

from tests.conftest import SENSITIVE_ROW_SENTINEL
from tse_analysis.inventory.catalog import SourceCatalog
from tse_analysis.inventory.inspector import (
    inspect_csv_file,
    inspect_remote_source,
    inspect_zip_file,
    validate_header_keys,
)
from tse_analysis.inventory.report import (
    INVENTORY_INSPECTION_SCHEMA,
    SECTION_TURN_KEY_SCHEMA,
    format_inspection_markdown_table,
    results_to_polars,
    results_to_pyarrow,
)


def test_inspect_zip_with_latin1_csv_without_disk_extraction(
    zip_with_latin1_csv: Path,
    catalog: SourceCatalog,
    tmp_path: Path,
) -> None:
    bu_entry = catalog.get("resultados_boletim_urna")
    files_before = set(tmp_path.iterdir())

    result = inspect_zip_file(
        zip_with_latin1_csv,
        source_entry=bu_entry,
        election_year=2026,
        turn=1,
        uf="AC",
    )

    files_after = set(tmp_path.iterdir())
    assert files_before == files_after, "O inspetor não deve extrair arquivos do ZIP em disco"

    assert result.encoding == "latin1"
    assert result.delimiter == ";"
    assert result.member_count == 3
    assert result.extension_counts[".csv"] == 1
    assert result.extension_counts[".sha512"] == 1
    assert result.has_log_jez is False
    assert "ANO_ELEICAO" in result.header_columns
    assert "DS_OBSERVACAO_SEÇÃO" in result.header_columns
    assert result.missing_keys == ()
    assert result.is_valid_key_set is True


def test_inspect_utf8_csv_file_and_detect_missing_keys(
    utf8_csv_file: Path,
) -> None:
    result = inspect_csv_file(
        utf8_csv_file,
        source_id="resultados_apuracao_secao",
        election_year=2026,
        turn=1,
        uf="SP",
        expected_keys=("ANO_ELEICAO", "NR_TURNO", "SG_UF", "COLUNA_INEXISTENTE"),
    )
    assert result.encoding == "utf-8"
    assert result.delimiter == ";"
    assert result.missing_keys == ("COLUNA_INEXISTENTE",)
    assert result.is_valid_key_set is False
    assert "CD_MUNICIPIO" in result.extra_columns


def test_inspect_totalizacao_zip_detects_jez_presence_and_absence(
    zip_totalizacao_with_jez: Path,
    zip_totalizacao_without_jez: Path,
    catalog: SourceCatalog,
) -> None:
    tot_entry = catalog.get("totalizacao_arquivos_transmitidos")

    res_with_jez = inspect_zip_file(
        zip_totalizacao_with_jez,
        source_entry=tot_entry,
        election_year=2026,
        turn=1,
        uf="AC",
    )
    assert res_with_jez.has_log_jez is True
    assert res_with_jez.extension_counts[".jez"] == 1
    assert res_with_jez.extension_counts[".bu"] == 1
    assert res_with_jez.member_count == 5

    res_without_jez = inspect_zip_file(
        zip_totalizacao_without_jez,
        source_entry=tot_entry,
        election_year=2026,
        turn=1,
        uf="RR",
    )
    assert res_without_jez.has_log_jez is False
    assert res_without_jez.extension_counts.get(".jez", 0) == 0
    assert res_without_jez.member_count == 2


def test_validate_header_keys_maps_canonical_and_physical_columns() -> None:
    header = ("ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "QT_VOTOS")
    canonical_keys = ("election_year", "turn", "uf", "municipio_code", "zone_num", "section_num")
    missing, extra, is_valid = validate_header_keys(header, canonical_keys)
    assert missing == ()
    assert extra == ("QT_VOTOS",)
    assert is_valid is True


def test_unavailable_resource_never_infers_zero_occurrences(
    tmp_path: Path, catalog: SourceCatalog
) -> None:
    missing_zip = tmp_path / "nao_existe_2026.zip"
    tot_entry = catalog.get("totalizacao_arquivos_transmitidos")

    local_unavail = inspect_zip_file(
        missing_zip, source_entry=tot_entry, election_year=2026, turn=1, uf="AM"
    )
    assert local_unavail.availability_status == "UNAVAILABLE"
    assert local_unavail.member_count is None
    assert local_unavail.has_log_jez is None
    assert local_unavail.is_valid_key_set is None

    # Simula HTTP 404 no CDN do TSE para 2026 antes da publicação oficial
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with httpx.Client(transport=transport) as client:
        remote_unavail = inspect_remote_source(
            tot_entry, election_year=2026, turn=1, uf="AM", client=client
        )
    assert remote_unavail.availability_status == "UNAVAILABLE"
    assert remote_unavail.member_count is None
    assert remote_unavail.has_log_jez is None


def test_privacy_minimization_never_leaks_row_values_into_reports(
    zip_with_latin1_csv: Path,
    utf8_csv_file: Path,
    catalog: SourceCatalog,
) -> None:
    r1 = inspect_zip_file(
        zip_with_latin1_csv,
        source_entry=catalog.get("resultados_boletim_urna"),
        election_year=2026,
        turn=1,
        uf="AC",
    )
    r2 = inspect_csv_file(
        utf8_csv_file,
        source_entry=catalog.get("resultados_apuracao_secao"),
        election_year=2026,
        turn=1,
        uf="SP",
    )

    assert SENSITIVE_ROW_SENTINEL not in repr(r1)
    assert SENSITIVE_ROW_SENTINEL not in repr(r2)
    assert SENSITIVE_ROW_SENTINEL not in str(r1.to_record())

    df = results_to_polars([r1, r2])
    assert df.schema == INVENTORY_INSPECTION_SCHEMA
    assert df.height == 2

    arrow_table = results_to_pyarrow([r1, r2])
    assert isinstance(arrow_table, pa.Table)
    assert arrow_table.num_rows == 2

    md_table = format_inspection_markdown_table([r1, r2])
    assert SENSITIVE_ROW_SENTINEL not in md_table
    assert "resultados_boletim_urna" in md_table


def test_section_turn_key_schema_contract() -> None:
    expected_fields = [
        ("election_year", pa.int16()),
        ("turn", pa.int8()),
        ("uf", pa.string()),
        ("municipio_code", pa.int32()),
        ("zone_num", pa.int16()),
        ("section_num", pa.int32()),
    ]
    assert len(SECTION_TURN_KEY_SCHEMA) == len(expected_fields)
    for field, (name, dtype) in zip(SECTION_TURN_KEY_SCHEMA, expected_fields, strict=True):
        assert field.name == name
        assert field.type == dtype
        assert field.nullable is False
