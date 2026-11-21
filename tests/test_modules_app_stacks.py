#!/usr/bin/env python3
"""Tests for app-stack modules: nextjs-ts, go-service, and java-spring."""

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
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import agy_init  # noqa: E402


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True)


def _run_init(out_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [
            str(AGY_INIT),
            "--project-name",
            "App Stack Test",
            "--output-dir",
            str(out_dir),
            "--yes",
            *extra_args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"agy-init failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


class TestAppStackModules(unittest.TestCase):
    def test_catalog_discovers_all_three_app_stack_modules(self) -> None:
        catalog = agy_init.load_catalog()
        self.assertIn("nextjs-ts", catalog.modules["frontend"])
        self.assertIn("go-service", catalog.modules["backend"])
        self.assertIn("java-spring", catalog.modules["backend"])

        proc = subprocess.run(
            [str(AGY_INIT), "--list-modules", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        frontend_ids = {m["id"] for m in data["modules"]["frontend"]}
        backend_ids = {m["id"] for m in data["modules"]["backend"]}
        self.assertIn("nextjs-ts", frontend_ids)
        self.assertTrue({"go-service", "java-spring"}.issubset(backend_ids))

    def test_skill_frontmatter_and_markdown_hygiene(self) -> None:
        expected_skills = [
            ("frontend", "nextjs-ts", "frontend-nextjs-ts"),
            ("backend", "go-service", "backend-go-service"),
            ("backend", "java-spring", "backend-java-spring"),
        ]
        for category, mod_id, skill_name in expected_skills:
            mod_dir = REPO_ROOT / "modules" / category / mod_id
            skill_md = mod_dir / "skills" / skill_name / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"Missing {skill_md}")
            fm = agy_init.parse_skill_frontmatter(skill_md)
            self.assertEqual(fm.get("name"), skill_name)
            self.assertRegex(fm.get("name", ""), r"^[a-z0-9-]+$")
            self.assertTrue(fm.get("description"), f"Empty description in {skill_md}")

            for md_file in mod_dir.rglob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                self.assertNotIn("file:///", content, f"Machine-local link in {md_file}")

    def test_day0_guard_files_declared_on_all_ci_jobs(self) -> None:
        catalog = agy_init.load_catalog()
        for category, mod_id in (
            ("frontend", "nextjs-ts"),
            ("backend", "go-service"),
            ("backend", "java-spring"),
        ):
            mod = catalog.modules[category][mod_id]
            ci_jobs = mod.raw.get("ci_jobs") or []
            self.assertTrue(ci_jobs, f"{mod_id} must declare ci_jobs")
            for job in ci_jobs:
                guard_files = job.get("guard_files") or []
                self.assertTrue(guard_files, f"{mod_id} CI job {job.get('id')} must declare Day-0 guard_files")

    def test_nextjs_ts_and_node_express_ci_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "next-node-app"
            _run_init(
                out_dir,
                "--frontend",
                "nextjs-ts",
                "--backend",
                "node-express-ts",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
            )

            manifest = json.loads((out_dir / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("frontend-nextjs-ts", manifest["active_skills"])
            self.assertIn("backend-node-express", manifest["active_skills"])

            ci_yml = (out_dir / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertEqual(ci_yml.count("node-workspace:"), 1)
            self.assertIn('[ -f "package.json" ]', ci_yml)
            self.assertIn("actions/setup-node@v4", ci_yml)
            self.assertIn('node-version: "22"', ci_yml)
            self.assertIn("hashFiles('package-lock.json')", ci_yml)
            self.assertNotIn("cache: 'npm'", ci_yml)

            dependabot = (out_dir / ".github" / "dependabot.yml").read_text(encoding="utf-8")
            self.assertEqual(dependabot.count('- package-ecosystem: "npm"'), 1)

            # Bitbucket Pipelines should also keep a single deduplicated step (no parallel block)
            bb_dir = Path(tmp) / "next-node-bb"
            _run_init(
                bb_dir,
                "--frontend",
                "nextjs-ts",
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
            )
            pipelines = (bb_dir / "bitbucket-pipelines.yml").read_text(encoding="utf-8")
            self.assertNotIn("- parallel:", pipelines)
            self.assertIn("image: node:22-slim", pipelines)
            self.assertIn('[ -f "package.json" ]', pipelines)
            self.assertIn("- node", pipelines)
            self.assertNotIn("- npm", pipelines)

            # GitLab CI also keeps a single deduplicated node-workspace job
            gl_dir = Path(tmp) / "next-node-gl"
            _run_init(
                gl_dir,
                "--frontend",
                "nextjs-ts",
                "--backend",
                "node-express-ts",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "gitlab",
            )
            gitlab_ci = (gl_dir / ".gitlab-ci.yml").read_text(encoding="utf-8")
            self.assertEqual(gitlab_ci.count("node-workspace:"), 1)
            self.assertIn("[ -f package.json ]", gitlab_ci)

            # Hook scripts staged and executable
            fe_hook = out_dir / ".githooks" / "pre-commit.d" / "20-frontend-check.sh"
            node_hook = out_dir / ".githooks" / "pre-commit.d" / "30-node-check.sh"
            self.assertTrue(fe_hook.is_file())
            self.assertTrue(node_hook.is_file())
            self.assertTrue(os.access(fe_hook, os.X_OK))
            self.assertTrue(os.access(node_hook, os.X_OK))

            # Commit with staged .ts file executes both pre-commit hooks cleanly without tsc installed
            _git_init(out_dir)
            subprocess.run(["git", "-C", str(out_dir), "config", "core.hooksPath", ".githooks"], check=True)
            subprocess.run(
                ["git", "-C", str(out_dir), "checkout", "-b", "feature/issue-2-hooks"],
                check=True,
                capture_output=True,
            )
            (out_dir / "app").mkdir()
            (out_dir / "app" / "page.tsx").write_text("export default function Page() { return null; }\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(out_dir), "add", "app/page.tsx"], check=True, capture_output=True)
            commit_proc = subprocess.run(
                ["git", "-C", str(out_dir), "commit", "-m", "feat(#2): add page"],
                cwd=out_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(commit_proc.returncode, 0, msg=commit_proc.stderr + commit_proc.stdout)

    def test_nextjs_ts_staging_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "next-only"
            _run_init(
                out_dir,
                "--frontend",
                "nextjs-ts",
                "--backend",
                "none",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
            )

            agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("frontend-nextjs-ts/SKILL.md", agents_md)
            self.assertLess(len(agents_md.encode("utf-8")), agy_init.MAX_AGENTS_MD_BYTES)

            stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
            for cmd in ("npx tsc --noEmit", "npm run lint", "npm test", "npm run build"):
                self.assertIn(cmd, stack_profile)
            self.assertIn("Core Web Vitals", stack_profile)

            gitignore = (out_dir / ".gitignore").read_text(encoding="utf-8")
            for pattern in ("node_modules/", ".next/", "out/", "next-env.d.ts"):
                self.assertIn(pattern, gitignore)

            env_example = (out_dir / ".env.example").read_text(encoding="utf-8")
            self.assertIn('NEXT_PUBLIC_APP_NAME="App Stack Test"', env_example)

            pr_template = (out_dir / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
            self.assertIn("Core Web Vitals", pr_template)

    def test_go_service_staging_and_ci_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "go-gh"
            _run_init(
                out_dir,
                "--frontend",
                "nextjs-ts",
                "--backend",
                "go-service",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
            )

            manifest = json.loads((out_dir / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("frontend-nextjs-ts", manifest["active_skills"])
            self.assertIn("backend-go-service", manifest["active_skills"])
            self.assertTrue((out_dir / ".agents" / "skills" / "backend-go-service" / "SKILL.md").is_file())

            ci_yml = (out_dir / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("node-workspace:", ci_yml)
            self.assertIn("backend-go:", ci_yml)
            self.assertIn("uses: actions/setup-go@v5", ci_yml)
            self.assertIn('go-version: "1.23"', ci_yml)
            self.assertIn("hashFiles('go.sum')", ci_yml)
            self.assertIn('[ -f "go.mod" ]', ci_yml)
            self.assertIn("go vet ./...", ci_yml)
            self.assertIn("golangci-lint run", ci_yml)
            self.assertIn("go test -race ./...", ci_yml)

            dependabot = (out_dir / ".github" / "dependabot.yml").read_text(encoding="utf-8")
            self.assertIn('- package-ecosystem: "npm"', dependabot)
            self.assertIn('- package-ecosystem: "gomod"', dependabot)

            stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
            for cmd in ("go vet ./...", "golangci-lint run", "go test -race ./..."):
                self.assertIn(cmd, stack_profile)
            self.assertIn("Go Service Architecture, Context & Concurrency Evaluator", stack_profile)

            agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("backend-go-service/SKILL.md", agents_md)
            self.assertLess(len(agents_md.encode("utf-8")), agy_init.MAX_AGENTS_MD_BYTES)

            gitignore = (out_dir / ".gitignore").read_text(encoding="utf-8")
            for pattern in ("bin/", "coverage.out", "*.test"):
                self.assertIn(pattern, gitignore)

            bb_dir = Path(tmp) / "go-bb"
            _run_init(
                bb_dir,
                "--frontend",
                "none",
                "--backend",
                "go-service",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "jira",
                "--jira-key",
                "GOAPI",
                "--git-hosting",
                "bitbucket",
            )
            pipelines = (bb_dir / "bitbucket-pipelines.yml").read_text(encoding="utf-8")
            self.assertIn("image: golang:1.23", pipelines)
            self.assertIn("definitions:\n  caches:\n    gomod: /go/pkg/mod", pipelines)
            self.assertIn("- gomod", pipelines)
            self.assertIn('[ -f "go.mod" ]', pipelines)
            self.assertIn("go test -race ./...", pipelines)

    def test_java_spring_staging_and_ci_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "spring-gh"
            _run_init(
                out_dir,
                "--frontend",
                "none",
                "--backend",
                "java-spring",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
            )

            manifest = json.loads((out_dir / ".agy-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("backend-java-spring", manifest["active_skills"])
            self.assertTrue((out_dir / ".agents" / "skills" / "backend-java-spring" / "SKILL.md").is_file())

            ci_yml = (out_dir / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("backend-java:", ci_yml)
            self.assertIn("actions/setup-java@v4", ci_yml)
            self.assertIn('java-version: "21"', ci_yml)
            self.assertIn('[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]', ci_yml)
            self.assertIn("./mvnw -B test", ci_yml)
            self.assertIn("./gradlew test --no-daemon", ci_yml)

            dependabot = (out_dir / ".github" / "dependabot.yml").read_text(encoding="utf-8")
            self.assertIn('- package-ecosystem: "maven"', dependabot)

            stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
            self.assertIn("./mvnw test", stack_profile)
            self.assertIn("./gradlew test", stack_profile)
            self.assertIn("Java 21+ / Spring Boot Architecture, Security & Data Evaluator", stack_profile)

            agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("backend-java-spring/SKILL.md", agents_md)

            gitignore = (out_dir / ".gitignore").read_text(encoding="utf-8")
            for pattern in ("target/", "build/", ".gradle/", "*.class"):
                self.assertIn(pattern, gitignore)

            bb_dir = Path(tmp) / "spring-bb"
            _run_init(
                bb_dir,
                "--frontend",
                "nextjs-ts",
                "--backend",
                "java-spring",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "bitbucket",
            )
            pipelines = (bb_dir / "bitbucket-pipelines.yml").read_text(encoding="utf-8")
            self.assertIn("- parallel:", pipelines)
            self.assertIn("image: node:22-slim", pipelines)
            self.assertIn("image: eclipse-temurin:21-jdk", pipelines)
            self.assertIn('[ -f "pom.xml" ] || [ -f "build.gradle" ] || [ -f "build.gradle.kts" ]', pipelines)

    def test_day0_ci_guard_conditions_skip_cleanly_without_manifests(self) -> None:
        catalog = agy_init.load_catalog()
        with tempfile.TemporaryDirectory() as empty_dir:
            for category, mod_id in (
                ("frontend", "nextjs-ts"),
                ("backend", "go-service"),
                ("backend", "java-spring"),
            ):
                job = catalog.modules[category][mod_id].raw["ci_jobs"][0]
                guard_cond = " || ".join(f'[ -f "{p}" ]' for p in job["guard_files"])
                for step in job["steps"]:
                    step_run = step["run"]
                    self.assertNotIn("\n", step_run, f"{mod_id} step '{step['name']}' must be single-line")
                    script = (
                        f"if {guard_cond}; then\n"
                        f"  {step_run}\n"
                        f"else\n"
                        f"  echo 'Day-0 skip'\n"
                        f"fi\n"
                    )
                    proc = subprocess.run(
                        ["bash", "-euo", "pipefail", "-c", script],
                        cwd=empty_dir,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
                    self.assertIn("Day-0 skip", proc.stdout)

    def test_go_pre_commit_hook_executes_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "go-repo"
            _run_init(
                repo,
                "--frontend",
                "none",
                "--backend",
                "go-service",
                "--data",
                "none",
                "--cloud",
                "none",
                "--issue-tracker",
                "github-issues",
                "--git-hosting",
                "github",
            )
            _git_init(repo)
            subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature/issue-1-init"], check=True, capture_output=True)

            go_hook = repo / ".githooks" / "pre-commit.d" / "30-go-check.sh"
            self.assertTrue(go_hook.is_file())
            self.assertTrue(os.access(go_hook, os.X_OK))

            # Commit with no .go files should succeed immediately
            (repo / "README.custom.txt").write_text("day0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.custom.txt"], check=True, capture_output=True)
            ok_no_go = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "chore(#1): add readme note"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok_no_go.returncode, 0, msg=ok_no_go.stderr + ok_no_go.stdout)

            # Deterministic check with a stub gofmt binary on PATH (and real gofmt if installed)
            fake_bin = Path(tmp) / "fake-bin"
            fake_bin.mkdir()
            stub_gofmt = fake_bin / "gofmt"
            stub_gofmt.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"-l\" ]] && grep -q 'func main(){' \"$2\"; then\n"
                "  echo \"$2\"\n"
                "fi\n",
                encoding="utf-8",
            )
            stub_gofmt.chmod(0o755)
            hook_env = dict(os.environ, PATH=f"{fake_bin}:{os.environ.get('PATH', '')}")

            bad_go = repo / "main.go"
            bad_go.write_text("package main\nfunc main(){println(1)}\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "main.go"], check=True, capture_output=True)
            fail_fmt = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(#1): unformatted go"],
                cwd=repo,
                env=hook_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(fail_fmt.returncode, 0)
            self.assertIn("not gofmt-formatted", fail_fmt.stderr)

            bad_go.write_text("package main\n\nfunc main() {\n\tprintln(1)\n}\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "main.go"], check=True, capture_output=True)
            ok_fmt = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(#1): formatted go"],
                cwd=repo,
                env=hook_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(ok_fmt.returncode, 0, msg=ok_fmt.stderr + ok_fmt.stdout)

            # Stub gofmt returning non-zero exit code (syntax error) must fail the commit
            stub_gofmt.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'syntax error' >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            stub_gofmt.chmod(0o755)
            bad_go.write_text("package main\nfunc broken(\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "main.go"], check=True, capture_output=True)
            fail_syntax = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(#1): go syntax error"],
                cwd=repo,
                env=hook_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(fail_syntax.returncode, 0)

            # When gofmt is absent from PATH, hook skips cleanly (Day-0 compatibility)
            no_go_bin = Path(tmp) / "empty-bin"
            no_go_bin.mkdir()
            for tool in ("git", "grep", "bash"):
                tool_path = shutil.which(tool)
                if tool_path:
                    (no_go_bin / tool).symlink_to(tool_path)
            no_gofmt_env = dict(os.environ, PATH=f"{no_go_bin}:/usr/bin:/bin")
            if shutil.which("gofmt") is None:
                skip_res = subprocess.run(
                    ["bash", str(go_hook)],
                    cwd=repo,
                    env=no_gofmt_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(skip_res.returncode, 0, msg=skip_res.stderr + skip_res.stdout)
            else:
                skip_res = subprocess.run(
                    ["bash", str(go_hook)],
                    cwd=repo,
                    env=dict(os.environ, PATH=str(no_go_bin)),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(skip_res.returncode, 0, msg=skip_res.stderr + skip_res.stdout)

    def test_java_spring_missing_build_tool_fails_when_manifest_present(self) -> None:
        catalog = agy_init.load_catalog()
        job = catalog.modules["backend"]["java-spring"].raw["ci_jobs"][0]
        step_run = job["steps"][0]["run"]
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "pom.xml").write_text("<project/>\n", encoding="utf-8")
            # Minimal PATH without mvn or ./mvnw
            empty_bin = project / "empty-bin"
            empty_bin.mkdir()
            res = subprocess.run(
                ["/bin/bash", "-euo", "pipefail", "-c", step_run],
                cwd=project,
                env={"PATH": str(empty_bin)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("neither ./mvnw nor mvn is available", res.stderr)

            (project / "pom.xml").unlink()
            (project / "build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
            res_gradle = subprocess.run(
                ["/bin/bash", "-euo", "pipefail", "-c", step_run],
                cwd=project,
                env={"PATH": str(empty_bin)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(res_gradle.returncode, 0)
            self.assertIn("neither ./gradlew nor gradle is available", res_gradle.stderr)

    def test_inplace_init_nextjs_and_java_spring_prunes_scaffolding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "template-fork"
            shutil.copytree(
                REPO_ROOT,
                repo,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
            )
            _git_init(repo)

            proc = subprocess.run(
                [
                    str(repo / "agy-init"),
                    "--project-name",
                    "Spring Next Portal",
                    "--frontend",
                    "nextjs-ts",
                    "--backend",
                    "java-spring",
                    "--data",
                    "none",
                    "--cloud",
                    "none",
                    "--issue-tracker",
                    "jira",
                    "--jira-key",
                    "SNP",
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
            self.assertFalse((repo / "modules").exists())
            self.assertFalse((repo / "core").exists())
            self.assertTrue((repo / ".agents" / "skills" / "frontend-nextjs-ts" / "SKILL.md").is_file())
            self.assertTrue((repo / ".agents" / "skills" / "backend-java-spring" / "SKILL.md").is_file())
            self.assertLess((repo / "AGENTS.md").stat().st_size, agy_init.MAX_AGENTS_MD_BYTES)


if __name__ == "__main__":
    unittest.main()
