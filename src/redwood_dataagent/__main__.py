from __future__ import annotations

"""CLI entrypoint for running the Redwood Data Agent package."""

import signal
import time

from .agent import run_agent
from .config import load_config
from .logging_utils import configure_logging, set_transfer_session_id, get_logger


def main() -> int:
    """Load configuration, initialize logging, and execute the agent.
    
    After successful execution, idles indefinitely to prevent pod restart loops.
    The pod will be restarted by Flux on deployment updates or manually by scaling.
    """
    logger = get_logger("redwood_dataagent")
    
    # Load configuration from environment variables + defaults
    config = load_config()

    # Configure JSON logging with the specified log level
    configure_logging(config.log_level)

    # Inject transfer session ID into logging context (all logs will auto-include this)
    # This enables correlation of all logs for this transfer across the entire pipeline
    set_transfer_session_id(config.transfer_session_id)

    # Execute agent with fully configured context
    result = run_agent(config)

    if result == 0:
        # Successful execution - idle to prevent restart loop
        logger.info(
            "Agent workflow completed successfully, idling until next event or pod restart",
            extra={"event": "agent_idle_start"},
        )
        # Sleep forever - pod will be restarted by Flux or manual intervention
        try:
            signal.pause()  # Waits for SIGTERM on pod deletion
        except KeyboardInterrupt:
            logger.info("Agent interrupted, shutting down")
            return 0
    
    return result


if __name__ == "__main__":
    raise SystemExit(main())
