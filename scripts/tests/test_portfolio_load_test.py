from __future__ import annotations

import importlib.util
import io
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "portfolio-load-test.py"
SPEC = importlib.util.spec_from_file_location("portfolio_load_test", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PortfolioLoadHarnessTests(unittest.TestCase):
    @staticmethod
    def _jwt(exp: int) -> str:
        payload = MODULE.base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        return f"header.{payload}.signature"

    def test_fixed_token_must_outlive_the_profile(self) -> None:
        token = self._jwt(int(MODULE.time.time()) + 30)
        with patch.dict(MODULE.os.environ, {}, clear=False):
            credential = MODULE.TokenProvider(persona="owner", tenant_id="tenant", bearer_token=token)

        with self.assertRaisesRegex(SystemExit, "expires before this profile"):
            credential.ensure_valid_for(120)

    def test_client_credentials_are_renewed_without_persisting_them(self) -> None:
        token = self._jwt(int(MODULE.time.time()) + 600)
        response = io.BytesIO(json.dumps({"access_token": token, "expires_in": 600}).encode())
        with (
            patch.object(MODULE.urllib.request, "urlopen", return_value=response),
            patch.dict(MODULE.os.environ, {
                "ASF_LOAD_OIDC_TOKEN_URL": "http://127.0.0.1:8081/token",
                "ASF_LOAD_OWNER_CLIENT_ID": "load-owner",
                "ASF_LOAD_OWNER_CLIENT_SECRET": "local-secret",
            }),
        ):
            credential = MODULE.TokenProvider(persona="owner", tenant_id="tenant", bearer_token="")

        self.assertTrue(credential.renewable)
        self.assertEqual(credential.refreshes, 1)
        self.assertEqual(credential.headers()["Authorization"], f"Bearer {token}")

    def test_spike_starting_sequences_cover_every_persona_path(self) -> None:
        owner_paths = {
            MODULE.PERSONA_PATHS["owner"][(number // 2) % len(MODULE.PERSONA_PATHS["owner"])]
            for number in range(0, 500, 2)
        }
        vp_paths = {
            MODULE.PERSONA_PATHS["vp"][(number // 2) % len(MODULE.PERSONA_PATHS["vp"])]
            for number in range(1, 500, 2)
        }

        self.assertEqual(owner_paths, set(MODULE.PERSONA_PATHS["owner"]))
        self.assertEqual(vp_paths, set(MODULE.PERSONA_PATHS["vp"]))

    def test_warmup_covers_each_persona_path_independently(self) -> None:
        schedule = MODULE.warmup_schedule(18)
        owner_paths = {path for persona, path in schedule if persona == "owner"}
        vp_paths = {path for persona, path in schedule if persona == "vp"}

        self.assertEqual(owner_paths, set(MODULE.PERSONA_PATHS["owner"]))
        self.assertEqual(vp_paths, set(MODULE.PERSONA_PATHS["vp"]))

    def test_socket_timeout_is_classified_as_timeout(self) -> None:
        with patch.object(MODULE.urllib.request, "urlopen", side_effect=socket.timeout("timed out")):
            sample = MODULE.request_once("http://127.0.0.1:8000", "/health", {}, 0.01)

        self.assertEqual(sample.status, 0)
        self.assertTrue(sample.timed_out)

    def test_unexpected_transport_error_fails_closed(self) -> None:
        samples = [MODULE.Sample("/health", 200, 1.0, False) for _ in range(99)]
        samples.append(MODULE.Sample("/health", 0, 1.0, False, "connection reset"))

        assessment = MODULE.assess_samples(samples)

        self.assertFalse(assessment["passed"])
        self.assertEqual(len(assessment["unexpected_failures"]), 1)

    def test_persistent_client_reconnects_once_for_a_stale_keepalive(self) -> None:
        stale_connection = MagicMock()
        stale_connection.request.side_effect = MODULE.http.client.RemoteDisconnected("closed")
        healthy_connection = MagicMock()
        response = MagicMock(status=200, reason="OK")
        healthy_connection.getresponse.return_value = response
        with patch.object(
            MODULE.http.client,
            "HTTPConnection",
            side_effect=[stale_connection, healthy_connection],
        ):
            client = MODULE.PersistentHTTPClient("http://127.0.0.1:8000", 1.0)
            sample = client.get("/health", {}, persona="owner")
            client.close()

        self.assertEqual(sample.status, 200)
        self.assertEqual(sample.transport_retries, 1)
        stale_connection.close.assert_called_once()
        response.read.assert_called_once()

    def test_documented_provider_and_timeout_thresholds_are_applied(self) -> None:
        allowed = [MODULE.Sample("/health", 200, 1.0, False) for _ in range(93)]
        allowed.extend(MODULE.Sample("/health", 503, 1.0, False) for _ in range(4))
        allowed.extend(MODULE.Sample("/health", 0, 1.0, True, "timed out") for _ in range(3))
        self.assertTrue(MODULE.assess_samples(allowed)["passed"])

        too_many_timeouts = allowed[:-1]
        too_many_timeouts.append(MODULE.Sample("/health", 0, 1.0, True, "timed out"))
        too_many_timeouts.append(MODULE.Sample("/health", 0, 1.0, True, "timed out"))
        self.assertFalse(MODULE.assess_samples(too_many_timeouts)["passed"])

    def test_full_duration_scale_is_persisted_for_release_evidence(self) -> None:
        args = type("Args", (), {
            "profile": "baseline-2", "duration_scale": 1.0, "base_url": "http://127.0.0.1:8000",
            "allow_remote": False, "timeout": 0.01, "think_time": 0.1, "warmup_requests": 1,
        })()
        with (
            patch.object(MODULE, "request_once", return_value=MODULE.Sample("/health", 200, 1.0, False)),
            patch.object(MODULE, "idempotency_probe", return_value={"passed": True}),
            patch.object(MODULE, "fetch_pool_metrics", return_value={
                "checked_out": 1.0,
                "overflow": 0.0,
                "utilization_ratio": 0.1,
                "http_in_flight": 1.0,
                "http_in_flight_peak": 1.0,
                "threadpool_tokens": 40.0,
            }),
            patch.dict(MODULE.os.environ, {
                "ASF_LOAD_BEARER_TOKEN": "owner-token",
                "ASF_LOAD_TENANT_ID": "tenant",
                "ASF_LOAD_VP_BEARER_TOKEN": "vp-token",
                "ASF_LOAD_VP_TENANT_ID": "tenant",
            }),
            patch.object(MODULE, "PROFILES", {"baseline-2": (1, 1)}),
        ):
            report = MODULE.run_profile(args)
        self.assertEqual(report["duration_scale"], 1.0)
        self.assertEqual(report["schema_version"], "service-portfolio-load-v2")
        self.assertEqual(report["personas"], ["owner", "vp"])
        self.assertEqual(report["think_time_seconds"], 0.1)

    def test_profiles_distinguish_sustained_stress_from_short_500_user_spike(self) -> None:
        self.assertGreater(MODULE.PROFILE_RAMP_SECONDS["stress-200"], 0)
        self.assertEqual(MODULE.PROFILE_RAMP_SECONDS["spike-500"], 30)
        self.assertGreater(MODULE.PROFILES["spike-500"][0], MODULE.PROFILES["stress-200"][0])
        self.assertLess(MODULE.PROFILES["spike-500"][1], MODULE.PROFILES["stress-200"][1])
        self.assertGreaterEqual(MODULE.PROFILE_THINK_SECONDS["stress-200"], 1)


if __name__ == "__main__":
    unittest.main()
