# Investigating a cancellation path

[English](demo.md) · [简体中文](demo.zh-CN.md)

This walkthrough uses `examples/cancellation`, a fictional C++ source tree, to
demonstrate Jev Scout's first milestone: read-only repository search and recorded
source evidence. It does not compile the example, execute a callback, reproduce
a defect, determine a root cause, or propose a verified fix.

## Run an investigation

After installing Jev Scout as described in the repository README, run this from
the repository root:

```sh
scout investigate \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/demo \
  --max-steps 6 \
  --max-context-chars 1200
```

The supplied question names a concrete symbol. The rule-based investigator can
use that name and related text to locate source candidates. No Jev API key is
needed for the rule-based first milestone.

Read the three generated files in `.scout/demo`:

- `report.md`: the human-readable investigation report.
- `evidence.json`: the recorded source evidence.
- `events.jsonl`: the investigation event log.

Open each cited source file at its recorded line and check the surrounding code.
File matches are investigation leads; they are not a computed C++ call graph.

For a broader follow-up, use the exact symbol names in
`examples/cancellation/task.txt`: `Request::queue_completion`, `Queue::enqueue`,
`Queue::remove_for`, and `Queue::dispatch_one`. A short initial search may not
include every relevant path. Expand the question or examine the neighboring
definitions when a link is missing.

Use `--max-steps N` and `--max-context-chars N` to bound an investigation. A
budget limit can stop evidence collection before all useful source is inspected;
it should not be read as evidence that a missing path does not exist.

Use fresh output directories outside `examples/cancellation` for every command.
If `.scout/demo` already exists from an earlier run, choose a new name and use
that name in the recovery command below.

## Recover a retained observation

Find an observation ID in the generated `evidence.json`, then request it
explicitly. The first recorded observation normally has ID `o0001`:

```sh
scout recover \
  --evidence .scout/demo/evidence.json \
  --repo examples/cancellation \
  --observation o0001 \
  --output .scout/recovery \
  --max-context-chars 1200
```

Read `.scout/recovery/report.md` and `recovery.json`. Recovery retains the
requested original excerpt and checks it against current source before placing
it in bounded context. It can recover a context-evicted record; it does not
continue the original run. Repeat `--observation` for additional IDs. The
[recovery guide](evidence-recovery.md) explains stale and mismatched records.

## Compare on the same captured inputs

Run the offline sanity comparison:

```sh
scout compare \
  --repo examples/cancellation \
  --task 'Investigate whether Request::cancel removes queued callbacks.' \
  --output .scout/comparison \
  --max-steps 6 \
  --max-context-chars 1200
```

The default challenger is another fresh rule policy. Both arms use one captured
candidate frontier and source content. Inspect `comparison.json`, the top-level
`report.md`, and the normal evidence bundles under `rule/` and `challenger/`.
Frozen observations describe captured content; a separate checkout check shows
whether the original files still match afterward.

Identical rule decisions are a sanity check, not a quality or cost result.
`--challenger jev` explicitly enables TypeSafe source transmission and requires
an environment key. See the [comparison guide](policy-comparison.md) before
running it on private source. No live Jev benefit is established by this demo.

## Read the evidence

The source provides these manual inspection targets. The actual report's
ranking and included excerpts depend on the investigator and its limits.

| Target | What to inspect | What the source alone does not establish |
| --- | --- | --- |
| `request.cpp`: `Request::cancel` | The write to `cancelled_`; whether this body calls a queue removal method | The intended cancellation contract |
| `request.cpp`: `Request::queue_completion` | `weak_request`, `lock()`, and the cancellation check in the stored closure | The lifetime and synchronization rules of a real application |
| `queue.cpp`: `Queue::enqueue` | The entry stored in `callbacks_` | Which application paths enqueue work |
| `queue.cpp`: `Queue::remove_for` | The owner-based erase operation | Whether all callers use it appropriately |
| `queue.cpp`: `Queue::dispatch_one` | The pop before `entry.callback()` | Runtime scheduling or concurrent interleavings |
| `call_site.cpp` | The queue-then-cancel source scenario | A reproduced failure or an executed assertion |

Keep two questions separate: whether a queued entry is removed during cancel,
and whether its `on_complete` callback can run after cancel. A dispatch-time
guard can affect the second question without removing the entry during cancel.
An investigation should preserve the source citations behind each observation
and leave unresolved questions explicit.

Scout's first milestone records text evidence. It cannot prove that a symbol
resolves to a particular overload, that a source path executes, that a callback
has a use-after-free, or that cancellation is thread-safe. The fictional example
is single-threaded and does not contain a claimed memory-safety defect.

## Planned validation beyond the first milestone

Future investigation capabilities may add a compiler-backed symbol index and
clangd cross-references using a real `compile_commands.json`. Before drawing
behavioral conclusions, a project would need a build target, tests asserting its
chosen cancellation contract, and executed scenarios covering callback ownership
and request destruction. AddressSanitizer and UndefinedBehaviorSanitizer could
then help check those scenarios; ThreadSanitizer would be relevant only after a
concurrent design and tests exist.

Those capabilities and checks are future work. This walkthrough does not report
a compilation result, sanitizer result, bug reproduction, or coding benchmark.
