"""Unit tests for policy approval logic."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from redwood_dataagent.exceptions import PolicyApprovalError
from redwood_dataagent.policy import PolicyApprover


class TestPolicyApproverInitialization:
    """Tests for PolicyApprover initialization."""

    def test_default_mode_is_not_strict(self) -> None:
        """PolicyApprover defaults to non-strict mode."""
        approver = PolicyApprover()
        assert approver.strict_mode is False

    def test_strict_mode_can_be_enabled(self) -> None:
        """PolicyApprover strict_mode can be set to True."""
        approver = PolicyApprover(strict_mode=True)
        assert approver.strict_mode is True


class TestApproveTransfer:
    """Tests for the approve_transfer() method."""

    def test_approve_transfer_default_approve(self) -> None:
        """Day 1 MVP: approve_transfer always returns True for valid inputs."""
        approver = PolicyApprover()
        result = approver.approve_transfer("dot", 42)
        assert result is True

    def test_approve_transfer_with_various_file_counts(self) -> None:
        """approve_transfer works with any valid file count."""
        approver = PolicyApprover()

        for count in [1, 10, 100, 1000]:
            result = approver.approve_transfer("dot", count)
            assert result is True

    def test_approve_transfer_with_different_agencies(self) -> None:
        """approve_transfer works with different agency codes."""
        approver = PolicyApprover()

        for agency in ["dot", "gsa", "EPA", "usda", "a"]:
            result = approver.approve_transfer(agency, 5)
            assert result is True

    def test_approve_transfer_agency_blank_raises_error(self) -> None:
        """approve_transfer raises error when agency is blank."""
        approver = PolicyApprover()

        with pytest.raises(PolicyApprovalError, match="Agency cannot be blank"):
            approver.approve_transfer("", 5)

    def test_approve_transfer_agency_whitespace_raises_error(self) -> None:
        """approve_transfer raises error when agency is whitespace-only."""
        approver = PolicyApprover()

        with pytest.raises(PolicyApprovalError, match="Agency cannot be blank"):
            approver.approve_transfer("   ", 5)

    def test_approve_transfer_file_count_zero_raises_error(self) -> None:
        """approve_transfer raises error when file_count is zero."""
        approver = PolicyApprover()

        with pytest.raises(PolicyApprovalError, match="File count must be at least 1"):
            approver.approve_transfer("dot", 0)

    def test_approve_transfer_file_count_negative_raises_error(self) -> None:
        """approve_transfer raises error when file_count is negative."""
        approver = PolicyApprover()

        with pytest.raises(PolicyApprovalError, match="File count must be at least 1"):
            approver.approve_transfer("dot", -5)

    def test_approve_transfer_strict_mode_still_approves_in_day1(self) -> None:
        """Even in strict mode, Day 1 MVP approves valid transfers."""
        approver = PolicyApprover(strict_mode=True)
        result = approver.approve_transfer("dot", 10)
        assert result is True

    def test_approve_transfer_strict_mode_still_validates_inputs(self) -> None:
        """Strict mode still validates input parameters."""
        approver = PolicyApprover(strict_mode=True)

        with pytest.raises(PolicyApprovalError, match="Agency cannot be blank"):
            approver.approve_transfer("", 5)

    def test_approve_transfer_none_agency_raises_error(self) -> None:
        """approve_transfer raises error when agency is None."""
        approver = PolicyApprover()

        with pytest.raises((PolicyApprovalError, AttributeError)):
            approver.approve_transfer(None, 5)  # type: ignore


class TestApproveTransferEdgeCases:
    """Edge case tests for approve_transfer()."""

    def test_approve_transfer_with_large_file_count(self) -> None:
        """approve_transfer handles large file counts."""
        approver = PolicyApprover()
        result = approver.approve_transfer("dot", 1_000_000)
        assert result is True

    def test_approve_transfer_with_unicode_agency(self) -> None:
        """approve_transfer works with unicode agency codes."""
        approver = PolicyApprover()
        result = approver.approve_transfer("dot🏛️", 5)
        assert result is True

    def test_approve_transfer_with_case_variants(self) -> None:
        """approve_transfer works with mixed-case agency codes."""
        approver = PolicyApprover()

        for agency in ["DOT", "Dot", "dOt"]:
            result = approver.approve_transfer(agency, 5)
            assert result is True


class TestPolicyApproverIntegration:
    """Integration tests for typical usage patterns."""

    def test_multiple_approvals_same_instance(self) -> None:
        """PolicyApprover can be reused for multiple approvals."""
        approver = PolicyApprover()

        approvals = [
            approver.approve_transfer("dot", 10),
            approver.approve_transfer("gsa", 20),
            approver.approve_transfer("usda", 30),
        ]

        assert all(approvals)

    def test_separate_instances_independent(self) -> None:
        """Multiple PolicyApprover instances are independent."""
        approver1 = PolicyApprover(strict_mode=False)
        approver2 = PolicyApprover(strict_mode=True)

        result1 = approver1.approve_transfer("dot", 5)
        result2 = approver2.approve_transfer("dot", 5)

        assert result1 is True
        assert result2 is True
        assert approver1.strict_mode != approver2.strict_mode


class TestPolicyHealthProbe:
    """Tests for policy server health probe logging and resiliency."""

    def test_probe_success_logs_connectivity_validated(self) -> None:
        """Successful probe logs a success event."""
        approver = PolicyApprover()
        mock_logger = MagicMock()

        response = MagicMock()
        response.status = 200
        response.read.return_value = b"ok"
        response_cm = MagicMock()
        response_cm.__enter__.return_value = response
        response_cm.__exit__.return_value = False

        with (
            patch("redwood_dataagent.policy.approver.get_logger", return_value=mock_logger),
            patch("redwood_dataagent.policy.approver.urlopen", return_value=response_cm),
        ):
            approver._probe_policy_server_connectivity("dot")

        assert mock_logger.info.call_count >= 2

    def test_probe_http_error_logs_warning_without_raising(self) -> None:
        """HTTP failures are logged as warnings and do not raise."""
        approver = PolicyApprover()
        mock_logger = MagicMock()
        http_error = HTTPError(
            url="https://example.test/health",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b"down"),
        )

        with (
            patch("redwood_dataagent.policy.approver.get_logger", return_value=mock_logger),
            patch("redwood_dataagent.policy.approver.urlopen", side_effect=http_error),
        ):
            approver._probe_policy_server_connectivity("dot")

        assert mock_logger.warning.called

    def test_probe_url_error_logs_warning_without_raising(self) -> None:
        """URLError failures are logged as warnings and do not raise."""
        approver = PolicyApprover()
        mock_logger = MagicMock()

        with (
            patch("redwood_dataagent.policy.approver.get_logger", return_value=mock_logger),
            patch("redwood_dataagent.policy.approver.urlopen", side_effect=URLError("dns error")),
        ):
            approver._probe_policy_server_connectivity("dot")

        assert mock_logger.warning.called

    def test_probe_generic_error_logs_warning_without_raising(self) -> None:
        """Unexpected probe failures are logged as warnings and do not raise."""
        approver = PolicyApprover()
        mock_logger = MagicMock()

        with (
            patch("redwood_dataagent.policy.approver.get_logger", return_value=mock_logger),
            patch("redwood_dataagent.policy.approver.urlopen", side_effect=RuntimeError("boom")),
        ):
            approver._probe_policy_server_connectivity("dot")

        assert mock_logger.warning.called
