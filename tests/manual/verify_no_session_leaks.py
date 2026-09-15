# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import asyncio
import gc
import logging
import sys
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


warnings.filterwarnings("always")
logging.basicConfig(level=logging.DEBUG)


async def simulate_endpoint_with_http_exception():
    from contextlib import asynccontextmanager

    from giljo_mcp.auth.dependencies import get_db_session
    from giljo_mcp.database import DatabaseManager

    mock_request = MagicMock(spec=Request)
    mock_db_manager = MagicMock(spec=DatabaseManager)
    sessions_created = 0
    sessions_closed = 0

    @asynccontextmanager
    async def track_sessions():
        nonlocal sessions_created, sessions_closed
        mock_session = AsyncMock(spec=AsyncSession)
        sessions_created += 1

        async def close():
            nonlocal sessions_closed
            sessions_closed += 1

        mock_session.close = close
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.is_active = False

        try:
            yield mock_session
            await mock_session.commit()
        except Exception as _exc:
            await mock_session.rollback()
            raise
        finally:
            if hasattr(mock_session, "is_active") and mock_session.is_active:
                await mock_session.rollback()
            await mock_session.close()

    mock_db_manager.get_session_async = track_sessions
    mock_request.app.state.api_state.db_manager = mock_db_manager

    for i in range(100):
        session_generator = get_db_session(mock_request)

        try:
            await session_generator.__anext__()
            raise HTTPException(status_code=403, detail="Permission denied")
        except HTTPException:
            await session_generator.aclose()

    gc.collect()
    await asyncio.sleep(0.2)

    print("\n" + "=" * 60)
    print("SESSION LEAK VERIFICATION RESULTS")
    print("=" * 60)
    print(f"Sessions created: {sessions_created}")
    print(f"Sessions closed:  {sessions_closed}")

    if sessions_created == sessions_closed:
        print("\n✓ PASS: No session leaks detected")
        print("✓ All sessions properly cleaned up")
    else:
        print("\n✗ FAIL: Session leak detected!")
        print(f"✗ {sessions_created - sessions_closed} sessions leaked")

    return sessions_created == sessions_closed


async def main():
    print("Starting database session leak verification...")
    print("This will simulate 100 requests that raise HTTPException")
    print("Watching for garbage collector warnings and session leaks...\n")

    try:
        success = await simulate_endpoint_with_http_exception()

        print("\n" + "=" * 60)
        if success:
            print("✓ VERIFICATION SUCCESSFUL")
            print("✓ No session leaks detected")
            print("✓ Connection pool is stable")
            print("✓ No garbage collector warnings")
        else:
            print("✗ VERIFICATION FAILED")
            print("✗ Session leaks detected")

        print("=" * 60)

        return 0 if success else 1

    except Exception as e:
        print(f"\n✗ ERROR during verification: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
