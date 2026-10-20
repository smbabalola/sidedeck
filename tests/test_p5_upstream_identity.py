import json
from importlib import metadata as package_metadata

import pytest

from sidedeck.bridges.upstream_identity import resolve_hedge_fund_identity

SHA = "ec025370c66cf71d3ea2f2d8f463b5934c1c48af"


class FakeDist:
    def __init__(self, version: str, direct_url: dict | None):
        self.version = version
        self._direct_url = direct_url

    def read_text(self, name: str):
        if name == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


def _lookup(dists: dict):
    def distribution(name: str):
        if name in dists:
            return dists[name]
        raise package_metadata.PackageNotFoundError(name)
    return distribution


def _git(head: str = SHA, dirty: str = ""):
    calls = []

    def run(path, *args):
        calls.append((path, args))
        if args[:2] == ("rev-parse", "HEAD"):
            return head
        if args[0] == "status":
            return dirty
        raise AssertionError(args)
    run.calls = calls
    return run


EDITABLE = {"dir_info": {"editable": True},
            "url": "file:///C:/Users/x/ai-hedge-fund"}


def test_editable_install_is_pinned_to_clean_git_commit():
    git = _git()
    identity = resolve_hedge_fund_identity(
        distribution=_lookup({"aihf": FakeDist("2.5.0", EDITABLE)}), run_git=git,
    )
    assert identity["distribution"] == "aihf"
    assert identity["version"] == "2.5.0"
    assert identity["git_commit"] == SHA
    assert identity["source"] == "EDITABLE_GIT_CHECKOUT"
    assert identity["identity"] == f"aihf==2.5.0+git.{SHA}"
    assert all(call[0].endswith("ai-hedge-fund") for call in git.calls)


def test_modified_upstream_checkout_is_refused():
    with pytest.raises(ValueError, match="uncommitted"):
        resolve_hedge_fund_identity(
            distribution=_lookup({"aihf": FakeDist("2.5.0", EDITABLE)}),
            run_git=_git(dirty=" M hedge_fund/signals/buffett.py"),
        )


@pytest.mark.parametrize("head", ["", "not-a-sha", SHA[:12], None])
def test_editable_install_without_verifiable_commit_fails_closed(head):
    def run(path, *args):
        if head is None:
            raise OSError("git unavailable")
        return head if args[0] == "rev-parse" else ""
    with pytest.raises(ValueError, match="commit"):
        resolve_hedge_fund_identity(
            distribution=_lookup({"aihf": FakeDist("2.5.0", EDITABLE)}), run_git=run,
        )


def test_vcs_wheel_install_uses_recorded_commit_without_git():
    direct = {"url": "https://github.com/virattt/ai-hedge-fund.git",
              "vcs_info": {"vcs": "git", "commit_id": SHA}}

    def no_git(*_args):
        raise AssertionError("git must not be called")
    identity = resolve_hedge_fund_identity(
        distribution=_lookup({"aihf": FakeDist("2.5.0", direct)}), run_git=no_git,
    )
    assert identity["source"] == "VCS_DIRECT_URL"
    assert identity["identity"] == f"aihf==2.5.0+git.{SHA}"


def test_index_release_without_direct_url_uses_version_only():
    identity = resolve_hedge_fund_identity(
        distribution=_lookup({"aihf": FakeDist("2.5.0", None)}), run_git=_git(),
    )
    assert identity["source"] == "PACKAGE_INDEX_RELEASE"
    assert identity["git_commit"] is None
    assert identity["identity"] == "aihf==2.5.0"


def test_missing_distribution_is_not_invented():
    with pytest.raises(ValueError, match="unavailable"):
        resolve_hedge_fund_identity(distribution=_lookup({}), run_git=_git())


def test_unrecorded_local_directory_install_fails_closed():
    direct = {"dir_info": {}, "url": "file:///C:/Users/x/ai-hedge-fund"}
    with pytest.raises(ValueError, match="revision"):
        resolve_hedge_fund_identity(
            distribution=_lookup({"aihf": FakeDist("2.5.0", direct)}), run_git=_git(),
        )
