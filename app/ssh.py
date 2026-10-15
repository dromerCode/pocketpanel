import asyncio

import asyncssh


class SSHError(Exception):
    pass


class SSH:
    """Conexión SSH compartida con el host; se rehace sola si se cae."""

    def __init__(self, host: str, user: str, key: str, known_hosts: str, port: int = 22):
        self.host, self.user, self.key, self.known_hosts, self.port = host, user, key, known_hosts, port
        self._conn = None
        self._lock = asyncio.Lock()

    async def conn(self):
        async with self._lock:
            if self._conn is None or self._conn.is_closed():
                try:
                    self._conn = await asyncio.wait_for(asyncssh.connect(
                        self.host, port=self.port, username=self.user, client_keys=[self.key],
                        known_hosts=self.known_hosts, keepalive_interval=30), 10)
                except (OSError, ValueError, asyncssh.Error, asyncio.TimeoutError) as e:
                    raise SSHError(f"no conecta por SSH: {e}") from e
            return self._conn

    async def run(self, cmd: str, timeout: float = 15) -> str:
        c = await self.conn()
        try:
            r = await asyncio.wait_for(c.run(cmd, check=False), timeout)
        except asyncio.TimeoutError as e:
            raise SSHError(f"tiempo agotado ({timeout:.0f} s): {cmd.strip().splitlines()[0][:60]}") from e
        except asyncssh.Error as e:
            raise SSHError(str(e)) from e
        return r.stdout or ""

    async def process(self, cmd: str, **kw):
        c = await self.conn()
        try:
            return await c.create_process(cmd, **kw)
        except asyncssh.Error as e:
            raise SSHError(str(e)) from e


class RemoteClaude:
    """Proceso de `claude -p` en el host, con el interfaz que espera ClaudeManager."""

    def __init__(self, ssh: SSH, proc):
        self.ssh, self.proc = ssh, proc
        self.pid: int | None = None
        self._err = asyncio.create_task(proc.stderr.read())

    @classmethod
    async def spawn(cls, ssh: SSH, cmd: str) -> "RemoteClaude":
        return cls(ssh, await ssh.process(cmd))

    async def lines(self):
        async for line in self.proc.stdout:
            if self.pid is None and line.startswith("PID:"):
                self.pid = int(line[4:].strip())
                continue
            yield line

    async def stop(self) -> None:
        if self.pid:
            await self.ssh.run(f"kill -INT {self.pid} 2>/dev/null; sleep 3; kill -TERM {self.pid} 2>/dev/null; true")
        else:
            self.proc.close()

    async def wait(self):
        r = await self.proc.wait(check=False)
        return r.exit_status, await self._err
