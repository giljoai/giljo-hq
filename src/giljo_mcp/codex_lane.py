# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.
# ruff: noqa: T201  # CLI tool: print() to stdout is the conductor-facing interface.


from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Self
from urllib.parse import urlparse

from giljo_mcp.exceptions import BaseGiljoError
from giljo_mcp.port_manager import PortManager


logger = logging.getLogger(__name__)

APPROVAL_POLICY = "never"
SANDBOX_MODE = "danger-full-access"
INCLUDE_TURNS = True

RUNNING_TURN_STATUSES = frozenset({"inProgress", "queued", "pending"})
SUCCESS_TURN_STATUS = "completed"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})

CLIENT_NAME = "giljo-codex-lane"

DEFAULT_CALL_TIMEOUT = 60.0
DEFAULT_POLL_TIMEOUT = 900.0
DEFAULT_POLL_INTERVAL = 5.0
SERVER_READY_TIMEOUT = 30.0


class CodexLaneFaultError(BaseGiljoError):
    pass


def _loopback_ws_url(host: str, port: int) -> str:
    if host not in LOOPBACK_HOSTS:
        raise CodexLaneFaultError(
            f"Refusing non-loopback host {host!r}. The codex app-server child must bind loopback only.",
            error_code="NON_LOOPBACK_HOST",
            context={"host": host, "allowed": sorted(LOOPBACK_HOSTS)},
        )
    bracketed = f"[{host}]" if ":" in host else host
    return f"ws://{bracketed}:{port}"


def assert_loopback_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "ws":
        raise CodexLaneFaultError(
            f"Refusing URL scheme {parsed.scheme!r}; the lane transport is plain ws:// on loopback.",
            error_code="BAD_URL_SCHEME",
            context={"url": url},
        )
    host = (parsed.hostname or "").strip()
    if host not in LOOPBACK_HOSTS:
        raise CodexLaneFaultError(
            f"Refusing non-loopback URL {url!r}. Only {sorted(LOOPBACK_HOSTS)} are allowed.",
            error_code="NON_LOOPBACK_URL",
            context={"url": url, "host": host},
        )
    return url


def resolve_codex_binary() -> str:
    found = shutil.which("codex")
    if not found:
        raise CodexLaneFaultError(
            "codex CLI not found on PATH. The app-server lane transport requires it; "
            "the conductor should fall back to the classic spawn row.",
            error_code="CODEX_NOT_FOUND",
        )
    return found


def _import_websockets():
    try:
        import websockets
    except ImportError as exc:
        raise CodexLaneFaultError(
            "The 'websockets' package is required for the codex app-server lane transport. "
            "It ships with uvicorn[standard]; reinstall requirements to restore it.",
            error_code="WEBSOCKETS_MISSING",
        ) from exc
    return websockets


class LaneConnection:

    def __init__(self, url: str):
        self.url = assert_loopback_url(url)
        self._ws = None
        self._next_id = 0
        self._websockets = None

    async def __aenter__(self) -> Self:
        self._websockets = _import_websockets()
        try:
            self._ws = await self._websockets.connect(self.url, max_size=None)
        except OSError as exc:
            raise CodexLaneFaultError(
                f"Could not connect to the codex app-server at {self.url}: {exc}",
                error_code="SERVER_UNREACHABLE",
                context={"url": self.url},
            ) from exc
        await self._handshake()
        return self

    async def __aexit__(self, *_exc_info) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def _allocate_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, method: str, params: dict | None, *, notify: bool = False) -> int | None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        request_id = None
        if not notify:
            request_id = self._allocate_id()
            message["id"] = request_id
        await self._ws.send(json.dumps(message))
        return request_id

    @staticmethod
    def _parse_frame(frame: str | bytes) -> list[dict]:
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8")
        parsed = []
        for raw_line in frame.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Unparsable frame from codex app-server: %s", line[:200])
        return parsed

    @staticmethod
    def classify(message: dict) -> str:
        has_method = message.get("method") is not None
        has_id = message.get("id") is not None
        if has_method and has_id:
            return "server_request"
        if has_method:
            return "notification"
        if has_id:
            return "response"
        return "unknown"

    def _reject_server_request(self, message: dict) -> None:
        raise CodexLaneFaultError(
            f"codex app-server sent a server->client request the lane driver cannot answer: "
            f"{message.get('method')!r}. The turn would stall. Check that approvalPolicy is "
            f"still {APPROVAL_POLICY!r} on this codex version.",
            error_code="UNANSWERED_SERVER_REQUEST",
            context={"method": message.get("method"), "request_id": message.get("id")},
        )

    async def call(self, method: str, params: dict | None, timeout: float = DEFAULT_CALL_TIMEOUT) -> dict:
        request_id = await self._send(method, params)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexLaneFaultError(
                    f"No response to {method!r} within {timeout:.0f}s.",
                    error_code="CALL_TIMEOUT",
                    context={"method": method, "timeout_s": timeout},
                )
            try:
                frame = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
            except TimeoutError as exc:
                raise CodexLaneFaultError(
                    f"No response to {method!r} within {timeout:.0f}s.",
                    error_code="CALL_TIMEOUT",
                    context={"method": method, "timeout_s": timeout},
                ) from exc
            for message in self._parse_frame(frame):
                kind = self.classify(message)
                if kind == "server_request":
                    self._reject_server_request(message)
                if kind == "response" and message.get("id") == request_id:
                    if "error" in message:
                        raise CodexLaneFaultError(
                            f"codex app-server rejected {method!r}: {message['error']}",
                            error_code="RPC_ERROR",
                            context={"method": method, "error": message["error"]},
                        )
                    return message.get("result") or {}

    async def _handshake(self) -> dict:
        result = await self.call(
            "initialize",
            {"clientInfo": {"name": CLIENT_NAME, "title": "Giljo HQ codex lane", "version": _client_version()}},
        )
        await self._send("initialized", {}, notify=True)
        return result


def _client_version() -> str:
    from giljo_mcp import __version__

    return __version__




def probe() -> dict:
    binary = resolve_codex_binary()
    try:
        completed = subprocess.run(
            [binary, "app-server", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": True, "app_server_capable": False, "reason": "codex app-server --help timed out"}
    output = f"{completed.stdout}{completed.stderr}"
    capable = completed.returncode == 0 and "--listen" in output
    return {
        "ok": True,
        "app_server_capable": capable,
        "codex_binary": binary,
        "exit_code": completed.returncode,
        "listen_flag_present": "--listen" in output,
    }


def _pick_loopback_port(requested: int | None) -> int:
    if requested is not None:
        if not PortManager.check_port_available(requested):
            raise CodexLaneFaultError(
                f"Port {requested} is already in use on loopback.",
                error_code="PORT_IN_USE",
                context={"port": requested},
            )
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return probe_socket.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = SERVER_READY_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def start_server(port: int | None = None, host: str = "127.0.0.1", cwd: str | None = None) -> dict:
    binary = resolve_codex_binary()
    url = _loopback_ws_url(host, _pick_loopback_port(port))
    resolved_port = urlparse(url).port

    creation_flags = 0
    start_new_session = False
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        start_new_session = True

    child = subprocess.Popen(
        [binary, "app-server", "--listen", url],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        start_new_session=start_new_session,
    )

    if not _wait_for_server(host, resolved_port):
        _terminate_process_tree(child.pid)
        raise CodexLaneFaultError(
            f"codex app-server did not accept connections on {url} within {SERVER_READY_TIMEOUT:.0f}s.",
            error_code="SERVER_START_TIMEOUT",
            context={"url": url, "pid": child.pid},
        )

    return {"ok": True, "url": url, "host": host, "port": resolved_port, "pid": child.pid}


def _listen_url_of(pid: int) -> str | None:
    import psutil

    try:
        argv = psutil.Process(pid).cmdline() or []
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    lowered = [str(arg).lower() for arg in argv]
    joined = " ".join(lowered)
    if "codex" not in joined or "app-server" not in lowered:
        return None
    for index, arg in enumerate(lowered):
        if arg == "--listen" and index + 1 < len(lowered):
            candidate = lowered[index + 1]
            try:
                return assert_loopback_url(candidate)
            except CodexLaneFaultError:
                return None
        if arg.startswith("--listen="):
            try:
                return assert_loopback_url(arg.split("=", 1)[1])
            except CodexLaneFaultError:
                return None
    return None


def _is_codex_app_server(pid: int, url: str | None = None) -> bool:
    listening_on = _listen_url_of(pid)
    if listening_on is None:
        return False
    return listening_on == url.lower() if url else True


def _terminate_process_tree(pid: int, timeout: float = 10.0) -> dict:
    import psutil

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return {"stopped_pids": [], "required_kill": [], "already_gone": True}

    try:
        members = [*parent.children(recursive=True), parent]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        members = [parent]

    for member in members:
        try:
            member.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _gone, alive = psutil.wait_procs(members, timeout=timeout)
    for member in alive:
        try:
            member.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone_after_kill, survivors = psutil.wait_procs(alive, timeout=timeout)

    if survivors:
        raise CodexLaneFaultError(
            f"Could not stop every codex app-server process under pid {pid}; "
            f"{[p.pid for p in survivors]} survived and may still hold the port.",
            error_code="SERVER_STOP_INCOMPLETE",
            context={"pid": pid, "survivors": [p.pid for p in survivors]},
        )

    return {
        "stopped_pids": [member.pid for member in members],
        "required_kill": [member.pid for member in alive],
        "already_gone": False,
    }


def stop_server(pid: int, url: str | None = None, timeout: float = 10.0) -> dict:
    if not _is_codex_app_server(pid, url):
        raise CodexLaneFaultError(
            f"pid {pid} is not a loopback-listening `codex app-server` this driver started; refusing to signal it.",
            error_code="NOT_A_CODEX_APP_SERVER",
            context={"pid": pid, "expected_url": url},
        )
    outcome = _terminate_process_tree(pid, timeout=timeout)
    return {"ok": True, "pid": pid, "stopped": True, **outcome}


async def thread_start(url: str, cwd: str, model: str | None = None) -> dict:
    params: dict[str, Any] = {
        "cwd": cwd,
        "approvalPolicy": APPROVAL_POLICY,
        "sandbox": SANDBOX_MODE,
    }
    if model:
        params["model"] = model
    async with LaneConnection(url) as connection:
        result = await connection.call("thread/start", params)
    thread = result.get("thread") or result
    thread_id = thread.get("id")
    if not thread_id:
        raise CodexLaneFaultError(
            "thread/start returned no thread id.",
            error_code="NO_THREAD_ID",
            context={"result": result},
        )
    return {
        "ok": True,
        "thread_id": thread_id,
        "approval_policy": APPROVAL_POLICY,
        "sandbox": SANDBOX_MODE,
        "model": thread.get("model") or model,
    }


async def turn_start(url: str, thread_id: str, prompt: str, model: str | None = None) -> dict:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
    }
    if model:
        params["model"] = model
    async with LaneConnection(url) as connection:
        result = await connection.call("turn/start", params)
    turn = result.get("turn") or result
    turn_id = turn.get("id")
    if not turn_id:
        raise CodexLaneFaultError(
            "turn/start returned no turn id; the lane would have nothing to poll.",
            error_code="NO_TURN_ID",
            context={"result": result},
        )
    return {"ok": True, "thread_id": thread_id, "turn_id": turn_id, "status": turn.get("status")}


def _find_turn(result: dict, turn_id: str) -> dict | None:
    thread = result.get("thread") or result
    for turn in thread.get("turns") or []:
        if turn.get("id") == turn_id:
            return turn
    return None


def _turn_texts(turn: dict) -> list[str]:
    return [
        item["text"]
        for item in turn.get("items") or []
        if item.get("type") in ("agentMessage", "assistantMessage") and item.get("text")
    ]


async def read_turn(url: str, thread_id: str, turn_id: str) -> dict | None:
    async with LaneConnection(url) as connection:
        result = await connection.call(
            "thread/read",
            {"threadId": thread_id, "includeTurns": INCLUDE_TURNS},
        )
    return _find_turn(result, turn_id)


async def poll_turn(
    url: str,
    thread_id: str,
    turn_id: str,
    timeout: float = DEFAULT_POLL_TIMEOUT,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> dict:
    started = time.monotonic()
    deadline = started + timeout
    polls = 0
    last_status = None
    while time.monotonic() < deadline:
        turn = await read_turn(url, thread_id, turn_id)
        polls += 1
        if turn is not None:
            last_status = turn.get("status")
            if last_status and last_status not in RUNNING_TURN_STATUSES:
                return {
                    "ok": last_status == SUCCESS_TURN_STATUS,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "status": last_status,
                    "texts": _turn_texts(turn),
                    "error": turn.get("error"),
                    "polls": polls,
                    "elapsed_s": round(time.monotonic() - started, 1),
                }
        await asyncio.sleep(interval)

    raise CodexLaneFaultError(
        f"Turn {turn_id} was still {last_status or 'unseen'} after {timeout:.0f}s. "
        "A turn that never reaches a terminal status usually means the server sent a "
        "request nobody answered while the driver was disconnected.",
        error_code="TURN_POLL_TIMEOUT",
        context={
            "thread_id": thread_id,
            "turn_id": turn_id,
            "last_status": last_status,
            "polls": polls,
            "timeout_s": timeout,
        },
    )




def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m giljo_mcp.codex_lane",
        description="Drive a headless codex lane over the app-server JSON-RPC transport.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="Is the installed codex app-server capable?")

    start = sub.add_parser("start-server", help="Start a loopback-bound codex app-server child.")
    start.add_argument("--port", type=int, default=None, help="Loopback port (default: a free one).")
    start.add_argument("--cwd", default=None, help="Working directory for the child.")

    stop = sub.add_parser("stop-server", help="Stop a codex app-server child by pid.")
    stop.add_argument("--pid", type=int, required=True)
    stop.add_argument("--url", default=None, help="The URL start-server returned, to confirm the right child.")

    thread = sub.add_parser("thread-start", help="Start a lane thread.")
    thread.add_argument("--url", required=True)
    thread.add_argument("--cwd", required=True)
    thread.add_argument("--model", default=None)

    turn = sub.add_parser("turn-start", help="Start a turn and disconnect.")
    turn.add_argument("--url", required=True)
    turn.add_argument("--thread-id", required=True)
    turn.add_argument("--prompt", default=None)
    turn.add_argument("--prompt-file", default=None, help="Read the prompt from a file instead of argv.")
    turn.add_argument("--model", default=None)

    poll = sub.add_parser("poll", help="Poll one turn until it is terminal.")
    poll.add_argument("--url", required=True)
    poll.add_argument("--thread-id", required=True)
    poll.add_argument("--turn-id", required=True)
    poll.add_argument("--timeout", type=float, default=DEFAULT_POLL_TIMEOUT)
    poll.add_argument("--interval", type=float, default=DEFAULT_POLL_INTERVAL)

    return parser


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        from pathlib import Path

        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt is None:
        raise CodexLaneFaultError(
            "turn-start needs --prompt or --prompt-file.",
            error_code="NO_PROMPT",
        )
    return args.prompt


def dispatch(args: argparse.Namespace) -> dict:
    if args.command == "probe":
        return probe()
    if args.command == "start-server":
        return start_server(port=args.port, cwd=args.cwd)
    if args.command == "stop-server":
        return stop_server(args.pid, args.url)
    if args.command == "thread-start":
        return asyncio.run(thread_start(args.url, args.cwd, args.model))
    if args.command == "turn-start":
        return asyncio.run(turn_start(args.url, args.thread_id, _read_prompt(args), args.model))
    if args.command == "poll":
        return asyncio.run(poll_turn(args.url, args.thread_id, args.turn_id, args.timeout, args.interval))
    raise CodexLaneFaultError(f"Unknown command {args.command!r}.", error_code="UNKNOWN_COMMAND")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = dispatch(args)
    except CodexLaneFaultError as fault:
        print(json.dumps({"ok": False, **fault.to_dict()}, indent=2))
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
