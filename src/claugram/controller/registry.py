"""Multi-project registry helpers.

Every `claugram init` registers its project in the shared store (via
Runtime.upsert_project). A hub bot lists those and lets each chat pick an
active project with /use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..storage import Store


@dataclass
class ProjectRef:
    project_id: str
    name: str
    root: Path


def _ref(row) -> ProjectRef:
    return ProjectRef(row["id"], row["name"] or Path(row["root_path"]).name,
                      Path(row["root_path"]))


def list_registered(store: Store) -> list[ProjectRef]:
    return [_ref(r) for r in store.list_projects()]


def by_id(store: Store, project_id: str) -> Optional[ProjectRef]:
    row = store.get_project(project_id)
    return _ref(row) if row else None


def find(store: Store, token: str) -> Optional[ProjectRef]:
    """Resolve a /use argument: 1-based index, exact/prefix name, or path part."""
    token = token.strip()
    refs = list_registered(store)
    if token.isdigit():
        idx = int(token) - 1
        return refs[idx] if 0 <= idx < len(refs) else None
    low = token.lower()
    for r in refs:  # exact name first
        if r.name.lower() == low:
            return r
    for r in refs:  # then prefix / path substring
        if r.name.lower().startswith(low) or low in str(r.root).lower():
            return r
    return None


def active_ref(store: Store, chat_id: int,
               default: Optional[ProjectRef]) -> Optional[ProjectRef]:
    pid = store.get_active_project(chat_id)
    if pid:
        ref = by_id(store, pid)
        if ref:
            return ref
    return default
