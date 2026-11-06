"""Catálogo declarativo de fontes CKAN do TSE e governança programática de licenças."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tse_analysis.config import (
    DEFAULT_ELECTION_YEAR,
    VALID_TURNS,
    VALID_UFS,
    ExecutionConfig,
    validate_partition_keys,
)

REQUIRED_SOURCE_IDS: tuple[str, ...] = (
    "totalizacao_arquivos_transmitidos",
    "ecossistema_urna_log_docs",
    "resultados_boletim_urna",
    "resultados_apuracao_secao",
    "eleitorado_perfil",
    "comparecimento_abstencao",
    "correspondencias_esperadas_efetivadas",
)

VALID_LICENSE_STATUSES: tuple[str, ...] = (
    "open_documented",
    "unspecified_no_license",
    "restricted",
)

REQUIRED_ENTRY_FIELDS: tuple[str, ...] = (
    "source_id",
    "title",
    "ckan_dataset_slug",
    "url_template",
    "supported_years",
    "file_format",
    "expected_encoding",
    "delimiter",
    "native_grain",
    "target_table",
    "natural_keys",
    "filter_rules",
    "license_status",
    "license_notes",
    "redistribution_allowed",
)


class CatalogValidationError(ValueError):
    """Erro lançado quando o catálogo configs/sources.yml viola o schema obrigatório."""


class LicenseRestrictionError(PermissionError):
    """Erro lançado quando há tentativa de redistribuir dados brutos sem licença aberta."""


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """Metadados e regras de governança de uma família de fontes primárias do TSE."""

    source_id: str
    title: str
    ckan_dataset_slug: str
    url_template: str
    supported_years: tuple[int, ...]
    file_format: str
    expected_encoding: str
    delimiter: str | None
    native_grain: str
    target_table: str
    natural_keys: tuple[str, ...]
    filter_rules: dict[str, Any]
    license_status: str
    license_notes: str
    redistribution_allowed: bool
    inner_artifacts: tuple[str, ...] = field(default_factory=tuple)
    expected_columns: tuple[str, ...] = field(default_factory=tuple)

    def resolve_url(
        self,
        election_year: int = DEFAULT_ELECTION_YEAR,
        turn: int = 1,
        uf: str = "BR",
    ) -> str:
        """Interpola o template de URL da fonte para (election_year, turn, uf)."""
        if election_year not in self.supported_years:
            raise ValueError(
                f"Ano eleitoral {election_year} não suportado pela fonte '{self.source_id}'. "
                f"Suportados: {self.supported_years}."
            )
        if turn not in VALID_TURNS:
            raise ValueError(f"Turno inválido: {turn!r}. Valores suportados: {VALID_TURNS}.")

        normalized_uf = str(uf).strip().upper()
        if normalized_uf not in VALID_UFS:
            raise ValueError(f"UF inválida: {uf!r}. Valores suportados: {VALID_UFS}.")

        return self.url_template.format(
            election_year=election_year,
            turn=turn,
            uf=normalized_uf,
        )

    def resolve_ckan_slug(self, election_year: int = DEFAULT_ELECTION_YEAR) -> str:
        """Interpola o identificador de pacote CKAN para o ano eleitoral informado."""
        if election_year not in self.supported_years:
            raise ValueError(
                f"Ano eleitoral {election_year} não suportado pela fonte '{self.source_id}'."
            )
        return self.ckan_dataset_slug.format(election_year=election_year)

    def resolve_for_config(self, config: ExecutionConfig) -> str:
        """Resolve a URL da fonte a partir de uma instância de ExecutionConfig."""
        return self.resolve_url(
            election_year=config.election_year,
            turn=config.turn,
            uf=config.uf,
        )


@dataclass(frozen=True, slots=True)
class SourceCatalog:
    """Catálogo declarativo completo das fontes primárias do TSE."""

    schema_version: str
    default_election_year: int
    supported_election_years: tuple[int, ...]
    allowed_partition_keys: tuple[str, ...]
    forbidden_partition_keys: tuple[str, ...]
    sources: dict[str, SourceEntry]

    def get(self, source_id: str) -> SourceEntry:
        """Retorna uma entrada do catálogo pelo seu source_id."""
        if source_id not in self.sources:
            raise KeyError(f"Fonte '{source_id}' não encontrada no catálogo.")
        return self.sources[source_id]

    def resolve_url(
        self,
        source_id: str,
        election_year: int = DEFAULT_ELECTION_YEAR,
        turn: int = 1,
        uf: str = "BR",
    ) -> str:
        """Resolve a URL parametrizada de uma fonte específica do catálogo."""
        entry = self.get(source_id)
        return entry.resolve_url(election_year=election_year, turn=turn, uf=uf)


def assert_redistribution_allowed(source: SourceEntry) -> None:
    """Verifica se uma fonte pode ter seus dados brutos republicados/redistribuídos.

    Lança LicenseRestrictionError caso redistribution_allowed seja False ou
    license_status não permita redistribuição aberta.
    """
    if not source.redistribution_allowed or source.license_status != "open_documented":
        raise LicenseRestrictionError(
            f"Redistribuição de dados brutos bloqueada para a fonte '{source.source_id}' "
            f"(license_status='{source.license_status}', "
            f"redistribution_allowed={source.redistribution_allowed}). "
            f"Motivo: {source.license_notes}"
        )


def _validate_and_build_entry(source_key: str, raw: Any) -> SourceEntry:
    if not isinstance(raw, dict):
        raise CatalogValidationError(
            f"Entrada da fonte '{source_key}' deve ser um mapeamento YAML válido."
        )

    for field_name in REQUIRED_ENTRY_FIELDS:
        if field_name not in raw:
            raise CatalogValidationError(
                f"Fonte '{source_key}' inválida: campo obrigatório ausente '{field_name}'."
            )
        if field_name != "delimiter" and raw[field_name] is None:
            raise CatalogValidationError(
                f"Fonte '{source_key}' inválida: campo obrigatório '{field_name}' está nulo."
            )

    source_id = str(raw["source_id"]).strip()
    if source_id != source_key:
        raise CatalogValidationError(
            f"Inconsistência de chave na fonte '{source_key}': source_id='{source_id}'."
        )

    native_grain = str(raw["native_grain"]).strip()
    if not native_grain:
        raise CatalogValidationError(
            f"Fonte '{source_id}' inválida: 'native_grain' não pode ser vazio."
        )

    natural_keys_raw = raw["natural_keys"]
    if not isinstance(natural_keys_raw, list) or not natural_keys_raw:
        raise CatalogValidationError(
            f"Fonte '{source_id}' inválida: 'natural_keys' deve ser uma lista não-vazia."
        )

    license_status = str(raw["license_status"]).strip()
    if license_status not in VALID_LICENSE_STATUSES:
        raise CatalogValidationError(
            f"Fonte '{source_id}' inválida: 'license_status'='{license_status}' "
            f"fora de {VALID_LICENSE_STATUSES}."
        )

    redistribution_allowed = raw["redistribution_allowed"]
    if not isinstance(redistribution_allowed, bool):
        raise CatalogValidationError(
            f"Fonte '{source_id}' inválida: 'redistribution_allowed' deve ser booleano."
        )

    if license_status == "unspecified_no_license" and redistribution_allowed:
        raise CatalogValidationError(
            f"Fonte '{source_id}' possui license_status='unspecified_no_license' "
            "e não pode permitir redistribuição bruta (redistribution_allowed deve ser false)."
        )

    if source_id == "comparecimento_abstencao" and (
        license_status != "unspecified_no_license" or redistribution_allowed is not False
    ):
        raise CatalogValidationError(
            "A fonte 'comparecimento_abstencao' (Sistema ELO) deve ter "
            "license_status='unspecified_no_license' e redistribution_allowed=false."
        )

    if source_id == "totalizacao_arquivos_transmitidos":
        filter_rules = raw.get("filter_rules") or {}
        if filter_rules.get("situacao") != "Totalizado":
            raise CatalogValidationError(
                "A fonte 'totalizacao_arquivos_transmitidos' exige regra de filtro "
                "situacao == 'Totalizado'."
            )

    supported_years = tuple(int(y) for y in raw["supported_years"])
    inner_artifacts = tuple(str(x) for x in raw.get("inner_artifacts", []))
    expected_columns = tuple(str(x) for x in raw.get("expected_columns", []))

    return SourceEntry(
        source_id=source_id,
        title=str(raw["title"]).strip(),
        ckan_dataset_slug=str(raw["ckan_dataset_slug"]).strip(),
        url_template=str(raw["url_template"]).strip(),
        supported_years=supported_years,
        file_format=str(raw["file_format"]).strip(),
        expected_encoding=str(raw["expected_encoding"]).strip(),
        delimiter=str(raw["delimiter"]) if raw["delimiter"] is not None else None,
        native_grain=native_grain,
        target_table=str(raw["target_table"]).strip(),
        natural_keys=tuple(str(k).strip() for k in natural_keys_raw),
        filter_rules=dict(raw["filter_rules"]),
        license_status=license_status,
        license_notes=str(raw["license_notes"]).strip(),
        redistribution_allowed=redistribution_allowed,
        inner_artifacts=inner_artifacts,
        expected_columns=expected_columns,
    )


def load_source_catalog(
    catalog_path: str | Path | None = None,
    *,
    require_all_standard_sources: bool = True,
) -> SourceCatalog:
    """Carrega e valida o catálogo declarativo configs/sources.yml."""
    if catalog_path is None:
        resolved_path = ExecutionConfig().sources_catalog_path
    else:
        resolved_path = Path(catalog_path)

    if not resolved_path.exists():
        raise FileNotFoundError(f"Arquivo de catálogo não encontrado: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)

    if not isinstance(payload, dict):
        raise CatalogValidationError("O conteúdo de sources.yml deve ser um objeto YAML raiz.")

    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, dict) or not raw_sources:
        raise CatalogValidationError("O catálogo deve conter uma seção 'sources' não-vazia.")

    entries: dict[str, SourceEntry] = {}
    for source_key, raw_entry in raw_sources.items():
        entries[source_key] = _validate_and_build_entry(source_key, raw_entry)

    if require_all_standard_sources:
        missing_sources = [s for s in REQUIRED_SOURCE_IDS if s not in entries]
        if missing_sources:
            raise CatalogValidationError(
                f"Catálogo incompleto. Fontes obrigatórias ausentes: {missing_sources}."
            )

    partition_policy = payload.get("partition_policy") or {}
    allowed_keys = validate_partition_keys(
        partition_policy.get("allowed_keys", ("election_year", "turn", "uf"))
    )
    forbidden_keys = tuple(
        str(k)
        for k in partition_policy.get(
            "forbidden_keys",
            ("section_num", "urna_serial", "municipio_code", "raw_timestamp"),
        )
    )

    return SourceCatalog(
        schema_version=str(payload.get("schema_version", "1.0")),
        default_election_year=int(payload.get("default_election_year", DEFAULT_ELECTION_YEAR)),
        supported_election_years=tuple(
            int(y) for y in payload.get("supported_election_years", (2022, 2024, 2026))
        ),
        allowed_partition_keys=allowed_keys,
        forbidden_partition_keys=forbidden_keys,
        sources=entries,
    )
