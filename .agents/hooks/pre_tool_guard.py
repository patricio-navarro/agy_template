#!/usr/bin/env python3
"""Deterministic Antigravity PreToolUse guard engine for agy_template workspaces."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

DECISION_PRECEDENCE = {
    "deny": 3,
    "force_ask": 2,
    "ask": 1,
    "allow": 0,
}

FILE_URI_MD_RE = re.compile(r"\]\(file:///")
LIVE_DOTENV_BASENAME_RE = re.compile(r"^\.env(\.(?!example$|sample$|template$).+)?$")


def _is_within_workspace(target: Path, workspace_paths: list[str], cwd: str) -> bool:
    roots = [Path(p).resolve() for p in workspace_paths if p]
    if not roots and cwd:
        roots = [Path(cwd).resolve()]
    if not roots:
        return True
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    for root in roots:
        if resolved == root or root in resolved.parents:
            return True
    return False


def _is_artifact_or_gemini_path(target_str: str) -> bool:
    normalized = target_str.replace("\\", "/")
    return "/.gemini/" in normalized or "/brain/" in normalized


def _resolve_target_path(raw_path: str, cwd: str, workspace_paths: list[str]) -> Path:
    p = Path(raw_path)
    if p.is_absolute():
        return p
    base = cwd or (workspace_paths[0] if workspace_paths else ".")
    return Path(base) / p


def _load_rules() -> dict[str, Any]:
    rules_path = Path(
        os.environ.get("AGY_GUARD_RULES") or Path(__file__).with_name("guard_rules.json")
    )
    if not rules_path.is_file():
        return {"command_rules": []}
    with rules_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _is_workspace_initialized(cwd: str, workspace_paths: list[str]) -> bool:
    candidates = [Path(__file__).resolve().parents[2] / ".agy-manifest.json"]
    if cwd:
        candidates.append(Path(cwd) / ".agy-manifest.json")
    for wp in workspace_paths:
        if wp:
            candidates.append(Path(wp) / ".agy-manifest.json")
    return any(c.is_file() for c in candidates)


def evaluate_payload(payload: dict[str, Any], rules_data: dict[str, Any] | None = None) -> dict[str, str]:
    tool_call = payload.get("toolCall") or {}
    tool_name = str(tool_call.get("name") or "")
    args = tool_call.get("args") or {}
    cwd = str(payload.get("cwd") or "")
    workspace_paths = [str(p) for p in (payload.get("workspacePaths") or [])]

    if tool_name in ("write_file", "edit_file"):
        raw_path = str(args.get("Path") or args.get("path") or "")
        if not raw_path:
            return {"decision": "allow"}

        target = _resolve_target_path(raw_path, cwd, workspace_paths)
        target_str = str(target)

        if _is_artifact_or_gemini_path(target_str) or _is_artifact_or_gemini_path(raw_path):
            return {"decision": "allow"}

        in_workspace = _is_within_workspace(target, workspace_paths, cwd)
        if not in_workspace:
            return {"decision": "allow"}

        if target.name and LIVE_DOTENV_BASENAME_RE.match(target.name):
            return {
                "decision": "ask",
                "reason": "Modifying live .env configuration files requires explicit confirmation.",
            }

        if target.suffix.lower() == ".md":
            text_to_check = str(
                args.get("Content")
                or args.get("Replacement")
                or args.get("content")
                or args.get("replacement")
                or ""
            )
            if FILE_URI_MD_RE.search(text_to_check):
                return {
                    "decision": "deny",
                    "reason": "Markdown Hygiene Rule: Committed repository .md files must use portable relative paths, never machine-local ](file:///...) links.",
                }

        return {"decision": "allow"}

    if tool_name == "run_command":
        command_line = str(args.get("CommandLine") or args.get("command") or "")
        if not command_line:
            return {"decision": "allow"}

        rules = (rules_data if rules_data is not None else _load_rules()).get("command_rules") or []
        initialized = _is_workspace_initialized(cwd, workspace_paths)

        best_decision = "allow"
        best_reason = ""

        for rule in rules:
            if rule.get("only_when_initialized") and not initialized:
                continue
            pattern = rule.get("pattern")
            if not pattern:
                continue
            if not re.search(pattern, command_line):
                continue
            exclude_pattern = rule.get("exclude_pattern")
            if exclude_pattern and re.search(exclude_pattern, command_line):
                continue

            decision = str(rule.get("decision") or "ask")
            if DECISION_PRECEDENCE.get(decision, 0) > DECISION_PRECEDENCE.get(best_decision, 0):
                best_decision = decision
                best_reason = str(rule.get("reason") or f"Matched guard rule: {rule.get('id', 'unknown')}")

        if best_decision != "allow":
            return {"decision": best_decision, "reason": best_reason}

    return {"decision": "allow"}


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        result = evaluate_payload(payload)
    except Exception:
        result = {"decision": "allow"}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
