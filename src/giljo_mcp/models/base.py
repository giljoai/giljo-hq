# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from uuid import uuid4

from sqlalchemy.orm import declarative_base


Base = declarative_base()


def generate_uuid() -> str:
    return str(uuid4())


def generate_project_alias() -> str:
    import random
    import string

    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=6))
