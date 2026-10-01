# Bounded adjacent-source follow-ups

Version 0.4.0 adds an optional route from a successful source read to neighboring
evidence. The local runtime generates concrete candidate windows; the existing
rule or Jev policy selects their IDs. The initial lexical discovery still runs
once, and the default fixed-frontier baseline remains unchanged.

## Enable follow-ups

Run from the Jev Scout repository root after installation:

```sh
scout investigate \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/followup-demo \
  --max-steps 12 \
  --max-context-chars 1200 \
  --max-followups 6
```

Use a fresh output directory outside the investigated source repository.
`--max-followups` accepts an integer from 0 through 100 and defaults to `0`.
`scout compare` accepts the same option. `scout recover` retains its explicit
observation-import boundary and has no follow-up option.

Library callers can pass the keyword argument `max_followups=N` to
`investigate(...)` or `compare(...)`. All other source, context, step, and
provider limits remain in force. Opting into follow-ups alone makes no network
request; Jev still requires explicit `--policy jev` or `--challenger jev`.

## Generation and selection

After a candidate produces a successful, hash-matching observation, the runtime
can offer two windows in a stable order:

1. `before`: the at most nine lines immediately before the parent candidate.
2. `after`: the at most nine lines immediately after it.

Windows are clipped to the source file. Empty windows at a file boundary are
omitted. Every generated candidate stays in the parent path, carries the same
expected SHA-256 and maximum excerpt-character limit, and names a concrete
start/end line. The algorithm identifier is `adjacent-lines-v1`; the window size
is fixed at nine lines, without a separate CLI setting.

An unavailable, skipped, failed, or hash-mismatched read cannot seed expansion.
Later live reads recheck the expected source identity through the ordinary
safe-read boundary. Frozen comparison reads use the shared captured file instead
of the live checkout. Neither path trusts provider-supplied coordinates.

Candidates are deduplicated by path, expected source hash, start/end lines, and
maximum excerpt characters. A duplicate is not added and consumes no generated
offer. Each admitted candidate gets a unique arm-local ID, a score of
`max(0, parent_score - 1)`, and a preview of at most 240 characters. This score
keeps the deterministic ranking explicit; it is not a relevance-quality score
validated against task outcomes. Previously generated candidates can seed further
neighbors after their own successful reads.

The policy sees the current offered frontier and chooses an unseen ID as usual.
Generation does not force the new candidate to be read. Jev cannot add paths,
commands, or coordinates; it remains a closed-choice selector. See the
[Jev policy guide](jev-policy.md) for request limits and fallback.

## Budgets and coverage

| Limit | Meaning |
| --- | --- |
| `--max-followups` | Maximum admitted generated candidates, including offers never selected |
| 100 total candidates | Initial discovery, follow-ups, and restoration offers share this global cap |
| `--max-steps` | All selected read and restoration actions, including skipped actions, share the same budget |
| Nine lines | Maximum proposed neighboring window; a file boundary can shorten it |
| 4,000 excerpt characters | Maximum retained text per ordinary CLI candidate read |
| `--max-context-chars` | Active excerpt characters; context eviction still preserves raw observations |

Adding follow-ups does not reset any budget. An initially full 100-candidate
frontier leaves no expansion capacity. An admitted offer consumes its quota
even if the run later stops before selecting it. With both generation options
enabled, follow-ups after a successful read are admitted before restoration
offers triggered by that read's context evictions. This stable order is visible
in events and matters when shared candidate capacity is nearly full. A step budget can end the run
with unseen follow-ups still in the frontier. Provider calls and request bytes
remain separate budgets; a larger menu can trigger explicit rule fallback.

Line windows are lexical coordinates, not functions or compiler symbols. A
4,000-character excerpt can truncate even one long line, and the next proposal
starts beyond the parent's complete line window. Repeated follow-ups therefore
do not guarantee complete text coverage, a complete function body, or discovery
of a necessary file. A missing observation does not prove a path is absent.

## Read the expansion trace

Investigation `evidence.json` schema 3 retains the expansion fields introduced in schema 2:

- `initial_candidate_ids`: the candidates discovered before the loop.
- `generated_candidate_lineage`: records with `candidate_id`,
  `parent_candidate_id`, `parent_observation_id`, and `direction`.
- `expansion`: generation configuration, counts, and capacity status.

`expansion` records `enabled`, `algorithm`, `window_lines`, `max_followups`,
`initial_candidates`, `generated_candidates`, `suppressed_proposals`,
`candidate_limit_reached`, `followup_limit_reached`,
`candidate_limit_suppressed_proposals`, and
`followup_limit_suppressed_proposals`.

`suppressed_proposals` counts distinct, nonempty proposals refused by the offer
quota or global candidate cap. The two reason counts can both include a proposal
when both limits apply. Duplicates and empty boundary windows are omitted rather
than counted as budget-suppressed proposals. A reached flag describes capacity;
it can be true without any proposal having been refused.

When expansion is enabled, `candidate_generated` events retain each complete
candidate and its parent IDs/direction. `frontier_expansion_checked` events retain
the parent IDs, admitted candidate IDs, and current expansion accounting. Normal
selection and read events still show which offers became observations. The
report summarizes initial discovery, generated offers, quota usage, and limits.
Evicting the parent from working context does not erase the original observation
or the candidate's lineage.

Recovery accepts schema 1, 2, and 3 investigation bundles through its existing
bounded observation contract. It checks selected excerpts against explicit
current source and does not resume expansion. See [evidence recovery](evidence-recovery.md).

## Frozen comparisons

Comparisons capture full source text only for the initial retained files, within
the existing 32 MiB memory cap. Both arms share those files, initial candidates,
task, expansion settings, and budgets. Each arm derives its own later menus from
its successful choices; no new file enters the capture.

Generated IDs depend on exploration order, so they are useful only within an
arm. Comparison schema 3 computes agreement from `kind`, `path`,
`expected_sha256`, `start_line`, `end_line`, and `max_chars`, while retaining
local IDs for trace lookup. Shared source does not imply identical later menus.
See [policy comparison](policy-comparison.md).

## Remaining work

Follow-ups do not rescan, discover cross-file relationships, resume a run, edit
source, execute investigated code, or add a repair solver. Version 0.5.0
separately offers opt-in [policy-selected context restoration](policy-context-restoration.md).
Restoration has its own generated-offer quota while sharing candidate capacity
and action steps with follow-ups; a restored observation does not seed neighbors. It does not establish live Jev compatibility,
quality, latency, or monetary benefit. Those boundaries and further work are
recorded in the [architecture](architecture.md), [roadmap](roadmap.md), and
[ADR 0004](adr/0004-bounded-follow-up-evidence.md).
