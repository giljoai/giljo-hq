# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any, ClassVar

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


class SetupStateManager:

    _instances: ClassVar[dict[str, "SetupStateManager"]] = {}
    _lock: ClassVar[Lock] = Lock()

    def __init__(
        self,
        tenant_key: str | None = None,
        db_session: Session | None = None,
        current_version: str | None = None,
        required_db_version: str | None = None,
    ):
        if tenant_key is None:
            raise ValueError("tenant_key is required")

        self.tenant_key = tenant_key
        self.db_session = db_session
        self.current_version = current_version
        self.required_db_version = required_db_version

        self.state_dir = Path.home() / ".giljo-mcp"
        self.state_file = self.state_dir / "setup_state.json"

        self._file_lock = Lock()

    @classmethod
    def get_instance(
        cls,
        tenant_key: str,
        db_session: Session | None = None,
        current_version: str | None = None,
        required_db_version: str | None = None,
    ) -> "SetupStateManager":
        with cls._lock:
            if tenant_key not in cls._instances:
                cls._instances[tenant_key] = cls(
                    tenant_key=tenant_key,
                    db_session=db_session,
                    current_version=current_version,
                    required_db_version=required_db_version,
                )
            return cls._instances[tenant_key]

    def get_state(self) -> dict[str, Any]:
        if self.db_session is not None:
            try:
                state_dict = self._get_state_from_database()
                if state_dict is not None:
                    return state_dict
            except SQLAlchemyError as e:
                logger.warning(
                    f"Failed to get state from database for tenant {self.tenant_key}: {e}. "
                    "Falling back to file storage."
                )

        try:
            state_dict = self._get_state_from_file()
            if state_dict is not None:
                return state_dict
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to get state from file for tenant {self.tenant_key}: {e}. Returning default state.")

        return self._get_default_state()

    def _get_state_from_database(self) -> dict[str, Any | None]:
        from giljo_mcp.models import SetupState

        state = SetupState.get_by_tenant(self.db_session, self.tenant_key)
        if state:
            return state.to_dict()
        return None

    def _get_state_from_file(self) -> dict[str, Any | None]:
        if not self.state_file.exists():
            return None

        with self._file_lock:
            try:
                with open(self.state_file) as f:
                    data = json.load(f)

                if data.get("tenant_key") == self.tenant_key:
                    return data

            except json.JSONDecodeError:
                logger.exception("Failed to parse setup state file")
                return None

        return None

    def _get_default_state(self) -> dict[str, Any]:
        return {
            "tenant_key": self.tenant_key,
            "database_initialized": False,
            "database_initialized_at": None,
            "setup_version": None,
            "python_version": None,
            "validation_failures": [],
        }

    def update_state(self, **kwargs) -> None:
        if self.db_session is not None:
            try:
                self._update_state_in_database(**kwargs)
                return
            except SQLAlchemyError as e:
                logger.warning(
                    f"Failed to update state in database for tenant {self.tenant_key}: {e}. "
                    "Falling back to file storage."
                )

        self._update_state_in_file(**kwargs)

    def _update_state_in_database(self, **kwargs) -> None:
        from giljo_mcp.models import SetupState

        SetupState.create_or_update(self.db_session, tenant_key=self.tenant_key, **kwargs)

        self.db_session.commit()

    def _update_state_in_file(self, **kwargs) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

        state = self._get_state_from_file()
        if state is None:
            state = self._get_default_state()

        for key, value in kwargs.items():
            state[key] = value

        with self._file_lock:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)

            import platform

            if platform.system() != "Windows":
                Path(self.state_file).chmod(0o600)

    def requires_migration(self) -> bool:
        if self.current_version is None:
            return False

        state = self.get_state()
        stored_version = state.get("setup_version")

        if stored_version is None:
            return False

        return stored_version != self.current_version

    def validate_state(self) -> tuple[bool, list[str]]:
        errors = []
        state = self.get_state()

        if self.current_version and state.get("setup_version") and state["setup_version"] != self.current_version:
            errors.append(f"Setup version mismatch: stored={state['setup_version']}, current={self.current_version}")

        validation_failures = state.get("validation_failures", [])
        if validation_failures:
            errors.append(f"Setup has {len(validation_failures)} validation failures")

        is_valid = len(errors) == 0
        return is_valid, errors

    def _validate_version_format(self, version: str) -> None:
        pattern = r"^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9\.\-]+)?$"

        if not re.match(pattern, version):
            raise ValueError(
                f"Invalid version format: {version}. Expected semantic versioning (e.g., 1.0.0, 2.1.0-beta)"
            )
