# Recovering retained evidence

`scout recover` builds a new bounded working context from explicitly requested observations in an earlier investigation. It runs offline and keeps the source repository read-only. It is useful when an excerpt was evicted from context or a developer wants to inspect a smaller handoff.

## Run recovery

After creating an investigation, inspect its `evidence.json` for observation IDs:

```sh
scout recover \
  --evidence .scout/demo/evidence.json \
  --repo examples/cancellation \
  --observation o0001 \
  --observation o0002 \
  --output .scout/recovery \
  --max-context-chars 1200
```

Use IDs that exist in your bundle. Repeat `--observation` for each requested record. The output directory must be fresh and outside the investigated repository; use a new directory for every recovery run. `--max-context-chars` defaults to 12,000 and bounds active excerpt characters, not tokens or the full artifact size.

The input must be an investigation `evidence.json` using schema 1 or 2, including a frozen comparison arm's bundle. Frozen validity is historical metadata; recovery still requires a fresh check against the supplied live repository before including an excerpt. Imports are capped at 16 MiB and 100 observations. Invalid schema or records, unknown requested IDs, and unsafe source paths are rejected rather than executed as instructions. A `recovery.json` is a distinct artifact, not another investigation bundle.

## What is checked

The explicit `--repo` controls source access. An absolute repository path recorded in the imported artifact is metadata and cannot redirect recovery. Paths are read through the same bounded, no-symlink repository access used by investigation.

Each requested record is checked against the current source file's SHA-256, line span, and excerpt text, including recorded truncation. A matching hash alone cannot make an edited historical excerpt eligible for context. All requested historical records remain in the result; only current matching records enter the bounded FIFO projection.

| Outcome | Retained historical record | Eligible for active context |
| --- | --- | --- |
| `current_at_recovery_check`: matching source, span, and excerpt | Yes | Yes, subject to context budget |
| `changed`: different source hash | Yes, labeled | No |
| `unavailable`: missing or unsupported source | Yes, labeled | No |
| `excerpt_mismatch`: inconsistent excerpt or span | Yes, labeled | No |

The context budget can evict an earlier recovered projection or truncate a large excerpt. This does not modify the retained original. `recovered` counts source-validated matching records, including those later evicted; it is not the number of active records. Check the report for active IDs and omissions. Matching is a point-in-time check, not a promise that the checkout will remain unchanged.

## Artifacts and limits

| Artifact | Purpose |
| --- | --- |
| `recovery.json` | Origin artifact SHA-256, requested historical records, validation results, and active context |
| `events.jsonl` | Ordered import, validation, and context events |
| `report.md` | Human-readable recovered evidence, current-source status, and budget limitations |

`recovery.json` has its own schema 1 and `artifact_type: "context_recovery"`. Its `origin` records the input path, SHA-256, and investigation schema version; `requested_observation_ids` preserves caller order. Retained observations distinguish `original_validity` from the new `validity`. `context` reports `max_chars`, `characters`, `active`, `evicted_ids`, and omitted IDs with reasons.

The origin hash identifies the imported bytes. It does not prove authorship, authenticity, or that an earlier run really read the source. The importer treats the entire bundle as untrusted data. A forged excerpt that differs from source cannot enter active context, but a matching excerpt is still a source observation rather than a verified diagnosis.

Recovery does not resume a policy, replay a provider request, generate new candidates, or infer whether a task is solved. It does not restore complete source files or any original excerpt content that was never retained. Automatic recovery and evidence expansion remain [M2 work](roadmap.md).

See the [demo](demo.md), [architecture](architecture.md), and [ADR 0003](adr/0003-recovery-and-frozen-comparisons.md).
