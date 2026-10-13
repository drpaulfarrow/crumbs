"""Whether Windows is pointed at the demo's DNS server, and switching it (needs admin)."""

from __future__ import annotations

import os
import subprocess

from .blocklist import PACKAGE_DIR
from .upstream import ORIGINAL_DNS_FILE

SCRIPTS = PACKAGE_DIR.parent / "scripts" / "windows"


def system_dns_state() -> dict:
    # system-dns-on.ps1 saves the previous settings here; system-dns-off.ps1 deletes it.
    return {"switched": ORIGINAL_DNS_FILE.exists(), "supported": os.name == "nt"}


def run_elevated(turn_on: bool) -> None:
    """Run the on/off script in an admin PowerShell. Windows shows a UAC prompt."""
    if os.name != "nt":
        raise RuntimeError("Switching system DNS is only supported on Windows.")
    script = SCRIPTS / ("system-dns-on.ps1" if turn_on else "system-dns-off.ps1")
    inner = f"-NoProfile -ExecutionPolicy Bypass -File \"{script}\""
    subprocess.Popen([
        "powershell", "-NoProfile", "-Command",
        f"Start-Process powershell -Verb RunAs -Wait -ArgumentList '{inner}'",
    ], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
