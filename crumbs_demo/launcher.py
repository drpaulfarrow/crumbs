"""Open the two side-by-side browser windows, each wired to its own lane."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .blocklist import CACHE_DIR

PROFILE_DIR = CACHE_DIR / "profiles"


def find_browser(prefer: str = "edge") -> str:
    """Path to Edge or Chrome, trying `prefer` first. CRUMBS_BROWSER overrides."""
    override = os.environ.get("CRUMBS_BROWSER")
    if override:
        return override
    edge, chrome = [], []
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                edge.append(Path(base, "Microsoft/Edge/Application/msedge.exe"))
                chrome.append(Path(base, "Google/Chrome/Application/chrome.exe"))
    elif sys.platform == "darwin":
        edge.append(Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"))
        chrome.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    edge_names, chrome_names = ["msedge", "microsoft-edge"], ["google-chrome", "chromium", "chromium-browser", "chrome"]
    order = [(edge, edge_names), (chrome, chrome_names)]
    if prefer == "chrome":
        order.reverse()
    for paths, names in order:
        for c in paths:
            if c.is_file():
                return str(c)
        for name in names:
            found = shutil.which(name)
            if found:
                return found
    raise FileNotFoundError("No Edge or Chrome found. Set CRUMBS_BROWSER to the browser's path.")


def screen_size() -> tuple[int, int]:
    if os.name == "nt":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            # Work area excludes the taskbar.
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            rect = RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            return rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 1920, 1040


def browser_args(profile: Path, proxy_port: int, cdp_port: int, x: int, width: int, height: int,
                 urls: list[str]) -> list[str]:
    # Chrome never proxies loopback, so the local test page loads directly while
    # everything it pulls in from the internet goes through the lane.
    return [
        f"--user-data-dir={profile}",
        f"--proxy-server=http://127.0.0.1:{proxy_port}",
        # Lets the control panel watch each window's tabs and requests (loopback only).
        f"--remote-debugging-port={cdp_port}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=PrivacySandboxSettings4,OptimizationHints,MediaRouter",
        f"--window-position={x},0",
        f"--window-size={width},{height}",
        "--new-window",
        *urls,
    ]


def launch_ab(lanes: dict, urls: list[str], prefer: str = "edge") -> list[str]:
    """lanes: {"a": (proxy_port, cdp_port), ...}. Window A on the left, B on the right.

    Pass urls=[] to open blank windows and let the browser monitor open the
    pages once it is attached, so no request goes unrecorded.

    Every launch gets brand-new profiles, so no cached tracker scripts or cookies
    carry over between runs and a still-open window can't swallow the new flags.
    """
    browser = find_browser(prefer)
    width, height = screen_size()
    half = width // 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for old in PROFILE_DIR.glob("lane-*") if PROFILE_DIR.exists() else []:
        shutil.rmtree(old, ignore_errors=True)  # best effort; open windows keep theirs
    started = []
    for i, (name, (port, cdp_port)) in enumerate(lanes.items()):
        profile = PROFILE_DIR / f"lane-{name}-{stamp}"
        profile.mkdir(parents=True, exist_ok=True)
        lane_urls = [u.replace("{lane}", name) for u in urls] or ["about:blank"]
        subprocess.Popen([browser, *browser_args(profile, port, cdp_port, i * half, half, height, lane_urls)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started.append(name)
    return started
