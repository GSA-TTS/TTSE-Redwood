from __future__ import annotations

"""CLI entrypoint for running the Redwood Data Agent package."""

from .agent import run_agent
from .config import load_config
from .logging_utils import configure_logging


def main() -> int:
    """Load configuration, initialize logging, and execute the agent."""
    config = load_config()
    configure_logging(config.log_level)
    return run_agent(config)


if __name__ == "__main__":
    raise SystemExit(main())