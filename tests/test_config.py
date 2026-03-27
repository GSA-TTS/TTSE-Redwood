"""Unit tests for configuration loading and validation."""

import pytest

from redwood_dataagent.config import AgentConfig, load_config
from redwood_dataagent.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_all_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that load_config() reads so tests start from a clean slate."""
    for var in (
        "AGENT_MODE",
        "SENDER_AGENCY",
        "RECEIVER_AGENCY",
        "TRANSFER_SESSION_ID",
        "TENANT",
        "ENVIRONMENT",
        "AWS_REGION",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

def test_load_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """All defaults are applied correctly when no env vars are set."""
    _clear_all_env(monkeypatch)

    config = load_config()

    assert config.agent_mode == "receiver"
    assert config.sender_agency == "dot"
    assert config.receiver_agency == "gsa"
    assert config.tenant == "tts"
    assert config.environment == "development"
    assert config.aws_region == "us-east-1"
    assert config.log_level == "INFO"
    assert config.transfer_session_id  # auto-generated UUID is non-empty


def test_load_config_returns_agent_config_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_config() always returns an AgentConfig dataclass."""
    _clear_all_env(monkeypatch)
    assert isinstance(load_config(), AgentConfig)


def test_load_config_is_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentConfig is frozen – direct attribute assignment raises FrozenInstanceError."""
    _clear_all_env(monkeypatch)
    config = load_config()

    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        config.agent_mode = "sender"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AGENT_MODE
# ---------------------------------------------------------------------------

def test_load_config_agent_mode_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_MODE=sender is accepted and stored in lowercase."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")

    config = load_config()

    assert config.agent_mode == "sender"


def test_load_config_agent_mode_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_MODE value is normalised to lowercase before validation."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "SENDER")

    config = load_config()

    assert config.agent_mode == "sender"


def test_load_config_invalid_agent_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised AGENT_MODE raises ConfigurationError."""
    monkeypatch.setenv("AGENT_MODE", "invalid")

    with pytest.raises(ConfigurationError, match="AGENT_MODE"):
        load_config()


# ---------------------------------------------------------------------------
# Agency names
# ---------------------------------------------------------------------------

def test_load_config_explicit_agencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom SENDER_AGENCY and RECEIVER_AGENCY are read from the environment."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("SENDER_AGENCY", "faa")
    monkeypatch.setenv("RECEIVER_AGENCY", "dot")

    config = load_config()

    assert config.sender_agency == "faa"
    assert config.receiver_agency == "dot"


def test_load_config_agency_names_normalised_to_lowercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agency names are stored in lowercase regardless of input case."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("SENDER_AGENCY", "DOT")
    monkeypatch.setenv("RECEIVER_AGENCY", "GSA")

    config = load_config()

    assert config.sender_agency == "dot"
    assert config.receiver_agency == "gsa"


def test_load_config_blank_sender_agency_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank SENDER_AGENCY value raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("SENDER_AGENCY", "   ")

    with pytest.raises(ConfigurationError, match="SENDER_AGENCY"):
        load_config()


def test_load_config_blank_receiver_agency_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank RECEIVER_AGENCY value raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("RECEIVER_AGENCY", "   ")

    with pytest.raises(ConfigurationError, match="RECEIVER_AGENCY"):
        load_config()


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def test_load_config_blank_environment_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank ENVIRONMENT value raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "   ")

    with pytest.raises(ConfigurationError, match="ENVIRONMENT"):
        load_config()


# ---------------------------------------------------------------------------
# Derived bucket names
# ---------------------------------------------------------------------------

def test_load_config_sender_staging_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default DOT sender staging bucket follows the naming convention."""
    _clear_all_env(monkeypatch)

    config = load_config()

    assert config.sender_staging_bucket == "dot-data-development-staging"


def test_load_config_receiver_landing_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default GSA receiver landing bucket follows the naming convention."""
    _clear_all_env(monkeypatch)

    config = load_config()

    assert config.receiver_landing_bucket == "gsa-data-development-landing"


def test_load_config_receiver_target_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default GSA receiver target bucket follows the naming convention."""
    _clear_all_env(monkeypatch)

    config = load_config()

    assert config.receiver_target_bucket == "gsa-data-development-target"


def test_load_config_buckets_reflect_custom_agencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bucket names are derived from the configured agency codes."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("SENDER_AGENCY", "faa")
    monkeypatch.setenv("RECEIVER_AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "prod")

    config = load_config()

    assert config.sender_staging_bucket == "faa-data-prod-staging"
    assert config.receiver_landing_bucket == "dot-data-prod-landing"
    assert config.receiver_target_bucket == "dot-data-prod-target"


def test_load_config_environment_propagates_to_all_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing ENVIRONMENT is reflected in all three derived bucket names."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "staging")

    config = load_config()

    assert "staging" in config.sender_staging_bucket
    assert "staging" in config.receiver_landing_bucket
    assert "staging" in config.receiver_target_bucket


def test_load_config_day1_dot_to_gsa_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full Day 1 MVP scenario: DOT sender → GSA receiver in dev environment."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("SENDER_AGENCY", "dot")
    monkeypatch.setenv("RECEIVER_AGENCY", "gsa")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("TRANSFER_SESSION_ID", "transfer-20260327-001")

    config = load_config()

    assert config.agent_mode == "sender"
    assert config.sender_agency == "dot"
    assert config.receiver_agency == "gsa"
    assert config.environment == "dev"
    assert config.transfer_session_id == "transfer-20260327-001"
    assert config.sender_staging_bucket == "dot-data-dev-staging"
    assert config.receiver_landing_bucket == "gsa-data-dev-landing"
    assert config.receiver_target_bucket == "gsa-data-dev-target"


# ---------------------------------------------------------------------------
# transfer_session_id
# ---------------------------------------------------------------------------

def test_load_config_generates_transfer_session_id_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UUID is auto-generated when TRANSFER_SESSION_ID is not set."""
    _clear_all_env(monkeypatch)

    config = load_config()

    assert config.transfer_session_id
    assert len(config.transfer_session_id) > 0


def test_load_config_uses_provided_transfer_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied TRANSFER_SESSION_ID is preserved verbatim."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("TRANSFER_SESSION_ID", "transfer-20260327-001")

    config = load_config()

    assert config.transfer_session_id == "transfer-20260327-001"


def test_load_config_unique_session_ids_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call without a supplied ID generates a unique transfer_session_id."""
    _clear_all_env(monkeypatch)

    config_a = load_config()
    config_b = load_config()

    assert config_a.transfer_session_id != config_b.transfer_session_id


# ---------------------------------------------------------------------------
# LOG_LEVEL normalisation
# ---------------------------------------------------------------------------

def test_load_config_log_level_normalised_to_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOG_LEVEL is stored in uppercase regardless of input case."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("LOG_LEVEL", "debug")

    config = load_config()

    assert config.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# ConfigurationError is a domain exception (not a bare ValueError)
# ---------------------------------------------------------------------------

def test_configuration_error_is_not_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ConfigurationError must not be a subclass of ValueError."""
    monkeypatch.setenv("AGENT_MODE", "bad")

    with pytest.raises(ConfigurationError):
        load_config()

    # Confirm it does NOT leak as a plain ValueError
    with pytest.raises(ConfigurationError):
        load_config()
    try:
        load_config()
    except ValueError:
        pytest.fail("load_config() raised ValueError instead of ConfigurationError")
    except ConfigurationError:
        pass  # expected
