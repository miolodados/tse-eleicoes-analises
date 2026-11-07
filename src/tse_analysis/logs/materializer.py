"""Materialização Polars/PyArrow, escrita Parquet ZSTD e staging efêmero de fact_urna_event."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa

from tse_analysis.config import ExecutionConfig, validate_partition_keys
from tse_analysis.logs.event_catalog import EventCatalog
from tse_analysis.logs.jez_reader import (
    JezExtractionResult,
    SectionTurnContext,
    extract_jez_events,
    extract_section_bundle_events,
    parse_section_keys_from_filename,
)
from tse_analysis.logs.line_parser import ParsedLogEvent

FACT_URNA_EVENT_POLARS_SCHEMA = pl.Schema(
    {
        "election_year": pl.Int16,
        "turn": pl.Int8,
        "uf": pl.String,
        "municipio_code": pl.Int32,
        "zone_num": pl.Int16,
        "section_num": pl.Int32,
        "urna_serial": pl.String,
        "file_seq": pl.Int64,
        "raw_timestamp": pl.Datetime("us"),
        "has_timestamp_regression": pl.Boolean,
        "application": pl.String,
        "log_level": pl.String,
        "event_code": pl.String,
        "biometric_attempt_num": pl.Int8,
    }
)

FACT_URNA_EVENT_SCHEMA = FACT_URNA_EVENT_POLARS_SCHEMA

FACT_URNA_EVENT_ARROW_SCHEMA = pa.schema(
    [
        pa.field("election_year", pa.int16(), nullable=False),
        pa.field("turn", pa.int8(), nullable=False),
        pa.field("uf", pa.string(), nullable=False),
        pa.field("municipio_code", pa.int32(), nullable=False),
        pa.field("zone_num", pa.int16(), nullable=False),
        pa.field("section_num", pa.int32(), nullable=False),
        pa.field("urna_serial", pa.string(), nullable=False),
        pa.field("file_seq", pa.int64(), nullable=False),
        pa.field("raw_timestamp", pa.timestamp("us"), nullable=True),
        pa.field("has_timestamp_regression", pa.bool_(), nullable=False),
        pa.field("application", pa.string(), nullable=False),
        pa.field("log_level", pa.string(), nullable=False),
        pa.field("event_code", pa.string(), nullable=False),
        pa.field("biometric_attempt_num", pa.int8(), nullable=True),
    ]
)


@dataclass(frozen=True, slots=True)
class UfBatchMaterializationReport:
    """Resumo da execução em batch de uma UF com staging efêmero e checkpoint manifest."""

    election_year: int
    turn: int
    uf: str
    availability_status: str
    packages_processed: int
    contingency_sections_count: int
    events_count: int | None
    parquet_path: Path | None
    manifest_path: Path
    staging_cleaned: bool


def _normalize_records(
    items: Sequence[ParsedLogEvent | JezExtractionResult | dict[str, Any]],
    section_context: SectionTurnContext | None = None,
) -> list[dict[str, Any]]:
    ctx = section_context if section_context is not None else SectionTurnContext()
    records: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, JezExtractionResult):
            records.extend(item.to_fact_records())
        elif isinstance(item, ParsedLogEvent):
            records.append(
                item.to_fact_record(
                    election_year=ctx.election_year,
                    turn=ctx.turn,
                    uf=ctx.uf,
                    municipio_code=ctx.municipio_code,
                    zone_num=ctx.zone_num,
                    section_num=ctx.section_num,
                )
            )
        elif isinstance(item, dict):
            records.append(
                {col: item.get(col) for col in FACT_URNA_EVENT_POLARS_SCHEMA.names()}
            )
        else:
            raise TypeError(f"Item incompatível para fact_urna_event: {type(item)!r}")
    return records


def events_to_polars(
    items: Sequence[ParsedLogEvent | JezExtractionResult | dict[str, Any]],
    *,
    section_context: SectionTurnContext | None = None,
) -> pl.DataFrame:
    """Converte eventos ou resultados de extração em polars.DataFrame validado pelo schema."""
    records = _normalize_records(items, section_context=section_context)
    if not records:
        return pl.DataFrame(schema=FACT_URNA_EVENT_POLARS_SCHEMA)
    return pl.DataFrame(records, schema=FACT_URNA_EVENT_POLARS_SCHEMA)


def events_to_pyarrow(
    items: Sequence[ParsedLogEvent | JezExtractionResult | dict[str, Any]],
    *,
    section_context: SectionTurnContext | None = None,
) -> pa.Table:
    """Converte eventos ou resultados de extração em pyarrow.Table estritamente tipada."""
    df = events_to_polars(items, section_context=section_context)
    return df.to_arrow().cast(FACT_URNA_EVENT_ARROW_SCHEMA)


def write_fact_urna_event_partition(
    df_or_items: pl.DataFrame | Sequence[ParsedLogEvent | JezExtractionResult | dict[str, Any]],
    *,
    config: ExecutionConfig,
    exports_dir: str | Path | None = None,
    filename: str = "part-00000.parquet",
    section_context: SectionTurnContext | None = None,
) -> Path:
    """Grava uma partição Parquet ZSTD de fact_urna_event validando chaves de particionamento."""
    validate_partition_keys(config.partition_keys)

    if isinstance(df_or_items, pl.DataFrame):
        df = df_or_items.cast(FACT_URNA_EVENT_POLARS_SCHEMA)
    else:
        df = events_to_polars(df_or_items, section_context=section_context)

    # Validação de schema PyArrow antes da persistência física
    _ = df.to_arrow().cast(FACT_URNA_EVENT_ARROW_SCHEMA)

    base_exports = (
        Path(exports_dir)
        if exports_dir is not None
        else (config.data_dir / "exports")
    )
    partition_dir = config.resolve_table_partition_dir(
        "fact_urna_event", base_dir=base_exports
    )
    partition_dir.mkdir(parents=True, exist_ok=True)
    output_path = partition_dir / filename

    df.write_parquet(
        output_path,
        compression=config.parquet_compression,
        compression_level=config.parquet_compression_level,
    )
    return output_path


def _update_checkpoint_manifest(
    manifest_path: Path,
    *,
    partition_key: str,
    entry_payload: dict[str, Any],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    else:
        current = {}

    if not isinstance(current, dict):
        current = {}
    partitions = current.setdefault("fact_urna_event", {})
    partitions[partition_key] = entry_payload
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(current, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, manifest_path)


def process_uf_staging_batch(
    *,
    config: ExecutionConfig,
    staging_uf_dir: str | Path | None = None,
    exports_dir: str | Path | None = None,
    catalog: EventCatalog | None = None,
    cleanup_staging: bool = True,
) -> UfBatchMaterializationReport:
    """Processa em batch os artefatos .jez/.zip de uma UF, grava Parquet ZSTD e limpa o staging."""
    validate_partition_keys(config.partition_keys)

    resolved_staging = (
        Path(staging_uf_dir)
        if staging_uf_dir is not None
        else (config.data_dir / "staging" / config.partition_path)
    )
    resolved_exports = (
        Path(exports_dir)
        if exports_dir is not None
        else (config.data_dir / "exports")
    )
    manifest_path = resolved_exports / "_checkpoints" / "manifest.json"
    partition_key = config.partition_path

    extraction_results: list[JezExtractionResult] = []
    seen_sections: set[tuple[int, int, int]] = set()
    if resolved_staging.exists():
        jez_files = sorted(resolved_staging.rglob("*.jez"))
        zip_files = sorted(resolved_staging.rglob("*.zip"))

        for jez_path in jez_files:
            inferred_ctx = parse_section_keys_from_filename(
                jez_path.name,
                election_year=config.election_year,
                turn=config.turn,
                uf=config.uf,
            ) or SectionTurnContext(
                election_year=config.election_year,
                turn=config.turn,
                uf=config.uf,
            )
            sec_key = (
                inferred_ctx.municipio_code,
                inferred_ctx.zone_num,
                inferred_ctx.section_num,
            )
            if sec_key != (0, 0, 0) and sec_key in seen_sections:
                continue
            res = extract_jez_events(
                jez_path,
                section_context=inferred_ctx,
                catalog=catalog,
                availability_status="AVAILABLE",
            )
            if res.events is not None:
                if sec_key != (0, 0, 0):
                    seen_sections.add(sec_key)
                extraction_results.append(res)

        for zip_path in zip_files:
            res = extract_section_bundle_events(
                zip_path,
                section_context=SectionTurnContext(
                    election_year=config.election_year,
                    turn=config.turn,
                    uf=config.uf,
                ),
                catalog=catalog,
                availability_status="AVAILABLE",
            )
            if res.events is not None:
                sec_key = (res.municipio_code, res.zone_num, res.section_num)
                if sec_key != (0, 0, 0) and sec_key in seen_sections:
                    continue
                if sec_key != (0, 0, 0):
                    seen_sections.add(sec_key)
                extraction_results.append(res)

    if not extraction_results:
        staging_cleaned = False
        if cleanup_staging and resolved_staging.exists():
            shutil.rmtree(resolved_staging)
            staging_cleaned = True

        _update_checkpoint_manifest(
            manifest_path,
            partition_key=partition_key,
            entry_payload={
                "election_year": config.election_year,
                "turn": config.turn,
                "uf": config.uf,
                "availability_status": "UNAVAILABLE",
                "packages_processed": 0,
                "contingency_sections_count": 0,
                "events_count": None,
                "parquet_path": None,
                "updated_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        return UfBatchMaterializationReport(
            election_year=config.election_year,
            turn=config.turn,
            uf=config.uf,
            availability_status="UNAVAILABLE",
            packages_processed=0,
            contingency_sections_count=0,
            events_count=None,
            parquet_path=None,
            manifest_path=manifest_path,
            staging_cleaned=staging_cleaned,
        )

    df = events_to_polars(extraction_results)
    parquet_path = write_fact_urna_event_partition(
        df,
        config=config,
        exports_dir=resolved_exports,
    )
    contingency_count = sum(
        1 for r in extraction_results if r.has_contingency_indicator
    )

    staging_cleaned = False
    if cleanup_staging and resolved_staging.exists():
        shutil.rmtree(resolved_staging)
        staging_cleaned = True

    _update_checkpoint_manifest(
        manifest_path,
        partition_key=partition_key,
        entry_payload={
            "election_year": config.election_year,
            "turn": config.turn,
            "uf": config.uf,
            "availability_status": "AVAILABLE",
            "packages_processed": len(extraction_results),
            "contingency_sections_count": contingency_count,
            "events_count": df.height,
            "parquet_path": str(parquet_path),
            "updated_at_utc": datetime.now(UTC).isoformat(),
        },
    )

    return UfBatchMaterializationReport(
        election_year=config.election_year,
        turn=config.turn,
        uf=config.uf,
        availability_status="AVAILABLE",
        packages_processed=len(extraction_results),
        contingency_sections_count=contingency_count,
        events_count=df.height,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        staging_cleaned=staging_cleaned,
    )
