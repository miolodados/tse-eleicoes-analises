"""Schemas Polars/PyArrow e geração de relatórios estruturados de inventário (Fase 0)."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import pyarrow as pa

from tse_analysis.inventory.inspector import HeaderInspectionResult

# Schema Polars do Relatório de Inspeção de Fontes (Fase 0)
INVENTORY_INSPECTION_SCHEMA = pl.Schema(
    {
        "source_id": pl.String,
        "election_year": pl.Int16,
        "turn": pl.Int8,
        "uf": pl.String,
        "availability_status": pl.String,
        "file_format": pl.String,
        "detected_encoding": pl.String,
        "detected_delimiter": pl.String,
        "member_count": pl.Int32,
        "has_log_jez": pl.Boolean,
        "header_columns": pl.List(pl.String),
        "missing_natural_keys": pl.List(pl.String),
        "is_valid_key_set": pl.Boolean,
        "license_status": pl.String,
        "redistribution_allowed": pl.Boolean,
    }
)

# Contrato de tipos canônicos PyArrow para a chave central section_turn
SECTION_TURN_KEY_SCHEMA = pa.schema(
    [
        pa.field("election_year", pa.int16(), nullable=False),
        pa.field("turn", pa.int8(), nullable=False),
        pa.field("uf", pa.string(), nullable=False),
        pa.field("municipio_code", pa.int32(), nullable=False),
        pa.field("zone_num", pa.int16(), nullable=False),
        pa.field("section_num", pa.int32(), nullable=False),
    ]
)


def results_to_polars(results: Sequence[HeaderInspectionResult]) -> pl.DataFrame:
    """Converte uma sequência de HeaderInspectionResult em um polars.DataFrame tipado."""
    if not results:
        return pl.DataFrame(schema=INVENTORY_INSPECTION_SCHEMA)

    records = [res.to_record() for res in results]
    return pl.DataFrame(records, schema=INVENTORY_INSPECTION_SCHEMA)


def results_to_pyarrow(results: Sequence[HeaderInspectionResult]) -> pa.Table:
    """Converte uma sequência de HeaderInspectionResult em uma pyarrow.Table."""
    df = results_to_polars(results)
    return df.to_arrow()


def format_inspection_markdown_table(results: Sequence[HeaderInspectionResult]) -> str:
    """Gera uma tabela Markdown resumindo os metadados estruturais inspecionados."""
    headers = (
        "| source_id | election_year | turn | uf | availability_status | "
        "encoding | delimiter | has_log_jez | is_valid_key_set | license_status | "
        "redistribution_allowed |"
    )
    separator = (
        "|---|---:|---:|---|---|---|---|---|---|---|---|"
    )
    lines = [headers, separator]
    for r in results:
        lines.append(
            f"| `{r.source_id}` | {r.election_year} | {r.turn} | {r.uf} | "
            f"`{r.availability_status}` | `{r.detected_encoding}` | `{r.detected_delimiter}` | "
            f"`{r.has_log_jez}` | `{r.is_valid_key_set}` | `{r.license_status}` | "
            f"`{r.redistribution_allowed}` |"
        )
    return "\n".join(lines)
