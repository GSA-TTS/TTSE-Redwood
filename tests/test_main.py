"""Tests for CLI entrypoint in redwood_dataagent.__main__."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from redwood_dataagent import __main__ as main_module


def _config(agent_mode: str = "sender", session_id: str = "sess-001") -> SimpleNamespace:
    """Build a lightweight config object used by entrypoint tests."""
    return SimpleNamespace(
        log_level="INFO",
        agent_mode=agent_mode,
        environment="dev",
        transfer_session_id=session_id,
    )


class TestMainEntrypoint:
    """Behavioral tests for main()."""

    def test_main_runs_one_successful_cycle_then_keyboard_interrupt(self) -> None:
        """main exits cleanly when interrupted after one successful run."""
        initial_config = _config()
        run_config = _config(session_id="sess-002")

        mock_logger = MagicMock()

        with patch.object(main_module, "load_config", side_effect=[initial_config, run_config]), \
             patch.object(main_module, "configure_logging"), \
             patch.object(main_module, "get_logger", return_value=mock_logger), \
             patch.object(main_module, "set_agent_mode"), \
             patch.object(main_module, "set_transfer_session_id"), \
             patch.object(main_module, "run_agent", return_value=0), \
             patch.object(main_module.signal, "signal"), \
             patch.object(main_module.time, "sleep", side_effect=KeyboardInterrupt):
            exit_code = main_module.main()

        assert exit_code == 0

    def test_main_logs_failure_branch_then_exits_on_interrupt(self) -> None:
        """Non-zero run result logs failure branch before graceful shutdown."""
        initial_config = _config()
        run_config = _config(session_id="sess-003")

        mock_logger = MagicMock()

        with patch.object(main_module, "load_config", side_effect=[initial_config, run_config]), \
             patch.object(main_module, "configure_logging"), \
             patch.object(main_module, "get_logger", return_value=mock_logger), \
             patch.object(main_module, "set_agent_mode"), \
             patch.object(main_module, "set_transfer_session_id"), \
             patch.object(main_module, "run_agent", return_value=7), \
             patch.object(main_module.signal, "signal"), \
             patch.object(main_module.time, "sleep", side_effect=KeyboardInterrupt):
            exit_code = main_module.main()

        assert exit_code == 0
        assert mock_logger.error.called

    def test_main_returns_one_on_startup_exception(self) -> None:
        """Unhandled startup errors return non-zero exit code."""
        with patch.object(main_module, "load_config", side_effect=RuntimeError("boom")), \
             patch.object(main_module, "get_logger", return_value=MagicMock()):
            exit_code = main_module.main()

        assert exit_code == 1

    def test_main_returns_one_when_logger_is_unavailable_in_error_path(self) -> None:
        """Fatal-path logger acquisition failure is swallowed and still returns 1."""
        with patch.object(main_module, "load_config", side_effect=RuntimeError("boom")), \
             patch.object(main_module, "get_logger", side_effect=RuntimeError("logger unavailable")):
            exit_code = main_module.main()

        assert exit_code == 1

    def test_main_registered_sigterm_handler_triggers_graceful_shutdown(self) -> None:
        """Registered SIGTERM handler logs and exits via KeyboardInterrupt."""
        initial_config = _config()
        run_config = _config(session_id="sess-004")
        mock_logger = MagicMock()
        captured_handler = {"fn": None}

        def _signal_side_effect(_sig: int, handler):
            captured_handler["fn"] = handler
            return None

        def _sleep_side_effect(_seconds: int):
            handler = captured_handler["fn"]
            assert handler is not None
            handler(15, object())

        with patch.object(main_module, "load_config", side_effect=[initial_config, run_config]), \
             patch.object(main_module, "configure_logging"), \
             patch.object(main_module, "get_logger", return_value=mock_logger), \
             patch.object(main_module, "set_agent_mode"), \
             patch.object(main_module, "set_transfer_session_id"), \
             patch.object(main_module, "run_agent", return_value=0), \
             patch.object(main_module.signal, "signal", side_effect=_signal_side_effect), \
             patch.object(main_module.time, "sleep", side_effect=_sleep_side_effect):
            exit_code = main_module.main()

        assert exit_code == 0