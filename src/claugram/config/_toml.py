"""Minimal TOML writer (stdlib ``tomllib`` reads but cannot write).

Supports the subset used by claugram: scalars, arrays of scalars, and nested
tables of arbitrary depth (emitted as dotted headers, e.g. ``[tokens.default]``).
"""

from __future__ import annotations

from typing import Any


def _fmt_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"Unsupported TOML scalar: {type(value)!r}")


def _fmt_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        items = ", ".join(_fmt_scalar(v) for v in value)
        return f"[{items}]"
    return _fmt_scalar(value)


def _emit_key(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, (list, tuple)) and len(value) > 3:
        lines.append(f"{key} = [")
        for v in value:
            lines.append(f"  {_fmt_scalar(v)},")
        lines.append("]")
    else:
        lines.append(f"{key} = {_fmt_value(value)}")


def _emit_table(lines: list[str], data: dict[str, Any], prefix: str = "") -> None:
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    # this table's own keys come before any nested tables (TOML requirement)
    for key, value in scalars.items():
        _emit_key(lines, key, value)
    for name, table in tables.items():
        full = f"{prefix}.{name}" if prefix else name
        lines.append("")
        lines.append(f"[{full}]")
        _emit_table(lines, table, full)


def dumps(data: dict[str, Any]) -> str:
    lines: list[str] = []
    _emit_table(lines, data)
    return "\n".join(lines).lstrip("\n") + "\n"
