from __future__ import annotations

from typing import Any

# This allow-list is intentionally centralized and will be expanded or modified
# as required when onboarding additional agencies and query templates.
ALLOWLISTED_QUERY_TEMPLATES: dict[str, dict[str, Any]] = {
    # Placeholder contract for DOT agencies; this will be adjusted as more
    # detailed agency-specific requirements become available.
    "dot_contract_extract_v1": {
        "required_params": {"schema", "table"},
        "max_row_limit": 100_000,
        "max_timeout_seconds": 300,
    },
}
