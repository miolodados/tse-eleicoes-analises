"""Submódulo de inventário, catálogo declarativo, inspeção em streaming e relatórios."""

from tse_analysis.inventory.catalog import (
    REQUIRED_SOURCE_IDS,
    VALID_LICENSE_STATUSES,
    CatalogValidationError,
    LicenseRestrictionError,
    SourceCatalog,
    SourceEntry,
    assert_redistribution_allowed,
    load_source_catalog,
)
from tse_analysis.inventory.inspector import (
    MAX_HEADER_SAMPLE_BYTES,
    HeaderInspectionResult,
    build_unavailable_result,
    detect_encoding_and_extract_header,
    inspect_csv_file,
    inspect_csv_stream,
    inspect_remote_source,
    inspect_zip_file,
    inspect_zip_stream,
    validate_header_keys,
)
from tse_analysis.inventory.report import (
    INVENTORY_INSPECTION_SCHEMA,
    SECTION_TURN_KEY_SCHEMA,
    format_inspection_markdown_table,
    results_to_polars,
    results_to_pyarrow,
)

__all__ = [
    "CatalogValidationError",
    "HeaderInspectionResult",
    "INVENTORY_INSPECTION_SCHEMA",
    "LicenseRestrictionError",
    "MAX_HEADER_SAMPLE_BYTES",
    "REQUIRED_SOURCE_IDS",
    "SECTION_TURN_KEY_SCHEMA",
    "SourceCatalog",
    "SourceEntry",
    "VALID_LICENSE_STATUSES",
    "assert_redistribution_allowed",
    "build_unavailable_result",
    "detect_encoding_and_extract_header",
    "format_inspection_markdown_table",
    "inspect_csv_file",
    "inspect_csv_stream",
    "inspect_remote_source",
    "inspect_zip_file",
    "inspect_zip_stream",
    "load_source_catalog",
    "results_to_polars",
    "results_to_pyarrow",
    "validate_header_keys",
]
