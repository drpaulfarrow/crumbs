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
WARM_DIR = PROFILE_DIR / "warm"

# Not worth copying into each A/B profile (and the lock files would confuse the browser).
_CLONE_SKIP = shutil.ignore_patterns(
    "Singleton*", "lockfile", "LOCK", "*.lock", "Cache", "Code Cache", "GPUCache", "GrShaderCache",
    "ShaderCache", "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "Crashpad", "BrowserMetrics*",
    "component_crx_cache", "extensions_crx_cache", "optimization_guide_*", "Safe Browsing*")


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
    """Usable screen area in the scaled units browsers position windows in.

    Deliberately not DPI-aware: with display scaling (e.g. 150%) Windows then
    reports scaled sizes, which match the browser's own coordinates.
    """
    if os.name == "nt":
        try:
            import ctypes
            user32 = ctypes.windll.user32
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
                 urls: list[str], extra: list[str] | None = None) -> list[str]:
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
        *(extra or []),
        *urls,
    ]


def warm_profile_state() -> dict:
    """The warm-up profile: a normal browsing profile both A/B windows are cloned from."""
    if not (WARM_DIR / "Local State").exists():
        return {"exists": False, "in_use": False}
    in_use = any(os.path.lexists(WARM_DIR / name) for name in ("lockfile", "SingletonLock"))
    updated = max((p.stat().st_mtime for p in WARM_DIR.glob("Default/*") if p.is_file()), default=0)
    return {"exists": True, "in_use": in_use, "updated": updated}


def launch_warmup(urls: list[str], prefer: str = "edge") -> None:
    """A plain browser window (no proxy, no Crumbs, no DevTools port) on the warm-up profile.

    Browse a few sites and accept their cookie banners, then close it: every A/B
    launch afterwards starts both windows as copies of this profile.
    """
    WARM_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([find_browser(prefer), f"--user-data-dir={WARM_DIR}", "--no-first-run",
                      "--no-default-browser-check", "--new-window", *urls],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clone_warm_profile(dest: Path) -> None:
    state = warm_profile_state()
    if not state["exists"]:
        raise FileNotFoundError("No warm-up profile yet. Use 'Warm-up browser' first.")
    if state["in_use"]:
        raise RuntimeError("Close the warm-up browser window first, so its cookies are saved.")
    shutil.copytree(WARM_DIR, dest, ignore=_CLONE_SKIP, dirs_exist_ok=True)


def window_bounds(index: int, count: int = 2, reserve: float = 0.0) -> dict:
    """Split the screen between the windows. reserve keeps that share of the
    screen's left side free, for the case-study page beside the A/B windows."""
    width, height = screen_size()
    start = int(width * max(0.0, min(reserve, 0.8)))
    part = (width - start) // count
    return {"left": start + index * part, "top": 0, "width": part, "height": height}


def launch_ab(lanes: dict, urls: list[str], prefer: str = "edge", warm: bool = False,
              extra: list[str] | None = None, tag: str = "lane", reserve: float = 0.0) -> list[str]:
    """lanes: {"a": (proxy_port, cdp_port), ...}. Window A on the left, B on the right.

    Pass urls=[] to open blank windows and let the browser monitor open the
    pages once it is attached, so no request goes unrecorded.

    Every launch gets brand-new profiles, so nothing carries over between runs
    and a still-open window can't swallow the new flags. With warm=True both
    start as identical copies of the warm-up profile (same cookies, IDs, consent).
    """
    browser = find_browser(prefer)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for old in PROFILE_DIR.glob(f"{tag}-*") if PROFILE_DIR.exists() else []:
        shutil.rmtree(old, ignore_errors=True)  # best effort; open windows keep theirs
    started = []
    for i, (name, (port, cdp_port)) in enumerate(lanes.items()):
        profile = PROFILE_DIR / f"{tag}-{name}-{stamp}"
        if warm:
            clone_warm_profile(profile)
        profile.mkdir(parents=True, exist_ok=True)
        lane_urls = [u.replace("{lane}", name) for u in urls] or ["about:blank"]
        b = window_bounds(i, len(lanes), reserve)
        subprocess.Popen([browser, *browser_args(profile, port, cdp_port, b["left"], b["width"], b["height"],
                                                 lane_urls, extra)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started.append(name)
    return started
