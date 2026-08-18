"""Unit tests for the ClamAV virus scanner module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from redwood_dataagent.policy.virus_scanner import ScanResult, ScanStatus, scan_file


class TestScanFile:
    """Tests for scan_file()."""

    def _make_completed_process(self, returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=["clamscan", "--no-summary", "/tmp/test.json"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def test_clean_file_returns_clean_status(self, tmp_path: Path) -> None:
        """clamscan exit 0 → ScanResult.CLEAN."""
        test_file = tmp_path / "data.json"
        test_file.write_text('{"id": 1}')

        with patch("subprocess.run", return_value=self._make_completed_process(0)):
            result = scan_file(test_file)

        assert result.status == ScanStatus.CLEAN
        assert result.path == test_file
        assert result.detail == ""

    def test_infected_file_returns_infected_status(self, tmp_path: Path) -> None:
        """clamscan exit 1 → ScanResult.INFECTED with signature detail."""
        test_file = tmp_path / "malware.bin"
        test_file.write_bytes(b"EICAR-test")

        stdout = "/tmp/malware.bin: Eicar-Signature FOUND"
        with patch("subprocess.run", return_value=self._make_completed_process(1, stdout=stdout)):
            result = scan_file(test_file)

        assert result.status == ScanStatus.INFECTED
        assert result.path == test_file
        assert "Eicar-Signature" in result.detail

    def test_infected_file_with_empty_stdout_uses_fallback_detail(self, tmp_path: Path) -> None:
        """clamscan exit 1 with no output still returns INFECTED with fallback detail."""
        test_file = tmp_path / "malware.bin"
        test_file.write_bytes(b"x")

        with patch("subprocess.run", return_value=self._make_completed_process(1, stdout="")):
            result = scan_file(test_file)

        assert result.status == ScanStatus.INFECTED
        assert result.detail == "infection detected"

    def test_scanner_error_exit_code_returns_error_status(self, tmp_path: Path) -> None:
        """clamscan exit 2 → ScanResult.ERROR."""
        test_file = tmp_path / "data.json"
        test_file.write_text("{}")

        stderr = "ERROR: Can't open/read the log file."
        with patch("subprocess.run", return_value=self._make_completed_process(2, stderr=stderr)):
            result = scan_file(test_file)

        assert result.status == ScanStatus.ERROR
        assert "Can't open/read the log file" in result.detail

    def test_clamscan_not_found_returns_error_status(self, tmp_path: Path) -> None:
        """FileNotFoundError when clamscan binary is absent → ScanResult.ERROR."""
        test_file = tmp_path / "data.json"
        test_file.write_text("{}")

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = scan_file(test_file)

        assert result.status == ScanStatus.ERROR
        assert "not found" in result.detail

    def test_clamscan_timeout_returns_error_status(self, tmp_path: Path) -> None:
        """TimeoutExpired → ScanResult.ERROR."""
        test_file = tmp_path / "data.json"
        test_file.write_text("{}")

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="clamscan", timeout=120)):
            result = scan_file(test_file)

        assert result.status == ScanStatus.ERROR
        assert "timed out" in result.detail

    def test_scan_result_is_frozen(self, tmp_path: Path) -> None:
        """ScanResult is immutable (frozen dataclass)."""
        from dataclasses import FrozenInstanceError

        result = ScanResult(path=tmp_path / "f.json", status=ScanStatus.CLEAN)
        with pytest.raises(FrozenInstanceError):
            result.status = ScanStatus.INFECTED  # type: ignore[misc]

    def test_subprocess_called_with_correct_args(self, tmp_path: Path) -> None:
        """clamscan is invoked with --no-summary and the correct file path."""
        test_file = tmp_path / "data.json"
        test_file.write_text("{}")

        with patch("subprocess.run", return_value=self._make_completed_process(0)) as mock_run:
            scan_file(test_file)

        mock_run.assert_called_once_with(
            ["clamscan", "--no-summary", str(test_file)],
            capture_output=True,
            text=True,
            timeout=120,
        )
