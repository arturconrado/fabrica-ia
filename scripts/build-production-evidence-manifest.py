#!/usr/bin/env python3
"""Inventory real production-readiness evidence without fabricating results."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


EVIDENCE_FILES = (
    ("playwright.json", True, True),
    ("backup-restore/backup-restore.json", True, True),
    ("backup-restore/restore-log.txt", True, True),
    ("load/portfolio-v2-baseline-2.json", True, True),
    ("load/portfolio-v2-load-20.json", True, True),
    ("load/portfolio-v2-load-50.json", True, True),
    ("load/portfolio-v2-stress-200.json", False, True),
    ("load/portfolio-v2-spike-500.json", False, True),
    ("load/portfolio-v2-soak-20.json", True, True),
    ("agentic-journey-evaluation.json", True, True),
    ("commercial-ai-case-evaluation.json", True, True),
    ("workflow-candidate-evaluation.json", True, True),
    ("credential-rotation.json", True, True),
    ("production-readiness-gate.json", False, True),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def commit_sha(repo_root: Path) -> str:
    configured = os.getenv("ASF_RELEASE_COMMIT_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_manifest(root: Path, repo_root: Path) -> dict:
    verification_id = os.getenv("ASF_PRODUCTION_E2E_RUN_ID", "").strip()
    release_tenant_id = os.getenv("ASF_RELEASE_TENANT_ID", "").strip()
    operator = os.getenv("ASF_RELEASE_OPERATOR", "").strip()
    rows = []
    for relative, required_for_pilot, required_for_production_scale in EVIDENCE_FILES:
        path = root / relative
        exists = path.is_file()
        rows.append({
            "path": relative,
            "exists": exists,
            "sha256": sha256(path) if exists else None,
            "size_bytes": path.stat().st_size if exists else None,
            "required_for_pilot": required_for_pilot,
            "required_for_production_scale": required_for_production_scale,
        })
    return {
        "schema_version": "production-evidence-manifest/1.0",
        "verification_id": verification_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha(repo_root),
        "runtime_profile": os.getenv("ASF_EVIDENCE_RUNTIME_PROFILE", "homologation"),
        "agent_provider": os.getenv("ASF_AGENT_PROVIDER", ""),
        "workflow_backend": os.getenv("ASF_WORKFLOW_BACKEND", ""),
        "release_tenant_id": release_tenant_id,
        "operator": operator,
        "credential_source": "secret_or_environment",
        "credentials_persisted": False,
        "evidence_files": rows,
        "missing_for_pilot": [
            row["path"] for row in rows if row["required_for_pilot"] and not row["exists"]
        ],
        "missing_for_production_scale": [
            row["path"]
            for row in rows
            if row["required_for_production_scale"] and not row["exists"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    payload = build_manifest(root, args.repo_root.resolve())
    destination = root / "manifest.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "manifest": str(destination),
        "missing_for_pilot": payload["missing_for_pilot"],
        "missing_for_production_scale": payload["missing_for_production_scale"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
