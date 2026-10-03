#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import yaml


class GiljoLauncher:
    def __init__(self):
        self.processes = []
        self.config = None
        self.load_config()

    def load_config(self):
        config_path = Path("config.yaml")
        if not config_path.exists():
            print("Error: config.yaml not found. Please run installer first.")
            sys.exit(1)

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def check_port(self, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result != 0

    def validate_installation(self) -> bool:
        required_files = [".env", "config.yaml"]
        for file in required_files:
            if not Path(file).exists():
                print(f"Error: Missing {file} - installation incomplete")
                return False

        ports = {
            "API": self.config["services"].get("api_port", 8000),
            "WebSocket": self.config["services"].get("websocket_port", 7273),
            "Dashboard": self.config["services"].get("dashboard_port", 7274),
        }

        for service, port in ports.items():
            if not self.check_port(port):
                print(f"Error: Port {port} ({service}) is already in use")
                return False

        return True

    def start_service(self, name: str, command: list) -> subprocess.Popen:
        print(f"Starting {name}...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd())

        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(proc)
        return proc

    def start_all_services(self):
        print("=" * 60)
        print("   Starting Giljo HQ Services")
        print("=" * 60)
        print()

        api_port = self.config["services"].get("api_port", 8000)
        self.start_service(
            "API Server",
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        )
        time.sleep(2)

        ws_port = self.config["services"].get("websocket_port", 7273)
        self.start_service("WebSocket Server", [sys.executable, "-m", "giljo_mcp.websocket", "--port", str(ws_port)])
        time.sleep(1)

        dashboard_port = self.config["services"].get("dashboard_port", 7274)
        self.start_service(
            "Dashboard", [sys.executable, "-m", "http.server", str(dashboard_port), "--directory", "frontend"]
        )

        http_proto = "http"
        ws_proto = "ws"

        print()
        print("All services started successfully!")
        print()
        print("Access points:")
        print(f"  Dashboard: {http_proto}://localhost:{dashboard_port}")
        print(f"  API Docs: {http_proto}://localhost:{api_port}/docs")
        print(f"  WebSocket: {ws_proto}://localhost:{ws_port}")
        print()

        if self.config.get("features", {}).get("auto_start_browser", True):
            time.sleep(2)
            webbrowser.open(f"{http_proto}://localhost:{dashboard_port}")

    def shutdown(self, signum=None, frame=None):
        print("\n" + "=" * 60)
        print("   Shutting down services...")
        print("=" * 60)

        for proc in self.processes:
            if proc.poll() is None:
                proc.terminate()

        time.sleep(2)

        for proc in self.processes:
            if proc.poll() is None:
                proc.kill()

        print("All services stopped.")
        sys.exit(0)

    def run(self):
        if not self.validate_installation():
            sys.exit(1)

        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

        try:
            self.start_all_services()

            print("Press Ctrl+C to stop all services")
            print()

            while True:
                time.sleep(1)
                for proc in self.processes:
                    if proc.poll() is not None:
                        print("Warning: A service has stopped unexpectedly")
                        self.shutdown()

        except KeyboardInterrupt:
            self.shutdown()
        except Exception as e:
            print(f"Error: {e}")
            self.shutdown()


if __name__ == "__main__":
    launcher = GiljoLauncher()
    launcher.run()
