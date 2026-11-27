# ADR-0024: AI suggests, never mutates; is computed once off the request path, behind one swappable port

| | |
|---|---|
| Status | Accepted |
| Affects | `integration.mapping`, `integration.conflicts`, `shared.llm`, operator GraphQL/UI |

## In one sentence
Every AI feature in this system (ERP field-mapping proposals, sample-request suggestions,
conflict-cause classification, conflict summaries) is read-only — it can suggest and
explain, but nothing it returns is ever written to an order or an ERP without a human
approving it first — is computed once, at the point data is recorded rather than on every
later read, and is reached through one provider-agnostic port so the underlying model can
change without touching a caller.

## Why this needed a decision

| Problem | Detail |
|---|---|
| An LLM call is slow, costs money, and fails transiently | Confirmed live on this exact system: intermittent DNS failures to a cloud provider's endpoint, ordinary for any external HTTP dependency. A design that calls the model inline on every user-facing read pays that cost and that failure rate on every read, not once. |
| An LLM is wrong sometimes | Any feature that lets a model's output silently become the system's truth — change an order, write an ERP record — turns a wrong guess into a wrong action. The actions this system takes against orders and ERPs are business-significant (shipped goods, invoices, customer-facing status); a bad guess should cost a human a few seconds of review, never an unreviewed mutation. |
| Tying the system to one AI vendor is a real operational risk | A single provider can be unavailable, deprecate a model (confirmed live: an old Claude 3 Haiku model id returned "this model version has reached the end of its life" mid-build), or simply cost more than an alternative later. |
| This was first built without all three of the above in mind | Conflict-cause classification was originally computed live, inside the GraphQL read resolver, cached only in an unbounded in-process dict with no eviction, lost on restart, and not shared across replicas — exactly the failure mode the first problem above describes. Found and fixed in the same change that produced this ADR. |

## The decision

**1. One port, several adapters.** `src/shared/llm/client.py` defines `LlmClient`, a
minimal `ask(system, user) -> str`. Four interchangeable adapters implement it — Bedrock,
Anthropic, Azure Foundry, OpenAI (`src/shared/llm/*.py`) — selected once, by config, in
`composition.py`'s `_llm_client()`. No caller ever imports a cloud SDK directly (enforced
by the "framework-free" import-linter contract); swapping providers is a config change,
not a code change. The port lives in the shared kernel, not inside `mapping` or
`conflicts`, because both modules depend on it — a port two modules share belongs where
both can reach it without one importing the other's internals.

**2. Suggest, never mutate.** Every system prompt in this codebase explicitly forbids the
model from proposing an automatic change (`llm_explainer.py`: *"Do not suggest changing
the order automatically"*), and — more importantly — nothing in the write path ever
executes an AI response as a command. A mapping proposal becomes a real adapter only after
an operator approves it (`MappingService.approve`); a conflict's AI-suggested category is
a label on a read model, never a write to the order or the ERP; a conflict's AI summary is
display-only text. The guarantee is architectural, not a comment: there is no code path
from "the model said X" to "the system did X."

**3. Compute once, off the request path; read cheaply, forever after.** Where an AI call
produces something that gets read repeatedly (a conflict's category), it is computed once
— in `ConflictService.record_failure`, the single write path, not in the GraphQL resolver
that reads it back — and persisted as a plain column. A read that predates the column
existing falls back to the deterministic rule classifier, never a live model call for
history. Where an AI call is inherently on-demand and user-triggered (a conflict's
"explain this" summary), it stays lazy, but its result is cached by a hash of what was
actually asked, not a hand-picked tuple of fields that can drift out of sync with the real
input.

**4. One retry policy, not four copies of one.** `retry_with_backoff` (also in
`shared/llm/client.py`) retries any `LlmClient` call up to three times with exponential
backoff. All four AI call sites share it, so a transient provider failure — which this
exact system has hit live — gets one place to tune, not a silent gap in whichever call
site nobody remembered to copy the loop into.

**5. Never required.** Every feature here degrades to "no AI assist" rather than failing
when no provider is configured (`Unavailable*` classes implementing the same ports) — a
missing API key changes what a screen shows, never whether the system runs.

## Alternatives considered

| Option | Rejected because |
|---|---|
| Call the model inline, synchronously, on every read that needs its output | This was the original conflict-classification design. Confirmed live as the wrong choice: a flaky provider call became a flaky page load, repeated for every viewer, forever, with no persisted result to show for it. |
| Bind directly to one provider's SDK (e.g. `boto3` everywhere) | Works until that provider has an outage, deprecates a model, or a cheaper/better alternative appears — confirmed as a real, not theoretical, risk mid-session (a Bedrock model id reached end-of-life; a Bedrock credential stopped authenticating entirely). The port exists specifically so that's a config change. |
| A per-task model/provider override, so e.g. classification could use a cheaper model than summarisation | Examined directly: all four tasks already default to the same model (Haiku-class) and that model genuinely suits all four (structured one-token classification, short-form summarisation, structured JSON extraction) — adding configuration for a difference that doesn't exist yet is speculative, not a present need. |
| Persist every AI call (model id, prompt version, input hash, output, human accept/reject) as a full audit log | Considered and scoped down: no screen in this product currently has an accept/reject action on an AI suggestion, so there is no "human decision" to persist yet, and a prompt change only ever affects records created after it (the same semantics severity rules already have) — no `prompt_version` is needed to guard against a staleness risk that doesn't exist under the compute-once-at-write design. Revisit if a future screen adds a reviewable AI decision. |

## Consequences

| | |
|---|---|
| ✅ | Conflict-category reads are now a plain column read — no provider latency, no failure mode, on the page that showed both live during this ADR's own testing |
| ✅ | A provider outage or deprecated model is a config/credential fix, never a code change — demonstrated directly: the fix for a dead model id and an unauthenticated credential were both one-line config corrections |
| ✅ | A transient provider failure now self-heals via shared retry instead of surfacing to an operator as "try again in a moment" on the first attempt |
| ✅ | The suggest-never-mutate boundary means an AI regression (wrong classification, bad summary) degrades UX, never correctness of an order or ERP record |
| ⚠️ | There is still no cross-call audit trail (model id/prompt version/outcome) — acceptable today per the alternative above, but revisit the moment any screen gets an accept/reject action on an AI output |
| ⚠️ | `erp-agent-service`'s coding agent (turns an *approved* mapping into real adapter code) is a different, heavier-weight AI capability outside this port — it mutates a git worktree and opens a real PR. It still never merges anything unreviewed (a human merges the PR), so the suggest-never-mutate boundary holds, but it carries its own security surface (documented and hardened separately: authenticated API, environment allowlisted down from the full process environment, Bash allowlisted rather than denylisted) |

## Revisit when
A screen adds a reviewable AI decision (accept/edit/reject a suggested mapping field or
conflict category) — that is the point an audit trail and `prompt_version` tracking
actually pay for themselves, not before.
