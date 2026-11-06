"""Configuração transversal de execução, parametrização eleitoral e política de particionamento."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ELECTION_YEAR: int = 2026
SUPPORTED_ELECTION_YEARS: tuple[int, ...] = (2022, 2024, 2026)
VALID_TURNS: tuple[int, ...] = (1, 2)
VALID_UFS: tuple[str, ...] = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
    "BR",
    "ZZ",
)

ALLOWED_PARTITION_KEYS: tuple[str, ...] = ("election_year", "turn", "uf")
FORBIDDEN_PARTITION_KEYS: tuple[str, ...] = (
    "section_num",
    "section",
    "urna_serial",
    "urna",
    "municipio_code",
    "municipio",
    "raw_timestamp",
    "timestamp",
)
FORBIDDEN_PARTITION_TOKENS: tuple[str, ...] = (
    "section",
    "urna",
    "municipio",
    "timestamp",
)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_partition_keys(partition_keys: Sequence[str]) -> tuple[str, ...]:
    """Valida a política de particionamento Parquet.

    Permite apenas combinações de ('election_year', 'turn', 'uf') ou ('turn', 'uf'),
    rejeitando explicitamente chaves por seção, urna, município ou timestamp.
    """
    if not partition_keys:
        raise ValueError(
            "A lista de chaves de particionamento (partition_keys) não pode ser vazia."
        )

    normalized = tuple(str(k).strip() for k in partition_keys)
    for key in normalized:
        lowered = key.lower()
        if lowered in FORBIDDEN_PARTITION_KEYS or any(
            token in lowered for token in FORBIDDEN_PARTITION_TOKENS
        ):
            raise ValueError(
                f"Chave de particionamento proibida '{key}'. "
                f"Particionamento permitido apenas por {ALLOWED_PARTITION_KEYS}."
            )
        if key not in ALLOWED_PARTITION_KEYS:
            raise ValueError(
                f"Chave de particionamento inválida '{key}'. "
                f"Chaves permitidas: {ALLOWED_PARTITION_KEYS}."
            )

    allowed_combinations = {
        ("turn", "uf"),
        ("election_year", "turn", "uf"),
    }
    if normalized not in allowed_combinations:
        raise ValueError(
            f"Combinação de particionamento '{normalized}' não suportada. "
            "Use ('turn', 'uf') ou ('election_year', 'turn', 'uf')."
        )

    return normalized


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Parâmetros transversais de execução para ingestão, inspeção e processamento."""

    election_year: int = DEFAULT_ELECTION_YEAR
    turn: int = 1
    uf: str = "BR"
    partition_keys: Sequence[str] = field(default_factory=lambda: ALLOWED_PARTITION_KEYS)
    parquet_compression: str = "zstd"
    parquet_compression_level: int = 5
    config_dir: Path = field(default_factory=lambda: _default_repo_root() / "configs")
    data_dir: Path = field(default_factory=lambda: _default_repo_root() / "data")

    def __post_init__(self) -> None:
        if (
            isinstance(self.election_year, bool)
            or not isinstance(self.election_year, int)
            or self.election_year not in SUPPORTED_ELECTION_YEARS
        ):
            raise ValueError(
                f"election_year inválido: {self.election_year!r}. "
                f"Anos suportados: {SUPPORTED_ELECTION_YEARS}."
            )

        if isinstance(self.turn, bool) or self.turn not in VALID_TURNS:
            raise ValueError(f"turn inválido: {self.turn!r}. Valores suportados: {VALID_TURNS}.")

        normalized_uf = str(self.uf).strip().upper()
        if normalized_uf not in VALID_UFS:
            raise ValueError(
                f"uf inválida: {self.uf!r}. Siglas oficiais suportadas: {VALID_UFS}."
            )
        object.__setattr__(self, "uf", normalized_uf)

        validated_keys = validate_partition_keys(self.partition_keys)
        object.__setattr__(self, "partition_keys", validated_keys)

        object.__setattr__(self, "config_dir", Path(self.config_dir))
        object.__setattr__(self, "data_dir", Path(self.data_dir))

    @property
    def partition_path(self) -> str:
        """Retorna o caminho relativo de partição Hive-style (ex.: election_year=2026/turn=1/uf=SP)."""  # noqa: E501
        values = {
            "election_year": str(self.election_year),
            "turn": str(self.turn),
            "uf": self.uf,
        }
        return "/".join(f"{key}={values[key]}" for key in self.partition_keys)

    @property
    def sources_catalog_path(self) -> Path:
        """Retorna o caminho para o catálogo declarativo configs/sources.yml."""
        return self.config_dir / "sources.yml"

    def resolve_table_partition_dir(
        self, table_name: str, base_dir: Path | None = None
    ) -> Path:
        """Resolve o diretório físico de partição Parquet para uma tabela analítica."""
        root = Path(base_dir) if base_dir is not None else self.data_dir
        return root / table_name / self.partition_path
