"""CLI entrypoint for running the Redwood Data Agent package."""

from __future__ import annotations

import signal
import sys
import time
import traceback

from .adapter import app as adapter_app
from .agent import run_agent
from .config import load_config
from .logging_utils import (
    configure_logging,
    get_logger,
    prefix_log_message,
    set_agent_mode,
    set_transfer_session_id,
)


def main() -> int:
    """Load configuration, initialize logging, and execute the agent.

    After successful execution, idles indefinitely to prevent pod restart loops.
    The pod will be restarted by Flux on deployment updates or manually by scaling.
    """
    try:
        # Configure logging FIRST before using logger, so any startup errors are visible
        # Print to stdout/stderr directly before logging is configured
        print("Starting Redwood Data Agent...", file=sys.stdout, flush=True)

        # Load initial configuration from environment variables + defaults to get log level
        # This config is used only for initial logging setup; each transfer gets its own
        initial_config = load_config()

        # Configure JSON logging with the specified log level
        # NOW logging is ready for all subsequent logs
        configure_logging(initial_config.log_level)

        # Get logger after logging is configured
        logger = get_logger("redwood_dataagent")

        logger.info(
            prefix_log_message(
                "Redwood Data Agent initializing",
                agent_mode=initial_config.agent_mode,
            ),
            extra={
                "event": "agent_start",
                "agent_mode": initial_config.agent_mode,
                "environment": initial_config.environment,
            },
        )

        # Route to adapter HTTP server or scheduler loop based on agent mode
        if initial_config.agent_mode == "adapter":
            import os

            import uvicorn

            adapter_host = os.getenv("ADAPTER_HOST", "0.0.0.0")  # noqa: S104
            adapter_port = int(os.getenv("ADAPTER_PORT", "8080"))
            logger.info(
                prefix_log_message("Starting adapter HTTP server", agent_mode="adapter"),
                extra={"event": "adapter_server_start", "host": adapter_host, "port": adapter_port},
            )
            uvicorn.run(adapter_app, host=adapter_host, port=adapter_port, log_config=None, access_log=False)
            return 0

        # Run agent on 5-minute scheduler loop for long-running stateless deployment
        logger.info(
            prefix_log_message(
                "Starting 5-minute scheduler loop",
                agent_mode=initial_config.agent_mode,
            ),
            extra={
                "event": "scheduler_start",
                "agent_mode": initial_config.agent_mode,
                "interval_seconds": 300,
            },
        )

        scheduler_interval = 300  # 5 minutes in seconds

        def handle_sigterm(signum, frame):
            """Handle SIGTERM gracefully - exit the scheduler loop."""
            logger.info("SIGTERM received, shutting down gracefully")
            raise KeyboardInterrupt()

        # Register SIGTERM handler for graceful shutdown
        signal.signal(signal.SIGTERM, handle_sigterm)

        try:
            while True:
                # Load fresh config for each transfer to get a new transfer_session_id
                # (unless TRANSFER_SESSION_ID is explicitly set in environment)
                config = load_config()

                # Inject transfer session ID into logging context (all logs will auto-include this)
                # This enables correlation of all logs for this transfer across the entire pipeline
                set_agent_mode(config.agent_mode)
                set_transfer_session_id(config.transfer_session_id)

                logger.info(
                    prefix_log_message(
                        "Executing agent workflow",
                        agent_mode=config.agent_mode,
                        transfer_session_id=config.transfer_session_id,
                    ),
                    extra={"event": "workflow_start", "agent_mode": config.agent_mode},
                )
                result = run_agent(config)

                if result == 0:
                    logger.info(
                        prefix_log_message(
                            f"Agent workflow completed, sleeping {scheduler_interval}s until next run",
                            agent_mode=config.agent_mode,
                            transfer_session_id=config.transfer_session_id,
                        ),
                        extra={
                            "event": "agent_sleep",
                            "agent_mode": config.agent_mode,
                            "sleep_seconds": scheduler_interval,
                        },
                    )
                else:
                    logger.error(
                        prefix_log_message(
                            f"Agent workflow failed with exit code {result}, sleeping {scheduler_interval}s until retry",
                            agent_mode=config.agent_mode,
                            transfer_session_id=config.transfer_session_id,
                        ),
                        extra={
                            "event": "agent_failure",
                            "agent_mode": config.agent_mode,
                            "exit_code": result,
                            "sleep_seconds": scheduler_interval,
                        },
                    )

                # Sleep until next scheduled run
                time.sleep(scheduler_interval)
        except KeyboardInterrupt:
            logger.info(prefix_log_message("Scheduler loop terminated, agent shutting down"))
            return 0

    except Exception as e:
        # Catch any exceptions during startup or execution and log them to stderr
        # This ensures we see startup errors even if logging isn't configured yet
        error_msg = f"Fatal error in Redwood Data Agent: {e}\n{traceback.format_exc()}"
        print(error_msg, file=sys.stderr, flush=True)

        # Try to log via logger if it's available
        try:
            logger = get_logger("redwood_dataagent")
            logger.error(
                "Fatal error during agent execution",
                extra={
                    "event": "agent_fatal_error",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        except Exception:
            # If logger isn't available, logging error already went to stderr above
            pass

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
