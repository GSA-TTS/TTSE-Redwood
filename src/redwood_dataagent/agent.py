"""Agent runtime entrypoints for the Redwood MVP foundation.

The agent module implements the core sender and receiver workflows for Day 1 MVP:
- Sender: Extract → Policy Check → Compress → Manifest → Stage
- Receiver: Validate → Decompress → Verify → Store

Both workflows include comprehensive audit logging and error handling.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from pydantic import BaseModel, Field, ValidationError

from .audit.events import AuditEventType, EventOutcome
from .audit.logger import (
    log_compress,
    log_extract_data,
    log_manifest_created,
    log_pipeline_complete,
    log_pipeline_start,
    log_policy_check,
    log_sftp_transfer_complete,
    log_sftp_transfer_start,
)
from .aws.s3 import S3Client
from .config import AgentConfig
from .dataproduct_registry import DataproductRegistry, load_dataproduct_registry
from .exceptions import (
    ConfigurationError,
    InfectedFileError,
    StorageError,
)
from .json_utils import resolve_runtime_config_path
from .logging_utils import get_logger, logging_context, prefix_log_message
from .models.manifest import (
    ChecksumAlgorithm,
    CompressionType,
    ManifestFile,
    TransferManifest,
    apply_archive_field_naming,
)
from .models.request import DataproductRequest
from .policy import PolicyApprover
from .policy.virus_scanner import ScanStatus, scan_file
from .query_adapter import execute_query
from .query_templates import ALLOWLISTED_QUERY_TEMPLATES
from .receiver.landing import ReceiverLandingZone
from .receiver.store import ReceiverTargetStore
from .sftp import create_sftp_client_from_credentials
from .storage.conventions import FileModeStoragePath, QueryModeStoragePath

# Create module logger (will auto-inject transfer_session_id from context)
LOGGER = get_logger("redwood_dataagent")

# Day 1 MVP uses SHA256 for checksums and gzip for compression
DEFAULT_CHECKSUM_ALGORITHM = ChecksumAlgorithm.SHA256
DEFAULT_COMPRESSION = CompressionType.GZIP
DEFAULT_DATA_FILE_NAME = "data.json"
DEFAULT_ARCHIVE_FILE_NAME = "transfer.tar.gz"
DEFAULT_MANIFEST_FILE_NAME = "manifest.json"
DEFAULT_RETRY_ATTEMPTS = 3
DONE_MARKER_SUFFIX = ".done"
VALID_SENDER_INPUT_MODES = {"file", "query"}
QUERY_SKIP_REASON_MATCHING_MARKER = "matching query success marker already exists"

class SenderQueryInputContract(BaseModel):
    """Runtime query input contract for sender query mode."""

    template_id: str = Field(min_length=1)
    params: dict[str, Any]
    row_limit: int = Field(default=10_000, ge=1)
    timeout_seconds: int = Field(default=60, ge=1)


@dataclass
class SenderInputPreparation:
    """Mode-specific sender input prepared for shared transfer steps."""

    staged_file: Path
    file_name: str
    extract_details: dict[str, Any]
    pipeline_complete_details: dict[str, Any] | None = None


@dataclass
class SenderTransferArtifacts:
    """Artifacts and metadata emitted by shared sender transfer steps."""

    manifest: TransferManifest
    staged_artifact_keys: list[str]


@dataclass
class FileModeSource:
    """Resolved file-mode source and marker directory."""

    s3_path: str
    file_name: str
    marker_directory: str


def _retry_operation[T](operation_name: str, operation: Callable[[], T], attempts: int = DEFAULT_RETRY_ATTEMPTS) -> T:
    """Retry an operation for transient failures before raising StorageError."""
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - exercised via caller paths
            last_error = exc
            if attempt < attempts:
                LOGGER.warning(
                    prefix_log_message("Retrying operation after failure"),
                    extra={
                        "event": "operation_retry",
                        "operation": operation_name,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error": str(exc),
                    },
                )

    raise StorageError(f"{operation_name} failed after {attempts} attempts: {last_error}") from last_error


# Sender file-mode helpers


def _build_file_mode_processed_marker_key(key: str) -> str:
    """Build the file-mode .done marker key for a scanned sender object."""
    sender_scan_prefix = FileModeStoragePath.scan_prefix()
    processed_prefix = FileModeStoragePath.processed_prefix()
    if key.startswith(sender_scan_prefix):
        return key.replace(sender_scan_prefix, processed_prefix, 1) + DONE_MARKER_SUFFIX

    if f"/{sender_scan_prefix}" in key:
        return key.replace(f"/{sender_scan_prefix}", f"/{processed_prefix}", 1) + DONE_MARKER_SUFFIX

    return f"{processed_prefix}{Path(key).name}{DONE_MARKER_SUFFIX}"


def _resolve_file_mode_processed_marker(directory_path: str, file_name: str) -> tuple[str, str]:
    """Resolve bucket and processed marker key for a file-mode source object."""
    parsed = _parse_s3_path(directory_path)
    if parsed is None:
        raise StorageError(f"Sender directory must be an S3 path, got: {directory_path}")

    bucket, prefix = parsed
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"

    processed_prefix = prefix.replace(
        FileModeStoragePath.scan_prefix(),
        FileModeStoragePath.processed_prefix(),
        1,
    )
    marker_key = f"{processed_prefix}{file_name}{DONE_MARKER_SUFFIX}"
    return bucket, marker_key


def _marker_exists(client: S3Client, bucket: str, marker_key: str) -> bool:
    """Return True when an idempotency marker key exists in S3."""
    try:
        client._client.head_object(Bucket=bucket, Key=marker_key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise StorageError(f"Failed to check processed marker {marker_key}: {exc}") from exc
    except Exception as exc:
        raise StorageError(f"Failed to check processed marker {marker_key}: {exc}") from exc


def _extract_data(config: AgentConfig) -> None:
    """Placeholder extraction hook for future implementation.

    Day 1 expects sender agencies to provide a prepared source data file.
    Phase 2 can implement agency-side extraction logic here.
    """
    _ = config


# Sender query-mode helpers


def _load_runtime_dataproduct_registry() -> DataproductRegistry:
    """Load the runtime dataproduct registry from committed file-based definitions.

    The current repo keeps placeholder dataproduct definition instances under
    ``config/dataproducts/examples/definitions``. They are intentionally treated
    as runtime seed data for this MVP/WIP phase even though they are not the
    long-term source of truth. The end-state is to resolve real contracts from a
    central registry once that integration exists.
    """
    # These example definitions are temporary runtime stand-ins until a central
    # dataproduct contract registry becomes the authoritative source.
    definitions_dir = resolve_runtime_config_path("dataproducts", "examples", "definitions")
    schema_path = resolve_runtime_config_path("dataproducts", "schema", "dataproduct.schema.json")
    return load_dataproduct_registry(definitions_dir=definitions_dir, schema_path=schema_path)


def _validate_request_params_against_definition(
    request: DataproductRequest,
    definition_payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate request params against definition constraints and return extraction block."""
    extraction = _extract_sql_extraction_config(request.dataproduct_id, definition_payload)
    required_params, optional_params = _get_param_definitions(request.dataproduct_id, extraction)
    required_param_names, optional_param_names = _collect_param_names(required_params, optional_params)

    _validate_allowed_and_required_params(
        dataproduct_id=request.dataproduct_id,
        params=request.params,
        required_param_names=required_param_names,
        optional_param_names=optional_param_names,
    )
    _validate_allowed_param_values(
        params=request.params,
        param_definitions=required_params + optional_params,
    )
    _validate_allowed_select_fields(
        params=request.params,
        allowed_select_fields=extraction.get("allowed_select_fields", []),
    )
    _validate_allowed_filters(
        params=request.params,
        allowed_filters=extraction.get("allowed_filters", []),
    )

    return extraction


def _extract_sql_extraction_config(dataproduct_id: str, definition_payload: dict[str, Any]) -> dict[str, Any]:
    """Return extraction config and enforce sender query SQL compatibility."""
    extraction = definition_payload.get("extraction")
    if not isinstance(extraction, dict):
        raise ConfigurationError(f"Dataproduct definition for '{dataproduct_id}' is missing extraction constraints")

    source_type = extraction.get("source_type")
    if source_type != "sql":
        raise ConfigurationError(
            "Sender query mode only supports dataproduct definitions with "
            f"source_type='sql', got '{source_type}' for '{dataproduct_id}'"
        )

    return extraction


def _get_param_definitions(dataproduct_id: str, extraction: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """Return required/optional param definition lists from extraction config."""
    required_params = extraction.get("required_params", [])
    optional_params = extraction.get("optional_params", [])
    if not isinstance(required_params, list) or not isinstance(optional_params, list):
        raise ConfigurationError(f"Dataproduct definition for '{dataproduct_id}' has invalid param definitions")
    return required_params, optional_params


def _collect_param_names(required_params: list[Any], optional_params: list[Any]) -> tuple[set[str], set[str]]:
    """Return normalized required and optional param names from param definitions."""
    required_param_names = {
        str(param.get("name"))
        for param in required_params
        if isinstance(param, dict) and isinstance(param.get("name"), str)
    }
    optional_param_names = {
        str(param.get("name"))
        for param in optional_params
        if isinstance(param, dict) and isinstance(param.get("name"), str)
    }
    return required_param_names, optional_param_names


def _validate_allowed_and_required_params(
    dataproduct_id: str,
    params: dict[str, Any],
    required_param_names: set[str],
    optional_param_names: set[str],
) -> None:
    """Enforce allowed param set and required param presence."""
    allowed_param_names = required_param_names | optional_param_names
    unknown_params = sorted(param_name for param_name in params if param_name not in allowed_param_names)
    if unknown_params:
        raise ConfigurationError(f"Request contains params not allowed by dataproduct '{dataproduct_id}': {unknown_params}")

    missing_required_params = sorted(
        param_name
        for param_name in required_param_names
        if (
            param_name not in params
            or params[param_name] is None
            or (isinstance(params[param_name], str) and not params[param_name].strip())
        )
    )
    if missing_required_params:
        raise ConfigurationError(f"Missing required params for dataproduct '{dataproduct_id}': {missing_required_params}")


def _validate_allowed_param_values(
    params: dict[str, Any],
    param_definitions: list[Any],
) -> None:
    """Enforce param-level allowed_values constraints when configured."""
    for param_definition in param_definitions:
        if not isinstance(param_definition, dict):
            continue

        param_name = param_definition.get("name")
        allowed_values = param_definition.get("allowed_values")
        if not isinstance(param_name, str) or not isinstance(allowed_values, list) or not allowed_values:
            continue

        if param_name in params and params[param_name] not in allowed_values:
            raise ConfigurationError(
                "Param value not allowed by dataproduct definition: "
                f"param='{param_name}', value='{params[param_name]}', allowed_values={allowed_values}"
            )


def _validate_allowed_select_fields(params: dict[str, Any], allowed_select_fields: Any) -> None:
    """Enforce allowed select_fields constraints when configured."""
    if not isinstance(allowed_select_fields, list) or not allowed_select_fields or "select_fields" not in params:
        return

    select_fields = params["select_fields"]
    if not isinstance(select_fields, list):
        raise ConfigurationError("Param 'select_fields' must be an array when provided")

    disallowed_select_fields = sorted(field for field in select_fields if field not in allowed_select_fields)
    if disallowed_select_fields:
        raise ConfigurationError(
            "Request contains select_fields not allowed by dataproduct definition: " f"{disallowed_select_fields}"
        )


def _build_allowed_filter_map(allowed_filters: list[Any]) -> dict[str, set[str]]:
    """Build lookup of allowed filter fields to operator sets."""
    allowed_filter_map: dict[str, set[str]] = {}
    for filter_definition in allowed_filters:
        if not isinstance(filter_definition, dict):
            continue

        field_name = filter_definition.get("field")
        operators = filter_definition.get("operators", [])
        if isinstance(field_name, str) and isinstance(operators, list):
            allowed_filter_map[field_name] = {str(operator) for operator in operators}
    return allowed_filter_map


def _validate_allowed_filters(params: dict[str, Any], allowed_filters: Any) -> None:
    """Enforce allowed filters and operators constraints when configured."""
    if not isinstance(allowed_filters, list) or not allowed_filters or "filters" not in params:
        return

    filters = params["filters"]
    if not isinstance(filters, dict):
        raise ConfigurationError("Param 'filters' must be an object when provided")

    allowed_filter_map = _build_allowed_filter_map(allowed_filters)
    unknown_filter_fields = sorted(field_name for field_name in filters if field_name not in allowed_filter_map)
    if unknown_filter_fields:
        raise ConfigurationError(
            "Request contains filter fields not allowed by dataproduct definition: " f"{unknown_filter_fields}"
        )

    for field_name, operator_map in filters.items():
        if not isinstance(operator_map, dict):
            raise ConfigurationError(f"Filter for field '{field_name}' must be an object")

        disallowed_operators = sorted(
            operator for operator in operator_map if operator not in allowed_filter_map.get(field_name, set())
        )
        if disallowed_operators:
            raise ConfigurationError(
                "Request contains filter operators not allowed by dataproduct definition: "
                f"field='{field_name}', operators={disallowed_operators}"
            )


def _resolve_sender_query_contract_input(config: AgentConfig) -> tuple[str, int, int]:
    """Resolve query contract input from dataproduct request when provided."""
    if config.dataproduct_request is None:
        return config.sender_query_input_json, config.max_query_row_limit, config.max_query_timeout_seconds

    request = config.dataproduct_request
    try:
        definition = _load_runtime_dataproduct_registry().get(request.dataproduct_id)
    except KeyError as exc:
        raise ConfigurationError(str(exc)) from exc

    extraction = _validate_request_params_against_definition(request, definition.payload)

    template_id = extraction.get("template_id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise ConfigurationError(
            f"Dataproduct definition for '{request.dataproduct_id}' is missing extraction.template_id"
        )

    definition_default_row_limit = int(extraction.get("default_row_limit", config.max_query_row_limit))
    definition_max_row_limit = int(extraction.get("max_row_limit", config.max_query_row_limit))
    definition_default_timeout_seconds = int(extraction.get("default_timeout_seconds", config.max_query_timeout_seconds))
    definition_max_timeout_seconds = int(extraction.get("max_timeout_seconds", config.max_query_timeout_seconds))

    row_limit = request.requested_row_limit or definition_default_row_limit
    timeout_seconds = request.requested_timeout_seconds or definition_default_timeout_seconds

    payload = {
        "template_id": template_id,
        "params": request.params,
        "row_limit": row_limit,
        "timeout_seconds": timeout_seconds,
    }
    effective_row_limit_cap = min(config.max_query_row_limit, definition_max_row_limit)
    effective_timeout_cap = min(config.max_query_timeout_seconds, definition_max_timeout_seconds)
    return json.dumps(payload), effective_row_limit_cap, effective_timeout_cap


def _validate_sender_query_input_contract(
    raw_contract_json: str,
    max_query_row_limit: int,
    max_query_timeout_seconds: int,
) -> SenderQueryInputContract:
    """Validate sender-provided query input payload.

    Raises
    ------
    ConfigurationError
        When payload is missing, malformed, not allow-listed, or missing required params.
    """
    if not raw_contract_json or not raw_contract_json.strip():
        raise ConfigurationError("SENDER_QUERY_INPUT_JSON is required when SENDER_INPUT_MODE=query")

    try:
        payload = json.loads(raw_contract_json)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"SENDER_QUERY_INPUT_JSON must be valid JSON: {exc}") from exc

    try:
        contract = SenderQueryInputContract.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid query input contract: {exc}") from exc

    template_spec = ALLOWLISTED_QUERY_TEMPLATES.get(contract.template_id)
    if template_spec is None:
        raise ConfigurationError(
            "Query template is not allow-listed: "
            f"template_id='{contract.template_id}'. "
            f"Allowed templates: {sorted(ALLOWLISTED_QUERY_TEMPLATES.keys())}"
        )

    required_params = set(template_spec.get("required_params", set()))
    missing_required_params = sorted(
        param_name
        for param_name in required_params
        if (
            param_name not in contract.params
            or contract.params[param_name] is None
            or (isinstance(contract.params[param_name], str) and not contract.params[param_name].strip())
        )
    )
    if missing_required_params:
        raise ConfigurationError(
            "Missing required query params for template " f"'{contract.template_id}': {missing_required_params}"
        )

    template_max_row_limit = int(template_spec.get("max_row_limit", max_query_row_limit))
    effective_max_row_limit = min(template_max_row_limit, max_query_row_limit)
    if contract.row_limit > effective_max_row_limit:
        raise ConfigurationError(
            f"row_limit {contract.row_limit} exceeds allow-listed template max "
            f"{effective_max_row_limit} for template '{contract.template_id}'"
        )

    template_max_timeout_seconds = int(template_spec.get("max_timeout_seconds", max_query_timeout_seconds))
    effective_max_timeout_seconds = min(template_max_timeout_seconds, max_query_timeout_seconds)
    if contract.timeout_seconds > effective_max_timeout_seconds:
        raise ConfigurationError(
            f"timeout_seconds {contract.timeout_seconds} exceeds allow-listed template max "
            f"{effective_max_timeout_seconds} for template '{contract.template_id}'"
        )

    return contract


def _resolve_and_validate_sender_query_contract(config: AgentConfig) -> SenderQueryInputContract:
    """Resolve sender query contract input and validate it into a typed contract."""
    (
        raw_contract_json,
        effective_row_limit_cap,
        effective_timeout_cap,
    ) = _resolve_sender_query_contract_input(config)
    return _validate_sender_query_input_contract(
        raw_contract_json,
        max_query_row_limit=effective_row_limit_cap,
        max_query_timeout_seconds=effective_timeout_cap,
    )


def _create_sender_query_workflow(config: AgentConfig) -> None:
    """Execute validated query contract and produce staged CSV output.

    Orchestrates query execution and staging:
    1. Validate query input contract (schema, table, filters, row limits, timeout)
    2. Execute query via Ibis against PostgreSQL
    3. Write results to CSV file
    4. Upload to sender staging S3 bucket
    5. Log extraction outcome and completion

    Integration with the existing sender transfer pipeline (policy check, compression,
    manifest generation, and transfer artifact staging) will be addressed in RED-74/RED-93.

    Query execution includes:
    - Timeout enforcement via signal handlers
    - Result metadata tracking (row count, file size, duration)
    - Comprehensive error handling with actionable details

    Returns
    -------
    None
        Outcomes are logged via audit trail.
    """
    log_pipeline_start(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
    )

    try:
        contract = _resolve_and_validate_sender_query_contract(config)
    except ConfigurationError as exc:
        LOGGER.error(
            prefix_log_message(
                f"Invalid sender query input contract: {exc}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_contract_invalid",
                "error_type": type(exc).__name__,
            },
        )
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_contract_validation",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return

    try:
        LOGGER.info(
            prefix_log_message(
                "Validated sender query input contract",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_contract_validated",
                "template_id": contract.template_id,
                "param_names": sorted(contract.params.keys()),
                "row_limit": contract.row_limit,
                "timeout_seconds": contract.timeout_seconds,
            },
        )

        # Execute query and stage output
        LOGGER.info(
            prefix_log_message(
                "Executing query via Ibis adapter",
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "query_execution_start",
                "template_id": contract.template_id,
            },
        )

        result = execute_query(contract, config)

        if result.skipped:
            log_extract_data(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={
                    "step": "query_execution_skipped",
                    "template_id": contract.template_id,
                    "reason": QUERY_SKIP_REASON_MATCHING_MARKER,
                    "fingerprint": result.query_fingerprint,
                    "marker_key": result.marker_key,
                },
            )
            log_pipeline_complete(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details={
                    "template_id": contract.template_id,
                    "skipped": True,
                    "reason": QUERY_SKIP_REASON_MATCHING_MARKER,
                    "fingerprint": result.query_fingerprint,
                    "marker_key": result.marker_key,
                },
            )

            LOGGER.info(
                prefix_log_message(
                    "Query execution skipped; matching success marker already exists",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_query_execution_skipped",
                    "template_id": contract.template_id,
                    "marker_key": result.marker_key,
                },
            )
            return

        # Log extraction success with metadata
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "step": "query_execution",
                "template_id": contract.template_id,
                "row_count": result.row_count,
                "file_size_bytes": result.file_size_bytes,
                "duration_seconds": round(result.execution_duration_seconds, 2),
                "output_file": result.output_file_path,
            },
        )

        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "template_id": contract.template_id,
                "row_count": result.row_count,
                "file_size_bytes": result.file_size_bytes,
                "duration_seconds": round(result.execution_duration_seconds, 2),
            },
        )

        LOGGER.info(
            prefix_log_message(
                "Query execution completed successfully",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_execution_success",
                "template_id": contract.template_id,
                "row_count": result.row_count,
                "duration_seconds": result.execution_duration_seconds,
            },
        )
        return

    except ConfigurationError as exc:
        LOGGER.error(
            prefix_log_message(
                f"Query execution configuration failed: {exc}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_execution_configuration_failed",
                "error_type": type(exc).__name__,
            },
        )
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return

    except StorageError as exc:
        LOGGER.error(
            prefix_log_message(
                f"Query execution failed: {exc}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_execution_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return

    except Exception as exc:
        error_message = f"Unexpected error during query execution: {exc}"
        LOGGER.error(
            prefix_log_message(
                error_message,
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_query_execution_unexpected_error",
                "error_type": type(exc).__name__,
            },
        )
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": error_message,
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": error_message},
        )
        return

    # Shared sender workflow helpers


def _select_sender_input_mode(raw_mode: str | None) -> tuple[str, str]:
    """Normalize sender input mode and provide a selection reason.

    Returns
    -------
    tuple[str, str]
        (selected_mode, reason)
    """
    if raw_mode is None:
        return "file", "default_missing"

    normalized_mode = raw_mode.strip().lower()
    if not normalized_mode:
        return "file", "default_blank"

    if normalized_mode in VALID_SENDER_INPUT_MODES:
        return normalized_mode, "explicit"

    return "file", f"default_invalid:{raw_mode}"


def _scan_sender_directory(directory_path: str, aws_region: str) -> list[tuple[str, str]]:
    """Scan S3 directory for unprocessed files (files without .done marker).

    Parameters
    ----------
    directory_path : str
        S3 directory path (e.g., s3://bucket/outgoing/)
    aws_region : str
        AWS region for S3 access

    Returns
    -------
    list[tuple[str, str]]
        List of (s3_path, file_name) tuples for files ready to process.
        Excludes files that have .done markers in processed/

    Raises
    ------
    StorageError
        If directory listing fails
    """
    try:
        parsed = _parse_s3_path(directory_path)
        if parsed is None:
            raise StorageError(f"Sender directory must be an S3 path, got: {directory_path}")

        bucket, prefix = parsed
        client = S3Client(aws_region=aws_region)

        # List objects in the configured sender scan directory
        response = client._client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        files = []

        if "Contents" not in response:
            return []

        for obj in response["Contents"]:
            key = obj["Key"]
            # Skip if it's the prefix itself or is a directory marker
            if key == prefix or key.endswith("/"):
                continue

            file_name = Path(key).name

            # Skip if this is a marker file (.done files should not be processed)
            if file_name.endswith(DONE_MARKER_SUFFIX):
                LOGGER.debug(f"Skipping marker file: {key}")
                continue

            # Check if file has been processed (marker exists in processed/)
            processed_marker_key = _build_file_mode_processed_marker_key(key)
            if _marker_exists(client, bucket, processed_marker_key):
                LOGGER.debug(f"Skipping already processed file: {key}")
                continue

            s3_path = f"s3://{bucket}/{key}"
            files.append((s3_path, file_name))

        return files
    except Exception as e:
        raise StorageError(f"Failed to scan sender directory: {e}") from e


def _mark_file_processed(file_name: str, directory_path: str, aws_region: str) -> None:
    """Create a .done marker in the file-mode processed directory after success.

    Parameters
    ----------
    file_name : str
        Name of the file that was processed
    directory_path : str
        S3 directory path (e.g., s3://bucket/outgoing/)
    aws_region : str
        AWS region for S3 access

    Raises
    ------
    StorageError
        If marker creation fails
    """
    try:
        bucket, marker_key = _resolve_file_mode_processed_marker(directory_path, file_name)
        client = S3Client(aws_region=aws_region)
        timestamp = datetime.now(UTC).isoformat()
        marker_metadata = {
            "processed_at": timestamp,
            "original_file": file_name,
        }

        client._client.put_object(
            Bucket=bucket,
            Key=marker_key,
            Body=json.dumps(marker_metadata).encode("utf-8"),
        )
        LOGGER.info(prefix_log_message(f"Marked file as processed: {marker_key}"))
    except Exception as e:
        raise StorageError(f"Failed to mark file as processed: {e}") from e


def _parse_s3_path(path: str) -> tuple[str, str] | None:
    """Parse an S3 URL into bucket and key components.

    S3 paths have the format: s3://bucket-name/path/to/key

    Parameters
    ----------
    path : str
        S3 path or local file path

    Returns
    -------
    tuple[str, str] | None
        (bucket, key) if path is an S3 URL, None otherwise

    Example
    -------
    >>> _parse_s3_path("s3://my-bucket/transfers/sess-001/data.json")
    ("my-bucket", "transfers/sess-001/data.json")
    """
    if not path.startswith("s3://"):
        return None

    try:
        # Remove s3:// prefix
        path_without_scheme = path[5:]
        # Split on first slash
        parts = path_without_scheme.split("/", 1)
        if len(parts) == 2:
            bucket, key = parts
            if bucket and key:
                return bucket, key
    except (ValueError, IndexError):
        pass

    raise StorageError(f"Invalid S3 path format: {path}. Expected: s3://bucket/key")


def _download_from_s3(s3_path: str, destination_path: Path, aws_region: str) -> dict[str, Any]:
    """Download a file from S3 to container filesystem (S3 → container).

    Helper to fetch sender's data file from sender-side S3 storage into
    the container's working directory for processing (policy check, compression, etc).

    Parameters
    ----------
    s3_path : str
        Full S3 URL (e.g., "s3://tts-core-dev-dot-data-staging/transfers/sess-001/data.json")
    destination_path : Path
        Path on the container filesystem where the S3 object will be written.
        Typically in a temporary working directory for staging.
    aws_region : str
        AWS region where the S3 bucket is located

    Returns
    -------
    dict[str, Any]
        Metadata about the downloaded file:
        - data_source: "s3_object"
        - s3_bucket: Source bucket name
        - s3_key: Source object key
        - file_name: Name of the downloaded file
        - file_size_bytes: Size in bytes

    Raises
    ------
    StorageError
        If S3 download fails (bucket not found, object not found, access denied, etc)
    """
    bucket, key = _parse_s3_path(s3_path)

    client = S3Client(aws_region=aws_region)
    client.download_file(bucket, key, destination_path)

    return {
        "data_source": "s3_object",
        "s3_bucket": bucket,
        "s3_key": key,
        "file_name": destination_path.name,
        "file_size_bytes": destination_path.stat().st_size,
    }


def _resolve_configured_file(file_path: str | None, label: str) -> Path | None:
    """Resolve a configured file path and fail when it does not exist.

    Returns None when the path is not configured. Raises StorageError when the
    path is missing or is not a regular file.
    """
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        raise StorageError(f"{label} file does not exist: {path}")
    if not path.is_file():
        raise StorageError(f"{label} path is not a file: {path}")

    return path


def _prepare_sender_data_file(config: AgentConfig, working_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Load sender's data file from container filesystem or S3 into working directory.

    Implements flexible sourcing for Day 1 MVP:
    - For local testing: reads file from container filesystem (e.g., /tmp/data.json)
    - For cloud deployment: downloads file from sender-side S3 storage

    The loaded file is staged in the container's working directory for subsequent processing:
    policy validation → manifest generation → compression → upload to sender SFTP.

    Routing logic:
    - If path starts with "s3://": download from S3
    - Otherwise: treat as path on container filesystem

    Parameters
    ----------
    config : AgentConfig
        Runtime configuration containing:
        - sender_data_file: Path to source file (container path or s3://bucket/key)
        - aws_region: AWS region for S3 operations (if using S3 source)
    working_dir : Path
        Temporary working directory on the container filesystem where file will be staged.
        Typically created by the caller with tempfile.TemporaryDirectory.

    Returns
    -------
    tuple[Path, dict[str, Any]]
        - staged_file_path: Path on container filesystem where the file was copied/downloaded
        - metadata: Dict describing the file source and size

    Raises
    ------
    StorageError
        If sender_data_file is not configured, source file doesn't exist on the
        container filesystem, is not a regular file, or S3 download fails
    """
    if not config.sender_data_file:
        _extract_data(config)
        raise StorageError(
            "Sender data file is required for Day 1. "
            "Set SENDER_DATA_FILE to a valid file path (local or s3://bucket/key)."
        )

    file_path = config.sender_data_file.strip()

    # Check if this is an S3 path
    if file_path.startswith("s3://"):
        try:
            # Create a staged file in working directory
            # Use the last component of the S3 key as the filename
            _, key = _parse_s3_path(file_path)
            file_name = Path(key).name or "data"
            staged_file = working_dir / file_name

            # Download from S3
            metadata = _download_from_s3(file_path, staged_file, config.aws_region)
            return staged_file, metadata
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to download from S3: {e}") from e

    # Otherwise, treat as local file path
    configured_file = _resolve_configured_file(file_path, "Sender data")
    if configured_file is not None:
        staged_file = working_dir / configured_file.name
        shutil.copy2(configured_file, staged_file)
        return staged_file, {
            "data_source": "sender_provided_file",
            "file_name": configured_file.name,
            "file_size_bytes": staged_file.stat().st_size,
        }

    _extract_data(config)
    raise StorageError(
        "Sender data file is required for Day 1. "
        "Set SENDER_DATA_FILE to a valid file path (local or s3://bucket/key)."
    )


def _write_sender_manifest_output(manifest: TransferManifest, manifest_path: Path) -> None:
    """Write the generated sender manifest to an output path.

    Applied field naming:
    - Source file: file_name, file_size_bytes, checksum_sha256
    - Archive file: zip_file_name, zip_file_size_bytes, checksum_sha256
    """
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_dict = manifest.model_dump(mode="json")
        # Rename archive fields for clarity before writing
        manifest_dict = apply_archive_field_naming(manifest_dict)

        with manifest_path.open("w", encoding="utf-8") as file_obj:
            json.dump(manifest_dict, file_obj, indent=2)
    except OSError as exc:
        raise StorageError(f"Failed to write sender manifest file {manifest_path}: {exc}") from exc


def _compute_checksum(file_path: Path, algorithm: ChecksumAlgorithm = DEFAULT_CHECKSUM_ALGORITHM) -> str:
    """Compute file checksum using specified algorithm.

    Parameters
    ----------
    file_path : Path
        Path to the file to checksum.
    algorithm : ChecksumAlgorithm, optional
        Algorithm to use. Defaults to SHA256.

    Returns
    -------
    str
        Hexadecimal digest of the file.

    Raises
    ------
    StorageError
        If the file cannot be read or algorithm is unsupported.
    """
    if algorithm != ChecksumAlgorithm.SHA256:
        raise StorageError(f"Unsupported checksum algorithm: {algorithm}")

    hash_obj = hashlib.sha256()
    try:
        with file_path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(8192), b""):
                hash_obj.update(chunk)
    except OSError as e:
        raise StorageError(f"Failed to read file {file_path}: {e}") from e

    return hash_obj.hexdigest()


def _safe_archive_member_name(file_name: str) -> str:
    """Validate archive member name to avoid unsafe paths in produced tarballs."""
    member_path = Path(file_name)
    if not file_name or file_name in {".", ".."}:
        raise StorageError("Archive member name cannot be empty or traversal markers")
    if member_path.is_absolute() or ".." in member_path.parts:
        raise StorageError(f"Unsafe archive member name: {file_name}")

    return file_name


def _build_sender_transfer_key(selected_mode: str, transfer_session_id: str, file_name: str) -> str:
    """Build sender staging transfer key based on input mode."""
    if selected_mode == "query":
        return QueryModeStoragePath.transfers(transfer_session_id, file_name)

    return FileModeStoragePath.transfers(transfer_session_id, file_name)


def _extract_file_extraction_config(dataproduct_id: str, definition_payload: dict[str, Any]) -> dict[str, Any]:
    """Return extraction config and enforce sender file-mode compatibility."""
    extraction = definition_payload.get("extraction")
    if not isinstance(extraction, dict):
        raise ConfigurationError(f"Dataproduct definition for '{dataproduct_id}' is missing extraction constraints")

    source_type = extraction.get("source_type")
    if source_type != "file":
        raise ConfigurationError(
            "Sender file mode only supports dataproduct definitions with "
            f"source_type='file', got '{source_type}' for '{dataproduct_id}'"
        )

    engine = extraction.get("engine")
    if engine != "s3-file":
        raise ConfigurationError(
            "Sender file mode only supports dataproduct definitions with "
            f"engine='s3-file', got '{engine}' for '{dataproduct_id}'"
        )

    return extraction


def _resolve_file_mode_source_from_request(config: AgentConfig) -> FileModeSource | None:
    """Resolve file-mode source from dataproduct request when provided."""
    request = config.dataproduct_request
    if request is None:
        return None

    try:
        definition = _load_runtime_dataproduct_registry().get(request.dataproduct_id)
    except KeyError as exc:
        raise ConfigurationError(str(exc)) from exc

    extraction = _extract_file_extraction_config(request.dataproduct_id, definition.payload)
    required_params, optional_params = _get_param_definitions(request.dataproduct_id, extraction)
    required_param_names, optional_param_names = _collect_param_names(required_params, optional_params)
    _validate_allowed_and_required_params(
        dataproduct_id=request.dataproduct_id,
        params=request.params,
        required_param_names=required_param_names,
        optional_param_names=optional_param_names,
    )
    _validate_allowed_param_values(
        params=request.params,
        param_definitions=required_params + optional_params,
    )

    s3_path_value = request.params.get("s3_path")
    if not isinstance(s3_path_value, str) or not s3_path_value.strip():
        raise ConfigurationError("File-mode dataproduct request requires params.s3_path as a non-empty string")

    s3_path = s3_path_value.strip()
    parsed = _parse_s3_path(s3_path)
    if parsed is None:
        raise ConfigurationError(f"File-mode param 's3_path' must be an S3 URL, got: {s3_path}")

    bucket, key = parsed
    file_name_value = request.params.get("file_name")
    if isinstance(file_name_value, str) and file_name_value.strip():
        file_name = file_name_value.strip()
    else:
        file_name = Path(key).name
    if not file_name:
        raise ConfigurationError(f"File-mode param 's3_path' must include an object key, got: {s3_path}")

    parent_key = key.rsplit("/", 1)[0] if "/" in key else ""
    marker_directory = f"s3://{bucket}/{parent_key}/" if parent_key else f"s3://{bucket}/"
    return FileModeSource(
        s3_path=s3_path,
        file_name=file_name,
        marker_directory=marker_directory,
    )


def _select_file_mode_source(config: AgentConfig) -> FileModeSource | None:
    """Return resolved file-mode source, or None when no work exists."""
    request_source = _resolve_file_mode_source_from_request(config)
    if request_source is not None:
        marker_bucket, marker_key = _resolve_file_mode_processed_marker(
            request_source.marker_directory,
            request_source.file_name,
        )
        if _retry_operation(
            "check_file_processed",
            lambda: _marker_exists(
                S3Client(aws_region=config.aws_region),
                marker_bucket,
                marker_key,
            ),
        ):
            LOGGER.info(
                prefix_log_message(
                    "No new file read. Exiting sender workflow (idempotent).",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_no_files",
                    "resolution": "dataproduct_request",
                    "file_name": request_source.file_name,
                    "s3_path": request_source.s3_path,
                },
            )
            return None

        LOGGER.info(
            prefix_log_message(
                "Resolved file-mode source from dataproduct request",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_file_source_resolved",
                "resolution": "dataproduct_request",
                "s3_path": request_source.s3_path,
                "file_name": request_source.file_name,
            },
        )
        return request_source

    if not config.sender_data_directory:
        LOGGER.warning(
            prefix_log_message(
                "Sender data directory not configured. "
                "Set SENDER_DATA_DIRECTORY to a valid S3 directory path (e.g., s3://bucket/outgoing/)",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            )
        )
        return None

    LOGGER.info(
        prefix_log_message(
            "Scanning sender directory for new files",
            agent_mode=config.agent_mode,
            transfer_session_id=config.transfer_session_id,
        ),
        extra={"event": "sender_scan_start", "directory": config.sender_data_directory},
    )
    files_to_process = _retry_operation(
        "detect_files",
        lambda: _scan_sender_directory(config.sender_data_directory, config.aws_region),
    )

    if not files_to_process:
        LOGGER.info(
            prefix_log_message(
                "No new file read. Exiting sender workflow (idempotent).",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_no_files", "directory": config.sender_data_directory},
        )
        return None

    LOGGER.info(
        prefix_log_message(
            f"Found {len(files_to_process)} file(s) to process in sender directory",
            agent_mode=config.agent_mode,
            transfer_session_id=config.transfer_session_id,
        ),
        extra={"event": "sender_files_found", "file_count": len(files_to_process)},
    )

    s3_path, file_name = files_to_process[0]
    LOGGER.info(
        prefix_log_message(
            f"Processing file: {file_name}",
            agent_mode=config.agent_mode,
            transfer_session_id=config.transfer_session_id,
        ),
        extra={"event": "sender_process_start", "file_name": file_name, "s3_path": s3_path},
    )
    return FileModeSource(
        s3_path=s3_path,
        file_name=file_name,
        marker_directory=config.sender_data_directory,
    )


def _prepare_query_mode_input(config: AgentConfig, tmpdir_path: Path) -> SenderInputPreparation | None:
    """Validate, execute, and stage query-mode source input.

    Returns None when query mode should exit early (validation failure, execution
    failure, or idempotent skip) after logging the appropriate audit events.
    """
    try:
        contract = _resolve_and_validate_sender_query_contract(config)
    except ConfigurationError as exc:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_contract_validation",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return None

    try:
        query_result = execute_query(contract, config)
    except ConfigurationError as exc:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return None
    except StorageError as exc:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": str(exc),
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(exc)},
        )
        return None
    except Exception as exc:
        error_message = f"Unexpected error during query execution: {exc}"
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_execution",
                "error": error_message,
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": error_message},
        )
        return None

    if query_result.skipped:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "step": "query_execution_skipped",
                "template_id": contract.template_id,
                "reason": QUERY_SKIP_REASON_MATCHING_MARKER,
                "fingerprint": query_result.query_fingerprint,
                "marker_key": query_result.marker_key,
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details={
                "template_id": contract.template_id,
                "skipped": True,
                "reason": QUERY_SKIP_REASON_MATCHING_MARKER,
                "fingerprint": query_result.query_fingerprint,
                "marker_key": query_result.marker_key,
            },
        )
        return None

    try:
        parsed_output = _parse_s3_path(query_result.output_file_path)
        if parsed_output is None:
            raise StorageError("Query output path must be an S3 URL, got: " f"{query_result.output_file_path}")

        _bucket, output_key = parsed_output
        file_name = Path(output_key).name
        staged_file = tmpdir_path / file_name
        _retry_operation(
            "download_query_result",
            lambda: _download_from_s3(
                query_result.output_file_path,
                staged_file,
                config.aws_region,
            ),
        )

        extract_details = {
            "data_source": "query_execution",
            "template_id": contract.template_id,
            "query_output_path": query_result.output_file_path,
            "query_fingerprint": query_result.query_fingerprint,
            "file_name": file_name,
            "row_count": query_result.row_count,
            "file_size_bytes": query_result.file_size_bytes,
            "staged_file_size_bytes": staged_file.stat().st_size,
            "duration_seconds": round(query_result.execution_duration_seconds, 2),
        }
        pipeline_complete_details = {
            "template_id": contract.template_id,
            "row_count": query_result.row_count,
            "file_size_bytes": query_result.file_size_bytes,
            "duration_seconds": round(query_result.execution_duration_seconds, 2),
        }
        return SenderInputPreparation(
            staged_file=staged_file,
            file_name=file_name,
            extract_details=extract_details,
            pipeline_complete_details=pipeline_complete_details,
        )
    except Exception as e:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "query_result_download",
                "selected_path": query_result.output_file_path,
                "error": f"Failed to download query output: {e}",
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": f"Failed to download query output: {e}"},
        )
        return None


def _prepare_file_mode_input(
    config: AgentConfig,
    tmpdir_path: Path,
    s3_path: str,
    file_name: str,
) -> SenderInputPreparation:
    """Download file-mode source input from S3 into local staging."""
    try:
        bucket, key = _parse_s3_path(s3_path)
        client = S3Client(aws_region=config.aws_region)
        staged_file = tmpdir_path / file_name
        _retry_operation(
            "download_sender_file",
            lambda: client.download_file(bucket, key, staged_file),
        )

        extract_details = {
            "data_source": "s3_object",
            "s3_path": s3_path,
            "file_name": file_name,
            "file_size_bytes": staged_file.stat().st_size,
        }
        return SenderInputPreparation(
            staged_file=staged_file,
            file_name=file_name,
            extract_details=extract_details,
        )
    except Exception as e:
        log_extract_data(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={
                "step": "detect",
                "selected_path": s3_path,
                "error": f"Failed to download file: {e}",
            },
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": f"Failed to download file: {e}"},
        )
        raise StorageError(f"Failed to download {s3_path}: {e}") from e


def _build_policy_check_details(config: AgentConfig, file_count: int, is_approved: bool) -> dict[str, Any]:
    """Build audit detail payload for sender policy check outcomes."""
    details: dict[str, Any] = {
        "decision": "allow" if is_approved else "deny",
        "reason": "policy_approved" if is_approved else "policy_approval_denied",
        "file_count": file_count,
    }

    request = config.dataproduct_request
    if request is None:
        return details

    details["request_id"] = request.request_id
    details["dataproduct_id"] = request.dataproduct_id
    classification_tags = {
        key: value
        for key, value in request.metadata.items()
        if "classification" in key.lower()
    }
    if classification_tags:
        details["classification_tags"] = classification_tags

    return details


def _run_sender_transfer_pipeline(
    config: AgentConfig,
    selected_mode: str,
    staged_file: Path,
    file_name: str,
    tmpdir_path: Path,
) -> SenderTransferArtifacts | None:
    """Run shared sender transfer steps after source input is prepared."""
    approver = PolicyApprover()
    is_approved = approver.approve_transfer(
        config.sender_agency,
        1,
    )

    if not is_approved:
        policy_details = _build_policy_check_details(config=config, file_count=1, is_approved=False)
        log_policy_check(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details=policy_details,
        )
        return None

    policy_details = _build_policy_check_details(config=config, file_count=1, is_approved=True)
    log_policy_check(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        outcome=EventOutcome.SUCCESS,
        details=policy_details,
    )

    request_executing_event: dict[str, Any] = {
        "event": "request_executing",
        "selected_mode": selected_mode,
        "file_name": file_name,
        "policy_decision": "allow",
    }
    request_id = policy_details.get("request_id")
    dataproduct_id = policy_details.get("dataproduct_id")
    classification_tags = policy_details.get("classification_tags")
    if isinstance(request_id, str):
        request_executing_event["request_id"] = request_id
    if isinstance(dataproduct_id, str):
        request_executing_event["dataproduct_id"] = dataproduct_id
    if isinstance(classification_tags, dict):
        request_executing_event["classification_tags"] = classification_tags

    LOGGER.info(
        prefix_log_message(
            "Request executing",
            agent_mode=config.agent_mode,
            transfer_session_id=config.transfer_session_id,
        ),
        extra=request_executing_event,
    )

    archive_path = tmpdir_path / DEFAULT_ARCHIVE_FILE_NAME
    archive_member_name = _safe_archive_member_name(staged_file.name)
    try:
        _retry_operation(
            "compress_sender_data",
            lambda: _compress_sender_data(archive_path, staged_file, archive_member_name),
        )
    except Exception as e:
        log_compress(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"step": "compress", "source_file_name": staged_file.name, "error": str(e)},
        )
        raise

    log_compress(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        outcome=EventOutcome.SUCCESS,
        details={
            "compression_type": DEFAULT_COMPRESSION.value,
            "source_file_name": staged_file.name,
            "source_size_bytes": staged_file.stat().st_size,
            "compressed_size_bytes": archive_path.stat().st_size,
        },
    )

    manifest_files = [
        ManifestFile(
            file_name=file_name,
            file_size_bytes=staged_file.stat().st_size,
            checksum_sha256=_compute_checksum(staged_file, DEFAULT_CHECKSUM_ALGORITHM),
        ),
        ManifestFile(
            file_name=archive_path.name,
            file_size_bytes=archive_path.stat().st_size,
            checksum_sha256=_compute_checksum(archive_path, DEFAULT_CHECKSUM_ALGORITHM),
        ),
    ]

    manifest = TransferManifest(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        compression_type=DEFAULT_COMPRESSION,
        total_file_count=len(manifest_files),
        files=manifest_files,
    )

    manifest_path = tmpdir_path / DEFAULT_MANIFEST_FILE_NAME
    try:
        _retry_operation(
            "write_manifest",
            lambda: _write_sender_manifest_output(manifest, manifest_path),
        )
    except Exception as e:
        log_manifest_created(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"step": "manifest", "error": str(e)},
        )
        raise

    log_manifest_created(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        outcome=EventOutcome.SUCCESS,
        details={
            "manifest_path": _build_sender_transfer_key(
                selected_mode,
                config.transfer_session_id,
                manifest_path.name,
            ),
            "payload_file_count": manifest.total_file_count,
            "archive_name": archive_path.name,
        },
    )

    staging_client = S3Client(aws_region=config.aws_region)
    total_staged_bytes = 0
    staged_artifacts: list[tuple[Path, str]] = []
    staged_artifact_keys: list[str] = []
    for artifact_path in (archive_path, manifest_path):
        staging_key = _build_sender_transfer_key(
            selected_mode,
            config.transfer_session_id,
            artifact_path.name,
        )
        _retry_operation(
            "stage_upload",
            lambda artifact_path=artifact_path, staging_key=staging_key: staging_client.upload_file(
                artifact_path, config.sender_staging_bucket, staging_key
            ),
        )

        total_staged_bytes += artifact_path.stat().st_size
        staged_artifacts.append((artifact_path, staging_key))
        staged_artifact_keys.append(staging_key)
        LOGGER.info(
            prefix_log_message(
                f"Staged artifact to S3: {artifact_path.name}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_artifact_staged",
                "bucket": config.sender_staging_bucket,
                "key": staging_key,
            },
        )

    sftp_client = create_sftp_client_from_credentials(
        sftp_endpoints=config.sftp_endpoints,
        username=config.sftp_username,
        private_key_content=config.sftp_private_key,
    )
    primary_sftp_endpoint = config.sftp_endpoints[0]
    total_sftp_uploaded_bytes = 0
    log_sftp_transfer_start(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        destination_host=primary_sftp_endpoint,
        details={
            "step": "sftp_upload",
            "artifact_count": len(staged_artifacts),
            "endpoints": config.sftp_endpoints,
        },
    )

    for artifact_path, _staging_key in staged_artifacts:
        remote_path = f"/{config.sender_agency}/{config.transfer_session_id}/{artifact_path.name}"
        try:
            upload_metadata = _retry_operation(
                "sftp_upload",
                lambda artifact_path=artifact_path, remote_path=remote_path: sftp_client.upload_file(
                    artifact_path, remote_path
                ),
            )
        except Exception as e:
            log_sftp_transfer_complete(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                destination_host=primary_sftp_endpoint,
                bytes_transferred=total_sftp_uploaded_bytes,
                outcome=EventOutcome.FAILURE,
                details={
                    "step": "sftp_upload",
                    "remote_path": remote_path,
                    "error": str(e),
                },
            )
            raise

        total_sftp_uploaded_bytes += int(upload_metadata.get("file_size_bytes", 0))
        LOGGER.info(
            prefix_log_message(
                f"Uploaded artifact to SFTP: {artifact_path.name}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_artifact_uploaded_sftp",
                "remote_path": remote_path,
                "endpoint": upload_metadata.get("endpoint", primary_sftp_endpoint),
            },
        )

    log_sftp_transfer_complete(
        transfer_session_id=config.transfer_session_id,
        sender_agency=config.sender_agency,
        receiver_agency=config.receiver_agency,
        destination_host=primary_sftp_endpoint,
        outcome=EventOutcome.SUCCESS,
        bytes_transferred=total_sftp_uploaded_bytes,
        details={
            "step": "sftp_upload",
            "artifact_count": len(staged_artifacts),
            "remote_prefix": f"/{config.sender_agency}/{config.transfer_session_id}/",
            "staging_prefix": (
                QueryModeStoragePath.transfer_prefix(config.transfer_session_id)
                if selected_mode == "query"
                else FileModeStoragePath.transfer_prefix(config.transfer_session_id)
            ),
            "staged_bytes": total_staged_bytes,
        },
    )

    return SenderTransferArtifacts(
        manifest=manifest,
        staged_artifact_keys=staged_artifact_keys,
    )


def _create_sender_workflow(config: AgentConfig) -> int:
    """Execute sender-side transfer workflow.

    Implements: Extract → Policy → Compress → Manifest → Stage

    Scans SENDER_DATA_DIRECTORY for new files to process. Files marked with .done
    in processed/ directory are skipped. After successful processing, creates a
    .done marker to prevent reprocessing.

    Parameters
    ----------
    config : AgentConfig
        Validated runtime configuration.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    try:
        selected_mode, selection_reason = _select_sender_input_mode(config.sender_input_mode)
        LOGGER.info(
            prefix_log_message(
                "Selected sender input mode",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={
                "event": "sender_input_mode_selected",
                "selected_mode": selected_mode,
                "selection_source": "SENDER_INPUT_MODE",
                "selection_reason": selection_reason,
            },
        )

        file_mode_source: FileModeSource | None = None
        if selected_mode != "query":
            file_mode_source = _select_file_mode_source(config)
            if file_mode_source is None:
                return 0

        # 1. Log pipeline start
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
        )
        pipeline_complete_details: dict[str, Any] | None = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            prepared_input: SenderInputPreparation | None = None
            if selected_mode == "query":
                prepared_input = _prepare_query_mode_input(config, tmpdir_path)
            else:
                if file_mode_source is None:
                    raise StorageError("File mode source selection was not initialized")
                prepared_input = _prepare_file_mode_input(
                    config,
                    tmpdir_path,
                    file_mode_source.s3_path,
                    file_mode_source.file_name,
                )

            if prepared_input is None:
                return 0

            pipeline_complete_details = prepared_input.pipeline_complete_details
            staged_file = prepared_input.staged_file
            file_name = prepared_input.file_name
            extract_details = prepared_input.extract_details

            LOGGER.info(
                prefix_log_message(
                    f"File read successfully: {file_name}",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_file_read",
                    "file_name": file_name,
                    "file_size_bytes": extract_details.get("file_size_bytes"),
                },
            )

            log_extract_data(
                transfer_session_id=config.transfer_session_id,
                sender_agency=config.sender_agency,
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
                details=extract_details,
            )

            transfer_artifacts = _run_sender_transfer_pipeline(
                config=config,
                selected_mode=selected_mode,
                staged_file=staged_file,
                file_name=file_name,
                tmpdir_path=tmpdir_path,
            )
            if transfer_artifacts is None:
                return 1

            # 6. Mark file as processed for file mode inputs.
            if selected_mode != "query":
                if file_mode_source is None:
                    raise StorageError("File mode source selection was not initialized")
                _retry_operation(
                    "mark_file_processed",
                    lambda: _mark_file_processed(file_name, file_mode_source.marker_directory, config.aws_region),
                )
                LOGGER.info(
                    prefix_log_message(
                        f"File marked as processed and moved to processed folder: {file_name}",
                        agent_mode=config.agent_mode,
                        transfer_session_id=config.transfer_session_id,
                    ),
                    extra={
                        "event": "sender_file_marked",
                        "file_name": file_name,
                        "marker_location": (
                            f"{file_mode_source.marker_directory}../"
                            f"{FileModeStoragePath.processed_prefix()}{file_name}{DONE_MARKER_SUFFIX}"
                        ),
                    },
                )

            LOGGER.info(
                prefix_log_message(
                    "Sender workflow complete",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "sender_complete",
                    "session_id": config.transfer_session_id,
                    "manifest": transfer_artifacts.manifest.model_dump(),
                    "staged_artifacts": transfer_artifacts.staged_artifact_keys,
                },
            )

        # Pipeline completion
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.SUCCESS,
            details=pipeline_complete_details,
        )

        return 0

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Sender workflow failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "sender_error", "error_type": type(e).__name__},
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency=config.sender_agency,
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(e)},
        )
        return 1


def _compress_sender_data(archive_path: Path, staged_file: Path, archive_member_name: str) -> None:
    """Create transfer archive for sender payload."""
    with tarfile.open(archive_path, "w:gz") as tar:  # NOSONAR
        tar.add(staged_file, arcname=archive_member_name)


def _scan_extracted_files(
    extract_dir: Path,
    transfer_session_id: str,
    sender_agency: str,
    receiver_agency: str,
) -> None:
    """Scan all extracted files with ClamAV before allowing storage.

    Iterates every regular file under *extract_dir* and calls scan_file().
    Fails closed on both infection and scanner error — neither case proceeds
    to storage.

    Raises
    ------
    InfectedFileError
        If any file is found to be infected.
    StorageError
        If the scanner itself fails (binary missing, timeout, exit code 2+).
    """
    files = sorted(f for f in extract_dir.rglob("*") if f.is_file())
    for file_path in files:
        result = scan_file(file_path)
        audit = {
            "event": AuditEventType.VIRUS_SCAN,
            "file_name": file_path.name,
            "transfer_session_id": transfer_session_id,
            "sender_agency": sender_agency,
            "receiver_agency": receiver_agency,
        }

        if result.status == ScanStatus.CLEAN:
            LOGGER.info(
                prefix_log_message(f"Virus scan clean: {file_path.name}"),
                extra={**audit, "outcome": EventOutcome.SUCCESS},
            )
            continue

        LOGGER.error(
            prefix_log_message(f"Virus scan {result.status.value.upper()}: {file_path.name} — {result.detail}"),
            extra={**audit, "outcome": EventOutcome.FAILURE, "detail": result.detail},
        )
        if result.status == ScanStatus.INFECTED:
            raise InfectedFileError(
                f"Infected file detected in transfer {transfer_session_id}: "
                f"{file_path.name} — {result.detail}"
            )
        raise StorageError(
            f"Virus scanner error for {file_path.name} in transfer "
            f"{transfer_session_id}: {result.detail}"
        )


def _process_single_receiver_transfer(
    landing_zone: ReceiverLandingZone,
    target_store: ReceiverTargetStore,
    config: AgentConfig,
    sender_agency: str,
    transfer_session_id: str,
) -> int:
    """Fetch, validate, decompress, and store one transfer from the landing bucket.

    Parameters
    ----------
    landing_zone : ReceiverLandingZone
    target_store : ReceiverTargetStore
    config : AgentConfig
    sender_agency : str
        Discovered sender agency code (e.g., "dot").
    transfer_session_id : str
        Discovered transfer session ID from the S3 folder name.

    Returns
    -------
    int
        0 on success, 1 on failure.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="redwood-receiver-") as tmpdir:
            work_dir = Path(tmpdir)
            archive_payload, manifest_dict = _retry_operation(
                "landing_fetch",
                lambda: landing_zone.fetch_from_landing_bucket(
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                    target_directory=work_dir,
                ),
            )

            archive_path = archive_payload if isinstance(archive_payload, Path) else None
            archive_bytes = archive_payload if isinstance(archive_payload, bytes) else None

            manifest = _retry_operation(
                "manifest_validate",
                lambda: landing_zone.validate_manifest(
                    manifest_dict=manifest_dict,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                    archive_bytes=archive_bytes,
                    archive_path=archive_path,
                ),
            )

            # Guardrail: manifest identity must match what we discovered from S3.
            if manifest.transfer_session_id != transfer_session_id:
                raise StorageError(
                    "Manifest transfer_session_id mismatch: "
                    f"expected {transfer_session_id}, got {manifest.transfer_session_id}"
                )
            if manifest.receiver_agency and manifest.receiver_agency != config.receiver_agency:
                raise StorageError(
                    "Manifest receiver_agency mismatch: "
                    f"expected {config.receiver_agency}, got {manifest.receiver_agency}"
                )

            extract_dir = work_dir / "extracted"
            _retry_operation(
                "decompress",
                lambda: landing_zone.decompress_archive(
                    target_directory=extract_dir,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                    archive_bytes=archive_bytes,
                    archive_path=archive_path,
                ),
            )

            _scan_extracted_files(
                extract_dir=extract_dir,
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=config.receiver_agency,
            )

            _retry_operation(
                "store_to_target",
                lambda: target_store.store_to_target(
                    extracted_files_dir=extract_dir,
                    transfer_session_id=transfer_session_id,
                    sender_agency=sender_agency,
                    receiver_agency=config.receiver_agency,
                ),
            )

        return 0

    except InfectedFileError as e:
        # Write a permanent rejection marker so this transfer is never retried.
        # The existing is_transfer_already_stored pre-check covers .rejected keys,
        # so subsequent receiver cycles skip it before any S3 fetch or decompress.
        LOGGER.error(
            prefix_log_message(
                f"Transfer from {sender_agency} rejected: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=transfer_session_id,
            ),
            extra={
                "event": "receiver_transfer_rejected",
                "sender_agency": sender_agency,
                "transfer_session_id": transfer_session_id,
                "error_type": type(e).__name__,
            },
        )
        try:
            target_store.mark_transfer_rejected(
                transfer_session_id=transfer_session_id,
                sender_agency=sender_agency,
                receiver_agency=config.receiver_agency,
                reason=str(e),
            )
        except Exception as marker_err:
            LOGGER.error(
                prefix_log_message(
                    f"Failed to write rejection marker for {transfer_session_id}: {marker_err}"
                )
            )
        return 1

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Transfer from {sender_agency} failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=transfer_session_id,
            ),
            extra={
                "event": "receiver_transfer_error",
                "sender_agency": sender_agency,
                "transfer_session_id": transfer_session_id,
                "error_type": type(e).__name__,
            },
        )
        return 1


def _process_discovered_receiver_transfer(
    landing_zone: ReceiverLandingZone,
    target_store: ReceiverTargetStore,
    config: AgentConfig,
    sender_agency: str,
    transfer_session_id: str,
) -> tuple[str, dict[str, str]]:
    """Process one discovered transfer and return its status with transfer metadata."""
    transfer_ref = {
        "sender_agency": sender_agency,
        "transfer_session_id": transfer_session_id,
    }

    with logging_context(transfer_session_id):
        # Pre-check target idempotency marker so already-complete transfers
        # are not fetched/validated/decompressed again.
        if target_store.is_transfer_already_stored(transfer_session_id, sender_agency):
            LOGGER.debug(
                prefix_log_message(
                    f"Transfer from {sender_agency} already marked done in target; skipping.",
                    agent_mode=config.agent_mode,
                ),
                extra={
                    "event": "receiver_transfer_skip_done",
                    "sender_agency": sender_agency,
                    "transfer_session_id": transfer_session_id,
                },
            )
            return "already_processed", transfer_ref

        LOGGER.info(
            prefix_log_message(
                f"Processing transfer from {sender_agency}",
                agent_mode=config.agent_mode,
            ),
            extra={
                "event": "receiver_transfer_start",
                "sender_agency": sender_agency,
                "transfer_session_id": transfer_session_id,
            },
        )
        result = _process_single_receiver_transfer(
            landing_zone, target_store, config, sender_agency, transfer_session_id
        )
        if result == 0:
            return "processed", transfer_ref
        return "failed", transfer_ref


def _create_receiver_workflow(config: AgentConfig) -> int:
    """Execute receiver-side transfer workflow.

    Polls all sender agency folders in the landing bucket and processes every
    pending transfer session found.  The target-store idempotency marker prevents
    re-processing already-stored sessions.

    Returns 0 when all discovered transfers succeed (or there is nothing to do).
    Returns 1 if any individual transfer fails.
    """
    try:
        log_pipeline_start(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
        )

        s3_client = S3Client(aws_region=config.aws_region)
        landing_zone = ReceiverLandingZone(
            s3_client=s3_client,
            landing_bucket=config.receiver_landing_bucket,
            environment=config.environment,
        )
        target_store = ReceiverTargetStore(
            s3_client=s3_client,
            target_bucket=config.receiver_target_bucket,
            environment=config.environment,
        )

        # Scan the landing bucket for all sender agency folders.
        sender_agencies = _retry_operation(
            "list_sender_agencies",
            landing_zone.list_sender_agencies,
        )

        if not sender_agencies:
            LOGGER.info(
                prefix_log_message(
                    "No sender agency folders found in landing bucket; nothing to process.",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={"event": "receiver_no_senders", "bucket": config.receiver_landing_bucket},
            )
            log_pipeline_complete(
                transfer_session_id=config.transfer_session_id,
                sender_agency="",
                receiver_agency=config.receiver_agency,
                outcome=EventOutcome.SUCCESS,
            )
            return 0

        LOGGER.debug(
            prefix_log_message(
                f"Found {len(sender_agencies)} sender agency folder(s): {sender_agencies}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "receiver_senders_found", "sender_agencies": sender_agencies},
        )

        status_counts: dict[str, int] = {
            "processed": 0,
            "already_processed": 0,
            "failed": 0,
        }
        transfer_details: dict[str, list[dict[str, str]]] = {
            "processed": [],
            "already_processed": [],
            "failed": [],
        }

        for sender_agency in sender_agencies:
            transfer_sessions = _retry_operation(
                f"list_pending_transfers_{sender_agency}",
                lambda sa=sender_agency: landing_zone.list_pending_transfers(sa),
            )
            for transfer_session_id in transfer_sessions:
                status, transfer_ref = _process_discovered_receiver_transfer(
                    landing_zone=landing_zone,
                    target_store=target_store,
                    config=config,
                    sender_agency=sender_agency,
                    transfer_session_id=transfer_session_id,
                )
                status_counts[status] += 1
                transfer_details[status].append(transfer_ref)

        processed = status_counts["processed"]
        already_processed = status_counts["already_processed"]
        failed = status_counts["failed"]
        processed_transfers = transfer_details["processed"]
        already_processed_transfers = transfer_details["already_processed"]
        failed_transfers = transfer_details["failed"]

        recent_already_processed: list[dict[str, str]] = []

        if processed == 0 and failed == 0:
            LOGGER.info(
                prefix_log_message(
                    "No new files to process. Exiting receiver workflow (idempotent).",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "receiver_no_new_files",
                    "already_processed": already_processed,
                    "bucket": config.receiver_landing_bucket,
                },
            )
        else:
            recent_already_processed = sorted(
                already_processed_transfers,
                key=lambda item: item["transfer_session_id"],
                reverse=True,
            )[:3]
            recent_already_processed_refs = [
                f"{item['sender_agency']}/{item['transfer_session_id']}" for item in recent_already_processed
            ]

            LOGGER.info(
                prefix_log_message(
                    "Receiver scan complete: "
                    f"{processed} processed, {already_processed} already processed, {failed} failed "
                    f"(last_3_already_processed={recent_already_processed_refs})",
                    agent_mode=config.agent_mode,
                    transfer_session_id=config.transfer_session_id,
                ),
                extra={
                    "event": "receiver_scan_complete",
                    "processed": processed,
                    "already_processed": already_processed,
                    "failed": failed,
                    "last_3_already_processed": recent_already_processed,
                },
            )

        outcome = EventOutcome.SUCCESS if failed == 0 else EventOutcome.FAILURE
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
            outcome=outcome,
            details={
                "processed": processed,
                "already_processed": already_processed,
                "failed": failed,
                "processed_transfers": processed_transfers,
                "last_3_already_processed": recent_already_processed,
                "failed_transfers": failed_transfers,
            },
        )

        return 0 if failed == 0 else 1

    except Exception as e:
        LOGGER.error(
            prefix_log_message(
                f"Receiver workflow failed: {e}",
                agent_mode=config.agent_mode,
                transfer_session_id=config.transfer_session_id,
            ),
            extra={"event": "receiver_error", "error_type": type(e).__name__},
        )
        log_pipeline_complete(
            transfer_session_id=config.transfer_session_id,
            sender_agency="",
            receiver_agency=config.receiver_agency,
            outcome=EventOutcome.FAILURE,
            details={"error": str(e)},
        )
        return 1


def run_agent(config: AgentConfig) -> int:
    """Run the agent workflow for the configured mode.

    Routes to sender or receiver workflow based on config.agent_mode.
    All workflows include audit logging and error handling.

    Parameters
    ----------
    config : AgentConfig
        Validated runtime configuration with agency and environment settings.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    if config.agent_mode == "sender":
        return _create_sender_workflow(config)
    elif config.agent_mode == "receiver":
        return _create_receiver_workflow(config)
    else:
        raise ConfigurationError(f"Invalid agent mode: {config.agent_mode}. Must be 'sender' or 'receiver'.")
