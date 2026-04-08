"""Tests for redwood_dataagent.__main__ module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from redwood_dataagent.__main__ import main
from redwood_dataagent.config import AgentConfig, ConfigurationError


class TestMainEntrypoint:
    """Tests for main() CLI entrypoint."""

    def test_main_sender_success(self) -> None:
        """main() runs sender workflow successfully."""
        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="development",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="session-123",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="tts-core-development-dot-data-staging",
            receiver_landing_bucket="tts-core-development-gsa-data-landing",
            receiver_target_bucket="tts-core-development-gsa-data-target",
            sender_data_directory=None,
        )

        with patch("redwood_dataagent.__main__.load_config") as mock_load_config:
            with patch("redwood_dataagent.__main__.run_agent") as mock_run_agent:
                mock_load_config.return_value = config
                mock_run_agent.return_value = 0
                
                exit_code = main()
                
                assert exit_code == 0
                mock_load_config.assert_called_once()
                mock_run_agent.assert_called_once_with(config)

    def test_main_receiver_success(self) -> None:
        """main() runs receiver workflow successfully."""
        config = AgentConfig(
            agent_mode="receiver",
            tenant="tts",
            environment="development",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="session-456",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="tts-core-development-dot-data-staging",
            receiver_landing_bucket="tts-core-development-gsa-data-landing",
            receiver_target_bucket="tts-core-development-gsa-data-target",
            sender_data_directory=None,
        )

        with patch("redwood_dataagent.__main__.load_config") as mock_load_config:
            with patch("redwood_dataagent.__main__.run_agent") as mock_run_agent:
                mock_load_config.return_value = config
                mock_run_agent.return_value = 0
                
                exit_code = main()
                
                assert exit_code == 0
                mock_run_agent.assert_called_once_with(config)

    def test_main_workflow_error(self) -> None:
        """main() propagates workflow errors."""
        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="development",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="session-123",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="tts-core-development-dot-data-staging",
            receiver_landing_bucket="tts-core-development-gsa-data-landing",
            receiver_target_bucket="tts-core-development-gsa-data-target",
            sender_data_directory=None,
        )

        with patch("redwood_dataagent.__main__.load_config") as mock_load_config:
            with patch("redwood_dataagent.__main__.run_agent") as mock_run_agent:
                mock_load_config.return_value = config
                mock_run_agent.return_value = 1  # Error
                
                exit_code = main()
                
                assert exit_code == 1

    def test_main_configuration_error(self) -> None:
        """main() handles configuration errors."""
        with patch("redwood_dataagent.__main__.load_config") as mock_load_config:
            mock_load_config.side_effect = ConfigurationError("Missing AGENT_MODE")
            
            with pytest.raises(ConfigurationError):
                main()
