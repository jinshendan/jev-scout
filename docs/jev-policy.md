# Optional Jev candidate selection

M2a adds a Jev policy to the existing read-only investigator. The default remains `--policy rule`, which runs offline without credentials. Jev selects an existing candidate ID; the runtime owns every read, budget, and retained observation.

The adapter is available on `main`, delivered in [PR #6](https://github.com/jinshendan/jev-scout/pull/6) on top of the [M1 baseline](https://github.com/jinshendan/jev-scout/pull/5). Controlled HTTP fixtures validate our contract and failure paths. M2b adds a [frozen-input comparison harness](policy-comparison.md) and [explicit evidence recovery](evidence-recovery.md). M2c adds [opt-in same-file follow-ups](follow-up-evidence.md); the provider continues to select only IDs offered by the local runtime. An authenticated live-provider run and a policy-quality comparison have not been performed.

## Enable the policy

Set `TYPESAFE_API_KEY` in your shell environment or secret manager. This is the environment variable used by the [official TypeSafe SDK](https://docs.typesafe.ai/sdk/python/api/constants). Scout does not accept a key on the command line or write it into artifacts.

```sh
scout investigate \
  --repo examples/cancellation \
  --task "Investigate whether Request::cancel removes queued callbacks." \
  --output .scout/jev-demo \
  --policy jev \
  --jev-model jev-1.13.0 \
  --jev-min-confidence 0.0 \
  --jev-max-calls 8 \
  --jev-timeout 10 \
  --jev-max-request-bytes 65536
```

Use a fresh output directory outside the investigated repository. Missing or malformed API keys are a setup error before investigation. A key rejected by the provider produces an authentication-error fallback. Jev configuration flags require `--policy jev`; supplying them to a rule run is also a setup error.

| Option | Default | Meaning |
| --- | --- | --- |
| `--policy` | `rule` | `rule` for offline selection; `jev` for explicit remote opt-in |
| `--jev-model` | `jev-1.13.0` | Requested model ID; pin versions for comparable experiments |
| `--jev-min-confidence` | `0.0` | Minimum accepted provider confidence in the range 0–1 |
| `--jev-max-calls` | `8` | Maximum provider attempts in the investigation |
| `--jev-timeout` | `10` | Socket-operation timeout in seconds |
| `--jev-max-request-bytes` | `65536` | Maximum size of the complete serialized UTF-8 request |

Response bodies are limited to 65,536 bytes. These byte limits are not token counts or monetary budgets. Provider calls and source-read steps are separate budgets. The CLI creates one `JevPolicy` per run; library callers that reuse an instance share its remaining call budget across investigations. There are no automatic retries; one selection makes at most one attempt. The socket timeout does not guarantee a total investigation deadline.

## Transmitted and retained data

**Selecting `--policy jev` sends source context to TypeSafe AI.** Each attempted decision request contains the task, all unseen candidate descriptions with relative paths and previews, and active context excerpts. Attempted request payloads are retained in local artifacts so a reviewer can inspect what was sent.

Candidate descriptions contain concrete paths, spans, lexical scores, relevance reasons, and previews. The provider cannot invent paths, commands, or queries. The absolute repository root is excluded from the provider request. Treat source text and comments as data rather than permission to change the action boundary.

With `--max-followups N` enabled on `investigate` or `compare`, a successful hash-matching read can add locally generated adjacent windows in the same file. The next Jev request includes all unseen offered IDs, including these follow-ups and their descriptions. The generated-offer quota, total-candidate cap, step budget, provider-call budget, and request-byte cap remain separate; adding follow-ups grants no additional provider calls or source-read steps. The default `0` preserves the fixed initial frontier. See the [follow-up guide](follow-up-evidence.md).

Keep generated artifacts private when the investigated source is private. API keys, authorization headers, raw provider error bodies, and exception strings are excluded from artifacts.

The transport calls the fixed official HTTPS endpoint, rejects redirects, and does not inherit proxy settings. M2a has no configurable gateway route.

## Official API contract

Scout uses `POST https://api.typesafe.ai/v1/systemone`, authenticated with a TypeSafe Bearer key. The body contains `model`, structured `state`, and a named Choice question under `questions`. Its `criteria` map uses the frontier's candidate IDs as keys and their descriptions as values. These are the documented [official request fields](https://docs.typesafe.ai/api), rather than a chat-completion interface.

The response contains a matching `answers` entry with `type`, `choice`, `confidence`, and `probabilities`, plus the returned model identifier and usage. The selected choice should be a highest-probability option, and the distribution covers the supplied criteria. Local code validates the closed set before using a selection. See [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice).

The HTTP reference describes usage as integer counts, while the [official SDK response schema](https://docs.typesafe.ai/sdk/python/api/types/responses) allows missing or null counts. Scout preserves unknown counts as null. It validates reported counts instead of converting missing data to zero.

The default model is pinned to `jev-1.13.0`. The provider also documents moving aliases such as `jev-latest`; runs record both the requested and returned identifiers. A pinned request requires the matching response version; an alias requires a concrete returned Jev version. See [TypeSafe models](https://docs.typesafe.ai/models).

## Local validation and fallback

Scout accepts only the expected question and answer type, a current unseen candidate ID, and a complete probability distribution over the supplied candidates. Probabilities and confidence must be finite and within 0–1, probabilities must sum approximately to 1, and the selected option must be a maximum. Unknown choices cannot introduce new source actions.

The complete request must fit the byte cap before sending. If it does not, the rule policy selects from the same frontier; Scout does not truncate the candidate list to make the model request fit. This keeps a request limit distinct from a candidate-coverage change.

| Condition | Result |
| --- | --- |
| Missing or malformed API key | Setup error; no investigation or provider attempt |
| Request byte limit or exhausted call budget | Rule fallback without another provider attempt |
| Timeout, connection failure, non-success status, redirect, oversized or invalid response | Recorded attempt and rule fallback |
| Valid response below the confidence floor | Preserve available response metadata and usage, then use rules |
| Valid response meeting the floor | Use the selected candidate after local validation |

The provider documents authentication and validation errors, rate limits, and overload responses. Although its SDK recommends retries for transient failures, Scout's M2a adapter deliberately performs no automatic retries so attempts and fallback stay bounded and inspectable.

## Traces and accounting

Schema 2 extends `evidence.json` with `policy_config`, `decisions`, and `policy_accounting` while retaining source observations and bounded working context. `events.jsonl` preserves raw read events and records inspectable attempted decision payloads. `report.md` summarizes policy use alongside the evidence and coverage limits.

Each decision records `step`, `candidate_id`, `backend`, `fallback_reason`, and `attempts`. An attempt records `request`, `elapsed_ms`, `outcome`, `http_status`, `response_model`, nullable `input_tokens` and `output_tokens`, and validated `choice`, `confidence`, and `probabilities` where available. The requested model is in the retained request and policy configuration. The decision backend identifies who actually selected the action.

`policy_accounting` reports decision and backend counts, fallback decisions, provider attempts and latency, reported input/output token sums, and the number of attempts with unknown usage. An entirely offline run has no provider attempts or unknown provider usage; reported token sums of zero describe those absent calls.

Policy configuration records `transport: "http"` for the official adapter or `"injected"` for a supplied test transport. Comparisons keep this distinction visible; a controlled fixture is not live-provider validation.

Failed attempts can consume provider resources even when no usage is returned. Accounting reports what the provider disclosed; it does not establish an exact cost for timed-out calls or substitute zero for unknown usage. A fallback run should not be described as a successful Jev-selected investigation merely because `--policy jev` was requested.

## Confidence and remaining work

TypeSafe describes confidence as a statistic of how concentrated the answer's probability distribution is. It differs from the selected option's probability. Neither quantity establishes the probability of completing a repository task. The provider does not publish the exact confidence computation on its [confidence page](https://docs.typesafe.ai/confidence).

The default floor of `0.0` permits every locally valid distribution. It is a starting configuration, not an empirically validated reliability threshold. Compare thresholds against task outcomes before drawing quality conclusions.

M2a changes selection within a fixed lexical frontier. M2b provides manual recovery and shared-input comparison mechanics. M2c optionally offers bounded neighboring candidates while keeping selection within locally validated actions. Cross-file expansion, automatic recovery, and credentialed comparisons remain [M2 work](roadmap.md). Root-cause verification, downstream repair, and chronological memory belong to later milestones; the current investigator does not execute or edit source.
