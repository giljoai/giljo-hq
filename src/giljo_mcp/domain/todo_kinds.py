# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re


TODO_KIND_SELF_CLOSEOUT = "self_closeout"
TODO_KIND_CLOSEOUT_INTENT = "closeout_intent"
TODO_KIND_CHAIN_DRIVE = "chain_drive"


CLOSEOUT_TODO_PATTERN = re.compile(r"(?i)\b(closeout|complete[_ ]job|close[_ ]project|self[_ -]complete)\b")

CLOSEOUT_INTENT_PATTERN = re.compile(
    r"(?i)\b(wrap[- ]?up|finaliz|finalis|conclude|complete|finish|close|sign[- ]?off|wind[- ]?down)\b"
    r".{0,40}\b(project|job|work|chain|run|task|orchestrat|sprint|everything|up)\b"
)

CHAIN_DRIVE_TODO_PATTERN = re.compile(
    r"(?i)\b(poll|advance|spawn[ _-]?next|next[ _-]?project|series[ _-]?summary|"
    r"chain[ _-]?finale|finale|drive[ _-]the[ _-]chain|conductor)\b"
)


def classify_todo_kind(content: str | None) -> str | None:
    text = content or ""
    if CLOSEOUT_TODO_PATTERN.search(text):
        return TODO_KIND_SELF_CLOSEOUT
    if CLOSEOUT_INTENT_PATTERN.search(text):
        return TODO_KIND_CLOSEOUT_INTENT
    if CHAIN_DRIVE_TODO_PATTERN.search(text):
        return TODO_KIND_CHAIN_DRIVE
    return None
