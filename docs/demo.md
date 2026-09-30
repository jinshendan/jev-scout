# Investigating a cancellation path

This walkthrough uses `examples/cancellation`, a fictional C++ source tree, to
demonstrate Jev Scout's first milestone: read-only repository search and recorded
source evidence. It does not compile the example, execute a callback, reproduce
a defect, determine a root cause, or propose a verified fix.

## Run an investigation

The executable CLI is delivered in the M1 implementation PR. Until it is merged,
use the `feat/local-evidence-baseline` branch and its installation instructions.

After installing Jev Scout as described in the repository README, run this from
the repository root:

```sh
scout investigate --repo examples/cancellation --task 'Investigate whether Request::cancel removes queued callbacks.' --output .scout/demo
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
