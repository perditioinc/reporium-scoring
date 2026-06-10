# reporium-scoring

![License: MIT](https://img.shields.io/badge/license-MIT-brightgreen)

<!-- perditio-badges-start -->
[![Tests](https://github.com/perditioinc/reporium-scoring/actions/workflows/test.yml/badge.svg)](https://github.com/perditioinc/reporium-scoring/actions/workflows/test.yml)
![Last Commit](https://img.shields.io/github/last-commit/perditioinc/reporium-scoring)
![License](https://img.shields.io/github/license/perditioinc/reporium-scoring)
![python](https://img.shields.io/badge/python-3.11%2B-3776ab)
![suite](https://img.shields.io/badge/suite-Reporium-6e40c9)
![score range](https://img.shields.io/badge/score%20range-0--100-blue)
![install](https://img.shields.io/badge/install-pip-blue)
<!-- perditio-badges-end -->

> Score any GitHub repo 0-100 across README quality, activity, community health, and CI/CD. Pip-installable.

## Install

```bash
pip install git+https://github.com/perditioinc/reporium-scoring.git
```

## Quick Start

```bash
export GH_TOKEN=your_token
repo-score tiangolo/fastapi
```

Output:
```
tiangolo/fastapi: 95/100 (Grade: A)
  README:    25/25  ✓ exists ✓ >500 chars ✓ >2000 chars ✓ code blocks ✓ badges
  Activity:  20/25  ✓ committed last 30d ✓ >10 commits ✓ releases ✗ —
  Community: 25/25  ✓ license ✓ contributing ✓ issues enabled ✓ changelog
  CI:        25/25  ✓ workflows ✓ tests ✓ build config
```

## Scoring Rubric

| Category | Check | Points | Max |
|----------|-------|--------|-----|
| README | exists | 5 | |
| README | >500 chars | 5 | |
| README | >2000 chars | 5 | |
| README | has ``` blocks | 5 | |
| README | has badges | 5 | **25** |
| Activity | committed last 30d | 10 | |
| Activity | committed last 90d (if not 30d) | 7 | |
| Activity | committed last 365d (if not 90d) | 3 | |
| Activity | >10 commits | 5 | |
| Activity | has releases | 5 | **25** |
| Community | has LICENSE | 10 | |
| Community | has CONTRIBUTING.md | 5 | |
| Community | issues enabled | 5 | |
| Community | CHANGELOG or releases | 5 | **25** |
| CI | has .github/workflows/ | 10 | |
| CI | has tests/ or test/ | 10 | |
| CI | has pyproject.toml or package.json | 5 | **25** |

**Grades:** A=90+, B=75+, C=60+, D=40+, F<40

**Note:** Activity recency checks are mutually exclusive tiers (30d > 90d > 365d).

## Python API

```python
import asyncio
from reporium_scoring import score_repo, score_repos_batch

# Single repo
score = asyncio.run(score_repo("tiangolo", "fastapi", token="ghp_..."))
print(f"{score.total}/100  Grade: {score.grade}")
print(score.to_dict())

# Batch (concurrent)
repos = [("tiangolo", "fastapi"), ("pydantic", "pydantic"), ("huggingface", "transformers")]
scores = asyncio.run(score_repos_batch(repos, token="ghp_...", concurrency=5))
for s in scores:
    print(f"{s.owner}/{s.repo}: {s.total}/100 ({s.grade})")
```

Batch output:
```
tiangolo/fastapi: 95/100 (A)
pydantic/pydantic: 90/100 (A)
huggingface/transformers: 90/100 (A)
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| GH_TOKEN | yes | - | GitHub PAT (read:repo scope) |
| CONCURRENCY_CHECKS | no | 10 | Parallel checks per batch |

## How This Fits With Reporium

The Reporium platform already stores `ai_dev_skills` for 571 repos via reporium-api — that
signal captures **what a repo does** (RAG, Agents, LLM Serving, etc.).

reporium-scoring scores **how well it is maintained** — README quality, recent activity,
community health, CI/CD. These are orthogonal signals:

| Signal | Source | Answers |
|--------|--------|---------|
| `ai_dev_skills` | reporium-api | What does this repo do? |
| `score` (0-100) | reporium-scoring | How well is it maintained? |

Together they give two views on any repo. A high-starred project with ai_dev_skills="RAG"
and score=30/100 (Grade D) tells you it's relevant but poorly maintained — worth knowing
before you depend on it.

**Example — vllm:**
```
vllm-project/vllm: 95/100 (Grade: A)
  README:    25/25  ✓ exists ✓ >500 chars ✓ >2000 chars ✓ code blocks ✓ badges
  Activity:  25/25  ✓ committed last 30d ✓ >10 commits ✓ releases
  Community: 25/25  ✓ license ✓ contributing ✓ issues enabled ✓ changelog
  CI:        20/25  ✓ workflows ✓ tests ✗ build config
```

reporium-api tags vllm as `ai_dev_skills=["Inference & Serving"]`. reporium-scoring
confirms it is actively maintained (committed in last 30 days, 10+ commits, releases,
license, CI). Both signals together: high-quality, well-maintained LLM inference engine.

## How reporium-db Uses This

reporium-db calls `score_repos_batch` nightly to score newly added or updated repos.
Scores are stored alongside metadata and surfaced in the reporium.com UI for filtering and ranking.

Each repo in `pending_enrichment.json` is scored on its next run. Scores feed into the
reporium-api search index, enabling users to filter by quality grade.

## Contributing

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check .
```

## License

MIT
