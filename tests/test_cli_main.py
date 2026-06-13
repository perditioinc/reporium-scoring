"""Tests for reporium_scoring.cli.main entry point.

Covers process-level behavior that the existing test_cli.py does not: non-zero
exit on missing args, malformed 'owner/repo' argument handling, and the
no-network contract (score_repo is patched, load_config is patched, so these
tests never touch GitHub). main() lazily imports load_config and score_repo
from their source modules inside the function body, so the patches target
reporium_scoring.config.load_config and reporium_scoring.scorer.score_repo.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from reporium_scoring.cli import main
from reporium_scoring.config import Config
from reporium_scoring.models import RepoScore


def _fake_config() -> Config:
    """A Config with a dummy token so main() never reads the environment."""
    return Config(gh_token="dummy-token", concurrency=10)


def _ok_score(owner: str, repo: str) -> RepoScore:
    """A minimal successful RepoScore for the given coordinates."""
    return RepoScore(owner=owner, repo=repo, total=50, grade="D")


# -- Exit codes --------------------------------------------------------------


def test_main_no_args_exits_nonzero(capsys):
    """Invoking with no repo args prints usage and exits with code 1."""
    with patch("sys.argv", ["repo-score"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


def test_main_with_valid_arg_exits_zero(capsys):
    """A well-formed arg runs to completion without raising SystemExit.

    score_repo is patched to avoid any network call; success is 'main returns
    normally' (no SystemExit) and the repo coordinates reach the output.
    """

    async def fake_score(owner, repo, token):
        assert token == "dummy-token"
        return _ok_score(owner, repo)

    with patch("sys.argv", ["repo-score", "octocat/hello"]), patch(
        "reporium_scoring.config.load_config", _fake_config
    ), patch("reporium_scoring.scorer.score_repo", fake_score):
        main()  # must NOT raise SystemExit
    out = capsys.readouterr().out
    assert "octocat/hello" in out
    assert "50/100" in out


# -- Malformed input ---------------------------------------------------------


def test_main_malformed_arg_reports_and_skips(capsys):
    """An arg without '/' is reported as invalid and never scored."""
    calls: list[tuple[str, str]] = []

    async def fake_score(owner, repo, token):
        calls.append((owner, repo))
        return _ok_score(owner, repo)

    with patch("sys.argv", ["repo-score", "not-a-repo"]), patch(
        "reporium_scoring.config.load_config", _fake_config
    ), patch("reporium_scoring.scorer.score_repo", fake_score):
        main()
    out = capsys.readouterr().out
    assert "Invalid format" in out
    assert "not-a-repo" in out
    # Malformed arg must be skipped, not passed to the scorer.
    assert calls == []


def test_main_mixed_args_scores_valid_only(capsys):
    """With one good and one malformed arg, only the good one is scored."""
    calls: list[tuple[str, str]] = []

    async def fake_score(owner, repo, token):
        calls.append((owner, repo))
        return _ok_score(owner, repo)

    with patch("sys.argv", ["repo-score", "bad", "good-owner/good-repo"]), patch(
        "reporium_scoring.config.load_config", _fake_config
    ), patch("reporium_scoring.scorer.score_repo", fake_score):
        main()
    out = capsys.readouterr().out
    assert "Invalid format" in out
    assert calls == [("good-owner", "good-repo")]
    assert "good-owner/good-repo" in out


def test_main_owner_repo_split_is_first_slash_only(capsys):
    """'a/b/c' splits into owner='a', repo='b/c' (split on first slash only).

    Locks the split semantics so a nested-path arg is not silently rejected and
    the remainder is preserved verbatim as the repo segment.
    """
    calls: list[tuple[str, str]] = []

    async def fake_score(owner, repo, token):
        calls.append((owner, repo))
        return _ok_score(owner, repo)

    with patch("sys.argv", ["repo-score", "a/b/c"]), patch(
        "reporium_scoring.config.load_config", _fake_config
    ), patch("reporium_scoring.scorer.score_repo", fake_score):
        main()
    assert calls == [("a", "b/c")]


# -- Config failure surfaces ------------------------------------------------


def test_main_missing_token_raises_value_error():
    """When GH_TOKEN is absent, load_config raises and main propagates it.

    main() calls load_config() before scoring anything; a misconfigured
    environment must fail fast rather than attempting an unauthenticated scan.
    """

    def boom() -> Config:
        raise ValueError("GH_TOKEN environment variable is required")

    with patch("sys.argv", ["repo-score", "octocat/hello"]), patch(
        "reporium_scoring.config.load_config", boom
    ):
        with pytest.raises(ValueError, match="GH_TOKEN"):
            main()
