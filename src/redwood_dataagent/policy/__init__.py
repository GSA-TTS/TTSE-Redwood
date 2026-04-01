"""Policy evaluation and approval logic for Day 1 MVP.

The policy module handles compliance checks during the transfer workflow.
Day 1 MVP uses a simple always-approve strategy; Phase 2 will support
real policy engines with domain-specific validation rules.

Examples
--------
>>> from redwood_dataagent.policy import PolicyApprover
>>> approver = PolicyApprover()
>>> approver.approve_transfer("dot", "gsa", 42)
True
"""

from .approver import PolicyApprover

__all__ = ["PolicyApprover"]
