"""Unit tests for the agent runtime entrypoints."""

from redwood_dataagent.agent import run_agent
from redwood_dataagent.config import AgentConfig


def test_run_agent_sender_returns_success() -> None:
    """Verify sender mode agent completes with exit code 0."""
    config = AgentConfig(
        agent_mode="sender",
        tenant="tts",
        environment="development",
        aws_region="us-east-1",
        log_level="INFO",
        transfer_session_id="session-123",
        sender_agency="dot",
        receiver_agency="gsa",
        sender_staging_bucket="dot-data-development-staging",
        receiver_landing_bucket="gsa-data-development-landing",
        receiver_target_bucket="gsa-data-development-target",
    )

    assert run_agent(config) == 0


def test_run_agent_receiver_returns_success() -> None:
    """Verify receiver mode agent completes with exit code 0."""
    config = AgentConfig(
        agent_mode="receiver",
        tenant="tts",
        environment="development",
        aws_region="us-east-1",
        log_level="INFO",
        transfer_session_id="session-456",
        sender_agency="dot",
        receiver_agency="gsa",
        sender_staging_bucket="dot-data-development-staging",
        receiver_landing_bucket="gsa-data-development-landing",
        receiver_target_bucket="gsa-data-development-target",
    )

    assert run_agent(config) == 0