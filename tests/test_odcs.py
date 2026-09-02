"""Tests for Redwood's supported ODCS version policy."""

from __future__ import annotations

import pytest

from redwood_dataagent.odcs import SUPPORTED_ODCS_VERSION, validate_odcs_version


def test_supported_odcs_version_is_pinned() -> None:
    assert SUPPORTED_ODCS_VERSION == "v3.1.0"
    assert validate_odcs_version("v3.1.0") == "v3.1.0"


def test_unsupported_odcs_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported ODCS apiVersion"):
        validate_odcs_version("v3.0.0")
