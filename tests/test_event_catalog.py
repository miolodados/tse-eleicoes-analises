"""Testes unitários do catálogo semântico configs/event_catalog.yml e sanitização zero-PII."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from tse_analysis.logs.event_catalog import (
    REQUIRED_EVENT_CODES,
    UNKNOWN_EVENT_CODE,
    EventCatalogValidationError,
    classify_log_message,
    load_event_catalog,
)


def test_load_event_catalog_contains_all_required_codes(repo_root: Path) -> None:
    """Valida o carregamento de configs/event_catalog.yml e a presença de todos os event_codes."""
    catalog = load_event_catalog(repo_root / "configs" / "event_catalog.yml")
    assert catalog.schema_version == "1.0"
    assert catalog.fallback_event_code == UNKNOWN_EVENT_CODE
    for req_code in REQUIRED_EVENT_CODES:
        assert req_code in catalog.event_codes


@pytest.mark.parametrize(
    ("message", "application", "expected_code", "expected_attempt"),
    [
        ("Início das operações do logd", "scue", "LOGD_STARTED", None),
        ("Urna pronta para receber votos", "VOTA", "SECTION_OPENED", None),
        ("Emissão da Zerésima concluída", "VOTA", "SECTION_OPENED", None),
        ("Eleitor foi habilitado", "VOTA", "VOTER_ENABLED", None),
        ("Tentativa de reconhecimento biométrico 1", "VOTA", "BIOMETRIC_READ_ATTEMPT", 1),
        ("Tentativa de leitura biométrica nº 2", "VOTA", "BIOMETRIC_READ_ATTEMPT", 2),
        ("Tentativa de identificação biométrica 4", "VOTA", "BIOMETRIC_READ_ATTEMPT", 4),
        ("Solicitação de digital do eleitor", "VOTA", "BIOMETRIC_READ_ATTEMPT", None),
        ("Biometria reconhecida", "VOTA", "BIOMETRIC_RECOGNIZED", None),
        ("Digital não reconhecida", "VOTA", "BIOMETRIC_NOT_RECOGNIZED", None),
        ("Não há biometria cadastrada para o eleitor", "VOTA", "NO_BIOMETRIC_REGISTERED", None),
        ("Eleitor sem biometria", "VOTA", "NO_BIOMETRIC_REGISTERED", None),
        ("Habilitação manual pelo mesário", "VOTA", "MANUAL_ENABLE_PATH", None),
        (
            "Tempo limite de inatividade de 45 segundos atingido",
            "VOTA",
            "INACTIVITY_TIMEOUT_45S",
            None,
        ),
        ("Inatividade por 45s", "VOTA", "INACTIVITY_TIMEOUT_45S", None),
        ("Acionamento de tecla indevida", "VOTA", "INVALID_KEY_PRESSED", None),
        ("Tecla inválida pressionada", "VOTA", "INVALID_KEY_PRESSED", None),
        ("Voto confirmado para o cargo", "VOTA", "CARGO_VOTE_RECORDED", None),
        ("O voto do eleitor foi computado", "VOTA", "VOTER_VOTE_COMPUTED", None),
        ("Votação suspensa temporariamente", "VOTA", "VOTING_SUSPENDED", None),
        ("Votação retomada", "VOTA", "VOTING_RESUMED", None),
        ("Modo de contingência ativado", "GAP", "CONTINGENCY_EVENT", None),
        ("Encerramento da votação na seção", "VOTA", "SECTION_CLOSED", None),
    ],
)
def test_classify_known_urna_messages(
    message: str,
    application: str,
    expected_code: str,
    expected_attempt: int | None,
) -> None:
    """Valida a classificação semântica das famílias obrigatórias de eventos da urna."""
    result = classify_log_message(message, application=application)
    assert result.event_code == expected_code
    assert result.biometric_attempt_num == expected_attempt
    assert result.pattern_id is not None


def test_classify_unknown_message_with_simulated_pii_sanitizes_completely() -> None:
    """Garante que mensagens fora da allowlist com PII simulado viram UNKNOWN_EVENT sem texto."""
    raw_sensitive = (
        "Mesário 123456789012 digitou CPF 99988877766 e título 112233445566 "
        "em operação interna não catalogada"
    )
    result = classify_log_message(raw_sensitive, application="VOTA")
    assert result.event_code == UNKNOWN_EVENT_CODE
    assert result.biometric_attempt_num is None
    assert result.pattern_id is None

    serialized = str(asdict(result))
    assert "123456789012" not in serialized
    assert "99988877766" not in serialized
    assert "112233445566" not in serialized
    assert "Mesário" not in serialized


def test_event_catalog_rejects_duplicate_pattern_id(tmp_path: Path) -> None:
    """Rejeita catálogo com pattern_id duplicado."""
    bad_catalog = {
        "schema_version": "1.0",
        "patterns": [
            {
                "pattern_id": "dup_id",
                "event_code": "VOTER_ENABLED",
                "applications": ["VOTA"],
                "regex": "(?i)eleitor foi habilitado",
            },
            {
                "pattern_id": "dup_id",
                "event_code": "VOTER_VOTE_COMPUTED",
                "applications": ["VOTA"],
                "regex": "(?i)voto computado",
            },
        ],
    }
    path = tmp_path / "bad_dup.yml"
    path.write_text(yaml.safe_dump(bad_catalog), encoding="utf-8")

    with pytest.raises(EventCatalogValidationError, match="pattern_id duplicado"):
        load_event_catalog(path, require_all_standard_codes=False)


def test_event_catalog_rejects_pii_or_free_text_extractor(tmp_path: Path) -> None:
    """Rejeita catálogo que tente extrair CPF, título de eleitor, mesário ou texto livre."""
    bad_catalog = {
        "schema_version": "1.0",
        "patterns": [
            {
                "pattern_id": "capture_pii_rule",
                "event_code": "VOTER_ENABLED",
                "applications": ["VOTA"],
                "regex": "(?i)eleitor (?P<cpf_eleitor>\\d+)",
                "extractors": {"cpf_eleitor": "cpf_eleitor"},
            }
        ],
    }
    path = tmp_path / "bad_pii.yml"
    path.write_text(yaml.safe_dump(bad_catalog), encoding="utf-8")

    with pytest.raises(EventCatalogValidationError, match="zero-PII|não permitido"):
        load_event_catalog(path, require_all_standard_codes=False)
