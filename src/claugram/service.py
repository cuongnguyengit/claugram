"""Install claugram as a background service (Windows Task Scheduler / systemd)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SYSTEMD_TEMPLATE = """[Unit]
Description=Claugram controller for {name}
After=network-online.target

[Service]
ExecStart={claugram} controller --project {project}
WorkingDirectory={project}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _claugram_exe() -> str:
    import shutil
    return shutil.which("claugram") or "claugram"


def install_windows_task(project_root: Path, task_name: str) -> tuple[bool, str]:
    exe = _claugram_exe()
    cmd = f'"{exe}" controller --project "{project_root}"'
    args = [
        "schtasks", "/Create", "/TN", task_name, "/SC", "ONLOGON",
        "/TR", cmd, "/F", "/RL", "LIMITED",
    ]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as exc:
        return False, str(exc)
    if out.returncode == 0:
        return True, f"Created scheduled task '{task_name}' (runs at logon)."
    return False, (out.stderr or out.stdout).strip()


def install_systemd_user(project_root: Path, name: str) -> tuple[bool, str]:
    exe = _claugram_exe()
    unit = SYSTEMD_TEMPLATE.format(name=name, claugram=exe, project=project_root)
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / f"claugram-{name}.service"
    unit_path.write_text(unit, encoding="utf-8")
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=20)
        subprocess.run(["systemctl", "--user", "enable", "--now",
                        unit_path.name], timeout=20)
    except (subprocess.SubprocessError, OSError) as exc:
        return True, f"Wrote {unit_path} but could not enable: {exc}"
    return True, f"Installed and started {unit_path.name}."


def install_service(project_root: Path, name: str) -> tuple[bool, str]:
    if os.name == "nt":
        return install_windows_task(project_root, f"Claugram {name}")
    return install_systemd_user(project_root, name)


def remove_service(project_root: Path, name: str) -> tuple[bool, str]:
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["schtasks", "/Delete", "/TN", f"Claugram {name}", "/F"],
                capture_output=True, text=True, timeout=30)
        except (subprocess.SubprocessError, OSError) as exc:
            return False, str(exc)
        return out.returncode == 0, (out.stdout or out.stderr).strip()
    unit = Path.home() / ".config" / "systemd" / "user" / f"claugram-{name}.service"
    try:
        subprocess.run(["systemctl", "--user", "disable", "--now", unit.name],
                       timeout=20)
    except (subprocess.SubprocessError, OSError):
        pass
    if unit.exists():
        unit.unlink()
    return True, f"Removed {unit.name}."
