import re
import time
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.sandbox.executor import SandboxExecutor


def _counts(stdout: str) -> Tuple[int, int]:
    failed = 0
    passed = 0
    match = re.search(r"(\d+) failed", stdout)
    if match:
        failed = int(match.group(1))
    match = re.search(r"(\d+) passed", stdout)
    if match:
        passed = int(match.group(1))
    return passed, failed


def run_generated_tests(
    workspace: Path,
    timeout: Optional[int] = None,
    *,
    db: Optional[Session] = None,
    tenant_id: str = "local-dev",
    run_id: str = "",
) -> dict:
    start = time.time()
    command = "python -m pytest generated_app/tests"
    result = SandboxExecutor().run(
        command=command,
        workspace=workspace,
        timeout=timeout or get_settings().sandbox_timeout_seconds,
        db=db,
        tenant_id=tenant_id,
        run_id=run_id,
    )
    timed_out = bool(result["timed_out"])
    stdout = str(result["stdout"])
    stderr = str(result["stderr"])
    status = str(result["status"])
    passed, failed = _counts(stdout)
    return {
        "command": command,
        "status": status,
        "passed_count": passed,
        "failed_count": failed,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - start, 3),
        "sandbox_execution_id": str(result["sandbox_execution_id"]),
    }
