# Agent Instructions — `agy_template`

This repository is the uninitialized **`agy_template`** modular starter and governance harness. Determine which workflow the user wants:

- **1. Initializing a New Application Fork (Default for App Developers):**
  When the user asks to configure, initialize, or clean up this repository for a new project stack (e.g., *"Set up this repo for Python FastAPI, Firebase, GCP, Jira, and Bitbucket"*), read and follow [`.agents/skills/template-initializer/SKILL.md`](.agents/skills/template-initializer/SKILL.md) and run `./agy-init`.
- **2. Contributing New Stack Modules to `agy_template`:**
  When adding new modules (e.g., Java Spring, GitLab, AWS ECS) or editing `scripts/agy_init.py`, read [`CONTRIBUTING_MODULES.md`](CONTRIBUTING_MODULES.md), follow [`.agents/skills/engineering-philosophy/SKILL.md`](core/skills/engineering-philosophy/SKILL.md) (**DRY**, **KISS**, **YAGNI**, **CAZZ**), and verify every change with:
  ```sh
  ./agy-init --validate-catalog && python3 -m unittest discover -s tests -v
  ```
- **Committed Markdown Hygiene:** Never write machine-local `file:///...` links inside committed `.md` files (use portable relative paths).
