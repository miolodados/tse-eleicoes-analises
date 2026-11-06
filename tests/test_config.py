"""Testes unitários para tse_analysis.config (parametrização 2026/histórica e partições)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tse_analysis.config import (
    DEFAULT_ELECTION_YEAR,
    ExecutionConfig,
    validate_partition_keys,
)


def test_default_execution_config_uses_2026_cycle() -> None:
    cfg = ExecutionConfig()
    assert cfg.election_year == 2026
    assert cfg.election_year == DEFAULT_ELECTION_YEAR
    assert cfg.turn == 1
    assert cfg.uf == "BR"
    assert cfg.partition_keys == ("election_year", "turn", "uf")
    assert cfg.partition_path == "election_year=2026/turn=1/uf=BR"
    assert cfg.parquet_compression == "zstd"
    assert cfg.parquet_compression_level == 5


@pytest.mark.parametrize("year", [2022, 2024, 2026])
def test_execution_config_extensibility_across_election_years(
    year: int, tmp_path: Path
) -> None:
    cfg = ExecutionConfig(election_year=year, turn=2, uf="sp", data_dir=tmp_path)
    assert cfg.election_year == year
    assert cfg.turn == 2
    assert cfg.uf == "SP"
    assert cfg.partition_path == f"election_year={year}/turn=2/uf=SP"

    table_dir = cfg.resolve_table_partition_dir("fact_urna_event")
    assert table_dir == tmp_path / "fact_urna_event" / f"election_year={year}" / "turn=2" / "uf=SP"


def test_execution_config_supports_turn_uf_partition_scheme() -> None:
    cfg = ExecutionConfig(election_year=2026, turn=1, uf="AC", partition_keys=("turn", "uf"))
    assert cfg.partition_path == "turn=1/uf=AC"


@pytest.mark.parametrize(
    "forbidden_keys",
    [
        ("election_year", "turn", "uf", "section_num"),
        ("turn", "uf", "urna_serial"),
        ("turn", "uf", "municipio_code"),
        ("turn", "uf", "raw_timestamp"),
        ("section",),
        ("urna",),
        ("municipio",),
        ("timestamp",),
        (),
    ],
)
def test_validate_partition_keys_rejects_forbidden_keys(
    forbidden_keys: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        validate_partition_keys(forbidden_keys)

    with pytest.raises(ValueError):
        ExecutionConfig(partition_keys=forbidden_keys)


@pytest.mark.parametrize(
    ("kwargs", "match_pattern"),
    [
        ({"election_year": 1998}, "election_year inválido"),
        ({"election_year": True}, "election_year inválido"),
        ({"turn": 3}, "turn inválido"),
        ({"turn": 0}, "turn inválido"),
        ({"turn": False}, "turn inválido"),
        ({"uf": "XX"}, "uf inválida"),
    ],
)
def test_execution_config_rejects_invalid_parameters(
    kwargs: dict[str, object], match_pattern: str
) -> None:
    with pytest.raises(ValueError, match=match_pattern):
        ExecutionConfig(**kwargs)  # type: ignore[arg-type]
