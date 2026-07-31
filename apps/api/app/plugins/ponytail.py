"""Production-safe Ponytail policy adapter.

The upstream project is an instruction plugin.  This module preserves the
useful behaviour as a pure, version-pinned policy while the factory keeps
authority over tools, files, budgets and quality gates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from app.agents.ai_native_contracts import stable_hash


PONYTAIL_VERSION = "4.8.4"
PONYTAIL_SOURCE_REVISION = "16f29800fd2681bdf24f3eb4ccffe38be3baec6b"
PONYTAIL_SOURCE_URL = "https://github.com/DietrichGebert/ponytail"

PonytailMode = Literal["off", "lite", "full", "ultra"]
PonytailCommand = Literal["activate", "instructions", "review", "audit", "debt", "gain", "help"]


_BASE = """
PONYTAIL MODE ACTIVE — level: {mode}.
Understand the approved task and trace the real flow before minimizing it.
Use the first rung that fully holds: (1) do not build speculative work, (2) reuse existing code or artifacts,
(3) use the standard library, (4) use a native platform capability, (5) use an already-installed dependency,
(6) use the smallest clear expression, and only then (7) add the minimum code that works.
Fix a bug at its root cause after checking every caller; never patch only the reported symptom.
Do not add one-implementation interfaces, one-product factories, unused configuration, future scaffolding,
decorative wrappers, avoidable dependencies or duplicate helpers. Prefer deletion and boring code.
Never minimize away approved requirements, trust-boundary validation, data-loss protection, security,
tenant isolation, accessibility, error handling, tests, evidence, observability, budgets, HRS or human approval.
Non-trivial logic must retain at least one runnable check. A deliberate shortcut must state its ceiling and
upgrade trigger with `ponytail: <ceiling>; upgrade when <trigger>`.
""".strip()

_MODE = {
    "lite": "Build the approved solution completely. Report a simpler safe alternative, but do not apply it silently.",
    "full": "Enforce the complete minimal-solution ladder. The shortest correct and maintainable diff wins.",
    "ultra": "Challenge speculative scope before approval. Once a requirement is approved, implement it completely.",
    "off": "Ponytail is disabled for this activity; platform safety and quality controls still apply.",
}

_REVIEW = """
PONYTAIL REVIEW. Review the actual diff for unnecessary complexity in addition to correctness.
Return typed findings using only: delete, stdlib, native, yagni, shrink, root_cause.
Every finding must name a generated_app path, a precise problem and its smaller replacement.
Never flag a required test, security control, validation, accessibility behaviour or evidence as bloat.
If nothing can safely be removed, return no findings and state `Lean already. Ship.` in CODE_REVIEW.md.
""".strip()

_AUDIT = """
PONYTAIL AUDIT. Audit the generated application as a whole for dead flexibility, single-product factories,
single-implementation abstractions, pass-through wrappers, duplicate helpers, unused flags, avoidable dependencies,
hand-rolled standard-library behaviour and platform-native features implemented in application code.
Rank only evidence-backed findings. Estimated removable lines are estimates, never claimed savings.
""".strip()

_HELP = {
    "modes": {
        "lite": "complete build plus one safer simplification suggestion",
        "full": "enforce the minimal-solution ladder",
        "ultra": "challenge speculative scope before approval",
        "off": "administrative rollback only",
    },
    "commands": {
        "instructions": "stable minimal-solution policy",
        "review": "diff-focused over-engineering review",
        "audit": "whole generated-application minimality audit",
        "debt": "deterministic deliberate-simplification ledger",
        "gain": "measured factory metrics with an explicit baseline boundary",
        "help": "this production capability card",
    },
}

_DEBT = re.compile(r"(?://|#|/\*)\s*ponytail:\s*(?P<body>[^\n*]+)", re.IGNORECASE)


@dataclass(frozen=True)
class PonytailDebtItem:
    path: str
    line: int
    statement: str
    has_trigger: bool


class PonytailPolicy:
    """Pure policy used by inline and Temporal activity execution."""

    @staticmethod
    def manifest() -> dict[str, Any]:
        capabilities = ["activate", "instructions", "review", "audit", "debt", "gain", "help"]
        payload = {
            "name": "ponytail",
            "version": PONYTAIL_VERSION,
            "source_revision": PONYTAIL_SOURCE_REVISION,
            "source_url": PONYTAIL_SOURCE_URL,
            "license": "MIT",
            "capabilities": capabilities,
            "access_mode": "read_only_policy",
            "automatic_updates": False,
            "codex_plugin_selector": "ponytail@ponytail",
            "codex_default_mode": "full",
        }
        return {**payload, "manifest_sha256": stable_hash(payload)}

    @staticmethod
    def mode_for_node(node: dict[str, Any]) -> PonytailMode:
        configured = str(node.get("ponytail_mode") or "").strip().lower()
        if configured in {"off", "lite", "full", "ultra"}:
            return configured  # type: ignore[return-value]
        return "full"

    @staticmethod
    def instructions(mode: PonytailMode) -> str:
        if mode == "off":
            return _MODE["off"]
        return f"{_BASE.format(mode=mode)}\n{_MODE[mode]}"

    @staticmethod
    def command_instructions(command: PonytailCommand, mode: PonytailMode) -> str:
        if command in {"activate", "instructions"}:
            return PonytailPolicy.instructions(mode)
        if command == "review":
            return _REVIEW
        if command == "audit":
            return _AUDIT
        if command == "debt":
            return "Scan only persisted generated files for explicit `ponytail:` markers; do not infer hidden debt."
        if command == "gain":
            return "Report only measured run metrics. Never present upstream benchmark figures as this run's savings."
        return json.dumps(_HELP, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def prompt_for_node(node: dict[str, Any]) -> tuple[PonytailMode, list[PonytailCommand], str]:
        if not bool(node.get("ponytail_enabled")):
            return "off", [], ""
        mode = PonytailPolicy.mode_for_node(node)
        configured = [str(item) for item in (node.get("ponytail_commands") or [])]
        commands: list[PonytailCommand] = ["instructions"]
        for item in configured:
            if item in {"activate", "instructions", "review", "audit", "debt", "gain", "help"} and item not in commands:
                commands.append(item)  # type: ignore[arg-type]
        parts = [PonytailPolicy.command_instructions(command, mode) for command in commands if command not in {"debt", "gain", "help"}]
        return mode, commands, "\n\n".join(dict.fromkeys(part for part in parts if part))

    @staticmethod
    def scan_debt(files: Iterable[tuple[str, str]]) -> list[PonytailDebtItem]:
        rows: list[PonytailDebtItem] = []
        for path, content in files:
            for line_number, line in enumerate((content or "").splitlines(), start=1):
                match = _DEBT.search(line)
                if not match:
                    continue
                body = match.group("body").strip().rstrip("/").strip()
                normalized = body.casefold()
                rows.append(
                    PonytailDebtItem(
                        path=path,
                        line=line_number,
                        statement=body,
                        has_trigger="upgrade" in normalized and ("when" in normalized or "se " in normalized),
                    )
                )
        return rows

    @staticmethod
    def debt_markdown(items: list[PonytailDebtItem]) -> str:
        lines = ["# PONYTAIL_DEBT.md", "", "Proveniência: varredura determinística de arquivos persistidos.", ""]
        if not items:
            return "\n".join([*lines, "Nenhum marcador `ponytail:` encontrado. Ledger limpo."])
        lines.extend(["| Arquivo | Linha | Simplificação, teto e gatilho | Estado |", "|---|---:|---|---|"])
        for item in items:
            statement = item.statement.replace("|", "\\|")
            state = "rastreável" if item.has_trigger else "sem gatilho"
            lines.append(f"| `{item.path}` | {item.line} | {statement} | {state} |")
        missing = sum(not item.has_trigger for item in items)
        lines.extend(["", f"{len(items)} marcadores; {missing} sem gatilho de evolução."])
        return "\n".join(lines)

    @staticmethod
    def help_payload() -> dict[str, Any]:
        return {**PonytailPolicy.manifest(), **_HELP}
