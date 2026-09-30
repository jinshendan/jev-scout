# Jev Scout

**An evidence-first runtime for investigating code under a bounded budget.**

Jev Scout explores a repository, keeps source-backed observations recoverable, and hands bounded working context alongside inspectable evidence to a developer or a coding agent. Its research goal is to determine when a decision model such as Jev can improve the cost and reliability of code investigation.

**Status:** Alpha. M1's offline investigator is implemented in [PR #5](https://github.com/jinshendan/jev-scout/pull/5), pending merge. This stacked implementation adds **M2a: an optional typed Jev candidate selector**, with explicit rule fallback and decision accounting. Live provider validation, adaptive evidence recovery, and policy comparisons remain unfinished. No efficiency or repair-success claims have been established.

[Quick start](#quick-start) · [Jev policy](docs/jev-policy.md) · [Architecture](docs/architecture.md) · [Demo](docs/demo.md) · [Roadmap](docs/roadmap.md) · [Evaluation](docs/evaluation.md)

## The problem

Repository investigation consumes time and model context before a coding agent can propose a useful change. Search results, repeated file reads, and partially tested hypotheses accumulate. Compacting that history can remove evidence that becomes important later.

Jev Scout treats investigation as a sequence of explicit decisions:

1. **Acquire:** which concrete operation can answer an unresolved question?
2. **Retain:** which observations belong in the current working context?
3. **Escalate:** when do existing candidates stop making progress and require new reasoning?

The runtime keeps the evidence behind those decisions inspectable. A selected file is a lead; an observation is not automatically a root cause; a model's confidence is not a correctness guarantee.

## Architecture

This is the target architecture. The current runtime discovers a fixed lexical frontier once and reads selected excerpts. Rules or Jev choose among those candidates; adaptive search and model reasoning are later extensions.

```mermaid
flowchart LR
    Task[Task and repository state] --> Candidates[Concrete action candidates]
    Candidates --> Policy[Policy and budget controller]
    Policy --> Tools[Read-only repository tools]
    Tools --> Evidence[Source-backed evidence store]
    Evidence --> Context[Bounded working context]
    Context --> Candidates
    Evidence --> Handoff[Evidence bundle and report]
    Policy -. later milestone .-> Reasoner[LLM reasoning and repair]
    Reasoner -. new hypotheses .-> Candidates
```

**Concrete candidates** carry executable parameters. The decision layer selects a candidate ID rather than inventing shell commands. **Evidence** keeps source locations and content fingerprints. **Working context** is a bounded view of that evidence, so removing an observation from context does not destroy its original record.

The default policy is deterministic and runs without an API key. Explicitly selecting Jev enables a remote backend behind `Policy.choose(state, candidates)`. Jev chooses an existing candidate ID; local code validates the response and executes the read. Provider failures and low-confidence answers fall back to rules while remaining visible in the trace.

See the [architecture document](docs/architecture.md), [evidence decision](docs/adr/0001-evidence-first-runtime.md), and [Jev decision](docs/adr/0002-typed-jev-decisions.md) for boundaries and tradeoffs.

## Incremental delivery

| Milestone | Deliverable | Acceptance question |
| --- | --- | --- |
| M1 — Local evidence baseline | Implemented, in review: read-only investigation, bounded context, raw events, evidence bundle, source-linked report | Can a run preserve and expose useful source evidence reproducibly? |
| M2 — Jev decision backend | M2a in review: typed selection, explicit fallback, usage accounting. Recovery and comparisons remain planned. | Does Jev improve candidate selection over the rule baseline? |
| M3 — Repair and evaluation | Fixed downstream solver, executable verification, paired experiments | Does investigation improve the success–cost tradeoff end to end? |
| M4 — Repository memory | Version-aware reuse, invalidation, chronological evaluation | When does accumulated experience help, and when should it be ignored? |

The runnable M1 baseline is available in [PR #5](https://github.com/jinshendan/jev-scout/pull/5). [M2a PR #6](https://github.com/jinshendan/jev-scout/pull/6) builds on it; its review must be considered alongside the baseline. Try the full implementation on the [M2a branch](https://github.com/jinshendan/jev-scout/tree/feat/jev-decision-policy). Each milestone is delivered in focused PRs with an updated roadmap and relevant verification. See [open issues](https://github.com/jinshendan/jev-scout/issues) for the active work.

## Quick start

Requires **Python 3.11+ on macOS or Linux**. The runtime uses the Python standard library. There is no PyPI release yet; install from a checkout. During review, the full current implementation is on `feat/jev-decision-policy`.

```sh
git clone --branch feat/jev-decision-policy https://github.com/jinshendan/jev-scout.git
cd jev-scout
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

scout investigate \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/demo \
  --max-steps 6 \
  --max-context-chars 1200
```

Open `.scout/demo/report.md` and compare its citations with the source. The [walkthrough](docs/demo.md) explains what the example can establish.

| Artifact | What it contains |
| --- | --- |
| `report.md` | Source-linked excerpts, coverage limits, policy accounting, and stopping reason |
| `evidence.json` | Schema 2: observations, source fingerprints, candidates, active context, and decision traces |
| `events.jsonl` | Ordered decisions, inspectable request payloads, reads, context changes, and source revalidation |

Choose a fresh output directory **outside the repository being investigated**. In this example, `.scout/demo` is outside `examples/cancellation`. For another repository:

```sh
scout investigate --repo /path/to/repository \
  --task "Trace the cancellation path for Request::cancel" \
  --output /tmp/scout-investigation-001
```

`--max-steps` bounds snippet actions, including skipped actions. `--max-context-chars` bounds active excerpt characters, not tokens or the size of retained artifacts. The result also records fixed discovery, source-read, and candidate limits. Reuse an observation by its ID in `evidence.json`; automatic run resumption is future work.

## Optional Jev selection

The quick start uses `--policy rule` by default and makes no network requests. To enable Jev, set `TYPESAFE_API_KEY` in your environment, then run:

```sh
scout investigate \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/jev-demo \
  --policy jev \
  --jev-model jev-1.13.0 \
  --jev-max-calls 8
```

**Selecting Jev sends the task, candidate descriptions with relative source paths and previews, and active source excerpts to TypeSafe AI.** Request payloads are retained in local artifacts for inspection. Keep artifacts private when investigating private source. API keys, authorization headers, and provider error bodies are excluded from artifacts.

Jev ranks the same unseen candidates as the rule baseline. Requests that exceed the byte limit fall back without a network call; candidates are not silently dropped to fit. Exhausted call budgets, invalid responses, provider errors, and answers below the confidence floor also use explicit rule fallback. Missing credentials are a setup error. There are no automatic retries.

See the [Jev policy guide](docs/jev-policy.md) for all limits, the official API contract, and fallback accounting. Tests use controlled HTTP fixtures; an authenticated live-provider run has not been validated. Confidence describes the returned distribution, not the probability of solving the task.

## Implemented in M1

- Local text-based discovery and bounded snippet reads.
- Explicit action candidates and a replaceable policy interface.
- Source fingerprints and observation IDs.
- Context eviction with original evidence retained.
- English Markdown and JSON handoff artifacts.
- A small [C++ cancellation scenario](examples/cancellation/README.md) for inspecting the workflow.

M1 is a lexical source inspector. It does not provide semantic C++ analysis, automatic diagnosis, code edits, test execution, or measured token savings. Working-context eviction retains the original recorded excerpt; it does not archive the entire source file.

## Implemented in M2a

- Opt-in Jev Choice requests over existing candidate IDs.
- Local response validation and explicit deterministic fallback.
- Provider call and payload limits with no automatic retries.
- Schema 2 decision traces with requested and returned models, distributions, latency, and reported usage.

M2a changes candidate selection within the fixed frontier. It does not generate queries, recover evicted context automatically, edit code, add a solver, or create persistent repository memory. Those are tracked separately in the [roadmap](docs/roadmap.md).

## Development

```sh
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
python -m build
```

CI validates the package and CLI on Linux and macOS. Tests cover source-access boundaries, budgets, changed source, deterministic selection, recoverable context, and provider contract/fallback behavior without a live key. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development and PR workflow.

## Research discipline

The primary outcome is task quality at a measured total cost, not a smaller prompt in isolation. Comparisons will include simple output masking, structural retrieval, rule-based selection, and ordinary summarization. Cold-start indexing, caches, failed attempts, retries, and downstream repair must be accounted for.

Related work already covers repository maps, inexpensive exploration, and repository memory. The open question here is how candidate coverage, recoverable evidence, and escalation interact in a complete investigation loop. See the [evaluation plan](docs/evaluation.md) for sources, baselines, and protocol constraints.

## Contributing

The project is implemented and documented in English. Small contributions with clear behavior and validation are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); substantial design choices belong in [architecture decision records](docs/adr/).

## License

[MIT](LICENSE). Jev Scout is an independent project and is not affiliated with TypeSafe AI. The project license does not cover external model services or grant access to model weights.

## Implementation reviews

The runnable implementation is delivered in focused review branches. Each PR includes its behavior, validation, and remaining work.

| Review | Scope | Dependency |
| --- | --- | --- |
| [M1 — PR #5](https://github.com/jinshendan/jev-scout/pull/5) | Offline evidence investigator, CLI, source validation, packaging, and CI | Project foundation on `main` |
| [M2a — PR #6](https://github.com/jinshendan/jev-scout/pull/6) | Opt-in typed Jev selection, bounded requests, explicit rule fallback, and decision accounting | M1; review and merge PR #5 first |

Try the full current implementation using the [M2a branch quick start](https://github.com/jinshendan/jev-scout/tree/feat/jev-decision-policy#quick-start). Authenticated provider validation and policy-quality comparisons remain open M2 work.
