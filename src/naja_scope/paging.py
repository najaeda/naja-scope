# SPDX-License-Identifier: Apache-2.0
"""Pagination envelope: every list a tool returns is bounded (limit, cursor).

The cursor is an opaque offset string. Iteration order must be deterministic
on the producer side (SNL iteration is creation-ordered, so it is)."""

from __future__ import annotations

from typing import Iterable, Iterator, List, Tuple

from .errors import ScopeError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: int | None, default: int = DEFAULT_LIMIT,
                maximum: int = MAX_LIMIT) -> int:
    if limit is None:
        return default
    if limit < 1:
        return 1
    return min(limit, maximum)


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
        if offset < 0:
            raise ValueError
        return offset
    except ValueError:
        raise ScopeError(f"Invalid cursor: {cursor!r}")


def paginate(items: Iterable, limit: int | None = None,
             cursor: str | None = None) -> Tuple[List, dict]:
    """Take one page from an iterable. Returns (page, envelope_fields)."""
    limit = clamp_limit(limit)
    offset = decode_cursor(cursor)
    it: Iterator = iter(items)
    for _ in range(offset):
        if next(it, None) is None:
            return [], {"count": 0, "next_cursor": None, "has_more": False}
    page = []
    for item in it:
        page.append(item)
        if len(page) > limit:
            break
    has_more = len(page) > limit
    if has_more:
        page = page[:limit]
    return page, {
        "count": len(page),
        "next_cursor": str(offset + limit) if has_more else None,
        "has_more": has_more,
    }
