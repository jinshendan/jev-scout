# Comparing policies on shared inputs

`scout compare` runs two independent investigation arms over one bounded capture. It fixes task text, initial candidates, source read content, expansion and restoration rules, and budgets so a source change between arms cannot silently change their evidence. The default keeps the frontier fixed; opt-in follow-ups and context restoration derive later menus from each arm's own choices. This is a comparison harness, not a repair benchmark or a claim that Jev is better than rules.

## Start offline

Run from the Jev Scout repository root:

```sh
scout compare \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/comparison \
  --max-steps 6 \
  --max-context-chars 1200
```

The default `--challenger rule` compares two fresh rule policies and requires no key or network access. This is a sanity check for shared inputs, deterministic selection, and artifacts. Use a fresh output directory outside the investigated repository for every run.

## Opt in to Jev

Set `TYPESAFE_API_KEY` in your environment, then explicitly select the remote challenger:

```sh
scout compare \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/jev-comparison \
  --challenger jev \
  --max-steps 6 \
  --max-context-chars 1200 \
  --jev-model jev-1.13.0 \
  --jev-max-calls 8
```

**Selecting `--challenger jev` sends task text, candidate descriptions with relative paths and previews, and active source excerpts to TypeSafe AI.** Attempted requests remain in the challenger's local artifacts. API keys and raw provider error bodies do not. Keep the output private when investigating private source.

The challenger accepts the same `--jev-model`, `--jev-min-confidence`, `--jev-max-calls`, `--jev-timeout`, and `--jev-max-request-bytes` options as `investigate`. These options require a Jev challenger. Missing credentials are a setup error; provider failures and invalid or over-budget requests use recorded rule fallback. See the [Jev policy guide](jev-policy.md) for configuration and the provider boundary. Authenticated live-provider compatibility has not been validated.

## Shared capture and separate arms

Discovery runs once. The runtime captures full text only for sources in the retained frontier, bounded to 32 MiB in memory, and requires each captured hash to match the discovered candidate before starting either arm. Original source repositories remain read-only. Unsupported or changing source cannot be silently replaced with different content for one arm.

The snapshot ID hashes a canonical manifest containing task text, relative candidates, source hashes and byte counts, limits, expansion/restoration configuration, and implementation version. It excludes absolute repository roots and timestamps. Equivalent captured fixtures at different locations can therefore have the same ID. Changing `max_restores` changes the shared input identity even if the context is large enough that nothing is evicted. Capture is sequential and limited to the retained frontier; it is not an atomic whole-repository snapshot or a Git commit.

Complete captured source exists only in memory during the paired run. `comparison.json` retains the manifest, and arm bundles retain selected excerpts. These artifacts cannot reconstruct unobserved source or rerun the comparison after the checkout changes. Keep the original permitted repository revision separately when later reproduction is required.

The rule arm runs first, followed by the challenger. Each receives fresh policy state, its own active context, and a separate artifact directory. Jev can choose a different sequence using its own accumulated context. The provider cannot generate coordinates or read source outside the captured files.

## Compare with adjacent follow-ups

Both arms accept the same optional generated-candidate budget:

```sh
scout compare \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/followup-comparison \
  --max-steps 12 \
  --max-context-chars 1200 \
  --max-followups 6
```

`--max-followups` is an integer from 0 through 100, defaulting to `0`. A successful read lets the local runtime offer same-file adjacent windows of at most nine lines. Both arms share the initial frontier, the entire captured content for those files, the expansion algorithm, and all budgets. Generated offers count against each arm's quota and its total 100-candidate cap, including initial reads, follow-ups, and restoration offers. Selected follow-up reads use its existing action budget.

Later menus can differ because they depend on each arm's prior choices. This is part of the policy treatment, not unequal underlying source input. A candidate ID such as `c0007` is local to an arm and can refer to different spans after different exploration orders. Do not compare these IDs directly. See the [follow-up guide](follow-up-evidence.md) for source checks, suppression, and lineage.

## Compare with context restoration

Use a small context budget to exercise eviction and give both arms the same optional restoration quota:

```sh
scout compare \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/restoration-comparison \
  --max-steps 16 \
  --max-context-chars 40 \
  --max-followups 4 \
  --max-restores 4
```

`--max-restores` is an integer from 0 through 100, defaulting to `0`. The local runtime may offer one `restore_observation` candidate per actually evicted observation from that arm. The quota counts generated offers; it does not guarantee that a policy selects them or that checks succeed. Follow-ups are admitted before restore offers after a successful read, and all action kinds share the 100-candidate cap. Every selected restore, including a failed check, consumes one `--max-steps` action. The rule policy prioritizes unread source snippets before restoration.

A selected restore rechecks the source hash, exact original excerpt, and excerpt truncation against the captured source, then projects the retained text back into that arm's bounded FIFO context. It preserves the original observation ID and raw text and does not create a new observation or adjacent follow-up window. A restore may evict another observation; the one-off offer rule and quotas still apply. Changing or deleting the original checkout between arms cannot change these restoration inputs, and the restore does not reopen that checkout.

The snapshot records `restoration.algorithm: "evicted-observations-v1"`, `restoration.max_restores`, and `restoration.max_candidates`, along with `limits.max_restores`. Both arms share that configuration, but their evictions, offers, and restore choices can diverge. Standalone `scout recover` remains a separate explicit command for saved evidence; `--max-restores` concerns the ongoing investigation only. See the [context restoration guide](policy-context-restoration.md) for the typed action, source checks, and event trace.

## Read the output

```text
comparison/
  comparison.json
  report.md
  rule/
    evidence.json
    events.jsonl
    report.md
  challenger/
    evidence.json
    events.jsonl
    report.md
```

Each arm emits normal investigation schema 3 artifacts with `source_mode: "frozen"` and the shared `snapshot_id`. Observation validity `matched_frozen_snapshot` and `checked_snapshot_sha256` identify matching captured source; `current_sha256` is null. Selected restorations have separate `restoration_checks` with the same frozen-source scope, their target `observation_id`, and an `outcome` of `restored` or `omitted`. They do not claim the live checkout still matches. After both arms, the runtime rechecks the original checkout separately; inspect `original_source_revalidation` before following current-source links.

The top-level artifacts report discovery/capture elapsed time, whole-arm elapsed times, total comparison time through summary construction, provider attempts, actual backend choices, fallback, and reported or unknown usage. Total time includes output preparation and final checkout revalidation but excludes publication of the final comparison summary files. Missing usage remains unknown. A timed-out provider request may have consumed resources even when no token counts were returned.

`comparison.json` uses schema 3; its snapshot manifest remains schema 1. Each arm retains local `action_candidate_ids` and `observed_candidate_ids` for trace lookup alongside `action_identities` and `observed_action_identities`. The summary separates:

- `actions`: all selected read and restoration actions, including failed attempts.
- `action_counts.read_snippet` and `action_counts.restore_observation`: selected actions of each kind.
- `observations`: original source excerpts collected by successful reads; restoration does not increase this count.
- `successful_restores`: checks whose `outcome` is `restored`; inspect `restoration_checks` for individual outcomes and source scope.
- `initial_candidate_count`, `generated_followup_candidate_count`, `generated_restore_candidate_count`, and `total_candidate_count`: actual offered menu sizes. `generated_candidate_count` remains a compatibility alias for follow-up offers only.
- `expansion` and `restoration`: configured quotas, actual generated offers, and suppressed proposals for each mechanism.

`agreement.identity_basis` lists `kind`, `path`, `expected_sha256`, `start_line`, `end_line`, and `max_chars`. `positional_action_agreement` compares these semantic identities at corresponding positions across all selected actions. A read and a restoration of the same excerpt remain different actions because their `kind` differs. A restoration's `observation_id` is arm-local and is excluded: two arms can restore the same source excerpt under different IDs after reading it in different orders.

`observed_candidate_jaccard` measures semantic identity overlap among original reads that produced observations; restored context does not inflate it. These numeric field names remain unchanged from earlier schemas; schema 2 introduced semantic identities and schema 3 extends them to mixed read/restore actions. An empty denominator is null. These are behavioral diagnostics, not evidence-usefulness, root-cause, repair-success, or savings scores. A rule-versus-Jev run with fallback may mostly compare rules with rules; inspect actual selector counts before interpreting it. Enabling restoration gives both arms that option; this command does not directly compare restoration enabled against disabled or prove a restoration benefit.

The arms run sequentially, so ordering, filesystem caches, and provider load can affect latency. Shared capture cost is reported once; disclose how you allocate it when comparing per-arm cost. Controlled injected transports used by tests are labeled as fixtures or injected calls and are not live-provider measurements.

The [evaluation protocol](evaluation.md) defines the remaining task-quality and end-to-end work. See also the [architecture](architecture.md), [roadmap](roadmap.md), [ADR 0003](adr/0003-recovery-and-frozen-comparisons.md), [ADR 0004](adr/0004-bounded-follow-up-evidence.md), and [ADR 0005](adr/0005-policy-context-restoration.md).
