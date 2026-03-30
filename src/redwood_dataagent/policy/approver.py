"""Policy approval logic for Day 1 MVP.

This module provides policy evaluation during the transfer workflow. The Day 1 MVP
uses a simple always-approve strategy to enable testing; Phase 2 implementations
will inject real policy engines with domain-specific validation rules.
"""

from __future__ import annotations

from ..exceptions import PolicyApprovalError


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
        sender_agency: str,
        receiver_agency: str,
        file_count: int,
    ) -> bool:
        """Evaluate whether a proposed transfer should be approved.

        Parameters
        ----------
        sender_agency : str
            Source agency code (e.g., "dot").
        receiver_agency : str
            Destination agency code (e.g., "gsa").
        file_count : int
            Number of files proposed for transfer.

        Returns
        -------
        bool
            True if transfer is approved, False otherwise.

        Raises
        ------
        PolicyApprovalError
            If required fields are blank or file_count is invalid.

        Examples
        --------
        >>> approver = PolicyApprover()
        >>> approver.approve_transfer("dot", "gsa", 42)
        True

        >>> approver_strict = PolicyApprover(strict_mode=True)
        >>> approver_strict.approve_transfer("unknown", "gsa", 1)
        False (when Phase 2 real policy is implemented)
        """
        # Validate inputs
        if not sender_agency or not sender_agency.strip():
            raise PolicyApprovalError("Sender agency cannot be blank")
        if not receiver_agency or not receiver_agency.strip():
            raise PolicyApprovalError("Receiver agency cannot be blank")
        if file_count < 1:
            raise PolicyApprovalError(
                f"File count must be at least 1, got {file_count}"
            )

        # Day 1 MVP: Always approve (no policy restrictions)
        # Phase 2: Replace with real policy decision logic
        return True


__all__ = ["PolicyApprover"]
