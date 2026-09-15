# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import subprocess
import sys
from typing import Any

from colorama import Fore, Style


MIN_PYTHON_VERSION = (3, 10)


class PythonEnvSetupMixin:

    def _ensure_venv_site_packages(self) -> None:
        paths_to_add = []

        paths_to_add.append(self.venv_dir / "Lib" / "site-packages")

        py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        paths_to_add.append(self.venv_dir / "lib" / py_version / "site-packages")

        paths_to_add.append(self.install_dir / "src")

        for path in paths_to_add:
            if path.exists():
                str_path = str(path)
                if str_path not in sys.path:
                    sys.path.insert(0, str_path)

    def check_python_version(self) -> bool:
        current_version = sys.version_info
        is_compatible = current_version >= MIN_PYTHON_VERSION

        if hasattr(current_version, "major"):
            version_str = f"{current_version.major}.{current_version.minor}.{current_version.micro}"
        else:
            version_str = f"{current_version[0]}.{current_version[1]}.{current_version[2]}"

        if is_compatible:
            self._print_success(f"Python {version_str} detected")
        else:
            required_str = f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}"
            self._print_error(f"Python {version_str} detected, but {required_str}+ required")
            return False

        try:
            import importlib.util

            if importlib.util.find_spec("ensurepip") is None:
                self._print_error(f"Python {version_str} found, but the ensurepip module is missing.")
                print(
                    f"  {Fore.YELLOW}Fix:{Style.RESET_ALL}  "
                    f"sudo apt install -y python{sys.version_info.major}.{sys.version_info.minor}-venv"
                )
                print(f"  {Fore.YELLOW}Then:{Style.RESET_ALL} python3 install.py")
                return False
        except Exception as exc:  # pragma: no cover - defensive
            self._print_error(f"Could not probe ensurepip module: {exc}")
            return False

        return True

    def install_dependencies(self) -> dict[str, Any]:
        result = {"success": False}

        try:
            if self.venv_dir.exists():
                self._print_info(f"Virtual environment already exists: {self.venv_dir}")
                result["venv_existed"] = True
            else:
                self._print_info(f"Creating virtual environment: {self.venv_dir}")
                subprocess.run([sys.executable, "-m", "venv", str(self.venv_dir)], check=True, capture_output=True)
                self._print_success("Virtual environment created")
                result["venv_created"] = True
                self.venv_created = True

            self.platform.get_venv_pip(self.venv_dir)

            python_executable = self.platform.get_venv_python(self.venv_dir)
            self._print_info("Upgrading pip to latest version...")
            try:
                subprocess.run(
                    [str(python_executable), "-m", "pip", "install", "--upgrade", "pip"],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
                self._print_success("pip upgraded")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                self._print_warning("pip upgrade skipped (non-critical)")

            if not self.requirements_file.exists():
                self._print_error(f"requirements.txt not found: {self.requirements_file}")
                result["error"] = "requirements.txt missing"
                return result

            self._print_info("Installing Python packages (this may take 2-3 minutes)...")
            print(f"{Fore.WHITE}You will see pip's progress output below...{Style.RESET_ALL}\n")

            constraints_args = []
            if self.constraints_file.exists():
                constraints_args = ["-c", str(self.constraints_file)]
                self._print_info("Applying pinned dependency constraints (requirements.lock)")
            else:
                self._print_warning("requirements.lock not found — installing from unpinned version floors")

            subprocess.run(
                [
                    str(python_executable),
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "-r",
                    str(self.requirements_file),
                    *constraints_args,
                ],
                check=True,
                text=True,
                timeout=300,
            )

            self._print_success("Dependencies installed successfully")

            try:
                subprocess.run(
                    [str(python_executable), "-m", "pip", "install", "-e", ".", "--quiet", *constraints_args],
                    check=True,
                    capture_output=True,
                    timeout=60,
                    cwd=str(self.install_dir),
                )
                self._print_success("Package registered (editable install)")
            except Exception as e:
                self._print_warning(f"Editable install skipped (non-fatal): {e}")

            if self.settings.get("dev"):
                self._print_info("Setting up pre-commit hooks...")
                try:
                    python_executable = self.platform.get_venv_python(self.venv_dir)
                    subprocess.run(
                        [str(python_executable), "-m", "pip", "install", "-q", "--no-cache-dir", "pre-commit>=3.5.0"],
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                    subprocess.run(
                        [str(python_executable), "-m", "pre_commit", "install"],
                        check=True,
                        capture_output=True,
                        cwd=str(self.install_dir),
                        timeout=30,
                    )
                    self._print_success("Pre-commit hooks installed")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                    self._print_warning(f"Pre-commit hook setup skipped: {e}")
                    self._print_info("Install later: pip install pre-commit && pre-commit install")

            else:
                self._print_info("Skipping dev tools (pre-commit). Use --dev to include them.")

            result["success"] = True
            return result

        except subprocess.TimeoutExpired:
            self._print_error("Installation timed out (exceeded 5 minutes)")
            result["error"] = "Timeout"
            return result

        except subprocess.CalledProcessError as e:
            self._print_error(f"pip install failed: {e}")
            result["error"] = str(e)
            return result

        except Exception as e:
            self._print_error(f"Dependency installation failed: {e}")
            result["error"] = str(e)
            return result
