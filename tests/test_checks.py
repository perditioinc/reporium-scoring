"""Tests for individual check modules."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import respx

from reporium_scoring.checks.activity import check_activity
from reporium_scoring.checks.ci import check_ci
from reporium_scoring.checks.community import check_community
from reporium_scoring.checks.readme import check_readme
from reporium_scoring.client import GITHUB_API, GitHubClient

OWNER = "test-owner"
REPO = "test-repo"


def _readme_response(text: str) -> dict:
    """Build a /readme API response with encoded content."""
    return {"content": base64.b64encode(text.encode()).decode() + "\n", "encoding": "base64"}


# ── README checks ──────────────────────────────────────────────────────────────


@respx.mock
async def test_readme_full_score():
    """Long README with code blocks and badges earns all 5 check passes."""
    content = "# T\n" + "A" * 2100 + "\n```py\npass\n```\n![badge](url)"
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/readme").mock(
        return_value=httpx.Response(200, json=_readme_response(content))
    )
    async with GitHubClient("tok") as client:
        results = await check_readme(client, OWNER, REPO)
    passed = [c for c in results if c.passed]
    assert len(passed) == 5


@respx.mock
async def test_readme_minimal():
    """Short README without code blocks earns only the 'exists' check."""
    content = "Hello"
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/readme").mock(
        return_value=httpx.Response(200, json=_readme_response(content))
    )
    async with GitHubClient("tok") as client:
        results = await check_readme(client, OWNER, REPO)
    names = {c.name for c in results if c.passed}
    assert "readme_exists" in names
    assert "readme_2000_chars" not in names


@respx.mock
async def test_readme_missing():
    """No README means all checks fail."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/readme").mock(return_value=httpx.Response(404))
    async with GitHubClient("tok") as client:
        results = await check_readme(client, OWNER, REPO)
    assert all(not c.passed for c in results)


# ── Activity checks ────────────────────────────────────────────────────────────


@respx.mock
async def test_activity_full():
    """Repo pushed yesterday with 11 commits and releases passes all activity checks."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}").mock(
        return_value=httpx.Response(
            200,
            json={
                "pushed_at": (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "has_issues": True,
            }
        )
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/commits", params={"per_page": "11"}).mock(
        return_value=httpx.Response(200, json=[{}] * 11)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases", params={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )

    async with GitHubClient("tok") as client:
        results = await check_activity(client, OWNER, REPO)

    passed = {c.name for c in results if c.passed}
    assert "committed_30d" in passed
    assert "has_releases" in passed
    assert "commits_gt_10" in passed


@respx.mock
async def test_activity_old_repo():
    """Repo inactive for 2 years scores zero on recency, low overall."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}").mock(
        return_value=httpx.Response(
            200, json={"pushed_at": "2020-01-01T00:00:00Z", "has_issues": False}
        )
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/commits", params={"per_page": "11"}).mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases", params={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=[])
    )

    async with GitHubClient("tok") as client:
        results = await check_activity(client, OWNER, REPO)

    passed = {c.name for c in results if c.passed}
    assert "committed_30d" not in passed
    assert "committed_90d" not in passed
    assert "committed_365d" not in passed


# ── Community checks ───────────────────────────────────────────────────────────


@respx.mock
async def test_community_full():
    """Repo with license, contributing, issues, and changelog passes all checks."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}").mock(
        return_value=httpx.Response(200, json={"has_issues": True})
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/license").mock(
        return_value=httpx.Response(200, json={"license": {"key": "mit"}})
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/CONTRIBUTING.md").mock(
        return_value=httpx.Response(200, json={"name": "CONTRIBUTING.md"})
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/CHANGELOG.md").mock(
        return_value=httpx.Response(200, json={"name": "CHANGELOG.md"})
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases", params={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=[])
    )

    async with GitHubClient("tok") as client:
        results = await check_community(client, OWNER, REPO)

    assert all(c.passed for c in results)


@respx.mock
async def test_community_minimal():
    """Repo with no license, contributing, or changelog fails all community checks."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}").mock(
        return_value=httpx.Response(200, json={"has_issues": False})
    )
    for path in ["license", "contents/CONTRIBUTING.md", "contents/CHANGELOG.md"]:
        respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/{path}").mock(
            return_value=httpx.Response(404)
        )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases", params={"per_page": "1"}).mock(
        return_value=httpx.Response(200, json=[])
    )

    async with GitHubClient("tok") as client:
        results = await check_community(client, OWNER, REPO)

    assert all(not c.passed for c in results)


# ── CI checks ─────────────────────────────────────────────────────────────────


@respx.mock
async def test_ci_full():
    """Repo with workflows, tests dir, and pyproject.toml passes all CI checks."""
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/.github/workflows").mock(
        return_value=httpx.Response(200, json=[{"name": "test.yml"}])
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/tests").mock(
        return_value=httpx.Response(200, json=[{"name": "test_foo.py"}])
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/test").mock(
        return_value=httpx.Response(404)
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/pyproject.toml").mock(
        return_value=httpx.Response(200, json={"name": "pyproject.toml"})
    )
    respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/contents/package.json").mock(
        return_value=httpx.Response(404)
    )

    async with GitHubClient("tok") as client:
        results = await check_ci(client, OWNER, REPO)

    assert all(c.passed for c in results)


@respx.mock
async def test_ci_missing():
    """Repo with no workflows, tests, or build config fails all CI checks."""
    for path in [
        "contents/.github/workflows",
        "contents/tests",
        "contents/test",
        "contents/pyproject.toml",
        "contents/package.json",
    ]:
        respx.get(f"{GITHUB_API}/repos/{OWNER}/{REPO}/{path}").mock(
            return_value=httpx.Response(404)
        )

    async with GitHubClient("tok") as client:
        results = await check_ci(client, OWNER, REPO)

    assert all(not c.passed for c in results)
