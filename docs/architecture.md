# Jev Scout architecture

Jev Scout investigates a repository and produces inspectable evidence before a coding agent attempts a change. M1 implements the accepted evidence contract as a read-only, offline, deterministic rule baseline in Python 3.11+ using the standard library. It does not call a language model or produce a repair.

The design separates evidence collection, bounded working context, and the policy that chooses what to inspect next. Provider-specific behavior belongs behind a future policy adapter, not in evidence ownership or source attribution.

## M1 data flow

```text
task + repository
        |
        v
bounded scan --> inspection candidates
                        |
                        v
               Policy.choose(state, candidates)
                        |
                        v
               bounded source inspection
                        |
                        v
             evidence + ordered events
                        |
                        v
               bounded working context
                        |
                        v
            events.jsonl / evidence.json / report.md
```

Candidates identify concrete paths, spans, and expected SHA-256 values. The policy returns a candidate ID or `None` to stop. M1 ranks filename and content keyword matches once, then selects bounded excerpts from that fixed frontier. It does not generate new queries or update ranking from observations. Adaptive search is a later extension. The selected observations support a handoff for a person or a future solver.

The first milestone's CLI is:

```sh
scout investigate --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N
```

The implementation and its tests define argument defaults, schema, ranking behavior, and the precise limits applied to scans and reads.

## Implementation map

| Module | Responsibility |
| --- | --- |
| `models.py` | Immutable candidates, task state, context entries, policy interface, result paths |
| `repository.py` | Directory-relative source reads, bounded discovery, lexical ranking, qualified-symbol windows |
| `investigator.py` | Action loop, source validity, context projection, ordered events, output artifacts |
| `cli.py` | Argument parsing, user-facing errors, and run summary |

The runtime has no third-party dependencies. Provider adapters and persistent repository memory remain outside M1.

## Boundaries and contracts

| Boundary | Responsibility |
| --- | --- |
| Repository access | Read local content within the source scope; bound scans and reads. |
| Policy | Choose an inspection candidate or stop. Model-driven policy is planned, not part of M1. |
| Evidence | Preserve observed text and its source identity. Distinguish observations from interpretations. |
| Working context | Select observations within a character budget without destroying retained evidence. |
| Reporting | Present candidates, supporting observations, limitations, and the stopping reason. |

Repository text, task text, comments, and documentation are data. Instructions found in them do not authorize running commands, changing source, or widening access. M1 performs no network requests and no build, test, or patch actions. It requires an output directory outside the repository and refuses to overwrite existing result artifacts.

Safe source reads currently require POSIX directory-relative open and no-follow support. M1 skips symlinks, non-regular files, oversized files, binary content, and non-UTF-8 text. This is a bounded textual baseline; skipped content remains a coverage limitation.

## Evidence and provenance

An observation remains tied to its source path and span. Expected hashes identify the content the investigator intended to inspect; a mismatch prevents the candidate read from becoming an observation. Stored sources are checked again before final reporting, with changed or unavailable sources labeled. This final check is a point-in-time check, not a promise that source files remain unchanged afterward.

The artifacts have complementary roles:

- `events.jsonl` records ordered investigation events and outcomes.
- `evidence.json` contains retained observations and the selected working context.
- `report.md` presents the investigation for human review.

Stored observations are excerpts from an investigation, not a complete archive of the repository. Reading a source file later may return different content. Evidence recovery means inspecting a preserved observation and locating its source. It does not imply automatic run resumption, reproduction of a model answer, or replay of arbitrary tool side effects.

## Bounded context and work

The working-context budget bounds the text selected for the next consumer. It does not promise that every output artifact fits in the same limit. Evidence retention and context inclusion are separate decisions: evicting an observation from working context should not silently discard its retained original.

Step, scan, and read limits bound investigation work. A limit must be visible in the result, with an explicit stopping reason or partial-result limitation. Empty candidates, unreadable files, unsupported content, and incomplete inspection are valid outcomes to disclose; they do not prove that a task has no solution.

Discovery uses bounded directory iteration. When the entry limit is reached, only the enumerated prefix can be ranked; its coverage can depend on filesystem enumeration order. Full, unchanged fixture scans have stable decisions, while a truncated scan is not a cross-platform coverage guarantee. M1 creates one inspection window per matched file, so reading a file does not establish that all its relevant functions were inspected.

A ranking score estimates investigative relevance. It does not certify a diagnosis, identify every necessary file, or predict that a patch will pass tests. M1 does not attach an empirically calibrated correctness probability to a candidate score.

## Errors and recovery

Keep successful observations when a later inspection fails. Disclose the affected source or action rather than presenting an empty success. A partial result should expose gaps so a later investigator can broaden its search. Fatal setup or artifact-write errors must remain distinguishable from a completed investigation with no useful candidates.

Future Jev integration should use a recoverable handoff: suggested files guide the solver while the solver can request additional evidence or inspect elsewhere. Restricting a solver to an incomplete candidate set can turn a recoverable localization miss into an unavoidable repair failure.

## Language and cache limitations

M1 treats code as text and extracts ASCII identifier-like keywords from task text. A task without matching keywords can produce no candidates. It does not resolve C++ types, overloads, macros, conditional compilation, template instantiation, or build configurations. Textual relationships are search hints, not a compiler-derived call graph. Compiler semantics and build metadata require a separately scoped extension.

Evaluate this local baseline separately from future model and prompt caches. Warm repository indexes, operating-system caches, model-prefix caches, and previously constructed repository memory are different conditions. Future persistent evidence or summaries must carry revision identity, detect staleness, and fall back to current source inspection.

## Design grounding

Compact repository context has direct precedents. [Aider's repository map](https://aider.chat/docs/repomap.html) demonstrates budgeted structural context. [The Complexity Trap](https://github.com/JetBrains-Research/the-complexity-trap) motivates comparison with simple observation masking. [Cost-Effective Repository Exploration](https://arxiv.org/abs/2608.29675) motivates a measurable exploration boundary and recoverable candidate handoff. Jev Scout's value must be established by evaluation, not inferred from those results.
