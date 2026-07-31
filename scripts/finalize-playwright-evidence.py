#!/usr/bin/env python3
"""Add release metadata to Playwright JSON without changing its test result."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _commit_sha(repo_root: Path) -> str:
    configured = os.getenv("ASF_RELEASE_COMMIT_SHA", "").strip()
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _collect_failures(value: Any, failures: list[str]) -> None:
    if isinstance(value, dict):
        for result in value.get("tests") or []:
            for attempt in result.get("results") or []:
                error = attempt.get("error") or {}
                message = str(error.get("message") or "").strip()
                if message:
                    failures.append(message[:500])
        for child in value.get("suites") or []:
            _collect_failures(child, failures)


def finalize(report_path: Path, repo_root: Path, exit_code: int) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("Playwright JSON root must be an object")
    stats = report.get("stats") or {}
    failures: list[str] = []
    _collect_failures(report, failures)
    clean = (
        exit_code == 0
        and int(stats.get("unexpected") or 0) == 0
        and int(stats.get("skipped") or 0) == 0
        and int(stats.get("flaky") or 0) == 0
    )
    duration_ms = float(stats.get("duration") or 0)
    report.update({
        "schema_version": "playwright-release-evidence/1.0",
        "status": "passed" if clean else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": _commit_sha(repo_root),
        "environment": "homologation",
        "tenant_id": os.getenv("ASF_RELEASE_TENANT_ID", "").strip(),
        "command": "npm run test:e2e:release",
        "duration_seconds": round(duration_ms / 1000.0, 3),
        "critical_failures": int(stats.get("unexpected") or 0),
        "summary": {
            "expected": int(stats.get("expected") or 0),
            "skipped": int(stats.get("skipped") or 0),
            "unexpected": int(stats.get("unexpected") or 0),
            "flaky": int(stats.get("flaky") or 0),
        },
        "failures": failures,
        "artifacts": [],
    })
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    report = finalize(args.report, args.repo_root, args.exit_code)
    print(json.dumps({
        "status": report["status"],
        "critical_failures": report["critical_failures"],
        "report": str(args.report),
    }, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
