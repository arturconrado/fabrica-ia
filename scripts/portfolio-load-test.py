#!/usr/bin/env python3
"""Repeatable, dependency-free load profiles for portfolio v2 homologation.

The read mix mirrors owner and VP decision traffic. A single idempotent command
probe runs before each profile; provider traffic is deliberately excluded.
Reports are evidence candidates and never create a human approval.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import http.client
import json
import math
import os
import re
import socket
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def release_commit_sha() -> str:
    configured = os.getenv("ASF_RELEASE_COMMIT_SHA", "").strip()
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
        text=True, stderr=subprocess.DEVNULL,
    ).strip()


PROFILES = {
    "baseline-2": (2, 60),
    "load-20": (20, 120),
    "load-50": (50, 120),
    "stress-200": (200, 120),
    "spike-500": (500, 30),
    "soak-20": (20, 8 * 60 * 60),
}
PROFILE_RAMP_SECONDS = {
    "baseline-2": 2,
    "load-20": 10,
    "load-50": 20,
    "stress-200": 30,
    # The profile means 500 arrivals inside its 30-second window, not 500
    # sockets opened in one scheduler tick. run_profile reserves the final 20%
    # at full concurrency through its duration*0.8 clamp.
    "spike-500": 30,
    "soak-20": 30,
}
PROFILE_THINK_SECONDS = {
    "baseline-2": 1.0,
    "load-20": 2.0,
    "load-50": 3.0,
    "stress-200": 5.0,
    "spike-500": 5.0,
    "soak-20": 5.0,
}
PERSONA_PATHS = {
    "owner": (
        "/api/v1/service-catalog/offerings",
        "/api/v1/operator/capacity",
        "/api/v1/operator/work-queue",
        "/api/v1/engagements",
        "/api/v1/client-operations/overview",
    ),
    "vp": (
        "/api/v1/review/inbox",
        "/api/v1/service-deliverables",
        "/api/v1/engagements",
        "/api/v1/service-catalog/offerings",
    ),
}


@dataclass(frozen=True)
class Sample:
    path: str
    status: int
    duration_ms: float
    timed_out: bool
    error: str = ""
    persona: str = ""
    transport_retries: int = 0


class PersistentHTTPClient:
    """One HTTP/1.1 connection per virtual user, matching browser/BFF reuse."""

    _RECONNECTABLE_ERRORS = (
        http.client.CannotSendRequest,
        http.client.RemoteDisconnected,
        BrokenPipeError,
        ConnectionResetError,
    )

    def __init__(self, base_url: str, timeout: float) -> None:
        parsed = urllib.parse.urlparse(base_url)
        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        self._connection_type = connection_type
        self._host = parsed.hostname or ""
        self._port = parsed.port
        self._timeout = timeout
        self._base_path = parsed.path.rstrip("/")
        self._connection = self._new_connection()

    def _new_connection(self) -> http.client.HTTPConnection:
        return self._connection_type(self._host, self._port, timeout=self._timeout)

    def _reconnect(self) -> None:
        self._connection.close()
        self._connection = self._new_connection()

    def close(self) -> None:
        self._connection.close()

    def get(self, path: str, headers: dict[str, str], *, persona: str = "") -> Sample:
        started = time.perf_counter()
        target = f"{self._base_path}{path}" or "/"
        retries = 0
        for attempt in range(2):
            try:
                self._connection.request("GET", target, headers=headers)
                response = self._connection.getresponse()
                response.read()
                duration_ms = (time.perf_counter() - started) * 1000
                error = "" if 200 <= response.status < 300 else f"HTTP {response.status} {response.reason}"
                return Sample(
                    path,
                    response.status,
                    duration_ms,
                    False,
                    error,
                    persona,
                    retries,
                )
            except self._RECONNECTABLE_ERRORS as exc:
                if attempt == 0:
                    retries += 1
                    self._reconnect()
                    continue
                return Sample(
                    path,
                    0,
                    (time.perf_counter() - started) * 1000,
                    False,
                    str(exc),
                    persona,
                    retries,
                )
            except (TimeoutError, socket.timeout) as exc:
                self._reconnect()
                return Sample(
                    path,
                    0,
                    (time.perf_counter() - started) * 1000,
                    True,
                    str(exc),
                    persona,
                    retries,
                )
            except (http.client.HTTPException, OSError) as exc:
                self._reconnect()
                return Sample(
                    path,
                    0,
                    (time.perf_counter() - started) * 1000,
                    False,
                    str(exc),
                    persona,
                    retries,
                )
        raise AssertionError("unreachable")


class TokenProvider:
    """Thread-safe bearer provider with optional OIDC renewal."""

    def __init__(self, *, persona: str, tenant_id: str, bearer_token: str) -> None:
        prefix = f"ASF_LOAD_{persona.upper()}"
        self.persona = persona
        self.tenant_id = tenant_id
        self.token = bearer_token
        self.token_url = os.getenv("ASF_LOAD_OIDC_TOKEN_URL", "").strip()
        self.client_id = os.getenv(f"{prefix}_CLIENT_ID", "").strip()
        self.client_secret = os.getenv(f"{prefix}_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv(f"{prefix}_REFRESH_TOKEN", "").strip()
        self.expires_at = self._jwt_expiry(self.token)
        self.refreshes = 0
        self._lock = threading.Lock()
        if not self.token:
            self._renew()

    @property
    def renewable(self) -> bool:
        return bool(self.token_url and self.client_id and (self.refresh_token or self.client_secret))

    @staticmethod
    def _jwt_expiry(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload.encode()))
            return float(decoded.get("exp") or 0)
        except (IndexError, ValueError, TypeError, json.JSONDecodeError):
            return 0.0

    def _renew(self) -> None:
        if not self.token_url or not self.client_id:
            raise SystemExit(f"{self.persona} load credential is missing and has no OIDC renewal configuration")
        if self.refresh_token:
            parameters = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
            }
            if self.client_secret:
                parameters["client_secret"] = self.client_secret
        elif self.client_secret:
            parameters = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        else:
            raise SystemExit(f"{self.persona} OIDC renewal requires a refresh token or client secret")
        request = urllib.request.Request(
            self.token_url,
            data=urllib.parse.urlencode(parameters).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.load(response)
        except Exception as exc:
            raise SystemExit(f"{self.persona} OIDC token renewal failed: {type(exc).__name__}") from exc
        token = str(result.get("access_token") or "")
        if not token:
            raise SystemExit(f"{self.persona} OIDC token renewal returned no access token")
        self.token = token
        self.refresh_token = str(result.get("refresh_token") or self.refresh_token)
        self.expires_at = self._jwt_expiry(token) or (time.time() + float(result.get("expires_in") or 300))
        self.refreshes += 1

    def ensure_valid_for(self, seconds: float) -> None:
        if self.expires_at and self.expires_at - time.time() < seconds and not self.renewable:
            raise SystemExit(
                f"{self.persona} bearer expires before this profile can finish; configure OIDC renewal"
            )

    def headers(self) -> dict[str, str]:
        if self.expires_at and self.expires_at <= time.time() + 60:
            with self._lock:
                if self.expires_at and self.expires_at <= time.time() + 60:
                    self._renew()
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Tenant-ID": self.tenant_id,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(value * len(ordered)) - 1))
    return ordered[index]


def request_once(
    base_url: str,
    path: str,
    headers: dict[str, str],
    timeout: float,
    *,
    persona: str = "",
    transport: PersistentHTTPClient | None = None,
) -> Sample:
    if transport is not None:
        return transport.get(path, headers, persona=persona)
    started = time.perf_counter()
    request = urllib.request.Request(f"{base_url}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return Sample(path, response.status, (time.perf_counter() - started) * 1000, False, persona=persona)
    except urllib.error.HTTPError as exc:
        exc.read()
        return Sample(path, exc.code, (time.perf_counter() - started) * 1000, False, str(exc), persona)
    except (TimeoutError, socket.timeout) as exc:
        return Sample(path, 0, (time.perf_counter() - started) * 1000, True, str(exc), persona)
    except urllib.error.URLError as exc:
        timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
        return Sample(path, 0, (time.perf_counter() - started) * 1000, timed_out, str(exc), persona)
    except Exception as exc:  # network failures remain explicit evidence
        return Sample(path, 0, (time.perf_counter() - started) * 1000, False, str(exc), persona)


def idempotency_probe(
    base_url: str,
    headers: dict[str, str],
    timeout: float,
    profile: str,
    portfolio_version: str = "2.1",
) -> dict[str, Any]:
    key = f"load-{profile}-{hashlib.sha256(base_url.encode()).hexdigest()[:12]}"
    payload = json.dumps({
        "evaluation_type": "internal_assisted_pilot_ready",
        "portfolio_version": portfolio_version,
        "comment": f"Load harness idempotency probe: {profile}",
    }).encode()
    responses: list[tuple[int, bytes]] = []
    for _ in range(2):
        request_headers = {
            **headers,
            "Content-Type": "application/json",
            "Idempotency-Key": key,
        }
        request = urllib.request.Request(
            f"{base_url}/api/v1/admin/platform-readiness/evaluations",
            data=payload,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                responses.append((response.status, response.read()))
        except urllib.error.HTTPError as exc:
            responses.append((exc.code, exc.read()))
        except Exception as exc:
            return {"passed": False, "error": type(exc).__name__, "statuses": []}
    statuses = [status for status, _ in responses]
    bodies_match = responses[0][1] == responses[1][1]
    return {
        "passed": statuses == [200, 200] and bodies_match,
        "statuses": statuses,
        "responses_identical": bodies_match,
        "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
    }


def fetch_pool_metrics(base_url: str, timeout: float) -> dict[str, float]:
    request = urllib.request.Request(f"{base_url}/metrics", headers={"Accept": "text/plain"}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    values: dict[str, float] = {}
    patterns = {
        "checked_out": r'asf_db_pool_connections\{state="checked_out"\}\s+([0-9.]+)',
        "overflow": r'asf_db_pool_connections\{state="overflow"\}\s+([0-9.]+)',
        "utilization_ratio": r"asf_db_pool_utilization_ratio\s+([0-9.]+)",
        "http_in_flight": r"asf_http_requests_in_flight\s+([0-9.]+)",
        "http_in_flight_peak": r"asf_http_requests_in_flight_peak\s+([0-9.]+)",
        "threadpool_tokens": r"asf_api_threadpool_tokens\s+([0-9.]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, payload)
        if match:
            values[key] = float(match.group(1))
    if len(values) != len(patterns):
        raise ValueError("database pool metrics are incomplete")
    return values


def fetch_required_pool_metrics(
    base_url: str,
    timeout: float,
    *,
    attempts: int = 8,
) -> dict[str, float]:
    """Allow every API worker to initialize its per-process pool metrics."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch_pool_metrics(base_url, timeout)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25)
    assert last_error is not None
    raise last_error


def monitor_pool(
    base_url: str,
    timeout: float,
    stop: threading.Event,
    observations: list[dict[str, float]],
) -> None:
    while not stop.is_set():
        try:
            observations.append(fetch_pool_metrics(base_url, timeout))
        except Exception:
            observations.append({"error": 1.0})
        stop.wait(1.0)


def assess_samples(samples: list[Sample]) -> dict[str, Any]:
    failures = [sample for sample in samples if sample.status < 200 or sample.status >= 300]
    timeouts = [sample for sample in failures if sample.timed_out]
    provider_errors = [sample for sample in failures if sample.status in {429, 502, 503, 504}]
    tolerated_ids = {id(sample) for sample in (*timeouts, *provider_errors)}
    unexpected_failures = [sample for sample in failures if id(sample) not in tolerated_ids]
    count = len(samples)
    provider_error_rate = len(provider_errors) / count if count else 1.0
    timeout_rate = len(timeouts) / count if count else 1.0
    failure_rate = len(failures) / count if count else 1.0
    unexpected_failure_rate = len(unexpected_failures) / count if count else 1.0
    passed = (
        bool(count)
        and not unexpected_failures
        and provider_error_rate <= 0.05
        and timeout_rate <= 0.03
    )
    return {
        "failures": failures,
        "timeouts": timeouts,
        "provider_errors": provider_errors,
        "unexpected_failures": unexpected_failures,
        "provider_error_rate": provider_error_rate,
        "timeout_rate": timeout_rate,
        "failure_rate": failure_rate,
        "unexpected_failure_rate": unexpected_failure_rate,
        "passed": passed,
    }


def warmup_schedule(requests: int) -> list[tuple[str, str]]:
    """Cover each persona's read mix independently before measuring."""
    positions = {"owner": 0, "vp": 0}
    schedule: list[tuple[str, str]] = []
    for number in range(requests):
        persona = "owner" if number % 2 == 0 else "vp"
        paths = PERSONA_PATHS[persona]
        path = paths[positions[persona] % len(paths)]
        positions[persona] += 1
        schedule.append((persona, path))
    return schedule


def virtual_user(
    user_number: int,
    *,
    base_url: str,
    persona: str,
    credential: TokenProvider,
    deadline: float,
    start_delay: float,
    timeout: float,
    think_time: float,
    samples: list[Sample],
    lock: threading.Lock,
) -> None:
    if start_delay:
        time.sleep(start_delay)
    # Persona selection consumes the parity bit. Divide it out so the first
    # request of an instant spike covers every path for both personas.
    sequence = user_number // 2
    local: list[Sample] = []
    transport = PersistentHTTPClient(base_url, timeout)
    try:
        while time.monotonic() < deadline:
            paths = PERSONA_PATHS[persona]
            path = paths[sequence % len(paths)]
            local.append(
                request_once(
                    base_url,
                    path,
                    credential.headers(),
                    timeout,
                    persona=persona,
                    transport=transport,
                )
            )
            sequence += 1
            if think_time:
                time.sleep(think_time)
    finally:
        transport.close()
    with lock:
        samples.extend(local)


def run_profile(args: argparse.Namespace) -> dict[str, Any]:
    virtual_users, default_seconds = PROFILES[args.profile]
    duration_seconds = max(1, int(default_seconds * args.duration_scale))
    ramp_seconds = min(
        duration_seconds * 0.8,
        PROFILE_RAMP_SECONDS[args.profile] * args.duration_scale,
    )
    think_time = PROFILE_THINK_SECONDS[args.profile] if args.think_time is None else args.think_time
    base_url = args.base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit("--base-url must use http or https")
    if not args.allow_remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Remote load is disabled; pass --allow-remote only for an explicitly authorized target")
    owner_token = os.getenv("ASF_LOAD_BEARER_TOKEN", "").strip()
    owner_tenant_id = os.getenv("ASF_LOAD_TENANT_ID", "").strip()
    vp_token = os.getenv("ASF_LOAD_VP_BEARER_TOKEN", "").strip()
    vp_tenant_id = os.getenv("ASF_LOAD_VP_TENANT_ID", owner_tenant_id).strip()
    if not owner_tenant_id or not vp_tenant_id:
        raise SystemExit(
            "ASF_LOAD_TENANT_ID and ASF_LOAD_VP_TENANT_ID are required"
        )
    credentials = {
        "owner": TokenProvider(persona="owner", tenant_id=owner_tenant_id, bearer_token=owner_token),
        "vp": TokenProvider(persona="vp", tenant_id=vp_tenant_id, bearer_token=vp_token),
    }
    for credential in credentials.values():
        credential.ensure_valid_for(duration_seconds + args.timeout + 60)
    for persona, warmup_path in warmup_schedule(args.warmup_requests):
        warmup = request_once(
            base_url,
            warmup_path,
            credentials[persona].headers(),
            args.timeout,
            persona=persona,
        )
        if warmup.status < 200 or warmup.status >= 300:
            raise SystemExit(
                f"Warm-up failed for {warmup.path}: status={warmup.status} "
                f"timeout={warmup.timed_out} error={warmup.error}"
            )
    command_probe = idempotency_probe(
        base_url,
        credentials["owner"].headers(),
        args.timeout,
        args.profile,
        getattr(args, "portfolio_version", "2.1"),
    )
    if not command_probe["passed"]:
        raise SystemExit(f"Idempotency probe failed: {json.dumps(command_probe, sort_keys=True)}")
    samples: list[Sample] = []
    lock = threading.Lock()
    started_at = datetime.now(timezone.utc)
    monotonic_started = time.monotonic()
    deadline = monotonic_started + duration_seconds
    try:
        pool_observations: list[dict[str, float]] = [
            fetch_required_pool_metrics(base_url, args.timeout)
        ]
    except Exception as exc:
        raise SystemExit(f"Database pool metrics are required before load: {type(exc).__name__}") from exc
    monitor_stop = threading.Event()
    monitor = threading.Thread(
        target=monitor_pool, args=(base_url, args.timeout, monitor_stop, pool_observations), daemon=True,
    )
    monitor.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=virtual_users) as executor:
        futures = [
            executor.submit(
                virtual_user,
                number,
                base_url=base_url,
                persona="owner" if number % 2 == 0 else "vp",
                credential=credentials["owner" if number % 2 == 0 else "vp"],
                deadline=deadline,
                start_delay=(ramp_seconds * number / max(1, virtual_users - 1)),
                timeout=args.timeout,
                think_time=think_time,
                samples=samples,
                lock=lock,
            )
            for number in range(virtual_users)
        ]
        for future in futures:
            future.result()
    monitor_stop.set()
    monitor.join(timeout=max(1.0, args.timeout + 1.0))
    elapsed = time.monotonic() - monotonic_started
    durations = [sample.duration_ms for sample in samples]
    assessment = assess_samples(samples)
    failures = assessment["failures"]
    timeouts = assessment["timeouts"]
    provider_errors = assessment["provider_errors"]
    unexpected_failures = assessment["unexpected_failures"]
    count = len(samples)
    provider_error_rate = assessment["provider_error_rate"]
    timeout_rate = assessment["timeout_rate"]
    failure_rate = assessment["failure_rate"]
    unexpected_failure_rate = assessment["unexpected_failure_rate"]
    p95_ms = percentile(durations, 0.95)
    passed = assessment["passed"] and p95_ms <= 5000 and command_probe["passed"]
    valid_pool_observations = [item for item in pool_observations if "error" not in item]
    passed = passed and bool(valid_pool_observations)
    by_path = {}
    all_paths = tuple(dict.fromkeys(path for paths in PERSONA_PATHS.values() for path in paths))
    for endpoint_path in all_paths:
        path_samples = [sample for sample in samples if sample.path == endpoint_path]
        path_durations = [sample.duration_ms for sample in path_samples]
        path_assessment = assess_samples(path_samples)
        by_path[endpoint_path] = {
            "requests": len(path_samples),
            "latency_ms": {
                "median": round(statistics.median(path_durations), 3) if path_durations else 0.0,
                "p95": round(percentile(path_durations, 0.95), 3),
                "max": round(max(path_durations), 3) if path_durations else 0.0,
            },
            "failures": len(path_assessment["failures"]),
            "unexpected_failures": len(path_assessment["unexpected_failures"]),
            "timeout_rate": round(path_assessment["timeout_rate"], 6),
        }
    passed = passed and all(
        row["requests"] > 0
        and row["unexpected_failures"] == 0
        and row["timeout_rate"] <= 0.03
        and row["latency_ms"]["p95"] <= 5000
        for row in by_path.values()
    )
    report = {
        "schema_version": "service-portfolio-load-v2",
        "portfolio_version": getattr(args, "portfolio_version", "2.1"),
        "production_e2e_run_id": os.getenv("ASF_PRODUCTION_E2E_RUN_ID", "").strip() or None,
        "profile": args.profile,
        "environment": "homologation",
        "tenant_id": owner_tenant_id,
        "commit_sha": release_commit_sha(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": f"portfolio-load-test.py --profile {args.profile}",
        "required_for_pilot": args.profile in {"baseline-2", "load-20", "load-50", "soak-20"},
        "required_for_production_scale": True,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "target_origin": f"{parsed.scheme}://{parsed.netloc}",
        "actors": {
            "owner": {"tenant_id_sha256": hashlib.sha256(owner_tenant_id.encode()).hexdigest()},
            "vp": {"tenant_id_sha256": hashlib.sha256(vp_tenant_id.encode()).hexdigest()},
        },
        "authentication": {
            persona: {
                "renewable": credential.renewable,
                "token_renewals": credential.refreshes,
            }
            for persona, credential in credentials.items()
        },
        "personas": sorted(PERSONA_PATHS),
        "command_probe": command_probe,
        "db_pool": {
            "observations": len(valid_pool_observations),
            "observation_errors": len(pool_observations) - len(valid_pool_observations),
            "max_checked_out": max((item["checked_out"] for item in valid_pool_observations), default=0),
            "max_overflow": max((item["overflow"] for item in valid_pool_observations), default=0),
            "max_utilization_ratio": max((item["utilization_ratio"] for item in valid_pool_observations), default=0),
            "max_http_in_flight": max((item["http_in_flight"] for item in valid_pool_observations), default=0),
            "max_http_in_flight_peak": max((item["http_in_flight_peak"] for item in valid_pool_observations), default=0),
            "threadpool_tokens_per_process": max((item["threadpool_tokens"] for item in valid_pool_observations), default=0),
        },
        "virtual_users": virtual_users,
        "ramp_seconds": round(ramp_seconds, 3),
        "think_time_seconds": think_time,
        "duration_scale": args.duration_scale,
        "warmup_requests": args.warmup_requests,
        "duration_seconds": round(elapsed, 3),
        "requests": count,
        "requests_per_second": round(count / elapsed, 3) if elapsed else 0.0,
        "transport_retries": sum(sample.transport_retries for sample in samples),
        "latency_ms": {
            "median": round(statistics.median(durations), 3) if durations else 0.0,
            "p95": round(p95_ms, 3),
            "max": round(max(durations), 3) if durations else 0.0,
        },
        "by_path": by_path,
        "failures": len(failures),
        "failure_rate": round(failure_rate, 6),
        "unexpected_failures": len(unexpected_failures),
        "unexpected_failure_rate": round(unexpected_failure_rate, 6),
        "provider_error_rate": round(provider_error_rate, 6),
        "timeout_rate": round(timeout_rate, 6),
        "status": "passed" if passed else "failed",
        "thresholds": {
            "provider_error_rate_max": 0.05,
            "timeout_rate_max": 0.03,
            "unexpected_failure_rate_max": 0.0,
            "operational_read_p95_ms_max": 5000,
        },
        "errors": [asdict(sample) for sample in failures[:100]],
        "summary": {
            "requests": count,
            "passed": passed,
            "p95_ms": round(p95_ms, 3),
        },
        "failure_details": [asdict(sample) for sample in failures[:100]],
        "artifacts": [],
    }
    return report


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"portfolio-v2-{report['profile']}"
    json_payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (output_dir / f"{stem}.json").write_text(json_payload, encoding="utf-8")
    markdown = (
        f"# Portfolio v2 load report — {report['profile']}\n\n"
        f"- Status: **{report['status']}**\n"
        f"- Production E2E run: `{report.get('production_e2e_run_id') or 'unbound'}`\n"
        f"- Virtual users: {report['virtual_users']}\n"
        f"- Ramp / think time: {report['ramp_seconds']} / {report['think_time_seconds']} s\n"
        f"- Duration: {report['duration_seconds']} s\n"
        f"- Requests: {report['requests']} ({report['requests_per_second']} req/s)\n"
        f"- Transparent keep-alive reconnects: {report['transport_retries']}\n"
        f"- Latency median/p95/max: {report['latency_ms']['median']} / {report['latency_ms']['p95']} / {report['latency_ms']['max']} ms\n"
        f"- Failures: {report['failures']} ({report['failure_rate']:.2%})\n"
        f"- Unexpected failures: {report['unexpected_failures']} ({report['unexpected_failure_rate']:.2%})\n"
        f"- Provider errors: {report['provider_error_rate']:.2%}\n"
        f"- Timeouts: {report['timeout_rate']:.2%}\n\n"
        f"- DB pool max utilization observed: {report['db_pool']['max_utilization_ratio']:.2%} "
        f"({report['db_pool']['observations']} samples)\n\n"
        "This report is machine evidence only. Human approval must be recorded separately.\n"
    )
    (output_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/portfolio-v2/load"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--think-time", type=float)
    parser.add_argument("--warmup-requests", type=int, default=40)
    parser.add_argument("--duration-scale", type=float, default=1.0)
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--portfolio-version",
        choices=("2.0", "2.1"),
        default=os.getenv("ASF_PORTFOLIO_VERSION", "2.1"),
    )
    args = parser.parse_args()
    if args.duration_scale <= 0 or args.duration_scale > 1:
        raise SystemExit("--duration-scale must be > 0 and <= 1")
    if args.think_time is not None and args.think_time < 0:
        raise SystemExit("--think-time must be >= 0")
    if args.warmup_requests < 3 or args.warmup_requests > 100:
        raise SystemExit("--warmup-requests must be between 3 and 100")
    report = run_profile(args)
    write_report(report, args.output_dir)
    print(json.dumps({key: report[key] for key in ("profile", "status", "requests", "provider_error_rate", "timeout_rate")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
