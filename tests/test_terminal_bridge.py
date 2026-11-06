"""El puente navegador ↔ PTY: que se cierre limpio por los dos lados, sin ensuciar el registro."""
import asyncio

import pytest
from fastapi import WebSocketDisconnect

from app.modules.terminal.terminal import bridge


class Stdout:
    def __init__(self, chunks):
        self.q = asyncio.Queue()
        for c in chunks:
            self.q.put_nowait(c)

    async def read(self, n):
        return await self.q.get()


class Proc:
    def __init__(self, chunks=()):
        self.stdout, self.closed, self.sizes = Stdout(chunks), False, []
        self.stdin = self

    def write(self, b):
        pass

    def change_terminal_size(self, c, r):
        self.sizes.append((c, r))

    def close(self):
        self.closed = True


class SSH:
    def __init__(self, proc):
        self.proc = proc

    async def process(self, *a, **kw):
        return self.proc


class WS:
    def __init__(self, incoming, fail_send=False):
        self.incoming, self.sent, self.closed, self.fail_send = asyncio.Queue(), [], False, fail_send
        self.gone = False
        for m in incoming:
            self.incoming.put_nowait(m)

    async def receive(self):
        await asyncio.sleep(0)  # como la red: deja correr a la tarea que lee de la PTY
        m = await self.incoming.get()
        self.gone = self.gone or m["type"] == "websocket.disconnect"
        return m

    async def send_bytes(self, b):
        if self.fail_send:
            raise WebSocketDisconnect(1006)
        self.sent.append(b)

    async def close(self):
        if self.closed or self.gone:
            raise WebSocketDisconnect(1006)  # como starlette si el navegador ya se fue
        self.closed = True
        self.incoming.put_nowait({"type": "websocket.disconnect"})


@pytest.fixture
async def loop_errors():
    errors = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _l, ctx: errors.append(ctx))
    yield errors
    loop.set_exception_handler(None)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)
    import gc
    gc.collect()  # «Task exception was never retrieved» sale al recoger la tarea
    await asyncio.sleep(0)


async def test_browser_leaves(loop_errors):
    proc = Proc()
    ws = WS([{"type": "websocket.receive", "text": '{"resize": [100, 30]}'}, {"type": "websocket.disconnect"}])
    await bridge(ws, SSH(proc), "bash -l", 80, 24)
    await settle()
    assert proc.closed and proc.sizes == [(100, 30)] and loop_errors == []


async def test_shell_exits(loop_errors):
    proc = Proc([b"hola\r\n", b""])
    ws = WS([])
    await asyncio.wait_for(bridge(ws, SSH(proc), "bash -l", 80, 24), 2)
    await settle()
    assert ws.sent == [b"hola\r\n"] and ws.closed and proc.closed and loop_errors == []


async def test_output_after_the_browser_left(loop_errors):
    proc = Proc([b"x"])
    ws = WS([], fail_send=True)
    task = asyncio.create_task(bridge(ws, SSH(proc), "bash -l", 80, 24))
    await settle()
    ws.incoming.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)
    await settle()
    assert proc.closed and loop_errors == []
