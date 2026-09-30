# Jev Scout roadmap

The milestones separate an inspectable baseline from later agent behavior. Each milestone describes its deliverable and exit criteria; future components and performance benefits are not assumed to exist.

Track implementation in [M1](https://github.com/jinshendan/jev-scout/issues/1), the Jev adapter in [M2](https://github.com/jinshendan/jev-scout/issues/2), controlled repair evaluation in [M3](https://github.com/jinshendan/jev-scout/issues/3), and repository memory in [M4](https://github.com/jinshendan/jev-scout/issues/4).

## M1 — Offline evidence investigator

**Current scope:** Python 3.11+, standard-library implementation on supported POSIX systems; deterministic rules; read-only local repository inspection; bounded scans, reads, steps, and working context; structured evidence and a human-readable report.

**Delivery:** Merged in [PR #5](https://github.com/jinshendan/jev-scout/pull/5). The CLI, packaging, tests, and CI are available on `main`.

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

**In progress:** add Jev behind the decision-policy interface while keeping evidence collection and solver interfaces separate. M2 is split into focused increments; a working adapter alone does not complete the milestone.

### M2a — Typed candidate selection and accounting

**Delivered scope:** an optional standard-library adapter to the official TypeSafe endpoint, with the offline rule policy still the default. Merged in [PR #6](https://github.com/jinshendan/jev-scout/pull/6) and available on `main`.

Implemented in this increment:

- One Choice question over all unseen, concrete candidate IDs, task text, and active context.
- A pinned default model, configurable confidence floor, and environment-only credentials.
- Request/response byte limits, a provider-call budget, socket-operation timeout, and no automatic retries.
- Local closed-choice validation and explicit rule fallback for invalid, unavailable, uncertain, or over-budget requests.
- Schema 2 artifacts with inspectable payloads, decision traces, model versions, latency, and nullable provider token counts.
- Controlled HTTP fixture tests for the wire contract and failure paths without credentials.

Acceptance checks: the offline baseline remains runnable; unknown IDs cannot execute actions; source observations survive fallback; invalid responses and provider limits produce visible traces; keys and error bodies stay out of artifacts.

An authenticated live-provider run has not been validated. M2a provides a testable adapter contract, not a measured improvement over rules. See the [Jev policy guide](jev-policy.md) and [ADR 0002](adr/0002-typed-jev-decisions.md).

### Remaining M2 work

The following remain planned:

- Requests for additional evidence and recovery of context-evicted observations.
- Adaptive candidate generation with explicit coverage and revision checks.
- Reproducible rule-versus-Jev comparisons on the same sources, candidates, limits, and evidence contract.
- Credentialed provider validation and reporting of model behavior and actual usage.
- Trace links between investigations and subsequent work.

Exit criterion: a policy comparison uses the same source inputs, candidates, limits, and evidence contract with both the rule policy and Jev. Invalid or unavailable provider responses have an explicit fallback. No benchmark benefit is assumed.

## M3 — Fixed solver and controlled evaluation

**Planned:** connect investigation to a fixed LLM repair solver and compare policies under a reproducible evaluation environment.

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
