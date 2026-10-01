# Jev Scout roadmap

[English](roadmap.md) · [简体中文](roadmap.zh-CN.md)

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

### M2b — Explicit recovery and frozen policy comparisons

**Implemented in this increment:** recover retained observations by ID and compare two independent policy arms over one bounded capture. See the [recovery guide](evidence-recovery.md), [comparison guide](policy-comparison.md), and [ADR 0003](adr/0003-recovery-and-frozen-comparisons.md).

**Delivery:** [PR #7](https://github.com/jinshendan/jev-scout/pull/7).

```sh
scout recover --evidence PATH --repo PATH --observation ID --output DIR \
  --max-context-chars N
scout compare --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --challenger rule
```

Delivered scope:

- Bounded import of schema 1 or 2 evidence and explicit repository selection.
- Retained historical records with hash, span, and excerpt checks; only matching current records enter bounded context.
- A single captured frontier and source content shared by rule and challenger arms, with separate policy state and traces.
- Snapshot identity, separate checkout revalidation, setup and arm timing, and provider/fallback accounting.
- Offline rule-versus-rule sanity comparisons; explicit `--challenger jev` for credentialed comparisons.

Acceptance checks: evicted observations can be requested without losing their original excerpt; changed, unavailable, or tampered excerpts cannot enter active context; the artifact's repository metadata cannot widen source access; two arms read the same captured source even if the checkout changes; frozen evidence never claims live-source validity; unknown provider usage stays unknown.

This increment provides comparison mechanics, not live Jev validation or a policy-quality result. Sequential capture is not an atomic repository snapshot. Recovery is manual and does not resume the investigation or generate additional candidates.

### M2c — Bounded neighboring evidence

**Implemented in this increment, version 0.4.0:** allow either policy to select locally generated adjacent snippets after successful source inspection. See the [follow-up guide](follow-up-evidence.md), [comparison guide](policy-comparison.md), and [ADR 0004](adr/0004-bounded-follow-up-evidence.md).

**Delivery:** [PR #9](https://github.com/jinshendan/jev-scout/pull/9).

```sh
scout investigate --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-followups N
scout compare --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-followups N --challenger rule
```

Delivered scope:

- Opt-in `--max-followups` from 0 through 100, defaulting to zero to preserve the fixed-frontier baseline.
- At most nine-line windows immediately before or after a successfully read candidate in the same hash-matching file.
- A quota on generated offers and a shared 100-candidate cap; generated reads consume the existing step/context budgets.
- Duplicate suppression, parent candidate/observation lineage, explicit expansion accounting, and ordinary rule/Jev selection over offered IDs.
- Frozen comparisons sharing initial candidates, source, expansion rules, and limits, with independent later menus.
- Comparison schema 2 behavioral diagnostics based on source/action identity rather than arm-local candidate IDs; investigation schema 2 and recovery imports remain compatible.

Acceptance checks: failed or hash-mismatched reads cannot seed candidates; generated coordinates stay in the parent file and carry its expected hash; IDs remain unique; offer and total-candidate limits are visible; evicted context does not erase evidence or lineage; different arm-local IDs cannot create false agreement or disagreement; source mutation cannot change a frozen follow-up's content.

This increment expands neighboring evidence only. It does not rescan, discover new files, automatically recover context, resume a run, or add a solver. Excerpts and finite budgets can leave coverage gaps. Live Jev compatibility and task-quality gains remain unvalidated.

### M2d — Policy-selected context restoration

**Implemented in this increment, version 0.5.0:** let either policy select a runtime-generated action that restores an observation evicted from the current run's context. See the [restoration guide](policy-context-restoration.md), [recovery guide](evidence-recovery.md), and [ADR 0005](adr/0005-policy-context-restoration.md).

```sh
scout investigate --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-restores N
scout compare --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-restores N --challenger rule
```

Delivered scope:

- Opt-in `--max-restores` from 0 through 100, defaulting to zero; its quota counts generated offers rather than successful restorations.
- At most one concrete `restore_observation` candidate per context-evicted observation from this run, selected through the existing rule/Jev interface.
- Revalidation of safe source access, expected hash, line span, exact excerpt, and truncation before reusing the original observation ID and text.
- A shared 100-candidate cap across discovery, follow-ups, and restorations, plus one step budget for every selected read or restoration, including skipped actions.
- Schema 3 investigation/comparison artifacts with separate read/restoration accounting; explicit recovery imports schemas 1, 2, and 3.
- Frozen restoration checks against the same captured source as reads, with arm-local observation IDs excluded from semantic action agreement.

Acceptance checks: defaults preserve offline selection behavior; only offered IDs execute; active observations are not duplicated; stale, unavailable, or mismatched source cannot enter context; raw evidence survives restoration or omission; restoration never creates a new observation; quotas and global capacity are enforced; repeat eviction cannot generate another offer; comparison arms do not read live source to restore frozen evidence.

This increment provides bounded recall within an investigation. The rule baseline prioritizes unseen reads before restoration offers; a restored projection can evict another record under the same FIFO budget. Restoration does not resume a previous run, discover new files, produce a repair, or establish a measured quality benefit. Live Jev validation remains pending.

### Remaining M2 work

The following remain planned:

- Policy-requested cross-file evidence with explicit coverage and source-revision checks.
- Candidate expansion beyond adjacent windows with explicit coverage and revision checks.
- Real rule-versus-Jev rollouts using the shared-input harness and a disclosed task set.
- Credentialed provider validation and reporting of model behavior and actual usage.
- Trace links between investigations and subsequent work.

Exit criterion: publish credentialed rule-versus-Jev comparisons using the same source inputs, initial candidates, expansion/restoration rules, limits, and evidence contract, with reported provider behavior and usage. Later menus may depend on each policy's choices and must remain traceable. Invalid or unavailable provider responses have an explicit fallback. Inspectable traces must support evidence expansion and links to subsequent work. No benchmark benefit is assumed.

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
