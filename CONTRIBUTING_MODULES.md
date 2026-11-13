# Contributing Modules to `agy_template`

`agy_template` uses a declarative plugin catalog so contributors can add new frameworks, cloud providers, issue trackers, or Git hosting platforms in a single Pull Request **without modifying `scripts/agy_init.py`**.

---

## 1. Directory Layout for a New Module

Create `modules/<category>/<module-id>/` using one of the categories in `modules/categories.json` (`frontend`, `backend`, `data`, `cloud`, `issue-tracker`, `git-hosting`):

```text
modules/<category>/<module-id>/
├── module.json                  # Required: metadata, verification commands, CI jobs, evaluators
├── skills/<skill-name>/
│   └── SKILL.md                 # Required YAML frontmatter: name + third-person description
├── hooks/
│   ├── guard_rules.json         # Optional: PreToolUse command_rules merged into .agents/hooks/guard_rules.json
│   ├── commit-msg.json          # Optional (issue-tracker): Conventional Commit + ticket regex rules
│   ├── pre-commit.d/*.sh        # Optional: modular Git pre-commit checks
│   └── pre-push.d/*.sh          # Optional: modular Git pre-push checks
├── mcp_config.fragment.json     # Optional: merged into .agents/mcp_config.example.json
├── files/                       # Optional: static/template files copied to repo root
└── render.py                    # Optional: dynamic generator exposing render_files(context) -> dict[str, str]
```

---

## 2. `module.json` Schema Reference

| Field | Type | Required | Purpose |
| :--- | :--- | :--- | :--- |
| `id` | string | Yes | Must match the directory name (e.g., `java-spring`). |
| `category` | string | Yes | Must match the parent category directory (`backend`, `git-hosting`, etc.). |
| `name` | string | Yes | Human-readable module name. |
| `description` | string | Yes | Concise summary shown in `--list-modules` and interactive prompts. |
| `parameters` | array | No | Prompt/CLI overrides (`name`, `description`, `default`, `regex`) substituted as `{{PARAM}}`. |
| `verification_commands` | string[] | No | Commands listed in `.agents/stack-profile.md` and `README.md`. |
| `evaluators` | object[] | No | `{ "name", "scope" }` entries for Tier 2 `pr-quality-gate` reviews. |
| `single_concurrency_locks` | string[] | No | Shared-resource mutex notes for `parallel-pr-orchestrator`. |
| `pr_checklist` | string[] | No | Verification checkboxes merged into PR templates. |
| `agents_md_rules` | string[] | No | Concise 1-line routing bullets added to generated `AGENTS.md`. |
| `gitignore` | string[] | No | Lines appended (deduplicated) to `.gitignore`. |
| `env_example` | string[] | No | Lines appended to `.env.example`. |
| `dependabot_ecosystems` | string[] | No | Ecosystems passed to `git-hosting` renderers (e.g., `maven`, `gradle`, `pip`). |
| `ci_jobs` | object[] | No | Declarative CI job specs (`id`, `dedupe_key`, `name`, `runtimes`, `docker_image`, `caches`, `guard_files`, `steps`). |

### Placeholder Tokens

Any text file under `skills/`, `hooks/`, `files/`, or rendered by `render.py` supports `{{PROJECT_NAME}}`, `{{PROJECT_SLUG}}`, `{{BRANCH_CONVENTION}}`, `{{PR_TICKET_SYNTAX}}`, and any declared parameter `{{PARAM_NAME}}`.

---

## 3. `render.py` Contract (For Git Hosting / CI Providers)

A module providing `render.py` must define:

```python
def render_files(context: dict) -> dict[str, str]:
    ...
```

`context` provides `project_name`, `project_slug`, `params`, `ci_jobs`, `dependabot_ecosystems`, `pr_checklist`, `pr_ticket_syntax`, and `branch_convention`. Return a mapping of relative repository paths to file contents.

> [!IMPORTANT]
> Because `agy_template` installs a governance harness with zero starter application code, CI steps **must** guard manifest-dependent commands using each job's `guard_files` (e.g., `pom.xml`, `pyproject.toml`, `package.json`) so Day-0 commits pass green immediately.

---

## 4. Validate Before Opening a PR

Run both the catalog validator and the full automated test suite:

```sh
./agy-init --validate-catalog
python3 -m unittest discover -s tests -v
```
