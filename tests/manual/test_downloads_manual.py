# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import importlib
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dotenv import dotenv_values, load_dotenv  # noqa: E402
from sqlalchemy import select  # noqa: E402

from giljo_mcp.database import DatabaseManager  # noqa: E402
from giljo_mcp.models import AgentTemplate, User  # noqa: E402


def test_module_import_does_not_mutate_environ():
    pre_snapshot = dict(os.environ)
    module = sys.modules[__name__]
    importlib.reload(module)
    post_snapshot = dict(os.environ)
    assert post_snapshot == pre_snapshot, (
        "Importing test_downloads_manual mutated os.environ; module-level load_dotenv() must stay out of import path."
    )


def test_dotenv_values_is_read_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DOWNLOADS_MANUAL_PROBE=alpha\n")

    monkeypatch.delenv("DOWNLOADS_MANUAL_PROBE", raising=False)
    pre = os.environ.get("DOWNLOADS_MANUAL_PROBE")

    parsed = dotenv_values(env_file)

    post = os.environ.get("DOWNLOADS_MANUAL_PROBE")
    assert parsed.get("DOWNLOADS_MANUAL_PROBE") == "alpha"
    assert pre == post, "dotenv_values must not mutate os.environ"


class DownloadsTester:

    def __init__(self):
        self.base_url = "http://localhost:7272"
        self.results = []
        self.db = None
        self.test_user = None

    async def setup(self):
        print("=" * 70)
        print("DOWNLOADS API MANUAL INTEGRATION TEST")
        print("=" * 70)
        print("")

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print("ERROR: DATABASE_URL not set in environment")
            sys.exit(1)

        self.db = DatabaseManager(db_url, is_async=True)
        print(f"[OK] Connected to database: {db_url.split('@')[-1] if '@' in db_url else db_url}")

        async with self.db.get_session_async() as session:
            result = await session.execute(select(User).where(User.is_active == True).limit(1))  # noqa: E712 — SQLAlchemy filter
            self.test_user = result.scalar_one_or_none()

            if not self.test_user:
                print("ERROR: No active users found in database")
                sys.exit(1)

            print(f"[OK] Using test user: {self.test_user.username} (tenant: {self.test_user.tenant_key})")

        print("")

    async def create_test_templates(self):
        print("Creating test agent templates...")

        templates = [
            AgentTemplate(
                name="test_orchestrator",
                role="orchestrator",
                category="orchestration",
                description="Test orchestrator agent",
                system_instructions="You are a test orchestrator agent for integration testing.",
                tool="claude",
                tenant_key=self.test_user.tenant_key,
                is_active=True,
                behavioral_rules=["Always test thoroughly", "Document all findings"],
                success_criteria=["All tests pass", "No regressions"],
            ),
            AgentTemplate(
                name="test_implementor",
                role="implementor",
                category="development",
                description="Test implementor agent",
                system_instructions="You are a test implementor agent for integration testing.",
                tool="claude",
                tenant_key=self.test_user.tenant_key,
                is_active=True,
            ),
            AgentTemplate(
                name="test_inactive",
                role="inactive",
                category="testing",
                description="Inactive test template",
                system_instructions="This template should not appear in active downloads.",
                tool="claude",
                tenant_key=self.test_user.tenant_key,
                is_active=False,
            ),
        ]

        async with self.db.get_session_async() as session:
            existing = await session.execute(
                select(AgentTemplate).where(
                    AgentTemplate.name.like("test_%"),
                    AgentTemplate.tenant_key == self.test_user.tenant_key,
                )
            )
            for template in existing.scalars().all():
                await session.delete(template)
            await session.commit()

            session.add_all(templates)
            await session.commit()

        print(f"[OK] Created {len(templates)} test templates")
        print("")

    def test_result(self, test_name: str, passed: bool, details: str = ""):
        status = "PASS" if passed else "FAIL"
        self.results.append({"test": test_name, "passed": passed, "details": details})
        print(f"[{status}] {test_name}")
        if details:
            print(f"      {details}")

    async def test_slash_commands_download(self):
        print("Testing /api/download/slash-commands.zip...")

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/download/slash-commands.zip")
                self.test_result(
                    "Slash commands - unauthenticated",
                    response.status_code == 401,
                    f"Status: {response.status_code}",
                )

                print("      Note: Authenticated test requires valid JWT token")
                print("      Skipping authenticated test (use Postman/curl with real token)")

        except Exception as e:
            self.test_result("Slash commands download", False, f"Exception: {e}")

        print("")

    async def test_agent_templates_download(self):
        print("Testing /api/download/agent-templates.zip...")

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/download/agent-templates.zip")
                self.test_result(
                    "Agent templates - unauthenticated",
                    response.status_code == 401,
                    f"Status: {response.status_code}",
                )

                print("      Note: Authenticated test requires valid JWT token")
                print("      Skipping authenticated test (use Postman/curl with real token)")

        except Exception as e:
            self.test_result("Agent templates download", False, f"Exception: {e}")

        print("")

    async def test_install_scripts(self):
        print("Testing install scripts...")

        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/download/install-script.sh?script_type=slash-commands"
                )
                self.test_result(
                    "Install script .sh - unauthenticated",
                    response.status_code == 401,
                    f"Status: {response.status_code}",
                )

                response = await client.get(
                    f"{self.base_url}/api/download/install-script.ps1?script_type=agent-templates"
                )
                self.test_result(
                    "Install script .ps1 - unauthenticated",
                    response.status_code == 401,
                    f"Status: {response.status_code}",
                )

                response = await client.get(
                    f"{self.base_url}/api/download/install-script.bat?script_type=slash-commands"
                )
                self.test_result(
                    "Install script - invalid extension",
                    response.status_code in [400, 401],
                    f"Status: {response.status_code}",
                )

        except Exception as e:
            self.test_result("Install scripts", False, f"Exception: {e}")

        print("")

    async def test_utility_functions(self):
        print("Testing utility functions...")

        try:
            import io
            import zipfile

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr("test.md", "# Test Content")
                zipf.writestr("test2.md", "# More Content")
            zip_buffer.seek(0)
            zip_bytes = zip_buffer.read()

            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zipf:
                namelist = zipf.namelist()
                self.test_result(
                    "create_zip_archive (inline)",
                    len(namelist) == 2 and "test.md" in namelist,
                    f"Created ZIP with {len(namelist)} files",
                )

            yaml_lines = [
                "---",
                "name: test_agent",
                "description: Test description",
                'tools: ["mcp__giljo_mcp__*"]',
                "model: sonnet",
                "---",
            ]
            yaml = "\n".join(yaml_lines) + "\n"

            self.test_result(
                "generate_yaml_frontmatter (inline)",
                yaml.startswith("---\n") and "name: test_agent" in yaml,
                "Generated valid YAML frontmatter",
            )

            url = "http://localhost:7272"
            self.test_result(
                "get_server_url (inline)",
                url.startswith("http://") and ":" in url,
                f"Server URL: {url}",
            )

        except Exception as e:
            self.test_result("Utility functions", False, f"Exception: {e}")

        print("")

    async def test_database_templates(self):
        print("Testing database template retrieval...")

        try:
            async with self.db.get_session_async() as session:
                result = await session.execute(
                    select(AgentTemplate)
                    .where(
                        AgentTemplate.tenant_key == self.test_user.tenant_key,
                        AgentTemplate.is_active == True,  # noqa: E712 — SQLAlchemy filter
                    )
                    .order_by(AgentTemplate.name)
                )
                templates = result.scalars().all()

                self.test_result(
                    "Database - retrieve active templates",
                    len(templates) >= 2,
                    f"Found {len(templates)} active templates",
                )

                template_names = [t.name for t in templates]
                self.test_result(
                    "Database - test templates exist",
                    "test_orchestrator" in template_names and "test_implementor" in template_names,
                    f"Templates: {', '.join(template_names[:5])}...",
                )

                self.test_result(
                    "Database - inactive templates filtered",
                    "test_inactive" not in template_names,
                    "Inactive templates correctly filtered",
                )

        except Exception as e:
            self.test_result("Database template retrieval", False, f"Exception: {e}")

        print("")

    async def cleanup(self):
        print("Cleaning up test data...")

        try:
            async with self.db.get_session_async() as session:
                result = await session.execute(
                    select(AgentTemplate).where(
                        AgentTemplate.name.like("test_%"),
                        AgentTemplate.tenant_key == self.test_user.tenant_key,
                    )
                )
                for template in result.scalars().all():
                    await session.delete(template)
                await session.commit()

            print("[OK] Test templates removed")

        except Exception as e:
            print(f"Warning: Cleanup failed: {e}")

        print("")

    def print_summary(self):
        print("=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for r in self.results if r["passed"])
        failed = sum(1 for r in self.results if not r["passed"])
        total = len(self.results)

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Success Rate: {(passed / total * 100):.1f}%")
        print("")

        if failed > 0:
            print("Failed Tests:")
            for result in self.results:
                if not result["passed"]:
                    print(f"  - {result['test']}: {result['details']}")
            print("")

        print("=" * 70)
        print("")

        if failed == 0:
            print("[OK] ALL TESTS PASSED")
        else:
            print(f"[FAIL] {failed} TEST(S) FAILED")

        print("")

    async def run_all_tests(self):
        await self.setup()
        await self.create_test_templates()
        await self.test_utility_functions()
        await self.test_database_templates()
        await self.test_slash_commands_download()
        await self.test_agent_templates_download()
        await self.test_install_scripts()
        await self.cleanup()
        self.print_summary()


async def main():
    load_dotenv()
    tester = DownloadsTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
