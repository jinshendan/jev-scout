# Comparing policies on shared inputs

`scout compare` runs two independent investigation arms over one bounded capture. It fixes task text, initial candidates, source read content, expansion rules, and budgets so a source change between arms cannot silently change their evidence. The default keeps the frontier fixed; opt-in follow-ups derive later menus from each arm's own choices. This is a comparison harness, not a repair benchmark or a claim that Jev is better than rules.

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

The snapshot ID hashes a canonical manifest containing task text, relative candidates, source hashes and byte counts, limits, and implementation version. It excludes absolute repository roots and timestamps. Equivalent captured fixtures at different locations can therefore have the same ID. Capture is sequential and limited to the retained frontier; it is not an atomic whole-repository snapshot or a Git commit.

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

`--max-followups` is an integer from 0 through 100, defaulting to `0`. A successful read lets the local runtime offer same-file adjacent windows of at most nine lines. Both arms share the initial frontier, the entire captured content for those files, the expansion algorithm, and all budgets. Generated offers count against each arm's quota and the shared initial-plus-generated 100-candidate cap; selected follow-up reads use its existing step budget.

Later menus can differ because they depend on each arm's prior choices. This is part of the policy treatment, not unequal underlying source input. A candidate ID such as `c0007` is local to an arm and can refer to different spans after different exploration orders. Do not compare these IDs directly. See the [follow-up guide](follow-up-evidence.md) for source checks, suppression, and lineage.

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

Each arm emits normal investigation schema 2 artifacts with `source_mode: "frozen"` and the shared `snapshot_id`. Observation validity `matched_frozen_snapshot` and `checked_snapshot_sha256` identify matching captured source; `current_sha256` is null. They do not claim the live checkout still matches. After both arms, the runtime rechecks the original checkout separately; inspect `original_source_revalidation` before following current-source links.

The top-level artifacts report discovery/capture elapsed time, whole-arm elapsed times, total comparison time through summary construction, provider attempts, actual backend choices, fallback, and reported or unknown usage. Total time includes output preparation and final checkout revalidation but excludes publication of the final comparison summary files. Missing usage remains unknown. A timed-out provider request may have consumed resources even when no token counts were returned.

`comparison.json` now uses schema 2; its snapshot manifest remains schema 1. Each arm retains local `action_candidate_ids` and `observed_candidate_ids` for trace lookup alongside `action_identities` and `observed_action_identities`. It also records `initial_candidate_count`, `generated_candidate_count`, and `expansion`.

`agreement.identity_basis` lists `kind`, `path`, `expected_sha256`, `start_line`, `end_line`, and `max_chars`. `positional_action_agreement` compares these semantic identities at corresponding positions, while `observed_candidate_jaccard` measures identity overlap among actions that produced observations. Their numeric field names remain unchanged from schema 1, but their basis has changed from local IDs to source/action identities. An empty denominator is null. These are behavioral diagnostics, not evidence-usefulness, root-cause, repair-success, or savings scores. A rule-versus-Jev run with fallback may mostly compare rules with rules; inspect actual selector counts before interpreting it. Recovery is a separate command, so this comparison does not test a recovery treatment.

The arms run sequentially, so ordering, filesystem caches, and provider load can affect latency. Shared capture cost is reported once; disclose how you allocate it when comparing per-arm cost. Controlled injected transports used by tests are labeled as fixtures or injected calls and are not live-provider measurements.

The [evaluation protocol](evaluation.md) defines the remaining task-quality and end-to-end work. See also the [architecture](architecture.md), [roadmap](roadmap.md), [ADR 0003](adr/0003-recovery-and-frozen-comparisons.md), and [ADR 0004](adr/0004-bounded-follow-up-evidence.md).
