"""Dynamic renderer for Bitbucket Pipelines and PR template."""

from __future__ import annotations

from typing import Any


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_step_block(job: dict[str, Any], indent: str) -> list[str]:
    job_name = job["name"]
    docker_image = job.get("docker_image") or "ubuntu:24.04"
    caches = job.get("caches") or []
    guard_files = job.get("guard_files") or []
    runtimes = job.get("runtimes") or {}
    steps = job.get("steps") or []

    lines = [
        f"{indent}- step:",
        f"{indent}    name: {_yaml_quote(job_name)}",
        f"{indent}    image: {docker_image}",
    ]
    if caches:
        lines.append(f"{indent}    caches:")
        for cache in caches:
            lines.append(f"{indent}      - {cache}")
    lines.append(f"{indent}    script:")

    body_commands: list[str] = []
    if "node" in runtimes and "java" in runtimes and "node" not in docker_image:
        body_commands.append(
            "if ! command -v node >/dev/null 2>&1; then "
            "apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && "
            "curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && "
            "apt-get install -y --no-install-recommends nodejs; "
            "fi"
        )
    for step in steps:
        body_commands.append(step["run"])

    if guard_files:
        guard_cond = " || ".join(f'[ -f "{path}" ]' for path in guard_files)
        lines.append(f"{indent}      - |")
        lines.append(f"{indent}        if {guard_cond}; then")
        for cmd in body_commands:
            lines.append(f"{indent}          {cmd}")
        lines.append(f"{indent}        else")
        lines.append(
            f"{indent}          echo {_yaml_quote('No manifest found yet (' + ', '.join(guard_files) + '); skipping step on Day-0 harness.')}"
        )
        lines.append(f"{indent}        fi")
    else:
        for cmd in body_commands:
            lines.append(f"{indent}      - {cmd}")
    return lines


def _render_pipelines_yml(ci_jobs: list[dict[str, Any]]) -> str:
    if not ci_jobs:
        pipeline_body = [
            "    - step:",
            '        name: "Repository Hygiene"',
            "        image: python:3.12-slim",
            "        script:",
            "          - |",
            "            if grep -rnE '\\]\\(file:///' . --include='*.md' --exclude-dir=.git; then",
            "              echo 'Machine-local file:/// links are forbidden in committed markdown.'",
            "              exit 1",
            "            fi",
        ]
    elif len(ci_jobs) == 1:
        pipeline_body = _render_step_block(ci_jobs[0], "    ")
    else:
        pipeline_body = ["    - parallel:"]
        for job in ci_jobs:
            pipeline_body.extend(_render_step_block(job, "        "))

    lines = [
        "pipelines:",
        "  default:",
        *pipeline_body,
        "  branches:",
        "    main:",
        *pipeline_body,
        "  pull-requests:",
        "    '**':",
        *pipeline_body,
    ]
    return "\n".join(lines) + "\n"


def _render_pr_template(context: dict[str, Any]) -> str:
    ticket_syntax = context.get("pr_ticket_syntax") or "PROJ-<num>"
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


def render_files(context: dict[str, Any]) -> dict[str, str]:
    ci_jobs = context.get("ci_jobs") or []
    return {
        "bitbucket-pipelines.yml": _render_pipelines_yml(ci_jobs),
        ".bitbucket/pull_request_template.md": _render_pr_template(context),
    }
