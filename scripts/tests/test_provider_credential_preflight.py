from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "provider_credential_preflight.py"
SPEC = importlib.util.spec_from_file_location("provider_credential_preflight", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_rejects_missing_and_placeholder_credentials() -> None:
    assert MODULE.validate_provider_credentials("", "")[0] is False
    assert MODULE.validate_provider_credentials("replace-with-provider-key", "")[0] is False
    assert MODULE.validate_provider_credentials("short", "")[0] is False


def test_accepts_well_formed_openrouter_or_openai_credentials() -> None:
    openrouter = "sk-" + "or-v1-" + ("x" * 48)
    openai = "sk-" + ("x" * 48)
    assert MODULE.validate_provider_credentials(openrouter, "")[0] is True
    assert MODULE.validate_provider_credentials("", openai)[0] is True


def test_rejects_whitespace_and_invalid_prefix_without_echoing_values() -> None:
    credential = "sk-" + "or-v1-" + ("x" * 48)
    valid, message = MODULE.validate_provider_credentials(f"{credential}\n", "")
    assert valid is False
    assert credential not in message

    valid, message = MODULE.validate_provider_credentials("token-" + ("x" * 48), "")
    assert valid is False
    assert "token-" not in message
