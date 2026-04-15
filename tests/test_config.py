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
        "AGENCY",
        "TRANSFER_SESSION_ID",
        "TENANT",
        "ENVIRONMENT",
        "AWS_REGION",
        "LOG_LEVEL",
        "SENDER_DATA_DIRECTORY",
    ):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

def test_load_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-agency defaults are applied correctly; AGENCY must be explicitly set."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "gsa")

    config = load_config()

    assert config.agent_mode == "receiver"
    assert config.sender_agency == ""  # not applicable in receiver mode
    assert config.receiver_agency == "gsa"
    assert config.tenant == "tts"
    assert config.environment == "development"
    assert config.aws_region == "us-east-1"
    assert config.log_level == "INFO"
    assert config.transfer_session_id  # auto-generated UUID is non-empty
    assert config.sender_data_directory == ""  # not applicable in receiver mode


def test_load_config_missing_agency_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENCY is strictly required — omitting it raises ConfigurationError."""
    _clear_all_env(monkeypatch)

    with pytest.raises(ConfigurationError, match="AGENCY"):
        load_config()


def test_load_config_returns_agent_config_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """load_config() always returns an AgentConfig dataclass."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")
    assert isinstance(load_config(), AgentConfig)


def test_load_config_is_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentConfig is frozen – direct attribute assignment raises FrozenInstanceError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")
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
    monkeypatch.setenv("AGENCY", "dot")

    config = load_config()

    assert config.agent_mode == "sender"


def test_load_config_agent_mode_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_MODE value is normalised to lowercase before validation."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "SENDER")
    monkeypatch.setenv("AGENCY", "dot")

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

def test_load_config_agency_sender_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENCY is mapped to sender_agency when AGENT_MODE=sender."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "faa")

    config = load_config()

    assert config.sender_agency == "faa"
    assert config.receiver_agency == ""  # not applicable in sender mode


def test_load_config_agency_receiver_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENCY is mapped to receiver_agency when AGENT_MODE=receiver."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "hud")

    config = load_config()

    assert config.receiver_agency == "hud"
    assert config.sender_agency == ""  # not applicable in receiver mode


def test_load_config_agency_names_normalised_to_lowercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENCY value is stored in lowercase regardless of input case."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "DOT")

    config = load_config()

    assert config.sender_agency == "dot"


def test_load_config_blank_agency_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank AGENCY value raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "   ")

    with pytest.raises(ConfigurationError, match="AGENCY"):
        load_config()


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def test_load_config_blank_environment_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank ENVIRONMENT value raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.setenv("ENVIRONMENT", "   ")

    with pytest.raises(ConfigurationError, match="ENVIRONMENT"):
        load_config()


# ---------------------------------------------------------------------------
# Derived bucket names
# ---------------------------------------------------------------------------

def test_load_config_sender_staging_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default DOT sender staging bucket follows the naming convention."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")

    config = load_config()

    assert config.sender_staging_bucket == "tts-core-development-dot-data-staging"


def test_load_config_receiver_landing_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """GSA receiver landing bucket follows the naming convention."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")

    config = load_config()

    assert config.receiver_landing_bucket == "tts-core-development-gsa-data-landing"


def test_load_config_receiver_target_bucket_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """GSA receiver target bucket follows the naming convention."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")

    config = load_config()

    assert config.receiver_target_bucket == "tts-core-development-gsa-data-target"


def test_load_config_sender_bucket_reflects_custom_agency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sender staging bucket is derived from AGENCY in sender mode."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "faa")
    monkeypatch.setenv("ENVIRONMENT", "prod")

    config = load_config()

    assert config.sender_staging_bucket == "tts-core-prod-faa-data-staging"
    assert config.receiver_landing_bucket == ""
    assert config.receiver_target_bucket == ""


def test_load_config_receiver_buckets_reflect_custom_agency(monkeypatch: pytest.MonkeyPatch) -> None:
    """Receiver buckets are derived from AGENCY in receiver mode."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "hud")
    monkeypatch.setenv("ENVIRONMENT", "prod")

    config = load_config()

    assert config.sender_staging_bucket == ""
    assert config.receiver_landing_bucket == "tts-core-prod-hud-data-landing"
    assert config.receiver_target_bucket == "tts-core-prod-hud-data-target"


def test_load_config_environment_propagates_to_sender_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing ENVIRONMENT is reflected in the sender staging bucket name."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    config = load_config()

    assert "staging" in config.sender_staging_bucket


def test_load_config_environment_propagates_to_receiver_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing ENVIRONMENT is reflected in the receiver bucket names."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    config = load_config()

    assert "staging" in config.receiver_landing_bucket
    assert "staging" in config.receiver_target_bucket


def test_load_config_day1_dot_sender_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Day 1 MVP DOT sender pod: AGENCY=dot, AGENT_MODE=sender."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("TRANSFER_SESSION_ID", "transfer-20260327-001")

    config = load_config()

    assert config.agent_mode == "sender"
    assert config.sender_agency == "dot"
    assert config.receiver_agency == ""
    assert config.environment == "dev"
    assert config.transfer_session_id == "transfer-20260327-001"
    assert config.sender_staging_bucket == "tts-core-dev-dot-data-staging"
    assert config.receiver_landing_bucket == ""
    assert config.receiver_target_bucket == ""


def test_load_config_day1_gsa_receiver_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Day 1 MVP GSA receiver pod: AGENCY=gsa, AGENT_MODE=receiver."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("TRANSFER_SESSION_ID", "transfer-20260327-001")

    config = load_config()

    assert config.agent_mode == "receiver"
    assert config.receiver_agency == "gsa"
    assert config.sender_agency == ""
    assert config.environment == "dev"
    assert config.receiver_landing_bucket == "tts-core-dev-gsa-data-landing"
    assert config.receiver_target_bucket == "tts-core-dev-gsa-data-target"
    assert config.sender_staging_bucket == ""


# ---------------------------------------------------------------------------
# transfer_session_id
# ---------------------------------------------------------------------------

def test_load_config_generates_transfer_session_id_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UUID is auto-generated when TRANSFER_SESSION_ID is not set."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")

    config = load_config()

    assert config.transfer_session_id
    assert len(config.transfer_session_id) > 0


def test_load_config_uses_provided_transfer_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied TRANSFER_SESSION_ID is preserved verbatim."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.setenv("TRANSFER_SESSION_ID", "transfer-20260327-001")

    config = load_config()

    assert config.transfer_session_id == "transfer-20260327-001"


def test_load_config_unique_session_ids_generated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call without a supplied ID generates a unique transfer_session_id."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")

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
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    config = load_config()

    assert config.log_level == "DEBUG"


def test_load_config_sender_data_directory_ignores_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sender data directory is always derived from sender staging bucket."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SENDER_DATA_DIRECTORY", "s3://bucket/incoming/")
    monkeypatch.setenv("ENVIRONMENT", "dev")

    config = load_config()

    assert config.sender_data_directory == "s3://tts-core-dev-dot-data-staging/incoming/"


def test_load_config_sender_data_directory_derived_from_sender_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sender data directory defaults to the derived sender staging incoming prefix."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "dev")

    config = load_config()

    assert config.sender_staging_bucket == "tts-core-dev-dot-data-staging"
    assert config.sender_data_directory == "s3://tts-core-dev-dot-data-staging/incoming/"


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
