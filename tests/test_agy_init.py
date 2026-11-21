#!/usr/bin/env python3
"""Automated test suite for agy_template catalog, initializer, and hooks."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
AGY_INIT = REPO_ROOT / "agy-init"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import agy_init  # noqa: E402


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


class TestAgyTemplate(unittest.TestCase):
    def test_catalog_validation(self) -> None:
        proc = subprocess.run(
            [str(AGY_INIT), "--validate-catalog"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertIn("Catalog validation passed", proc.stdout)

    def test_list_modules_json(self) -> None:
        proc = subprocess.run(
            [str(AGY_INIT), "--list-modules", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        cat_ids = [c["id"] for c in data["categories"]]
        self.assertEqual(
            cat_ids,
            ["frontend", "backend", "data", "cloud", "issue-tracker", "git-hosting"],
        )
        all_module_ids = {
            mod["id"]
            for mods in data["modules"].values()
            for mod in mods
        }
        self.assertEqual(
            all_module_ids,
            {
                "react-vite-ts",
                "python-fastapi",
                "node-express-ts",
                "firebase",
                "gcp-cloudrun",
                "github-issues",
                "jira",
                "github",
                "bitbucket",
            },
        )

    def test_inplace_fastapi_firebase_gcp_jira_bitbucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _copy_template_repo(Path(tmp))
            _git_init(repo)

            proc = subprocess.run(
                [
                    str(repo / "agy-init"),
                    "--project-name",
                    "Order API",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "firebase",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "jira",
                    "--jira-key",
                    "ORD",
                    "--git-hosting",
                    "bitbucket",
                    "--yes",
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            # Template scaffolding pruned
            for pruned in [
                "modules",
                "core",
                "tests",
                "agy-init",
                ".github",
                "CONTRIBUTING_MODULES.md",
                "scripts/agy_init.py",
                ".agents/skills/template-initializer",
                ".agents/hooks/bootstrap_detector.py",
            ]:
                self.assertFalse((repo / pruned).exists(), f"{pruned} should have been pruned")

            # Expected files present
            for expected in [
                "bitbucket-pipelines.yml",
                ".bitbucket/pull_request_template.md",
                ".agents/mcp_config.example.json",
                ".agents/stack-profile.md",
                "firebase.json",
                "firestore.rules",
                "firestore.indexes.json",
                "scripts/deploy.sh",
                "scripts/provision.sh",
                "scripts/lib-firebase.sh",
                ".agy-manifest.json",
                "AGENTS.md",
            ]:
                self.assertTrue((repo / expected).exists(), f"{expected} missing after init")

            self.assertLess((repo / "AGENTS.md").stat().st_size, 5000)

            # Active vs pruned skills
            skills_dir = repo / ".agents" / "skills"
            active_skills = {p.name for p in skills_dir.iterdir() if p.is_dir()}
            self.assertEqual(
                active_skills,
                {
                    "engineering-philosophy",
                    "pr-quality-gate",
                    "parallel-pr-orchestrator",
                    "product-strategy-gate",
                    "backend-python-fastapi",
                    "firebase-platform",
                    "firestore-security-auditor",
                    "cloud-gcp-cloudrun",
                    "tracker-jira",
                    "git-bitbucket-pr",
                },
            )

            # Verify no leftover ClassFlow references anywhere
            for md_file in repo.rglob("*.md"):
                self.assertNotIn("classflow", md_file.read_text(encoding="utf-8").lower())

            # Verify git hooks configured & working
            hooks_path = subprocess.run(
                ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(hooks_path, ".githooks")

            env_main = dict(os.environ, ALLOW_MAIN_COMMIT="1")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            commit_ok = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(ORD-101): initialize governance harness"],
                cwd=repo,
                env=env_main,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(commit_ok.returncode, 0, msg=commit_ok.stderr + commit_ok.stdout)

            # Checkout feature branch and verify Jira commit-msg enforcement
            subprocess.run(
                ["git", "-C", str(repo), "checkout", "-b", "feature/ORD-102-test"],
                check=True,
                capture_output=True,
            )
            (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "notes.txt"], check=True, capture_output=True)
            bad_commit = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat: missing jira key"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(bad_commit.returncode, 0)

            # Verify pre-commit blocks file:/// markdown links
            (repo / "docs" / "bad.md").write_text("See [broken](file:///Users/local/doc.md)\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "docs/bad.md"], check=True, capture_output=True)
            bad_md = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "docs(ORD-102): bad markdown link"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(bad_md.returncode, 0)

    def test_inplace_classflow_stack_github(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _copy_template_repo(Path(tmp))
            _git_init(repo)

            proc = subprocess.run(
                [
                    str(repo / "agy-init"),
                    "--project-name",
                    "Studio App",
                    "--frontend",
                    "react-vite-ts",
                    "--backend",
                    "node-express-ts",
                    "--data",
                    "firebase",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "github",
                    "--yes",
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            ci_yml = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertEqual(ci_yml.count("node-workspace:"), 1)
            self.assertIn("firebase-rules:", ci_yml)
            self.assertFalse((repo / "bitbucket-pipelines.yml").exists())
            self.assertFalse((repo / ".github" / "workflows" / "template-ci.yml").exists())

            env_main = dict(os.environ, ALLOW_MAIN_COMMIT="1")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            commit_ok = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "chore(#1): initialize studio harness"],
                cwd=repo,
                env=env_main,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(commit_ok.returncode, 0, msg=commit_ok.stderr + commit_ok.stdout)

    def test_minimal_fastapi_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "minimal-api"
            proc = subprocess.run(
                [
                    str(AGY_INIT),
                    "--project-name",
                    "Minimal API",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "github",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
            self.assertFalse((out_dir / "firebase.json").exists())
            self.assertFalse((out_dir / "scripts" / "deploy.sh").exists())
            self.assertTrue((out_dir / ".github" / "workflows" / "ci.yml").is_file())
            self.assertTrue((out_dir / ".agents" / "skills" / "backend-python-fastapi" / "SKILL.md").is_file())

    def test_pre_tool_guard_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "guarded"
            subprocess.run(
                [
                    str(AGY_INIT),
                    "--project-name",
                    "Guarded App",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "github",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            )

            guard_script = out_dir / ".agents" / "hooks" / "pre_tool_guard.py"

            def run_guard(payload: dict) -> dict:
                proc = subprocess.run(
                    [sys.executable, str(guard_script)],
                    cwd=out_dir / ".agents",
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return json.loads(proc.stdout)

            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest -q"}},
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "allow",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {"name": "run_command", "args": {"CommandLine": "gh pr merge 12 --squash"}},
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "force_ask",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {"name": "run_command", "args": {"CommandLine": "./scripts/deploy.sh production"}},
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "force_ask",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {"name": "run_command", "args": {"CommandLine": "git add .env.production"}},
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "deny",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {"name": "run_command", "args": {"CommandLine": "git add .env.example"}},
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "allow",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {
                            "name": "write_file",
                            "args": {
                                "Path": str(out_dir / "docs" / "guide.md"),
                                "Content": "Broken [link](file:///Users/foo/bar.md)",
                            },
                        },
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "deny",
            )
            self.assertEqual(
                run_guard(
                    {
                        "toolCall": {
                            "name": "write_file",
                            "args": {
                                "Path": "/Users/foo/.gemini/antigravity-cli/brain/123/plan.md",
                                "Content": "Artifact [link](file:///Users/foo/bar.md)",
                            },
                        },
                        "workspacePaths": [str(out_dir)],
                        "cwd": str(out_dir),
                    }
                )["decision"],
                "allow",
            )

    def test_bootstrap_detector_contracts(self) -> None:
        detector = REPO_ROOT / ".agents" / "hooks" / "bootstrap_detector.py"
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            pre = subprocess.run(
                [sys.executable, str(detector)],
                input=json.dumps({"workspacePaths": [str(ws)], "cwd": str(ws)}),
                capture_output=True,
                text=True,
                check=True,
            )
            pre_out = json.loads(pre.stdout)
            self.assertIn("injectSteps", pre_out)

            (ws / ".agy-manifest.json").write_text("{}\n", encoding="utf-8")
            post = subprocess.run(
                [sys.executable, str(detector)],
                input=json.dumps({"workspacePaths": [str(ws)], "cwd": str(ws)}),
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(post.stdout), {})

    def test_single_pass_placeholder_substitution(self) -> None:
        result = agy_init.substitute_placeholders(
            "{{A}} {{UNKNOWN}}",
            {"A": "{{B}}", "B": "boom"},
        )
        self.assertEqual(result, "{{B}} {{UNKNOWN}}")

    def test_resolve_safe_subpath_blocks_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            safe = agy_init.resolve_safe_subpath(root, ".github/workflows/ci.yml")
            self.assertEqual(safe, root.resolve() / ".github" / "workflows" / "ci.yml")
            with self.assertRaises(agy_init.InitError):
                agy_init.resolve_safe_subpath(root, "../escape.txt")
            with self.assertRaises(agy_init.InitError):
                agy_init.resolve_safe_subpath(root, "/etc/passwd")

    def test_out_of_bounds_interactive_token_raises(self) -> None:
        catalog = agy_init.load_catalog()
        cat_mods = catalog.modules["backend"]
        ordered_mods = list(cat_mods.values())
        with self.assertRaises(agy_init.InitError):
            agy_init._resolve_choice_token("99", "backend", ordered_mods, cat_mods)

    def test_cli_errors_exit_cleanly_without_traceback(self) -> None:
        for cli_args in (
            ["--param", "BROKEN"],
            ["--backend", "unknown-stack", "--yes"],
        ):
            proc = subprocess.run(
                [str(AGY_INIT), *cli_args],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Error:", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_invoked_from_other_repo_initializes_cwd_without_touching_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template_copy = _copy_template_repo(tmp_path)
            app_repo = (tmp_path / "app-repo").resolve()
            app_repo.mkdir()
            _git_init(app_repo)
            (app_repo / "tests").mkdir()
            (app_repo / "tests" / "existing.txt").write_text("keep me\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    str(template_copy / "agy-init"),
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "github",
                    "--yes",
                ],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
            self.assertIn(str(app_repo), proc.stdout)

            manifest = json.loads((app_repo / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["project_slug"], "app-repo")
            self.assertTrue((app_repo / "AGENTS.md").is_file())
            self.assertTrue((app_repo / ".github" / "workflows" / "ci.yml").is_file())
            self.assertEqual((app_repo / "tests" / "existing.txt").read_text(encoding="utf-8"), "keep me\n")

            hooks_path = subprocess.run(
                ["git", "-C", str(app_repo), "config", "--get", "core.hooksPath"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(hooks_path, ".githooks")

            self.assertTrue((template_copy / "agy-init").is_file())
            self.assertTrue((template_copy / "modules").is_dir())
            self.assertTrue((template_copy / "core").is_dir())
            self.assertFalse((template_copy / ".agy-manifest.json").exists())

    def test_invoked_from_other_template_clone_prunes_cwd_not_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_dir = tmp_path / "source"
            target_dir = tmp_path / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            source_template = _copy_template_repo(source_dir)
            target_clone = _copy_template_repo(target_dir)
            _git_init(target_clone)

            proc = subprocess.run(
                [
                    str(source_template / "agy-init"),
                    "--project-name",
                    "Target Clone",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "github",
                    "--yes",
                ],
                cwd=target_clone,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            self.assertTrue((target_clone / ".agy-manifest.json").is_file())
            self.assertTrue((target_clone / "AGENTS.md").is_file())
            for pruned in ("agy-init", "modules", "core", "tests"):
                self.assertFalse((target_clone / pruned).exists(), f"{pruned} should have been pruned from target_clone")

            self.assertTrue((source_template / "agy-init").is_file())
            self.assertTrue((source_template / "modules").is_dir())
            self.assertTrue((source_template / "core").is_dir())
            self.assertFalse((source_template / ".agy-manifest.json").exists())

    def test_refuses_subdir_of_template_repo_without_output_dir(self) -> None:
        proc = subprocess.run(
            [str(AGY_INIT), "--backend", "python-fastapi", "--dry-run"],
            cwd=REPO_ROOT / "scripts",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Error:", proc.stderr)
        self.assertIn("--output-dir", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_merge_text_lines_unit(self) -> None:
        merged_git = agy_init._merge_text_lines("custom/\n.env", ".DS_Store\n.env\n.env.*\n.DS_Store\n")
        self.assertEqual(merged_git, "custom/\n.env\n.DS_Store\n.env.*\n")

        unchanged = agy_init._merge_text_lines("custom/\n.env\n", ".env\ncustom/\n")
        self.assertEqual(unchanged, "custom/\n.env\n")

        merged_env = agy_init._merge_text_lines(
            "CUSTOM=1\nPORT=3000\n# LOG_LEVEL=WARN\n",
            "# Header\n\n# Backend\nAPP_ENV=development\nLOG_LEVEL=INFO\nPORT=8080\n",
            dedupe_env_keys=True,
            blank_separator=True,
        )
        self.assertIn("CUSTOM=1", merged_env)
        self.assertIn("PORT=3000", merged_env)
        self.assertNotIn("PORT=8080", merged_env)
        self.assertIn("APP_ENV=development", merged_env)
        self.assertIn("LOG_LEVEL=INFO", merged_env)
        self.assertEqual(agy_init._merge_text_lines("", "A=1\n"), "A=1\n")

    def test_brownfield_preserves_readme_and_docs_and_merges_gitignore_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_repo = (Path(tmp) / "existing-app").resolve()
            app_repo.mkdir()
            _git_init(app_repo)

            readme_body = "# Existing App\nDo not clobber this README.\n"
            docs_readme_body = "# Existing Docs Hub\nCustom docs overview.\n"
            custom_doc_body = "# Runbook\nExisting team guide.\n"
            (app_repo / "README.md").write_text(readme_body, encoding="utf-8")
            (app_repo / "docs").mkdir()
            (app_repo / "docs" / "README.md").write_text(docs_readme_body, encoding="utf-8")
            (app_repo / "docs" / "custom-guide.md").write_text(custom_doc_body, encoding="utf-8")
            (app_repo / ".gitignore").write_text("custom-build/\n.env\n", encoding="utf-8")
            (app_repo / ".env.example").write_text(
                "CUSTOM_SECRET=keep-me\nPORT=3000\nLOG_LEVEL=INFO\n",
                encoding="utf-8",
            )

            cmd = [
                str(AGY_INIT),
                "--backend",
                "python-fastapi",
                "--cloud",
                "gcp-cloudrun",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
                "--yes",
            ]
            proc = subprocess.run(cmd, cwd=app_repo, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            self.assertEqual((app_repo / "README.md").read_text(encoding="utf-8"), readme_body)
            self.assertEqual((app_repo / "docs" / "README.md").read_text(encoding="utf-8"), docs_readme_body)
            self.assertEqual((app_repo / "docs" / "custom-guide.md").read_text(encoding="utf-8"), custom_doc_body)
            self.assertTrue((app_repo / "docs" / "architecture_decisions.md").is_file())
            self.assertTrue((app_repo / "docs" / "product_strategy.md").is_file())
            self.assertTrue((app_repo / "docs" / "infrastructure_and_devops.md").is_file())

            gitignore_lines = (app_repo / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertEqual(gitignore_lines[:2], ["custom-build/", ".env"])
            self.assertEqual(gitignore_lines.count(".env"), 1)
            self.assertIn(".DS_Store", gitignore_lines)
            self.assertIn("__pycache__/", gitignore_lines)
            self.assertIn(".env.sandbox", gitignore_lines)

            env_text = (app_repo / ".env.example").read_text(encoding="utf-8")
            env_lines = env_text.splitlines()
            self.assertIn("CUSTOM_SECRET=keep-me", env_lines)
            self.assertIn("PORT=3000", env_lines)
            self.assertNotIn("PORT=8080", env_lines)
            self.assertEqual(env_lines.count("LOG_LEVEL=INFO"), 1)
            self.assertIn("APP_ENV=development", env_lines)
            self.assertIn('DEPLOY_REGION="us-central1"', env_lines)

            # Re-running with identical selections must not duplicate lines
            proc2 = subprocess.run(cmd, cwd=app_repo, capture_output=True, text=True, check=False)
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr + proc2.stdout)
            self.assertEqual((app_repo / ".gitignore").read_text(encoding="utf-8").splitlines(), gitignore_lines)
            self.assertEqual((app_repo / ".env.example").read_text(encoding="utf-8"), env_text)

    def test_brownfield_writes_readme_and_docs_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "fresh-external"
            out_dir.mkdir()
            proc = subprocess.run(
                [
                    str(AGY_INIT),
                    "--project-name",
                    "Fresh External",
                    "--backend",
                    "python-fastapi",
                    "--output-dir",
                    str(out_dir),
                    "--yes",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
            self.assertIn("# Fresh External", (out_dir / "README.md").read_text(encoding="utf-8"))
            self.assertTrue((out_dir / "docs" / "README.md").is_file())
            self.assertTrue((out_dir / ".gitignore").is_file())
            self.assertTrue((out_dir / ".env.example").is_file())

    def test_reinit_add_modules_preserves_manifest_defaults_and_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_repo = (Path(tmp) / "reinit-app").resolve()
            app_repo.mkdir()
            _git_init(app_repo)

            first = subprocess.run(
                [
                    str(AGY_INIT),
                    "--project-name",
                    "Order API",
                    "--project-slug",
                    "custom-order-api",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "jira",
                    "--jira-key",
                    "ORD",
                    "--git-hosting",
                    "github",
                    "--yes",
                ],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr + first.stdout)

            # Customize brownfield files before re-init
            (app_repo / "README.md").write_text("# Order API Custom README\n", encoding="utf-8")
            (app_repo / "docs" / "architecture_decisions.md").write_text("# Custom ADRs\n", encoding="utf-8")
            with (app_repo / ".env.example").open("a", encoding="utf-8") as fh:
                fh.write("CUSTOM_APP_TOKEN=abc123\n")

            # Re-init adding cloud and data modules without re-specifying prior flags
            second = subprocess.run(
                [str(AGY_INIT), "--cloud", "gcp-cloudrun", "--data", "firebase", "--yes"],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, msg=second.stderr + second.stdout)

            manifest = json.loads((app_repo / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["project_name"], "Order API")
            self.assertEqual(manifest["project_slug"], "custom-order-api")
            self.assertEqual(manifest["selected_modules"]["backend"], ["python-fastapi"])
            self.assertEqual(manifest["selected_modules"]["issue-tracker"], ["jira"])
            self.assertEqual(manifest["selected_modules"]["git-hosting"], ["github"])
            self.assertEqual(manifest["selected_modules"]["cloud"], ["gcp-cloudrun"])
            self.assertEqual(manifest["selected_modules"]["data"], ["firebase"])
            self.assertEqual(manifest["parameters"], {"JIRA_PROJECT_KEY": "ORD"})

            # Newly added module artifacts staged cleanly
            self.assertTrue((app_repo / "scripts" / "deploy.sh").is_file())
            self.assertTrue((app_repo / "firebase.json").is_file())
            self.assertTrue((app_repo / "docs" / "infrastructure_and_devops.md").is_file())
            self.assertTrue((app_repo / ".agents" / "skills" / "cloud-gcp-cloudrun" / "SKILL.md").is_file())
            self.assertTrue((app_repo / ".agents" / "skills" / "firebase-platform" / "SKILL.md").is_file())
            self.assertTrue((app_repo / ".githooks" / "pre-commit.d" / "40-firestore-rules-check.sh").is_file())

            # Existing module artifacts retained
            self.assertTrue((app_repo / ".agents" / "skills" / "backend-python-fastapi" / "SKILL.md").is_file())
            self.assertTrue((app_repo / ".agents" / "skills" / "tracker-jira" / "SKILL.md").is_file())
            self.assertTrue((app_repo / ".githooks" / "pre-commit.d" / "30-python-check.sh").is_file())

            ci_yml = (app_repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("backend-python:", ci_yml)
            self.assertIn("firebase-rules:", ci_yml)
            agents_md = (app_repo / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("ORD", agents_md)
            self.assertIn("Cloud Run", agents_md)

            # Brownfield customizations preserved
            self.assertEqual((app_repo / "README.md").read_text(encoding="utf-8"), "# Order API Custom README\n")
            self.assertEqual((app_repo / "docs" / "architecture_decisions.md").read_text(encoding="utf-8"), "# Custom ADRs\n")
            env_text = (app_repo / ".env.example").read_text(encoding="utf-8")
            self.assertIn("CUSTOM_APP_TOKEN=abc123", env_text)
            self.assertIn('FIREBASE_DATABASE_ID="custom-order-api-db"', env_text)
            self.assertIn('SERVICE_NAME="custom-order-api"', env_text)

    def test_reinit_switch_modules_prunes_stale_harness_preserving_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_repo = (Path(tmp) / "switch-app").resolve()
            app_repo.mkdir()
            _git_init(app_repo)

            subprocess.run(
                [
                    str(AGY_INIT),
                    "--project-name",
                    "Switch App",
                    "--frontend",
                    "react-vite-ts",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "firebase",
                    "--cloud",
                    "gcp-cloudrun",
                    "--issue-tracker",
                    "jira",
                    "--jira-key",
                    "SWI",
                    "--git-hosting",
                    "github",
                    "--yes",
                ],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=True,
            )

            # Add unrelated user files inside directories managed by harness
            (app_repo / ".github" / "CODEOWNERS").write_text("* @team\n", encoding="utf-8")
            (app_repo / ".github" / "workflows" / "release.yml").write_text("name: Release\n", encoding="utf-8")
            custom_skill = app_repo / ".agents" / "skills" / "custom-domain"
            custom_skill.mkdir(parents=True)
            (custom_skill / "SKILL.md").write_text("---\nname: custom-domain\ndescription: Custom.\n---\n", encoding="utf-8")
            custom_hook = app_repo / ".githooks" / "pre-commit.d" / "99-custom.sh"
            custom_hook.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            user_script = app_repo / "scripts" / "user_tool.sh"
            user_script.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")

            # Switch stack completely (deselecting frontend, python, firebase, cloudrun, jira, github)
            proc = subprocess.run(
                [
                    str(AGY_INIT),
                    "--frontend",
                    "none",
                    "--backend",
                    "node-express-ts",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "github-issues",
                    "--git-hosting",
                    "bitbucket",
                    "--yes",
                ],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)

            # Stale skills, hooks, provider CI, and module files pruned
            for stale in (
                ".agents/skills/frontend-react-vite",
                ".agents/skills/backend-python-fastapi",
                ".agents/skills/firebase-platform",
                ".agents/skills/firestore-security-auditor",
                ".agents/skills/cloud-gcp-cloudrun",
                ".agents/skills/tracker-jira",
                ".agents/skills/git-github-pr",
                ".agents/mcp_config.example.json",
                ".githooks/pre-commit.d/20-frontend-check.sh",
                ".githooks/pre-commit.d/30-python-check.sh",
                ".githooks/pre-commit.d/40-firestore-rules-check.sh",
                ".github/workflows/ci.yml",
                ".github/pull_request_template.md",
                ".github/dependabot.yml",
                "scripts/deploy.sh",
                "scripts/provision.sh",
                "scripts/lib-firebase.sh",
                ".gcloudignore",
                "firebase.json",
                "firestore.rules",
                "firestore.indexes.json",
            ):
                self.assertFalse((app_repo / stale).exists(), f"{stale} should have been pruned")

            # New modules staged
            for expected in (
                ".agents/skills/backend-node-express/SKILL.md",
                ".agents/skills/tracker-github-issues/SKILL.md",
                ".agents/skills/git-bitbucket-pr/SKILL.md",
                ".githooks/pre-commit.d/30-node-check.sh",
                ".githooks/commit-msg.json",
                "bitbucket-pipelines.yml",
                ".bitbucket/pull_request_template.md",
            ):
                self.assertTrue((app_repo / expected).exists(), f"{expected} should be present")

            manifest = json.loads((app_repo / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["parameters"], {})
            self.assertNotIn("JIRA_PROJECT_KEY", (app_repo / "AGENTS.md").read_text(encoding="utf-8"))

            # Unrelated user files untouched
            self.assertEqual((app_repo / ".github" / "CODEOWNERS").read_text(encoding="utf-8"), "* @team\n")
            self.assertEqual((app_repo / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"), "name: Release\n")
            self.assertTrue((custom_skill / "SKILL.md").is_file())
            self.assertTrue(custom_hook.is_file())
            self.assertTrue(user_script.is_file())

            # Switching back to github without unrelated .bitbucket/ files removes empty .bitbucket/ dir cleanly
            proc_back = subprocess.run(
                [str(AGY_INIT), "--git-hosting", "github", "--yes"],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_back.returncode, 0, msg=proc_back.stderr + proc_back.stdout)
            self.assertFalse((app_repo / "bitbucket-pipelines.yml").exists())
            self.assertFalse((app_repo / ".bitbucket").exists())
            self.assertTrue((app_repo / ".github" / "workflows" / "ci.yml").is_file())

    def test_resolve_init_inputs_and_interactive_prompt_with_existing_manifest(self) -> None:
        catalog = agy_init.load_catalog()
        parser = agy_init.build_arg_parser(catalog)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".agy-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project_name": "Manifest App",
                        "project_slug": "manifest-app",
                        "selected_modules": {
                            "frontend": [],
                            "backend": ["python-fastapi"],
                            "data": ["firebase"],
                            "cloud": [],
                            "issue-tracker": ["jira"],
                            "git-hosting": ["github"],
                        },
                        "parameters": {"JIRA_PROJECT_KEY": "MAN"},
                    }
                ),
                encoding="utf-8",
            )

            # Non-interactive CLI flag overrides cloud while preserving manifest defaults
            args_yes = parser.parse_args(["--cloud", "gcp-cloudrun", "--yes"])
            name, selections, params = agy_init._resolve_init_inputs(args_yes, catalog, "fallback", target_dir=repo)
            self.assertEqual(name, "Manifest App")
            self.assertEqual(selections["backend"], ["python-fastapi"])
            self.assertEqual(selections["data"], ["firebase"])
            self.assertEqual(selections["cloud"], ["gcp-cloudrun"])
            self.assertEqual(params, {"JIRA_PROJECT_KEY": "MAN"})

            # Switching jira -> github-issues drops stale manifest JIRA_PROJECT_KEY
            args_no_jira = parser.parse_args(["--issue-tracker", "github-issues", "--yes"])
            _, sel_no_jira, params_no_jira = agy_init._resolve_init_inputs(
                args_no_jira, catalog, "fallback", target_dir=repo
            )
            self.assertEqual(sel_no_jira["issue-tracker"], ["github-issues"])
            self.assertEqual(params_no_jira, {})

            # Interactive prompt via _resolve_init_inputs pre-populates manifest defaults and lets user override/keep
            args_interactive = parser.parse_args(["--cloud", "gcp-cloudrun"])
            # Prompts: project_name, frontend, backend, data, issue-tracker, git-hosting, JIRA_PROJECT_KEY
            answers = iter(["", "", "", "", "", "bitbucket", "NEWKEY"])
            seen_prompts: list[str] = []

            def fake_input(prompt: str = "") -> str:
                seen_prompts.append(prompt)
                return next(answers)

            with (
                contextlib.redirect_stdout(io.StringIO()),
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=fake_input),
            ):
                i_name, i_sel, i_params = agy_init._resolve_init_inputs(
                    args_interactive, catalog, "fallback", target_dir=repo
                )
            self.assertEqual(i_name, "Manifest App")
            self.assertEqual(i_sel["frontend"], [])
            self.assertEqual(i_sel["backend"], ["python-fastapi"])
            self.assertEqual(i_sel["data"], ["firebase"])
            self.assertEqual(i_sel["cloud"], ["gcp-cloudrun"])
            self.assertEqual(i_sel["issue-tracker"], ["jira"])
            self.assertEqual(i_sel["git-hosting"], ["bitbucket"])
            self.assertEqual(i_params, {"JIRA_PROJECT_KEY": "NEWKEY"})
            self.assertIn("Project name [Manifest App]: ", seen_prompts)
            self.assertIn("Select option [python-fastapi]: ", seen_prompts)
            self.assertIn("Select comma-separated numbers or IDs [firebase]: ", seen_prompts)
            self.assertTrue(any("[MAN]" in p for p in seen_prompts))

            # Direct interactive_prompt call detects .agy-manifest.json, keeps multi-select default on Enter,
            # and allows interactive deselection via 'none'
            direct_answers = iter(["", "", "", "", "", "", "", ""])
            with (
                contextlib.redirect_stdout(io.StringIO()),
                mock.patch("builtins.input", side_effect=lambda _prompt="": next(direct_answers)),
            ):
                d_name, d_sel, d_params = agy_init.interactive_prompt(catalog, repo.name, {}, {}, target_dir=repo)
            self.assertEqual(d_name, "Manifest App")
            self.assertEqual(d_sel["data"], ["firebase"])
            self.assertEqual(d_params, {"JIRA_PROJECT_KEY": "MAN"})

            deselect_answers = iter(["", "", "", "none", "", "", "", ""])
            with (
                contextlib.redirect_stdout(io.StringIO()),
                mock.patch("builtins.input", side_effect=lambda _prompt="": next(deselect_answers)),
            ):
                _, d_sel2, _ = agy_init.interactive_prompt(catalog, repo.name, {}, {}, target_dir=repo)
            self.assertEqual(d_sel2["data"], [])

    def test_dry_run_reports_brownfield_and_stale_prune_without_modifying_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_repo = (Path(tmp) / "dry-brownfield").resolve()
            app_repo.mkdir()
            _git_init(app_repo)

            subprocess.run(
                [str(AGY_INIT), "--backend", "python-fastapi", "--git-hosting", "github", "--yes"],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=True,
            )
            (app_repo / "README.md").write_text("# Keep Me\n", encoding="utf-8")
            (app_repo / ".gitignore").write_text("my-cache/\n", encoding="utf-8")

            dry = subprocess.run(
                [str(AGY_INIT), "--git-hosting", "bitbucket", "--dry-run"],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(dry.returncode, 0, msg=dry.stderr + dry.stdout)
            summary = json.loads(dry.stdout)
            self.assertIn("README.md", summary["preserved_files"])
            self.assertIn("docs/README.md", summary["preserved_files"])
            self.assertIn(".gitignore", summary["merged_files"])
            self.assertIn(".github/workflows/ci.yml", summary["stale_files_to_prune"])
            self.assertIn(".agents/skills/git-github-pr", summary["stale_files_to_prune"])

            # Verify disk was not modified
            self.assertEqual((app_repo / "README.md").read_text(encoding="utf-8"), "# Keep Me\n")
            self.assertEqual((app_repo / ".gitignore").read_text(encoding="utf-8"), "my-cache/\n")
            self.assertTrue((app_repo / ".github" / "workflows" / "ci.yml").is_file())
            self.assertFalse((app_repo / "bitbucket-pipelines.yml").exists())

    def test_invalid_existing_manifest_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_repo = (Path(tmp) / "broken-manifest").resolve()
            app_repo.mkdir()
            (app_repo / ".agy-manifest.json").write_text("{broken json", encoding="utf-8")

            proc = subprocess.run(
                [str(AGY_INIT), "--yes"],
                cwd=app_repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Error:", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
