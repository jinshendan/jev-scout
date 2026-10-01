# Jev Scout architecture

[English](architecture.md) · [简体中文](architecture.zh-CN.md)

Jev Scout investigates a repository and produces inspectable evidence before a coding agent attempts a change. M1 implements a read-only, offline rule baseline. M2a adds an optional Jev candidate selector; M2b adds explicit evidence recovery and shared-input policy comparisons; M2c adds opt-in, bounded same-file follow-ups. Version 0.4.0 uses Python 3.11+ and the standard library. It does not produce a repair.

The design separates evidence collection, bounded working context, and the policy that chooses what to inspect next. Provider-specific behavior belongs behind a policy adapter; evidence ownership and source attribution stay local.

## Current data flow

```text
task + repository
        |
        v
bounded scan --> inspection candidates
                        |
                        v
               Policy.choose(state, candidates)
                 /                   \
          offline rules       optional Jev Choice
                 \                   /
                  validated decision
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

Candidates identify concrete paths, spans, and expected SHA-256 values. The policy returns a candidate ID, `None` to stop, or a typed `PolicyDecision` with trace metadata. Existing policies returning IDs remain compatible. The investigator validates the selected ID against the current frontier before executing a read.

Discovery ranks filename and content keyword matches once and constructs the initial frontier. The frontier stays fixed by default. With `--max-followups` enabled, a successful hash-matching read allows the local runtime to offer adjacent snippets in that file. The rule policy selects deterministically; Jev uses the task and active context to choose among the current offered IDs. Neither policy can invent paths or coordinates. A separate recovery command projects validated historical observations into context. Cross-file expansion and automatic recovery remain later M2 work. The observations support a handoff for a person or a future solver.

The offline CLI remains:

```sh
scout investigate --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-followups N
```

Add `--policy jev` to enable remote selection. The [Jev policy guide](jev-policy.md) defines configuration, transmitted data, provider contract, and fallback behavior. The implementation and its tests define argument defaults, schema, ranking behavior, and the precise limits applied to scans and reads.

Two additional commands operate at explicit boundaries:

```sh
scout recover --evidence PATH --repo PATH --observation ID --output DIR \
  --max-context-chars N
scout compare --repo PATH --task TEXT --output DIR \
  --max-steps N --max-context-chars N --max-followups N --challenger rule
```

Recovery reads a bounded import and checks requested observations against the explicit repository. Comparison discovers and captures inputs once, then runs independent rule and challenger policies sequentially over the same frozen source. Selecting `--challenger jev` uses the same provider limits and opt-in contract as investigation.

## Implementation map

| Module | Responsibility |
| --- | --- |
| `models.py` | Immutable candidates, task state, context entries, typed policy decisions, result paths |
| `repository.py` | Directory-relative source reads, bounded discovery, lexical ranking, qualified-symbol windows |
| `expansion.py` | Bounded adjacent-window proposals, duplicate suppression, candidate IDs, and parent lineage |
| `investigator.py` | Action loop, source validity, context projection, ordered events, output artifacts |
| `jev.py` | Bounded TypeSafe HTTP requests, closed-choice validation, rule fallback, decision metadata |
| `recovery.py` | Bounded evidence import, source and excerpt revalidation, recovered context and reports |
| `comparison.py` | Shared snapshot capture, independent policy arms, timing, diagnostics, and checkout revalidation |
| `cli.py` | Argument parsing, user-facing errors, and run summary |

The runtime has no third-party dependencies. Jev is replaceable; persistent repository memory and an LLM solver remain future components.

## Boundaries and contracts

| Boundary | Responsibility |
| --- | --- |
| Repository access | Read local content within the source scope; bound scans and reads. |
| Policy | Choose an inspection candidate or stop; expose provider decisions and fallback without owning source reads. |
| Evidence | Preserve observed text and its source identity. Distinguish observations from interpretations. |
| Working context | Select observations within a character budget without destroying retained evidence. |
| Reporting | Present candidates, supporting observations, limitations, and the stopping reason. |

Repository text, task text, comments, and documentation are data. Instructions found in them do not authorize running commands, changing source, or widening access. The rule policy performs no network requests. Explicit Jev selection transmits the task, candidate descriptions, relative paths and previews, and active context to the fixed official TypeSafe endpoint. Source content does not control that endpoint or the permitted actions.

Neither policy builds, tests, or patches investigated source. The investigator requires an output directory outside the repository and refuses to overwrite existing result artifacts.

Safe source reads currently require POSIX directory-relative open and no-follow support. M1 skips symlinks, non-regular files, oversized files, binary content, and non-UTF-8 text. This is a bounded textual baseline; skipped content remains a coverage limitation.

## Evidence and provenance

An observation remains tied to its source path and span. Expected hashes identify the content the investigator intended to inspect; a mismatch prevents the candidate read from becoming an observation. Stored sources are checked again before final reporting, with changed or unavailable sources labeled. This final check is a point-in-time check, not a promise that source files remain unchanged afterward.

The artifacts have complementary roles:

- `events.jsonl` records ordered investigation events, inspectable provider request payloads, decisions, and outcomes.
- `evidence.json` schema 2 contains retained observations, working context, policy configuration, decision traces, and accounting.
- `report.md` presents the investigation and provider/fallback accounting for human review.

Schema 2 extends the M1 handoff with typed decision metadata. Source paths, spans, fingerprints, observed text, and raw read events retain their meaning. Consumers that require schema 1 must explicitly support schema 2 before using new runs.

M2c retains investigation schema 2 and adds `expansion` accounting and `generated_candidate_lineage`. Ordered events identify the parent candidate, successful parent observation, and `before` or `after` direction for generated candidates. Recovery can import these investigation bundles through its existing observation contract.

Decision traces distinguish requested backend from the backend that actually selected an action. Jev traces include requested and returned model identifiers, confidence and probability distribution when valid, nullable provider token usage, elapsed milliseconds, attempted calls, and fallback reasons. Missing usage is unknown, not zero; a timeout can still correspond to provider work that Scout cannot account for.

Credentials, authorization headers, raw provider errors, and exception strings are excluded from artifacts. Request payloads intentionally contain source excerpts. Artifact privacy follows the source being investigated; inspectability does not make private source suitable for publication.

Stored observations are excerpts from an investigation, not a complete archive of the repository. Reading a source file later may return different content. Evidence recovery means inspecting a preserved observation and locating its source. It does not imply automatic run resumption, reproduction of a model answer, or replay of arbitrary tool side effects.

### Recovery provenance

`scout recover` accepts investigation schema 1 or 2, capped at 16 MiB and 100 observations. The import is data, not permission to choose a repository: only `--repo` controls source access. Requested records retain their original text and attribution, and the recovery bundle records the origin artifact's SHA-256.

Recovery checks each requested source through the existing safe-read boundary, then checks its hash, span, and recorded excerpt/truncation against current text. Changed, unavailable, or mismatched excerpts remain visible as historical records but cannot enter active context. Matching records enter the same bounded FIFO context projection used by investigation. The artifact hash links bytes; it does not prove authorship or authenticate the original investigator. See [evidence recovery](evidence-recovery.md).

### Frozen comparison provenance

`scout compare` runs discovery once and captures full text only for files in the retained initial frontier, with a 32 MiB memory cap. Each captured file must match the candidate's expected SHA-256 before either arm starts. Both arms share the task, initial candidates, captured read content, expansion settings, and limits, but receive separate policy state, contexts, and output directories. Follow-ups use those captured files; they cannot introduce a source outside the initial capture. Different prior choices can produce different later candidate menus.

The snapshot ID is a canonical hash of the task, relative candidates, source hashes and byte counts, limits, and implementation version. Absolute roots and timestamps are excluded. Capture is bounded and sequential; it does not claim an atomic whole-repository state or a Git revision.

Full captured source remains in process memory only. The persisted manifest and selected excerpts do not reconstruct unobserved captured content, so later reproduction also requires the original permitted repository revision.

Frozen arm bundles use schema 2 with `source_mode: "frozen"`, a `snapshot_id`, and observation validity `matched_frozen_snapshot`. Observations record `checked_snapshot_sha256` and leave `current_sha256` null. They describe matching captured content, even if the original checkout changes during either arm. After both arms, a separate check labels the checkout's current relationship to captured hashes. A source hyperlink refers to the explicit checkout, which may have changed after capture; the recorded excerpt remains the observed content.

`comparison.json` schema 2 records discovery/capture time, whole-arm time, total comparison time through summary construction, provider accounting, and behavioral diagnostics. Candidate IDs are local to each arm, so action identity uses kind, relative path, expected source hash, start/end lines, and maximum excerpt characters. Same-position agreement and observed-action overlap compare these identities while retaining local IDs for trace lookup. Total time excludes publication of the final summary files. These diagnostics do not measure localization quality, repair success, or savings. Controlled fixture transports are identified separately from real provider calls. See [policy comparisons](policy-comparison.md), [ADR 0003](adr/0003-recovery-and-frozen-comparisons.md), and [ADR 0004](adr/0004-bounded-follow-up-evidence.md).

### Bounded follow-up evidence

`--max-followups` defaults to `0` and accepts integers from 0 through 100. After recording a successful observation, the runtime proposes windows immediately before and after the parent candidate, clipped to the same source file and at most nine lines each. Duplicate candidate identities are suppressed. A generated candidate inherits its parent's expected hash, uses a score of `max(0, parent_score - 1)`, and keeps a preview of at most 240 characters. Each read retains at most 4,000 excerpt characters, so even a nine-line window can be truncated.

The quota counts admitted generated candidates rather than only candidates eventually read. Initial and generated candidates share the global limit of 100. All reads share the existing step budget, and no budget is reset when a candidate is generated. Expansion records generated counts, suppressed proposals, and reached limits. A failed, unavailable, or hash-mismatched read cannot seed follow-ups. Follow-ups preserve the read-only boundary and do not rescan the repository, add files, resume a previous run, or reinsert evicted evidence automatically. See the [follow-up guide](follow-up-evidence.md).

## Bounded context and work

The working-context budget bounds the text selected for the next consumer. It does not promise that every output artifact fits in the same limit. Evidence retention and context inclusion are separate decisions: evicting an observation from working context should not silently discard its retained original.

Step, scan, and read limits bound investigation work. A limit must be visible in the result, with an explicit stopping reason or partial-result limitation. Empty candidates, unreadable files, unsupported content, and incomplete inspection are valid outcomes to disclose; they do not prove that a task has no solution.

Discovery uses bounded directory iteration. When the entry limit is reached, only the enumerated prefix can be ranked; its coverage can depend on filesystem enumeration order. Full, unchanged fixture scans have stable decisions, while a truncated scan is not a cross-platform coverage guarantee. Initial discovery creates one inspection window per matched file. Opt-in adjacent follow-ups can inspect more of that file, but finite offer/step budgets and excerpt truncation still prevent any whole-file coverage guarantee.

A ranking score estimates investigative relevance. It does not certify a diagnosis, identify every necessary file, or predict that a patch will pass tests. M1 does not attach an empirically calibrated correctness probability to a candidate score.

## Remote decision boundary

Jev receives every unseen candidate in one Choice question, described with concrete source metadata. The whole serialized UTF-8 request must fit the configured request-byte cap; otherwise Scout selects by rules without sending it. This preserves candidate coverage instead of hiding a shortlist change inside the adapter. Response bodies also have a fixed byte cap.

Each selection uses at most one HTTP attempt. A separate provider-call budget counts attempts, including failed attempts, per `JevPolicy` instance. The CLI creates one instance per investigation; library callers may share its budget by reusing it. The transport uses the fixed HTTPS endpoint, rejects redirects, and does not inherit proxy settings. Its timeout bounds socket operations rather than guaranteeing a whole-run wall-clock deadline.

Local validation checks the requested question and type, selected frontier ID, distribution keys, finite probabilities and confidence, and probability normalization. A malformed response, provider failure, low confidence, request limit, or exhausted call budget produces an explicit rule fallback. A low-confidence response may still have consumed tokens; its reported usage remains visible. Missing or malformed API keys are setup errors before investigation. A key rejected by the provider produces an authentication-error fallback.

The confidence floor is a configurable control, with a default of `0.0`. It is not an empirically validated reliability threshold. TypeSafe describes confidence as a statistic of distribution concentration; it is distinct from selected-option probability and task success. See the [policy guide](jev-policy.md) and [ADR 0002](adr/0002-typed-jev-decisions.md).

## Errors and recovery

Keep successful observations when a later inspection fails. Disclose the affected source or action rather than presenting an empty success. A partial result should expose gaps so a later investigator can broaden its search. Fatal setup or artifact-write errors must remain distinguishable from a completed investigation with no useful candidates.

Explicit recovery supports rebuilding a context from retained observation IDs, and optional follow-ups support bounded same-file expansion. Later M2 work should support policy-requested recovery, cross-file evidence expansion, and live provider validation. A future solver should be able to request additional evidence or inspect elsewhere. Restricting a solver to an incomplete candidate set can turn a recoverable localization miss into an unavoidable repair failure.

## Language and cache limitations

M1 treats code as text and extracts ASCII identifier-like keywords from task text. A task without matching keywords can produce no candidates. It does not resolve C++ types, overloads, macros, conditional compilation, template instantiation, or build configurations. Textual relationships are search hints, not a compiler-derived call graph. Compiler semantics and build metadata require a separately scoped extension.

Evaluate this local baseline separately from future model and prompt caches. Warm repository indexes, operating-system caches, model-prefix caches, and previously constructed repository memory are different conditions. Future persistent evidence or summaries must carry revision identity, detect staleness, and fall back to current source inspection.

## Design grounding

Compact repository context has direct precedents. [Aider's repository map](https://aider.chat/docs/repomap.html) demonstrates budgeted structural context. [The Complexity Trap](https://github.com/JetBrains-Research/the-complexity-trap) motivates comparison with simple observation masking. [Cost-Effective Repository Exploration](https://arxiv.org/abs/2608.29675) motivates a measurable exploration boundary and recoverable candidate handoff. Jev Scout's value must be established by evaluation, not inferred from those results.
