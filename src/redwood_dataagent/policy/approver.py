"""Policy approval logic for Day 1 MVP.

This module provides policy evaluation during the transfer workflow. The Day 1 MVP
uses a simple always-approve strategy to enable testing; Phase 2 implementations
will inject real policy engines with domain-specific validation rules.
"""

from __future__ import annotations

import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..exceptions import PolicyApprovalError
from ..logging_utils import get_logger, prefix_log_message

DEFAULT_POLICY_HEALTHCHECK_URL = "https://everglades.dev.tts.mcaas.fcs.gsa.gov/health"
DEFAULT_POLICY_HEALTHCHECK_TIMEOUT_SECONDS = 5
POLICY_HEALTH_PROBE_FAILED_MESSAGE = "Policy server health probe failed"


class PolicyApprover:
    """Evaluates policy compliance for proposed transfers.

    Day 1 MVP: Implements default-approve behavior to unblock testing.
    Phase 2: Can be extended with real policy rules (sender/receiver validation,
    data classification, compliance checks, etc.)
    """

    def __init__(self, strict_mode: bool = False) -> None:
        """Initialize the policy approver.

        Parameters
        ----------
        strict_mode : bool, optional
            If True, enable stricter validation (reserved for Phase 2 real policy).
            Default is False (Day 1 MVP mode).
        """
        self.strict_mode = strict_mode

    def approve_transfer(
        self,
        agency: str,
        file_count: int,
    ) -> bool:
        """Evaluate whether a proposed transfer should be approved.

        Parameters
        ----------
        agency : str
            The agency code for this pod (sender or receiver, from AGENCY env var).
        file_count : int
            Number of files proposed for transfer.

        Returns
        -------
        bool
            True if transfer is approved, False otherwise.

        Raises
        ------
        PolicyApprovalError
            If agency is blank or file_count is invalid.

        Examples
        --------
        >>> approver = PolicyApprover()
        >>> approver.approve_transfer("dot", 42)
        True
        """
        # Validate inputs
        if not agency or not agency.strip():
            raise PolicyApprovalError("Agency cannot be blank")
        if file_count < 1:
            raise PolicyApprovalError(f"File count must be at least 1, got {file_count}")

        # Day 1 MVP: Always approve (no policy restrictions)
        # Phase 2: Replace with real policy decision logic
        # The policy health probe is optional for now: failures are logged,
        # but they do not block transfer approval or stop the process.
        self._probe_policy_server_connectivity(agency)
        return True

    def _probe_policy_server_connectivity(self, agency: str) -> None:
        """Probe the external policy server and emit structured log events."""
        logger = get_logger(__name__)
        healthcheck_url = os.getenv(
            "POLICY_HEALTHCHECK_URL",
            DEFAULT_POLICY_HEALTHCHECK_URL,
        )

        logger.info(
            prefix_log_message("Checking policy server connectivity"),
            extra={
                "event": "policy_server_health_probe_start",
                "healthcheck_url": healthcheck_url,
                "agency": agency,
            },
        )

        try:
            request = Request(
                healthcheck_url,
                headers={"User-Agent": "redwood-dataagent-healthcheck/1.0"},
            )
            with urlopen(request, timeout=DEFAULT_POLICY_HEALTHCHECK_TIMEOUT_SECONDS) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                logger.info(
                    prefix_log_message("Policy server connectivity validated"),
                    extra={
                        "event": "policy_server_health_probe_success",
                        "healthcheck_url": healthcheck_url,
                        "status_code": response.status,
                        "response_body": body,
                        "agency": agency,
                    },
                )
        except HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            logger.warning(
                prefix_log_message(POLICY_HEALTH_PROBE_FAILED_MESSAGE),
                extra={
                    "event": "policy_server_health_probe_failure",
                    "healthcheck_url": healthcheck_url,
                    "status_code": exc.code,
                    "response_body": body,
                    "error": str(exc),
                    "agency": agency,
                },
            )
        except URLError as exc:
            logger.warning(
                prefix_log_message(POLICY_HEALTH_PROBE_FAILED_MESSAGE),
                extra={
                    "event": "policy_server_health_probe_failure",
                    "healthcheck_url": healthcheck_url,
                    "error": str(exc),
                    "agency": agency,
                },
            )
        except Exception as exc:
            logger.warning(
                prefix_log_message(POLICY_HEALTH_PROBE_FAILED_MESSAGE),
                extra={
                    "event": "policy_server_health_probe_failure",
                    "healthcheck_url": healthcheck_url,
                    "error": str(exc),
                    "agency": agency,
                },
            )


__all__ = ["PolicyApprover"]
