#!/usr/bin/env python3

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Simple HTTP server to serve the production-built Vue frontend.
Serves files from frontend/dist/ directory with SPA routing support.
"""

import http.server
import socketserver
from pathlib import Path


PORT = 7274
DIRECTORY = Path(__file__).parent / "frontend" / "dist"


class SPAHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIRECTORY), **kwargs)

    def do_GET(self):
        # Get the file path
        path = self.translate_path(self.path)

        # If the path is a directory or file doesn't exist, serve index.html (SPA routing)
        file_path = Path(path)
        if (file_path.is_dir() or not file_path.exists()) and not self.path.startswith(("/api/", "/ws/")):
            self.path = "/index.html"

        return super().do_GET()

    def end_headers(self):
        # Add CORS headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), SPAHTTPRequestHandler) as httpd:
        print(f"Serving frontend at http://0.0.0.0:{PORT}")
        print(f"Directory: {DIRECTORY}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
