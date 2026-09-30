# Cancellation source investigation

This is a fictional, small C++ source tree for trying Jev Scout's read-only search
and evidence workflow. It is not a validated bug reproduction, a benchmark, or
an example of production cancellation code. The files use C++17 constructs, but
this repository does not provide a build target and the demo workflow does not
compile or run them.

The investigation question is:

> Investigate whether Request::cancel removes queued callbacks.

The source offers several related paths to inspect:

- `Request::queue_completion` captures a weak reference and enqueues a callback.
- `Request::cancel` changes a cancellation flag.
- `Queue::remove_for` is a separate operation for erasing pending queue entries.
- `Queue::dispatch_one` removes one entry before invoking its stored callback.
- `call_site.cpp` contains a queue-then-cancel source-reading scenario.

The distinction between an entry remaining queued and its completion callback
being skipped matters. A matching method name, an unused removal function, or a
cancellation flag does not establish a defect. Intended cancellation semantics,
caller lifetime requirements, concurrency, and runtime behavior still require
validation. The example intentionally has no threading or synchronization model.

From the Jev Scout repository root, run:

```sh
scout investigate --repo examples/cancellation --task 'Investigate whether Request::cancel removes queued callbacks.' --output .scout/demo
```

Inspect `.scout/demo/report.md`, `evidence.json`, and `events.jsonl` alongside the
source. `task.txt` offers additional exact symbol names for a more detailed
investigation. See `docs/demo.md` in the Jev Scout repository for the walkthrough
and its evidence limits.
