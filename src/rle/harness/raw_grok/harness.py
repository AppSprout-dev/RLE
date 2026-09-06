"""Drive the stock ``grok`` binary through the HeadlessCliHarness turn protocol.

Minimal by design: ``grok -p`` once per tick, project-local MCP stanza so
the binary can see the in-process RLE server, JSON stdout for token counts.
No isolated home, no compatibility-MCP lockdown, no healthcheck, no prompt
addenda beyond ``TURN_RULES``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from rle.harness import HarnessStepError
from rle.harness.cli_base import HeadlessCliHarness, TurnResult
from rle.harness.raw_grok.binary import binary_version, resolve_binary
from rle.harness.raw_grok.options import RawGrokOptions

logger = logging.getLogger(__name__)


def project_mcp_toml(mcp_url: str) -> str:
    """RLE MCP stanza only — no compat flags, no extra servers."""
    return (
        "[mcp_servers.rle]\n"
        f'url = "{mcp_url}"\n'
        "startup_timeout_sec = 30\n"
    )


def build_command(
    binary: str, prompt: str, *, model: str | None, workdir: str,
) -> list[str]:
    cmd = [
        binary, "-p", prompt,
        "--output-format", "json",
        "--yolo",
        "--cwd", workdir,
    ]
    if model:
        cmd += ["-m", model]
    return cmd


def parse_json_output(stdout: str) -> TurnResult:
    """Turn a headless JSON object into a TurnResult (tolerant of log noise)."""
    data: Any = None
    text = stdout.strip()
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if data is None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return TurnResult(text=text)
    if not isinstance(data, dict):
        return TurnResult(text=text)
    if data.get("type") == "error":
        raise HarnessStepError(f"grok reported an error: {data.get('message', data)}")
    usage = data.get("usage") or {}
    cached = int(usage.get("cache_read_input_tokens", 0) or 0) + int(
        usage.get("cache_creation_input_tokens", 0) or 0,
    )
    return TurnResult(
        text=str(data.get("text", "")),
        prompt_tokens=int(usage.get("input_tokens", 0) or 0) + cached,
        completion_tokens=int(usage.get("output_tokens", 0) or 0),
        reasoning_tokens=int(usage.get("reasoning_tokens", 0) or 0),
        extras={
            "session_id": str(data.get("sessionId", "")),
            "stop_reason": data.get("stopReason"),
        },
    )


class RawGrokHarness(HeadlessCliHarness):
    name: ClassVar[str] = "raw-grok"

    def __init__(self, options: RawGrokOptions) -> None:
        super().__init__(options)
        self.opts = options
        self._binary: str | None = None
        self._workdir: str | None = None
        self._proc: asyncio.subprocess.Process | None = None

    async def start_agent(self, mcp_url: str) -> None:
        binary = resolve_binary(self.opts.binary)
        if binary is None:
            raise HarnessStepError(f"stock grok binary {self.opts.binary!r} not found on PATH")
        self._binary = binary
        self._workdir = tempfile.mkdtemp(prefix="rle-raw-grok-")
        cfg_dir = Path(self._workdir) / ".grok"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.toml").write_text(project_mcp_toml(mcp_url), encoding="utf-8")
        logger.info("raw-grok cwd=%s MCP %s", self._workdir, mcp_url)

    async def send_turn(self, prompt: str) -> TurnResult:
        assert self._binary is not None and self._workdir is not None
        cmd = build_command(
            self._binary, prompt,
            model=self.opts.model or self.ctx.config.model,
            workdir=self._workdir,
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=self._workdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        try:
            stdout_b, stderr_b = await proc.communicate()
        except asyncio.CancelledError:
            await self._terminate_process(proc)
            raise
        finally:
            if self._proc is proc:
                self._proc = None
        returncode = proc.returncode or 0
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        if stderr.strip():
            logger.debug("grok stderr (tail): %s", stderr.strip()[-1500:])
        if returncode != 0:
            raise HarnessStepError(
                f"grok exited {returncode}: {(stderr or stdout).strip()[-800:]}",
            )
        return parse_json_output(stdout)

    async def _terminate_process(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass

    async def abort_turn(self) -> None:
        proc = self._proc
        if proc is not None:
            await self._terminate_process(proc)
            if self._proc is proc:
                self._proc = None

    async def stop_agent(self) -> None:
        await self.abort_turn()
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    def agent_versions(self) -> dict[str, str]:
        return {"grok": binary_version(self.opts.binary), "kind": "model-baseline"}
