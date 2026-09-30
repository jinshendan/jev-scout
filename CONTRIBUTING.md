# Contributing to Jev Scout

Thanks for helping make code investigation measurable and inspectable.

## Scope and language

Use English for code identifiers, comments, documentation, issues, and pull requests. The [roadmap](docs/roadmap.md) defines the current milestone. Keep contributions focused on one reviewable behavior; avoid combining a new backend, a storage redesign, and a benchmark change in the same PR.

The first implementation establishes an offline rule baseline. Learned policies should remain replaceable and must be compared with that baseline. Do not describe observations as verified root causes or advertise performance gains without an appropriate evaluation.

## Development workflow

With Python 3.11+ on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
python -m build
```

The runtime has no third-party dependencies. The `dev` extra provides linting and distribution-building tools. Use a fresh output directory outside the investigated repository for CLI smoke tests.

1. Open or choose an issue with a concrete problem and acceptance criteria.
2. Create a feature branch from `main`.
3. Implement the change and update the affected documentation.
4. Run the checks above and an appropriate CLI smoke test.
5. Open a PR explaining the behavior, validation, and material limits.

Push a focused branch when it reaches a validated checkpoint. Use draft PRs for work that is still changing. Keep `main` as the reviewed project entry point; avoid pushing unrelated work or generated investigation outputs.

## Evidence and data

Tests and examples must use synthetic or redistributable source. Never commit API credentials, private code, local reports, raw investigations of unrelated repositories, or benchmark solutions. Source-derived observations should retain their scope and provenance. Context eviction must not silently destroy recoverable raw evidence.

For evaluation work, freeze dataset revisions and task IDs. Keep development and test splits separate. A public benchmark result must follow the dataset's protocol; cross-task memory experiments require a separately documented chronological protocol.

## Design changes

Changes to evidence validity, action execution, budgets, or remote data handling need an architecture decision record in `docs/adr/`. Describe the problem, considered options, decision, and consequences. Prefer the simplest design that makes failures visible and provides a practical fallback.

## Pull request descriptions

Lead with the problem and resulting behavior. Include the relevant checks and remaining limitations. Link the issue being addressed and distinguish implemented functionality from future work. A reviewer should be able to understand the PR without reading earlier chats.
