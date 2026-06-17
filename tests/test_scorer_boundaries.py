"""Boundary tests locking the 0-100 scoring envelope for score_repo.

These assert the EXACT integer total produced for hand-built repo fixtures so
that any future change to point weights or pass logic surfaces here. The scoring
lib is deterministic and fully mockable, so totals are computed by hand from the
per-check point tables in reporium_scoring/checks/*.py.

Point tables (max per category = 25):
  readme:    exists 5, >500 5, >2000 5, code-blocks 5, badges 5
  activity:  committed_30d 10 / committed_90d 7 / committed_365d 3 (mutually
             exclusive recency tiers), commits_gt_10 5, has_releases 5
  community: has_license 10, has_contributing 5, issues_enabled 5,
             changelog_or_releases 5
  ci:        has_workflows 10, has_tests_dir 10, has_build_config 5
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import respx

from reporium_scoring.client import GITHUB_API
from reporium_scoring.scorer import score_repo

OWNER = "test-owner"
REPO = "test-repo"
TOKEN = "test-token"


def _readme(text: str) -> dict:
    """Build a GitHub /readme JSON response for the given text."""
    return {"content": base64.b64encode(text.encode()).decode() + "\n", "encoding": "base64"}


def _iso_days_ago(days: int) -> str:
    """Return an ISO-8601 UTC timestamp `days` days in the past."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_repo(
    *,
    readme: httpx.Response,
    pushed_at: str | None,
    has_issues: bool,
    commits: list,
    releases: list,
    has_license: bool,
    has_contributing: bool,
    has_changelog: bool,
    has_workflows: bool,
    has_tests: bool,
    has_pyproject: bool,
    has_package_json: bool,
) -> None:
    """Register respx mocks for every endpoint score_repo touches.

    A 404 (resource absent) is the GitHub signal the checks treat as a failed
    condition; a 200 with a body is the present signal. The repo object always
    returns 200 because score_repo derives recency and issues from it.
    """
    repo_json: dict = {"has_issues": has_issues}
    if pushed_at is not None:
        repo_json["pushed_at"] = pushed_at

    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/readme").mock(return_value=readme)
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}").mock(
        return_value=httpx.Response(200, json=repo_json)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/commits", params={"per_page": "11"}).mock(
        return_value=httpx.Response(200, json=commits)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases", params={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=releases)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/license").mock(
        return_value=httpx.Response(200, json={"license": {"key": "mit"}})
        if has_license
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/CONTRIBUTING.md").mock(
        return_value=httpx.Response(200, json={"name": "CONTRIBUTING.md"})
        if has_contributing
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/CHANGELOG.md").mock(
        return_value=httpx.Response(200, json={"name": "CHANGELOG.md"})
        if has_changelog
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/.github/workflows").mock(
        return_value=httpx.Response(200, json=[{"name": "test.yml"}])
        if has_workflows
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/tests").mock(
        return_value=httpx.Response(200, json=[{"name": "test_foo.py"}])
        if has_tests
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/test").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/pyproject.toml").mock(
        return_value=httpx.Response(200, json={"name": "pyproject.toml"})
        if has_pyproject
        else httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/package.json").mock(
        return_value=httpx.Response(200, json={"name": "package.json"})
        if has_package_json
        else httpx.Response(404)
    )


# -- Lower bound: everything absent ------------------------------------------


@respx.mock
async def test_total_floor_is_exactly_zero():
    """A repo with no README, no recency, no commits, no community, no CI = 0.

    pushed_at is far older than 365d so all three recency tiers fail; this is
    also the archived/abandoned-repo case (an archived repo stops receiving
    pushes, so its pushed_at ages out of every recency window).
    """
    _mock_repo(
        readme=httpx.Response(404),
        pushed_at="2015-01-01T00:00:00Z",
        has_issues=False,
        commits=[],
        releases=[],
        has_license=False,
        has_contributing=False,
        has_changelog=False,
        has_workflows=False,
        has_tests=False,
        has_pyproject=False,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    assert score.total == 0
    assert score.grade == "F"
    # Every per-category subtotal is floored at 0, never negative.
    assert score.readme_score == 0
    assert score.activity_score == 0
    assert score.community_score == 0
    assert score.ci_score == 0


# -- Upper bound: everything present -----------------------------------------


@respx.mock
async def test_total_ceiling_is_95_not_100():
    """Max achievable total is 95: recency tiers are mutually exclusive.

    committed_30d (10) excludes committed_90d (7) and committed_365d (3), so a
    perfect repo earns 10 of the nominal 20 recency points. The advertised
    0-100 range therefore caps at 95, never 100. This is the load-bearing
    invariant: if someone makes the tiers additive the ceiling jumps and this
    test fails loudly.
    """
    long_readme = (
        "# Title\n\n" + "A" * 2100 + "\n```python\nprint('x')\n```\n" + "![b](https://img/x.svg)"
    )
    _mock_repo(
        readme=httpx.Response(200, json=_readme(long_readme)),
        pushed_at=_iso_days_ago(1),
        has_issues=True,
        commits=[{}] * 11,
        releases=[{"id": 1}],
        has_license=True,
        has_contributing=True,
        has_changelog=True,
        has_workflows=True,
        has_tests=True,
        has_pyproject=True,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    assert score.total == 95
    assert score.grade == "A"
    # README 25, activity 10+5+5=20, community 25, CI 25.
    assert score.readme_score == 25
    assert score.activity_score == 20
    assert score.community_score == 25
    assert score.ci_score == 25
    # Total never exceeds the documented 100 ceiling.
    assert 0 <= score.total <= 100


# -- Empty README edge case --------------------------------------------------


@respx.mock
async def test_empty_readme_scores_exists_only():
    """A present-but-empty README earns the 5 'exists' points and nothing else.

    Length 0 fails >500 and >2000; no backticks fails code-blocks; no '![' or
    '[![' fails badges. So readme_score == 5 exactly, distinct from both the
    missing-README case (0) and the rich-README case (25).
    """
    _mock_repo(
        readme=httpx.Response(200, json=_readme("")),
        pushed_at="2015-01-01T00:00:00Z",
        has_issues=False,
        commits=[],
        releases=[],
        has_license=False,
        has_contributing=False,
        has_changelog=False,
        has_workflows=False,
        has_tests=False,
        has_pyproject=False,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    assert score.readme_score == 5
    assert score.total == 5
    readme_passed = {c.name for c in score.readme_checks if c.passed}
    assert readme_passed == {"readme_exists"}


# -- Zero-commit repo edge case ----------------------------------------------


@respx.mock
async def test_zero_commit_repo_fails_commit_check():
    """An empty repo (0 commits) fails commits_gt_10 but recency still scores.

    Separates the commit-count signal from the recency signal: this repo was
    pushed 5 days ago (committed_30d -> 10) yet has zero commits in the listing
    (commits_gt_10 -> fail). Activity subtotal is exactly 10, not 15.
    """
    _mock_repo(
        readme=httpx.Response(404),
        pushed_at=_iso_days_ago(5),
        has_issues=False,
        commits=[],
        releases=[],
        has_license=False,
        has_contributing=False,
        has_changelog=False,
        has_workflows=False,
        has_tests=False,
        has_pyproject=False,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    activity_passed = {c.name for c in score.activity_checks if c.passed}
    assert "committed_30d" in activity_passed
    assert "commits_gt_10" not in activity_passed
    assert "has_releases" not in activity_passed
    assert score.activity_score == 10
    assert score.total == 10


# -- Missing CI edge case ----------------------------------------------------


@respx.mock
async def test_missing_ci_zeroes_ci_category_only():
    """A well-documented repo with no CI scores 0 on CI but keeps other points.

    Isolates the CI category: README is rich (25) and license/issues present,
    but no workflows, no tests dir, no build config -> ci_score == 0. Confirms
    a missing CI subtracts exactly its own 25-point band and nothing more.
    """
    long_readme = (
        "# Title\n\n" + "A" * 2100 + "\n```python\nx=1\n```\n" + "![b](https://img/x.svg)"
    )
    _mock_repo(
        readme=httpx.Response(200, json=_readme(long_readme)),
        pushed_at="2015-01-01T00:00:00Z",
        has_issues=True,
        commits=[],
        releases=[],
        has_license=True,
        has_contributing=False,
        has_changelog=False,
        has_workflows=False,
        has_tests=False,
        has_pyproject=False,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    assert score.ci_score == 0
    assert all(not c.passed for c in score.ci_checks)
    # README 25 + community (license 10 + issues 5) 15 == 40; activity 0.
    assert score.readme_score == 25
    assert score.community_score == 15
    assert score.activity_score == 0
    assert score.total == 40


# -- Recency tier boundary (exclusive bands) ---------------------------------


@respx.mock
async def test_recency_90d_tier_excludes_30d():
    """A repo pushed 60 days ago scores the 90d tier (7), not the 30d tier (10).

    Locks the mutual exclusivity at a single point: exactly one recency check
    may pass, and it is the tightest band the age qualifies for.
    """
    _mock_repo(
        readme=httpx.Response(404),
        pushed_at=_iso_days_ago(60),
        has_issues=False,
        commits=[],
        releases=[],
        has_license=False,
        has_contributing=False,
        has_changelog=False,
        has_workflows=False,
        has_tests=False,
        has_pyproject=False,
        has_package_json=False,
    )
    score = await score_repo(OWNER, REPO, TOKEN)
    assert score.error is None
    recency_passed = [
        c.name
        for c in score.activity_checks
        if c.passed and c.name in {"committed_30d", "committed_90d", "committed_365d"}
    ]
    assert recency_passed == ["committed_90d"]
    assert score.activity_score == 7
    assert score.total == 7
