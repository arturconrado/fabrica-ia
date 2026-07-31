"""Shared metadata for evidence produced by deterministic release evaluators."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit_sha(repo_root: Path) -> str:
    configured = os.getenv("ASF_RELEASE_COMMIT_SHA", "").strip()
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def enrich_release_report(
    report: dict[str, Any],
    *,
    repo_root: Path,
    command: str,
    started_monotonic: float,
    artifact_paths: Iterable[Path],
) -> dict[str, Any]:
    artifacts = []
    for path in artifact_paths:
        resolved = path.resolve()
        if resolved.is_file():
            artifacts.append({
                "path": str(resolved),
                "sha256": _sha256(resolved),
                "size_bytes": resolved.stat().st_size,
            })
    blockers = [str(item) for item in report.get("blockers") or []]
    report.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _commit_sha(repo_root),
        "environment": "homologation",
        "tenant_id": os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        "command": command,
        "duration_seconds": round(max(0.0, time.monotonic() - started_monotonic), 6),
        "summary": {
            "passed": report.get("passed") is True,
            "blocker_count": len(blockers),
        },
        "failures": blockers,
        "artifacts": artifacts,
    })
    return report
