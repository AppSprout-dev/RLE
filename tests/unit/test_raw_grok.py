"""raw-grok model-baseline plugin, options, and prompt contract."""

from __future__ import annotations

import json
import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rle.harness.brief import ScenarioBrief
from rle.harness.raw_grok.plugin import PLUGIN, RAW_GROK_DESCRIPTION
from rle.harness.registry import create_harness, get_plugin, harness_names, validate_options
from tests.unit.test_harness_registry import _ctx

mcp_available = find_spec("mcp") is not None
requires_mcp = pytest.mark.skipif(not mcp_available, reason="mcp extra not installed")


class TestRawGrokPlugin:
    def test_registers(self) -> None:
        assert "raw-grok" in harness_names()
        plugin = get_plugin("raw-grok")
        assert plugin.name == "raw-grok"
        assert plugin is PLUGIN
        assert "MODEL BASELINE" in plugin.description
        assert "MODEL BASELINE" in RAW_GROK_DESCRIPTION

    @requires_mcp
    def test_options_schema_defaults(self) -> None:
        plugin = get_plugin("raw-grok")
        opts = validate_options(plugin, {})
        assert opts.binary == "grok"  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 180.0  # type: ignore[attr-defined]
        assert opts.extra_instructions == ""  # type: ignore[attr-defined]
        assert opts.mcp_advertise_url is None  # type: ignore[attr-defined]
        assert opts.mcp_container_reachable is None  # type: ignore[attr-defined]

    @requires_mcp
    def test_options_accept_binary_timeout_and_advertise_url(self) -> None:
        plugin = get_plugin("raw-grok")
        opts = validate_options(plugin, {
            "binary": "/opt/grok",
            "turn_timeout_s": 300,
            "mcp_advertise_url": "http://host.docker.internal:8766/mcp",
            "mcp_container_reachable": True,
        })
        assert opts.binary == "/opt/grok"  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 300.0  # type: ignore[attr-defined]
        assert opts.mcp_advertise_url == "http://host.docker.internal:8766/mcp"  # type: ignore[attr-defined]
        assert opts.mcp_container_reachable is True  # type: ignore[attr-defined]

    @requires_mcp
    def test_prompt_is_turn_rules_only(self) -> None:
        from rle.harness.cli_base import TURN_RULES
        from rle.harness.raw_grok.harness import RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        harness = RawGrokHarness(RawGrokOptions())
        brief = ScenarioBrief(
            tick=1, day=0, macro_time=0.0,
            goals={}, state={"colony": {"tick": 1}},
            map_summary="SHELTER SITE (1,1)-(7,7)",
            recent_events=[], actions=[],
        )
        prompt = harness.render_prompt(brief)
        assert TURN_RULES in prompt
        assert "get_brief" in prompt
        assert "end_turn" in prompt
        assert harness.options.extra_instructions == ""
        # Model baseline: no namespaced-tool addendum, no extra instructions.
        assert "rle__get_brief" not in prompt
        assert "namespaced" not in prompt.lower()
        assert "the only mcp server" not in prompt.lower()

    @requires_mcp
    def test_smoke_builds_scripted_standin(self) -> None:
        harness = create_harness("raw-grok", _ctx(), smoke=True)
        assert harness.name == "raw-grok"

    @requires_mcp
    def test_mcp_toml_is_rle_stanza_only(self) -> None:
        from rle.harness.raw_grok.harness import project_mcp_toml

        text = project_mcp_toml("http://127.0.0.1:8766/mcp")
        assert "[mcp_servers.rle]" in text
        assert "http://127.0.0.1:8766/mcp" in text
        assert "compat" not in text


def _ok_json(text: str = "ok") -> bytes:
    return json.dumps({
        "text": text,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }).encode()


def _mock_proc(stdout: bytes, *, returncode: int = 0, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode

    async def _communicate() -> tuple[bytes, bytes]:
        return stdout, stderr

    proc.communicate = _communicate
    return proc


@requires_mcp
class TestWindowsArgvJson:
    def test_detects_cmd_and_bat_paths(self) -> None:
        from rle.harness.raw_grok.harness import is_windows_script_binary

        assert is_windows_script_binary(r"C:\tools\grok-docker.cmd")
        assert is_windows_script_binary(r"C:\tools\GROK-DOCKER.CMD")
        assert is_windows_script_binary("/tmp/wrapper.bat")
        assert is_windows_script_binary("grok-docker.cmd")
        assert not is_windows_script_binary("/usr/bin/grok")
        assert not is_windows_script_binary(r"C:\tools\grok.exe")
        assert not is_windows_script_binary("grok-docker.sh")
        assert not is_windows_script_binary("grok-docker.ps1")

    def test_prepare_writes_sidecar_and_strips_cli_args(self, tmp_path: Path) -> None:
        from rle.harness.raw_grok.harness import (
            ARGV_JSON_ENV,
            prepare_windows_script_invocation,
        )

        dest = tmp_path / "argv.json"
        env: dict[str, str] = {}
        prompt = 'RLE turn — tick 0: colonist "Lee"\n' + ("priority " * 50)
        cmd = [
            r"C:\repo\docker\grok-docker.cmd", "-p", prompt,
            "--output-format", "json", "--yolo", "--cwd", r"C:\tmp\work",
        ]
        invoke, sidecar = prepare_windows_script_invocation(cmd, env, dest=dest)
        assert invoke == [r"C:\repo\docker\grok-docker.cmd"]
        assert sidecar == dest
        assert env[ARGV_JSON_ENV] == str(dest)
        loaded = json.loads(dest.read_text(encoding="utf-8"))
        assert loaded[0] == "-p"
        assert loaded[1] == prompt
        assert "--output-format" in loaded

    def test_prepare_leaves_host_grok_argv_alone(self, tmp_path: Path) -> None:
        from rle.harness.raw_grok.harness import (
            ARGV_JSON_ENV,
            prepare_windows_script_invocation,
        )

        env: dict[str, str] = {}
        cmd = ["/usr/bin/grok", "-p", "hello", "--output-format", "json"]
        invoke, sidecar = prepare_windows_script_invocation(cmd, env, dest=tmp_path / "x.json")
        assert invoke == cmd
        assert sidecar is None
        assert ARGV_JSON_ENV not in env
        assert not (tmp_path / "x.json").exists()

    async def test_send_turn_cmd_writes_env_and_cleans_sidecar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from rle.harness.raw_grok.harness import ARGV_JSON_ENV, RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        binary = str(tmp_path / "grok-docker.cmd")
        Path(binary).write_text("@echo off\r\n", encoding="utf-8")
        workdir = tmp_path / "work"
        workdir.mkdir()
        stale = tmp_path / "stale-argv.json"
        stale.write_text("[]", encoding="utf-8")
        monkeypatch.setenv(ARGV_JSON_ENV, str(stale))

        captured: dict[str, Any] = {}
        during: dict[str, Any] = {}
        proc = _mock_proc(_ok_json())

        async def _exec(*args: str, **kwargs: Any) -> MagicMock:
            captured["args"] = args
            captured["kwargs"] = kwargs
            env = kwargs["env"]
            sidecar = Path(env[ARGV_JSON_ENV])
            during["sidecar"] = sidecar
            during["exists"] = sidecar.exists()
            during["argv"] = json.loads(sidecar.read_text(encoding="utf-8"))
            return proc

        harness = RawGrokHarness(RawGrokOptions(binary=binary, model="grok-4.6"))
        harness._binary = binary
        harness._workdir = str(workdir)
        huge = 'RLE turn — tick 0: colonist "Lee" needs a bed\n' + ("priority " * 200)
        with patch(
            "rle.harness.raw_grok.harness.asyncio.create_subprocess_exec",
            _exec,
        ):
            turn = await harness.send_turn(huge)

        assert turn.text == "ok"
        assert turn.prompt_tokens == 3
        assert captured["args"] == (binary,)
        assert captured["kwargs"]["cwd"] == str(workdir)
        env = captured["kwargs"]["env"]
        assert env[ARGV_JSON_ENV] != str(stale)
        assert during["exists"] is True
        assert during["argv"][0] == "-p"
        assert during["argv"][1] == huge
        assert during["argv"][during["argv"].index("-m") + 1] == "grok-4.6"
        assert "--output-format" in during["argv"]
        assert "--yolo" in during["argv"]
        assert during["argv"][during["argv"].index("--cwd") + 1] == str(workdir)
        assert not Path(during["sidecar"]).exists()
        assert ARGV_JSON_ENV in os.environ

    async def test_send_turn_bat_uses_argv_json(self, tmp_path: Path) -> None:
        from rle.harness.raw_grok.harness import ARGV_JSON_ENV, RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        binary = str(tmp_path / "grok-docker.bat")
        captured: dict[str, Any] = {}
        proc = _mock_proc(_ok_json("bat"))

        async def _exec(*args: str, **kwargs: Any) -> MagicMock:
            captured["args"] = args
            captured["env"] = kwargs["env"]
            captured["argv"] = json.loads(
                Path(kwargs["env"][ARGV_JSON_ENV]).read_text(encoding="utf-8"),
            )
            return proc

        harness = RawGrokHarness(RawGrokOptions(binary=binary, model="grok-4.6"))
        harness._binary = binary
        harness._workdir = str(tmp_path)
        with patch(
            "rle.harness.raw_grok.harness.asyncio.create_subprocess_exec",
            _exec,
        ):
            turn = await harness.send_turn("go")

        assert turn.text == "bat"
        assert captured["args"] == (binary,)
        assert captured["argv"][:2] == ["-p", "go"]

    async def test_send_turn_host_grok_passes_argv_without_sidecar(
        self, tmp_path: Path,
    ) -> None:
        from rle.harness.raw_grok.harness import ARGV_JSON_ENV, RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        binary = "/usr/bin/grok"
        captured: dict[str, Any] = {}
        proc = _mock_proc(_ok_json())

        async def _exec(*args: str, **kwargs: Any) -> MagicMock:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return proc

        harness = RawGrokHarness(RawGrokOptions(binary=binary, model="grok-4.6"))
        harness._binary = binary
        harness._workdir = str(tmp_path)
        with patch(
            "rle.harness.raw_grok.harness.asyncio.create_subprocess_exec",
            _exec,
        ):
            turn = await harness.send_turn("host prompt")

        assert turn.text == "ok"
        assert captured["args"][0] == binary
        assert captured["args"][1:3] == ("-p", "host prompt")
        assert captured["kwargs"]["env"] is None
        assert ARGV_JSON_ENV not in captured["kwargs"]

    async def test_sidecar_cleaned_on_nonzero_exit(self, tmp_path: Path) -> None:
        from rle.harness import HarnessStepError
        from rle.harness.raw_grok.harness import ARGV_JSON_ENV, RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        binary = str(tmp_path / "grok-docker.cmd")
        sidecar_path: dict[str, Path] = {}
        proc = _mock_proc(b"", returncode=1, stderr=b"auth failed")

        async def _exec(*args: str, **kwargs: Any) -> MagicMock:
            sidecar_path["path"] = Path(kwargs["env"][ARGV_JSON_ENV])
            assert sidecar_path["path"].exists()
            return proc

        harness = RawGrokHarness(RawGrokOptions(binary=binary, model="grok-4.6"))
        harness._binary = binary
        harness._workdir = str(tmp_path)
        with patch(
            "rle.harness.raw_grok.harness.asyncio.create_subprocess_exec",
            _exec,
        ), pytest.raises(HarnessStepError, match="auth failed"):
            await harness.send_turn("x")
        assert not sidecar_path["path"].exists()
