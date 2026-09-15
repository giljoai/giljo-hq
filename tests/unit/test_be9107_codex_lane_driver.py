# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import argparse
import asyncio
import json
import os

import pytest

from giljo_mcp import codex_lane
from giljo_mcp.codex_lane import CodexLaneFaultError, LaneConnection


THREAD_ID_6 = "01a00931-d699-7712-9777-16e11cc82906"
TURN_ID_6 = "01a00931-e6c2-7381-b77b-e2f11a323906"
OTHER_TURN_ID_6 = "01a00931-e6c2-7381-b77b-e2f11a323907"


class FakeWebSocket:

    def __init__(self, responder):
        self.responder = responder
        self.sent: list[dict] = []
        self._inbox: list[str] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)
        frames = self.responder(message)
        for frame in frames or []:
            self._inbox.append(json.dumps(frame))

    async def recv(self) -> str:
        if not self._inbox:
            await asyncio.sleep(3600)
        return self._inbox.pop(0)

    async def close(self) -> None:
        self.closed = True

    def params_for(self, method: str) -> dict:
        for message in self.sent:
            if message.get("method") == method:
                return message.get("params") or {}
        raise AssertionError(f"driver never sent {method!r}; sent {[m.get('method') for m in self.sent]}")


def install_fake_transport(monkeypatch, responder) -> list[FakeWebSocket]:
    opened: list[FakeWebSocket] = []

    class _FakeWebsocketsModule:
        @staticmethod
        async def connect(_url, **_kwargs):
            socket = FakeWebSocket(responder)
            opened.append(socket)
            return socket

    monkeypatch.setattr(codex_lane, "_import_websockets", lambda: _FakeWebsocketsModule)
    return opened


def initialize_response(message: dict) -> list[dict]:
    return [{"id": message["id"], "result": {"userAgent": "giljo-codex-lane/0.146.0"}}]


def _turn(status: str, *, turn_id: str = TURN_ID_6, text: str = "DONE-6") -> dict:
    return {
        "id": turn_id,
        "status": status,
        "items": [{"type": "agentMessage", "text": text, "phase": "final_answer"}],
    }


def scripted_server(*, turns: list[dict] | None = None, extra: dict | None = None):

    def responder(message: dict) -> list[dict]:
        method = message.get("method")
        if method == "initialize":
            return initialize_response(message)
        if method == "initialized":
            return []
        if method == "thread/start":
            return [{"id": message["id"], "result": {"thread": {"id": THREAD_ID_6, "status": {"type": "idle"}}}}]
        if method == "turn/start":
            return [{"id": message["id"], "result": {"turn": {"id": TURN_ID_6, "status": "inProgress"}}}]
        if method == "thread/read":
            return [{"id": message["id"], "result": {"thread": {"id": THREAD_ID_6, "turns": turns or []}}}]
        if extra and method in extra:
            return extra[method](message)
        raise AssertionError(f"unscripted method {method!r}")

    return responder




class TestThePinnedLiterals:

    def test_approval_policy_is_never(self):
        assert codex_lane.APPROVAL_POLICY == "never"

    def test_sandbox_is_danger_full_access(self):
        assert codex_lane.SANDBOX_MODE == "danger-full-access"

    def test_include_turns_is_true(self):
        assert codex_lane.INCLUDE_TURNS is True

    async def test_thread_start_puts_both_autonomy_literals_on_the_wire(self, monkeypatch):
        opened = install_fake_transport(monkeypatch, scripted_server())

        result = await codex_lane.thread_start("ws://127.0.0.1:8916", cwd="C:/scratch6")

        params = opened[0].params_for("thread/start")
        assert params["approvalPolicy"] == "never"
        assert params["sandbox"] == "danger-full-access"
        assert result["thread_id"] == THREAD_ID_6

    async def test_thread_read_always_asks_for_turns(self, monkeypatch):
        opened = install_fake_transport(monkeypatch, scripted_server(turns=[_turn("completed")]))

        await codex_lane.read_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6)

        assert opened[0].params_for("thread/read")["includeTurns"] is True


class TestTheLiteralsCannotBeOverriddenFromArgv:

    @pytest.mark.parametrize("forbidden", ["--approval-policy", "--sandbox", "--include-turns", "--approval"])
    def test_no_subcommand_exposes_an_autonomy_flag(self, forbidden):
        parser = codex_lane.build_parser()
        for argv in (
            ["thread-start", "--url", "ws://127.0.0.1:8916", "--cwd", "C:/scratch6", forbidden, "on-request"],
            ["turn-start", "--url", "ws://127.0.0.1:8916", "--thread-id", THREAD_ID_6, "--prompt", "x", forbidden, "y"],
        ):
            with pytest.raises(SystemExit):
                parser.parse_args(argv)

    async def test_thread_start_ignores_a_caller_supplied_policy(self, monkeypatch):
        opened = install_fake_transport(monkeypatch, scripted_server())

        await codex_lane.thread_start("ws://127.0.0.1:8916", cwd="C:/scratch6", model="gpt-5.6-sol")

        params = opened[0].params_for("thread/start")
        assert params["approvalPolicy"] == "never"
        assert params["model"] == "gpt-5.6-sol"




class TestAnyUnansweredServerRequestIsALaneFault:

    @pytest.mark.parametrize(
        "method",
        [
            "item/fileChange/requestApproval",
            "item/commandExecution/requestApproval",
            "item/permissions/requestApproval",
            "item/tool/requestUserInput",
            "mcpServer/elicitation/request",
            "applyPatchApproval",
            "execCommandApproval",
            "attestation/generate",
            "item/tool/call",
            "account/chatgptAuthTokens/refresh",
            "some/method/invented/in/a/later/codex",
        ],
    )
    async def test_it_faults_instead_of_stalling(self, monkeypatch, method):
        def responder(message):
            if message.get("method") == "initialize":
                return initialize_response(message)
            if message.get("method") == "initialized":
                return []
            return [{"jsonrpc": "2.0", "method": method, "id": 99, "params": {}}]

        install_fake_transport(monkeypatch, responder)

        with pytest.raises(CodexLaneFaultError) as caught:
            await codex_lane.thread_start("ws://127.0.0.1:8916", cwd="C:/scratch6")

        assert caught.value.error_code == "UNANSWERED_SERVER_REQUEST"
        assert caught.value.context["method"] == method

    def test_classification_distinguishes_the_three_message_kinds(self):
        assert LaneConnection.classify({"method": "item/tool/call", "id": 4}) == "server_request"
        assert LaneConnection.classify({"method": "turn/completed", "params": {}}) == "notification"
        assert LaneConnection.classify({"id": 4, "result": {}}) == "response"
        assert LaneConnection.classify({"id": 4, "error": {"code": -1}}) == "response"

    def test_a_request_with_id_zero_still_counts(self):
        assert LaneConnection.classify({"method": "applyPatchApproval", "id": 0}) == "server_request"

    async def test_a_notification_does_not_fault(self, monkeypatch):
        def responder(message):
            if message.get("method") == "initialize":
                return initialize_response(message)
            if message.get("method") == "initialized":
                return []
            return [
                {"method": "thread/status/changed", "params": {"status": {"type": "active"}}},
                {"method": "turn/started", "params": {}},
                {"id": message["id"], "result": {"thread": {"id": THREAD_ID_6}}},
            ]

        install_fake_transport(monkeypatch, responder)

        result = await codex_lane.thread_start("ws://127.0.0.1:8916", cwd="C:/scratch6")

        assert result["thread_id"] == THREAD_ID_6




class TestPollingReadsThePerTurnStatus:
    async def test_completed_turn_is_reported_with_its_text(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server(turns=[_turn("completed")]))

        result = await codex_lane.poll_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6, timeout=5, interval=0)

        assert result["ok"] is True
        assert result["status"] == "completed"
        assert result["texts"] == ["DONE-6"]

    async def test_failed_turn_is_terminal_but_not_ok(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server(turns=[_turn("failed")]))

        result = await codex_lane.poll_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6, timeout=5, interval=0)

        assert result["ok"] is False
        assert result["status"] == "failed"

    async def test_an_unrecognised_status_surfaces_instead_of_polling_forever(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server(turns=[_turn("cancelledByOperator")]))

        result = await codex_lane.poll_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6, timeout=5, interval=0)

        assert result["ok"] is False
        assert result["status"] == "cancelledByOperator"

    async def test_another_turns_completion_is_not_mistaken_for_ours(self, monkeypatch):
        turns = [_turn("completed", turn_id=OTHER_TURN_ID_6, text="AN OLDER TURN"), _turn("inProgress")]
        install_fake_transport(monkeypatch, scripted_server(turns=turns))

        with pytest.raises(CodexLaneFaultError) as caught:
            await codex_lane.poll_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6, timeout=0.3, interval=0.1)

        assert caught.value.error_code == "TURN_POLL_TIMEOUT"
        assert caught.value.context["last_status"] == "inProgress"

    async def test_a_turn_that_never_finishes_faults_with_the_hypothesis_named(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server(turns=[_turn("inProgress")]))

        with pytest.raises(CodexLaneFaultError) as caught:
            await codex_lane.poll_turn("ws://127.0.0.1:8916", THREAD_ID_6, TURN_ID_6, timeout=0.3, interval=0.1)

        assert caught.value.error_code == "TURN_POLL_TIMEOUT"
        assert "request nobody answered" in caught.value.message

    async def test_turn_start_returns_the_turn_id_the_poller_needs(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server())

        result = await codex_lane.turn_start("ws://127.0.0.1:8916", THREAD_ID_6, "do the thing")

        assert result["turn_id"] == TURN_ID_6
        assert result["status"] == "inProgress"




class TestLoopbackIsEnforcedNotDocumented:
    @pytest.mark.parametrize(
        "url",
        [
            "ws://0.0.0.0:8916",
            "ws://198.51.100.7:8916",
            "ws://example.invalid:8916",
            "ws://localhost:8916",
            "wss://127.0.0.1:8916",
            "http://127.0.0.1:8916",
        ],
    )
    def test_non_loopback_urls_are_refused(self, url):
        with pytest.raises(CodexLaneFaultError) as caught:
            codex_lane.assert_loopback_url(url)
        assert caught.value.error_code in ("NON_LOOPBACK_URL", "BAD_URL_SCHEME")

    @pytest.mark.parametrize("url", ["ws://127.0.0.1:8916", "ws://[::1]:8916"])
    def test_loopback_urls_are_accepted(self, url):
        assert codex_lane.assert_loopback_url(url) == url

    async def test_a_lane_cannot_dial_a_remote_codex(self, monkeypatch):
        install_fake_transport(monkeypatch, scripted_server())

        with pytest.raises(CodexLaneFaultError) as caught:
            await codex_lane.thread_start("ws://198.51.100.7:8916", cwd="C:/scratch6")

        assert caught.value.error_code == "NON_LOOPBACK_URL"

    def test_the_server_child_url_is_built_loopback_only(self):
        assert codex_lane._loopback_ws_url("127.0.0.1", 8916) == "ws://127.0.0.1:8916"
        with pytest.raises(CodexLaneFaultError):
            codex_lane._loopback_ws_url("0.0.0.0", 8916)


class TestStopServerRefusesToSignalAnythingElse:
    def test_a_pid_that_is_not_a_codex_app_server_is_refused(self, monkeypatch):
        monkeypatch.setattr(codex_lane, "_is_codex_app_server", lambda *_args: False)

        with pytest.raises(CodexLaneFaultError) as caught:
            codex_lane.stop_server(999906)

        assert caught.value.error_code == "NOT_A_CODEX_APP_SERVER"


class FakeProcess:

    def __init__(self, pid, children=(), *, stubborn=False):
        self.pid = pid
        self._children = list(children)
        self.stubborn = stubborn
        self.terminated = False
        self.killed = False

    def children(self, recursive=False):  # noqa: ARG002 - signature parity with psutil
        if self.terminated:
            return []
        return list(self._children)

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.killed = True

    def kill(self):
        self.killed = True

    def is_running(self):
        return not self.killed


class TestTheGuardDistinguishesOurChildFromTheOperatorsCodex:

    @staticmethod
    def _with_cmdline(monkeypatch, argv):
        class _Proc:
            def __init__(self, _pid):
                pass

            @staticmethod
            def cmdline():
                return argv

        class _FakePsutil:
            NoSuchProcess = LookupError
            AccessDenied = PermissionError
            Process = _Proc

        monkeypatch.setitem(__import__("sys").modules, "psutil", _FakePsutil)

    DESKTOP_APP = [
        r"C:\Program Files\WindowsApps\OpenAI.Codex_26.803.10989.0_x64__2p2nqsd0c76g0\app\resources\codex.exe",
        "-c",
        "features.code_mode_host=true",
        "app-server",
        "--analytics-default-enabled",
    ]
    OUR_CHILD = [
        r"C:\WINDOWS\system32\cmd.exe",
        "/c",
        r"C:\Users\user\AppData\Roaming\npm\codex.CMD",
        "app-server",
        "--listen",
        "ws://127.0.0.1:49481",
    ]

    def test_the_operators_desktop_codex_is_not_killable(self, monkeypatch):
        self._with_cmdline(monkeypatch, self.DESKTOP_APP)

        assert codex_lane._is_codex_app_server(27276) is False

        with pytest.raises(CodexLaneFaultError) as caught:
            codex_lane.stop_server(27276)
        assert caught.value.error_code == "NOT_A_CODEX_APP_SERVER"

    def test_our_own_loopback_child_is_recognised(self, monkeypatch):
        self._with_cmdline(monkeypatch, self.OUR_CHILD)

        assert codex_lane._is_codex_app_server(25964) is True
        assert codex_lane._listen_url_of(25964) == "ws://127.0.0.1:49481"

    def test_a_non_loopback_listener_is_not_ours(self, monkeypatch):
        self._with_cmdline(monkeypatch, [*self.OUR_CHILD[:-1], "ws://0.0.0.0:49481"])

        assert codex_lane._is_codex_app_server(25964) is False

    def test_the_url_must_match_when_given(self, monkeypatch):
        self._with_cmdline(monkeypatch, self.OUR_CHILD)

        assert codex_lane._is_codex_app_server(25964, "ws://127.0.0.1:49481") is True
        assert codex_lane._is_codex_app_server(25964, "ws://127.0.0.1:8916") is False

    def test_the_equals_form_of_listen_is_read(self, monkeypatch):
        self._with_cmdline(monkeypatch, [*self.OUR_CHILD[:-2], "--listen=ws://127.0.0.1:49481"])

        assert codex_lane._listen_url_of(25964) == "ws://127.0.0.1:49481"

    def test_an_unrelated_process_is_not_ours(self, monkeypatch):
        self._with_cmdline(monkeypatch, ["python.exe", "-m", "http.server", "--listen", "ws://127.0.0.1:49481"])

        assert codex_lane._is_codex_app_server(4242) is False


class TestStopServerKillsTheWholeTree:

    @staticmethod
    def _install(monkeypatch, parent):
        registry = {parent.pid: parent}

        class _FakePsutil:
            NoSuchProcess = LookupError
            AccessDenied = PermissionError
            TimeoutExpired = TimeoutError

            @staticmethod
            def Process(pid):  # noqa: N802 - psutil's own casing
                if pid not in registry:
                    raise LookupError(pid)
                return registry[pid]

            @staticmethod
            def wait_procs(procs, timeout=None):  # noqa: ARG004 - signature parity
                gone = [p for p in procs if p.killed]
                alive = [p for p in procs if not p.killed]
                return gone, alive

        monkeypatch.setitem(__import__("sys").modules, "psutil", _FakePsutil)
        return registry

    def test_every_descendant_is_terminated_not_just_the_launched_pid(self, monkeypatch):
        listener = FakeProcess(22868)
        node = FakeProcess(29020)
        shim = FakeProcess(25964, children=[node, listener])
        self._install(monkeypatch, shim)
        monkeypatch.setattr(codex_lane, "_is_codex_app_server", lambda *_args: True)

        result = codex_lane.stop_server(25964)

        assert listener.terminated is True, "the process actually holding the port survived"
        assert node.terminated is True
        assert shim.terminated is True
        assert sorted(result["stopped_pids"]) == [22868, 25964, 29020]

    def test_a_survivor_is_a_fault_not_a_clean_stop(self, monkeypatch):
        listener = FakeProcess(22868, stubborn=True)
        listener.kill = lambda: None
        shim = FakeProcess(25964, children=[listener])
        self._install(monkeypatch, shim)
        monkeypatch.setattr(codex_lane, "_is_codex_app_server", lambda *_args: True)

        with pytest.raises(CodexLaneFaultError) as caught:
            codex_lane.stop_server(25964)

        assert caught.value.error_code == "SERVER_STOP_INCOMPLETE"
        assert 22868 in caught.value.context["survivors"]

    def test_an_already_dead_pid_is_not_an_error(self, monkeypatch):
        self._install(monkeypatch, FakeProcess(25964))
        monkeypatch.setattr(codex_lane, "_is_codex_app_server", lambda *_args: True)

        assert codex_lane._terminate_process_tree(999906)["already_gone"] is True




class TestCliSurface:
    def test_a_fault_prints_json_and_exits_non_zero(self, capsys):
        exit_code = codex_lane.main(["thread-start", "--url", "ws://0.0.0.0:8916", "--cwd", "C:/scratch6"])

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["error_code"] == "NON_LOOPBACK_URL"

    def test_success_prints_json_and_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(codex_lane, "probe", lambda: {"ok": True, "app_server_capable": True})

        exit_code = codex_lane.main(["probe"])

        assert exit_code == 0
        assert json.loads(capsys.readouterr().out)["app_server_capable"] is True

    def test_turn_start_without_a_prompt_is_a_fault_not_a_traceback(self):
        args = argparse.Namespace(prompt=None, prompt_file=None)
        with pytest.raises(CodexLaneFaultError) as caught:
            codex_lane._read_prompt(args)
        assert caught.value.error_code == "NO_PROMPT"

    def test_prompt_file_is_read(self, tmp_path):
        prompt_file = tmp_path / "mission6.txt"
        prompt_file.write_text("lane 6 mission", encoding="utf-8")

        args = argparse.Namespace(prompt=None, prompt_file=str(prompt_file))

        assert codex_lane._read_prompt(args) == "lane 6 mission"




def _pids_listening_on(port: int) -> set[int]:
    import psutil

    pids = set()
    for connection in psutil.net_connections(kind="tcp"):
        if connection.status == psutil.CONN_LISTEN and connection.laddr and connection.laddr.port == port:
            if connection.pid:
                pids.add(connection.pid)
    return pids


@pytest.mark.integration
class TestLiveCodexAppServer:

    @pytest.mark.timeout(300)
    def test_a_real_lane_runs_end_to_end_and_the_child_is_stopped(self, tmp_path):
        if os.environ.get("GILJO_CODEX_LANE_LIVE") != "1":
            pytest.skip(reason="live codex app-server test; set GILJO_CODEX_LANE_LIVE=1 to run it")

        capability = codex_lane.probe()
        assert capability["app_server_capable"] is True

        started = codex_lane.start_server(cwd=str(tmp_path))
        try:
            assert started["url"].startswith("ws://127.0.0.1:")
            thread = asyncio.run(codex_lane.thread_start(started["url"], cwd=str(tmp_path)))
            turn = asyncio.run(
                codex_lane.turn_start(
                    started["url"],
                    thread["thread_id"],
                    "Reply with exactly the word LIVE-6 and nothing else.",
                )
            )
            result = asyncio.run(
                codex_lane.poll_turn(started["url"], thread["thread_id"], turn["turn_id"], timeout=180, interval=5)
            )
            assert result["status"] == "completed"
            assert any("LIVE-6" in text for text in result["texts"])
            listeners_during = _pids_listening_on(started["port"])
            assert listeners_during, "no process was listening on the lane port"
        finally:
            codex_lane.stop_server(started["pid"])

        assert codex_lane._is_codex_app_server(started["pid"]) is False
        assert _pids_listening_on(started["port"]) == set(), "the app-server still holds the port"
