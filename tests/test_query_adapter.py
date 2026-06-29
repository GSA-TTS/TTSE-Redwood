"""Unit tests for the Ibis query adapter."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from redwood_dataagent.agent import SenderQueryInputContract
from redwood_dataagent.audit.events import AuditEventType, EventOutcome
from redwood_dataagent.config import AgentConfig
from redwood_dataagent.exceptions import ConfigurationError, StorageError
from redwood_dataagent.query_adapter import (
    QueryExecutionResult,
    _build_ibis_query,
    _execute_query_with_timeout,
    _get_ibis_connection,
    _upload_results_to_s3,
    _write_query_results_to_file,
    execute_query,
)


class TestGetIbisConnection:
    """Tests for _get_ibis_connection()."""

    def test_get_ibis_connection_imports_ibis(self) -> None:
        """Connection attempt requires ibis library."""
        with patch.dict(
            "os.environ",
            {
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=False,
        ):
            with patch("redwood_dataagent.query_adapter.ibis") as mock_ibis:
                mock_ibis.postgres.connect.return_value = MagicMock()

                connection = _get_ibis_connection("dot")

                assert connection is not None
                mock_ibis.postgres.connect.assert_called_once()

    def test_get_ibis_connection_uses_postgres_by_default(self) -> None:
        """Connection defaults to postgres when DB_ENGINE is not set."""
        with patch.dict(
            "os.environ",
            {
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=True,
        ):
            with patch("redwood_dataagent.query_adapter.ibis") as mock_ibis:
                mock_ibis.postgres.connect.return_value = MagicMock()

                _get_ibis_connection("dot")

                mock_ibis.postgres.connect.assert_called_once()

    def test_get_ibis_connection_unsupported_engine_raises_configuration_error(self) -> None:
        """Unsupported DB_ENGINE values fail fast with a clear error."""
        with patch.dict(
            "os.environ",
            {
                "DB_ENGINE": "mysql",
                "DB_HOST": "example-host",
                "DB_PORT": "3306",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=True,
        ):
            with patch("redwood_dataagent.query_adapter.ibis") as mock_ibis:
                mock_ibis.postgres.connect.return_value = MagicMock()

                with pytest.raises(ConfigurationError, match="Unsupported DB_ENGINE"):
                    _get_ibis_connection("dot")

    def test_get_ibis_connection_missing_ibis_raises_configuration_error(self) -> None:
        """Missing Ibis library raises ConfigurationError."""
        with patch("redwood_dataagent.query_adapter.ibis", None):
            with pytest.raises(ConfigurationError, match="Ibis postgres backend is unavailable"):
                _get_ibis_connection("dot")

    def test_get_ibis_connection_database_error_raises_configuration_error(self) -> None:
        """Database connection failure raises ConfigurationError."""
        with patch.dict(
            "os.environ",
            {
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=False,
        ):
            with patch("redwood_dataagent.query_adapter.ibis") as mock_ibis:
                mock_ibis.postgres.connect.side_effect = Exception("Connection refused")

                with pytest.raises(ConfigurationError, match="Failed to connect to PostgreSQL"):
                    _get_ibis_connection("dot")


class TestBuildIbisQuery:
    """Tests for _build_ibis_query()."""

    def test_build_ibis_query_basic(self) -> None:
        """Build query from validated contract with basic parameters."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "select_fields": ["contract_id", "vendor_name"],
            },
            row_limit=1000,
            timeout_seconds=60,
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            mock_table = MagicMock()
            mock_table.select.return_value = mock_table
            mock_connection = MagicMock()
            mock_connection.table.return_value = mock_table
            mock_get_conn.return_value = mock_connection

            ibis_table, row_limit = _build_ibis_query(contract)

            assert ibis_table is mock_table
            assert row_limit == 1000
            mock_connection.table.assert_called_once_with("contract_data", schema="dot")
            mock_table.select.assert_called_once()

    def test_build_ibis_query_with_filters(self) -> None:
        """Build query applies min/max filters."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "filters": {
                    "contract_value": {"min": 1000000},
                    "award_date": {"max": "2026-12-31"},
                },
            },
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            mock_table = MagicMock()
            mock_connection = MagicMock()
            mock_connection.table.return_value = mock_table
            mock_table.filter.return_value = mock_table
            mock_get_conn.return_value = mock_connection

            ibis_table, _ = _build_ibis_query(contract)

            # Verify filter was called twice (once for min, once for max)
            assert mock_table.filter.call_count == 2

    def test_build_ibis_query_with_order_by(self) -> None:
        """Build query applies ordering with DESC direction."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "order_by": "award_date DESC",
            },
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            # Mock the entire ibis module with desc and asc functions
            mock_ibis = MagicMock()
            mock_desc_result = MagicMock()
            mock_ibis.desc.return_value = mock_desc_result
            
            mock_table = MagicMock()
            mock_connection = MagicMock()
            mock_connection.table.return_value = mock_table
            mock_table.order_by.return_value = mock_table
            mock_get_conn.return_value = mock_connection

            with patch("redwood_dataagent.query_adapter.ibis", mock_ibis):
                ibis_table, _ = _build_ibis_query(contract)

                # Verify ibis.desc() was called with the correct field
                mock_ibis.desc.assert_called_once_with("award_date")
                # Verify order_by was called with the result of ibis.desc()
                mock_table.order_by.assert_called_once_with(mock_desc_result)

    def test_build_ibis_query_with_order_by_asc(self) -> None:
        """Build query applies ordering with ASC direction."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "order_by": "vendor_name ASC",
            },
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            # Mock the entire ibis module with desc and asc functions
            mock_ibis = MagicMock()
            mock_asc_result = MagicMock()
            mock_ibis.asc.return_value = mock_asc_result
            
            mock_table = MagicMock()
            mock_connection = MagicMock()
            mock_connection.table.return_value = mock_table
            mock_table.order_by.return_value = mock_table
            mock_get_conn.return_value = mock_connection

            with patch("redwood_dataagent.query_adapter.ibis", mock_ibis):
                ibis_table, _ = _build_ibis_query(contract)

                # Verify ibis.asc() was called with the correct field
                mock_ibis.asc.assert_called_once_with("vendor_name")
                # Verify order_by was called with the result of ibis.asc()
                mock_table.order_by.assert_called_once_with(mock_asc_result)

    def test_build_ibis_query_falls_back_when_schema_kwarg_is_unsupported(self) -> None:
        """Backends without schema= support should fall back to database=."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
            },
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            mock_table = MagicMock()
            mock_connection = MagicMock()

            def _table_side_effect(*args, **kwargs):
                if "schema" in kwargs:
                    raise TypeError("SQLBackend.table() got an unexpected keyword argument 'schema'")
                return mock_table

            mock_connection.table.side_effect = _table_side_effect
            mock_get_conn.return_value = mock_connection

            ibis_table, _ = _build_ibis_query(contract)

            assert ibis_table is mock_table
            assert mock_connection.table.call_count == 2
            assert mock_connection.table.call_args_list[0].kwargs == {
                "schema": "dot",
            }
            assert mock_connection.table.call_args_list[1].kwargs == {
                "database": "dot",
            }

    def test_build_ibis_query_missing_schema_raises(self) -> None:
        """Query without schema raises ConfigurationError."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={"table": "contract_data"},
        )

        with pytest.raises(ConfigurationError, match="must specify 'schema' and 'table'"):
            _build_ibis_query(contract)

    def test_build_ibis_query_invalid_filter_format_raises(self) -> None:
        """Query with invalid filter format raises ConfigurationError."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "filters": {"contract_value": "invalid"},  # Should be dict
            },
        )

        with patch("redwood_dataagent.query_adapter._get_ibis_connection") as mock_get_conn:
            mock_table = MagicMock()
            mock_connection = MagicMock()
            mock_connection.table.return_value = mock_table
            mock_get_conn.return_value = mock_connection

            with pytest.raises(ConfigurationError, match="must be a dict"):
                _build_ibis_query(contract)


class TestExecuteQueryWithTimeout:
    """Tests for _execute_query_with_timeout()."""

    def test_execute_query_with_timeout_success(self) -> None:
        """Query execution succeeds and returns results."""
        mock_table = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        mock_table.limit.return_value.execute.return_value = mock_result

        with patch("redwood_dataagent.query_adapter.signal"):
            rows = _execute_query_with_timeout(mock_table, timeout_seconds=30, row_limit=100)

            assert len(rows) == 2
            assert rows[0]["id"] == 1

    def test_execute_query_with_timeout_sets_alarm(self) -> None:
        """Query execution sets timeout signal."""
        mock_table = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = []
        mock_table.limit.return_value.execute.return_value = mock_result

        with patch("redwood_dataagent.query_adapter.signal") as mock_signal:
            _execute_query_with_timeout(mock_table, timeout_seconds=30, row_limit=100)

            # Verify alarm was set and then cancelled
            assert mock_signal.alarm.call_count >= 2


class TestWriteQueryResultsToFile:
    """Tests for _write_query_results_to_file()."""

    def test_write_query_results_to_file_with_rows(self, tmp_path: Path) -> None:
        """Write rows to CSV file."""
        output_file = tmp_path / "results.csv"
        rows = [
            {"id": 1, "name": "Alice", "value": 100},
            {"id": 2, "name": "Bob", "value": 200},
        ]

        file_size = _write_query_results_to_file(rows, output_file)

        assert output_file.exists()
        assert file_size > 0
        assert file_size == output_file.stat().st_size

        # Verify CSV content
        with output_file.open("r") as f:
            reader = csv.DictReader(f)
            written_rows = list(reader)

        assert len(written_rows) == 2
        assert written_rows[0]["name"] == "Alice"

    def test_write_query_results_to_file_empty_rows(self, tmp_path: Path) -> None:
        """Write empty results to CSV file."""
        output_file = tmp_path / "results.csv"
        rows = []

        file_size = _write_query_results_to_file(rows, output_file)

        assert output_file.exists()
        assert file_size == 0

    def test_write_query_results_to_file_with_special_chars(self, tmp_path: Path) -> None:
        """Write results with special characters and unicode."""
        output_file = tmp_path / "results.csv"
        rows = [
            {"id": 1, "name": "José García", "description": 'Quote "test" value'},
        ]

        file_size = _write_query_results_to_file(rows, output_file)

        assert file_size > 0
        assert output_file.exists()


class TestUploadResultsToS3:
    """Tests for _upload_results_to_s3()."""

    def test_upload_results_to_s3_success(self, tmp_path: Path) -> None:
        """Upload CSV file to S3 staging bucket."""
        local_file = tmp_path / "results.csv"
        local_file.write_text("id,name\n1,Alice\n2,Bob\n")

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter.S3Client") as mock_s3_client_class:
            mock_client = MagicMock()
            mock_s3_client_class.return_value = mock_client

            s3_key = _upload_results_to_s3(
                local_file,
                config,
                "dot_contract_extract_v1",
                "test-session-001",
                "ce9b55325ce3708377997a21ae44be2b72e0de16aa5f7a9f4234e020f8a7ea07",
            )

            assert "query_mode/outgoing/test-session-001" in s3_key
            assert "dot_contract_extract_v1_ce9b55325ce3_results.csv" in s3_key
            mock_client.upload_file.assert_called_once()

    def test_upload_results_to_s3_failure_raises_storage_error(self, tmp_path: Path) -> None:
        """Upload failure raises StorageError."""
        local_file = tmp_path / "results.csv"
        local_file.write_text("data")

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter.S3Client") as mock_s3_client_class:
            mock_client = MagicMock()
            mock_client.upload_file.side_effect = Exception("Upload failed")
            mock_s3_client_class.return_value = mock_client

            with pytest.raises(StorageError, match="Failed to upload query results"):
                _upload_results_to_s3(
                    local_file,
                    config,
                    "dot_contract_extract_v1",
                    "test-session-001",
                    "ce9b55325ce3708377997a21ae44be2b72e0de16aa5f7a9f4234e020f8a7ea07",
                )


class TestExecuteQuery:
    """Tests for execute_query() end-to-end orchestration."""

    def test_execute_query_success(self, tmp_path: Path) -> None:
        """End-to-end successful query execution."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "select_fields": ["contract_id", "vendor_name"],
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
             patch("redwood_dataagent.query_adapter._execute_query_with_timeout") as mock_execute, \
             patch("redwood_dataagent.query_adapter._upload_results_to_s3") as mock_upload, \
               patch("redwood_dataagent.query_adapter._query_already_processed", return_value=False), \
               patch("redwood_dataagent.query_adapter._upload_query_processed_marker"), \
             patch("redwood_dataagent.query_adapter.signal"):

            mock_table = MagicMock()
            mock_build.return_value = (mock_table, 100)

            rows = [
                {"contract_id": "1", "vendor_name": "Acme Corp"},
                {"contract_id": "2", "vendor_name": "Beta Inc"},
            ]
            mock_execute.return_value = rows
            mock_upload.return_value = "query_mode/outgoing/test-session-001/dot_contract_extract_v1_ce9b55325ce3_results.csv"

            result = execute_query(contract, config)

            assert isinstance(result, QueryExecutionResult)
            assert result.row_count == 2
            assert result.file_size_bytes > 0
            assert result.execution_duration_seconds >= 0
            assert "s3://" in result.output_file_path

    def test_execute_query_skips_when_matching_marker_exists(self) -> None:
        """Matching query success marker causes query execution to be skipped."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "select_fields": ["contract_id", "vendor_name"],
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch.dict(
            "os.environ",
            {
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=False,
        ):
            with patch("redwood_dataagent.query_adapter.S3Client") as mock_s3_client_class:
                mock_client = MagicMock()
                mock_client.object_exists.return_value = True
                mock_s3_client_class.return_value = mock_client

                with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
                     patch("redwood_dataagent.query_adapter._execute_query_with_timeout") as mock_execute, \
                     patch("redwood_dataagent.query_adapter._upload_results_to_s3") as mock_upload:

                    result = execute_query(contract, config)

        assert result.skipped is True
        assert result.row_count == 0
        assert result.file_size_bytes == 0
        assert result.output_file_path == ""
        mock_build.assert_not_called()
        mock_execute.assert_not_called()
        mock_upload.assert_not_called()
        mock_client.object_exists.assert_called_once()

    def test_execute_query_writes_marker_after_success(self) -> None:
        """Successful query execution stages output and writes a success marker."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "select_fields": ["contract_id", "vendor_name"],
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch.dict(
            "os.environ",
            {
                "DB_ENGINE": "postgres",
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=False,
        ):
            with patch("redwood_dataagent.query_adapter.S3Client") as mock_s3_client_class:
                mock_client = MagicMock()
                mock_client.object_exists.return_value = False
                mock_s3_client_class.return_value = mock_client

                with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
                     patch("redwood_dataagent.query_adapter._execute_query_with_timeout") as mock_execute:

                    mock_table = MagicMock()
                    mock_build.return_value = (mock_table, 100)
                    mock_execute.return_value = [
                        {"contract_id": "1", "vendor_name": "Acme Corp"},
                    ]

                    result = execute_query(contract, config)

        assert result.skipped is False
        assert result.row_count == 1
        assert result.marker_key.startswith("query_mode/processed/dot_contract_extract_v1/")
        assert mock_client.object_exists.call_count == 1
        assert mock_client.upload_file.call_count == 2

    def test_execute_query_timeout_raises_storage_error(self) -> None:
        """Query timeout raises StorageError."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
            },
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
             patch("redwood_dataagent.query_adapter._execute_query_with_timeout") as mock_execute:

            mock_table = MagicMock()
            mock_build.return_value = (mock_table, 100)
            mock_execute.side_effect = StorageError("Query execution exceeded 60s timeout")

            with pytest.raises(StorageError, match="Query execution exceeded"):
                execute_query(contract, config)

    def test_execute_query_configuration_error_raises(self) -> None:
        """Invalid contract raises ConfigurationError."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={},  # Missing required schema/table
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build:
            mock_build.side_effect = ConfigurationError("Query contract must specify 'schema' and 'table'")

            with pytest.raises(ConfigurationError, match="must specify 'schema' and 'table'"):
                execute_query(contract, config)


class TestAuditEventEmission:
    """Tests for audit event emission during query execution lifecycle."""

    def test_execute_query_emits_extract_data_event_on_success(self, tmp_path: Path) -> None:
        """Successful query execution emits EXTRACT_DATA event with metadata."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
                "select_fields": ["contract_id", "vendor_name"],
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
             patch("redwood_dataagent.query_adapter._execute_query_with_timeout") as mock_execute, \
             patch("redwood_dataagent.query_adapter._upload_results_to_s3") as mock_upload, \
             patch("redwood_dataagent.query_adapter._query_already_processed", return_value=False), \
             patch("redwood_dataagent.query_adapter._upload_query_processed_marker"), \
             patch("redwood_dataagent.query_adapter.log_event") as mock_log_event, \
             patch("redwood_dataagent.query_adapter.signal"):

            mock_table = MagicMock()
            mock_build.return_value = (mock_table, 100)

            rows = [
                {"contract_id": "1", "vendor_name": "Acme Corp"},
                {"contract_id": "2", "vendor_name": "Beta Inc"},
            ]
            mock_execute.return_value = rows
            mock_upload.return_value = "query_mode/outgoing/test-session-001/dot_contract_extract_v1_ce9b55325ce3_results.csv"

            result = execute_query(contract, config)

            # Verify EXTRACT_DATA event was emitted with SUCCESS outcome
            mock_log_event.assert_called_once()
            call_args = mock_log_event.call_args
            
            assert call_args.kwargs["event_type"] == AuditEventType.EXTRACT_DATA
            assert call_args.kwargs["transfer_session_id"] == "test-session-001"
            assert call_args.kwargs["sender_agency"] == "dot"
            assert call_args.kwargs["receiver_agency"] == "gsa"
            assert call_args.kwargs["outcome"] == EventOutcome.SUCCESS
            
            # Verify metadata in details
            details = call_args.kwargs["details"]
            assert details["template_id"] == "dot_contract_extract_v1"
            assert details["row_count"] == 2
            assert details["file_size_bytes"] > 0
            assert details["duration_seconds"] >= 0
            assert "s3://" in details["output_file_path"]
            assert len(details["fingerprint"]) > 0

    def test_execute_query_emits_extract_data_event_on_failure(self) -> None:
        """Failed query execution emits EXTRACT_DATA event with error details."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "nonexistent_table",
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch("redwood_dataagent.query_adapter._build_ibis_query") as mock_build, \
             patch("redwood_dataagent.query_adapter._query_already_processed", return_value=False), \
             patch("redwood_dataagent.query_adapter.log_event") as mock_log_event:

            error_msg = "Table 'nonexistent_table' not found in schema 'dot'"
            mock_build.side_effect = ConfigurationError(error_msg)

            with pytest.raises(ConfigurationError):
                execute_query(contract, config)

            # Verify EXTRACT_DATA event was emitted with FAILURE outcome
            mock_log_event.assert_called_once()
            call_args = mock_log_event.call_args
            
            assert call_args.kwargs["event_type"] == AuditEventType.EXTRACT_DATA
            assert call_args.kwargs["outcome"] == EventOutcome.FAILURE
            
            # Verify error details
            details = call_args.kwargs["details"]
            assert details["error_type"] == "ConfigurationError"
            assert error_msg in details["error_message"]
            assert details["duration_seconds"] >= 0

    def test_execute_query_emits_extract_data_event_on_skip(self) -> None:
        """Skipped query execution (idempotency marker exists) emits EXTRACT_DATA event."""
        contract = SenderQueryInputContract(
            template_id="dot_contract_extract_v1",
            params={
                "schema": "dot",
                "table": "contract_data",
            },
            row_limit=100,
            timeout_seconds=60,
        )

        config = AgentConfig(
            agent_mode="sender",
            tenant="tts",
            environment="dev",
            aws_region="us-east-1",
            log_level="INFO",
            transfer_session_id="test-session-001",
            sender_agency="dot",
            receiver_agency="gsa",
            sender_staging_bucket="test-bucket",
            receiver_landing_bucket="",
            receiver_target_bucket="",
            sender_data_directory="s3://test-bucket/scans/",
            sftp_endpoints=["sftp.example.com"],
            sftp_username="test-secret",
        )

        with patch.dict(
            "os.environ",
            {
                "DB_HOST": "example-rds.us-east-1.rds.amazonaws.com",
                "DB_PORT": "5432",
                "DB_NAME": "sample_db",
                "DB_USERNAME": "sample_user",
                "DB_PASSWORD": "sample_password",
            },
            clear=False,
        ):
            with patch("redwood_dataagent.query_adapter.S3Client") as mock_s3_client_class, \
                 patch("redwood_dataagent.query_adapter.log_event") as mock_log_event:

                mock_client = MagicMock()
                mock_client.object_exists.return_value = True
                mock_s3_client_class.return_value = mock_client

                result = execute_query(contract, config)

                # Verify EXTRACT_DATA event was emitted with SUCCESS outcome (skipped)
                mock_log_event.assert_called_once()
                call_args = mock_log_event.call_args
                
                assert call_args.kwargs["event_type"] == AuditEventType.EXTRACT_DATA
                assert call_args.kwargs["outcome"] == EventOutcome.SUCCESS
                
                # Verify skip details
                details = call_args.kwargs["details"]
                assert details["execution_status"] == "skipped"
                assert details["reason"] == "matching_success_marker_exists"
                assert result.skipped is True
