"""
Eligibility & waiting period checks.

Component contract
-------------------
Input:
    member: Member
    policy: PolicyTerms
    treatment_date: str (YYYY-MM-DD)
    diagnosis_text: Optional[str]  -- free text from prescription extraction

Output: RuleCheckResult
    - passed: bool
    - code: "OK" | "WAITING_PERIOD" | "MEMBER_NOT_FOUND" | "POLICY_INACTIVE"
    - message: human-readable, must state the eligible-from date if blocked
      by a waiting period (TC005 requirement)
    - details: dict with computed values (days_since_join, waiting_days, etc.)

Raises: nothing. All failure modes are represented via RuleCheckResult
so the rules engine can aggregate multiple checks without exceptions
controlling flow. (Genuinely unexpected errors, e.g. bad date formats,
are allowed to raise and are caught by BaseAgent.run_safe at the
agent boundary.)

Condition -> waiting period key mapping
----------------------------------------
Diagnosis free text is matched (case-insensitive substring) against
this map to find a specific waiting period in
policy.waiting_periods.specific_conditions. If no specific condition
matches, only the general `initial_waiting_period_days` applies.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.models.policy import PolicyTerms, Member
from app.models.decision import TraceEntry, TraceStatus

# Maps free-text diagnosis substrings -> waiting_periods.specific_conditions key
CONDITION_KEYWORDS: dict[str, list[str]] = {
    "diabetes": ["diabetes", "t2dm", "type 2 diabetes", "type 1 diabetes"],
    "hypertension": ["hypertension", "htn"],
    "thyroid_disorders": ["thyroid", "hypothyroidism", "hyperthyroidism"],
    "joint_replacement": ["joint replacement", "knee replacement", "hip replacement"],
    "maternity": ["maternity", "pregnancy", "antenatal"],
    "mental_health": ["mental health", "depression", "anxiety disorder", "psychiatric"],
    "obesity_treatment": ["obesity", "bariatric", "weight loss", "morbid obesity"],
    "hernia": ["hernia"],
    "cataract": ["cataract"],
}


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def match_specific_condition(diagnosis_text: str | None) -> str | None:
    if not diagnosis_text:
        return None
    text = diagnosis_text.lower()
    for condition_key, keywords in CONDITION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return condition_key
    return None


def check_waiting_period(
    member: Member,
    policy: PolicyTerms,
    treatment_date: str,
    diagnosis_text: str | None,
) -> TraceEntry:
    """
    Checks the general initial waiting period and any
    condition-specific waiting period that applies based on diagnosis.
    The member's *join_date* (or their primary member's join_date for
    dependents) is used as the coverage start date.
    """
    join_date_str = member.join_date
    if join_date_str is None and member.primary_member_id:
        primary = policy.get_member(member.primary_member_id)
        if primary:
            join_date_str = primary.join_date

    if join_date_str is None:
        return TraceEntry(
            stage="waiting_period_check",
            component="RulesEngine.waiting_periods",
            status=TraceStatus.WARNING,
            message=(
                f"No join date on record for member {member.member_id}; "
                f"waiting period could not be verified."
            ),
            confidence_impact=-0.1,
        )

    join_date = _parse_date(join_date_str)
    treat_date = _parse_date(treatment_date)
    days_since_join = (treat_date - join_date).days

    general_wp = policy.waiting_periods.initial_waiting_period_days
    if days_since_join < general_wp:
        eligible_from = join_date + timedelta(days=general_wp)
        return TraceEntry(
            stage="waiting_period_check",
            component="RulesEngine.waiting_periods",
            status=TraceStatus.FAIL,
            message=(
                f"Member joined on {join_date.isoformat()}. The general "
                f"{general_wp}-day waiting period applies. Member becomes "
                f"eligible from {eligible_from.isoformat()}, but treatment "
                f"was on {treat_date.isoformat()} ({days_since_join} days "
                f"after joining)."
            ),
            details={
                "rule": "initial_waiting_period",
                "join_date": join_date.isoformat(),
                "treatment_date": treat_date.isoformat(),
                "days_since_join": days_since_join,
                "required_days": general_wp,
                "eligible_from": eligible_from.isoformat(),
            },
        )

    condition_key = match_specific_condition(diagnosis_text)
    if condition_key:
        required_days = policy.waiting_periods.specific_conditions.get(condition_key)
        if required_days is not None and days_since_join < required_days:
            eligible_from = join_date + timedelta(days=required_days)
            return TraceEntry(
                stage="waiting_period_check",
                component="RulesEngine.waiting_periods",
                status=TraceStatus.FAIL,
                message=(
                    f"Diagnosis '{diagnosis_text}' matches condition "
                    f"'{condition_key}', which has a {required_days}-day "
                    f"waiting period from the member's join date "
                    f"({join_date.isoformat()}). Member becomes eligible "
                    f"for {condition_key.replace('_', ' ')} claims from "
                    f"{eligible_from.isoformat()}. Treatment date "
                    f"({treat_date.isoformat()}) is within the waiting "
                    f"period ({days_since_join} days since joining)."
                ),
                details={
                    "rule": "specific_condition_waiting_period",
                    "condition": condition_key,
                    "join_date": join_date.isoformat(),
                    "treatment_date": treat_date.isoformat(),
                    "days_since_join": days_since_join,
                    "required_days": required_days,
                    "eligible_from": eligible_from.isoformat(),
                },
            )

    return TraceEntry(
        stage="waiting_period_check",
        component="RulesEngine.waiting_periods",
        status=TraceStatus.PASS,
        message=(
            f"Member joined {join_date.isoformat()}, treatment on "
            f"{treat_date.isoformat()} ({days_since_join} days after "
            f"joining). No applicable waiting period is active."
        ),
        details={
            "join_date": join_date.isoformat(),
            "treatment_date": treat_date.isoformat(),
            "days_since_join": days_since_join,
            "matched_condition": condition_key,
        },
    )