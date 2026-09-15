# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers.test_db_helper import PostgreSQLTestHelper, wait_for_database_ready


async def main():
    print("Setting up PostgreSQL test database...")
    print("=" * 80)

    print("\n1. Checking PostgreSQL availability...")
    is_ready = await wait_for_database_ready(max_attempts=5, delay=0.5)

    if not is_ready:
        print("\n ERROR: PostgreSQL is not available!")
        print("        Please ensure PostgreSQL is running and accessible at localhost:5432")
        print("        Default credentials: postgres/<your-password> (set POSTGRES_SUPERUSER_PASSWORD env var)")
        sys.exit(1)

    print("   PostgreSQL is available!")

    print("\n2. Creating test database (giljo_mcp_test)...")
    try:
        await PostgreSQLTestHelper.ensure_test_database_exists()
        print("   Test database created successfully!")
    except Exception as e:
        print(f"\n ERROR: Failed to create test database: {e}")
        sys.exit(1)

    print("\n3. Creating database tables...")
    try:
        from giljo_mcp.database import DatabaseManager

        test_url = PostgreSQLTestHelper.get_test_db_url()
        db_manager = DatabaseManager(test_url, is_async=True)
        await PostgreSQLTestHelper.create_test_tables(db_manager)
        await db_manager.close_async()
        print("   Database tables created successfully!")
    except Exception as e:
        print(f"\n ERROR: Failed to create tables: {e}")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("Test database setup complete!")
    print("\nYou can now run tests with:")
    print("  pytest tests/")
    print("\nTo drop the test database after testing:")
    print("  pytest tests/ --drop-test-db")


if __name__ == "__main__":
    asyncio.run(main())
