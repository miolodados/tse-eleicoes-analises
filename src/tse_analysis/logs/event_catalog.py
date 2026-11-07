"""Catálogo declarativo de eventos de log da urna (allowlist semântica com zero PII)."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tse_analysis.config import ExecutionConfig

UNKNOWN_EVENT_CODE: str = "UNKNOWN_EVENT"
MALFORMED_LINE_CODE: str = "MALFORMED_LINE"

ALLOWED_EXTRACTOR_FIELDS: tuple[str, ...] = ("biometric_attempt_num",)

FORBIDDEN_EXTRACTOR_TOKENS: tuple[str, ...] = (
    "cpf",
    "titulo",
    "eleitor",
    "mesario",
    "message",
    "text",
    "mac",
    "voto",
    "votavel",
    "candidato",
)

REQUIRED_EVENT_CODES: tuple[str, ...] = (
    "LOGD_STARTED",
    "SECTION_OPENED",
    "VOTER_ENABLED",
    "BIOMETRIC_READ_ATTEMPT",
    "BIOMETRIC_RECOGNIZED",
    "BIOMETRIC_NOT_RECOGNIZED",
    "NO_BIOMETRIC_REGISTERED",
    "MANUAL_ENABLE_PATH",
    "INACTIVITY_TIMEOUT_45S",
    "INVALID_KEY_PRESSED",
    "CARGO_VOTE_RECORDED",
    "VOTER_VOTE_COMPUTED",
    "VOTING_SUSPENDED",
    "VOTING_RESUMED",
    "CONTINGENCY_EVENT",
    "SECTION_CLOSED",
)


class EventCatalogValidationError(ValueError):
    """Erro lançado quando configs/event_catalog.yml viola o contrato de allowlist e zero-PII."""


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Resultado sanitizado da classificação semântica de uma linha de log (sem texto livre)."""

    event_code: str
    biometric_attempt_num: int | None = None
    pattern_id: str | None = None


@dataclass(frozen=True, slots=True)
class EventPattern:
    """Regra compilada de classificação semântica da allowlist de eventos."""

    pattern_id: str
    event_code: str
    applications: tuple[str, ...]
    regex: str
    compiled_regex: re.Pattern[str]
    extractors: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def matches_application(self, application: str) -> bool:
        """Verifica se a regra se aplica ao aplicativo emissor do log."""
        if "*" in self.applications:
            return True
        normalized_app = application.strip().upper()
        return any(app.upper() == normalized_app for app in self.applications)


@dataclass(frozen=True, slots=True)
class EventCatalog:
    """Catálogo declarativo compilado para classificação de eventos do Ecossistema da Urna."""

    schema_version: str
    fallback_event_code: str
    malformed_event_code: str
    patterns: tuple[EventPattern, ...]

    @property
    def event_codes(self) -> frozenset[str]:
        """Retorna o conjunto de todos os event_codes declarados nas regras do catálogo."""
        return frozenset(p.event_code for p in self.patterns)

    def classify(
        self,
        message_text: str,
        application: str = "VOTA",
    ) -> ClassificationResult:
        """Classifica a mensagem em memória efêmera e descarta qualquer texto livre."""
        normalized_msg = message_text.strip()
        if not normalized_msg:
            return ClassificationResult(
                event_code=self.fallback_event_code,
                biometric_attempt_num=None,
                pattern_id=None,
            )

        for pattern in self.patterns:
            if not pattern.matches_application(application):
                continue

            match = pattern.compiled_regex.search(normalized_msg)
            if match is None:
                continue

            attempt_num: int | None = None
            group_name = pattern.extractors.get("biometric_attempt_num")
            if group_name:
                raw_val = match.groupdict().get(group_name)
                if raw_val is not None:
                    try:
                        parsed_int = int(raw_val)
                        if 1 <= parsed_int <= 127:
                            attempt_num = parsed_int
                    except ValueError:
                        attempt_num = None

            return ClassificationResult(
                event_code=pattern.event_code,
                biometric_attempt_num=attempt_num,
                pattern_id=pattern.pattern_id,
            )

        return ClassificationResult(
            event_code=self.fallback_event_code,
            biometric_attempt_num=None,
            pattern_id=None,
        )


def _validate_and_build_pattern(raw: Any, seen_pattern_ids: set[str]) -> EventPattern:
    if not isinstance(raw, dict):
        raise EventCatalogValidationError("Cada item em 'patterns' deve ser um objeto YAML.")

    for req_field in ("pattern_id", "event_code", "applications", "regex"):
        if req_field not in raw or raw[req_field] is None:
            raise EventCatalogValidationError(
                f"Regra de evento inválida: campo obrigatório ausente '{req_field}'."
            )

    pattern_id = str(raw["pattern_id"]).strip()
    if not pattern_id:
        raise EventCatalogValidationError("Campo 'pattern_id' não pode ser vazio.")
    if pattern_id in seen_pattern_ids:
        raise EventCatalogValidationError(f"pattern_id duplicado no catálogo: '{pattern_id}'.")
    seen_pattern_ids.add(pattern_id)

    event_code = str(raw["event_code"]).strip()
    if not event_code or not re.fullmatch(r"[A-Z][A-Z0-9_]*", event_code):
        raise EventCatalogValidationError(
            f"Regra '{pattern_id}' possui event_code inválido '{event_code}'. "
            "Use UPPER_SNAKE_CASE."
        )

    apps_raw = raw["applications"]
    if not isinstance(apps_raw, list) or not apps_raw:
        raise EventCatalogValidationError(
            f"Regra '{pattern_id}' deve definir 'applications' como lista não-vazia."
        )
    applications = tuple(str(app).strip() for app in apps_raw if str(app).strip())

    regex_str = str(raw["regex"])
    if not regex_str.strip():
        raise EventCatalogValidationError(f"Regra '{pattern_id}' possui regex vazia.")
    try:
        compiled = re.compile(regex_str)
    except re.error as exc:
        raise EventCatalogValidationError(
            f"Expressão regular inválida na regra '{pattern_id}': {exc}"
        ) from exc

    # Validação de grupos nomeados e extratores para impedir captura de PII ou texto livre
    for group_name in compiled.groupindex:
        lowered_group = group_name.lower()
        if any(token in lowered_group for token in FORBIDDEN_EXTRACTOR_TOKENS):
            raise EventCatalogValidationError(
                f"Regra '{pattern_id}' declara grupo regex proibido '{group_name}' "
                "(violação de política zero-PII/zero-texto-livre)."
            )

    extractors_raw = raw.get("extractors") or {}
    if not isinstance(extractors_raw, dict):
        raise EventCatalogValidationError(
            f"Campo 'extractors' na regra '{pattern_id}' deve ser um mapeamento."
        )

    extractors: dict[str, str] = {}
    for target_field, source_group in extractors_raw.items():
        field_str = str(target_field).strip()
        group_str = str(source_group).strip()
        lowered_field = field_str.lower()
        if (
            any(token in lowered_field for token in FORBIDDEN_EXTRACTOR_TOKENS)
            or field_str not in ALLOWED_EXTRACTOR_FIELDS
        ):
            raise EventCatalogValidationError(
                f"Regra '{pattern_id}' tenta extrair campo não permitido '{field_str}'. "
                f"Campos permitidos: {ALLOWED_EXTRACTOR_FIELDS}."
            )
        if group_str not in compiled.groupindex:
            raise EventCatalogValidationError(
                f"Regra '{pattern_id}' referencia grupo regex inexistente '{group_str}' "
                f"para o extrator '{field_str}'."
            )
        extractors[field_str] = group_str

    return EventPattern(
        pattern_id=pattern_id,
        event_code=event_code,
        applications=applications,
        regex=regex_str,
        compiled_regex=compiled,
        extractors=extractors,
        description=str(raw.get("description", "")).strip(),
    )


def load_event_catalog(
    catalog_path: str | Path | None = None,
    *,
    require_all_standard_codes: bool = True,
) -> EventCatalog:
    """Carrega, compila e valida o catálogo declarativo configs/event_catalog.yml."""
    if catalog_path is None:
        resolved_path = ExecutionConfig().config_dir / "event_catalog.yml"
    else:
        resolved_path = Path(catalog_path)

    if not resolved_path.exists():
        raise FileNotFoundError(f"Arquivo de catálogo de eventos não encontrado: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)

    if not isinstance(payload, dict):
        raise EventCatalogValidationError(
            "O conteúdo de event_catalog.yml deve ser um objeto YAML raiz."
        )

    raw_patterns = payload.get("patterns")
    if not isinstance(raw_patterns, list) or not raw_patterns:
        raise EventCatalogValidationError(
            "O catálogo de eventos deve conter uma lista não-vazia em 'patterns'."
        )

    seen_ids: set[str] = set()
    patterns = tuple(_validate_and_build_pattern(item, seen_ids) for item in raw_patterns)

    catalog = EventCatalog(
        schema_version=str(payload.get("schema_version", "1.0")),
        fallback_event_code=str(payload.get("fallback_event_code", UNKNOWN_EVENT_CODE)),
        malformed_event_code=str(payload.get("malformed_event_code", MALFORMED_LINE_CODE)),
        patterns=patterns,
    )

    if require_all_standard_codes:
        present_codes = catalog.event_codes
        missing = [code for code in REQUIRED_EVENT_CODES if code not in present_codes]
        if missing:
            raise EventCatalogValidationError(
                f"Catálogo de eventos incompleto. Códigos obrigatórios ausentes: {missing}."
            )

    return catalog


@functools.lru_cache(maxsize=1)
def _get_default_event_catalog() -> EventCatalog:
    return load_event_catalog()


def classify_log_message(
    message_text: str,
    application: str = "VOTA",
    *,
    catalog: EventCatalog | None = None,
) -> ClassificationResult:
    """Classifica uma mensagem de log contra a allowlist de configs/event_catalog.yml.

    Qualquer mensagem fora da allowlist recebe event_code = 'UNKNOWN_EVENT' e
    biometric_attempt_num = None, sem reter texto livre ou PII.
    """
    active_catalog = catalog if catalog is not None else _get_default_event_catalog()
    return active_catalog.classify(message_text=message_text, application=application)
