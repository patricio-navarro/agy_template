#!/usr/bin/env python3
"""SessionStart hook that alerts the agent when agy_template has not been initialized yet."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def detect(workspace_root: Path | None = None) -> dict:
    root = workspace_root or Path(__file__).resolve().parents[2]
    manifest = root / ".agy-manifest.json"
    if manifest.is_file():
        return {}
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": (
                        "This workspace is an uninitialized agy_template repository. "
                        "If the user wants to configure their project stack and clean up unused automations, "
                        "read .agents/skills/template-initializer/SKILL.md and run ./agy-init. "
                        "If contributing new modules to agy_template, read CONTRIBUTING_MODULES.md."
                    )
                }
            }
        ]
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        workspace_paths = payload.get("workspacePaths") or []
        cwd = os.environ.get("AGY_WORKSPACE_ROOT") or (workspace_paths[0] if workspace_paths else "") or payload.get("cwd") or ""
        root = Path(cwd) if cwd else None
        result = detect(root)
    except Exception:
        result = {}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
