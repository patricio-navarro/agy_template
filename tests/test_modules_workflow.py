#!/usr/bin/env python3
"""Automated test suite for workflow modules: issue-tracker/linear and git-hosting/gitlab."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGY_INIT = REPO_ROOT / "agy-init"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import agy_init  # noqa: E402

UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def _copy_template_repo(dst: Path) -> Path:
    target = dst / "repo"
    shutil.copytree(
        REPO_ROOT,
        target,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )
    return target


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True)


def _run_init(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cwd / "agy-init") if (cwd / "agy-init").is_file() else str(AGY_INIT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class TestWorkflowModules(unittest.TestCase):
    def test_workflow_modules_discovered_and_valid(self) -> None:
        catalog = agy_init.load_catalog()
        self.assertIn("linear", catalog.modules["issue-tracker"])
        self.assertIn("gitlab", catalog.modules["git-hosting"])

        proc = subprocess.run(
            [str(AGY_INIT), "--list-modules", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        tracker_ids = {m["id"]: m for m in data["modules"]["issue-tracker"]}
        hosting_ids = {m["id"]: m for m in data["modules"]["git-hosting"]}
        self.assertIn("linear", tracker_ids)
        self.assertIn("gitlab", hosting_ids)
        self.assertEqual(
            tracker_ids["linear"]["parameters"][0]["regex"],
            "^[A-Z][A-Z0-9]{1,9}$",
        )

        val_proc = subprocess.run(
            [str(AGY_INIT), "--validate-catalog"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(val_proc.returncode, 0, msg=val_proc.stderr + val_proc.stdout)

        for mod_dir in (
            REPO_ROOT / "modules" / "issue-tracker" / "linear",
            REPO_ROOT / "modules" / "git-hosting" / "gitlab",
        ):
            for md_file in mod_dir.rglob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                self.assertNotIn("file:///", content, msg=f"Forbidden file:/// link in {md_file}")
                self.assertNotIn("classflow", content.lower(), msg=f"Stale classflow reference in {md_file}")

    def test_linear_team_key_parameter_validation(self) -> None:
        catalog = agy_init.load_catalog()

        # Default resolves to TEAM when omitted
        _, default_params = agy_init.normalize_selections(
            catalog,
            {"issue-tracker": ["linear"], "git-hosting": ["github"]},
            {},
        )
        self.assertEqual(default_params["LINEAR_TEAM_KEY"], "TEAM")

        for valid_key in ("AB", "ENG", "TEAM", "A1", "A123456789"):
            _, resolved = agy_init.normalize_selections(
                catalog,
                {"issue-tracker": ["linear"], "git-hosting": ["github"]},
                {"LINEAR_TEAM_KEY": valid_key},
            )
            self.assertEqual(resolved["LINEAR_TEAM_KEY"], valid_key)

        for invalid_key in ("A", "ABCDEFGHIJK", "eng", "1ENG", "ENG_1", "ENG-1"):
            with self.assertRaises(agy_init.InitError, msg=f"{invalid_key} should be rejected"):
                agy_init.normalize_selections(
                    catalog,
                    {"issue-tracker": ["linear"], "git-hosting": ["github"]},
                    {"LINEAR_TEAM_KEY": invalid_key},
                )

            cli_err = _run_init(
                [
                    "--issue-tracker",
                    "linear",
                    "--param",
                    f"LINEAR_TEAM_KEY={invalid_key}",
                    "--git-hosting",
                    "github",
                    "--dry-run",
                ],
                cwd=REPO_ROOT,
            )
            self.assertNotEqual(cli_err.returncode, 0)
            self.assertIn("Error:", cli_err.stderr)
            self.assertNotIn("Traceback", cli_err.stderr)

    def test_linear_placeholder_substitution_and_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "linear-app"
            proc = _run_init(
                [
                    "--project-name",
                    "Linear App",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "linear",
                    "--param",
                    "LINEAR_TEAM_KEY=ENG",
                    "--git-hosting",
                    "github",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            commit_cfg = json.loads((out_dir / ".githooks" / "commit-msg.json").read_text(encoding="utf-8"))
            self.assertEqual(commit_cfg["ticket_regex"], r"\bENG-[0-9]+\b")
            self.assertIn("ENG-123", commit_cfg["example"])
            self.assertNotIn("{{LINEAR_TEAM_KEY}}", json.dumps(commit_cfg))

            skill_md = (out_dir / ".agents" / "skills" / "tracker-linear" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("ENG-<num>", skill_md)
            self.assertIn("feature/ENG-<num>-<short-slug>", skill_md)
            self.assertIsNone(UNRESOLVED_PLACEHOLDER_RE.search(skill_md))

            stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
            self.assertIn("feature/ENG-<num>-<short-slug> or fix/ENG-<num>-<short-slug>", stack_profile)
            self.assertIn("**PR Ticket Reference:** `ENG-<num>`", stack_profile)
            self.assertIn("`LINEAR_TEAM_KEY` = `ENG`", stack_profile)

            agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(".agents/skills/tracker-linear/SKILL.md", agents_md)
            self.assertIn("ENG-<num>", agents_md)
            self.assertLess((out_dir / "AGENTS.md").stat().st_size, agy_init.MAX_AGENTS_MD_BYTES)

            mcp_cfg = json.loads((out_dir / ".agents" / "mcp_config.example.json").read_text(encoding="utf-8"))
            self.assertEqual(mcp_cfg["mcpServers"]["linear"]["url"], "https://mcp.linear.app/mcp")

            env_example = (out_dir / ".env.example").read_text(encoding="utf-8")
            self.assertIn('LINEAR_TEAM_KEY="ENG"', env_example)

    def test_linear_commit_msg_hook_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "linear-repo"
            repo.mkdir()
            _git_init(repo)

            proc = _run_init(
                [
                    "--project-name",
                    "Hook Test",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "linear",
                    "--param",
                    "LINEAR_TEAM_KEY=ENG",
                    "--git-hosting",
                    "gitlab",
                    "--output-dir",
                    str(repo),
                    "--yes",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            env_main = dict(os.environ, ALLOW_MAIN_COMMIT="1")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            init_commit = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(ENG-100): initialize governance harness"],
                cwd=repo,
                env=env_main,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_commit.returncode, 0, msg=init_commit.stderr + init_commit.stdout)

            subprocess.run(
                ["git", "-C", str(repo), "checkout", "-b", "feature/ENG-101-auth"],
                check=True,
                capture_output=True,
            )

            def try_commit(filename: str, msg: str) -> subprocess.CompletedProcess[str]:
                (repo / filename).write_text(f"{msg}\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(repo), "add", filename], check=True, capture_output=True)
                return subprocess.run(
                    ["git", "-C", str(repo), "commit", "-m", msg],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            for idx, bad_msg in enumerate(
                [
                    "feat: missing linear key",
                    "fix: missing key",
                    "refactor: missing key",
                    "feat(PROJ-101): wrong tracker key",
                    "feat(XENG-101): wrong prefix boundary",
                    "feat(ENG-101a): invalid trailing characters",
                    "added ENG-101 without conventional commit prefix",
                ]
            ):
                res = try_commit(f"bad_{idx}.txt", bad_msg)
                self.assertNotEqual(res.returncode, 0, msg=f"Commit should have been rejected: {bad_msg}")

            for idx, good_msg in enumerate(
                [
                    "feat(ENG-101): add auth middleware",
                    "fix(ENG-102)!: handle expired session token",
                    "refactor: simplify ENG-103 token parser",
                    "chore: refresh lockfile metadata",
                ]
            ):
                res = try_commit(f"good_{idx}.txt", good_msg)
                self.assertEqual(res.returncode, 0, msg=f"Commit '{good_msg}' failed: {res.stderr + res.stdout}")

    def test_gitlab_renderer_direct_contracts(self) -> None:
        render_fn = agy_init.load_renderer(REPO_ROOT / "modules" / "git-hosting" / "gitlab" / "render.py")

        # Empty ci_jobs falls back to hygiene job and default ticket syntax
        empty_rendered = render_fn({"ci_jobs": []})
        self.assertEqual(
            set(empty_rendered.keys()),
            {".gitlab-ci.yml", ".gitlab/merge_request_templates/Default.md"},
        )
        self.assertIn("hygiene:", empty_rendered[".gitlab-ci.yml"])
        self.assertIn("stage: test", empty_rendered[".gitlab-ci.yml"])
        self.assertIn("Ticket: Closes #<issue-number>", empty_rendered[".gitlab/merge_request_templates/Default.md"])

        # Custom jobs exercise runtime image inference, caching, Node+Java bootstrap, and unguarded colons
        rich_rendered = render_fn(
            {
                "pr_ticket_syntax": "ENG-<num>",
                "pr_checklist": [
                    "Unit tests pass",
                    "Unit tests pass",
                    "Linked to tracked ticket (`ENG-<num>`)",
                ],
                "ci_jobs": [
                    {
                        "id": "go-service",
                        "name": "Go Vet & Test",
                        "runtimes": {"go": "1.23"},
                        "caches": ["gomod"],
                        "guard_files": ["go.mod"],
                        "steps": [{"name": "Run go test", "run": "go test ./..."}],
                    },
                    {
                        "id": "firebase-rules",
                        "name": "Firestore Rules",
                        "runtimes": {"node": "22", "java": "21"},
                        "docker_image": "eclipse-temurin:21-jdk",
                        "caches": ["npm"],
                        "guard_files": ["firestore.rules", "package.json"],
                        "steps": [{"name": "Run rules", "run": "npm run test:rules"}],
                    },
                    {
                        "id": "lint-docs",
                        "name": "Docs Check",
                        "steps": [{"name": "Echo status", "run": "echo status: ok"}],
                    },
                ],
            }
        )
        ci_yml = rich_rendered[".gitlab-ci.yml"]
        self.assertIn("go-service:", ci_yml)
        self.assertIn("image: golang:1.23", ci_yml)
        self.assertIn(".go/pkg/mod/", ci_yml)
        self.assertIn('if [ -f "go.mod" ]; then', ci_yml)
        self.assertIn("firebase-rules:", ci_yml)
        self.assertIn("nodesource.com/setup_22.x", ci_yml)
        self.assertIn('if [ -f "firestore.rules" ] || [ -f "package.json" ]; then', ci_yml)
        self.assertIn("lint-docs:", ci_yml)
        self.assertIn("echo status: ok", ci_yml)
        # GitLab CI rejects `name:` as a job-level keyword
        self.assertNotRegex(ci_yml, re.compile(r"^  name:", re.MULTILINE))

        mr_tmpl = rich_rendered[".gitlab/merge_request_templates/Default.md"]
        self.assertIn("Ticket: ENG-<num>", mr_tmpl)
        self.assertEqual(mr_tmpl.count("- [ ] Linked to tracked ticket (`ENG-<num>`)"), 1)
        self.assertEqual(mr_tmpl.count("- [ ] Unit tests pass"), 1)

    def test_gitlab_day0_guard_scripts_pass_without_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "gitlab-day0"
            proc = _run_init(
                [
                    "--project-name",
                    "Day Zero App",
                    "--frontend",
                    "react-vite-ts",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "firebase",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "linear",
                    "--param",
                    "LINEAR_TEAM_KEY=APP",
                    "--git-hosting",
                    "gitlab",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            ci_yml = (out_dir / ".gitlab-ci.yml").read_text(encoding="utf-8")
            self.assertEqual(ci_yml.count("\nnode-workspace:\n"), 1)
            self.assertIn("\nbackend-python:\n", ci_yml)
            self.assertIn("\nfirebase-rules:\n", ci_yml)

            # Extract each guarded shell block (`if [ -f ... ] ... fi`) and execute in empty Day-0 dir
            blocks = re.findall(r"(if \[ -f [^\n]+\n(?:      .*\n)+?      fi)", ci_yml)
            self.assertEqual(len(blocks), 3, msg=f"Expected 3 guarded job scripts in:\n{ci_yml}")

            day0_empty_dir = Path(tmp) / "empty-checkout"
            day0_empty_dir.mkdir()
            for block in blocks:
                dedented = "\n".join(line[6:] if line.startswith("      ") else line for line in block.splitlines())
                syntax = subprocess.run(
                    ["bash", "-n"],
                    input=dedented,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(syntax.returncode, 0, msg=syntax.stderr)
                exec_res = subprocess.run(
                    ["bash", "-euo", "pipefail"],
                    input=dedented,
                    cwd=day0_empty_dir,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(exec_res.returncode, 0, msg=exec_res.stderr + exec_res.stdout)
                self.assertIn("skipping step on Day-0 harness", exec_res.stdout)

    def test_inplace_gitlab_linear_prunes_github_and_bitbucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _copy_template_repo(Path(tmp))
            _git_init(repo)

            # Ensure stale Bitbucket artifacts are also present alongside .github
            (repo / ".bitbucket").mkdir(exist_ok=True)
            (repo / ".bitbucket" / "pull_request_template.md").write_text("stale\n", encoding="utf-8")
            (repo / "bitbucket-pipelines.yml").write_text("stale: true\n", encoding="utf-8")

            proc = _run_init(
                [
                    "--project-name",
                    "GitLab Stack",
                    "--frontend",
                    "react-vite-ts",
                    "--backend",
                    "node-express-ts",
                    "--data",
                    "firebase",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "linear",
                    "--param",
                    "LINEAR_TEAM_KEY=APP",
                    "--git-hosting",
                    "gitlab",
                    "--yes",
                ],
                cwd=repo,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            for pruned in (
                ".github",
                ".bitbucket",
                "bitbucket-pipelines.yml",
                "modules",
                "core",
                "tests",
                "agy-init",
                "scripts/agy_init.py",
                ".agents/skills/template-initializer",
            ):
                self.assertFalse((repo / pruned).exists(), f"{pruned} should have been pruned")

            self.assertTrue((repo / ".gitlab-ci.yml").is_file())
            mr_tmpl_path = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            self.assertTrue(mr_tmpl_path.is_file())
            self.assertTrue((repo / ".agents" / "skills" / "git-gitlab-mr" / "SKILL.md").is_file())
            self.assertTrue((repo / ".agents" / "skills" / "tracker-linear" / "SKILL.md").is_file())
            self.assertLess((repo / "AGENTS.md").stat().st_size, 5000)

            mr_tmpl = mr_tmpl_path.read_text(encoding="utf-8")
            self.assertIn("Ticket: APP-<num>", mr_tmpl)
            self.assertIn("Linear issue `APP-<num>`", mr_tmpl)
            self.assertIn("GitLab CI pipeline (`.gitlab-ci.yml`)", mr_tmpl)
            self.assertIsNone(UNRESOLVED_PLACEHOLDER_RE.search(mr_tmpl))

            gitlab_skill = (repo / ".agents" / "skills" / "git-gitlab-mr" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("APP-<num>", gitlab_skill)
            self.assertIsNone(UNRESOLVED_PLACEHOLDER_RE.search(gitlab_skill))

    def test_gitlab_pre_tool_guard_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "gitlab-guarded"
            proc = _run_init(
                [
                    "--project-name",
                    "Guarded GitLab",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "linear",
                    "--git-hosting",
                    "gitlab",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            guard_script = out_dir / ".agents" / "hooks" / "pre_tool_guard.py"

            def run_guard(command_line: str) -> dict:
                res = subprocess.run(
                    [sys.executable, str(guard_script)],
                    cwd=out_dir / ".agents",
                    input=json.dumps(
                        {
                            "toolCall": {"name": "run_command", "args": {"CommandLine": command_line}},
                            "workspacePaths": [str(out_dir)],
                            "cwd": str(out_dir),
                        }
                    ),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return json.loads(res.stdout)

            for gated_cmd in (
                "glab mr merge",
                "glab mr merge 42 --squash --remove-source-branch",
                "glab mr accept 42",
                "git push && glab mr merge 42",
                "glab repo delete my-group/my-repo",
                "glab api -X PUT projects/1/merge_requests/42/merge",
                "curl -X POST https://gitlab.com/api/v4/projects/1/merge_requests/42/merge",
            ):
                self.assertEqual(run_guard(gated_cmd)["decision"], "force_ask", msg=gated_cmd)

            for allowed_cmd in (
                "glab mr create --target-branch main",
                "glab mr view 42",
                "glab mr note 42 --message 'APPROVED'",
                "glab ci status",
                "glab api projects/1/merge_requests/42",
            ):
                self.assertEqual(run_guard(allowed_cmd)["decision"], "allow", msg=allowed_cmd)


if __name__ == "__main__":
    unittest.main()
