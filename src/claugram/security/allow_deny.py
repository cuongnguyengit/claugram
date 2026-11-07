"""File-path and root safety helpers."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path


def matches_any(path: str, patterns: list[str]) -> bool:
    """True if *path*'s basename or full path matches any glob pattern."""
    name = os.path.basename(path)
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(path, pat):
            return True
    return False


def is_sensitive_file(path: str, sensitive_patterns: list[str]) -> bool:
    return matches_any(path, sensitive_patterns)


def is_within_roots(path: str, project_root: str, allowed_roots: list[str]) -> bool:
    """True if *path* is inside project_root or one of the extra allowed roots."""
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False
    roots = [project_root, *allowed_roots]
    for root in roots:
        if not root:
            continue
        try:
            root_p = Path(root).resolve()
        except (OSError, ValueError):
            continue
        try:
            target.relative_to(root_p)
            return True
        except ValueError:
            continue
    return False
