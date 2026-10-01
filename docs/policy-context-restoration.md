# Policy-selected context restoration

Version 0.5.0 adds bounded recall of evidence during an ongoing investigation.
When an observation leaves working context, the runtime can offer a concrete
`restore_observation` action. A rule or Jev policy selects its ID; local code
revalidates the source and reinserts the original observation into context.
The default remains disabled, preserving the offline read-selection baseline.

## Enable restoration

Run from the installed Jev Scout checkout:

```sh
scout investigate \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/restoration-demo \
  --max-steps 12 \
  --max-context-chars 40 \
  --max-restores 3
```

Choose a fresh output directory outside `examples/cancellation`. The small
context budget makes eviction and bounded reinsertion visible. On the unchanged
fixture with the rule policy, this command collects seven original observations
and selects ten actions: seven reads and three successful restorations. It admits
three restoration offers and ends with `o0003` projected to forty characters.
These counts describe this fixture and configuration, not a quality result.

`--max-restores` accepts an integer from 0 through 100 and defaults to `0`.
`scout compare` accepts the same option. Library callers can pass the keyword
argument `max_restores=N` to `investigate(...)` or `compare(...)`; booleans,
non-integers, and values outside the range are rejected before run setup.
Opting into restoration makes no network request; Jev remains explicit through
`--policy jev` or `--challenger jev`.

## Eligible observations and concrete actions

Only an observation recorded by the current run and evicted from its working
context can seed a restoration offer. The local runtime supplies its original
observation ID, relative source path, start/end lines, expected SHA-256, retained
excerpt limit, and preview. The action kind is `restore_observation`; its
parameters use `RestoreObservationArgs`. Read candidates continue to use
`ReadSnippetArgs` and the kind `read_snippet`.

Each observation is considered at most once. An admitted offer counts against
its quota even if never selected. An observation whose offer is suppressed by
a quota or the global candidate cap is not reconsidered. Restoring and later
evicting the same observation cannot generate another offer. Currently active
observations are never inserted twice.

A policy selects from unseen offered IDs through the existing
`Policy.choose(state, candidates)` interface. It cannot invent an observation,
read an imported run, supply new paths or line numbers, or return a freeform
operation. Unknown or repeated candidate IDs are rejected before action
execution. Candidate and observation IDs are local to the run.

The rule policy preserves deterministic ordering and prioritizes unseen reads
before restoration offers, whose score is `-1`. Jev can select either action
kind from the same menu. Jev descriptions include `kind` and, for restoration,
`observation_id`; the ordinary request-size, provider-call, validation, and
fallback rules still apply. See the [Jev policy guide](jev-policy.md).

## Source validation and context projection

A selected restoration checks that its target and source attribution match the
runtime-owned original. It then uses the ordinary safe-read boundary to check:

1. The source remains available through the permitted relative path.
2. Its SHA-256 matches the observed source identity.
3. The line span exists and yields exactly the recorded excerpt.
4. The excerpt's recorded truncation agrees with the original excerpt limit.

A live match has validity `current_at_restore_check`. A frozen comparison match
has validity `matched_frozen_snapshot`. Changed, unavailable, or mismatched
source is omitted from the restored context while historical evidence remains
retained. An already-active or mismatched target is also omitted. Validation is
a point-in-time check; final source revalidation still labels later changes.

A successful restoration reuses the original observation ID and retained text.
It does not append another raw observation or recover text that was never
retained. The same FIFO eviction and character truncation rules apply; a
restoration can evict another observation, which may receive its own one-shot
offer. Raw evidence remains independent of the current context projection.
Restored evidence cannot seed adjacent follow-ups.

## Shared budgets

| Limit | Meaning |
| --- | --- |
| `--max-restores` | Maximum admitted restoration offers, including unselected offers |
| 100 total candidates | Initial discovery, follow-ups, and restoration offers share one cap |
| `--max-steps` | Every selected read or restoration, including skipped actions, uses one step |
| `--max-context-chars` | Active excerpt characters after FIFO eviction and projection |
| 4,000 excerpt characters | Ordinary CLI reads retain at most this many characters per original observation |
| Jev calls and request bytes | Independent provider limits; restoration grants no additional allowance |

An initially full 100-candidate frontier leaves no capacity for restoration or
follow-ups. With both generation options enabled, follow-ups after a successful
read are admitted before restoration offers caused by that read's evictions.
This stable order is visible in events and can affect which offers fit the
remaining candidate capacity. No option resets another budget.

## Inspect the trace

Investigation `evidence.json` uses schema 3. In addition to the original
observations and current context, inspect:

- `candidates`: complete read and restoration actions; restoration arguments
  identify the original `observation_id`.
- `action_counts`: selected `read_snippet` and `restore_observation` counts.
- `restoration`: configuration, generated offers, and suppressed proposals.
- `restoration_checks`: outcomes of selected restoration actions.

`restoration` records `enabled`, `algorithm: "evicted-observations-v1"`,
`max_restores`, `generated_candidates`, `suppressed_proposals`,
`candidate_limit_suppressed_proposals`, and
`restore_limit_suppressed_proposals`. A proposal can count under both suppression
reasons when both limits apply. Repeated consideration and a disabled feature
do not create another suppressed proposal.

Each restoration check records `candidate_id`, `observation_id`, `source_mode`,
`current_sha256`, `outcome` (`restored` or `omitted`), `validity`, and
`source_check_reason`. Frozen checks use null `current_sha256` and record
`checked_snapshot_sha256` when a captured source is available. Check records
remain separate from the original observation's final source-validity label.

Ordered events include `restoration_candidate_generated`,
`restoration_frontier_checked`, and `observation_restoration_checked`, alongside
normal decisions, action selection, context eviction, and truncation. The
report distinguishes original observations, reads, restoration attempts,
successful restorations, and offered candidates. A restored count does not mean
all those observations remain active at the end.

Consumers of previous investigation schemas must explicitly support schema 3
and mixed action kinds. Manual [evidence recovery](evidence-recovery.md) accepts
schemas 1, 2, and 3 through its bounded observation-import contract.

## Frozen policy comparisons

Exercise restoration with two independent offline rule policies:

```sh
scout compare \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/restoration-comparison \
  --max-steps 12 \
  --max-context-chars 40 \
  --max-restores 3
```

Both arms restore only their own observations and validate them against captured
source. Neither arm consults the live checkout during restoration. A separate
checkout check after both arms retains the existing provenance boundary. The
snapshot manifest includes `max_restores` in `limits` and a `restoration`
configuration with algorithm, maximum offers, and the 100-candidate cap.

Comparison summary schema 3 exposes each arm's `action_counts`,
`successful_restores`, `restoration_checks`,
`generated_followup_candidate_count`, `generated_restore_candidate_count`, and
`total_candidate_count`. `generated_candidate_count` remains a follow-up-only
compatibility field; it is not the total of both generated kinds.

Semantic action agreement uses kind, relative path, expected source hash,
start/end lines, and maximum excerpt characters. It excludes arm-local candidate
and observation IDs. A read and a restoration of the same span remain distinct
actions. Observation overlap counts the original successful reads; reinserting
evidence does not inflate it. The unchanged fixture yields matching rule arms
with three successful restorations each. Agreement is a sanity check, not a
measurement of localization quality, repair success, or monetary savings.
See the [comparison guide](policy-comparison.md).

## Relationship to explicit recovery and remaining work

`scout recover` imports an earlier bundle, takes explicit observation IDs and an
explicit live repository, and produces a new context handoff. In-run restoration
uses observations already owned by the active runtime and lets a policy choose
within its existing action budget. Neither mechanism resumes a previous run,
replays provider requests, or executes investigated code.

Bounded recall can revisit evidence removed from a prompt, but it does not
establish which evidence is useful or verify a diagnosis. Cross-file expansion,
credentialed Jev comparisons, and links to subsequent investigations remain M2
work. Repair evaluation and chronological repository memory remain later
milestones. See the [architecture](architecture.md), [roadmap](roadmap.md), and
[ADR 0005](adr/0005-policy-context-restoration.md).
