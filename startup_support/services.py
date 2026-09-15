# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import contextlib
import os
import platform
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path

from startup_support.console import print_error, print_info, print_success, print_warning


@contextlib.contextmanager
def _single_instance_lock(timeout: float = 20.0):
    lock_path = Path.cwd() / "logs" / ".startup.lock"
    fd = None
    locked = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + timeout
        is_windows = platform.system() == "Windows"
        while True:
            try:
                if is_windows:
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    print_warning("Another GiljoAI start appears to be in progress; proceeding without lock.")
                    break
                time.sleep(0.25)
    except Exception as lock_err:
        print_warning(f"Single-instance lock unavailable ({lock_err}); proceeding.")
    try:
        yield
    finally:
        if fd is not None:
            if locked:
                with contextlib.suppress(Exception):
                    if platform.system() == "Windows":
                        import msvcrt

                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(fd)


def _launch_log_viewer(stdout_path: Path, run_stamp: str) -> None:
    title = f"GiljoAI API - live logs ({run_stamp})"
    system = platform.system()
    try:
        if system == "Windows":
            viewer_cmd = (
                f"$Host.UI.RawUI.WindowTitle = '{title}'; "
                "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
                f"Get-Content -Wait -Encoding utf8 -LiteralPath '{stdout_path}' | ForEach-Object {{ "
                r'$l = $_ -replace "\x1b\[[0-9;]*m",""; '
                r"if ($l -match '\b(CRITICAL|FATAL)\b') {$c='Magenta'} "
                r"elseif ($l -match '\b(ERROR|Traceback|Exception|Failed)\b') {$c='Red'} "
                r"elseif ($l -match '\b(WARN|WARNING)\b') {$c='Yellow'} "
                r"elseif ($l -match '\bINFO\b') {$c='Cyan'} "
                r"elseif ($l -match '\bDEBUG\b') {$c='DarkGray'} "
                r"else {$c='Gray'}; "
                r"Write-Host $l -ForegroundColor $c }"
            )
            subprocess.Popen(
                ["powershell", "-NoExit", "-NoProfile", "-Command", viewer_cmd],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            print_success("Live log viewer opened (colorized). Closing it does NOT stop the server.")
            return

        if system == "Linux":
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            tail_cmd = ["tail", "-n", "+1", "-F", str(stdout_path)]
            emulators = (
                ("gnome-terminal", ["gnome-terminal", "--title", title, "--", *tail_cmd]),
                ("konsole", ["konsole", "--title", title, "-e", *tail_cmd]),
                ("xterm", ["xterm", "-title", title, "-e", *tail_cmd]),
            )
            if has_display:
                for name, cmd in emulators:
                    if shutil.which(name):
                        with contextlib.suppress(OSError):
                            subprocess.Popen(cmd)
                            print_success(f"Live log viewer opened in {name}. Closing it does NOT stop the server.")
                            return
            print_info(f"No graphical terminal available - follow live logs with:  tail -f {stdout_path}")
            return

        if system == "Darwin":
            sh_path = str(stdout_path).replace("'", "'\\''")
            sh_cmd = f"tail -n +1 -F '{sh_path}'"
            as_cmd = sh_cmd.replace("\\", "\\\\").replace('"', '\\"')
            script = f'tell application "Terminal" to do script "{as_cmd}"'
            subprocess.Popen(["osascript", "-e", script])
            print_success("Live log viewer opened in Terminal.app. Closing it does NOT stop the server.")
            return

        print_info(f"Follow live logs with:  tail -f {stdout_path}")
    except Exception as viewer_err:
        print_warning(f"Could not open live log viewer ({viewer_err}). Tail manually: tail -f {stdout_path}")


def wait_for_api_ready(port: int, max_attempts: int = 60, interval: float = 0.5, ssl_enabled: bool = False) -> bool:
    import ssl
    import urllib.error
    import urllib.request

    protocol = "https" if ssl_enabled else "http"
    url = f"{protocol}://localhost:{port}/health"
    print_info(f"Waiting for API to be ready (max {max_attempts * interval:.0f}s)...")

    ssl_context = None
    if ssl_enabled:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=1, context=ssl_context) as response:  # noqa: S310  # reason: url is dev-server localhost http(s):// only, scheme controlled by config
                if response.status == 200:
                    print_success(f"API ready after {attempt * interval:.1f}s")
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            if attempt % 10 == 0:
                print_info(f"Still waiting... ({attempt * interval:.0f}s elapsed)")
            time.sleep(interval)
        except Exception as e:
            print_warning(f"Unexpected error checking API health: {e}")
            time.sleep(interval)

    print_error(f"API did not become ready within {max_attempts * interval:.0f}s timeout")
    return False


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def _open_browser_wsl(url: str) -> bool:
    openers = (
        ["wslview", url],
        ["explorer.exe", url],
        ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"],
    )
    for cmd in openers:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def open_browser(url: str, delay: int = 3) -> None:
    print_info(f"Opening browser to {url} in {delay} seconds...")
    time.sleep(delay)
    try:
        opened = _open_browser_wsl(url) if _is_wsl() else webbrowser.open(url)
    except Exception as e:
        print_error(f"Failed to open browser: {e}")
        print_info(f"Please manually open: {url}")
        return
    if opened:
        print_success("Browser opened")
    else:
        print_warning(f"Couldn't auto-open a browser - please manually open: {url}")


def _choose_browser_target(deployment_context: str, is_first_run: bool) -> str | None:
    if deployment_context == "saas-production":
        return None
    if is_first_run:
        return "/welcome"
    return ""
