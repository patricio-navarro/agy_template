#!/usr/bin/env python3
"""Modular initializer, catalog validator, and workspace pruner for agy_template."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / "modules"
CORE_DIR = REPO_ROOT / "core"

CORE_GITIGNORE_BASE = [
    ".DS_Store",
    ".env",
    ".env.*",
    "!.env.example",
]

TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".sh",
    ".py",
    ".rules",
    ".toml",
    ".tmpl",
    ".gitignore",
    ".gcloudignore",
}

EXECUTABLE_BASENAMES = {"pre-commit", "commit-msg", "pre-push"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "my-app"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_text(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def load_catalog(modules_dir: Path = MODULES_DIR) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    categories_path = modules_dir / "categories.json"
    if not categories_path.is_file():
        raise FileNotFoundError(f"Missing categories catalog: {categories_path}")

    categories_data = load_json(categories_path)
    categories: list[dict[str, Any]] = categories_data.get("categories") or []
    catalog: dict[str, dict[str, dict[str, Any]]] = {cat["id"]: {} for cat in categories}

    for cat in categories:
        cat_id = cat["id"]
        cat_dir = modules_dir / cat_id
        if not cat_dir.is_dir():
            continue
        for mod_dir in sorted(cat_dir.iterdir()):
            if not mod_dir.is_dir():
                continue
            manifest_path = mod_dir / "module.json"
            if not manifest_path.is_file():
                continue
            mod_data = load_json(manifest_path)
            mod_data["_path"] = str(mod_dir)
            catalog[cat_id][mod_data["id"]] = mod_data

    return categories, catalog


def parse_skill_frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{skill_md}: missing YAML frontmatter block")
    block = match.group(1)
    fields: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    for line in block.splitlines():
        key_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if key_match and not line.startswith((" ", "\t")):
            if current_key is not None:
                fields[current_key] = " ".join(buf).strip().strip("\"'")
            current_key = key_match.group(1)
            val = key_match.group(2).strip()
            buf = [] if val in (">-", ">", "|", "|-") else [val]
        elif current_key is not None:
            buf.append(line.strip())

    if current_key is not None:
        fields[current_key] = " ".join(buf).strip().strip("\"'")
    return fields


def validate_shell_syntax(path: Path, errors: list[str]) -> None:
    proc = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        errors.append(f"Shell syntax error in {path}: {proc.stderr.strip()}")


def validate_guard_rules_file(path: Path, errors: list[str]) -> None:
    try:
        data = load_json(path)
    except Exception as exc:
        errors.append(f"Invalid JSON in {path}: {exc}")
        return
    rules = data.get("command_rules")
    if not isinstance(rules, list):
        errors.append(f"{path}: 'command_rules' must be a list")
        return
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"{path}: rule[{idx}] must be an object")
            continue
        for req in ("id", "pattern", "decision", "reason"):
            if not rule.get(req):
                errors.append(f"{path}: rule[{idx}] missing '{req}'")
        if rule.get("decision") not in ("allow", "ask", "force_ask", "deny"):
            errors.append(f"{path}: rule[{idx}] invalid decision '{rule.get('decision')}'")
        for regex_key in ("pattern", "exclude_pattern"):
            if rule.get(regex_key):
                try:
                    re.compile(rule[regex_key])
                except re.error as exc:
                    errors.append(f"{path}: rule[{idx}] invalid regex in '{regex_key}': {exc}")


def validate_catalog(repo_root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    modules_dir = repo_root / "modules"
    core_dir = repo_root / "core"

    try:
        categories, catalog = load_catalog(modules_dir)
    except Exception as exc:
        return [str(exc)]

    valid_selections = {"single_optional", "multi_optional", "single_required", "multi_required"}
    for cat in categories:
        for req in ("id", "label", "selection"):
            if not cat.get(req):
                errors.append(f"categories.json: category missing '{req}'")
        if cat.get("selection") not in valid_selections:
            errors.append(f"categories.json: invalid selection '{cat.get('selection')}' for '{cat.get('id')}'")

    for cat_id, mods in catalog.items():
        for mod_id, mod in mods.items():
            mod_dir = Path(mod["_path"])
            for req in ("id", "category", "name", "description"):
                if not mod.get(req):
                    errors.append(f"{mod_dir / 'module.json'}: missing '{req}'")
            if mod.get("id") != mod_dir.name:
                errors.append(f"{mod_dir / 'module.json'}: id '{mod.get('id')}' != dir '{mod_dir.name}'")
            if mod.get("category") != cat_id:
                errors.append(f"{mod_dir / 'module.json'}: category '{mod.get('category')}' != '{cat_id}'")

            for param in mod.get("parameters") or []:
                if not param.get("name"):
                    errors.append(f"{mod_dir / 'module.json'}: parameter missing 'name'")
                if param.get("regex"):
                    try:
                        re.compile(param["regex"])
                    except re.error as exc:
                        errors.append(f"{mod_dir / 'module.json'}: invalid parameter regex: {exc}")

            guard_file = mod_dir / "hooks" / "guard_rules.json"
            if guard_file.is_file():
                validate_guard_rules_file(guard_file, errors)

            commit_msg_file = mod_dir / "hooks" / "commit-msg.json"
            if commit_msg_file.is_file():
                try:
                    cm = load_json(commit_msg_file)
                    if cm.get("header_regex"):
                        re.compile(cm["header_regex"])
                    if cm.get("ticket_regex"):
                        re.compile(cm["ticket_regex"])
                except Exception as exc:
                    errors.append(f"{commit_msg_file}: invalid commit-msg config: {exc}")

            render_py = mod_dir / "render.py"
            if render_py.is_file():
                try:
                    spec = importlib.util.spec_from_file_location(f"validate_{cat_id}_{mod_id}", render_py)
                    assert spec and spec.loader
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if not callable(getattr(module, "render_files", None)):
                        errors.append(f"{render_py}: missing callable render_files(context)")
                except Exception as exc:
                    errors.append(f"{render_py}: failed import: {exc}")

    # Validate all SKILL.md files (core, pre-init .agents, and modules)
    skill_files = (
        list((core_dir / "skills").glob("*/SKILL.md"))
        + list((repo_root / ".agents" / "skills").glob("*/SKILL.md"))
        + list(modules_dir.glob("*/*/skills/*/SKILL.md"))
    )
    for skill_md in skill_files:
        try:
            fm = parse_skill_frontmatter(skill_md)
            name = fm.get("name", "")
            desc = fm.get("description", "")
            if not name or not re.match(r"^[a-z0-9-]+$", name):
                errors.append(f"{skill_md}: frontmatter 'name' must be lowercase hyphenated (got '{name}')")
            if not desc:
                errors.append(f"{skill_md}: frontmatter 'description' must be non-empty")
        except Exception as exc:
            errors.append(str(exc))

    # Validate core/pre-init guard rules & hook configs
    for gr in [
        core_dir / "hooks" / "guard_rules.core.json",
        repo_root / ".agents" / "hooks" / "guard_rules.json",
    ]:
        if gr.is_file():
            validate_guard_rules_file(gr, errors)
        else:
            errors.append(f"Missing required guard rules file: {gr}")

    for json_file in [
        core_dir / "hooks" / "hooks.template.json",
        repo_root / ".agents" / "hooks.json",
    ]:
        try:
            load_json(json_file)
        except Exception as exc:
            errors.append(f"Invalid JSON in {json_file}: {exc}")

    # Validate shell script syntax
    shell_targets = (
        list((core_dir / "githooks").glob("*"))
        + list(modules_dir.glob("**/*.sh"))
    )
    for sh_path in shell_targets:
        if sh_path.is_file() and sh_path.suffix != ".json":
            validate_shell_syntax(sh_path, errors)

    return errors


def substitute_placeholders(text: str, replacements: dict[str, str]) -> str:
    result = text
    for key, value in replacements.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def copy_with_substitutions(
    src_dir: Path,
    dst_dir: Path,
    replacements: dict[str, str],
) -> None:
    if not src_dir.is_dir():
        return
    for item in src_dir.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src_dir)
        target = dst_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        src_mode = item.stat().st_mode
        is_exec = bool(src_mode & stat.S_IXUSR) or item.suffix == ".sh" or item.name in EXECUTABLE_BASENAMES
        if item.suffix.lower() in TEXT_EXTENSIONS or item.name in EXECUTABLE_BASENAMES or item.name.startswith("."):
            content = item.read_text(encoding="utf-8")
            write_text(target, substitute_placeholders(content, replacements), executable=is_exec)
        else:
            shutil.copy2(item, target)
            if is_exec:
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def parse_param_overrides(raw_params: list[str], jira_key: str | None) -> dict[str, str]:
    params: dict[str, str] = {}
    for entry in raw_params:
        if "=" not in entry:
            raise ValueError(f"Invalid --param '{entry}'. Expected KEY=VALUE.")
        key, value = entry.split("=", 1)
        params[key.strip()] = value.strip()
    if jira_key:
        params["JIRA_PROJECT_KEY"] = jira_key.strip()
    return params


def interactive_prompt(
    categories: list[dict[str, Any]],
    catalog: dict[str, dict[str, dict[str, Any]]],
    initial_project_name: str,
    initial_selections: dict[str, list[str]],
    initial_params: dict[str, str],
) -> tuple[str, dict[str, list[str]], dict[str, str]]:
    print("\n=== Antigravity Template Initializer (agy_template) ===\n")
    entered_name = input(f"Project name [{initial_project_name}]: ").strip()
    project_name = entered_name or initial_project_name

    selections: dict[str, list[str]] = {}
    for cat in categories:
        cat_id = cat["id"]
        mods = list(catalog.get(cat_id, {}).values())
        sel_mode = cat["selection"]

        if cat_id in initial_selections:
            selections[cat_id] = initial_selections[cat_id]
            continue

        print(f"\n[{cat['label']}] {cat['description']}")
        if sel_mode in ("single_optional", "multi_optional"):
            print("  0) none")
        for idx, mod in enumerate(mods, start=1):
            print(f"  {idx}) {mod['id']} — {mod['name']}")

        if sel_mode == "multi_optional":
            raw = input("Select comma-separated numbers or IDs [0]: ").strip()
            if not raw or raw == "0" or raw.lower() == "none":
                selections[cat_id] = []
            else:
                chosen: list[str] = []
                for token in [t.strip() for t in raw.split(",") if t.strip()]:
                    if token.isdigit():
                        pos = int(token)
                        if 1 <= pos <= len(mods):
                            chosen.append(mods[pos - 1]["id"])
                    elif token in catalog[cat_id]:
                        chosen.append(token)
                    else:
                        raise ValueError(f"Invalid selection '{token}' for category '{cat_id}'")
                selections[cat_id] = list(dict.fromkeys(chosen))
        else:
            default_id = str(cat.get("default") or "none")
            default_display = "0" if default_id == "none" else default_id
            raw = input(f"Select option [{default_display}]: ").strip()
            if not raw:
                selections[cat_id] = [] if default_id == "none" else [default_id]
            elif raw == "0" or raw.lower() == "none":
                if sel_mode == "single_required":
                    raise ValueError(f"Category '{cat_id}' is required and cannot be 'none'.")
                selections[cat_id] = []
            elif raw.isdigit():
                pos = int(raw)
                if not (1 <= pos <= len(mods)):
                    raise ValueError(f"Invalid option number '{raw}' for category '{cat_id}'")
                selections[cat_id] = [mods[pos - 1]["id"]]
            elif raw in catalog[cat_id]:
                selections[cat_id] = [raw]
            else:
                raise ValueError(f"Invalid selection '{raw}' for category '{cat_id}'")

    params = dict(initial_params)
    for cat in categories:
        for mod_id in selections.get(cat["id"], []):
            mod = catalog[cat["id"]][mod_id]
            for param in mod.get("parameters") or []:
                pname = param["name"]
                if pname in params:
                    continue
                default_val = str(param.get("default") or "")
                entered = input(f"\nParameter {pname} ({param.get('description', '')}) [{default_val}]: ").strip()
                params[pname] = entered or default_val

    return project_name, selections, params


def normalize_selections(
    categories: list[dict[str, Any]],
    catalog: dict[str, dict[str, dict[str, Any]]],
    raw_selections: dict[str, list[str]],
    params: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    selected_modules: list[dict[str, Any]] = []
    resolved_params = dict(params)

    for cat in categories:
        cat_id = cat["id"]
        sel_mode = cat["selection"]
        chosen_ids = raw_selections.get(cat_id)
        if chosen_ids is None:
            default_val = cat.get("default")
            if isinstance(default_val, list):
                chosen_ids = list(default_val)
            elif default_val and default_val != "none":
                chosen_ids = [str(default_val)]
            else:
                chosen_ids = []

        if sel_mode in ("single_optional", "single_required") and len(chosen_ids) > 1:
            raise ValueError(f"Category '{cat_id}' allows at most 1 module; got {chosen_ids}")
        if sel_mode in ("single_required", "multi_required") and len(chosen_ids) == 0:
            raise ValueError(f"Category '{cat_id}' requires at least 1 module.")

        for mod_id in chosen_ids:
            if mod_id not in catalog.get(cat_id, {}):
                available = ", ".join(sorted(catalog.get(cat_id, {}).keys()))
                raise ValueError(f"Unknown module '{mod_id}' in category '{cat_id}'. Available: {available}")
            mod = catalog[cat_id][mod_id]
            selected_modules.append(mod)
            for param in mod.get("parameters") or []:
                pname = param["name"]
                val = resolved_params.get(pname) or str(param.get("default") or "")
                regex = param.get("regex")
                if regex and not re.match(regex, val):
                    raise ValueError(f"Parameter '{pname}' value '{val}' does not match required pattern '{regex}'.")
                resolved_params[pname] = val

    return selected_modules, resolved_params


def stage_workspace(
    stage_dir: Path,
    project_name: str,
    project_slug: str,
    categories: list[dict[str, Any]],
    selected_modules: list[dict[str, Any]],
    resolved_params: dict[str, str],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    core_dir = repo_root / "core"

    # Resolve tracker & git conventions first so replacements include them everywhere
    branch_convention = "feature/<ticket-id>-<short-slug> or fix/<ticket-id>-<short-slug>"
    pr_ticket_syntax = "#<id>"
    for mod in selected_modules:
        if mod["category"] == "issue-tracker":
            branch_convention = mod.get("branch_convention") or branch_convention
            pr_ticket_syntax = mod.get("pr_ticket_syntax") or pr_ticket_syntax

    replacements: dict[str, str] = {
        "PROJECT_NAME": project_name,
        "PROJECT_SLUG": project_slug,
        **resolved_params,
    }
    branch_convention = substitute_placeholders(branch_convention, replacements)
    pr_ticket_syntax = substitute_placeholders(pr_ticket_syntax, replacements)
    replacements["BRANCH_CONVENTION"] = branch_convention
    replacements["PR_TICKET_SYNTAX"] = pr_ticket_syntax

    # 1. Copy core skills, hooks, githooks, and core docs/files
    copy_with_substitutions(core_dir / "skills", stage_dir / ".agents" / "skills", replacements)
    copy_with_substitutions(core_dir / "githooks", stage_dir / ".githooks", replacements)
    copy_with_substitutions(core_dir / "files", stage_dir, replacements)

    pre_tool_guard_src = core_dir / "hooks" / "pre_tool_guard.py"
    write_text(
        stage_dir / ".agents" / "hooks" / "pre_tool_guard.py",
        pre_tool_guard_src.read_text(encoding="utf-8"),
        executable=True,
    )
    hooks_tmpl_src = core_dir / "hooks" / "hooks.template.json"
    write_text(
        stage_dir / ".agents" / "hooks.json",
        hooks_tmpl_src.read_text(encoding="utf-8"),
    )

    guard_rules_data = load_json(core_dir / "hooks" / "guard_rules.core.json")
    command_rules: list[dict[str, Any]] = list(guard_rules_data.get("command_rules") or [])

    mcp_servers: dict[str, Any] = {}
    verification_commands: list[str] = []
    evaluators: list[dict[str, str]] = []
    concurrency_locks: list[str] = []
    pr_checklist: list[str] = []
    agents_md_rules: list[str] = []
    gitignore_lines: list[str] = list(CORE_GITIGNORE_BASE)
    env_example_lines: list[str] = [f"# Environment variables for {project_name} ({project_slug})"]
    dependabot_ecosystems: list[str] = []
    ci_jobs_by_key: dict[str, dict[str, Any]] = {}
    renderers: list[Path] = []

    # 2. Apply selected modules
    for mod in selected_modules:
        mod_dir = Path(mod["_path"])
        copy_with_substitutions(mod_dir / "skills", stage_dir / ".agents" / "skills", replacements)
        copy_with_substitutions(mod_dir / "files", stage_dir, replacements)

        # Hooks
        mod_guard = mod_dir / "hooks" / "guard_rules.json"
        if mod_guard.is_file():
            mod_rules = load_json(mod_guard).get("command_rules") or []
            command_rules.extend(mod_rules)

        copy_with_substitutions(
            mod_dir / "hooks" / "pre-commit.d",
            stage_dir / ".githooks" / "pre-commit.d",
            replacements,
        )
        copy_with_substitutions(
            mod_dir / "hooks" / "pre-push.d",
            stage_dir / ".githooks" / "pre-push.d",
            replacements,
        )
        commit_msg_cfg = mod_dir / "hooks" / "commit-msg.json"
        if commit_msg_cfg.is_file():
            write_text(
                stage_dir / ".githooks" / "commit-msg.json",
                substitute_placeholders(commit_msg_cfg.read_text(encoding="utf-8"), replacements),
            )

        # MCP fragments
        mcp_frag = mod_dir / "mcp_config.fragment.json"
        if mcp_frag.is_file():
            frag_json = json.loads(substitute_placeholders(mcp_frag.read_text(encoding="utf-8"), replacements))
            mcp_servers.update(frag_json.get("mcpServers") or {})

        # Metadata aggregation
        for cmd in mod.get("verification_commands") or []:
            c = substitute_placeholders(cmd, replacements)
            if c not in verification_commands:
                verification_commands.append(c)

        for ev in mod.get("evaluators") or []:
            evaluators.append(
                {
                    "name": substitute_placeholders(ev["name"], replacements),
                    "scope": substitute_placeholders(ev["scope"], replacements),
                }
            )

        for lock in mod.get("single_concurrency_locks") or []:
            l_str = substitute_placeholders(lock, replacements)
            if l_str not in concurrency_locks:
                concurrency_locks.append(l_str)

        for item in mod.get("pr_checklist") or []:
            c_item = substitute_placeholders(item, replacements)
            if c_item not in pr_checklist:
                pr_checklist.append(c_item)

        for rule in mod.get("agents_md_rules") or []:
            r_str = substitute_placeholders(rule, replacements)
            if r_str not in agents_md_rules:
                agents_md_rules.append(r_str)

        for line in mod.get("gitignore") or []:
            if line not in gitignore_lines:
                gitignore_lines.append(line)

        mod_env = mod.get("env_example") or []
        if mod_env:
            env_example_lines.append("")
            for line in mod_env:
                env_example_lines.append(substitute_placeholders(line, replacements))

        for eco in mod.get("dependabot_ecosystems") or []:
            if eco not in dependabot_ecosystems:
                dependabot_ecosystems.append(eco)

        for job in mod.get("ci_jobs") or []:
            dedupe_key = job.get("dedupe_key") or job["id"]
            if dedupe_key not in ci_jobs_by_key:
                ci_jobs_by_key[dedupe_key] = job

        render_py = mod_dir / "render.py"
        if render_py.is_file():
            renderers.append(render_py)

    # Write merged guard_rules.json
    write_text(
        stage_dir / ".agents" / "hooks" / "guard_rules.json",
        json.dumps({"command_rules": command_rules}, indent=2) + "\n",
    )

    # Write mcp_config.example.json if any fragments existed
    if mcp_servers:
        write_text(
            stage_dir / ".agents" / "mcp_config.example.json",
            json.dumps({"mcpServers": mcp_servers}, indent=2) + "\n",
        )

    # Write .gitignore and .env.example
    write_text(stage_dir / ".gitignore", "\n".join(gitignore_lines) + "\n")
    write_text(stage_dir / ".env.example", "\n".join(env_example_lines) + "\n")

    # Build tables & lists for templates
    selected_by_cat: dict[str, list[str]] = {cat["id"]: [] for cat in categories}
    for mod in selected_modules:
        selected_by_cat.setdefault(mod["category"], []).append(f"`{mod['id']}` ({mod['name']})")

    table_lines = ["| Category | Active Module(s) |", "| :--- | :--- |"]
    for cat in categories:
        entries = selected_by_cat.get(cat["id"]) or ["*none*"]
        table_lines.append(f"| **{cat['label']}** | {', '.join(entries)} |")
    selected_modules_table = "\n".join(table_lines)

    if verification_commands:
        verif_md = "\n".join(f"- `{cmd}`" for cmd in verification_commands)
    else:
        verif_md = "- *No runtime-specific verification commands configured yet.*"

    if evaluators:
        eval_md = "\n".join(f"- **{ev['name']}:** {ev['scope']}" for ev in evaluators)
    else:
        eval_md = "- **General Architecture & Security Evaluator:** Audit changes against **DRY**, **KISS**, **YAGNI**, **CAZZ**, and tests."

    if concurrency_locks:
        locks_md = "\n".join(f"- {lock}" for lock in concurrency_locks)
    else:
        locks_md = "- *No single-concurrency hardware or emulator locks active.*"

    if resolved_params:
        param_lines = ["", "## Parameters", ""]
        for k, v in sorted(resolved_params.items()):
            param_lines.append(f"- `{k}` = `{v}`")
        params_section = "\n".join(param_lines)
    else:
        params_section = ""

    module_rules_block = "\n".join(f"- {rule}" for rule in agents_md_rules)

    template_replacements = {
        **replacements,
        "SELECTED_MODULES_TABLE": selected_modules_table,
        "VERIFICATION_COMMANDS_LIST": verif_md,
        "DOMAIN_EVALUATORS_LIST": eval_md,
        "CONCURRENCY_LOCKS_LIST": locks_md,
        "PARAMETERS_SECTION": params_section,
        "MODULE_RULES": module_rules_block,
    }

    for tmpl_name, out_rel in [
        ("AGENTS.md.tmpl", Path("AGENTS.md")),
        ("stack-profile.md.tmpl", Path(".agents/stack-profile.md")),
        ("README.project.md.tmpl", Path("README.md")),
    ]:
        tmpl_text = (core_dir / "templates" / tmpl_name).read_text(encoding="utf-8")
        write_text(stage_dir / out_rel, substitute_placeholders(tmpl_text, template_replacements))

    # Execute module renderers (e.g. GitHub Actions, Bitbucket Pipelines)
    ci_jobs = list(ci_jobs_by_key.values())
    render_context = {
        "project_name": project_name,
        "project_slug": project_slug,
        "params": resolved_params,
        "ci_jobs": ci_jobs,
        "dependabot_ecosystems": dependabot_ecosystems,
        "pr_checklist": pr_checklist,
        "pr_ticket_syntax": pr_ticket_syntax,
        "branch_convention": branch_convention,
    }
    for idx, render_py in enumerate(renderers):
        spec = importlib.util.spec_from_file_location(f"agy_render_{idx}", render_py)
        assert spec and spec.loader
        mod_py = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod_py)
        rendered_map = mod_py.render_files(render_context)
        for rel_path, content in rendered_map.items():
            write_text(stage_dir / rel_path, substitute_placeholders(content, replacements))

    # Manifest
    manifest = {
        "schema_version": 1,
        "template_source": "agy_template",
        "initialized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_name": project_name,
        "project_slug": project_slug,
        "selected_modules": {
            cat["id"]: [m["id"] for m in selected_modules if m["category"] == cat["id"]]
            for cat in categories
        },
        "parameters": resolved_params,
        "active_skills": sorted(p.parent.name for p in (stage_dir / ".agents" / "skills").glob("*/SKILL.md")),
    }
    write_text(stage_dir / ".agy-manifest.json", json.dumps(manifest, indent=2) + "\n")

    # Validate staged artifacts before touching target
    agents_size = (stage_dir / "AGENTS.md").stat().st_size
    if agents_size >= 8000:
        raise RuntimeError(f"Generated AGENTS.md is too large ({agents_size} bytes >= 8000).")

    for jf in stage_dir.rglob("*.json"):
        load_json(jf)

    validation_errors: list[str] = []
    for shf in list(stage_dir.rglob("*.sh")) + list((stage_dir / ".githooks").glob("*")):
        if shf.is_file() and shf.suffix != ".json":
            validate_shell_syntax(shf, validation_errors)
    if validation_errors:
        raise RuntimeError("Staged script validation failed:\n" + "\n".join(validation_errors))

    return manifest


def prune_template_scaffolding(target_root: Path, keep_engine: bool) -> list[str]:
    removed: list[str] = []
    # Always prune stale git-hosting / template-specific dirs before copying rendered output
    always_clean = [
        target_root / ".github",
        target_root / ".bitbucket",
        target_root / "bitbucket-pipelines.yml",
    ]
    for path in always_clean:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path.relative_to(target_root)))
        elif path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(target_root)))

    if keep_engine:
        return removed

    prune_targets = [
        target_root / "modules",
        target_root / "core",
        target_root / "tests",
        target_root / "CONTRIBUTING_MODULES.md",
        target_root / ".agents" / "skills" / "template-initializer",
        target_root / ".agents" / "hooks" / "bootstrap_detector.py",
        target_root / "scripts" / "agy_init.py",
        target_root / "agy-init",
    ]
    for path in prune_targets:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path.relative_to(target_root)))
        elif path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(target_root)))

    # Prune unselected core/old skills & stale hooks in .agents before copy
    for stale_dir in [
        target_root / ".agents" / "skills",
        target_root / ".githooks",
    ]:
        if stale_dir.is_dir():
            shutil.rmtree(stale_dir)

    scripts_dir = target_root / "scripts"
    if scripts_dir.is_dir() and not any(scripts_dir.iterdir()):
        scripts_dir.rmdir()

    return removed


def copy_staged_to_target(stage_dir: Path, target_dir: Path) -> list[str]:
    written: list[str] = []
    for item in sorted(stage_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(stage_dir)
        dest = target_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        written.append(str(rel))
    return written


def build_arg_parser(categories: list[dict[str, Any]]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-init",
        description="Initialize agy_template for your stack and prune unused automations.",
    )
    parser.add_argument("--validate-catalog", action="store_true", help="Validate all modules, skills, hooks, and scripts.")
    parser.add_argument("--list-modules", action="store_true", help="List available categories, modules, and parameters.")
    parser.add_argument("--json", action="store_true", help="Output JSON (used with --list-modules).")
    parser.add_argument("--project-name", help="Human-readable project name (defaults to target directory name).")
    parser.add_argument("--project-slug", help="URL/service-safe slug (defaults to kebab-case of project name).")
    for cat in categories:
        cat_id = cat["id"]
        help_suffix = "comma-separated IDs or 'none'" if cat["selection"] == "multi_optional" else "module ID or 'none'"
        parser.add_argument(f"--{cat_id}", dest=f"cat_{cat_id}", help=f"{cat['label']} ({help_suffix})")
    parser.add_argument("--param", action="append", default=[], help="Module parameter override (KEY=VALUE). Repeatable.")
    parser.add_argument("--jira-key", help="Convenience alias for --param JIRA_PROJECT_KEY=<KEY>.")
    parser.add_argument("--config", help="Optional JSON file specifying project_name, modules, and parameters.")
    parser.add_argument("--output-dir", help="Optional target directory to write initialized harness without modifying template repo.")
    parser.add_argument("--keep-template-engine", action="store_true", help="Keep modules/, core/, and agy-init after init.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing or deleting files.")
    parser.add_argument("-y", "--yes", action="store_true", help="Run non-interactively without confirmation prompts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    categories, catalog = load_catalog(MODULES_DIR)
    parser = build_arg_parser(categories)
    args = parser.parse_args(argv)

    if args.validate_catalog:
        errors = validate_catalog(REPO_ROOT)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print(f"Catalog validation passed ({sum(len(m) for m in catalog.values())} modules across {len(categories)} categories).")
        return 0

    if args.list_modules:
        if args.json:
            payload = {
                "categories": categories,
                "modules": {
                    cat_id: [
                        {k: v for k, v in mod.items() if not k.startswith("_")}
                        for mod in mods.values()
                    ]
                    for cat_id, mods in catalog.items()
                },
            }
            print(json.dumps(payload, indent=2))
        else:
            for cat in categories:
                print(f"\n{cat['label']} (--{cat['id']}, {cat['selection']}):")
                for mod in catalog[cat["id"]].values():
                    print(f"  - {mod['id']}: {mod['name']} — {mod['description']}")
                    for p in mod.get("parameters") or []:
                        print(f"      param {p['name']} (default={p.get('default', '')}): {p.get('description', '')}")
        return 0

    target_dir = Path(args.output_dir).resolve() if args.output_dir else REPO_ROOT
    default_project_name = target_dir.name if target_dir.name != "agy_template" else "my-project"

    raw_selections: dict[str, list[str]] = {}
    params = parse_param_overrides(args.param, args.jira_key)
    project_name = args.project_name

    if args.config:
        cfg = load_json(Path(args.config))
        project_name = project_name or cfg.get("project_name")
        for cat_id, val in (cfg.get("modules") or {}).items():
            if isinstance(val, list):
                raw_selections[cat_id] = [v for v in val if v and v != "none"]
            elif val and val != "none":
                raw_selections[cat_id] = [str(val)]
            else:
                raw_selections[cat_id] = []
        for k, v in (cfg.get("parameters") or {}).items():
            params.setdefault(k, str(v))

    for cat in categories:
        cat_id = cat["id"]
        cli_val = getattr(args, f"cat_{cat_id}", None)
        if cli_val is not None:
            if cli_val.strip().lower() in ("", "none"):
                raw_selections[cat_id] = []
            else:
                raw_selections[cat_id] = [t.strip() for t in cli_val.split(",") if t.strip() and t.strip().lower() != "none"]

    needs_interactive = (
        not args.yes
        and not args.dry_run
        and not args.config
        and len(raw_selections) < len(categories)
    )

    if needs_interactive:
        if not sys.stdin.isatty():
            print(
                "Error: Non-interactive shell requires --yes (or --dry-run) when omitting interactive prompts.",
                file=sys.stderr,
            )
            return 2
        project_name, raw_selections, params = interactive_prompt(
            categories,
            catalog,
            project_name or default_project_name,
            raw_selections,
            params,
        )

    final_project_name = project_name or default_project_name
    final_project_slug = slugify(args.project_slug or final_project_name)

    try:
        selected_modules, resolved_params = normalize_selections(categories, catalog, raw_selections, params)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="agy_init_") as tmp:
        stage_dir = Path(tmp) / "workspace"
        stage_dir.mkdir(parents=True, exist_ok=True)
        manifest = stage_workspace(
            stage_dir,
            final_project_name,
            final_project_slug,
            categories,
            selected_modules,
            resolved_params,
            REPO_ROOT,
        )
        staged_files = sorted(str(p.relative_to(stage_dir)) for p in stage_dir.rglob("*") if p.is_file())

        if args.dry_run:
            summary = {
                "mode": "output-dir" if args.output_dir else "in-place",
                "target_dir": str(target_dir),
                "manifest": manifest,
                "files_to_write": staged_files,
                "would_prune_engine": not args.output_dir and not args.keep_template_engine,
            }
            print(json.dumps(summary, indent=2))
            return 0

        if args.output_dir:
            target_dir.mkdir(parents=True, exist_ok=True)
            license_src = REPO_ROOT / "LICENSE"
            if license_src.is_file() and not (target_dir / "LICENSE").exists():
                shutil.copy2(license_src, target_dir / "LICENSE")
        else:
            prune_template_scaffolding(target_dir, keep_engine=args.keep_template_engine)

        copy_staged_to_target(stage_dir, target_dir)

    if (target_dir / ".git").exists():
        subprocess.run(
            ["git", "-C", str(target_dir), "config", "core.hooksPath", ".githooks"],
            check=False,
            capture_output=True,
        )

    print(f"Initialized '{final_project_name}' ({final_project_slug}) at {target_dir}")
    print(f"Active skills ({len(manifest['active_skills'])}): {', '.join(manifest['active_skills'])}")
    print("Manifest written to .agy-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
