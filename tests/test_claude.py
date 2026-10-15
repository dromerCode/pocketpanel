import asyncio
import json
import shlex

from app.claude import ClaudeManager, build_cmd, normalize_stream, parse_session_file


def ev(**k):
    return k


def test_normalize_init_and_text_delta():
    assert normalize_stream({"type": "system", "subtype": "init", "session_id": "abc"}) == [{"t": "session", "id": "abc"}]
    d = {"type": "stream_event", "parent_tool_use_id": None,
         "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ho"}}}
    assert normalize_stream(d) == [{"t": "text", "d": "ho"}]


def test_normalize_ignores_subagent_and_thinking():
    d = {"type": "stream_event", "parent_tool_use_id": "toolu_1",
         "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}}}
    assert normalize_stream(d) == []
    d = {"type": "stream_event", "parent_tool_use_id": None,
         "event": {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "x"}}}
    assert normalize_stream(d) == []


def test_normalize_tool_use_and_result():
    a = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
        {"type": "text", "text": "voy"},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}}
    assert normalize_stream(a) == [{"t": "tool", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]
    u = {"type": "user", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "a\nb"}], "is_error": False}]}}
    assert normalize_stream(u) == [{"t": "tool_result", "id": "t1", "output": "a\nb", "error": False}]


def test_tool_result_truncated():
    u = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "x" * 20000}]}}
    out = normalize_stream(u)[0]["output"]
    assert len(out) < 9000 and out.endswith("…")


def test_normalize_result():
    r = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.07, "result": "hola"}
    assert normalize_stream(r) == [{"t": "done", "cost": 0.07, "error": None}]
    r = {"type": "result", "is_error": True, "result": "boom"}
    assert normalize_stream(r) == [{"t": "done", "cost": None, "error": "boom"}]


def test_build_cmd_quotes_message():
    nasty = "'\"; rm -rf / $(whoami)\nsegunda línea"
    cmd = build_cmd(nasty, None, home="/home/u", cwd="/srv")
    args = shlex.split(cmd.split("exec ", 1)[1])
    assert args[args.index("-p") + 1] == nasty
    assert "--resume" not in args


def test_build_cmd_resume_validates_id():
    sid = "7f0c498a-d4fb-4620-87f7-16553d8453f6"
    assert f"--resume {sid}" in build_cmd("x", sid, home="/h", cwd="/c")
    try:
        build_cmd("x", "abc; rm", home="/h", cwd="/c")
        assert False
    except ValueError:
        pass


def test_parse_session_file():
    lines = [
        {"type": "user", "timestamp": "2026-10-13T10:00:00Z", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "timestamp": "2026-10-13T10:00:01Z", "message": {"role": "user", "content": "mira docker"}},
        {"type": "assistant", "timestamp": "2026-10-13T10:00:02Z", "message": {"content": [{"type": "text", "text": "vale"}]}},
        {"type": "assistant", "timestamp": "2026-10-13T10:00:03Z", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "docker ps"}}]}},
        {"type": "user", "timestamp": "2026-10-13T10:00:04Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "isSidechain": True, "timestamp": "2026-10-13T10:00:05Z", "message": {"content": [{"type": "text", "text": "sub"}]}},
        {"type": "user", "isMeta": True, "timestamp": "2026-10-13T10:00:06Z", "message": {"content": "meta"}},
        {"type": "assistant", "timestamp": "2026-10-13T10:00:07Z", "message": {"content": [{"type": "text", "text": "todo bien"}]}},
    ]
    r = parse_session_file([json.dumps(l) for l in lines] + ["no json"])
    assert r["title"] == "mira docker"
    assert [m["t"] for m in r["messages"]] == ["user", "text", "tool", "tool_result", "text"]
    r2 = parse_session_file([json.dumps(l) for l in lines], before="2026-10-13T10:00:03Z")
    assert [m["t"] for m in r2["messages"]] == ["user", "text"]
    r3 = parse_session_file([json.dumps({"type": "ai-title", "aiTitle": "Título IA"})] + [json.dumps(l) for l in lines])
    assert r3["title"] == "Título IA"


class FakeProc:
    def __init__(self, lines, gate=None):
        self._lines, self.gate, self.stopped = lines, gate, False

    async def lines(self):
        for i, l in enumerate(self._lines):
            if self.gate and i == 1:
                await self.gate.wait()
            yield l

    async def stop(self):
        self.stopped = True

    async def wait(self):
        return 0, ""


async def test_manager_runs_and_late_subscriber_gets_snapshot():
    gate = asyncio.Event()
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
             json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hola"}}}),
             json.dumps({"type": "result", "total_cost_usd": 0.1})]
    proc = FakeProc(lines, gate)

    async def spawn(cmd):
        return proc

    m = ClaudeManager(spawn, home="/h", cwd="/c")
    early = m.subscribe()
    await m.send("hola", None)
    await asyncio.sleep(0.01)
    assert m.running and m.session == "s1"
    gate.set()
    await m.task
    assert not m.running
    late = m.subscribe()
    seen = []
    while not early.empty():
        seen.append(early.get_nowait()["t"])
    assert seen == ["user", "session", "text", "done", "idle"]
    assert [e["t"] for e in m.snapshot()] == ["user", "session", "text", "done"]
    m.unsubscribe(late)


async def test_manager_rejects_second_turn_and_stops():
    gate = asyncio.Event()
    proc = FakeProc([json.dumps({"type": "system", "subtype": "init", "session_id": "s"}), "x"], gate)

    async def spawn(cmd):
        return proc

    m = ClaudeManager(spawn, home="/h", cwd="/c")
    await m.send("a", None)
    await asyncio.sleep(0.01)
    try:
        await m.send("b", None)
        assert False
    except RuntimeError:
        pass
    q = m.subscribe()
    await m.stop()
    assert proc.stopped
    gate.set()
    await m.task
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()["t"])
    assert "stopped" in kinds and "error" not in kinds


async def test_manager_reports_failure_without_result():
    class Bad(FakeProc):
        async def wait(self):
            return 1, "not logged in"

    async def spawn(cmd):
        return Bad([])

    m = ClaudeManager(spawn, home="/h", cwd="/c")
    q = m.subscribe()
    await m.send("a", None)
    await m.task
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    assert any(e["t"] == "error" and "not logged in" in e["msg"] for e in evs)


def test_term_command_modes():
    from app.terminal import term_command
    assert term_command("shell", None, "/h", "/c", "/h/claude").endswith("bash -l")
    assert "tmux -u new-session -A -s claude" in term_command("tmux", None, "/h", "/c", "/h/claude")
    sid = "7f0c498a-d4fb-4620-87f7-16553d8453f6"
    assert f"--resume {sid}" in term_command("resume", sid, "/h", "/c", "/h/claude")
    for bad in [("resume", "x; rm -rf /"), ("resume", None), ("nope", None)]:
        try:
            term_command(bad[0], bad[1], "/h", "/c", "/h/claude")
            assert False
        except ValueError:
            pass


async def test_on_finish_gets_last_text():
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "s9"}),
             json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "miro"}}}),
             json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}}),
             json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Todo   bien\npor aquí"}}}),
             json.dumps({"type": "result", "total_cost_usd": 0})]

    async def spawn(cmd):
        return FakeProc(lines)

    got = []
    m = ClaudeManager(spawn, home="/h", cwd="/c")
    m.on_finish = lambda sid, text: got.append((sid, text))
    await m.send("x", None)
    await m.task
    assert got == [("s9", "Todo bien por aquí")]


def test_build_cmd_uses_configured_bin():
    cmd = build_cmd("x", None, home="/home/u", cwd="/srv", bin="/usr/local/bin/claude")
    assert shlex.split(cmd.split("exec ", 1)[1])[2] == "/usr/local/bin/claude"


def test_term_tmux_runs_configured_bin():
    from app.terminal import term_command
    cmd = term_command("tmux", None, "/home/u", "/srv", "/opt/claude")
    assert "/opt/claude" in cmd and "HOME=/home/u" in cmd
