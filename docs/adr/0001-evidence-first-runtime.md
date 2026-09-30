# ADR 0001: Evidence-first investigation runtime

- Status: Accepted for M1
- Date: 2026-09-30
- Scope: Jev Scout investigation and handoff

## Context

Repository exploration can generate more text than a downstream agent should receive. Forwarding everything makes context expensive and difficult to inspect. Keeping only a summary can erase source detail, hide uncertainty, and make mistaken interpretations hard to correct.

Scout needs a useful first milestone without depending on a particular language model or provider. A deterministic offline rule baseline makes the evidence contract and resource boundaries testable before adding model policy, repair, or long-term memory.

## Decision

Retain inspectable observations separately from bounded working context. Every observation must be attributable to its source, and interpretations must remain distinguishable from observations. Eviction from working context must not silently discard a retained original.

Record ordered investigation events and stopping reasons. Emit `events.jsonl`, structured `evidence.json`, and human-readable `report.md`. Preserve successful observations across recoverable inspection failures. Disclose truncation, missing information, and partial investigation.

Use the provider-neutral `Policy.choose(state, candidates)` boundary. Candidates specify concrete paths, spans, and expected SHA-256 values. M1 uses deterministic rules and bounded local read-only access, implemented with Python 3.11+ and the standard library. Jev integration, model policy with fixed-solver evaluation, and persistent repository memory are separate milestones.

Candidate scores guide investigation; they are not calibrated correctness probabilities. Future consumers should recover original evidence and widen search rather than being constrained to an incomplete file set.

## Alternatives considered

**Full transcript as working context.** Simple and transparent, but does not enforce a useful handoff budget. Separate retention preserves inspectability without forwarding every observation.

**Summary-only handoff and storage.** Compact, but recovery depends on rereading source that may have changed, and interpretations replace evidence. Summaries may become optional views later, not the only stored record.

**Model-driven exploration from the first release.** Potentially useful, but mixes contract problems with provider behavior, stochastic decisions, and API costs. Start with rules to make comparison measurable.

**Compiler graph as a universal requirement.** Offers deeper semantics, but adds build, platform, and language dependencies. M1 provides textual evidence and declares its limitations; compiler integration needs a separate decision.

## Consequences

Retained evidence can be larger than working context. Retention therefore needs explicit limits and visible truncation; a context budget alone does not bound disk use. Original excerpts support inspection, not a complete repository archive, automatic run resumption, or deterministic replay of arbitrary tools.

M1 cannot claim repair correctness, complete root-cause analysis, semantic C++ understanding, or token savings for an LLM pipeline. Those require controlled evaluation. Future memory must identify revisions, invalidate stale entries, account for construction and refresh costs, and preserve a fallback to current source.

This decision adds a small artifact and provenance contract to the runtime, making later policy changes comparable under the same evidence boundary. See [architecture](../architecture.md), [roadmap](../roadmap.md), and [evaluation protocol](../evaluation.md).
