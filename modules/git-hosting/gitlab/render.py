"""Dynamic renderer for GitLab CI (.gitlab-ci.yml) and Merge Request template."""

from __future__ import annotations

import shlex
from typing import Any

_CACHE_MAP: dict[str, tuple[tuple[str, str], str]] = {
    "pip": (("PIP_CACHE_DIR", "$CI_PROJECT_DIR/.cache/pip"), ".cache/pip/"),
    "npm": (("NPM_CONFIG_CACHE", "$CI_PROJECT_DIR/.npm"), ".npm/"),
    "gomod": (("GOPATH", "$CI_PROJECT_DIR/.go"), ".go/pkg/mod/"),
    "go": (("GOPATH", "$CI_PROJECT_DIR/.go"), ".go/pkg/mod/"),
    "maven": (("MAVEN_OPTS", "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"), ".m2/repository/"),
    "gradle": (("GRADLE_USER_HOME", "$CI_PROJECT_DIR/.gradle"), ".gradle/"),
}

_RUNTIME_IMAGES: dict[str, str] = {
    "python": "python:{ver}-slim",
    "node": "node:{ver}-slim",
    "go": "golang:{ver}",
    "java": "eclipse-temurin:{ver}-jdk",
}


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _resolve_docker_image(job: dict[str, Any]) -> str:
    explicit = job.get("docker_image")
    if explicit:
        return str(explicit)
    runtimes = job.get("runtimes") or {}
    for runtime, template in _RUNTIME_IMAGES.items():
        if runtime in runtimes:
            return template.format(ver=runtimes[runtime])
    return "ubuntu:24.04"


def _collect_job_caches(caches: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    env_vars: list[tuple[str, str]] = []
    cache_paths: list[str] = []
    seen_vars: set[str] = set()
    seen_paths: set[str] = set()

    for cache_key in caches:
        entry = _CACHE_MAP.get(cache_key)
        if entry is None:
            continue
        (var_name, var_val), cache_path = entry
        if var_name not in seen_vars:
            seen_vars.add(var_name)
            env_vars.append((var_name, var_val))
        if cache_path not in seen_paths:
            seen_paths.add(cache_path)
            cache_paths.append(cache_path)

    return env_vars, cache_paths


def _append_indented_command(lines: list[str], cmd: str, indent: str) -> None:
    for line in cmd.splitlines() or [""]:
        lines.append(f"{indent}{line}" if line else "")


def _render_script_block(job: dict[str, Any], docker_image: str) -> list[str]:
    runtimes = job.get("runtimes") or {}
    guard_files = job.get("guard_files") or []
    steps = job.get("steps") or []

    body_commands: list[str] = []
    if "node" in runtimes and "java" in runtimes and "node" not in docker_image:
        node_major = str(runtimes["node"]).split(".", 1)[0]
        if not node_major.isdigit():
            node_major = "22"
        body_commands.append(
            "if ! command -v node >/dev/null 2>&1; then "
            "apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && "
            f"curl -fsSL https://deb.nodesource.com/setup_{node_major}.x | bash - && "
            "apt-get install -y --no-install-recommends nodejs; "
            "fi"
        )
    for step in steps:
        run_cmd = str(step.get("run") or "").strip()
        if run_cmd:
            body_commands.append(run_cmd)
    if not body_commands:
        body_commands.append(":")

    lines = ["  script:"]
    if guard_files:
        guard_cond = " || ".join(f"[ -f {shlex.quote(path)} ]" for path in guard_files)
        skip_msg = shlex.quote(
            f"No manifest found yet ({', '.join(guard_files)}); skipping step on Day-0 harness."
        )
        lines.append("    - |")
        lines.append(f"      if {guard_cond}; then")
        for cmd in body_commands:
            _append_indented_command(lines, cmd, "        ")
        lines.append("      else")
        lines.append(f"        echo {skip_msg}")
        lines.append("      fi")
    else:
        for cmd in body_commands:
            lines.append("    - |")
            _append_indented_command(lines, cmd, "      ")
    return lines


def _render_job(job: dict[str, Any]) -> list[str]:
    job_id = job["id"]
    job_name = " ".join(str(job.get("name") or job_id).splitlines())
    docker_image = _resolve_docker_image(job)
    env_vars, cache_paths = _collect_job_caches(job.get("caches") or [])

    lines = [
        f"# {job_name}",
        f"{job_id}:",
        "  stage: test",
        f"  image: {docker_image}",
    ]
    if env_vars:
        lines.append("  variables:")
        for var_name, var_val in env_vars:
            lines.append(f"    {var_name}: {_yaml_quote(var_val)}")
    if cache_paths:
        lines.extend(
            [
                "  cache:",
                '    key: "$CI_JOB_NAME-$CI_COMMIT_REF_SLUG"',
                "    paths:",
            ]
        )
        for cache_path in cache_paths:
            lines.append(f"      - {cache_path}")

    lines.extend(_render_script_block(job, docker_image))
    return lines


def _render_gitlab_ci_yml(ci_jobs: list[dict[str, Any]]) -> str:
    lines = [
        "stages:",
        "  - test",
        "",
        "workflow:",
        "  rules:",
        '    - if: $CI_PIPELINE_SOURCE == "merge_request_event"',
        "    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS",
        "      when: never",
        "    - if: $CI_COMMIT_BRANCH",
        "",
        "default:",
        "  interruptible: true",
    ]

    if not ci_jobs:
        lines.extend(
            [
                "",
                "# Repository Hygiene",
                "hygiene:",
                "  stage: test",
                "  image: python:3.12-slim",
                "  script:",
                "    - |",
                "      if grep -rnE '\\]\\(file:///' . --include='*.md' --exclude-dir=.git; then",
                "        echo 'Machine-local file:/// links are forbidden in committed markdown.'",
                "        exit 1",
                "      fi",
            ]
        )
        return "\n".join(lines) + "\n"

    for job in ci_jobs:
        lines.append("")
        lines.extend(_render_job(job))

    return "\n".join(lines) + "\n"


def _render_mr_template(context: dict[str, Any]) -> str:
    ticket_syntax = context.get("pr_ticket_syntax") or "Closes #<issue-number>"
    checklist_items = context.get("pr_checklist") or []

    base_items = [
        f"Linked to tracked ticket (`{ticket_syntax}`)",
        "Follows `AGENTS.md` and `.agents/skills/engineering-philosophy/SKILL.md` (**DRY**, **KISS**, **YAGNI**, **CAZZ**)",
        "Completed right-sized review gate (`.agents/skills/pr-quality-gate/SKILL.md`) with independent final MR approval",
    ]
    all_items = list(dict.fromkeys([*base_items, *checklist_items]))

    lines = [
        "## Summary",
        "<!-- Brief description of the changes introduced by this MR -->",
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
    """Generate .gitlab-ci.yml and .gitlab/merge_request_templates/Default.md."""
    ci_jobs = context.get("ci_jobs") or []
    return {
        ".gitlab-ci.yml": _render_gitlab_ci_yml(ci_jobs),
        ".gitlab/merge_request_templates/Default.md": _render_mr_template(context),
    }
