# ADR 0003: Explicit recovery and frozen comparison inputs

- Status: Accepted and implemented for M2b
- Date: 2026-10-01
- Scope: Evidence import, current-source checks, and policy-comparison provenance

## Context

M1 retains observations independently of working context; M2a records typed policy choices and fallback. A retained record needs an explicit route back into context. Comparing policies also needs equal source inputs: ordinary sequential live investigations can read different text if the checkout changes between them.

Recovery and comparison have different validity questions. Recovery asks whether a historical excerpt still matches current source. A frozen comparison asks whether each arm read the captured input, then separately asks whether the checkout still matches that capture. Treating both as live-current evidence would hide source changes.

## Decision

Add an offline `scout recover` command with explicit repository scope and requested observation IDs. Accept bounded schema 1 or 2 imports, capped at 16 MiB and 100 observations. Validate records and relative source access locally. Ignore imported repository metadata for access decisions.

Retain every requested historical record. Check its source hash, span, and excerpt/truncation against current source before admitting it to bounded FIFO context. Label changed, unavailable, and mismatched records and omit them from active context. Record the imported artifact's SHA-256 as a byte-level provenance link without claiming authenticity or automatic run resumption.

Add `scout compare` with an offline rule challenger by default and explicit Jev opt-in. Discover once, then capture full text only for the retained frontier within a 32 MiB memory cap. Captured source must match expected discovery hashes before either arm starts. Give fresh rule and challenger policies the same task, candidates, captured read content, and budgets.

Hash a canonical snapshot manifest containing relative inputs, source identities and sizes, task, limits, and implementation version. Exclude roots and timestamps. Run arms sequentially and keep separate traces. Mark frozen observations `matched_frozen_snapshot` and add `source_mode` and `snapshot_id` to their schema 2 bundles. Recheck the original checkout independently after both arms.

Report capture/setup, whole-arm, and total time, together with provider attempts, usage, and fallback. Preserve unknown usage. Report selection agreement and overlap only as behavior diagnostics; label injected transports as controlled fixtures rather than provider results.

## Alternatives considered

**Trust imported hashes and paths.** A hash can accompany altered text, and an absolute imported root can redirect access. Explicit source scope and span/excerpt checks keep the evidence contract local.

**Discard stale records.** This would erase what was observed and obscure why the recovered context differs. Keep historical evidence while excluding it from current context.

**Run both arms against live files.** Independent live reads can confound policy choices with changed input. A shared bounded capture makes the comparison's permitted reads inspectable.

**Call capture a repository revision.** Sequential file capture cannot guarantee an atomic global state. The snapshot ID identifies the disclosed bounded inputs only.

**Treat agreement as quality.** Policies can agree on poor evidence, and a valid Jev request can fall back to rules. Task outcomes and a fixed repair oracle are separate evaluation work.

## Consequences

Recovery and comparison remain read-only. Neither generates adaptive candidates, authenticates historical artifacts, resumes an investigation, edits code, or runs a repair solver.

Full captured text exists only in bounded process memory for permitted frontier sources. Persisted artifacts retain normal source excerpts and snapshot metadata rather than creating a whole-source archive. Frozen source citations point at a checkout that may change, so the recorded excerpt and separate checkout status are essential.

Sequential arms can have order and cache effects. Timing and usage are observable accounting, not proof of a monetary advantage. Authenticated live Jev validation, real task comparisons, adaptive expansion, solver evaluation, and chronological memory remain [roadmap](../roadmap.md) work.

See [evidence recovery](../evidence-recovery.md), [policy comparison](../policy-comparison.md), [architecture](../architecture.md), and [evaluation](../evaluation.md).
