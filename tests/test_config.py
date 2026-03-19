"""Unit tests for configuration loading and validation."""

import os

import pytest

from redwood_dataagent.config import load_config


def test_load_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify config defaults when all env vars are absent."""
    monkeypatch.delenv("AGENT_MODE", raising=False)
    monkeypatch.delenv("TRANSFER_SESSION_ID", raising=False)
    monkeypatch.delenv("TENANT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    config = load_config()

    # Confirm defaults match expectations
    assert config.agent_mode == "receiver"
    assert config.tenant == "tts"
    assert config.environment == "development"
    assert config.aws_region == "us-east-1"
    assert config.log_level == "INFO"
    assert config.transfer_session_id


def test_load_config_invalid_agent_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify config rejects invalid AGENT_MODE values."""
    monkeypatch.setenv("AGENT_MODE", "invalid")

    with pytest.raises(ValueError):
        load_config()