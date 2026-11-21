#!/usr/bin/env python3
"""Automated test suite for postgres, supabase, and alloydb data modules."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGY_INIT = REPO_ROOT / "agy-init"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import agy_init  # noqa: E402

NEW_DATA_MODULES = ("postgres", "supabase", "alloydb")

MODULE_EXPECTATIONS = {
    "postgres": {
        "skill": "data-postgres",
        "evaluator": "PostgreSQL Data, Query Safety & Migration Evaluator",
        "env_tokens": [
            "# PostgreSQL",
            'DATABASE_URL="postgresql://postgres:replace-with-local-dev-password@localhost:5432/order-platform?sslmode=disable"',
            'POSTGRES_DB="order-platform"',
            'DB_POOL_MIN="2"',
            'DB_POOL_MAX="10"',
        ],
        "gitignore": ["pgdata/"],
        "rule_ids": {
            "confirm-postgres-destructive-cli",
            "confirm-postgres-destructive-sql",
            "confirm-postgres-piped-destructive-sql",
        },
    },
    "supabase": {
        "skill": "data-supabase",
        "evaluator": "Supabase Auth & PostgreSQL RLS Security Evaluator",
        "env_tokens": [
            "# Supabase",
            'SUPABASE_URL="http://127.0.0.1:54321"',
            'SUPABASE_ANON_KEY=""',
            'SUPABASE_SERVICE_ROLE_KEY=""',
            'SUPABASE_DB_URL=""',
            'SUPABASE_PROJECT_REF=""',
        ],
        "gitignore": ["supabase/.temp/", "supabase/.branches/"],
        "rule_ids": {
            "confirm-supabase-db-push",
            "confirm-supabase-destructive-remote",
        },
    },
    "alloydb": {
        "skill": "data-alloydb",
        "evaluator": "AlloyDB Data, Security & Performance Evaluator",
        "env_tokens": [
            "# Google Cloud AlloyDB for PostgreSQL",
            'ALLOYDB_CONNECTION_NAME="projects/PROJECT_ID/locations/us-central1/clusters/order-platform-cluster/instances/order-platform-primary"',
            'ALLOYDB_USER=""',
            'ALLOYDB_DB="order-platform"',
            'ALLOYDB_USE_IAM_AUTH="true"',
            'ALLOYDB_DATABASE_URL="postgresql://127.0.0.1:5432/order-platform"',
        ],
        "gitignore": [],
        "rule_ids": {
            "confirm-alloydb-destructive-delete",
            "confirm-alloydb-topology-mutation",
        },
    },
}


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


def _init_project(
    out_dir: Path,
    data_selection: str,
    project_name: str = "Order Platform",
    backend: str = "python-fastapi",
    cloud: str = "none",
) -> Path:
    proc = subprocess.run(
        [
            str(AGY_INIT),
            "--project-name",
            project_name,
            "--frontend",
            "none",
            "--backend",
            backend,
            "--data",
            data_selection,
            "--cloud",
            cloud,
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
    if proc.returncode != 0:
        raise AssertionError(f"agy-init failed ({proc.returncode}):\n{proc.stderr}\n{proc.stdout}")
    return out_dir


def _run_guard(workspace_dir: Path, command_line: str) -> dict[str, str]:
    guard_script = workspace_dir / ".agents" / "hooks" / "pre_tool_guard.py"
    payload = {
        "toolCall": {"name": "run_command", "args": {"CommandLine": command_line}},
        "workspacePaths": [str(workspace_dir)],
        "cwd": str(workspace_dir),
    }
    proc = subprocess.run(
        [sys.executable, str(guard_script)],
        cwd=workspace_dir / ".agents",
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


class TestDataModules(unittest.TestCase):
    def test_catalog_discovers_and_validates_new_data_modules(self) -> None:
        val_proc = subprocess.run(
            [str(AGY_INIT), "--validate-catalog"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(val_proc.returncode, 0, msg=val_proc.stderr + val_proc.stdout)

        list_proc = subprocess.run(
            [str(AGY_INIT), "--list-modules", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(list_proc.returncode, 0, msg=list_proc.stderr)
        payload = json.loads(list_proc.stdout)

        data_cat = next(c for c in payload["categories"] if c["id"] == "data")
        self.assertEqual(data_cat["selection"], "multi_optional")

        data_mods = {mod["id"]: mod for mod in payload["modules"]["data"]}
        for mod_id in ("firebase", *NEW_DATA_MODULES):
            self.assertIn(mod_id, data_mods)

        for mod_id in NEW_DATA_MODULES:
            mod = data_mods[mod_id]
            self.assertEqual(mod["category"], "data")
            self.assertTrue(mod.get("verification_commands"), f"{mod_id} missing verification_commands")
            self.assertTrue(mod.get("evaluators"), f"{mod_id} missing evaluators")
            self.assertTrue(mod.get("single_concurrency_locks"), f"{mod_id} missing single_concurrency_locks")
            self.assertTrue(mod.get("pr_checklist"), f"{mod_id} missing pr_checklist")
            self.assertTrue(mod.get("agents_md_rules"), f"{mod_id} missing agents_md_rules")
            self.assertTrue(mod.get("env_example"), f"{mod_id} missing env_example")

    def test_skill_frontmatter_and_markdown_hygiene(self) -> None:
        for mod_id, spec in MODULE_EXPECTATIONS.items():
            mod_dir = REPO_ROOT / "modules" / "data" / mod_id
            skill_md = mod_dir / "skills" / spec["skill"] / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"Missing {skill_md}")

            fm = agy_init.parse_skill_frontmatter(skill_md)
            self.assertEqual(fm.get("name"), spec["skill"])
            self.assertRegex(fm.get("name", ""), r"^[a-z0-9-]+$")

            desc = fm.get("description", "")
            self.assertTrue(desc, f"{skill_md} description must be non-empty")
            self.assertFalse(
                desc.lower().startswith(("use this", "you ", "i ", "we ")),
                f"{skill_md} description must be third-person: {desc}",
            )

            for md_file in mod_dir.rglob("*.md"):
                content = md_file.read_text(encoding="utf-8")
                self.assertNotIn("file:///", content, f"Machine-local file:/// link in {md_file}")

    def test_guard_rules_schema_uniqueness_and_regex_safety(self) -> None:
        core_rules = agy_init.load_json(REPO_ROOT / "core" / "hooks" / "guard_rules.core.json")["command_rules"]
        seen_ids = {r["id"] for r in core_rules}

        adversarial_inputs = [
            "psql " * 1500,
            "; echo DROP TABLE " * 1000,
            "; psql -c '" * 1000,
            "; psql -a -b -c -d -e -f -g -h -i -j -k -l " * 400,
            "A=1 " * 1500,
            "docker compose exec -a -b -c -d db " * 400,
            "supabase db reset " + "--flag " * 1500,
            "gcloud alpha alloydb clusters " * 400,
            "echo " + "DROP TABLE " * 1000,
            'git commit -m \'' + "dropdb supabase db push gcloud alloydb " * 250 + "'",
        ]

        for guard_path in sorted((REPO_ROOT / "modules").glob("*/*/hooks/guard_rules.json")):
            errors: list[str] = []
            agy_init.validate_guard_rules_file(guard_path, errors)
            self.assertEqual(errors, [], f"Guard validation errors in {guard_path}: {errors}")

            rules = agy_init.load_json(guard_path)["command_rules"]
            for rule in rules:
                self.assertNotIn(rule["id"], seen_ids, f"Duplicate rule id: {rule['id']}")
                seen_ids.add(rule["id"])

                for key in ("pattern", "exclude_pattern"):
                    pat = rule.get(key)
                    if not pat:
                        continue
                    compiled = re.compile(pat)
                    for sample in adversarial_inputs:
                        start = time.perf_counter()
                        compiled.search(sample)
                        elapsed_ms = (time.perf_counter() - start) * 1000.0
                        self.assertLess(
                            elapsed_ms,
                            20.0,
                            f"Regex backtracking risk in {guard_path} ({rule['id']}.{key}): {elapsed_ms:.1f}ms",
                        )

    def test_individual_module_staging_and_env_example(self) -> None:
        for mod_id, exp in MODULE_EXPECTATIONS.items():
            with self.subTest(module=mod_id), tempfile.TemporaryDirectory() as tmp:
                out_dir = _init_project(Path(tmp) / f"app-{mod_id}", data_selection=mod_id)

                manifest = json.loads((out_dir / ".agy-manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["selected_modules"]["data"], [mod_id])
                self.assertIn(exp["skill"], manifest["active_skills"])

                staged_skill = out_dir / ".agents" / "skills" / exp["skill"] / "SKILL.md"
                self.assertTrue(staged_skill.is_file())
                self.assertNotRegex(staged_skill.read_text(encoding="utf-8"), r"\{\{[A-Z0-9_]+\}\}")

                agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
                self.assertIn(f".agents/skills/{exp['skill']}/SKILL.md", agents_md)
                self.assertNotIn("](file:///", agents_md)
                self.assertLess(len(agents_md.encode("utf-8")), agy_init.MAX_AGENTS_MD_BYTES)

                stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
                self.assertIn(exp["evaluator"], stack_profile)
                self.assertIn("order-platform", stack_profile)
                self.assertNotIn("{{PROJECT_SLUG}}", stack_profile)

                env_example = (out_dir / ".env.example").read_text(encoding="utf-8")
                for token in exp["env_tokens"]:
                    self.assertIn(token, env_example)

                gitignore = (out_dir / ".gitignore").read_text(encoding="utf-8")
                for ignore_line in exp["gitignore"]:
                    self.assertIn(ignore_line, gitignore)

                pr_tmpl = (out_dir / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
                mod_json = agy_init.load_json(REPO_ROOT / "modules" / "data" / mod_id / "module.json")
                for item in mod_json["pr_checklist"]:
                    self.assertIn(item, pr_tmpl)

                guard_rules = agy_init.load_json(out_dir / ".agents" / "hooks" / "guard_rules.json")["command_rules"]
                staged_ids = {r["id"] for r in guard_rules}
                self.assertTrue(exp["rule_ids"].issubset(staged_ids))

    def test_multiselect_data_combinations(self) -> None:
        combos = [
            "postgres,alloydb",
            "postgres,supabase",
            "firebase,supabase",
            "firebase,postgres,supabase,alloydb",
        ]
        for combo in combos:
            expected_mods = combo.split(",")
            with self.subTest(data=combo), tempfile.TemporaryDirectory() as tmp:
                out_dir = _init_project(Path(tmp) / "combo-app", data_selection=combo, cloud="gcp-cloudrun")

                manifest = json.loads((out_dir / ".agy-manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["selected_modules"]["data"], expected_mods)

                agents_md = (out_dir / "AGENTS.md").read_text(encoding="utf-8")
                self.assertLess(len(agents_md.encode("utf-8")), agy_init.MAX_AGENTS_MD_BYTES)

                env_example = (out_dir / ".env.example").read_text(encoding="utf-8")
                declared_env_keys = [
                    line.split("=", 1)[0].strip()
                    for line in env_example.splitlines()
                    if line.strip() and not line.strip().startswith("#") and "=" in line
                ]
                self.assertEqual(
                    len(declared_env_keys),
                    len(set(declared_env_keys)),
                    f"Duplicate .env.example keys for {combo}: {declared_env_keys}",
                )
                stack_profile = (out_dir / ".agents" / "stack-profile.md").read_text(encoding="utf-8")
                staged_guard_ids = {
                    r["id"]
                    for r in agy_init.load_json(out_dir / ".agents" / "hooks" / "guard_rules.json")["command_rules"]
                }

                for mod_id in expected_mods:
                    if mod_id == "firebase":
                        self.assertIn("firebase-platform", manifest["active_skills"])
                        self.assertIn("firestore-security-auditor", manifest["active_skills"])
                        self.assertIn("FIREBASE_PROJECT_ID", env_example)
                        self.assertIn("confirm-firebase-destructive-delete", staged_guard_ids)
                        continue

                    exp = MODULE_EXPECTATIONS[mod_id]
                    self.assertIn(exp["skill"], manifest["active_skills"])
                    self.assertIn(f".agents/skills/{exp['skill']}/SKILL.md", agents_md)
                    self.assertIn(exp["evaluator"], stack_profile)
                    for token in exp["env_tokens"]:
                        self.assertIn(token, env_example)
                    self.assertTrue(exp["rule_ids"].issubset(staged_guard_ids))

    def test_inplace_init_pruning_and_githooks_with_new_data_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _copy_template_repo(Path(tmp))
            _git_init(repo)

            proc = subprocess.run(
                [
                    str(repo / "agy-init"),
                    "--project-name",
                    "Analytics Core",
                    "--frontend",
                    "none",
                    "--backend",
                    "python-fastapi",
                    "--data",
                    "postgres,supabase,alloydb",
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

            for pruned in ("modules", "core", "tests", "agy-init", "CONTRIBUTING_MODULES.md"):
                self.assertFalse((repo / pruned).exists(), f"{pruned} should have been pruned")

            for skill in ("data-postgres", "data-supabase", "data-alloydb"):
                self.assertTrue((repo / ".agents" / "skills" / skill / "SKILL.md").is_file())

            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/42-data-harness"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
            commit_proc = subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "feat(#42): initialize data governance harness"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(commit_proc.returncode, 0, msg=commit_proc.stderr + commit_proc.stdout)

    def test_pre_tool_guard_contracts_postgres(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _init_project(Path(tmp) / "pg-app", data_selection="postgres")

            should_gate = [
                "dropdb prod_db",
                "PGPASSWORD=local dropdb app_db",
                "echo ok && dropdb app_db",
                "echo ok\ndropdb prod_db",
                "docker compose exec -T db dropdb prod_db",
                "pg_restore --clean -d app_db dump.bak",
                "pg_restore -c -d app_db dump.bak",
                "flyway clean",
                "npx prisma migrate reset",
                "npx -y prisma migrate reset",
                "pnpm dlx drizzle-kit drop",
                "bunx prisma db push --force-reset",
                "prisma db push --force-reset",
                "prisma db push --accept-data-loss",
                "alembic downgrade base",
                "alembic -c prod.ini downgrade base",
                "npx drizzle-kit drop",
                'psql "$DATABASE_URL" -c "DROP DATABASE app;"',
                'psql "$DATABASE_URL" -c "BEGIN; DROP TABLE users; COMMIT;"',
                'psql -c "SET lock_timeout = \'2s\'; DROP TABLE users;"',
                'psql -c "drop table users;"',
                'psql -c"DROP TABLE users;"',
                'psql --command="BEGIN; DROP TABLE users;"',
                'psql -c "TRUNCATE TABLE sessions;"',
                'DATABASE_URL=postgres://localhost/app psql -c "DROP SCHEMA public CASCADE;"',
                'docker compose exec -T db psql -U postgres -c "DROP TABLE orders;"',
                'docker compose exec -u postgres db psql -c "DROP TABLE users;"',
                'docker exec -e PGPASSWORD=x db psql -c "TRUNCATE TABLE sessions;"',
                'echo "DROP DATABASE app;" | psql "$DATABASE_URL"',
                'echo -e "DROP TABLE users;" | psql',
                'echo "BEGIN; DROP TABLE users;" | psql',
                'printf "%s\\n" "DROP TABLE users;" | psql',
                "printf 'TRUNCATE users;' | docker exec -i db psql -U postgres",
                'echo ok\npsql -c "DROP TABLE users;"',
            ]
            for cmd in should_gate:
                with self.subTest(gated_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "force_ask", msg=f"Expected force_ask for: {cmd} -> {res}")

            should_allow = [
                'pg_isready -d "postgresql://127.0.0.1:5432/order-platform"',
                'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT 1;"',
                "psql -f migrations/001_init.sql",
                'psql -c "SELECT 1;" && echo "DROP TABLE"',
                'echo "DROP TABLE docs" && echo "SELECT 1;" | psql',
                'echo "DROP TABLE reminder"; cat healthcheck.sql | psql',
                "pg_dump -Fc app_db > app.dump",
                "pg_restore -Fc -d app_db app.dump",
                "alembic upgrade head",
                "alembic downgrade -1",
                "prisma migrate dev --create-only",
                'git commit -m "docs: warn against dropdb and DROP TABLE"',
            ]
            for cmd in should_allow:
                with self.subTest(allowed_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "allow", msg=f"Expected allow for: {cmd} -> {res}")

    def test_pre_tool_guard_contracts_supabase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _init_project(Path(tmp) / "sb-app", data_selection="supabase")

            should_gate = [
                "supabase db push",
                "supabase db push --linked",
                "npx -y supabase db push",
                "pnpm dlx supabase --workdir ./app db push",
                "bunx supabase db push --linked",
                "supabase db push --dry-run && supabase db push",
                'echo "--dry-run" && supabase db push',
                "echo ok\nsupabase db push",
                "SUPABASE_ACCESS_TOKEN=tok supabase db push",
                "echo ready && supabase db push --linked",
                "supabase db reset --linked",
                "supabase --workdir ./app db reset --linked",
                "supabase db reset --db-url postgresql://postgres@db.example.supabase.co:5432/postgres",
                "supabase projects delete abcdefghijklmnopqrst",
                "supabase functions delete billing-webhook",
                "supabase secrets unset STRIPE_SECRET_KEY",
                "supabase migration repair --status reverted 20240101000000",
            ]
            for cmd in should_gate:
                with self.subTest(gated_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "force_ask", msg=f"Expected force_ask for: {cmd} -> {res}")

            should_allow = [
                "supabase start",
                "supabase stop",
                "supabase status",
                "supabase db reset",
                "supabase db reset --local",
                "supabase test db",
                "supabase db push --dry-run",
                "supabase db push --linked --dry-run",
                "supabase migration new add_orders_rls",
                'git commit -m "docs: guard supabase db push and linked reset"',
            ]
            for cmd in should_allow:
                with self.subTest(allowed_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "allow", msg=f"Expected allow for: {cmd} -> {res}")

    def test_pre_tool_guard_contracts_alloydb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = _init_project(Path(tmp) / "alloy-app", data_selection="alloydb", cloud="gcp-cloudrun")

            should_gate = [
                "gcloud alloydb clusters delete prod-cluster --region=us-central1",
                "gcloud --project=prod alloydb clusters delete prod-cluster --region=us-central1",
                "gcloud -q alloydb instances delete prod-primary --cluster=prod-cluster --region=us-central1",
                "gcloud beta alloydb instances delete prod-primary --cluster=prod-cluster --region=us-central1",
                "gcloud alloydb backups delete daily-bkp --region=us-central1",
                "gcloud alpha alloydb users delete app-sa --cluster=prod-cluster --region=us-central1",
                "CLOUDSDK_CORE_PROJECT=prod gcloud alloydb clusters delete prod-cluster --region=us-central1",
                "echo ok && gcloud alloydb instances failover prod-primary --cluster=prod-cluster --region=us-central1",
                "echo ok\ngcloud alloydb instances failover prod-primary --cluster=prod-cluster --region=us-central1",
                "gcloud --project=prod beta alloydb clusters promote secondary-cluster --region=us-east1",
                "gcloud alloydb clusters restore prod-cluster --backup=daily-bkp --region=us-central1",
            ]
            for cmd in should_gate:
                with self.subTest(gated_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "force_ask", msg=f"Expected force_ask for: {cmd} -> {res}")

            should_allow = [
                "gcloud alloydb clusters list --region=us-central1",
                "gcloud alloydb instances describe prod-primary --cluster=prod-cluster --region=us-central1",
                "gcloud alloydb clusters create dev-cluster --region=us-central1",
                "alloydb-auth-proxy projects/p/locations/us-central1/clusters/c/instances/i --auto-iam-authn",
                'git commit -m "docs: guard gcloud alloydb clusters delete"',
            ]
            for cmd in should_allow:
                with self.subTest(allowed_cmd=cmd):
                    res = _run_guard(ws, cmd)
                    self.assertEqual(res["decision"], "allow", msg=f"Expected allow for: {cmd} -> {res}")


if __name__ == "__main__":
    unittest.main()
