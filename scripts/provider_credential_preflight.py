#!/usr/bin/env python3
"""Fail closed before a paid provider run without exposing credential values."""

from __future__ import annotations

import os


PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "example",
    "placeholder",
    "replace",
    "your-key",
)


def validate_provider_credentials(
    openrouter_api_key: str,
    openai_api_key: str,
) -> tuple[bool, str]:
    candidates = [
        ("OPENROUTER_API_KEY", openrouter_api_key, "sk-" + "or-v1-", 40),
        ("OPENAI_API_KEY", openai_api_key, "sk-", 20),
    ]
    configured = [candidate for candidate in candidates if candidate[1]]
    if not configured:
        return False, "OPENROUTER_API_KEY or OPENAI_API_KEY is required"

    for name, value, prefix, minimum_length in configured:
        lowered = value.lower()
        if (
            len(value) < minimum_length
            or not value.startswith(prefix)
            or value != value.strip()
            or any(character.isspace() for character in value)
            or any(marker in lowered for marker in PLACEHOLDER_MARKERS)
        ):
            return False, f"{name} does not look like a rotated provider credential"
    return True, "provider credential format accepted"


def main() -> int:
    valid, message = validate_provider_credentials(
        os.getenv("OPENROUTER_API_KEY", ""),
        os.getenv("OPENAI_API_KEY", ""),
    )
    if not valid:
        print(message)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
