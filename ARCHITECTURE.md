# Architecture

This document explains how the system is put together, why it's put
together that way, the trade-offs made along the way, and how it would
need to evolve to handle 10x the load. For the I/O contract of each
individual component, see `COMPONENT_CONTRACTS.md`. For per-test-case
behaviour and edge cases, see `EVAL_REPORT.md`.

---

## 1. High-level shape

The system is a single linear pipeline (`run_claim_pipeline` in
`app/orchestrator/pipeline.py`) over a shared, mutable `ClaimContext`
object. Each stage is a small, single-responsibility component that
reads from and writes to that context, and appends entries to an ordered
`trace` list as it goes. The trace *is* the explainability deliverable --
nothing is hidden inside a stage's internal state.


```

ClaimSubmission
|
v
+----------------------------+
| Stage 0: Document          |  infers actual_type for live uploads
| Classification             |  (no-op when eval harness supplies it)
+----------------------------+
|
v
+----------------------------+
| Stage 1: Document          |  readability -> required types ->
| Verification (can BLOCK)   |  patient-identity consistency
+----------------------------+
|  (blocked? return immediately)
v
+----------------------------+
| Stage 2: Extraction        |  passthrough (eval) or Gemini (live);
|                            |  per-document confidence + status
+----------------------------+
|
v
+----------------------------+
| Stage 3: Rules Engine      |  eligibility -> waiting period ->
| (deterministic, pure function)|  exclusions -> pre-auth -> limits ->
|                            |  coverage calculation
+----------------------------+
|
v
+----------------------------+
| Stage 4: Fraud Detection   |  same-day / monthly claim counts,
|                            |  high-value threshold
+----------------------------+
|
v
+----------------------------+
| Stage 5: Decision Synthesis|  combines everything into
|                            |  ClaimDecision + confidence_score
+----------------------------+
|
v
ClaimContext (decision + full trace) -> API response

```

Two structural choices anchor everything else:

1. **The rules engine is deterministic and LLM-free.** It is plain
   Python reading `data/policy_terms.json`. Given the same
   `ClaimContext`, it always produces the same `RulesEvaluationResult`.
2. **Every agent has a uniform failure boundary** (`BaseAgent.run_safe`).
   A stage can throw; the pipeline never does. Failures become trace
   entries with confidence penalties, not exceptions or 500s.

---

## 2. Why a single shared `ClaimContext` instead of message-passing agents?

An alternative design would have each agent communicate via discrete
messages/events (more "agentic", closer to a multi-agent framework like
AutoGen or CrewAI). We chose a shared mutable context instead because:

- **The data dependencies are linear and well-known up front.** Stage 3
  needs the output of Stage 2; Stage 5 needs the output of Stages 3 and
  4. There's no need for agents to negotiate, re-plan, or call each other
  dynamically -- this isn't a "the model decides what to do next"
  problem, it's a fixed audit checklist.
- **Explainability is simpler with one trace.** If each agent maintained
  its own log and the orchestrator had to merge them, ordering and
  causality (e.g. "extraction confidence fed into this fraud signal")
  would be harder to present coherently.
- **It's trivially testable.** Every agent's `run(ctx)` is a pure-ish
  function: build a `ClaimContext`, call `run_safe`, assert on the
  returned context. No mocking of an inter-agent message bus is needed.

The trade-off: this design doesn't generalize to a scenario where the
*set* or *order* of checks needs to be decided dynamically (e.g. "if this
is a maternity claim, also run these three extra checks in a different
order"). For this assignment's scope -- a fixed claim-adjudication
checklist -- that flexibility isn't needed. If it became needed, the
rules engine's `evaluate()` function is the natural seam: it could be
replaced with a small planner that selects which check modules to run
based on `claim_category`, while keeping the same `RulesEvaluationResult`
contract.

---

## 3. Why is the rules engine deterministic, not LLM-based?

Insurance adjudication has three properties that make determinism the
right default:

- **Auditability.** A rejected claim must be explainable with a specific
  policy clause and a specific number (e.g. "waiting period ends
  2024-11-30" or "exceeds the Rs.5,000 per-claim limit"). An LLM can
  *describe* this convincingly even when it's wrong; a deterministic
  function reading `policy_terms.json` cannot drift from the configured
  policy.
- **Reproducibility.** Re-running the same claim through the pipeline
  must produce the same decision, every time, including in unit tests
  and CI. LLM calls are non-deterministic by default (and rate-limited,
  slow, and costly to call for every rule check).
- **Policy changes are config changes, not code or prompt changes.**
  Every limit, percentage, exclusion, and waiting period lives in
  `data/policy_terms.json` (see `app/policy_loader.py` and
  `app/models/policy.py`, which provide a fully-typed view over it). To
  change the consultation co-pay from 10% to 15%, you edit one JSON
  field -- no code change, no prompt tuning, no risk of an LLM
  "interpreting" the new percentage differently for different claims.

LLMs are used **only** where the task is genuinely about *understanding
unstructured input* -- reading a photographed prescription and turning it
into `{diagnosis, treatment, medicines, ...}` (Stage 2), and guessing a
document's type from its filename/content (Stage 0). Both of those
outputs are then validated against a strict Pydantic schema
(`ExtractionResponse`) before they're allowed to influence the
deterministic rules engine. If extraction fails or returns garbage, the
rules engine degrades gracefully (Section 6) rather than trusting bad
data.

---

## 4. Why separate agents with a `run_safe` boundary?

Each of the stages is its own class extending `BaseAgent`, with:

- a `name` and `stage` identifier (used in trace entries),
- a `run(ctx) -> ctx` method containing the actual logic,
- inheritance of `run_safe(ctx) -> ctx`, which wraps `run` in a
  try/except.

`run_safe` is the multi-agent system's single most important piece of
plumbing. On any unhandled exception inside `run`, it:

1. logs the exception (`logger.exception`),
2. sets `ctx.degraded = True`,
3. appends a `FAIL`-status `TraceEntry` naming the failing component and
   the error, with `confidence_impact = -0.25`,
4. returns the (otherwise unmodified) context so the pipeline continues.

This gives three benefits that a monolithic "do everything in one
function" design wouldn't:

- **Independent testability.** `tests/unit/test_*.py` has one file per
  agent/rules-module; each test constructs a minimal `ClaimContext` and
  asserts on the specific trace entries and outputs that agent produces,
  without needing to run the whole pipeline.
- **Independent failure containment.** A bug or outage in, say, the
  Gemini extraction call cannot crash fraud detection or decision
  synthesis -- they still run, just with `ctx.extractions = []` and
  `ctx.degraded = True` to work with.
- **Clear, per-stage observability.** The trace naturally groups by
  `stage`/`component`, so an ops dashboard can show "extraction failed on
  3% of claims this week" without any extra instrumentation.

---

## 5. Design decisions and trade-offs (the non-obvious ones)

These are the places where the assignment's test cases (`test_cases.json`)
under-specified the policy schema, and where we had to make and document a
judgment call. All are covered with trace messages and unit tests; the
full reasoning per test case is in `EVAL_REPORT.md`'s *Known Limitations*
section. Summarized here:

### 5.1 Category sub-limits vs. the annual OPD limit

`ClaimSubmission.ytd_claims_amount` is a single overall figure -- the
schema has no category-specific year-to-date breakdown. Two limit fields
exist in `policy_terms.json`: `coverage.annual_opd_limit` (Rs.50,000,
overall) and `opd_categories[category].sub_limit` (e.g. Rs.2,000 for
consultation, Rs.10,000 for dental).

If the category `sub_limit` were checked against the *overall*
`ytd_claims_amount` (e.g. Rs.5,000 already spent vs. a Rs.2,000
consultation sub-limit), every consultation claim with any prior spend in
*any* category would be rejected -- which contradicts TC004 and TC010,
both of which expect approval.

**Decision:** the category `sub_limit` is evaluated against the *current
claim alone* (category YTD = 0). It can still produce a hard rejection if
a single claim exceeds the category's annual allowance on its own, but
its remaining headroom does **not** cap the approved amount -- we have no
reliable category-level spend-to-date to base a cap on. The *annual OPD
limit*, which **is** backed by the real `ytd_claims_amount`, is the only
headroom figure used as a cap on the approved amount.

**Trade-off:** in a real system, the claim submission schema would carry
(or the backend would look up) a per-category YTD figure, and the
sub-limit check would use it the same way the annual check uses
`ytd_claims_amount`. The current behaviour is correct for "first claim of
the year in this category" and degrades to "informational only" for
subsequent claims in the same category -- which is a known simplification,
not a hidden bug (it's called out explicitly in both the code comments in
`engine.py` and `EVAL_REPORT.md`).

### 5.2 Per-claim limit applies to the post-exclusion amount, and is category-scoped

`coverage.per_claim_limit` is Rs.5,000. TC006 is a dental claim totalling
Rs.12,000 claimed, of which Rs.4,000 (teeth whitening) is excluded as
cosmetic; the expected result is `PARTIAL` with `approved_amount = 8000`
-- i.e. Rs.8,000, which is *also* greater than Rs.5,000.

Two changes were needed to make this consistent:

1. **Line-item exclusions are computed before the per-claim-limit check**,
   and the limit is checked against the post-exclusion *eligible* amount
   (Rs.8,000), not the raw claimed total (Rs.12,000). A claim shouldn't be
   hard-rejected for exceeding a limit when the excess is entirely made up
   of amounts that were never going to be paid anyway.
2. **DENTAL and VISION are exempt from the general `per_claim_limit`.**
   Their own category `sub_limit`s (Rs.10,000 and Rs.5,000 respectively)
   are larger than the Rs.5,000 general limit and are treated as the
   effective per-claim ceiling for itemized treatments in those
   categories -- a single dental procedure routinely costs more than a
   single OPD consultation, and the policy's own numbers reflect that.

**Trade-off:** the exemption list (`_PER_CLAIM_LIMIT_EXEMPT_CATEGORIES` in
`limits.py`) is currently a hardcoded set of two category names, which is
the one piece of "policy logic" not driven purely by
`policy_terms.json`. A cleaner long-term fix would be an explicit
`per_claim_limit_applies: bool` (or a category-specific override) field in
the policy schema itself, removing the need for any in-code category list.

### 5.3 "Any fraud signal -> MANUAL_REVIEW", not just score-over-threshold

`fraud_thresholds.fraud_score_manual_review_threshold` is 0.8. TC009's
single same-day-claims-limit breach produces `fraud_score = 0.4`, which
is below that threshold -- yet TC009 expects `MANUAL_REVIEW`.

**Decision:** `DecisionSynthesizerAgent` routes to `MANUAL_REVIEW`
whenever `ctx.fraud_signals` is non-empty, *in addition to* the existing
score-threshold and high-value-claim triggers. The rationale: a detected
behavioural anomaly (e.g. "this member submitted 4 claims today against a
limit of 2") is qualitatively different from "this claim's amount is
unusually large" -- the former is evidence of a *pattern*, which a human
reviewer should see regardless of how it numerically scores. The
`fraud_score` and threshold remain in the output (`decision.notes`) for
transparency, but are no longer the sole gate.

**Trade-off:** in a high-volume system, "any signal -> review" could
overwhelm a manual review queue if signals are noisy or low-value. The
fix there isn't to relax this rule, but to make signal *generation*
itself more precise (Section 7) -- e.g. only flag same-day-claim counts
that are unusual *for that member's history*, not a flat global
threshold.

### 5.4 PARTIAL vs. APPROVED: contractual co-pay/discount is not "partial"

A naive `approved_amount < claimed_amount => PARTIAL` rule would
incorrectly mark TC004 (Rs.1,500 claimed, Rs.1,350 approved after a
contractual 10% co-pay) and TC010 (Rs.4,500 claimed, Rs.3,240 approved
after network discount + co-pay) as `PARTIAL` -- but both are expected to
be `APPROVED`.

**Decision:** `PARTIAL` means the policy *excluded something the member
asked for* (a line item was rejected) or *capped the eligible base amount
itself* (annual headroom). The normal discount-then-co-pay arithmetic
applied to the *full* eligible amount is the member's expected
contractual share -- not a denial of anything -- so it doesn't change the
decision status. Concretely: `base_was_reduced = eligible_base <
claimed_amount` (true only when exclusions/caps shrank the base), and
`PARTIAL` triggers on `any_line_item_rejected or base_was_reduced`,
*not* on `approved_amount < claimed_amount`.

### 5.5 Multiple simultaneous hard rejections are all reported

For TC007 and TC012, more than one hard-rejection rule legitimately fires
on the same input (e.g. TC012's obesity claim is simultaneously inside its
waiting period, excluded by condition, *and* over the per-claim limit).

**Decision:** the rules engine evaluates every applicable hard-rejection
check before returning (it doesn't stop at the first failure), and
`rejection_reasons` lists all of them. The evaluation harness checks that
the *expected* code is a subset of the actual codes, which both cases
satisfy.

**Trade-off:** a system that needs to present the member with exactly one
primary reason (for UX simplicity) would need a priority ordering over
rejection codes to pick "the" reason while still logging the rest in the
trace. We chose to surface everything because, for an *operations* /
adjuster-facing tool (which is this system's primary audience, per the
trace-based explainability goal), more true information is strictly
better than less.

---

## 6. Failure handling and graceful degradation

The system assumes failures *will* happen -- LLM timeouts, malformed
model output, transient waves of 503 unavailability -- and is built so that
none of them produce a 500 or an unexplainable result.

**Three layers of defense:**

1. **`BaseAgent.run_safe`** wraps every agent. Any unhandled exception becomes a `FAIL` trace entry + `ctx.degraded = True` + a `-0.25` confidence penalty, and the pipeline continues.
2. **Transient API Recovery**: The `ExtractionAgent` incorporates an automated exponential backoff loop that automatically intercepts and retries failed Gemini calls up to 3 times if the upstream server flags temporary 503 high-demand rate spikes, preventing unnecessary context degradation.
3. **The orchestrator wraps the rules engine** (`evaluate_rules`) separately, since it's a plain function rather than a `BaseAgent`. If it raises, the orchestrator builds an empty `RulesEvaluationResult`, logs a `FAIL` trace entry with a `-0.3` confidence penalty, and continues to fraud detection and decision synthesis.

**The data-fallback path (TC011):** if `ExtractionAgent` fails entirely
(`ctx.extractions = []`), the rules engine's `_gather_text_fields` helper
falls back to reading `diagnosis`, `treatment`, `line_items`, and `total`
directly from `ctx.submission.documents[*].content` -- the raw data the
client uploaded, bypassing the (failed) structured-extraction step. This
means a single extraction-service outage doesn't block claims that
already carry usable structured data (which the eval harness's documents
always do, and which a well-formed API client could also supply
directly).

**The final safety net:** if `DecisionSynthesizerAgent` *itself* fails
(`ctx.decision is None` after `run_safe`), the orchestrator constructs a
fallback `ClaimDecision(decision=MANUAL_REVIEW, confidence_score=0.1,
manual_review_recommended=True, ...)` directly -- so `ctx.decision` is
*never* `None` when `run_claim_pipeline` returns (unless the claim was
`blocked` at Stage 1, which is a distinct, intentional non-decision
state).

**Confidence reflects all of this** (`app/utils/confidence.py`,
`calculate_pipeline_confidence`): degraded pipelines, failed document
extractions, fraud risk, and blocked claims all pull the score down in
documented, fixed increments -- see `README.md`'s *Confidence scoring*
section for the exact formula. A human reviewing a `MANUAL_REVIEW` or
low-confidence `APPROVED` claim can see *why* the confidence is low
directly from the trace, without needing to inspect logs.

---

## 7. What would change at 10x scale

The current design optimizes for correctness, explainability, and testing
velocity on a single-claim, synchronous, in-process pipeline. At 10x
claim volume (or 10x document size/complexity), the following would need
to change:

### 7.1 Asynchronous, parallel document extraction

`ExtractionAgent.run` currently extracts documents one at a time in a
loop. For a claim with 5+ documents (common for hospitalization claims
with discharge summaries, multiple bills, and lab reports), this is
purely additive latency. At higher volume, this should become:

- `asyncio.gather` (or a small worker pool) over per-document Gemini
  calls, since each document's extraction is independent.
- A per-document timeout shorter than the overall request timeout, so one
  slow document degrades to `extraction_status = "FAILED"` for *that
  document* rather than stalling the whole claim.

### 7.2 Queue-based processing instead of synchronous request/response

`POST /claims` currently runs the entire pipeline synchronously and
returns the decision in the response. At 10x volume, LLM extraction
latency (seconds per document) would make this a poor fit for a
request/response API. The natural evolution:

- `POST /claims` ingests binary streams over multipart data paths, buffers them securely to disk (`storage/uploads/`), validates the parameters, enqueues an asynchronous background task (e.g. via Celery/RQ + Redis, or SQS), and returns `202 Accepted` with a `claim_id`.
- A worker pool runs `run_claim_pipeline` per job and persists the
  resulting `ClaimContext` (decision + trace).
- `GET /claims/{claim_id}` (already present in `routes_claims.py`) becomes
  the polling endpoint; a websocket/SSE channel could push the result when
  ready.

The pipeline function itself (`run_claim_pipeline`) doesn't need to
change for this -- it's already a pure function from `(submission,
policy) -> ClaimContext`, which is exactly the shape a queue worker wants.

### 7.3 Persistent storage instead of the in-memory `CLAIMS_DB`

`routes_claims.py` currently stores results in a process-local dict, which
doesn't survive restarts and doesn't work across multiple API instances.
At 10x scale this becomes a Postgres table (claim submissions, decisions,
and traces as JSONB columns, indexed by `claim_id`, `member_id`, and
`treatment_date` for the fraud detector's same-day/monthly lookups).

This also fixes a current limitation: `FraudDetectorAgent` relies on
`ClaimSubmission.claims_history` being supplied by the *client* in the
request. In a real system, claim history should be looked up server-side
from the persistent store, both for correctness (clients shouldn't be
trusted to report their own fraud signals) and so the same-day/monthly
counts reflect *all* claims, not just what one client happens to send.

### 7.4 Caching the policy configuration

`policy_loader.load_policy()` is already `functools.lru_cache`'d, so
`policy_terms.json` is parsed once per process. At 10x scale with
multiple worker processes/pods, this is fine as-is (each process caches
its own copy); if the policy needs to be updatable *without a redeploy*,
it would move to a config service (e.g. a database row + cache with TTL
or a pub/sub invalidation signal) rather than a file on disk, but the
`PolicyTerms` Pydantic model and everything downstream of
`load_policy()` would be unchanged.

### 7.5 Vector-based / cross-claim fraud detection

The current fraud detector only looks at counts within the single
submitted `claims_history`. At 10x volume, more sophisticated signals
become viable and valuable:

- Embedding-based similarity search across recently submitted documents
  to detect duplicate or reused bills/prescriptions across different
  claims or members (a common real-world fraud pattern).
- Cross-member pattern detection (e.g. the same hospital/provider name
  appearing in an unusual number of claims in a short window).

These would be additive `FraudSignal`s feeding into the existing
`ctx.fraud_signals` / `ctx.fraud_score` mechanism -- the
`DecisionSynthesizerAgent`'s "any signal -> MANUAL_REVIEW" rule (Section
5.3) already generalizes to new signal types without code changes there.

### 7.6 Batching LLM calls

If extraction prompts (`app/llm/prompts/extraction_prompts.py`) are
similar across many documents of the same type, batch/async APIs (where
supported) or response caching (e.g. identical-document-hash -> cached
extraction) would reduce both latency and Gemini API cost at scale.

### 7.7 What does *not* need to change

The deterministic rules engine, the `ClaimContext`/trace model, the
`BaseAgent.run_safe` failure boundary, and the confidence-scoring formula
are all O(1) per claim and have no shared mutable state across claims --
they scale horizontally for free by running more worker processes. The
architectural decisions in Sections 2-5 (shared context per claim,
deterministic policy logic, per-agent failure isolation) were chosen
specifically so that the *scaling* story is "add more workers / queue
depth", not "redesign the decision logic".

---

## Author

AI Engineer Assignment submission for Plum.
