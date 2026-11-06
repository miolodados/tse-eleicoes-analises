"""Pacote principal tse-analysis para análise do comportamento eleitoral (dados públicos do TSE)."""

from tse_analysis.config import (
    ALLOWED_PARTITION_KEYS,
    DEFAULT_ELECTION_YEAR,
    FORBIDDEN_PARTITION_KEYS,
    SUPPORTED_ELECTION_YEARS,
    VALID_TURNS,
    VALID_UFS,
    ExecutionConfig,
    validate_partition_keys,
)

__version__ = "0.1.0"

__all__ = [
    "ALLOWED_PARTITION_KEYS",
    "DEFAULT_ELECTION_YEAR",
    "ExecutionConfig",
    "FORBIDDEN_PARTITION_KEYS",
    "SUPPORTED_ELECTION_YEARS",
    "VALID_TURNS",
    "VALID_UFS",
    "__version__",
    "validate_partition_keys",
]
