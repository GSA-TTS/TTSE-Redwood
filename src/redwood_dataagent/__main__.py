from __future__ import annotations

"""CLI entrypoint for running the Redwood Data Agent package."""

import signal
import sys
import time
import traceback

from .agent import run_agent
from .config import load_config
from .logging_utils import configure_logging, set_transfer_session_id, get_logger


def main() -> int:
    """Load configuration, initialize logging, and execute the agent.
    
    After successful execution, idles indefinitely to prevent pod restart loops.
    The pod will be restarted by Flux on deployment updates or manually by scaling.
    """
    try:
        # Configure logging FIRST before using logger, so any startup errors are visible
        # Print to stdout/stderr directly before logging is configured
        print("Starting Redwood Data Agent...", file=sys.stdout, flush=True)
        
        # Load configuration from environment variables + defaults
        # Do this before configuring logging so we know the log level
        config = load_config()

        # Configure JSON logging with the specified log level
        # NOW logging is ready for all subsequent logs
        configure_logging(config.log_level)

        # Get logger after logging is configured
        logger = get_logger("redwood_dataagent")
        
        logger.info(
            "Redwood Data Agent initializing",
            extra={
                "event": "agent_start",
                "agent_mode": config.agent_mode,
                "environment": config.environment,
            },
        )

        # Inject transfer session ID into logging context (all logs will auto-include this)
        # This enables correlation of all logs for this transfer across the entire pipeline
        set_transfer_session_id(config.transfer_session_id)

        # Run agent on 5-minute scheduler loop for long-running stateless deployment
        logger.info(
            "Starting 5-minute scheduler loop",
            extra={"event": "scheduler_start", "interval_seconds": 300},
        )
        
        SCHEDULER_INTERVAL = 300  # 5 minutes in seconds
        
        def handle_sigterm(signum, frame):
            """Handle SIGTERM gracefully - exit the scheduler loop."""
            logger.info("SIGTERM received, shutting down gracefully")
            raise KeyboardInterrupt()
        
        # Register SIGTERM handler for graceful shutdown
        signal.signal(signal.SIGTERM, handle_sigterm)
        
        try:
            while True:
                # Execute agent with fully configured context
                logger.info(
                    "Executing agent workflow",
                    extra={"event": "workflow_start"},
                )
                result = run_agent(config)
                
                if result == 0:
                    logger.info(
                        f"Agent workflow completed, sleeping {SCHEDULER_INTERVAL}s until next run",
                        extra={"event": "agent_sleep", "sleep_seconds": SCHEDULER_INTERVAL},
                    )
                else:
                    logger.error(
                        f"Agent workflow failed with exit code {result}, sleeping {SCHEDULER_INTERVAL}s until retry",
                        extra={"event": "agent_failure", "exit_code": result, "sleep_seconds": SCHEDULER_INTERVAL},
                    )
                
                # Sleep until next scheduled run
                time.sleep(SCHEDULER_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Scheduler loop terminated, agent shutting down")
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
