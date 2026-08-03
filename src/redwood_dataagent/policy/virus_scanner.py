"""ClamAV-based virus scanner for receiver-side file validation.

MVP approach: invoke local ``clamscan`` CLI via subprocess for each file.
Fail closed — scanner errors are treated as hard failures, not skipped.

Phase 1 design (CLI-per-file) is intentional; upgrade path is:
  1. local clamd daemon  (reduce per-scan overhead)
  2. sidecar / shared scanner service (separate image lifecycle)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ScanStatus(str, Enum):
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


@dataclass(frozen=True)
class ScanResult:
    """Result of a single file virus scan."""

    path: Path
    status: ScanStatus
    detail: str = ""


def scan_file(path: Path) -> ScanResult:
    """Scan a single file with the local ``clamscan`` binary.

    Parameters
    ----------
    path:
        Absolute path to the file to scan.

    Returns
    -------
    ScanResult
        - status=CLEAN  when clamscan exits 0 (no infection)
        - status=INFECTED when clamscan exits 1 (infection found)
        - status=ERROR  when clamscan exits 2 or is not found

    Notes
    -----
    ``clamscan`` exit codes:
        0  Clean
        1  Virus found
        2  Error (missing database, unreadable file, etc.)
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["clamscan", "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return ScanResult(path=path, status=ScanStatus.ERROR, detail="clamscan binary not found")
    except subprocess.TimeoutExpired:
        return ScanResult(path=path, status=ScanStatus.ERROR, detail="clamscan timed out")
    except Exception as exc:  # noqa: BLE001
        return ScanResult(path=path, status=ScanStatus.ERROR, detail=f"clamscan execution error: {exc}")

    if result.returncode == 0:
        return ScanResult(path=path, status=ScanStatus.CLEAN)

    if result.returncode == 1:
        detail = result.stdout.strip() or "infection detected"
        return ScanResult(path=path, status=ScanStatus.INFECTED, detail=detail)

    detail = result.stderr.strip() or result.stdout.strip() or f"clamscan exited with code {result.returncode}"
    return ScanResult(path=path, status=ScanStatus.ERROR, detail=detail)
