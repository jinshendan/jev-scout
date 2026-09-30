# Jev Scout roadmap

The milestones separate an inspectable baseline from later agent behavior. Each milestone describes its deliverable and exit criteria; future components and performance benefits are not assumed to exist.

## M1 — Offline evidence investigator

**Current scope:** Python 3.11+, standard-library implementation on supported POSIX systems; deterministic rules; read-only local repository inspection; bounded scans, reads, steps, and working context; structured evidence and a human-readable report.

**Delivery:** the first implementation PR. The foundation commit documents the contract and evaluation plan; the implementation branch adds the CLI, packaging, tests, and CI.

```sh
scout investigate --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N
```

Artifacts: `events.jsonl`, `evidence.json`, and `report.md`.

Exit criteria:

- Produce inspectable artifacts from a local repository without model credentials or network access.
- Respect resource limits and disclose truncation, partial inspection, and budget exhaustion.
- Preserve original observations independently of working-context eviction.
- Attribute evidence to source locations and expected content identities.
- Distinguish errors and partial results from successful inspection.
- Test deterministic decisions, budgets, evidence recovery, source access boundaries, and artifact consistency.

M1 is a rule baseline for investigation. It does not resolve issues, establish complete root causes, validate patches, resume a previous run, learn across tasks, or provide calibrated confidence.

## M2 — Jev integration

**Planned:** add Jev behind the decision-policy interface while keeping evidence collection and solver interfaces separate.

Deliverables:

- A typed Jev policy adapter with explicit configuration and model-version recording.
- Narrow questions over concrete candidates, with separately validated confidence handling.
- Provider usage, latency, retries, and fallback accounting; credentials remain outside artifacts.
- A versioned evidence contract and inspectable request payloads.
- Requests for additional evidence and recovery of context-evicted observations.
- Revision checks, partial-result handling, and links between investigation traces and subsequent work.
- Provider-neutral policy boundaries that preserve evidence ownership and provenance.

Exit criterion: a policy comparison uses the same source inputs, candidates, limits, and evidence contract with both the rule policy and Jev. Invalid or unavailable provider responses have an explicit fallback. No benchmark benefit is assumed.

## M3 — Fixed solver and controlled evaluation

**Planned:** introduce a model-driven investigation policy and compare it with M1 under a fixed LLM solver and reproducible evaluation environment.

Deliverables:

- Pinned model, prompt, tool, dataset, and environment configurations.
- Baselines for ordinary search, observation masking, summaries, and Scout's evidence handoff.
- Whole-pipeline cost and latency accounting, including failed attempts, escalation, and context construction.
- Per-instance results, failure analysis, and uncertainty over both tasks and repositories.
- Conditional evidence expansion or model escalation compared with fixed allocation policies.

Exit criterion: publish a reproducible success-rate versus cost comparison with its limitations. A negative result is informative; smaller prompts alone do not establish better economics or correctness.

## M4 — Long-term repository memory

**Planned:** explore repository-specific memory across a chronological task sequence after single-task evaluation is stable.

Deliverables:

- Evidence-backed memory with revision identity, refresh rules, and explicit invalidation.
- Retrieval and fallback for stale, conflicting, sparse, or irrelevant memory.
- Separate cold-start construction cost and amortized maintenance cost.
- A chronological evaluation track that prevents future fixes or evaluation labels from entering earlier investigations.

Exit criterion: show when memory helps, when it harms, and the task volume needed to justify its construction. Keep this track separate from standard single-task leaderboard results.

## Decision gates

Add complexity after the preceding interface is inspectable and its evaluation is credible. Defer compiler semantics, multi-agent orchestration, a hosted service, and automatic repair until a concrete use case warrants them. In particular, textual C++ inspection must not be marketed as semantic understanding without compiler-grounded validation.

Repository memory already has direct precedent in [Improving Code Localization with Repository Memory](https://arxiv.org/abs/2510.01003). A later Jev memory component must be compared with such approaches; combining memory, search, and routing is not itself a novelty claim.
