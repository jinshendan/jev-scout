# ADR 0004: Bounded same-file follow-up evidence

- Status: Accepted and implemented for M2c
- Date: 2026-10-01
- Scope: Adjacent candidate generation, lineage, budgets, and comparison identity

## Context

The baseline discovers one lexical window per retained file. A policy can choose
among those windows but cannot inspect neighboring definitions through the same
action loop. Explicit recovery restores retained observations; it does not
create evidence that the first investigation never read.

Adding an unrestricted search or provider-authored action would widen source
access and make budget accounting difficult. A small local expansion should
preserve the offline baseline, source identity checks, evidence retention, and
the closed-choice policy boundary.

Frozen comparisons also need to distinguish shared underlying inputs from
policy-dependent later menus. Generated candidate IDs reflect each arm's order
of discovery; equal IDs alone cannot establish that two actions read the same
source span.

## Decision

Add the keyword argument `max_followups` and CLI option `--max-followups`, defaulting to zero and
restricted to integers from 0 through 100. Keep discovery once per run. After a
successful observation with a matching expected hash, the runtime proposes at
most nine lines immediately before and after the parent candidate in the same
file, under algorithm `adjacent-lines-v1`.

Keep generation and validation of concrete paths, spans, and expected source hashes
under local runtime control. Jev still receives relative paths, spans, and previews
in the offered candidate descriptions; it does not supply these coordinates. A failed read
cannot seed follow-ups. Deduplicate span identities and give admitted candidates
unique local IDs, a score of `max(0, parent_score - 1)`, a preview capped at 240
characters, and the parent's maximum excerpt size. Either policy selects among
offered IDs; the provider gains no ability to invent coordinates or commands.

Count admitted offers against the follow-up quota even when they are never
selected. Initial and generated candidates share the global cap of 100. All
selected actions use the existing step budget, and context remains the existing
bounded FIFO projection. Do not reset provider budgets or silently enlarge
request limits.

Retain investigation schema 2. Record the initial candidate IDs, generation
settings/counters, and parent candidate/observation/direction lineage in the
bundle and ordered events. Preserve original observations when context evicts
them. Existing explicit recovery imports continue to validate observations;
they do not replay generation or resume the run.

Frozen comparisons capture full bounded source only for the initial retained
files. Give both arms the same initial candidates, source, task, expansion rules,
and limits; allow later menus to depend on their own successful choices. Update
the top-level comparison summary to schema 2 and compare semantic identities
`(kind, path, expected_sha256, start_line, end_line, max_chars)` for action
agreement and observation overlap. Keep local candidate IDs for trace lookup.
The snapshot manifest remains schema 1 and records expansion configuration.

## Alternatives considered

**Let Jev propose paths or line numbers.** This would widen a validated choice
boundary into action generation. Keep coordinates executable and inspectable
before the provider sees the menu.

**Rescan after every read.** This adds repeated repository work and can introduce
different source coverage in the two comparison arms. Use adjacent windows in
already retained files as the first expansion increment.

**Count only selected follow-ups.** Unbounded unselected offers would still grow
the frontier and provider request. Count generation itself and preserve a
separate read-step budget.

**Compare generated IDs directly.** Different exploration orders can assign
different IDs to the same span or the same ID to different spans. Compare source
and action identity while keeping IDs for each arm's trace.

**Enable expansion by default.** This would change the established rule baseline
and its cost. Make the treatment explicit and leave the default frontier fixed.

## Consequences

The investigator remains read-only, offline by default, and bounded. Follow-ups
can reveal nearby text missed by the initial window, but they do not establish
semantic relationships, whole-file coverage, a root cause, or a repair result.
Long lines can exceed the 4,000-character retained excerpt; adjacency is based
on the parent line span rather than the truncated text.

Fixed source capture supports both arms' neighboring reads even when the live
checkout changes. Different menus are an expected policy effect. Shared initial
inputs and semantic agreement make the trace comparable, not a quality score.

Cross-file expansion, automatic recovery, investigation links, authenticated
Jev validation, solver evaluation, and repository memory remain separate work.
See [follow-up evidence](../follow-up-evidence.md), [policy comparison](../policy-comparison.md),
[architecture](../architecture.md), and [roadmap](../roadmap.md).
