# Component Contracts

## Purpose

This document defines the interface contracts for all major components in the Health Insurance Claims Processing System.

Each contract specifies:

* Responsibility
* Inputs
* Outputs
* Failure behavior
* Dependencies

The goal is to make each component independently replaceable.

---

# 1. DocumentClassifierAgent

## Responsibility

Determine document type for uploaded documents that do not already have a known type.

Runs before document verification.

Examples:

* Prescription
* Hospital Bill
* Lab Report
* Discharge Summary

---

## Input

```python
ClaimContext
```

Required fields:

```python
ctx.submission.documents
```

Each document may contain:

```python
file_id
file_name
content
actual_type
```

---

## Output

Mutates:

```python
document.actual_type
```

Possible values:

```python
PRESCRIPTION
HOSPITAL_BILL
PHARMACY_BILL
LAB_REPORT
DIAGNOSTIC_REPORT
DISCHARGE_SUMMARY
DENTAL_REPORT
UNKNOWN
```

Adds trace entries.

---

## Failure Behavior

Classification failure:

```python
actual_type = UNKNOWN
```

Pipeline continues.

Confidence reduced.

---

# 2. DocumentVerifierAgent

## Responsibility

Validate uploaded documents before any extraction or policy evaluation.

Runs immediately after classification.

---

## Input

```python
ClaimContext
PolicyTerms
```

Required:

```python
submission.claim_category
submission.documents
policy.document_requirements
```

---

## Checks

### Required Documents

Verify mandatory document types exist.

Example:

```text
Hospital Bill required
Prescription uploaded
```

Result:

```text
BLOCKED
```

---

### Readability

Verify documents are readable.

Example:

```text
Blurry hospital bill
```

Result:

```text
BLOCKED
```

---

### Patient Consistency

Verify all documents belong to the same person.

Example:

```text
Bill -> Rahul
Prescription -> Amit
```

Result:

```text
BLOCKED
```

---

## Output

Mutates:

```python
ctx.document_check_passed
ctx.blocked
ctx.block_code
ctx.block_message
```

Adds trace entries.

---

## Failure Behavior

Unexpected verification errors:

```python
ctx.degraded = True
```

Pipeline continues.

---

# 3. ExtractionAgent

## Responsibility

Convert medical documents into structured information.

---

## Input

```python
ClaimContext
```

Required:

```python
submission.documents
```

---

## Output

Produces:

```python
ctx.extractions
```

Type:

```python
list[DocumentExtractionResult]
```

Each result contains:

```python
file_id
document_type
extracted_fields
confidence
quality_flags
extraction_status
```

---

## Extraction Modes

### Passthrough

Used by evaluation harness.

Reads:

```python
document.content
```

directly.

---

### Gemini Extraction

Used for live uploads.

Calls:

```python
LLMClient.extract_document()
```

---

## Failure Behavior

Extraction failure:

```python
extraction_status = FAILED
```

Pipeline continues.

Trace recorded.

Confidence reduced.

---

# 4. Rules Engine

## Responsibility

Evaluate insurance policy coverage.

Pure deterministic component.

No LLM usage.

---

## Input

```python
ClaimContext
PolicyTerms
```

Required:

```python
member information
claim category
extracted fields
policy configuration
```

---

## Evaluates

Coverage eligibility

Waiting periods

Copay

Exclusions

Coverage limits

Sub-limits

Network requirements

Pre-authorization requirements

---

## Output

```python
RulesEvaluationResult
```

Contains:

```python
approved_amount
rejection_reasons
traces
line_items
```

---

## Failure Behavior

Rules exception:

```python
ctx.degraded = True
```

Pipeline continues.

Manual review may be triggered.

---

# 5. FraudDetectorAgent

## Responsibility

Identify suspicious claims.

---

## Input

```python
ClaimContext
PolicyTerms
```

---

## Output

Produces:

```python
ctx.fraud_score
ctx.fraud_signals
```

Example:

```python
fraud_score = 0.85
```

Signals:

```python
HIGH_AMOUNT
MULTIPLE_CLAIMS
OUT_OF_NETWORK
```

---

## Failure Behavior

Fraud detection failure:

```python
ctx.degraded = True
```

Pipeline continues.

---

# 6. DecisionSynthesizerAgent

## Responsibility

Generate final claim decision.

Consumes outputs from all previous stages.

---

## Input

```python
ClaimContext
RulesEvaluationResult
PolicyTerms
```

---

## Decision Types

```python
APPROVED
PARTIAL
REJECTED
MANUAL_REVIEW
```

---

## Output

Produces:

```python
ctx.decision
```

Type:

```python
ClaimDecision
```

Contains:

```python
decision
approved_amount
confidence_score
reasons
rejection_reasons
line_items
manual_review_recommended
notes
```

---

## Failure Behavior

If synthesis fails:

```python
MANUAL_REVIEW
```

is returned.

Pipeline never crashes.

---

# 7. LLMClient

## Responsibility

Encapsulate Gemini interactions.

Provides a stable interface between business logic and AI models.

---

## Input

```python
UploadedDocument
```

---

## Output

Validated extraction response:

```python
{
  "fields": {},
  "confidence": 0.95,
  "quality_flags": [],
  "status": "OK"
}
```

---

## Validation

All Gemini outputs are validated through:

```python
ExtractionResponse
```

Pydantic schema.

---

## Failure Behavior

Malformed JSON

Timeout

API Error

Invalid schema

Result:

```python
status = FAILED
```

Returned to ExtractionAgent.

---

# 8. Pipeline Orchestrator

## Responsibility

Coordinate all stages.

Single source of workflow execution.

---

## Input

```python
ClaimSubmission
PolicyTerms
```

---

## Workflow

```text
Document Classifier
        ↓
Document Verifier
        ↓
Extraction Agent
        ↓
Rules Engine
        ↓
Fraud Detector
        ↓
Decision Synthesizer
```

---

## Output

```python
ClaimContext
```

Fully populated.

---

## Failure Behavior

Agent failures are isolated.

Pipeline attempts to continue whenever safe.

Final fallback:

```python
MANUAL_REVIEW
```

instead of system failure.

---

# Confidence Scoring

Confidence is derived from:

* Extraction quality
* Failed documents
* Fraud score
* Pipeline degradation state
* Blocked claims

Range:

```python
0.0 - 1.0
```

Used by:

```python
DecisionSynthesizerAgent
```

to determine trust in automated decisions.
