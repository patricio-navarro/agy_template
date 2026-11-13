#!/usr/bin/env python3
"""Automated test suite for agy_template catalog, initializer, and hooks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGY_INIT = REPO_ROOT / "agy-init"


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
                    "learn",
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


if __name__ == "__main__":
    unittest.main()
