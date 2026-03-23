from __future__ import annotations

"""CLI entrypoint for running the Redwood Data Agent package."""

from .agent import run_agent
from .config import load_config
from .logging_utils import configure_logging, set_transfer_session_id


def main() -> int:
    """Load configuration, initialize logging, and execute the agent."""
    # Load configuration from environment variables + defaults
    config = load_config()

    # Configure JSON logging with the specified log level
    configure_logging(config.log_level)

    # Inject transfer session ID into logging context (all logs will auto-include this)
    # This enables correlation of all logs for this transfer across the entire pipeline
    set_transfer_session_id(config.transfer_session_id)

    # Execute agent with fully configured context
    return run_agent(config)


if __name__ == "__main__":
    raise SystemExit(main())
