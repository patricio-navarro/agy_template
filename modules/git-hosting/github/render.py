"""Dynamic renderer for GitHub Actions CI, PR template, and Dependabot."""

from __future__ import annotations

from typing import Any


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_guard_condition(guard_files: list[str]) -> str:
    if not guard_files:
        return "true"
    checks = [f'[ -f "{path}" ]' for path in guard_files]
    return " || ".join(checks)


def _render_ci_yml(ci_jobs: list[dict[str, Any]]) -> str:
    lines = [
        "name: CI",
        "",
        "on:",
        "  push:",
        "    branches: [main]",
        "  pull_request:",
        "    branches: [main]",
        "  workflow_dispatch:",
        "",
        "permissions:",
        "  contents: read",
        "",
        "concurrency:",
        "  group: ${{ github.workflow }}-${{ github.ref }}",
        "  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}",
        "",
        "jobs:",
    ]

    if not ci_jobs:
        lines.extend(
            [
                "  hygiene:",
                "    name: Repository Hygiene",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - name: Checkout repository",
                "        uses: actions/checkout@v4",
                "      - name: Verify no machine-local markdown links",
                "        run: |",
                "          if grep -rnE '\\]\\(file:///' . --include='*.md' --exclude-dir=.git; then",
                "            echo 'Machine-local file:/// links are forbidden in committed markdown.'",
                "            exit 1",
                "          fi",
            ]
        )
        return "\n".join(lines) + "\n"

    for job in ci_jobs:
        job_id = job["id"]
        job_name = job["name"]
        runtimes = job.get("runtimes") or {}
        caches = job.get("caches") or []
        guard_files = job.get("guard_files") or []
        steps = job.get("steps") or []

        lines.append(f"  {job_id}:")
        lines.append(f"    name: {_yaml_quote(job_name)}")
        lines.append("    runs-on: ubuntu-latest")
        lines.append("    steps:")
        lines.append("      - name: Checkout repository")
        lines.append("        uses: actions/checkout@v4")

        if "python" in runtimes:
            py_ver = runtimes["python"]
            lines.append(f"      - name: Set up Python {py_ver}")
            lines.append("        uses: actions/setup-python@v5")
            lines.append("        with:")
            lines.append(f"          python-version: {_yaml_quote(str(py_ver))}")

        if "node" in runtimes:
            node_ver = runtimes["node"]
            lines.append(f"      - name: Set up Node.js {node_ver}")
            lines.append("        uses: actions/setup-node@v4")
            lines.append("        with:")
            lines.append(f"          node-version: {_yaml_quote(str(node_ver))}")
            if "npm" in caches:
                lines.append("          cache: 'npm'")

        if "java" in runtimes:
            java_ver = runtimes["java"]
            lines.append(f"      - name: Set up Java {java_ver}")
            lines.append("        uses: actions/setup-java@v4")
            lines.append("        with:")
            lines.append("          distribution: 'temurin'")
            lines.append(f"          java-version: {_yaml_quote(str(java_ver))}")

        guard_cond = _render_guard_condition(guard_files)
        for step in steps:
            step_name = step["name"]
            step_run = step["run"]
            lines.append(f"      - name: {_yaml_quote(step_name)}")
            lines.append("        run: |")
            if guard_files:
                lines.append(f"          if {guard_cond}; then")
                lines.append(f"            {step_run}")
                lines.append("          else")
                lines.append(
                    f"            echo {_yaml_quote('No manifest found yet (' + ', '.join(guard_files) + '); skipping step on Day-0 harness.')}"
                )
                lines.append("          fi")
            else:
                lines.append(f"          {step_run}")

    return "\n".join(lines) + "\n"


def _render_pr_template(context: dict[str, Any]) -> str:
    ticket_syntax = context.get("pr_ticket_syntax") or "Closes #<issue-number>"
    checklist_items = context.get("pr_checklist") or []

    base_items = [
        f"Linked to tracked ticket (`{ticket_syntax}`)",
        "Follows `AGENTS.md` and `.agents/skills/engineering-philosophy/SKILL.md` (**DRY**, **KISS**, **YAGNI**, **CAZZ**)",
        "Completed right-sized review gate (`.agents/skills/pr-quality-gate/SKILL.md`) with independent final PR approval",
    ]
    all_items = base_items + [item for item in checklist_items if item not in base_items]

    lines = [
        "## Summary",
        "<!-- Brief description of the changes introduced by this PR -->",
        "",
        f"Ticket: {ticket_syntax}",
        "",
        "## Changes",
        "- ",
        "",
        "## Verification & Quality Checklist",
    ]
    for item in all_items:
        lines.append(f"- [ ] {item}")
    return "\n".join(lines) + "\n"


def _render_dependabot(ecosystems: list[str]) -> str:
    lines = [
        "version: 2",
        "updates:",
    ]
    for eco in ecosystems:
        lines.extend(
            [
                f"  - package-ecosystem: {_yaml_quote(eco)}",
                '    directory: "/"',
                "    schedule:",
                '      interval: "weekly"',
                "    open-pull-requests-limit: 5",
            ]
        )
    return "\n".join(lines) + "\n"


def render_files(context: dict[str, Any]) -> dict[str, str]:
    ci_jobs = context.get("ci_jobs") or []
    ecosystems = context.get("dependabot_ecosystems") or ["github-actions"]
    return {
        ".github/workflows/ci.yml": _render_ci_yml(ci_jobs),
        ".github/pull_request_template.md": _render_pr_template(context),
        ".github/dependabot.yml": _render_dependabot(ecosystems),
    }
