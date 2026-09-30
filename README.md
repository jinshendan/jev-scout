# Jev Scout

**An evidence-first runtime for investigating code under a bounded budget.**

Jev Scout explores a repository, keeps source-backed observations recoverable, and hands a compact evidence bundle to a developer or a coding agent. Its research goal is to determine when a decision model such as Jev can improve the cost and reliability of code investigation.

**Status:** project foundation. The first implementation milestone is a local, read-only, deterministic baseline. Jev integration and automated repair are subsequent milestones; no efficiency or repair-success claims have been established.

[Architecture](docs/architecture.md) · [Roadmap](docs/roadmap.md) · [Evaluation plan](docs/evaluation.md) · [Contributing](CONTRIBUTING.md)

## The problem

Repository investigation consumes time and model context before a coding agent can propose a useful change. Search results, repeated file reads, and partially tested hypotheses accumulate. Compacting that history can remove evidence that becomes important later.

Jev Scout treats investigation as a sequence of explicit decisions:

1. **Acquire:** which concrete operation can answer an unresolved question?
2. **Retain:** which observations belong in the current working context?
3. **Escalate:** when do existing candidates stop making progress and require new reasoning?

The runtime keeps the evidence behind those decisions inspectable. A selected file is a lead; an observation is not automatically a root cause; a model's confidence is not a correctness guarantee.

## Architecture

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

The first policy is deterministic and runs without an API key. Jev will be the first remote decision backend behind a replaceable policy interface. This separation provides a meaningful baseline and keeps the project usable when a model is unavailable.

See the [architecture document](docs/architecture.md) and [first design decision](docs/adr/0001-evidence-first-runtime.md) for boundaries and tradeoffs.

## Incremental delivery

| Milestone | Deliverable | Acceptance question |
| --- | --- | --- |
| M1 — Local evidence baseline | Read-only investigation, bounded context, raw events, evidence bundle, source-linked report | Can a run preserve and expose useful source evidence reproducibly? |
| M2 — Jev decision backend | Typed decisions, explicit fallback, usage accounting, backend comparisons | Does Jev improve candidate selection over the rule baseline? |
| M3 — Repair and evaluation | Fixed downstream solver, executable verification, paired experiments | Does investigation improve the success–cost tradeoff end to end? |
| M4 — Repository memory | Version-aware reuse, invalidation, chronological evaluation | When does accumulated experience help, and when should it be ignored? |

M1 is the first implementation PR. Each later milestone will be delivered in focused PRs with an updated roadmap and relevant verification. See [open issues](https://github.com/jinshendan/jev-scout/issues) for the active work.

## What the first implementation will demonstrate

- Local text-based discovery and bounded snippet reads.
- Explicit action candidates and a replaceable policy interface.
- Source fingerprints and observation IDs.
- Context eviction with original evidence retained.
- English Markdown and JSON handoff artifacts.
- A small [C++ cancellation scenario](examples/cancellation/README.md) for inspecting the workflow.

This milestone will not provide semantic C++ analysis, automatic diagnosis, code edits, test execution, or measured token savings. Those boundaries are part of the experiment design, not hidden capabilities.

## Research discipline

The primary outcome is task quality at a measured total cost, not a smaller prompt in isolation. Comparisons will include simple output masking, structural retrieval, rule-based selection, and ordinary summarization. Cold-start indexing, caches, failed attempts, retries, and downstream repair must be accounted for.

Related work already covers repository maps, inexpensive exploration, and repository memory. The open question here is how candidate coverage, recoverable evidence, and escalation interact in a complete investigation loop. See the [evaluation plan](docs/evaluation.md) for sources, baselines, and protocol constraints.

## Contributing

The project is implemented and documented in English. Small contributions with clear behavior and validation are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); substantial design choices belong in [architecture decision records](docs/adr/).

## License

[MIT](LICENSE). Jev Scout is an independent project and is not affiliated with TypeSafe AI. The project license does not cover external model services or grant access to model weights.
