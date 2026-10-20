"""Verifiable source identity for the installed AI Hedge Fund upstream.

The upstream distribution is named ``aihf``. An editable install's version
number does not pin the code, so editable installs must also resolve to a
clean git commit. Nothing here is guessed: if the revision cannot be proven,
resolution fails.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from importlib import metadata as package_metadata
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

DISTRIBUTIONS = ("aihf",)
_SHA = re.compile(r"^[0-9a-f]{40}$")

GitRunner = Callable[..., str]


def _run_git(path: str, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True,
        timeout=10, check=False,
    )
    if completed.returncode != 0:
        raise OSError("git command failed")
    return completed.stdout.strip()


def _local_path(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise ValueError("editable upstream install is not a local directory")
    return url2pathname(parsed.path)


def resolve_hedge_fund_identity(
    *,
    distribution: Callable[[str], Any] = package_metadata.distribution,
    run_git: GitRunner = _run_git,
) -> dict[str, Any]:
    dist = None
    name = ""
    for name in DISTRIBUTIONS:
        try:
            dist = distribution(name)
            break
        except package_metadata.PackageNotFoundError:
            continue
    if dist is None:
        raise ValueError("AI Hedge Fund upstream version is unavailable")
    version = str(dist.version or "").strip()
    if not version:
        raise ValueError("AI Hedge Fund upstream version is unavailable")

    raw = dist.read_text("direct_url.json")
    if raw is None:
        return {"distribution": name, "version": version, "git_commit": None,
                "source": "PACKAGE_INDEX_RELEASE", "identity": f"{name}=={version}"}
    direct = json.loads(raw)
    vcs = direct.get("vcs_info") or {}
    if vcs.get("vcs") == "git" and _SHA.match(str(vcs.get("commit_id", ""))):
        commit, source = str(vcs["commit_id"]), "VCS_DIRECT_URL"
    elif (direct.get("dir_info") or {}).get("editable") is True:
        path = _local_path(str(direct.get("url", "")))
        try:
            commit = run_git(path, "rev-parse", "HEAD") or ""
            dirty = run_git(path, "status", "--porcelain", "--untracked-files=no")
        except OSError as exc:
            raise ValueError("upstream git commit cannot be verified") from exc
        if not _SHA.match(commit):
            raise ValueError("upstream git commit cannot be verified")
        if dirty:
            raise ValueError("upstream checkout has uncommitted tracked changes")
        source = "EDITABLE_GIT_CHECKOUT"
    else:
        raise ValueError("upstream install has no verifiable source revision")
    return {"distribution": name, "version": version, "git_commit": commit,
            "source": source, "identity": f"{name}=={version}+git.{commit}"}


def main() -> int:
    try:
        identity = resolve_hedge_fund_identity()
    except ValueError as exc:
        print(json.dumps({"status": "UNVERIFIED", "reason": str(exc)}))
        return 2
    print(json.dumps({"status": "VERIFIED", **identity}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
