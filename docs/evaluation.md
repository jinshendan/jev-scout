# Jev Scout evaluation protocol

Evaluation distinguishes an investigation artifact from end-to-end repair. M1 establishes a deterministic rule baseline. It has no measured repair rate, API-cost reduction, or calibrated probability of correctness.

## M1 checks

Use local fixture repositories with known text, unrelated files, repeated symbols, missing matches, unsupported content, and bounded excerpts. Check:

- Deterministic decisions and selected evidence for the same task, repository content, configuration, and implementation version.
- Source attribution and consistency across events, evidence, and report.
- Recovery of retained observations evicted from working context.
- Context, scan, read, and step limits, including boundary values and explicit stopping reasons.
- Repository access boundaries and disclosed errors or incomplete results.

Timestamps and other run metadata may differ between repeated runs. Compare meaningful investigation content, not byte-for-byte identity of every artifact. M1 requires output outside the source repository. Use fresh output directories when checking that investigation leaves source content unchanged.

Treat a truncated discovery frontier separately: filesystem enumeration order can affect which entries enter a bounded prefix. A selected file provides one bounded window in M1, so file coverage must not be confused with symbol or causal-chain coverage.

These checks verify implementation contracts. They do not establish candidate accuracy on real issues.

## M2b recovery and shared-input checks

Recovery checks import bounds and schema validation, explicit source scope, preserved historical text, and separation of retained evidence from active context. Exercise current, changed, unavailable, malformed-span, and excerpt-mismatch records. Confirm that a small context budget can evict or truncate a recovered projection while retaining the requested original record. The origin artifact hash links the input bytes; it does not authenticate them.

The comparison harness creates a bounded frozen input before either arm starts. Use an offline rule-versus-rule run as a sanity check, then controlled injected policies to test differing choices, fallback, unknown usage, and source mutation during an arm. Injected transports are implementation fixtures and must be labeled as such; they are not live Jev experiments.

Check that both arms receive identical task text, candidate frontier, expected source hashes, captured read content, and budgets. They have fresh policy state and separate contexts. A changed checkout must not change an arm's observed snapshot text or appear as `current_at_final_check` in frozen evidence. Recheck the original checkout separately after both arms.

Record the snapshot manifest and ID, discovery/capture limits, exclusions, source mode, implementation version, requested and actual backends, provider attempts, fallback reasons, and reported or unknown usage. Capture is sequential and bounded; it does not identify an atomic repository state. Snapshot IDs exclude absolute roots and timestamps, so equivalent relocated fixtures can be compared without asserting byte-identical run metadata.

The current harness reports same-position action agreement and observed-candidate overlap. These diagnose policy behavior. High agreement can reflect identical rules or repeated fallback; low agreement can reflect useful or harmful choices. Neither is a correctness, localization-quality, repair-success, or savings metric. Recovery is a separate command and is not a treatment inside the current comparison.

Discovery/capture time, whole-arm time, and total comparison time through summary construction are reported separately. Total time includes output preparation and checkout revalidation and excludes publication of the final comparison summary files. Arms run sequentially, so ordering, OS caches, and provider load may affect latency. Shared capture cost is paid once by this harness; report the accounting convention before deriving per-arm cost. Preserve unknown provider usage rather than treating a failed call as free. Without live calls, prices, and task outcomes, the harness cannot establish monetary savings.

Use the [comparison guide](policy-comparison.md) for artifacts and opt-in behavior. Credentialed provider validation and a disclosed real task set remain M2 work; the fixed repair solver and executable success oracle remain M3 work.

## Frozen end-to-end track — planned for M3

Pin repository revisions, dataset revision and instance IDs, container digests, model versions, prompts, tool configuration, pricing date, random seeds, timeout rules, and total budgets. Keep the solver fixed when comparing investigation methods. Each arm receives the same permitted task information.

For SWE-style tasks, the agent receives the permitted problem statement and pre-fix repository environment. Do not expose the gold patch, test patch, hidden tests, evaluator results, or future solution discussions during the rollout. Evaluate the submitted patch after the agent finishes; do not use the hidden evaluator as an iterative repair tool. Preserve benchmark-specific rules on hints and environment access.

Use reference-patch and unchanged-snapshot checks to confirm that the environment and test oracle work before accepting tasks into the evaluation set. Report infrastructure failures separately, with exclusion criteria fixed before comparing methods. Do not remove tasks simply because one arm fails to solve them.

### Baselines and ablations

Use an inspectable agent such as [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), with fixed solver and tool access. Compare:

| Arm | Purpose |
| --- | --- |
| Ordinary search, original history | Establish the existing agent's behavior. |
| Ordinary search, observation masking | Compare with a strong simple context baseline. |
| Ordinary search, model summary | Include summarization cost and information loss. |
| M1 rules plus evidence handoff | Measure deterministic investigation without a model explorer. |
| Model policy plus the same evidence handoff | Isolate investigation policy from artifact representation. |

Later, vary retrieval, memory, and allocation independently before measuring combinations. Compare fixed strong-model allocation, fixed lower-cost exploration, and conditional escalation. Hold overall budgets constant and also publish budget sweeps. Compare recoverable handoffs with restrictive file gates explicitly; do not silently change solver access between arms.

The [observation-masking study](https://github.com/JetBrains-Research/the-complexity-trap) and [explorer allocation study](https://arxiv.org/abs/2608.29675) motivate these baselines; their results are not evidence of Scout's performance.

### Outcomes and accounting

Report resolved rate against the benchmark's executable oracle, including issue-specific fail-to-pass and regression pass-to-pass tests where required. Add localization measures such as Hit@k and file recall as diagnostics. Historical gold-file sets are repair footprints, not proof that every touched file is necessary or that another valid fix must touch the same set.

Record per instance:

- Total pipeline cost, including investigation, solver, routing, summaries, embeddings, indexing, cache writes, retries, and unsuccessful attempts.
- Provider-reported input, cached input, output, and billed reasoning tokens where available; distinguish these from logical prompt length.
- Total elapsed time, investigation time, solver time, steps, and timeout reason; report p50 and p95 latency.
- Selected context size, retained evidence size, candidate coverage, and additional evidence requested after handoff.
- Final outcome and a supported failure category.

Cost per solved task is total cost across **all** evaluated attempts divided by the number of solved tasks. It is not the mean cost of successful runs. If none are solved, report total expenditure and the undefined ratio. For local inference, report hardware and runtime configuration alongside an explicit cost model.

Separate cold and warm runs. A warm repository index, filesystem cache, model-prefix cache, and reused memory are distinct conditions. Compression can shorten a prompt while disrupting prefix-cache reuse. Measure actual billed usage when available; label estimates. Report parallel branches by both critical-path elapsed time and aggregate resource consumption.

Use paired instance comparisons and confidence intervals. Include repository-clustered sensitivity analysis so many issues from one project do not imply broad transfer. Repeat stochastic arms with disclosed seeds. Keep tuning tasks and repositories separate from the final test set.

### Failure attribution

Distinguish setup or infrastructure errors, missed localization, misleading or stale evidence, incomplete handoff, patch-generation errors, regression failures, and budget exhaustion. Preserve supporting traces. A failure may have multiple causes; do not force a single category without evidence.

A small diagnostic run with oracle file hints can test whether better localization would help a fixed solver. Label it as oracle analysis and exclude it from normal scores. A solver failing after a useful handoff differs from an investigator failing to find that handoff.

## C++ coverage

[SWE-bench Multilingual](https://www.swebench.com/multilingual.html) contains 300 tasks across nine languages, but only 12 C++ tasks from two repositories. It supports a smoke test, not a broad C++ claim. The currently published [SWE-bench-Live/MultiLang data card](https://huggingface.co/datasets/SWE-bench-Live/MultiLang/blob/main/README.md) lists 142 C++ tasks; pin a revision because this dataset evolves.

Report compiler, standard-library, build-system, and configuration details. Separate textual localization quality, compiler semantics, and repair success. Include cross-file tasks and varied repositories; task difficulty, repository mix, and build failures can explain apparent language differences.

## Chronological memory track — planned for M4

Evaluate tasks in a disclosed temporal order. Memory may contain only information legitimately available before the current task; exclude future commits, linked solution material, and overlapping evaluation instances. Record revision ancestry and memory updates, not timestamps alone. Do not seed memory with the task's patch or hidden tests.

Compare no memory, repository summaries, and evidence-backed memory; stress stale, contradictory, sparse, and irrelevant entries. Report construction, refresh, retrieval, and maintenance cost separately, then amortize over explicit task counts. Keep this track separate from single-task leaderboards to avoid an unfair warm-start advantage.

## Offline replay limits

Fixed trajectories support inspection, schema checks, context-size comparisons, candidate rescoring, and labeled cost estimates. They cannot establish how different context or model choices affect the next action: altered observations can change every subsequent search, edit, and retry. Claims about resolved rate, adaptive routing, or real latency require new rollouts in the pinned environment.
