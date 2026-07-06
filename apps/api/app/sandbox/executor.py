import time
import uuid
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import safe_join
from app.models import SandboxExecution


class SandboxCommandRejected(PermissionError):
    pass


class SandboxExecutor:
    def run(
        self,
        *,
        command: str,
        workspace: Path,
        tenant_id: str,
        run_id: str,
        db: Optional[Session] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, object]:
        settings = get_settings()
        if command not in settings.allowed_sandbox_commands:
            raise SandboxCommandRejected(f"Command is not allowlisted: {command}")
        safe_join(workspace, "generated_app/tests")
        backend = settings.sandbox_backend.lower()
        if backend != "kubernetes":
            raise SandboxCommandRejected("Production-only sandbox requires ASF_SANDBOX_BACKEND=kubernetes")
        try:
            result = self._run_kubernetes_job(command, workspace, timeout or settings.sandbox_timeout_seconds, run_id)
        except Exception as exc:
            result = {
                "status": "failed",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(exc),
                "timed_out": False,
                "duration_seconds": 0.0,
                "evidence": {"backend": "kubernetes", "error": str(exc), "workspace_ref": str(workspace)},
            }
        execution_id = str(uuid.uuid4())
        if db is not None:
            db.add(
                SandboxExecution(
                    id=execution_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    backend=backend,
                    workspace_ref=str(workspace),
                    command=command,
                    status=str(result["status"]),
                    exit_code=int(result["exit_code"]),
                    stdout=str(result["stdout"])[:20000],
                    stderr=str(result["stderr"])[:20000],
                    timed_out=bool(result["timed_out"]),
                    limits_json={
                        "timeout_seconds": timeout or settings.sandbox_timeout_seconds,
                        "cpu": settings.sandbox_cpu_limit,
                        "memory": settings.sandbox_memory_limit,
                        "network": "deny-by-default for kubernetes backend",
                    },
                    evidence_json=result.get("evidence", {}),
                    duration_seconds=float(result["duration_seconds"]),
                )
            )
            db.flush()
        result["sandbox_execution_id"] = execution_id
        return result

    def _run_kubernetes_job(self, command: str, workspace: Path, timeout: int, run_id: str) -> Dict[str, object]:
        settings = get_settings()
        if not settings.sandbox_workspace_pvc:
            raise RuntimeError("ASF_SANDBOX_WORKSPACE_PVC is required so Kubernetes Jobs can mount generated workspaces")
        start = time.time()
        try:
            from kubernetes import client, config, watch
        except Exception as exc:  # pragma: no cover - optional production dependency
            raise RuntimeError(f"kubernetes client is not installed: {exc}") from exc
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config(config_file=settings.sandbox_kubeconfig or None)
        batch = client.BatchV1Api()
        core = client.CoreV1Api()
        job_name = f"asf-sandbox-{uuid.uuid4().hex[:12]}"
        container = client.V1Container(
            name="runner",
            image=settings.sandbox_image,
            command=["/bin/sh", "-lc", command],
            working_dir=settings.sandbox_workspace_mount_path,
            env=[
                client.V1EnvVar(name="HOME", value="/tmp"),
                client.V1EnvVar(name="PYTHONDONTWRITEBYTECODE", value="1"),
                client.V1EnvVar(name="PYTEST_ADDOPTS", value="-p no:cacheprovider"),
            ],
            security_context=client.V1SecurityContext(
                run_as_non_root=True,
                run_as_user=10001,
                allow_privilege_escalation=False,
                read_only_root_filesystem=True,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
            resources=client.V1ResourceRequirements(
                limits={"cpu": settings.sandbox_cpu_limit, "memory": settings.sandbox_memory_limit},
                requests={"cpu": "250m", "memory": "256Mi"},
            ),
            volume_mounts=[
                client.V1VolumeMount(
                    name="workspace",
                    mount_path=settings.sandbox_workspace_mount_path,
                    read_only=True,
                    sub_path=run_id,
                ),
                client.V1VolumeMount(name="tmp", mount_path="/tmp", read_only=False),
            ],
        )
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            runtime_class_name=settings.sandbox_runtime_class or None,
            automount_service_account_token=False,
            containers=[container],
            volumes=[
                client.V1Volume(
                    name="workspace",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=settings.sandbox_workspace_pvc),
                ),
                client.V1Volume(name="tmp", empty_dir=client.V1EmptyDirVolumeSource()),
            ],
        )
        job = client.V1Job(
            metadata=client.V1ObjectMeta(name=job_name, labels={"app": "software-factory-sandbox"}),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=300,
                active_deadline_seconds=timeout,
                backoff_limit=0,
                template=client.V1PodTemplateSpec(spec=pod_spec),
            ),
        )
        batch.create_namespaced_job(settings.sandbox_namespace, job)
        watcher = watch.Watch()
        status = "failed"
        timed_out = True
        for event in watcher.stream(
            batch.list_namespaced_job,
            namespace=settings.sandbox_namespace,
            field_selector=f"metadata.name={job_name}",
            timeout_seconds=timeout,
        ):
            obj = event["object"]
            if obj.status.succeeded:
                status = "passed"
                timed_out = False
                watcher.stop()
            if obj.status.failed:
                timed_out = False
                watcher.stop()
        pods = core.list_namespaced_pod(settings.sandbox_namespace, label_selector=f"job-name={job_name}").items
        stdout = ""
        if pods:
            stdout = core.read_namespaced_pod_log(pods[0].metadata.name, settings.sandbox_namespace)
        return {
            "status": status,
            "exit_code": 0 if status == "passed" else 1,
            "stdout": stdout,
            "stderr": "",
            "timed_out": timed_out,
            "duration_seconds": round(time.time() - start, 3),
            "evidence": {
                "backend": "kubernetes",
                "job_name": job_name,
                "runtime_class": settings.sandbox_runtime_class,
                "workspace_ref": str(workspace),
                "workspace_pvc": settings.sandbox_workspace_pvc,
                "workspace_sub_path": run_id,
            },
        }
