#!/usr/bin/env python3
"""Modular initializer, catalog validator, and workspace pruner for agy_template."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / "modules"
CORE_DIR = REPO_ROOT / "core"

MAX_AGENTS_MD_BYTES = 8000
EXEC_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

CORE_GITIGNORE_BASE = (
    ".DS_Store",
    ".env",
    ".env.*",
    "!.env.example",
)

TEXT_EXTENSIONS = frozenset({
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
})

EXECUTABLE_BASENAMES = frozenset({"pre-commit", "commit-msg", "pre-push"})
VALID_SELECTIONS = frozenset({"single_optional", "multi_optional", "single_required", "multi_required"})
VALID_DECISIONS = frozenset({"allow", "ask", "force_ask", "deny"})

SLUG_RE = re.compile(r"[^a-z0-9]+")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9-]+$")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
ENV_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
MERGED_BROWNFIELD_FILES = frozenset({".gitignore", ".env.example"})

PRUNE_ALWAYS_PATHS = (
    ".github",
    ".bitbucket",
    "bitbucket-pipelines.yml",
    ".gitlab",
    ".gitlab-ci.yml",
)

PRUNE_ENGINE_PATHS = (
    "modules",
    "core",
    "tests",
    "CONTRIBUTING_MODULES.md",
    ".agents/skills/template-initializer",
    ".agents/hooks/bootstrap_detector.py",
    "scripts/agy_init.py",
    "agy-init",
)


class InitError(Exception):
    """Domain or CLI error carrying a process exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """Declared parameter metadata for a module."""

    name: str
    description: str = ""
    default: str = ""
    regex: str | None = None


@dataclass(frozen=True, slots=True)
class CategorySpec:
    """Category rule from modules/categories.json."""

    id: str
    label: str
    description: str
    selection: str
    default: str | tuple[str, ...] = "none"

    @property
    def allows_multiple(self) -> bool:
        return self.selection in ("multi_optional", "multi_required")

    @property
    def is_required(self) -> bool:
        return self.selection in ("single_required", "multi_required")


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """Loaded stack module definition."""

    id: str
    category: str
    name: str
    description: str
    path: Path
    parameters: tuple[ParameterSpec, ...]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Catalog:
    """Complete discovered catalog of categories and modules."""

    categories: tuple[CategorySpec, ...]
    modules: dict[str, dict[str, ModuleSpec]]

    @property
    def total_modules(self) -> int:
        return sum(len(mods) for mods in self.modules.values())

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "categories": [
                {
                    "id": cat.id,
                    "label": cat.label,
                    "description": cat.description,
                    "selection": cat.selection,
                    "default": list(cat.default) if isinstance(cat.default, tuple) else cat.default,
                }
                for cat in self.categories
            ],
            "modules": {
                cat_id: [mod.raw for mod in mods.values()]
                for cat_id, mods in self.modules.items()
            },
        }


@dataclass(slots=True)
class StagedAggregation:
    """Mutable accumulator for merged metadata across selected modules."""

    command_rules: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    verification_commands: list[str] = field(default_factory=list)
    evaluators: list[dict[str, str]] = field(default_factory=list)
    concurrency_locks: list[str] = field(default_factory=list)
    pr_checklist: list[str] = field(default_factory=list)
    agents_md_rules: list[str] = field(default_factory=list)
    gitignore_lines: list[str] = field(default_factory=lambda: list(CORE_GITIGNORE_BASE))
    env_example_lines: list[str] = field(default_factory=list)
    dependabot_ecosystems: list[str] = field(default_factory=list)
    ci_jobs_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    renderers: list[Path] = field(default_factory=list)


def slugify(name: str) -> str:
    """Convert a project name into a lowercase kebab-case slug."""
    slug = SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "my-app"


def load_json(path: Path) -> Any:
    """Read and parse a UTF-8 JSON file."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_text(path: Path, content: str, executable: bool = False) -> None:
    """Write UTF-8 text to disk, creating parents and optionally setting +x bits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | EXEC_BITS)


def substitute_placeholders(text: str, replacements: Mapping[str, str]) -> str:
    """Replace {{TOKEN}} placeholders in a single pass without double-expanding values."""
    return PLACEHOLDER_RE.sub(lambda match: replacements.get(match.group(1), match.group(0)), text)


def resolve_safe_subpath(root: Path, rel_path: str | Path) -> Path:
    """Resolve rel_path under root while rejecting absolute paths and traversal."""
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise InitError(f"Refusing absolute path from renderer: {rel_path}")
    base = root.resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise InitError(f"Path traversal blocked for '{rel_path}' outside '{root}'.")
    return resolved


def _resolve_lexical_subpath(
    root: Path,
    rel_path: str | Path,
    *,
    must_be_under: Path | None = None,
) -> Path:
    """Resolve rel_path lexically under root without dereferencing symlinks."""
    candidate = Path(rel_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise InitError(f"Unsafe relative path blocked: {rel_path}")
    base = root.resolve()
    parts = [part for part in candidate.parts if part not in ("", ".")]
    if not parts:
        raise InitError(f"Refusing to operate on root directory itself: {rel_path}")

    current = base
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise InitError(f"Refusing to traverse symlink ancestor '{current}' for '{rel_path}'.")
    raw_target = current / parts[-1]

    if must_be_under is not None:
        anchor_rel = must_be_under.resolve().relative_to(base)
        rel_clean = Path(*parts)
        if rel_clean == anchor_rel or not rel_clean.is_relative_to(anchor_rel):
            raise InitError(f"Path '{rel_path}' must reside strictly inside '{must_be_under}'.")
    return raw_target


def _is_template_checkout(path: Path) -> bool:
    """Return True if path looks like an uninitialized agy_template checkout."""
    return (
        (path / "agy-init").is_file()
        and (path / "scripts" / "agy_init.py").is_file()
        and (path / "modules" / "categories.json").is_file()
        and (path / "core" / "templates" / "AGENTS.md.tmpl").is_file()
    )


def resolve_target_dir(
    output_dir: str | None,
    cwd: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, bool]:
    """Resolve target directory and whether it is an in-place template checkout."""
    resolved_repo = repo_root.resolve()
    if output_dir:
        return Path(output_dir).resolve(), False
    resolved_cwd = (cwd or Path.cwd()).resolve()
    if resolved_cwd != resolved_repo and resolved_cwd.is_relative_to(resolved_repo):
        raise InitError(
            f"Refusing to initialize inside a subdirectory of the template repo ({resolved_repo}). "
            "Run from the target repository root or pass --output-dir."
        )
    return resolved_cwd, _is_template_checkout(resolved_cwd)


def load_renderer(render_py: Path, module_name: str | None = None) -> Callable[[dict[str, Any]], dict[str, str]]:
    """Dynamically import a module's render.py and return its render_files callable."""
    spec = importlib.util.spec_from_file_location(module_name or f"agy_render_{render_py.parent.name}", render_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for {render_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    render_fn = getattr(module, "render_files", None)
    if not callable(render_fn):
        raise TypeError(f"{render_py}: missing callable render_files(context)")
    return render_fn


def _extend_unique(
    target: list[str],
    items: Iterable[str],
    replacements: Mapping[str, str] | None = None,
) -> None:
    for item in items:
        value = substitute_placeholders(item, replacements) if replacements is not None else item
        if value not in target:
            target.append(value)


def _parse_category(raw_cat: dict[str, Any]) -> CategorySpec:
    raw_default = raw_cat.get("default", "none")
    default: str | tuple[str, ...] = tuple(str(x) for x in raw_default) if isinstance(raw_default, list) else str(raw_default)
    return CategorySpec(
        id=str(raw_cat.get("id") or ""),
        label=str(raw_cat.get("label") or ""),
        description=str(raw_cat.get("description") or ""),
        selection=str(raw_cat.get("selection") or ""),
        default=default,
    )


def _parse_module(mod_dir: Path, raw_mod: dict[str, Any]) -> ModuleSpec:
    params = tuple(
        ParameterSpec(
            name=str(p.get("name") or ""),
            description=str(p.get("description") or ""),
            default=str(p.get("default") or ""),
            regex=p.get("regex"),
        )
        for p in (raw_mod.get("parameters") or [])
    )
    return ModuleSpec(
        id=str(raw_mod.get("id") or ""),
        category=str(raw_mod.get("category") or ""),
        name=str(raw_mod.get("name") or ""),
        description=str(raw_mod.get("description") or ""),
        path=mod_dir,
        parameters=params,
        raw=raw_mod,
    )


def load_catalog(modules_dir: Path = MODULES_DIR) -> Catalog:
    """Discover categories and modules from the modules/ directory."""
    categories_path = modules_dir / "categories.json"
    if not categories_path.is_file():
        raise InitError(f"Missing categories catalog: {categories_path}")

    categories_data = load_json(categories_path)
    categories = tuple(_parse_category(c) for c in (categories_data.get("categories") or []))
    modules: dict[str, dict[str, ModuleSpec]] = {cat.id: {} for cat in categories}

    for cat in categories:
        cat_dir = modules_dir / cat.id
        if not cat_dir.is_dir():
            continue
        for mod_dir in sorted(cat_dir.iterdir()):
            manifest_path = mod_dir / "module.json"
            if not mod_dir.is_dir() or not manifest_path.is_file():
                continue
            mod_spec = _parse_module(mod_dir, load_json(manifest_path))
            modules[cat.id][mod_spec.id] = mod_spec

    return Catalog(categories=categories, modules=modules)


def parse_skill_frontmatter(skill_md: Path) -> dict[str, str]:
    """Parse YAML frontmatter fields (name, description) from a SKILL.md file."""
    text = skill_md.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{skill_md}: missing YAML frontmatter block")

    fields: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    for line in match.group(1).splitlines():
        key_match = FRONTMATTER_KEY_RE.match(line)
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
    """Validate POSIX/bash shell script syntax using `bash -n`."""
    proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        errors.append(f"Shell syntax error in {path}: {proc.stderr.strip()}")


def validate_guard_rules_file(path: Path, errors: list[str]) -> None:
    """Validate guard_rules.json structure and compile all regex patterns."""
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
        if rule.get("decision") not in VALID_DECISIONS:
            errors.append(f"{path}: rule[{idx}] invalid decision '{rule.get('decision')}'")
        for regex_key in ("pattern", "exclude_pattern"):
            if rule.get(regex_key):
                try:
                    re.compile(rule[regex_key])
                except re.error as exc:
                    errors.append(f"{path}: rule[{idx}] invalid regex in '{regex_key}': {exc}")


def _validate_categories_schema(categories: tuple[CategorySpec, ...], errors: list[str]) -> None:
    for cat in categories:
        for req_name, req_val in (("id", cat.id), ("label", cat.label), ("selection", cat.selection)):
            if not req_val:
                errors.append(f"categories.json: category missing '{req_name}'")
        if cat.selection not in VALID_SELECTIONS:
            errors.append(f"categories.json: invalid selection '{cat.selection}' for '{cat.id}'")


def _validate_module_manifest(cat_id: str, mod: ModuleSpec, errors: list[str]) -> None:
    manifest_path = mod.path / "module.json"
    for req_name, req_val in (
        ("id", mod.id),
        ("category", mod.category),
        ("name", mod.name),
        ("description", mod.description),
    ):
        if not req_val:
            errors.append(f"{manifest_path}: missing '{req_name}'")
    if mod.id != mod.path.name:
        errors.append(f"{manifest_path}: id '{mod.id}' != dir '{mod.path.name}'")
    if mod.category != cat_id:
        errors.append(f"{manifest_path}: category '{mod.category}' != '{cat_id}'")

    for param in mod.parameters:
        if not param.name:
            errors.append(f"{manifest_path}: parameter missing 'name'")
        if param.regex:
            try:
                re.compile(param.regex)
            except re.error as exc:
                errors.append(f"{manifest_path}: invalid parameter regex: {exc}")

    guard_file = mod.path / "hooks" / "guard_rules.json"
    if guard_file.is_file():
        validate_guard_rules_file(guard_file, errors)

    commit_msg_file = mod.path / "hooks" / "commit-msg.json"
    if commit_msg_file.is_file():
        try:
            cm = load_json(commit_msg_file)
            for key in ("header_regex", "ticket_regex"):
                if cm.get(key):
                    re.compile(cm[key])
        except Exception as exc:
            errors.append(f"{commit_msg_file}: invalid commit-msg config: {exc}")

    render_py = mod.path / "render.py"
    if render_py.is_file():
        try:
            load_renderer(render_py, f"validate_{cat_id}_{mod.id}")
        except Exception as exc:
            errors.append(f"{render_py}: failed validation: {exc}")


def _validate_skill_files(repo_root: Path, errors: list[str]) -> None:
    skill_files = (
        list((repo_root / "core" / "skills").glob("*/SKILL.md"))
        + list((repo_root / ".agents" / "skills").glob("*/SKILL.md"))
        + list((repo_root / "modules").glob("*/*/skills/*/SKILL.md"))
    )
    for skill_md in skill_files:
        try:
            fm = parse_skill_frontmatter(skill_md)
            name = fm.get("name", "")
            desc = fm.get("description", "")
            if not name or not SKILL_NAME_RE.match(name):
                errors.append(f"{skill_md}: frontmatter 'name' must be lowercase hyphenated (got '{name}')")
            if not desc:
                errors.append(f"{skill_md}: frontmatter 'description' must be non-empty")
        except Exception as exc:
            errors.append(str(exc))


def validate_catalog(repo_root: Path = REPO_ROOT) -> list[str]:
    """Run static validation across categories, modules, skills, hooks, and shell scripts."""
    errors: list[str] = []
    modules_dir = repo_root / "modules"
    core_dir = repo_root / "core"

    try:
        catalog = load_catalog(modules_dir)
    except Exception as exc:
        return [str(exc)]

    _validate_categories_schema(catalog.categories, errors)
    for cat_id, mods in catalog.modules.items():
        for mod in mods.values():
            _validate_module_manifest(cat_id, mod, errors)

    _validate_skill_files(repo_root, errors)

    for gr in (core_dir / "hooks" / "guard_rules.core.json", repo_root / ".agents" / "hooks" / "guard_rules.json"):
        if gr.is_file():
            validate_guard_rules_file(gr, errors)
        else:
            errors.append(f"Missing required guard rules file: {gr}")

    for json_file in (core_dir / "hooks" / "hooks.template.json", repo_root / ".agents" / "hooks.json"):
        try:
            load_json(json_file)
        except Exception as exc:
            errors.append(f"Invalid JSON in {json_file}: {exc}")

    shell_targets = list((core_dir / "githooks").glob("*")) + list(modules_dir.glob("**/*.sh"))
    for sh_path in shell_targets:
        if sh_path.is_file() and sh_path.suffix != ".json":
            validate_shell_syntax(sh_path, errors)

    return errors


def copy_with_substitutions(src_dir: Path, dst_dir: Path, replacements: Mapping[str, str]) -> None:
    """Copy src_dir to dst_dir, substituting placeholders in text files and preserving +x bits."""
    if not src_dir.is_dir():
        return
    for item in src_dir.rglob("*"):
        if item.is_dir():
            continue
        target = dst_dir / item.relative_to(src_dir)
        is_exec = bool(item.stat().st_mode & stat.S_IXUSR) or item.suffix == ".sh" or item.name in EXECUTABLE_BASENAMES
        if item.suffix.lower() in TEXT_EXTENSIONS or item.name in EXECUTABLE_BASENAMES or item.name.startswith("."):
            content = item.read_text(encoding="utf-8")
            write_text(target, substitute_placeholders(content, replacements), executable=is_exec)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            if is_exec:
                target.chmod(target.stat().st_mode | EXEC_BITS)


def parse_param_overrides(raw_params: Sequence[str], jira_key: str | None) -> dict[str, str]:
    """Parse repeatable --param KEY=VALUE arguments and --jira-key alias."""
    params: dict[str, str] = {}
    for entry in raw_params:
        if "=" not in entry:
            raise InitError(f"Invalid --param '{entry}'. Expected KEY=VALUE.")
        key, value = entry.split("=", 1)
        params[key.strip()] = value.strip()
    if jira_key:
        params["JIRA_PROJECT_KEY"] = jira_key.strip()
    return params


def _resolve_choice_token(
    token: str,
    cat_id: str,
    ordered_mods: Sequence[ModuleSpec],
    mod_map: Mapping[str, ModuleSpec],
) -> str:
    if token.isdigit():
        pos = int(token)
        if 1 <= pos <= len(ordered_mods):
            return ordered_mods[pos - 1].id
        raise InitError(f"Invalid option number '{token}' for category '{cat_id}'.")
    if token in mod_map:
        return token
    raise InitError(f"Invalid selection '{token}' for category '{cat_id}'.")


def _default_project_name(target_dir: Path) -> str:
    return target_dir.name if target_dir.name != "agy_template" else "my-project"


def _parse_manifest_params(manifest: Mapping[str, Any]) -> dict[str, str]:
    raw = manifest.get("parameters")
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _default_ids_for_category(cat: CategorySpec, valid_mods: Mapping[str, ModuleSpec] | None = None) -> list[str]:
    if isinstance(cat.default, tuple):
        ids = [str(x) for x in cat.default if x and str(x) != "none"]
    elif cat.default and cat.default != "none":
        ids = [str(cat.default)]
    else:
        ids = []
    return [mod_id for mod_id in ids if mod_id in valid_mods] if valid_mods is not None else ids


def _parse_module_selection_map(raw_map: Mapping[str, Any] | None) -> dict[str, list[str]]:
    selections: dict[str, list[str]] = {}
    for cat_id, val in (raw_map or {}).items():
        if isinstance(val, list):
            selections[cat_id] = list(dict.fromkeys(str(v) for v in val if v and str(v) != "none"))
        elif val and str(val) != "none":
            selections[cat_id] = [str(val)]
        else:
            selections[cat_id] = []
    return selections


def _sanitize_manifest_selections(
    catalog: Catalog,
    manifest_selections: Mapping[str, list[str]],
) -> dict[str, list[str]]:
    """Drop unknown/removed modules from an older manifest and enforce category rules."""
    cat_by_id = {cat.id: cat for cat in catalog.categories}
    sanitized: dict[str, list[str]] = {}
    for cat_id, chosen_ids in manifest_selections.items():
        cat = cat_by_id.get(cat_id)
        if cat is None:
            print(f"Warning: ignoring unknown category '{cat_id}' from existing .agy-manifest.json.", file=sys.stderr)
            continue
        valid_mods = catalog.modules.get(cat_id, {})
        valid: list[str] = []
        for mod_id in dict.fromkeys(chosen_ids):
            if mod_id in valid_mods:
                valid.append(mod_id)
            else:
                print(
                    f"Warning: ignoring unknown module '{mod_id}' in category '{cat_id}' from existing .agy-manifest.json.",
                    file=sys.stderr,
                )
        if not cat.allows_multiple and len(valid) > 1:
            print(
                f"Warning: category '{cat_id}' allows at most 1 module; keeping '{valid[0]}' from existing .agy-manifest.json.",
                file=sys.stderr,
            )
            valid = valid[:1]
        if cat.is_required and not valid:
            fallback = _default_ids_for_category(cat, valid_mods)
            print(
                f"Warning: required category '{cat_id}' had no valid modules in .agy-manifest.json; using default {fallback}.",
                file=sys.stderr,
            )
            valid = fallback
        sanitized[cat_id] = valid
    return sanitized


def _load_existing_manifest(target_dir: Path | None) -> dict[str, Any]:
    """Load and validate .agy-manifest.json from target_dir if present."""
    if target_dir is None:
        return {}
    manifest_path = target_dir / ".agy-manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = load_json(manifest_path)
    except Exception as exc:
        raise InitError(f"Invalid existing manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InitError(f"Invalid existing manifest {manifest_path}: expected JSON object.")

    for str_key in ("project_name", "project_slug"):
        val = data.get(str_key)
        if val is not None and not isinstance(val, str):
            raise InitError(f"Invalid existing manifest {manifest_path}: '{str_key}' must be a string.")

    for dict_key in ("selected_modules", "parameters"):
        val = data.get(dict_key)
        if val is not None and not isinstance(val, dict):
            raise InitError(f"Invalid existing manifest {manifest_path}: '{dict_key}' must be an object.")

    active_skills = data.get("active_skills")
    if active_skills is not None:
        if not isinstance(active_skills, list) or any(not isinstance(item, str) for item in active_skills):
            raise InitError(f"Invalid existing manifest {manifest_path}: 'active_skills' must be a list of strings.")

    return data


def _prompt_category_selection(
    cat: CategorySpec,
    mod_map: Mapping[str, ModuleSpec],
    default_ids: Sequence[str] | None = None,
) -> list[str]:
    ordered_mods = list(mod_map.values())
    print(f"\n[{cat.label}] {cat.description}")
    if not cat.is_required:
        print("  0) none")
    for idx, mod in enumerate(ordered_mods, start=1):
        print(f"  {idx}) {mod.id} — {mod.name}")

    if default_ids is not None:
        resolved_defaults = [mod_id for mod_id in default_ids if mod_id in mod_map]
    else:
        resolved_defaults = _default_ids_for_category(cat, mod_map)

    if cat.is_required and not resolved_defaults:
        resolved_defaults = _default_ids_for_category(cat, mod_map)

    if cat.allows_multiple:
        default_display = ",".join(resolved_defaults) if resolved_defaults else "0"
        raw = input(f"Select comma-separated numbers or IDs [{default_display}]: ").strip()
        if not raw:
            return list(resolved_defaults)
        if raw == "0" or raw.lower() == "none":
            if cat.is_required:
                raise InitError(f"Category '{cat.id}' is required and cannot be 'none'.")
            return []
        chosen = [
            _resolve_choice_token(token.strip(), cat.id, ordered_mods, mod_map)
            for token in raw.split(",")
            if token.strip()
        ]
        return list(dict.fromkeys(chosen))

    default_display = resolved_defaults[0] if resolved_defaults else "0"
    raw = input(f"Select option [{default_display}]: ").strip()
    if not raw:
        return [resolved_defaults[0]] if resolved_defaults else []
    if raw == "0" or raw.lower() == "none":
        if cat.is_required:
            raise InitError(f"Category '{cat.id}' is required and cannot be 'none'.")
        return []
    return [_resolve_choice_token(raw, cat.id, ordered_mods, mod_map)]


def interactive_prompt(
    catalog: Catalog,
    initial_project_name: str,
    initial_selections: Mapping[str, list[str]],
    initial_params: Mapping[str, str],
    target_dir: Path | None = None,
    default_selections: Mapping[str, list[str]] | None = None,
    default_params: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, list[str]], dict[str, str]]:
    """Run interactive terminal prompts for any unspecified stack categories and parameters."""
    manifest: dict[str, Any] = {}
    if default_selections is None or default_params is None:
        manifest = _load_existing_manifest(target_dir)
        if default_selections is None:
            default_selections = _sanitize_manifest_selections(
                catalog, _parse_module_selection_map(manifest.get("selected_modules"))
            )
        if default_params is None:
            default_params = _parse_manifest_params(manifest)
        if manifest.get("project_name") and target_dir is not None:
            fallback_name = _default_project_name(target_dir)
            if not initial_project_name or initial_project_name == fallback_name:
                initial_project_name = str(manifest["project_name"])

    for cat in catalog.categories:
        cat_mods = catalog.modules.get(cat.id, {})
        for mod_id in initial_selections.get(cat.id, []):
            if mod_id not in cat_mods:
                available = ", ".join(sorted(cat_mods.keys()))
                raise InitError(f"Unknown module '{mod_id}' in category '{cat.id}'. Available: {available}")

    print("\n=== Antigravity Template Initializer (agy_template) ===\n")
    if target_dir is not None:
        print(f"Target directory: {target_dir}\n")
    if manifest or default_selections or default_params:
        print("Detected existing .agy-manifest.json — pre-populating defaults (press Enter to keep).\n")
    entered_name = input(f"Project name [{initial_project_name}]: ").strip()
    project_name = entered_name or initial_project_name

    selections: dict[str, list[str]] = {}
    for cat in catalog.categories:
        if cat.id in initial_selections:
            selections[cat.id] = list(initial_selections[cat.id])
        else:
            selections[cat.id] = _prompt_category_selection(
                cat,
                catalog.modules.get(cat.id, {}),
                default_ids=default_selections.get(cat.id) if default_selections else None,
            )

    params = dict(initial_params)
    for cat in catalog.categories:
        cat_mods = catalog.modules.get(cat.id, {})
        for mod_id in selections.get(cat.id, []):
            mod = cat_mods[mod_id]
            for param in mod.parameters:
                if param.name in params:
                    continue
                default_val = default_params.get(param.name) or param.default
                entered = input(f"\nParameter {param.name} ({param.description}) [{default_val}]: ").strip()
                params[param.name] = entered or default_val

    return project_name, selections, params


def normalize_selections(
    catalog: Catalog,
    raw_selections: Mapping[str, list[str]],
    params: Mapping[str, str],
) -> tuple[list[ModuleSpec], dict[str, str]]:
    """Validate category cardinality, module existence, and parameter regex constraints."""
    selected_modules: list[ModuleSpec] = []
    resolved_params = dict(params)

    for cat in catalog.categories:
        chosen_ids = raw_selections.get(cat.id)
        if chosen_ids is None:
            chosen_ids = _default_ids_for_category(cat)

        if not cat.allows_multiple and len(chosen_ids) > 1:
            raise InitError(f"Category '{cat.id}' allows at most 1 module; got {chosen_ids}")
        if cat.is_required and not chosen_ids:
            raise InitError(f"Category '{cat.id}' requires at least 1 module.")

        cat_mods = catalog.modules.get(cat.id, {})
        for mod_id in chosen_ids:
            if mod_id not in cat_mods:
                available = ", ".join(sorted(cat_mods.keys()))
                raise InitError(f"Unknown module '{mod_id}' in category '{cat.id}'. Available: {available}")
            mod = cat_mods[mod_id]
            selected_modules.append(mod)
            for param in mod.parameters:
                val = resolved_params.get(param.name) or param.default
                if param.regex and not re.match(param.regex, val):
                    raise InitError(
                        f"Parameter '{param.name}' value '{val}' does not match required pattern '{param.regex}'."
                    )
                resolved_params[param.name] = val

    return selected_modules, resolved_params


def _build_replacements(
    project_name: str,
    project_slug: str,
    selected_modules: Sequence[ModuleSpec],
    resolved_params: Mapping[str, str],
) -> dict[str, str]:
    branch_convention = "feature/<ticket-id>-<short-slug> or fix/<ticket-id>-<short-slug>"
    pr_ticket_syntax = "#<id>"
    for mod in selected_modules:
        if mod.category == "issue-tracker":
            branch_convention = mod.raw.get("branch_convention") or branch_convention
            pr_ticket_syntax = mod.raw.get("pr_ticket_syntax") or pr_ticket_syntax

    base = {"PROJECT_NAME": project_name, "PROJECT_SLUG": project_slug, **resolved_params}
    return {
        **base,
        "BRANCH_CONVENTION": substitute_placeholders(branch_convention, base),
        "PR_TICKET_SYNTAX": substitute_placeholders(pr_ticket_syntax, base),
    }


def _stage_core_layer(stage_dir: Path, core_dir: Path, replacements: Mapping[str, str]) -> list[dict[str, Any]]:
    copy_with_substitutions(core_dir / "skills", stage_dir / ".agents" / "skills", replacements)
    copy_with_substitutions(core_dir / "githooks", stage_dir / ".githooks", replacements)
    copy_with_substitutions(core_dir / "files", stage_dir, replacements)

    write_text(
        stage_dir / ".agents" / "hooks" / "pre_tool_guard.py",
        (core_dir / "hooks" / "pre_tool_guard.py").read_text(encoding="utf-8"),
        executable=True,
    )
    write_text(
        stage_dir / ".agents" / "hooks.json",
        (core_dir / "hooks" / "hooks.template.json").read_text(encoding="utf-8"),
    )
    guard_rules_data = load_json(core_dir / "hooks" / "guard_rules.core.json")
    return list(guard_rules_data.get("command_rules") or [])


def _stage_module(
    stage_dir: Path,
    mod: ModuleSpec,
    replacements: Mapping[str, str],
    agg: StagedAggregation,
) -> None:
    copy_with_substitutions(mod.path / "skills", stage_dir / ".agents" / "skills", replacements)
    copy_with_substitutions(mod.path / "files", stage_dir, replacements)
    copy_with_substitutions(mod.path / "hooks" / "pre-commit.d", stage_dir / ".githooks" / "pre-commit.d", replacements)
    copy_with_substitutions(mod.path / "hooks" / "pre-push.d", stage_dir / ".githooks" / "pre-push.d", replacements)

    mod_guard = mod.path / "hooks" / "guard_rules.json"
    if mod_guard.is_file():
        agg.command_rules.extend(load_json(mod_guard).get("command_rules") or [])

    commit_msg_cfg = mod.path / "hooks" / "commit-msg.json"
    if commit_msg_cfg.is_file():
        write_text(
            stage_dir / ".githooks" / "commit-msg.json",
            substitute_placeholders(commit_msg_cfg.read_text(encoding="utf-8"), replacements),
        )

    mcp_frag = mod.path / "mcp_config.fragment.json"
    if mcp_frag.is_file():
        frag_json = json.loads(substitute_placeholders(mcp_frag.read_text(encoding="utf-8"), replacements))
        agg.mcp_servers.update(frag_json.get("mcpServers") or {})

    _extend_unique(agg.verification_commands, mod.raw.get("verification_commands") or [], replacements)
    _extend_unique(agg.concurrency_locks, mod.raw.get("single_concurrency_locks") or [], replacements)
    _extend_unique(agg.pr_checklist, mod.raw.get("pr_checklist") or [], replacements)
    _extend_unique(agg.agents_md_rules, mod.raw.get("agents_md_rules") or [], replacements)
    _extend_unique(agg.gitignore_lines, mod.raw.get("gitignore") or [])
    _extend_unique(agg.dependabot_ecosystems, mod.raw.get("dependabot_ecosystems") or [])

    for ev in mod.raw.get("evaluators") or []:
        agg.evaluators.append({
            "name": substitute_placeholders(ev["name"], replacements),
            "scope": substitute_placeholders(ev["scope"], replacements),
        })

    mod_env = mod.raw.get("env_example") or []
    if mod_env:
        agg.env_example_lines.append("")
        agg.env_example_lines.extend(substitute_placeholders(line, replacements) for line in mod_env)

    for job in mod.raw.get("ci_jobs") or []:
        agg.ci_jobs_by_key.setdefault(job.get("dedupe_key") or job["id"], job)

    render_py = mod.path / "render.py"
    if render_py.is_file():
        agg.renderers.append(render_py)


def _render_project_templates(
    stage_dir: Path,
    core_dir: Path,
    catalog: Catalog,
    selected_modules: Sequence[ModuleSpec],
    resolved_params: Mapping[str, str],
    replacements: Mapping[str, str],
    agg: StagedAggregation,
) -> None:
    selected_by_cat: dict[str, list[str]] = {cat.id: [] for cat in catalog.categories}
    for mod in selected_modules:
        selected_by_cat.setdefault(mod.category, []).append(f"`{mod.id}` ({mod.name})")

    table_lines = ["| Category | Active Module(s) |", "| :--- | :--- |"]
    for cat in catalog.categories:
        entries = selected_by_cat.get(cat.id) or ["*none*"]
        table_lines.append(f"| **{cat.label}** | {', '.join(entries)} |")

    verif_md = (
        "\n".join(f"- `{cmd}`" for cmd in agg.verification_commands)
        if agg.verification_commands
        else "- *No runtime-specific verification commands configured yet.*"
    )
    eval_md = (
        "\n".join(f"- **{ev['name']}:** {ev['scope']}" for ev in agg.evaluators)
        if agg.evaluators
        else "- **General Architecture & Security Evaluator:** Audit changes against **DRY**, **KISS**, **YAGNI**, **CAZZ**, and tests."
    )
    locks_md = (
        "\n".join(f"- {lock}" for lock in agg.concurrency_locks)
        if agg.concurrency_locks
        else "- *No single-concurrency hardware or emulator locks active.*"
    )
    params_section = (
        "\n".join(["", "## Parameters", "", *(f"- `{k}` = `{v}`" for k, v in sorted(resolved_params.items()))])
        if resolved_params
        else ""
    )

    template_replacements = {
        **replacements,
        "SELECTED_MODULES_TABLE": "\n".join(table_lines),
        "VERIFICATION_COMMANDS_LIST": verif_md,
        "DOMAIN_EVALUATORS_LIST": eval_md,
        "CONCURRENCY_LOCKS_LIST": locks_md,
        "PARAMETERS_SECTION": params_section,
        "MODULE_RULES": "\n".join(f"- {rule}" for rule in agg.agents_md_rules),
    }

    for tmpl_name, out_rel in (
        ("AGENTS.md.tmpl", Path("AGENTS.md")),
        ("stack-profile.md.tmpl", Path(".agents/stack-profile.md")),
        ("README.project.md.tmpl", Path("README.md")),
    ):
        tmpl_text = (core_dir / "templates" / tmpl_name).read_text(encoding="utf-8")
        write_text(stage_dir / out_rel, substitute_placeholders(tmpl_text, template_replacements))


def _execute_module_renderers(
    stage_dir: Path,
    render_context: dict[str, Any],
    replacements: Mapping[str, str],
    renderers: Sequence[Path],
) -> None:
    for idx, render_py in enumerate(renderers):
        render_fn = load_renderer(render_py, f"agy_render_{idx}")
        rendered_map = render_fn(render_context)
        for rel_path, content in rendered_map.items():
            dest = resolve_safe_subpath(stage_dir, rel_path)
            write_text(dest, substitute_placeholders(content, replacements))


def _validate_staged_workspace(stage_dir: Path) -> None:
    agents_size = (stage_dir / "AGENTS.md").stat().st_size
    if agents_size >= MAX_AGENTS_MD_BYTES:
        raise InitError(f"Generated AGENTS.md is too large ({agents_size} bytes >= {MAX_AGENTS_MD_BYTES}).")

    for jf in stage_dir.rglob("*.json"):
        load_json(jf)

    validation_errors: list[str] = []
    for shf in list(stage_dir.rglob("*.sh")) + list((stage_dir / ".githooks").glob("*")):
        if shf.is_file() and shf.suffix != ".json":
            validate_shell_syntax(shf, validation_errors)
    if validation_errors:
        raise InitError("Staged script validation failed:\n" + "\n".join(validation_errors))


def stage_workspace(
    stage_dir: Path,
    project_name: str,
    project_slug: str,
    catalog: Catalog,
    selected_modules: Sequence[ModuleSpec],
    resolved_params: Mapping[str, str],
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Render the complete tailored workspace into stage_dir and validate it."""
    core_dir = repo_root / "core"
    replacements = _build_replacements(project_name, project_slug, selected_modules, resolved_params)

    agg = StagedAggregation(
        command_rules=_stage_core_layer(stage_dir, core_dir, replacements),
        env_example_lines=[f"# Environment variables for {project_name} ({project_slug})"],
    )
    for mod in selected_modules:
        _stage_module(stage_dir, mod, replacements, agg)

    write_text(stage_dir / ".agents" / "hooks" / "guard_rules.json", json.dumps({"command_rules": agg.command_rules}, indent=2) + "\n")
    if agg.mcp_servers:
        write_text(stage_dir / ".agents" / "mcp_config.example.json", json.dumps({"mcpServers": agg.mcp_servers}, indent=2) + "\n")
    write_text(stage_dir / ".gitignore", "\n".join(agg.gitignore_lines) + "\n")
    write_text(stage_dir / ".env.example", "\n".join(agg.env_example_lines) + "\n")

    _render_project_templates(stage_dir, core_dir, catalog, selected_modules, resolved_params, replacements, agg)
    _execute_module_renderers(
        stage_dir,
        {
            "project_name": project_name,
            "project_slug": project_slug,
            "params": dict(resolved_params),
            "ci_jobs": list(agg.ci_jobs_by_key.values()),
            "dependabot_ecosystems": agg.dependabot_ecosystems,
            "pr_checklist": agg.pr_checklist,
            "pr_ticket_syntax": replacements["PR_TICKET_SYNTAX"],
            "branch_convention": replacements["BRANCH_CONVENTION"],
        },
        replacements,
        agg.renderers,
    )

    manifest = {
        "schema_version": 1,
        "template_source": "agy_template",
        "initialized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "project_name": project_name,
        "project_slug": project_slug,
        "selected_modules": {
            cat.id: [m.id for m in selected_modules if m.category == cat.id]
            for cat in catalog.categories
        },
        "parameters": dict(resolved_params),
        "active_skills": sorted(p.parent.name for p in (stage_dir / ".agents" / "skills").glob("*/SKILL.md")),
    }
    write_text(stage_dir / ".agy-manifest.json", json.dumps(manifest, indent=2) + "\n")
    _validate_staged_workspace(stage_dir)
    return manifest


def remove_paths(target_root: Path, rel_paths: Iterable[str]) -> list[str]:
    """Delete files or directories under target_root, returning relative paths removed."""
    removed: list[str] = []
    for rel in rel_paths:
        path = target_root / rel
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(rel)
        elif path.is_file():
            path.unlink()
            removed.append(rel)
    return removed


def prune_template_scaffolding(target_root: Path, keep_engine: bool) -> list[str]:
    """Remove stale provider files and (unless keep_engine) agy_template scaffolding."""
    removed = remove_paths(target_root, PRUNE_ALWAYS_PATHS)
    if keep_engine:
        return removed

    removed.extend(remove_paths(target_root, PRUNE_ENGINE_PATHS))
    remove_paths(target_root, (".agents/skills", ".githooks"))

    scripts_dir = target_root / "scripts"
    if scripts_dir.is_dir() and not any(scripts_dir.iterdir()):
        scripts_dir.rmdir()
    return removed


def _is_preserved_brownfield_path(rel: Path) -> bool:
    return rel == Path("README.md") or (len(rel.parts) > 0 and rel.parts[0] == "docs")


def _merge_text_lines(
    existing_text: str,
    staged_text: str,
    *,
    dedupe_env_keys: bool = False,
    blank_separator: bool = False,
) -> str:
    """Append deduplicated non-empty lines from staged_text onto existing_text."""
    if not existing_text or not existing_text.strip():
        return staged_text
    existing_lines = existing_text.splitlines()
    seen_lines = {line.strip() for line in existing_lines if line.strip()}
    seen_keys: set[str] = set()
    if dedupe_env_keys:
        for line in existing_lines:
            match = ENV_KEY_RE.match(line.strip())
            if match:
                seen_keys.add(match.group(1))

    appended: list[str] = []
    pending_comments: list[str] = []
    pending_blank = False
    for idx, line in enumerate(staged_text.splitlines()):
        stripped = line.strip()
        if not stripped:
            if appended:
                pending_blank = True
            pending_comments.clear()
            continue
        if dedupe_env_keys and stripped.startswith("#"):
            if idx == 0 and stripped.startswith("# Environment variables for "):
                continue
            if stripped not in seen_lines:
                pending_comments.append(line)
            continue
        if stripped in seen_lines:
            continue
        if dedupe_env_keys:
            match = ENV_KEY_RE.match(stripped)
            if match and match.group(1) in seen_keys:
                continue
            if match:
                seen_keys.add(match.group(1))
        seen_lines.add(stripped)
        if not appended and blank_separator and existing_lines and existing_lines[-1].strip():
            appended.append("")
        elif pending_blank and appended:
            appended.append("")
        pending_blank = False
        for comment in pending_comments:
            comment_stripped = comment.strip()
            if comment_stripped not in seen_lines:
                seen_lines.add(comment_stripped)
                appended.append(comment)
        pending_comments.clear()
        appended.append(line)

    if not appended:
        return existing_text
    return "\n".join([*existing_lines, *appended]) + "\n"


def _cleanup_empty_parents(path: Path, stop_at: Path) -> None:
    resolved_stop = stop_at.resolve()
    parent = path.parent
    while parent != resolved_stop and parent.is_relative_to(resolved_stop):
        if parent.is_symlink() or not parent.is_dir() or any(parent.iterdir()):
            break
        parent.rmdir()
        parent = parent.parent


def _module_owned_paths(
    mod: ModuleSpec,
    new_active_skills: set[str],
    prev_render_context: dict[str, Any],
) -> tuple[set[Path], set[Path]]:
    """Collect harness files and skill directories belonging to a single module."""
    stale_dirs: set[Path] = set()
    stale_files: set[Path] = set()

    skills_dir = mod.path / "skills"
    if skills_dir.is_dir():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in new_active_skills:
                stale_dirs.add(Path(".agents") / "skills" / skill_dir.name)

    for hook_subdir in ("pre-commit.d", "pre-push.d"):
        hook_src = mod.path / "hooks" / hook_subdir
        if hook_src.is_dir():
            for item in hook_src.rglob("*"):
                if item.is_file():
                    stale_files.add(Path(".githooks") / hook_subdir / item.relative_to(hook_src))

    if (mod.path / "hooks" / "commit-msg.json").is_file():
        stale_files.add(Path(".githooks") / "commit-msg.json")
    if (mod.path / "mcp_config.fragment.json").is_file():
        stale_files.add(Path(".agents") / "mcp_config.example.json")

    files_dir = mod.path / "files"
    if files_dir.is_dir():
        for item in files_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(files_dir)
                if not _is_preserved_brownfield_path(rel) and str(rel) not in MERGED_BROWNFIELD_FILES:
                    stale_files.add(rel)

    render_py = mod.path / "render.py"
    if render_py.is_file():
        render_fn = load_renderer(render_py, f"agy_prune_{mod.category}_{mod.id}")
        for rel_str in render_fn(prev_render_context):
            rel = Path(rel_str)
            if (
                not rel.is_absolute()
                and ".." not in rel.parts
                and not _is_preserved_brownfield_path(rel)
                and str(rel) not in MERGED_BROWNFIELD_FILES
            ):
                stale_files.add(rel)

    return stale_files, stale_dirs


def _collect_deselected_module_files(
    catalog: Catalog,
    previous_manifest: Mapping[str, Any],
    selected_modules: Sequence[ModuleSpec],
    staged_rel_set: set[Path],
    stage_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Compute stale harness files and skill directories owned by deselected modules."""
    if not previous_manifest:
        return [], []

    prev_selection_map = _parse_module_selection_map(previous_manifest.get("selected_modules"))
    selected_keys = {(mod.category, mod.id) for mod in selected_modules}
    deselected_mods = [
        catalog.modules[cat_id][mod_id]
        for cat_id, mod_ids in prev_selection_map.items()
        for mod_id in mod_ids
        if (cat_id, mod_id) not in selected_keys and mod_id in catalog.modules.get(cat_id, {})
    ]

    skills_stage_root = stage_dir / ".agents" / "skills"
    new_active_skills = (
        {p.name for p in skills_stage_root.iterdir() if p.is_dir()}
        if skills_stage_root.is_dir()
        else set()
    )

    stale_dirs = {
        Path(".agents") / "skills" / skill_name
        for skill_name in (previous_manifest.get("active_skills") or [])
        if isinstance(skill_name, str) and SKILL_NAME_RE.match(skill_name) and skill_name not in new_active_skills
    }

    prev_project_name = str(previous_manifest.get("project_name") or "project")
    prev_render_context = {
        "project_name": prev_project_name,
        "project_slug": str(previous_manifest.get("project_slug") or slugify(prev_project_name)),
        "params": _parse_manifest_params(previous_manifest),
        "ci_jobs": [],
        "dependabot_ecosystems": [],
        "pr_checklist": [],
        "pr_ticket_syntax": "#<id>",
        "branch_convention": "feature/<ticket-id>-<short-slug> or fix/<ticket-id>-<short-slug>",
    }

    stale_files: set[Path] = set()
    for mod in deselected_mods:
        mod_files, mod_dirs = _module_owned_paths(mod, new_active_skills, prev_render_context)
        stale_files.update(mod_files)
        stale_dirs.update(mod_dirs)

    filtered_files = sorted(
        rel
        for rel in stale_files
        if rel not in staged_rel_set and rel != Path(".agy-manifest.json")
    )
    return filtered_files, sorted(stale_dirs)


def _find_existing_stale_targets(
    target_dir: Path,
    stale_files: Sequence[Path],
    stale_dirs: Sequence[Path],
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    """Validate stale paths lexically without symlink traversal and return existing targets."""
    skills_root = target_dir / ".agents" / "skills"
    existing_dirs: list[tuple[Path, Path]] = []
    for rel_dir in stale_dirs:
        raw_dir = _resolve_lexical_subpath(target_dir, rel_dir, must_be_under=skills_root)
        if raw_dir.is_symlink() or raw_dir.is_dir():
            existing_dirs.append((rel_dir, raw_dir))
    existing_files: list[tuple[Path, Path]] = []
    for rel_file in stale_files:
        raw_file = _resolve_lexical_subpath(target_dir, rel_file)
        if raw_file.is_symlink() or raw_file.is_file():
            existing_files.append((rel_file, raw_file))
    return existing_dirs, existing_files


def prune_stale_harness_files(
    target_dir: Path,
    stale_files: Sequence[Path],
    stale_dirs: Sequence[Path],
) -> list[str]:
    """Delete stale harness files/skill dirs from deselected modules without touching user files."""
    removed: list[str] = []
    existing_dirs, existing_files = _find_existing_stale_targets(target_dir, stale_files, stale_dirs)
    for rel_dir, raw_dir in existing_dirs:
        if raw_dir.is_symlink():
            raw_dir.unlink()
        elif raw_dir.is_dir():
            shutil.rmtree(raw_dir)
        removed.append(str(rel_dir))
        _cleanup_empty_parents(raw_dir, target_dir)
    for rel_file, raw_file in existing_files:
        if raw_file.is_symlink() or raw_file.is_file():
            raw_file.unlink()
            removed.append(str(rel_file))
            _cleanup_empty_parents(raw_file, target_dir)
    return removed


def _merge_brownfield_file(rel: Path, staged_file: Path, dest_file: Path) -> str | None:
    """Return merged file contents if new lines need to be appended, else None."""
    existing_text = dest_file.read_text(encoding="utf-8")
    staged_text = staged_file.read_text(encoding="utf-8")
    is_env = rel == Path(".env.example")
    merged = _merge_text_lines(
        existing_text,
        staged_text,
        dedupe_env_keys=is_env,
        blank_separator=is_env,
    )
    return merged if merged != existing_text else None


def _plan_target_operations(
    stage_dir: Path,
    target_dir: Path,
    preserve_brownfield: bool,
) -> tuple[list[Path], list[Path], dict[Path, str]]:
    """Partition staged files into direct writes, preserved paths, and merge contents."""
    to_write: list[Path] = []
    preserved: list[Path] = []
    to_merge: dict[Path, str] = {}
    for item in sorted(stage_dir.rglob("*")):
        if item.is_dir():
            continue
        rel = item.relative_to(stage_dir)
        dest = target_dir / rel
        if preserve_brownfield and (dest.exists() or dest.is_symlink()):
            if _is_preserved_brownfield_path(rel):
                preserved.append(rel)
                continue
            if str(rel) in MERGED_BROWNFIELD_FILES:
                safe_dest = resolve_safe_subpath(target_dir, rel)
                if dest.is_symlink():
                    raise InitError(f"Refusing to merge through symlink '{rel}' inside '{target_dir}'.")
                if safe_dest.is_file():
                    merged = _merge_brownfield_file(rel, item, safe_dest)
                    if merged is not None:
                        to_merge[rel] = merged
                    else:
                        preserved.append(rel)
                    continue
        to_write.append(rel)
    return to_write, preserved, to_merge


def copy_staged_to_target(
    stage_dir: Path,
    target_dir: Path,
    preserve_brownfield: bool = False,
) -> list[str]:
    """Copy staged files into target_dir, preserving/merging brownfield files when requested."""
    written: list[str] = []
    to_write, _, to_merge = _plan_target_operations(stage_dir, target_dir, preserve_brownfield)
    for rel, merged in to_merge.items():
        raw_dest = _resolve_lexical_subpath(target_dir, rel)
        if raw_dest.is_symlink():
            raise InitError(f"Refusing to overwrite symlink '{rel}' inside '{target_dir}'.")
        write_text(raw_dest, merged)
        written.append(str(rel))
    for rel in to_write:
        raw_dest = _resolve_lexical_subpath(target_dir, rel)
        if raw_dest.is_symlink():
            raise InitError(f"Refusing to overwrite symlink '{rel}' inside '{target_dir}'.")
        raw_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage_dir / rel, raw_dest)
        written.append(str(rel))
    return written


def build_arg_parser(catalog: Catalog) -> argparse.ArgumentParser:
    """Build the CLI argument parser dynamically from discovered categories."""
    parser = argparse.ArgumentParser(
        prog="agy-init",
        description="Initialize agy_template for your stack and prune unused automations.",
    )
    parser.add_argument("--validate-catalog", action="store_true", help="Validate all modules, skills, hooks, and scripts.")
    parser.add_argument("--list-modules", action="store_true", help="List available categories, modules, and parameters.")
    parser.add_argument("--json", action="store_true", help="Output JSON (used with --list-modules).")
    parser.add_argument("--project-name", help="Human-readable project name (defaults to target directory name).")
    parser.add_argument("--project-slug", help="URL/service-safe slug (defaults to kebab-case of project name).")
    for cat in catalog.categories:
        help_suffix = "comma-separated IDs or 'none'" if cat.allows_multiple else "module ID or 'none'"
        parser.add_argument(f"--{cat.id}", dest=f"cat_{cat.id}", help=f"{cat.label} ({help_suffix})")
    parser.add_argument("--param", action="append", default=[], help="Module parameter override (KEY=VALUE). Repeatable.")
    parser.add_argument("--jira-key", help="Convenience alias for --param JIRA_PROJECT_KEY=<KEY>.")
    parser.add_argument("--config", help="Optional JSON file specifying project_name, modules, and parameters.")
    parser.add_argument("--output-dir", help="Optional target directory to write initialized harness (defaults to current working directory).")
    parser.add_argument("--keep-template-engine", action="store_true", help="Keep modules/, core/, and agy-init after init.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing or deleting files.")
    parser.add_argument("-y", "--yes", action="store_true", help="Run non-interactively without confirmation prompts.")
    return parser


def _run_validate_catalog(catalog: Catalog) -> int:
    errors = validate_catalog(REPO_ROOT)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"Catalog validation passed ({catalog.total_modules} modules across {len(catalog.categories)} categories).")
    return 0


def _run_list_modules(catalog: Catalog, as_json: bool) -> int:
    if as_json:
        print(json.dumps(catalog.to_public_dict(), indent=2))
        return 0
    for cat in catalog.categories:
        print(f"\n{cat.label} (--{cat.id}, {cat.selection}):")
        for mod in catalog.modules[cat.id].values():
            print(f"  - {mod.id}: {mod.name} — {mod.description}")
            for p in mod.parameters:
                print(f"      param {p.name} (default={p.default}): {p.description}")
    return 0


def _filter_stale_manifest_params(
    catalog: Catalog,
    selections: Mapping[str, list[str]],
    explicit_params: Mapping[str, str],
    merged_params: Mapping[str, str],
) -> dict[str, str]:
    """Drop manifest-only parameters whose declaring module is no longer selected."""
    active_param_names: set[str] = set()
    for cat in catalog.categories:
        cat_mods = catalog.modules.get(cat.id, {})
        chosen_ids = selections.get(cat.id)
        if chosen_ids is None:
            chosen_ids = _default_ids_for_category(cat, cat_mods)
        for mod_id in chosen_ids:
            mod = cat_mods.get(mod_id)
            if mod is not None:
                active_param_names.update(p.name for p in mod.parameters)
    return {
        k: v
        for k, v in merged_params.items()
        if k in explicit_params or k in active_param_names
    }


def _resolve_init_inputs(
    args: argparse.Namespace,
    catalog: Catalog,
    default_project_name: str,
    target_dir: Path | None = None,
    existing_manifest: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, list[str]], dict[str, str]]:
    manifest = dict(existing_manifest) if existing_manifest is not None else _load_existing_manifest(target_dir)
    manifest_name = manifest.get("project_name")
    manifest_selections = _sanitize_manifest_selections(
        catalog, _parse_module_selection_map(manifest.get("selected_modules"))
    )
    manifest_params = _parse_manifest_params(manifest)

    explicit_selections: dict[str, list[str]] = {}
    cli_params = parse_param_overrides(args.param, args.jira_key)
    config_params: dict[str, str] = {}
    project_name = args.project_name

    if args.config:
        cfg = load_json(Path(args.config))
        project_name = project_name or cfg.get("project_name")
        explicit_selections.update(_parse_module_selection_map(cfg.get("modules")))
        for k, v in (cfg.get("parameters") or {}).items():
            config_params[str(k)] = str(v)

    for cat in catalog.categories:
        cli_val = getattr(args, f"cat_{cat.id}", None)
        if cli_val is None:
            continue
        if cli_val.strip().lower() in ("", "none"):
            explicit_selections[cat.id] = []
        else:
            explicit_selections[cat.id] = list(
                dict.fromkeys(t.strip() for t in cli_val.split(",") if t.strip() and t.strip().lower() != "none")
            )

    explicit_params = {**config_params, **cli_params}
    effective_project_name = str(project_name or manifest_name or default_project_name)
    merged_selections = {**manifest_selections, **explicit_selections}
    merged_params = {**manifest_params, **explicit_params}

    needs_interactive = (
        not args.yes
        and not args.dry_run
        and not args.config
        and len(explicit_selections) < len(catalog.categories)
    )
    if not needs_interactive:
        return (
            effective_project_name,
            merged_selections,
            _filter_stale_manifest_params(catalog, merged_selections, explicit_params, merged_params),
        )

    if not sys.stdin.isatty():
        raise InitError("Non-interactive shell requires --yes (or --dry-run) when omitting interactive prompts.", exit_code=2)

    return interactive_prompt(
        catalog,
        effective_project_name,
        explicit_selections,
        explicit_params,
        target_dir=target_dir,
        default_selections=manifest_selections,
        default_params=manifest_params,
    )


def _execute_init(args: argparse.Namespace, catalog: Catalog) -> int:
    target_dir, is_inplace_template = resolve_target_dir(args.output_dir)
    default_project_name = _default_project_name(target_dir)
    existing_manifest = _load_existing_manifest(target_dir)

    final_project_name, raw_selections, params = _resolve_init_inputs(
        args, catalog, default_project_name, target_dir=target_dir, existing_manifest=existing_manifest
    )
    if args.project_slug:
        final_project_slug = slugify(args.project_slug)
    elif (
        existing_manifest
        and final_project_name == existing_manifest.get("project_name")
        and existing_manifest.get("project_slug")
    ):
        final_project_slug = slugify(str(existing_manifest["project_slug"]))
    else:
        final_project_slug = slugify(final_project_name)
    selected_modules, resolved_params = normalize_selections(catalog, raw_selections, params)

    with tempfile.TemporaryDirectory(prefix="agy_init_") as tmp:
        stage_dir = Path(tmp) / "workspace"
        stage_dir.mkdir(parents=True, exist_ok=True)
        manifest = stage_workspace(
            stage_dir, final_project_name, final_project_slug, catalog, selected_modules, resolved_params, REPO_ROOT
        )
        staged_rel_set = {p.relative_to(stage_dir) for p in stage_dir.rglob("*") if p.is_file()}

        stale_files, stale_dirs = (
            ([], [])
            if (is_inplace_template and not args.keep_template_engine)
            else _collect_deselected_module_files(
                catalog, existing_manifest, selected_modules, staged_rel_set, stage_dir
            )
        )

        if args.dry_run:
            to_write, preserved, to_merge = _plan_target_operations(
                stage_dir, target_dir, preserve_brownfield=not is_inplace_template
            )
            existing_dirs, existing_files = _find_existing_stale_targets(target_dir, stale_files, stale_dirs)
            stale_existing = [str(rel) for rel, _ in existing_dirs] + [str(rel) for rel, _ in existing_files]
            summary = {
                "mode": "output-dir" if args.output_dir else "in-place",
                "target_dir": str(target_dir),
                "manifest": manifest,
                "files_to_write": [str(p) for p in to_write],
                "preserved_files": [str(p) for p in preserved],
                "merged_files": [str(p) for p in to_merge],
                "stale_files_to_prune": stale_existing,
                "would_prune_engine": is_inplace_template and not args.keep_template_engine,
            }
            print(json.dumps(summary, indent=2))
            return 0

        if is_inplace_template:
            prune_template_scaffolding(target_dir, keep_engine=args.keep_template_engine)
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            license_src = REPO_ROOT / "LICENSE"
            if license_src.is_file() and not (target_dir / "LICENSE").exists():
                shutil.copy2(license_src, target_dir / "LICENSE")

        if stale_files or stale_dirs:
            prune_stale_harness_files(target_dir, stale_files, stale_dirs)

        copy_staged_to_target(stage_dir, target_dir, preserve_brownfield=not is_inplace_template)

    if (target_dir / ".git").exists():
        subprocess.run(["git", "-C", str(target_dir), "config", "core.hooksPath", ".githooks"], check=False, capture_output=True)

    print(f"Initialized '{final_project_name}' ({final_project_slug}) at {target_dir}")
    print(f"Active skills ({len(manifest['active_skills'])}): {', '.join(manifest['active_skills'])}")
    print("Manifest written to .agy-manifest.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for agy-init."""
    try:
        catalog = load_catalog(MODULES_DIR)
        args = build_arg_parser(catalog).parse_args(argv)
        if args.validate_catalog:
            return _run_validate_catalog(catalog)
        if args.list_modules:
            return _run_list_modules(catalog, args.json)
        return _execute_init(args, catalog)
    except InitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
