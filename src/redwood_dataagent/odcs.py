"""ODCS version policy for Redwood data-product contracts."""

from __future__ import annotations

SUPPORTED_ODCS_VERSION = "v3.1.0"


def validate_odcs_version(api_version: object) -> str:
    """Validate and return the supported ODCS API version.

    Full ODCS contract validation is intentionally deferred to the contract
    validation task. This guard establishes the version boundary first.
    """
    if api_version != SUPPORTED_ODCS_VERSION:
        raise ValueError(
            f"Unsupported ODCS apiVersion '{api_version}'. "
            f"Supported version is '{SUPPORTED_ODCS_VERSION}'."
        )
    return SUPPORTED_ODCS_VERSION
