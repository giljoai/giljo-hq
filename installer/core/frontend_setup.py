# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


MIN_DISK_SPACE_MB = 500
NPM_INSTALL_TIMEOUT = 300
NPM_MAX_RETRIES = 3


class FrontendSetupMixin:

    @staticmethod
    def _get_node_version() -> str:
        with contextlib.suppress(Exception):
            proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10, check=False)
            return proc.stdout.strip()
        return "unknown"

    def _npm_preflight_checks(self, frontend_dir: Path) -> dict[str, Any]:
        result = {"healthy": True, "issues": [], "warnings": []}

        try:
            npm_ping = self.platform.run_npm_command(cmd=["npm", "ping"], cwd=frontend_dir, timeout=30)

            if not npm_ping["success"]:
                result["healthy"] = False
                result["issues"].append(f"npm registry unreachable: {npm_ping.get('stderr', 'Unknown error')}")
        except FileNotFoundError:
            result["healthy"] = False
            result["issues"].append("npm is not installed or not in PATH")
        except Exception as e:
            result["healthy"] = False
            result["issues"].append(f"npm registry check failed: {e!s}")

        try:
            disk_usage = shutil.disk_usage(frontend_dir)
            free_mb = disk_usage.free / (1024 * 1024)

            if free_mb < MIN_DISK_SPACE_MB:
                result["healthy"] = False
                result["issues"].append(
                    f"Insufficient disk space: {free_mb:.0f}MB available, {MIN_DISK_SPACE_MB}MB required"
                )
        except Exception as e:
            result["warnings"].append(f"Could not check disk space: {e!s}")

        lockfile = frontend_dir / "package-lock.json"
        if not lockfile.exists():
            result["warnings"].append("package-lock.json not found - will use 'npm install' instead of 'npm ci'")

        return result

    def _verify_npm_dependencies(self, frontend_dir: Path) -> bool:
        node_modules = frontend_dir / "node_modules"

        if not node_modules.exists():
            return False

        critical_deps = [
            "vue",
            "vuetify",
            "vue-router",
            "pinia",
            "axios",
            "lodash-es",
            "date-fns",
            "dompurify",
        ]

        for dep in critical_deps:
            dep_path = node_modules / dep
            if not dep_path.exists():
                self._print_warning(f"Missing dependency: {dep}")
                return False

        return True

    def _install_npm_dependencies_with_retry(self, frontend_dir: Path, max_retries: int = NPM_MAX_RETRIES) -> bool:
        logs_dir = self._ensure_logs_dir()
        log_file = logs_dir / "install_npm.log"

        self._print_info("Running npm pre-flight checks...")
        preflight = self._npm_preflight_checks(frontend_dir)

        if not preflight["healthy"]:
            self._print_error("Pre-flight checks failed:")
            for issue in preflight["issues"]:
                self._print_error(f"  • {issue}")
            self._npm_preflight_results = preflight
            return False

        if preflight["warnings"]:
            for warning in preflight["warnings"]:
                self._print_warning(f"  • {warning}")

        self._npm_preflight_results = preflight

        lockfile = frontend_dir / "package-lock.json"
        use_npm_ci = lockfile.exists()

        for attempt in range(max_retries):
            if attempt > 0:
                self._print_info(f"Retrying npm install (attempt {attempt + 1}/{max_retries})...")
            else:
                self._print_info("Installing frontend dependencies...")

            if attempt == max_retries - 1 and attempt > 0:
                self._print_info("Clearing npm cache before final attempt...")
                cache_result = self.platform.run_npm_command(
                    cmd=["npm", "cache", "clean", "--force"], cwd=frontend_dir, timeout=60
                )
                if cache_result["success"]:
                    self._print_success("npm cache cleared")

            if use_npm_ci and attempt == 0:
                npm_cmd = ["npm", "ci"]
                cmd_name = "npm ci"
            else:
                npm_cmd = ["npm", "install"]
                cmd_name = "npm install"
                use_npm_ci = False

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 70}\n")
                f.write(f"Attempt {attempt + 1}/{max_retries} - {datetime.now(UTC).isoformat()}\n")
                f.write(f"Command: {' '.join(npm_cmd)}\n")
                f.write(f"{'=' * 70}\n\n")

            npm_result = self.platform.run_npm_command(cmd=npm_cmd, cwd=frontend_dir, timeout=NPM_INSTALL_TIMEOUT)

            with open(log_file, "a", encoding="utf-8") as f:
                f.write("STDOUT:\n")
                f.write(npm_result.get("stdout", "") + "\n\n")
                f.write("STDERR:\n")
                f.write(npm_result.get("stderr", "") + "\n\n")

            if npm_result["success"]:
                if not self._verify_npm_dependencies(frontend_dir):
                    self._print_warning(f"{cmd_name} succeeded but folder verification failed")
                    continue

                self._print_info("Verifying installation integrity...")
                list_result = self.platform.run_npm_command(
                    cmd=["npm", "list", "--depth=0"], cwd=frontend_dir, timeout=30
                )

                if "ENOENT" in list_result.get("stderr", "") or "ERR!" in list_result.get("stderr", ""):
                    self._print_warning(f"{cmd_name} succeeded but npm list verification failed")
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write("NPM LIST VERIFICATION FAILED:\n")
                        f.write(list_result.get("stderr", "") + "\n\n")
                    continue

                self._print_success("Frontend dependencies installed and verified successfully")
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("SUCCESS: Installation verified\n")
                return True
            error_msg = npm_result.get("stderr", npm_result.get("error", "Unknown error"))
            self._print_warning(f"Attempt {attempt + 1} failed: {error_msg[:100]}...")

            if "ci" in npm_cmd and attempt == 0:
                self._print_info("npm ci failed, will try npm install next")
                use_npm_ci = False

            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                self._print_info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\nFAILURE: All {max_retries} attempts exhausted\n")
        return False

    def install_frontend_dependencies(self) -> dict[str, Any]:
        result = {"success": False}

        try:
            if not shutil.which("npm"):
                self._print_warning("npm not found - skipping frontend dependencies")
                self._print_info("Install Node.js from: https://nodejs.org/")
                result["success"] = True
                result["skipped"] = True
                result["reason"] = "npm not available"
                return result

            frontend_dir = self.install_dir / "frontend"
            if not frontend_dir.exists():
                self._print_warning("Frontend directory not found - skipping frontend dependencies")
                result["success"] = True
                result["skipped"] = True
                result["reason"] = "frontend directory not found"
                return result

            self._print_info("Installing frontend dependencies...")

            if self._verify_npm_dependencies(frontend_dir):
                self._print_success("Frontend dependencies already installed and verified")
                result["success"] = True
                result["already_installed"] = True
                return result

            if self._install_npm_dependencies_with_retry(frontend_dir):
                self._print_success("Frontend dependencies installed successfully")
                result["success"] = True
                return result
            self._print_error("=" * 70)
            self._print_error("INSTALLATION FAILED: Frontend dependencies could not be installed")
            self._print_error("=" * 70)
            self._print_error("")

            if hasattr(self, "_npm_preflight_results"):
                preflight = self._npm_preflight_results
                if preflight.get("issues"):
                    self._print_error("Pre-flight check issues detected:")
                    for issue in preflight["issues"]:
                        self._print_error(f"  • {issue}")
                    self._print_error("")

            log_file = self.install_dir / "logs" / "install_npm.log"
            if log_file.exists():
                self._print_error(f"Detailed logs: {log_file}")
                self._print_error("")

            self._print_error("Troubleshooting steps:")
            self._print_error("  1. Check network connectivity to npm registry:")
            self._print_error("     npm ping")
            self._print_error("     curl https://registry.npmjs.org/")
            self._print_error("")
            self._print_error(f"  2. Verify disk space (need ~{MIN_DISK_SPACE_MB}MB):")
            if self.platform.platform_name == "Windows":
                self._print_error("     dir")
            else:
                self._print_error("     df -h")
            self._print_error("")
            self._print_error("  3. Clear npm cache and retry manually:")
            self._print_error(f"     cd {frontend_dir}")
            self._print_error("     npm cache clean --force")
            self._print_error("     npm cache verify")
            self._print_error("     npm install --verbose")
            self._print_error("")
            self._print_error("  4. Check for proxy/firewall blocking npm registry:")
            self._print_error("     npm config get proxy")
            self._print_error("     npm config get https-proxy")
            self._print_error("")
            self._print_error("  5. If behind corporate proxy, configure npm:")
            self._print_error("     npm config set proxy http://proxy.company.com:8080")
            self._print_error("     npm config set https-proxy http://proxy.company.com:8080")
            self._print_error("")
            self._print_error("=" * 70)

            result["error"] = f"npm install failed after {NPM_MAX_RETRIES} retry attempts"
            result["success"] = False
            return result

        except Exception as e:
            self._print_error(f"Frontend dependency installation failed: {e}")
            result["error"] = str(e)
            result["success"] = False
            return result
