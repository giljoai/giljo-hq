# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import importlib.metadata
import re
from pathlib import Path


_INLINE_COMMENT = re.compile(r"(^|\s)#.*")


def unsatisfied_requirements(requirements_path: Path) -> list[str]:
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:
        return ["packaging: not installed, needed to compare installed versions with requirements.txt"]

    problems: list[str] = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = _INLINE_COMMENT.sub("", raw).strip()
        if not line or line.startswith("-"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"{requirement.name}: not installed, required {requirement.specifier}")
            continue
        if not requirement.specifier.contains(installed, prereleases=True):
            problems.append(f"{requirement.name}: installed {installed}, required {requirement.specifier}")
    return problems
