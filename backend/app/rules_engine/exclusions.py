"""
Exclusion checks, at two levels:

1. Condition-level (whole-claim): if the diagnosis matches a globally
   excluded condition (policy.exclusions.conditions), the entire claim
   is rejected with rejection_reasons=["EXCLUDED_CONDITION"] (TC012).

2. Line-item-level: for categories with itemized bills (notably DENTAL
   and VISION), individual line items are checked against
   excluded_procedures / excluded_items for that category. Items that
   match are excluded from the approved amount but do not reject the
   whole claim (TC006 — PARTIAL approval).

Component contract
-------------------
check_condition_exclusion(diagnosis_text, treatment_text, policy) -> TraceEntry
    status PASS if no exclusion matched, FAIL if the whole claim is excluded.
    On FAIL, details.matched_exclusion names the excluded condition phrase.

check_line_item_exclusions(line_items, category, policy) -> tuple[list[LineItemDecision], TraceEntry]
    Returns a decision per line item (APPROVED/REJECTED with reason) and
    a summary TraceEntry. Matching is case-insensitive substring matching
    against excluded_procedures / excluded_items for the category.

Raises: nothing; all results are returned as data.
"""
from __future__ import annotations

from app.models.policy import PolicyTerms
from app.models.documents import LineItem
from app.models.decision import TraceEntry, TraceStatus, LineItemDecision


# Generic medical/insurance terms that are too common to be useful as
# match signals on their own (they'd cause false positives, e.g.
# "Root Canal Treatment" matching "Orthodontic Treatment").
_GENERIC_WORDS = {
    "treatment", "treatments", "procedure", "procedures", "surgery",
    "surgical", "cosmetic", "program", "programs", "therapy", "and",
    "the", "for", "non", "medically", "necessary",
}


def _text_matches_any(text: str | None, phrases: list[str]) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for phrase in phrases:
        # match on the distinctive (non-generic) key words of the phrase
        # (handles "Obesity and weight loss programs" matching diagnosis
        # "Morbid Obesity" without "Root Canal Treatment" matching
        # "Orthodontic Treatment")
        raw_words = phrase.lower().replace("(", " ").replace(")", " ").split()
        words = [w for w in raw_words if len(w) > 3 and w not in _GENERIC_WORDS]
        if words and any(w in lowered for w in words):
            return phrase
    return None


def check_condition_exclusion(
    diagnosis_text: str | None,
    treatment_text: str | None,
    policy: PolicyTerms,
) -> TraceEntry:
    combined = " ".join(filter(None, [diagnosis_text, treatment_text]))
    matched = _text_matches_any(combined, policy.exclusions.conditions)

    if matched:
        return TraceEntry(
            stage="exclusion_check",
            component="RulesEngine.exclusions",
            status=TraceStatus.FAIL,
            message=(
                f"Diagnosis/treatment ('{combined}') matches the policy "
                f"exclusion '{matched}'. This condition/treatment is not "
                f"covered under the policy."
            ),
            details={"matched_exclusion": matched, "diagnosis_text": diagnosis_text, "treatment_text": treatment_text},
        )

    return TraceEntry(
        stage="exclusion_check",
        component="RulesEngine.exclusions",
        status=TraceStatus.PASS,
        message="No condition-level policy exclusion matched.",
        details={"diagnosis_text": diagnosis_text, "treatment_text": treatment_text},
    )


def check_line_item_exclusions(
    line_items: list[LineItem],
    category: str,
    policy: PolicyTerms,
) -> tuple[list[LineItemDecision], TraceEntry]:
    cat = policy.get_category(category)
    excluded_phrases: list[str] = []
    if cat:
        excluded_phrases = list(cat.excluded_procedures) + list(cat.excluded_items)
    # also fold in global dental/vision exclusions
    if category.upper() == "DENTAL":
        excluded_phrases += policy.exclusions.dental_exclusions
    if category.upper() == "VISION":
        excluded_phrases += policy.exclusions.vision_exclusions

    decisions: list[LineItemDecision] = []
    rejected_descriptions = []
    for item in line_items:
        matched = _text_matches_any(item.description, excluded_phrases) if excluded_phrases else None
        if matched:
            decisions.append(
                LineItemDecision(
                    description=item.description,
                    claimed_amount=item.amount,
                    approved_amount=0,
                    status="REJECTED",
                    reason=f"Excluded under policy: matches '{matched}'",
                )
            )
            rejected_descriptions.append(f"{item.description} (matches '{matched}')")
        else:
            decisions.append(
                LineItemDecision(
                    description=item.description,
                    claimed_amount=item.amount,
                    approved_amount=item.amount,
                    status="APPROVED",
                    reason=None,
                )
            )

    if rejected_descriptions:
        trace = TraceEntry(
            stage="exclusion_check",
            component="RulesEngine.exclusions",
            status=TraceStatus.WARNING,
            message=(
                f"{len(rejected_descriptions)} line item(s) excluded under "
                f"policy and removed from the approved amount: "
                + "; ".join(rejected_descriptions)
            ),
            details={"rejected_items": rejected_descriptions},
        )
    else:
        trace = TraceEntry(
            stage="exclusion_check",
            component="RulesEngine.exclusions",
            status=TraceStatus.PASS,
            message="No line items matched any policy exclusion.",
        )

    return decisions, trace