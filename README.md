# Overview

This project is an AI-assisted Health Insurance Claims Processing System
built as part of the Plum AI Engineer Assignment.

The system automates the end-to-end claim review workflow:

1. Classify and verify uploaded documents
2. Extract structured medical information
3. Evaluate policy coverage rules
4. Detect fraud signals
5. Generate explainable claim decisions

It is designed around reliability, explainability, and graceful failure
handling rather than black-box decision making. All 12 scenarios in the
assignment's evaluation suite pass end-to-end -- see `EVAL_REPORT.md` for
the full trace of every case.

---

## Repository layout


```

.
├── README.md                  # this file
├── ARCHITECTURE.md             # design doc, trade-offs, scaling discussion
├── COMPONENT_CONTRACTS.md      # I/O contract for every agent/module
├── EVAL_REPORT.md              # all 12 test cases, full traces, pass/fail
├── docker-compose.yml
├── data/
│   └── policy_terms.json       # single source of truth for all policy rules
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── policy_loader.py
│   │   ├── api/                # routes_claims.py, routes_health.py
│   │   ├── models/              # claim, documents, decision, policy,
│   │   │                         # extraction_response (Pydantic schemas)
│   │   ├── agents/               # document_classifier, document_verifier,
│   │   │                          # extractor, fraud_detector,
│   │   │                          # decision_synthesizer, base
│   │   ├── rules_engine/          # eligibility, waiting_periods, exclusions,
│   │   │                           # preauth, limits, coverage_calculator,
│   │   │                           # engine (orchestrates all checks)
│   │   ├── orchestrator/
│   │   │   └── pipeline.py        # wires every stage together
│   │   ├── utils/
│   │   │   └── confidence.py      # single source of truth for confidence scoring
│   │   └── llm/
│   │       ├── client.py          # Gemini wrapper for live extraction
│   │       └── prompts/           # per-document-type extraction prompts
│   └── tests/
│       ├── unit/                  # one file per agent / rules module
│       ├── integration/
│       └── eval/
│           ├── test_cases.json    # the 12 assignment scenarios
│           └── run_test_cases.py  # runs all 12, prints expected vs actual + trace
└── frontend/
├── package.json
└── src/
├── pages/                 # SubmitClaim, ClaimResult
├── components/            # DocumentUpload, DecisionCard, TraceViewer
└── api/client.ts

```

---

## Features

### Claim submission

Accepts:

- Member ID and policy ID
- Claim category (CONSULTATION, DIAGNOSTIC, PHARMACY, DENTAL, VISION,
  ALTERNATIVE_MEDICINE)
- Claimed amount, treatment date, hospital name
- Year-to-date claims amount and claims history (for fraud detection)
- One or more uploaded documents

Supported document types: Prescription, Hospital Bill, Pharmacy Bill, Lab
Report, Diagnostic Report, Discharge Summary, Dental Report.

---

### Stage 0 -- Document Classification

`DocumentClassifierAgent` infers a document's type (filename heuristics,
content hints, and optionally an LLM) for any uploaded document that
doesn't already carry an `actual_type`. This is the live-upload path. The
evaluation harness supplies `actual_type` directly for every document, so
classification is a no-op there (each document is recorded as
`source: "provided"`).

---

### Stage 1 -- Document Verification

Before any extraction or decision-making, `DocumentVerifierAgent` checks,
in order:

1. **Readability** -- any document flagged `UNREADABLE` blocks the claim
   and asks for that *specific* file to be re-uploaded, without rejecting
   the rest of the submission.
2. **Required document types** -- compares uploaded document types against
   `policy_terms.json -> document_requirements[category]`. If something is
   missing, the message names both what was uploaded and what's still
   required.
3. **Patient identity consistency** -- if documents carry different
   patient names, the claim is blocked and both names (with their
   document types) are surfaced.

Any failure here sets `blocked = True` and a `block_code` /
`block_message`; the pipeline stops immediately -- no extraction, rules,
fraud, or decision stages run.

---

### Stage 2 -- Extraction

`ExtractionAgent` converts each document into structured fields
(diagnosis, treatment, line items, totals, dates, etc.) via one of two
modes:

1. **Passthrough** -- if the document already carries a `content` dict
   (the evaluation harness's ground-truth data), it's validated and used
   directly with confidence 0.95.
2. **Gemini-powered** -- for live uploads over standard multi-part form data (`multipart/form-data`), binary streams are saved securely onto local disk staging (`storage/uploads/`), dynamically cast into `UploadedDocument` structural models, and sent directly to Gemini Vision for structured parsing.

If an individual document fails extraction, it's marked
`extraction_status = "FAILED"` with confidence 0 and the pipeline
continues with the remaining documents (confidence is reduced
proportionally). If extraction itself errors out entirely (e.g. simulated
service timeout), `BaseAgent.run_safe` catches it, marks the pipeline
`degraded`, and the rules engine falls back to reading `content` directly
from the submitted documents.

---

### Stage 3 -- Policy Rules Engine (deterministic)

All policy logic lives in `app/rules_engine/` and reads exclusively from
`data/policy_terms.json` -- **nothing is hardcoded**. `engine.py`
orchestrates these checks in order:

1. **Eligibility** (`eligibility.py`) -- member lookup, policy
   active/renewal status, dependent/family-floater coverage.
2. **Waiting periods** (`waiting_periods.py`) -- general initial waiting
   period plus condition-specific periods (diabetes, hypertension,
   maternity, etc.), matched from free-text diagnosis via keyword mapping.
   On failure, states the exact date the member becomes eligible.
3. **Condition-level exclusions** (`exclusions.py`) -- rejects the whole
   claim if the diagnosis/treatment matches a globally excluded condition.
4. **Line-item exclusions** (`exclusions.py`) -- for itemized bills
   (notably DENTAL/VISION), excludes individual cosmetic/non-covered line
   items while approving the rest (drives `PARTIAL` decisions).
5. **Pre-authorization** (`preauth.py`) -- for high-value diagnostics
   (MRI/CT/PET) above a configured threshold, requires a pre-auth
   reference and explains how to resubmit if missing.
6. **Per-claim limit** (`limits.py`) -- checked against the
   post-exclusion eligible amount, not the raw claimed total. DENTAL and
   VISION are exempt (their own larger category sub-limits act as the
   ceiling).
7. **Category sub-limit & annual OPD limit** (`limits.py`) -- the annual
   OPD limit (backed by real `ytd_claims_amount`) caps the approved
   amount; the category sub-limit can independently reject a single
   over-sized claim.
8. **Coverage calculation** (`coverage_calculator.py`) -- network
   discount applied **first**, then co-pay applied to the discounted
   amount, then any annual-headroom cap. The full breakdown (base amount,
   discount, co-pay, final) is returned in `decision.breakdown` and
   `decision.notes`.

---

### Stage 4 -- Fraud Detection

`FraudDetectorAgent` checks, against `policy_terms.json ->
fraud_thresholds`:

- Same-day claim count vs. `same_day_claims_limit`
- Monthly claim count vs. `monthly_claims_limit`
- Claimed amount vs. `high_value_claim_threshold`

Each triggered check becomes a specific, human-readable signal (naming
the offending claim IDs where relevant) and contributes to `fraud_score`.
**Any** detected signal routes the claim to `MANUAL_REVIEW` rather than
letting it auto-approve or auto-reject -- a detected anomaly should always
get human eyes.

---

### Stage 5 -- Decision Synthesis

`DecisionSynthesizerAgent` combines the rules-engine result, fraud
signals, and pipeline confidence into a final `ClaimDecision`:

- **REJECTED** -- any hard rejection from the rules engine
  (`MEMBER_NOT_FOUND`, `POLICY_INACTIVE`, `DEPENDENT_NOT_COVERED`,
  `WAITING_PERIOD`, `EXCLUDED_CONDITION`, `PRE_AUTH_MISSING`,
  `PER_CLAIM_EXCEEDED`, limit exhaustion, or `NO_PAYABLE_AMOUNT`). All
  applicable codes are reported, not just the first.
- **MANUAL_REVIEW** -- any fraud signal present, fraud score over
  threshold, or claimed amount over the manual-review ceiling.
- **PARTIAL** -- line items were excluded, or the eligible base amount
  itsmselves was reduced (e.g. by an annual-limit cap). Normal network
  discount / co-pay arithmetic on the *full* eligible amount is **not**
  treated as partial -- that's the member's expected contractual share,
  so it's `APPROVED`.
- **APPROVED** -- full eligible amount payable (after normal discount/
  co-pay), `approved_amount > 0`.

If a component fails partway through (`ctx.degraded = True`), the
decision still proceeds on whatever data is available, but confidence is
reduced and `manual_review_recommended = True` with an explanatory note.

---

### Explainable decisions

Every claim produces a full ordered trace (`ctx.trace`, returned as
`trace` in the API response), one entry per check:


```

Document Classification
|
v
Document Verification
|
v
Extraction
|
v
Eligibility -> Waiting Period -> Exclusions -> Pre-Auth -> Limits -> Coverage Calc
|
v
Fraud Detection
|
v
Decision Synthesis

```

Each trace entry records `stage`, `component`, `status`
(PASS/FAIL/WARNING/BLOCKED/SKIPPED), a human-readable `message`, structured
`details`, and (where relevant) `confidence_impact`. Operations teams can
see exactly what was checked, what passed or failed, and why a decision
(or confidence score) came out the way it did.

---

## Decision types


```

APPROVED        -- full eligible amount payable
PARTIAL         -- some items/amount excluded or capped
REJECTED        -- one or more hard policy rules failed
MANUAL_REVIEW   -- fraud/anomaly signal detected, needs human review

```

Each non-blocked decision includes: `approved_amount`, `confidence_score`,
`reasons`, `rejection_reasons`, `line_items` (per-item approve/reject with
reasons), `breakdown` (discount/co-pay math), and
`manual_review_recommended`.

A **blocked** claim (failed Stage 1) never reaches a decision; the API
response instead carries `blocked: true`, `block_code`, and
`block_message`, plus a `confidence_score` of `0.40` (see *Confidence
Scoring* below).

---

## Confidence scoring

Confidence is computed once, deterministically, by
`app/utils/confidence.py -> calculate_pipeline_confidence(ctx)` -- it is
the single source of truth used by both the decision synthesizer and the
API layer (for blocked claims, which never reach the synthesizer).

Starting point:

- average per-document extraction confidence, if any documents were
  extracted, **or**
- `1.0 - 0.30 = 0.70` if no documents were extracted at all

Then, in order:

- `-0.10` per document with `extraction_status == "FAILED"`
- `-0.20` if the pipeline is `degraded` (a component failed and was
  skipped)
- `-(fraud_score x 0.20)` for fraud/anomaly risk
- capped at `0.40` if the claim is `blocked`

...clamped to `[0.0, 1.0]`.

---

## Failure handling

The system degrades gracefully rather than failing hard. Examples of
handled failures: LLM/extraction timeout, malformed AI JSON response
(rejected by `ExtractionResponse` schema validation), or an unexpected
exception inside the rules engine.

In all cases:

- `BaseAgent.run_safe` (and an equivalent try/except around the rules
  engine in the orchestrator) catches the exception, logs it, and appends
  a `FAIL`-status trace entry with a `confidence_impact` penalty.
- `ctx.degraded = True` is set.
- The pipeline **continues** with whatever partial data is available
  (the rules engine falls back to reading `content` directly from
  `ctx.submission.documents` if extraction didn't run).
- **Transient API Recovery**: The `ExtractionAgent` incorporates an automated exponential backoff loop that automatically retries failed Gemini calls up to 3 times if the upstream server flags temporary 503 high-demand rate spikes.
- The final decision is still produced, but with reduced confidence and
  `manual_review_recommended = True`.
- **No exception ever propagates to the API as a 500** for a pipeline
  failure (`run_claim_pipeline` always returns a `ClaimContext` with a
  decision or a block reason).

---

## Technology stack

**Backend:** Python 3.11+, FastAPI, Pydantic v2, Uvicorn, python-dotenv.

**AI / extraction:** Google Gemini (`google-genai` modern SDK), prompt-based
per-document-type extraction, structured-output validation via Pydantic.

**Frontend:** React, TypeScript, Vite, Tailwind.

---

## Deployment & Local Setup
Live Deployments
Frontend Web Dashboard UI: https://agentic-insurance-claims-platform.vercel.app/

Backend Multi-Agent API Engine: https://plum-ai-claims-engine.onrender.com/ (Swagger documentation interactive sandbox available at /docs)

## Running the project

### Option A: Docker Compose (recommended)

```bash
# from the repo root
cp backend/.env.example backend/.env   # optional: add GEMINI_API_KEY for live extraction
docker compose up --build

```

* Backend: http://localhost:8000 (Swagger UI at `/docs`)
* Frontend: http://localhost:5173

### Option B: Run locally

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload

```

* API: http://localhost:8000
* Swagger UI: http://localhost:8000/docs

**Frontend**

```bash
cd frontend
npm install
npm run dev

```

* App: http://localhost:5173

### Configuration

All environment variables are read once via `app/config.py -> get_settings()`. Copy `backend/.env.example` to `backend/.env` and adjust
as needed:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | development / staging / production |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | uvicorn bind address |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | frontend origins |
| `GEMINI_API_KEY` | (none) | required only for live document extraction |
| `MODEL_NAME` | `gemini-2.5-flash` | Gemini model for extraction |
| `POLICY_DATA_PATH` | `<repo_root>/data/policy_terms.json` | policy config location |

The evaluation harness and full test suite require **none** of these to be
set -- `test_cases.json` supplies ground-truth `content` for every
document, so the live Gemini path is never invoked.

---

## Testing & evaluation

```bash
cd backend

# unit tests (one file per agent / rules module)
pytest tests/unit -v

# run all 12 assignment scenarios, with expected-vs-actual + full trace
python tests/eval/run_test_cases.py

```

`run_test_cases.py` prints, for each of the 12 cases: the expected
outcome, the actual decision summary, and the complete ordered trace. See
`EVAL_REPORT.md` for the full output (all 12 pass) and a discussion of
edge-case design decisions.

---

## Design decisions

### Why deterministic policy decisions?

Insurance outcomes (waiting periods, coverage limits, exclusions, co-pay
math) must be strictly enforced and auditable. LLMs are used only for
*document understanding* (extraction, classification); every policy
decision is computed by plain Python reading `policy_terms.json`, so the
same input always produces the same output and every number can be traced
back to a specific config value.

### Why separate agents?

Each stage (classification, verification, extraction, fraud detection,
decision synthesis) has a single responsibility, a documented I/O
contract (see `COMPONENT_CONTRACTS.md`), and its own failure boundary via
`BaseAgent.run_safe`. This gives independent unit testability, clear
observability per stage in the trace, and the ability for one stage to
fail without taking down the whole pipeline.

### Why per-line-item exclusions before limit checks?

A claim that includes both covered and excluded items (e.g. a dental bill
with a root canal *and* cosmetic teeth whitening) should be evaluated
against its post-exclusion eligible amount for limit purposes -- otherwise
a legitimately partial claim could be wrongly rejected outright for
exceeding a limit that only the excluded portion was responsible for.

For the full rationale behind every edge-case decision (sub-limit
scoping, DENTAL/VISION per-claim-limit exemption, multiple simultaneous
rejection reasons, etc.), see `ARCHITECTURE.md` and the *Known
Limitations* section of `EVAL_REPORT.md`.

---

## Future improvements

* Gemini Vision-based document classification (current classifier uses
filename/content heuristics with an LLM hook for the future)
* Native PDF/multi-page image handling in the extraction pipeline
* Postgres persistence layer (currently an in-memory dict in
`routes_claims.py`)
* Async/queued extraction for higher throughput
* Human-in-the-loop review UI for `MANUAL_REVIEW` claims
* Production monitoring/metrics on trace outcomes and confidence
distributions

---

## Author

AI Engineer Assignment submission for Plum.