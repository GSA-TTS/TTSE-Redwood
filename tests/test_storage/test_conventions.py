"""Tests for storage naming conventions and path builders."""

import pytest

from redwood_dataagent.storage import (
    ReceiverStoragePath,
    SenderStoragePath,
    StoragePurpose,
    build_receiver_bucket,
    build_sender_bucket,
)


class TestStoragePurpose:
    """Test StoragePurpose enum."""

    def test_staging_value(self):
        """Verify STAGING purpose value."""
        assert StoragePurpose.STAGING.value == "staging"

    def test_landing_value(self):
        """Verify LANDING purpose value."""
        assert StoragePurpose.LANDING.value == "landing"

    def test_target_value(self):
        """Verify TARGET purpose value."""
        assert StoragePurpose.TARGET.value == "target"

    def test_enum_membership(self):
        """Verify all expected purposes are defined."""
        purposes = {purpose.value for purpose in StoragePurpose}
        assert purposes == {"staging", "landing", "target"}


class TestBuildSenderBucket:
    """Test sender bucket name builder."""

    def test_basic_bucket_name(self):
        """Verify basic sender bucket naming."""
        bucket = build_sender_bucket("dot", "dev", StoragePurpose.STAGING)
        assert bucket == "dot-data-dev-staging"

    def test_case_insensitive_agency(self):
        """Verify agency name is lowercased."""
        bucket = build_sender_bucket("DOT", "dev", StoragePurpose.STAGING)
        assert bucket == "dot-data-dev-staging"

    def test_case_insensitive_environment(self):
        """Verify environment is lowercased."""
        bucket = build_sender_bucket("dot", "PROD", StoragePurpose.STAGING)
        assert bucket == "dot-data-prod-staging"

    def test_all_purposes(self):
        """Verify bucket name for all storage purposes."""
        for purpose in StoragePurpose:
            bucket = build_sender_bucket("faa", "staging", purpose)
            assert bucket == f"faa-data-staging-{purpose.value}"

    def test_blank_agency_raises(self):
        """Verify blank agency raises ValueError."""
        with pytest.raises(ValueError, match="agency cannot be blank"):
            build_sender_bucket("", "dev", StoragePurpose.STAGING)

    def test_whitespace_agency_raises(self):
        """Verify whitespace-only agency raises ValueError."""
        with pytest.raises(ValueError, match="agency cannot be blank"):
            build_sender_bucket("   ", "dev", StoragePurpose.STAGING)

    def test_blank_environment_raises(self):
        """Verify blank environment raises ValueError."""
        with pytest.raises(ValueError, match="environment cannot be blank"):
            build_sender_bucket("dot", "", StoragePurpose.STAGING)

    def test_whitespace_environment_raises(self):
        """Verify whitespace-only environment raises ValueError."""
        with pytest.raises(ValueError, match="environment cannot be blank"):
            build_sender_bucket("dot", "   ", StoragePurpose.STAGING)


class TestBuildReceiverBucket:
    """Test receiver bucket name builder."""

    def test_landing_bucket_name(self):
        """Verify receiver landing bucket naming."""
        bucket = build_receiver_bucket("gsa", "dev", "landing")
        assert bucket == "gsa-data-dev-landing"

    def test_target_bucket_name(self):
        """Verify receiver target bucket naming."""
        bucket = build_receiver_bucket("gsa", "prod", "target")
        assert bucket == "gsa-data-prod-target"

    def test_case_insensitive_agency(self):
        """Verify agency name is lowercased."""
        bucket = build_receiver_bucket("GSA", "dev", "landing")
        assert bucket == "gsa-data-dev-landing"

    def test_case_insensitive_environment(self):
        """Verify environment is lowercased."""
        bucket = build_receiver_bucket("gsa", "STAGING", "landing")
        assert bucket == "gsa-data-staging-landing"

    def test_case_insensitive_purpose(self):
        """Verify purpose is lowercased."""
        bucket = build_receiver_bucket("gsa", "dev", "LANDING")
        assert bucket == "gsa-data-dev-landing"

    def test_blank_agency_raises(self):
        """Verify blank agency raises ValueError."""
        with pytest.raises(ValueError, match="agency cannot be blank"):
            build_receiver_bucket("", "dev", "landing")

    def test_whitespace_agency_raises(self):
        """Verify whitespace-only agency raises ValueError."""
        with pytest.raises(ValueError, match="agency cannot be blank"):
            build_receiver_bucket("   ", "dev", "landing")

    def test_blank_environment_raises(self):
        """Verify blank environment raises ValueError."""
        with pytest.raises(ValueError, match="environment cannot be blank"):
            build_receiver_bucket("gsa", "", "landing")

    def test_whitespace_environment_raises(self):
        """Verify whitespace-only environment raises ValueError."""
        with pytest.raises(ValueError, match="environment cannot be blank"):
            build_receiver_bucket("gsa", "   ", "landing")

    def test_invalid_purpose_raises(self):
        """Verify invalid purpose raises ValueError."""
        with pytest.raises(ValueError, match='purpose must be either "landing" or "target"'):
            build_receiver_bucket("gsa", "dev", "staging")

    def test_blank_purpose_raises(self):
        """Verify blank purpose raises ValueError."""
        with pytest.raises(ValueError, match='purpose must be either "landing" or "target"'):
            build_receiver_bucket("gsa", "dev", "")


class TestSenderStoragePath:
    """Test sender-side path builders."""

    def test_transfers_path(self):
        """Verify transfers path format."""
        path = SenderStoragePath.transfers("transfer-001", "data.tar.gz")
        assert path == "transfers/transfer-001/data.tar.gz"

    def test_transfers_with_different_filenames(self):
        """Verify transfers path with various file names."""
        test_cases = [
            ("transfer-001", "data.tar.gz"),
            ("transfer-20260324-001", "payload.zip"),
            ("session-abc-123", "manifest.json"),
        ]
        for session_id, filename in test_cases:
            path = SenderStoragePath.transfers(session_id, filename)
            assert path == f"transfers/{session_id}/{filename}"

    def test_blank_transfer_session_id_raises(self):
        """Verify blank transfer_session_id raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            SenderStoragePath.transfers("", "data.tar.gz")

    def test_whitespace_transfer_session_id_raises(self):
        """Verify whitespace-only transfer_session_id raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            SenderStoragePath.transfers("   ", "data.tar.gz")

    def test_blank_file_name_raises(self):
        """Verify blank file_name raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            SenderStoragePath.transfers("transfer-001", "")

    def test_whitespace_file_name_raises(self):
        """Verify whitespace-only file_name raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            SenderStoragePath.transfers("transfer-001", "   ")


class TestReceiverStoragePath:
    """Test receiver-side path builders."""

    def test_landing_path(self):
        """Verify landing zone path format."""
        path = ReceiverStoragePath.landing("transfer-001", "data.tar.gz")
        assert path == "landing/transfer-001/data.tar.gz"

    def test_extracted_path(self):
        """Verify extracted data path format."""
        path = ReceiverStoragePath.extracted("transfer-001", "records.csv")
        assert path == "extracted/transfer-001/records.csv"

    def test_landing_with_different_filenames(self):
        """Verify landing path with various file names."""
        test_cases = [
            ("transfer-001", "data.tar.gz"),
            ("transfer-20260324-001", "payload.zip"),
            ("session-abc-123", "manifest.json"),
        ]
        for session_id, filename in test_cases:
            path = ReceiverStoragePath.landing(session_id, filename)
            assert path == f"landing/{session_id}/{filename}"

    def test_extracted_with_different_filenames(self):
        """Verify extracted path with various file names."""
        test_cases = [
            ("transfer-001", "records.csv"),
            ("transfer-20260324-001", "data.parquet"),
            ("session-abc-123", "output.json"),
        ]
        for session_id, filename in test_cases:
            path = ReceiverStoragePath.extracted(session_id, filename)
            assert path == f"extracted/{session_id}/{filename}"

    def test_landing_blank_transfer_session_id_raises(self):
        """Verify blank transfer_session_id in landing raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.landing("", "data.tar.gz")

    def test_landing_whitespace_transfer_session_id_raises(self):
        """Verify whitespace transfer_session_id in landing raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.landing("   ", "data.tar.gz")

    def test_landing_blank_file_name_raises(self):
        """Verify blank file_name in landing raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.landing("transfer-001", "")

    def test_landing_whitespace_file_name_raises(self):
        """Verify whitespace file_name in landing raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.landing("transfer-001", "   ")

    def test_extracted_blank_transfer_session_id_raises(self):
        """Verify blank transfer_session_id in extracted raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.extracted("", "records.csv")

    def test_extracted_whitespace_transfer_session_id_raises(self):
        """Verify whitespace transfer_session_id in extracted raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.extracted("   ", "records.csv")

    def test_extracted_blank_file_name_raises(self):
        """Verify blank file_name in extracted raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.extracted("transfer-001", "")

    def test_extracted_whitespace_file_name_raises(self):
        """Verify whitespace file_name in extracted raises ValueError."""
        with pytest.raises(ValueError, match="path component cannot be blank"):
            ReceiverStoragePath.extracted("transfer-001", "   ")


class TestStorageConventionsIntegration:
    """Integration tests for complete storage naming workflows."""

    def test_full_sender_workflow(self):
        """Verify complete sender-side transfer workflow."""
        agency = "dot"
        env = "dev"
        bucket = build_sender_bucket(agency, env, StoragePurpose.STAGING)
        assert bucket == "dot-data-dev-staging"

        session_id = "transfer-20260324-001"
        data_path = SenderStoragePath.transfers(session_id, "data.tar.gz")
        manifest_path = SenderStoragePath.transfers(session_id, "manifest.json")

        assert data_path == "transfers/transfer-20260324-001/data.tar.gz"
        assert manifest_path == "transfers/transfer-20260324-001/manifest.json"

    def test_full_receiver_workflow(self):
        """Verify complete receiver-side transfer workflow."""
        agency = "gsa"
        env = "dev"
        landing_bucket = build_receiver_bucket(agency, env, "landing")
        target_bucket = build_receiver_bucket(agency, env, "target")

        assert landing_bucket == "gsa-data-dev-landing"
        assert target_bucket == "gsa-data-dev-target"

        session_id = "transfer-20260324-001"
        inbound_path = ReceiverStoragePath.landing(session_id, "data.tar.gz")
        extracted_path = ReceiverStoragePath.extracted(session_id, "records.csv")

        assert inbound_path == "landing/transfer-20260324-001/data.tar.gz"
        assert extracted_path == "extracted/transfer-20260324-001/records.csv"

    def test_multi_agency_isolation(self):
        """Verify bucket names isolate data between agencies."""
        # Different agencies produce different buckets
        dot_bucket = build_sender_bucket("dot", "dev", StoragePurpose.STAGING)
        faa_bucket = build_sender_bucket("faa", "dev", StoragePurpose.STAGING)

        assert dot_bucket == "dot-data-dev-staging"
        assert faa_bucket == "faa-data-dev-staging"
        assert dot_bucket != faa_bucket

    def test_multi_environment_isolation(self):
        """Verify bucket names isolate data between environments."""
        dev_bucket = build_sender_bucket("dot", "dev", StoragePurpose.STAGING)
        prod_bucket = build_sender_bucket("dot", "prod", StoragePurpose.STAGING)

        assert dev_bucket == "dot-data-dev-staging"
        assert prod_bucket == "dot-data-prod-staging"
        assert dev_bucket != prod_bucket

    def test_multi_purpose_isolation(self):
        """Verify bucket names isolate data by purpose."""
        staging_bucket = build_sender_bucket("dot", "dev", StoragePurpose.STAGING)

        # Receiver side - compare with landing and target
        landing_bucket = build_receiver_bucket("gsa", "dev", "landing")
        target_bucket = build_receiver_bucket("gsa", "dev", "target")

        assert landing_bucket == "gsa-data-dev-landing"
        assert target_bucket == "gsa-data-dev-target"
        assert landing_bucket != target_bucket
