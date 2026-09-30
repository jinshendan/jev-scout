# ADR 0002: Typed Jev decisions with explicit rule fallback

- Status: Accepted and implemented for M2a
- Date: 2026-09-30
- Scope: Candidate selection and provider accounting

## Context

M1 establishes a bounded, read-only investigator with deterministic candidate selection and recoverable evidence. Adding a remote policy should expose which decisions it actually makes without changing source ownership, weakening execution boundaries, or removing the offline baseline.

Jev's official API supports closed Choice questions. This fits the existing frontier: local code defines executable candidates, and the provider chooses among their IDs. Provider availability and confidence must not be confused with evidence quality or repair success.

## Decision

Keep `--policy rule` as the default. Enable the TypeSafe adapter only through explicit `--policy jev` selection, with credentials supplied by `TYPESAFE_API_KEY`. Use a pinned default model and record the requested and returned versions.

Send one Choice question containing every unseen candidate, the task, and active working context. Bound the complete serialized request and response by bytes. If a request exceeds its cap, fall back to rules without sending it; do not silently reduce candidate coverage.

The standard-library transport calls only the official HTTPS endpoint, rejects redirects, ignores inherited proxy settings, and makes no automatic retries. Bound provider attempts separately from read steps. Configure an operation timeout and disclose that it is not a hard total-run deadline.

Validate closed-set membership, answer type, probability keys, finite values, normalization, selected maximum, response version, and the confidence floor locally. Exhausted limits, provider failures, invalid responses, and low confidence produce explicit rule fallback. Missing or malformed API keys fail setup before investigation; a provider authentication rejection is an attempted-call fallback.

Extend the compatible policy boundary to permit a typed `PolicyDecision` alongside the existing ID-or-stop result. The investigator retains ownership of source reads, evidence, and action validation. Schema 2 records configuration, typed decision traces, inspectable request payloads, response models, distributions, latency, attempts, and nullable provider usage. Credentials and raw provider errors remain excluded.

## Alternatives considered

**Require Jev for every run.** This would remove the offline control and turn service availability into an investigation prerequisite.

**Let the provider generate actions.** Free-form paths or commands would widen the execution boundary and mix candidate discovery with decision quality. M2a selects IDs only.

**Send a silently shortened shortlist.** This could make a byte limit look like a policy improvement or regression when the real difference was candidate coverage.

**Retry automatically.** Retries can improve availability but add attempts, latency, and potentially unreported cost. M2a uses explicit bounded fallback; a retry policy would require separately tested accounting.

**Treat confidence as task correctness.** Confidence summarizes the provider's distribution. Its utility for investigation needs task-level evaluation; the default floor is not a calibrated success threshold.

## Consequences

Remote selection transmits source context. Local artifacts retain those payloads for review and may contain private source excerpts. Their privacy follows the investigated repository. A request or context byte cap does not bound the total artifact size or establish a token budget.

Provider usage can be unknown after failed requests, and a rule fallback can follow a billed provider response. Reports must distinguish requested policy from actual selector and preserve missing usage as unknown.

Controlled HTTP fixtures validate the adapter's implementation contract, not live compatibility or model usefulness. M2a does not complete M2: adaptive evidence expansion, context recovery, credentialed validation, and reproducible comparisons remain necessary. Solver integration and persistent memory are later milestones.

See the [Jev policy guide](../jev-policy.md), [architecture](../architecture.md), and [roadmap](../roadmap.md).
