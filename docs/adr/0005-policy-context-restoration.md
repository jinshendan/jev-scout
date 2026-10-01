# ADR 0005: Policy-selected restoration of evicted context

- Status: Accepted and implemented for M2d
- Date: 2026-10-01
- Scope: In-run restoration actions, source validity, shared budgets, and comparison identity

## Context

The runtime preserves original observations when bounded working context evicts
them. Explicit recovery can rebuild a handoff from an earlier bundle, but an
ongoing policy cannot choose to revisit an evicted observation through its
normal action interface. Adjacent follow-ups collect more source; they do not
reinsert existing evidence.

A restoration action needs source-validity checks before an old excerpt can
return to active context. It must also remain bounded when restoring one
observation evicts another. Adding a second generated action kind creates a
shared-capacity and candidate-ID problem, and comparison IDs remain local to
each arm's exploration order.

## Decision

Add CLI `--max-restores` and keyword argument `max_restores` to investigation and
comparison, defaulting to zero and restricted to integer values from 0 through
100. Count generated offers rather than successful restorations. Only evicted
observations recorded by this current run are eligible. Consider each observation
once, so repeat eviction cannot mint another offer, including when the first
proposal was suppressed by a limit.

Keep executable action parameters under runtime ownership. Add the action kind
`restore_observation` and typed `RestoreObservationArgs` carrying the original
observation ID and concrete source attribution. The policy selects an offered
candidate ID through its existing interface. The rule baseline prioritizes
unseen reads before restorations, scored `-1`; the Jev Choice descriptions include
kind and restoration observation ID. Provider-authored paths, coordinates, and
freeform operations remain outside the contract.

Use one candidate registry to allocate unique IDs and enforce the global cap of
100 across discovery, follow-ups, and restorations. Keep their generated-offer
quotas separate. After a successful read, admit follow-ups before restoration
offers caused by its context evictions. Every selected action consumes the same
step budget, including a restoration omitted after validation. Do not reset
source, context, request, or provider limits.

Before reinsertion, check the runtime-owned target, safe source access, source
hash, line span, exact retained excerpt, and truncation flag. Share the exact
excerpt checker with explicit recovery. Changed, unavailable, or mismatched
records remain historical evidence and cannot enter restored context. A valid
restoration reuses the original observation ID and text without creating a new
raw observation. Keep FIFO eviction and bounded character projection; prevent
duplicate active observation IDs. Restorations do not seed adjacent follow-ups.

Advance investigation and comparison summary schemas to 3. Preserve original
observation meanings and add mixed action candidates, separate action counts,
restoration generation accounting, and ordered check outcomes. Explicit recovery
continues its distinct schema 1 handoff and accepts investigation schemas 1, 2,
and 3 through its existing bounded import.

Frozen comparisons restore each arm's own observations against the same captured
source used for reads, without live source access during an arm. Include
restoration settings in snapshot identity and keep checkout revalidation
separate. Agreement uses `(kind, path, expected_sha256, start_line, end_line,
max_chars)` and excludes arm-local observation IDs. Read and restoration actions
for the same span remain distinct. Observed-evidence overlap counts original
reads, so reinsertion cannot inflate it.

## Alternatives considered

**Reinsert every evicted observation automatically.** That would make retention
an implicit runtime action and can repeatedly evict other records. Offer a
bounded action for policy selection, with one consideration per observation.

**Count only successful restorations.** Unselected menus and failed checks would
still grow runtime/provider work. Bound offers, total candidates, and selected
actions separately.

**Trust an observed source hash without an excerpt check.** A matching hash does
not alone establish that the retained span, text, and truncation are consistent.
Share the exact check with explicit recovery.

**Create a new observation when restoring.** This would obscure retained-evidence
ownership and could inflate evidence counts or overlap. Reuse the original ID.

**Read the current checkout in a frozen arm.** This would give restoration a
different source boundary from ordinary reads. Revalidate captured source and
report live-checkout changes separately.

**Compare restoration observation IDs across arms.** They depend on each arm's
read order. Compare source/action identity and retain IDs only for trace lookup.

## Consequences

The offline baseline remains available and defaults to read-only investigation
with restoration disabled. Opt-in policies can revisit retained evidence while
all work stays bounded and source-attributed. A tiny context may restore and
then evict useful evidence; one-shot offers prevent unbounded cycling but do not
promise an optimal retention strategy.

Consumers must support schema 3 and distinguish total selected actions from new
observations. Mixed action menus can enlarge provider requests and trigger the
existing explicit fallback. Restoration is point-in-time reuse of retained
excerpts, not persistent memory, run resumption, a diagnosis, or a measured
quality improvement.

Cross-file expansion, authenticated Jev validation, trace links to subsequent
work, downstream repair evaluation, and repository memory remain separate work.
See [context restoration](../policy-context-restoration.md),
[evidence recovery](../evidence-recovery.md),
[policy comparison](../policy-comparison.md),
[architecture](../architecture.md), and [roadmap](../roadmap.md).
