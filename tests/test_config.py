"""Unit tests for configuration loading and validation."""

import json
from pathlib import Path

import pytest

from redwood_dataagent.config import AgentConfig, load_config
from redwood_dataagent.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_all_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset env vars used by load_config() and seed required baseline defaults."""
    for var in (
        "AGENT_MODE",
        "AGENCY",
        "TRANSFER_SESSION_ID",
        "TENANT",
        "ENVIRONMENT",
        "AWS_REGION",
        "LOG_LEVEL",
        "SENDER_DATA_DIRECTORY",
        "SFTP_ENDPOINTS",
        "SFTP_USERNAME",
        "SFTP_PRIVATE_KEY",
        "SENDER_INPUT_MODE",
        "SENDER_QUERY_INPUT_JSON",
        "DATAPRODUCT_REQUEST_JSON",
        "MAX_QUERY_ROW_LIMIT",
        "MAX_QUERY_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("SFTP_ENDPOINTS", "sftp.example.com")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv(
        "SFTP_PRIVATE_KEY",
        "-----BEGIN OPENSSH PRIVATE KEY-----\\nabc\\n-----END OPENSSH PRIVATE KEY-----",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_request_payload(filename: str = "sample-sender-request.json") -> str:
    request_path = _repo_root() / "config" / "dataproducts" / "examples" / "requests" / filename
    return request_path.read_text(encoding="utf-8")


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
    assert config.dataproduct_request is None


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


def test_load_config_adapter_mode_uses_sender_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter mode loads sender settings for outbound execution."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "adapter")
    monkeypatch.setenv("AGENCY", "dot")

    config = load_config()

    assert config.agent_mode == "adapter"
    assert config.sender_agency == "dot"
    assert config.receiver_agency == ""
    assert config.sftp_endpoints == ["sftp.example.com"]


def test_load_config_is_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentConfig is frozen – direct attribute assignment raises FrozenInstanceError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENCY", "gsa")
    config = load_config()

    with pytest.raises(Exception):  # noqa: B017 # dataclasses.FrozenInstanceError
        config.agent_mode = "sender"  # type: ignore[misc]


def test_load_config_sender_input_mode_default_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """SENDER_INPUT_MODE defaults to blank and is normalized by sender workflow."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")

    config = load_config()

    assert config.sender_input_mode == ""


def test_load_config_sender_input_mode_preserves_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured SENDER_INPUT_MODE value is loaded as provided."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SENDER_INPUT_MODE", "QUERY")

    config = load_config()

    assert config.sender_input_mode == "QUERY"


def test_load_config_dataproduct_request_json_returns_normalized_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATAPRODUCT_REQUEST_JSON is parsed into a typed normalized request."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")

    payload = json.loads(_load_request_payload())
    payload["dataproduct_id"] = "  DOT_CONTRACT_EXTRACT  "
    monkeypatch.setenv("DATAPRODUCT_REQUEST_JSON", json.dumps(payload))

    config = load_config()

    assert config.dataproduct_request_json
    assert config.dataproduct_request is not None
    assert config.dataproduct_request.dataproduct_id == "dot_contract_extract"


def test_load_config_invalid_dataproduct_request_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid DATAPRODUCT_REQUEST_JSON fails fast during config load."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("DATAPRODUCT_REQUEST_JSON", "{}")

    with pytest.raises(ConfigurationError, match="Schema validation failed"):
        load_config()


def test_load_config_query_caps_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Global query caps default when env vars are not provided."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")

    config = load_config()

    assert config.max_query_row_limit == 1_000_000
    assert config.max_query_timeout_seconds == 600


def test_load_config_query_caps_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Global query caps are loaded from env when explicitly set."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("MAX_QUERY_ROW_LIMIT", "250000")
    monkeypatch.setenv("MAX_QUERY_TIMEOUT_SECONDS", "240")

    config = load_config()

    assert config.max_query_row_limit == 250000
    assert config.max_query_timeout_seconds == 240


def test_load_config_query_caps_invalid_non_numeric_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-numeric query cap env vars raise ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("MAX_QUERY_ROW_LIMIT", "abc")

    with pytest.raises(ConfigurationError, match="MAX_QUERY_ROW_LIMIT"):
        load_config()


def test_load_config_query_caps_invalid_non_positive_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-positive query cap env vars raise ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("MAX_QUERY_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigurationError, match="MAX_QUERY_TIMEOUT_SECONDS"):
        load_config()


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
    monkeypatch.setenv("SENDER_DATA_DIRECTORY", "s3://bucket/outgoing/")
    monkeypatch.setenv("ENVIRONMENT", "dev")

    config = load_config()

    assert config.sender_data_directory == "s3://tts-core-dev-dot-data-staging/file_mode/outgoing/"


def test_load_config_sender_data_directory_derived_from_sender_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sender data directory defaults to the derived sender staging outgoing prefix."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "dev")

    config = load_config()

    assert config.sender_staging_bucket == "tts-core-dev-dot-data-staging"
    assert config.sender_data_directory == "s3://tts-core-dev-dot-data-staging/file_mode/outgoing/"


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


# ---------------------------------------------------------------------------
# SFTP Configuration
# ---------------------------------------------------------------------------


def test_load_config_sftp_endpoints_single_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS can be a single IP address."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50")

    config = load_config()

    assert config.sftp_endpoints == ["10.0.1.50"]


def test_load_config_sftp_endpoints_multiple_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS can be comma-separated IPs for failover."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50,10.0.2.50,10.0.3.50")

    config = load_config()

    assert config.sftp_endpoints == ["10.0.1.50", "10.0.2.50", "10.0.3.50"]


def test_load_config_sftp_endpoints_dns_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS can be a DNS name."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "sftp.example.com")

    config = load_config()

    assert config.sftp_endpoints == ["sftp.example.com"]


def test_load_config_sftp_endpoints_multiple_dns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS can be comma-separated DNS names."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "sftp-1.example.com,sftp-2.example.com")

    config = load_config()

    assert config.sftp_endpoints == ["sftp-1.example.com", "sftp-2.example.com"]


def test_load_config_sftp_endpoints_whitespace_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS values are trimmed of surrounding whitespace."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "  10.0.1.50 , 10.0.2.50  ")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv(
        "SFTP_PRIVATE_KEY", "-----BEGIN OPENSSH PRIVATE KEY-----\\nabc\\n-----END OPENSSH PRIVATE KEY-----"
    )

    config = load_config()

    assert config.sftp_endpoints == ["10.0.1.50", "10.0.2.50"]


def test_load_config_sftp_endpoints_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS is required only in sender mode."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.delenv("SFTP_ENDPOINTS", raising=False)
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv("SFTP_PRIVATE_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="SFTP_ENDPOINTS"):
        load_config()


def test_load_config_sftp_endpoints_blank_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank SFTP_ENDPOINTS raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "   ")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv("SFTP_PRIVATE_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="SFTP_ENDPOINTS"):
        load_config()


def test_load_config_sftp_endpoints_empty_values_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_ENDPOINTS with empty values after split raises ConfigurationError."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50,,10.0.2.50")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv("SFTP_PRIVATE_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="empty values"):
        load_config()


def test_load_config_sftp_username_and_private_key_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sender mode loads SFTP username/private key directly from env vars."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv(
        "SFTP_PRIVATE_KEY", "-----BEGIN OPENSSH PRIVATE KEY-----\\nabc\\n-----END OPENSSH PRIVATE KEY-----"
    )

    config = load_config()

    assert config.sftp_username == "dot-sender"
    assert "BEGIN OPENSSH PRIVATE KEY" in config.sftp_private_key


def test_load_config_sftp_username_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_USERNAME is required in sender mode."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50")
    monkeypatch.delenv("SFTP_USERNAME", raising=False)
    monkeypatch.setenv("SFTP_PRIVATE_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="SFTP_USERNAME"):
        load_config()


def test_load_config_sftp_private_key_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFTP_PRIVATE_KEY is required in sender mode."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.delenv("SFTP_PRIVATE_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="SFTP_PRIVATE_KEY"):
        load_config()


def test_load_config_sftp_full_scenario(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full SFTP configuration scenario with multiple endpoints and env credentials."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "sender")
    monkeypatch.setenv("AGENCY", "dot")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("SFTP_ENDPOINTS", "10.0.1.50,10.0.2.50,10.0.3.50")
    monkeypatch.setenv("SFTP_USERNAME", "dot-sender")
    monkeypatch.setenv(
        "SFTP_PRIVATE_KEY", "-----BEGIN OPENSSH PRIVATE KEY-----\\nabc\\n-----END OPENSSH PRIVATE KEY-----"
    )

    config = load_config()

    assert config.sftp_endpoints == ["10.0.1.50", "10.0.2.50", "10.0.3.50"]
    assert config.sftp_username == "dot-sender"
    assert config.agent_mode == "sender"
    assert config.environment == "dev"


def test_load_config_receiver_does_not_require_sftp_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receiver mode should load without sender-specific SFTP settings."""
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("AGENT_MODE", "receiver")
    monkeypatch.setenv("AGENCY", "gsa")
    monkeypatch.delenv("SFTP_ENDPOINTS", raising=False)
    monkeypatch.delenv("SFTP_USERNAME", raising=False)
    monkeypatch.delenv("SFTP_PRIVATE_KEY", raising=False)

    config = load_config()

    assert config.sftp_endpoints == []
    assert config.sftp_username == ""
    assert config.sftp_private_key == ""
