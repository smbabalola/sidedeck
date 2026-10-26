"""Run one pinned upstream script in an offline, network-blocked, credential-free sandbox.

Controls (all fail closed):

* the script must verify against its pinned SHA-256 (``manifest.resolve``);
* only allowlisted subcommands; scripts that can fetch data always get ``--offline``;
* the child runs ``python -I`` (no user site, no PYTHONPATH) through a bootstrap that
  replaces socket connects, DNS lookups and subprocess creation with errors before the
  script loads, so even a code path that ignores ``--offline`` cannot reach the network;
* the environment is rebuilt from a short allowlist: no broker, provider or SideDeck
  credential variable can reach the child, whatever the parent holds;
* the working directory is a fresh temporary folder; every path argument must stay inside it;
* bounded runtime and output; stdout must be JSON when ``--json`` is requested.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from sidedeck.modules.day_trader.manifest import SKILLS, Verification, resolve

TIMEOUT_SECONDS = 180
MAX_OUTPUT_BYTES = 5_000_000
ENV_ALLOWLIST = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC")
BLOCKED = "SIDEDECK_SANDBOX_BLOCKED"
BOOTSTRAP = r'''
import runpy, socket, subprocess, sys
def _no_network(*a, **k):
    raise OSError("SIDEDECK_SANDBOX_BLOCKED: network access is not allowed")
def _no_process(*a, **k):
    raise OSError("SIDEDECK_SANDBOX_BLOCKED: subprocesses are not allowed")
socket.socket.connect = _no_network
socket.socket.connect_ex = _no_network
socket.create_connection = _no_network
socket.getaddrinfo = _no_network
subprocess.Popen.__init__ = _no_process
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
'''


class SandboxRefused(PermissionError):
    """The requested run is outside the module's safety envelope; nothing was executed."""


@dataclass(frozen=True)
class SkillRun:
    skill: str
    command: str | None
    argv: tuple[str, ...]
    status: str                     # OK | FAILED | MALFORMED | TIMEOUT
    returncode: int | None
    output: Any
    stdout_sha256: str
    stderr: str
    seconds: float
    files: dict[str, str] = field(default_factory=dict)   # written files -> sha256


def _env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                "TZ": "America/New_York"})
    return env


class Workspace:
    """A temporary folder holding the skill's ``trader/`` state for one module run."""

    def __init__(self, root: Path | None = None) -> None:
        self._tmp = None if root else tempfile.TemporaryDirectory(prefix="sidedeck-daytrader-")
        self.root = (root or Path(self._tmp.name)).resolve()   # type: ignore[union-attr]
        (self.root / "trader" / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "inputs").mkdir(exist_ok=True)

    def add_input(self, source: Path, name: str | None = None) -> str:
        """Copy a data file or folder in; returns the relative path to pass to the skill."""
        target = self.root / "inputs" / (name or source.name)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        return str(target.relative_to(self.root)).replace("\\", "/")

    def write_json(self, rel: str, payload: Any) -> str:
        target = self._inside(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return rel

    def read_json(self, rel: str) -> Any:
        return json.loads(self._inside(rel).read_text(encoding="utf-8"))

    def _inside(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if self.root not in target.parents and target != self.root:
            raise SandboxRefused("path escapes the module workspace")
        return target

    def snapshot(self) -> dict[str, str]:
        return {str(p.relative_to(self.root)).replace("\\", "/"):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*")) if p.is_file()
                and "inputs" not in p.relative_to(self.root).parts}

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()


def _check_args(spec_name: str, command: str | None, args: Sequence[str],
                workspace: Workspace) -> None:
    spec = SKILLS.get(spec_name)
    if spec is None:
        raise SandboxRefused(f"unknown skill {spec_name}")
    if spec.allowed is None:
        if command is not None:
            raise SandboxRefused(f"{spec_name} takes no subcommand")
    elif command not in spec.allowed:
        raise SandboxRefused(f"{spec_name} {command!r} is not allowed in SideDeck")
    if spec.needs_offline and "--offline" not in args:
        raise SandboxRefused(f"{spec_name} must run with --offline (no network data source "
                             "is authorized for this module)")
    for arg in args:
        if len(arg) > 2 and (arg[1:3] == ":\\" or arg[1:3] == ":/" or arg.startswith(("/",
                                                                                       "\\"))):
            raise SandboxRefused("absolute paths are not allowed; copy inputs into the "
                                 "workspace")
        if ".." in arg.replace("\\", "/").split("/"):
            raise SandboxRefused("parent-directory paths are not allowed")


def run_skill(skill: str, command: str | None, args: Sequence[str], workspace: Workspace, *,
              verification: Verification | None = None, json_output: bool = True,
              timeout: float = TIMEOUT_SECONDS) -> SkillRun:
    found = verification or resolve()
    if found.status != "VERIFIED" or found.root is None:
        raise SandboxRefused(f"upstream skill is not verified ({found.status})")
    _check_args(skill, command, args, workspace)
    script = found.root / SKILLS[skill].script
    bootstrap = workspace.root / ".sidedeck_bootstrap.py"
    bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
    argv = ([command] if command else []) + list(args) + (["--json"] if json_output and
                                                          "--json" not in args else [])
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, "-I", str(bootstrap), str(script), *argv],
                              cwd=workspace.root, env=_env(), capture_output=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return SkillRun(skill, command, tuple(argv), "TIMEOUT", None, None, "", "timeout",
                        time.monotonic() - started)
    finally:
        bootstrap.unlink(missing_ok=True)
    seconds = time.monotonic() - started
    stdout = proc.stdout[:MAX_OUTPUT_BYTES + 1]
    stderr = proc.stderr.decode("utf-8", "replace")[-2000:]
    digest = hashlib.sha256(stdout).hexdigest()
    if len(stdout) > MAX_OUTPUT_BYTES:
        return SkillRun(skill, command, tuple(argv), "MALFORMED", proc.returncode, None, digest,
                        "output too large", seconds)
    output: Any = None
    status = "OK" if proc.returncode == 0 else "FAILED"
    if json_output:
        try:
            output = json.loads(stdout.decode("utf-8")) if stdout.strip() else None
        except (UnicodeDecodeError, ValueError):
            status = "MALFORMED" if status == "OK" else status
    else:
        output = stdout.decode("utf-8", "replace")[:20000]
    if BLOCKED in stderr:
        status = "FAILED"
    return SkillRun(skill, command, tuple(argv), status, proc.returncode, output, digest,
                    stderr, seconds, workspace.snapshot())


def run_raw(script_body: str, workspace: Workspace) -> subprocess.CompletedProcess[bytes]:
    """Test hook: run arbitrary code through the same bootstrap (proves the block holds)."""
    probe = workspace.root / "probe.py"
    probe.write_text(script_body, encoding="utf-8")
    bootstrap = workspace.root / ".sidedeck_bootstrap.py"
    bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(bootstrap), str(probe)],
                          cwd=workspace.root, env=_env(), capture_output=True, timeout=60,
                          check=False)


def environment_preview(parent: Mapping[str, str] | None = None) -> list[str]:
    """Names (never values) the child would receive."""
    return sorted(_env())
