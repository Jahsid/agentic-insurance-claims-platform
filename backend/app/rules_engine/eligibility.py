"""
Eligibility checks: member lookup, policy active status, and
dependent coverage validation.

These run BEFORE waiting-period / exclusion / limit checks in
RulesEngine.evaluate() -- a claim for a member who doesn't exist, whose
policy isn't active, or whose relationship isn't covered under the
family floater should never reach those later, more expensive checks.

Three checks, each returning a TraceEntry:

1. check_member_exists(member_id, policy) -> TraceEntry
   FAIL -> rejection code "MEMBER_NOT_FOUND". Message states the member
   ID that was not found.

2. check_policy_active(treatment_date, policy) -> TraceEntry
   FAIL -> rejection code "POLICY_INACTIVE". Triggers if:
     - treatment_date is outside [policy_start_date, policy_end_date], or
     - policy_holder.renewal_status != "ACTIVE"
   Message states the policy's valid date range (and renewal status if
   that's the cause) plus the treatment date that fell outside it.

3. check_dependent_coverage(member, policy) -> TraceEntry
   FAIL -> rejection code "DEPENDENT_NOT_COVERED". Applies only to
   non-SELF members (dependents): their `relationship` must be present
   in policy.coverage.family_floater.covered_relationships, AND
   family_floater.enabled must be True, AND (if primary_member_id is
   set) the primary member must exist and list this member in their
   `dependents`. Message states the dependent's relationship and which
   relationships are covered.

Component contract
-------------------
Input:  member_id: str, treatment_date: str (YYYY-MM-DD), policy: PolicyTerms
Output: each function returns a single TraceEntry (status PASS or FAIL).
        check_member_exists additionally returns the resolved Member
        (or None) as the second element of its tuple, so callers don't
        need a second lookup.

Raises: nothing. Date-format errors are caught and surfaced as a
WARNING TraceEntry rather than raising, so a malformed treatment_date
degrades the eligibility check rather than crashing the pipeline
(BaseAgent.run_safe provides a second line of defense regardless).
"""
from __future__ import annotations

from datetime import datetime

from app.models.policy import PolicyTerms, Member
from app.models.decision import TraceEntry, TraceStatus


def _parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def check_member_exists(member_id: str, policy: PolicyTerms) -> tuple[TraceEntry, Member | None]:
    member = policy.get_member(member_id)

    if member is None:
        return (
            TraceEntry(
                stage="eligibility_check",
                component="RulesEngine.eligibility.member_exists",
                status=TraceStatus.FAIL,
                message=(
                    f"Member ID '{member_id}' was not found in the policy "
                    f"member roster for policy '{policy.policy_id}'. This "
                    f"claim cannot be processed."
                ),
                details={"member_id": member_id, "policy_id": policy.policy_id},
            ),
            None,
        )

    return (
        TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.member_exists",
            status=TraceStatus.PASS,
            message=(
                f"Member '{member.name}' ({member.member_id}, "
                f"{member.relationship}) found on policy '{policy.policy_id}'."
            ),
            details={"member_id": member.member_id, "name": member.name, "relationship": member.relationship},
        ),
        member,
    )


def check_policy_active(treatment_date: str, policy: PolicyTerms) -> TraceEntry:
    holder = policy.policy_holder

    if holder.renewal_status.upper() != "ACTIVE":
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.policy_active",
            status=TraceStatus.FAIL,
            message=(
                f"Policy '{policy.policy_id}' has renewal status "
                f"'{holder.renewal_status}' (not ACTIVE). Claims cannot be "
                f"processed against an inactive policy."
            ),
            details={"policy_id": policy.policy_id, "renewal_status": holder.renewal_status},
        )

    try:
        start = _parse_date(holder.policy_start_date)
        end = _parse_date(holder.policy_end_date)
        treat = _parse_date(treatment_date)
    except ValueError as exc:
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.policy_active",
            status=TraceStatus.WARNING,
            message=(
                f"Could not verify policy active dates due to a date "
                f"format issue ({exc}); proceeding without this check."
            ),
            confidence_impact=-0.05,
        )

    if not (start <= treat <= end):
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.policy_active",
            status=TraceStatus.FAIL,
            message=(
                f"Policy '{policy.policy_id}' is valid from "
                f"{start.isoformat()} to {end.isoformat()}. The treatment "
                f"date {treat.isoformat()} falls outside this period, so "
                f"this claim cannot be processed under the current policy term."
            ),
            details={
                "policy_id": policy.policy_id,
                "policy_start_date": start.isoformat(),
                "policy_end_date": end.isoformat(),
                "treatment_date": treat.isoformat(),
            },
        )

    return TraceEntry(
        stage="eligibility_check",
        component="RulesEngine.eligibility.policy_active",
        status=TraceStatus.PASS,
        message=(
            f"Policy '{policy.policy_id}' is ACTIVE and treatment date "
            f"{treat.isoformat()} falls within the policy term "
            f"({start.isoformat()} to {end.isoformat()})."
        ),
        details={
            "policy_id": policy.policy_id,
            "policy_start_date": start.isoformat(),
            "policy_end_date": end.isoformat(),
            "treatment_date": treat.isoformat(),
        },
    )


def check_dependent_coverage(member: Member, policy: PolicyTerms) -> TraceEntry:
    if member.relationship.upper() == "SELF":
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.dependent_coverage",
            status=TraceStatus.PASS,
            message=f"Member '{member.name}' is the primary policyholder (SELF); no dependent-coverage check needed.",
            details={"member_id": member.member_id, "relationship": member.relationship},
        )

    floater = policy.coverage.family_floater

    if not floater.enabled:
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.dependent_coverage",
            status=TraceStatus.FAIL,
            message=(
                f"Family floater coverage is not enabled on policy "
                f"'{policy.policy_id}'. Dependent '{member.name}' "
                f"({member.relationship}) is not covered."
            ),
            details={"member_id": member.member_id, "relationship": member.relationship, "family_floater_enabled": False},
        )

    covered_relationships = [r.upper() for r in floater.covered_relationships]
    if member.relationship.upper() not in covered_relationships:
        return TraceEntry(
            stage="eligibility_check",
            component="RulesEngine.eligibility.dependent_coverage",
            status=TraceStatus.FAIL,
            message=(
                f"Dependent '{member.name}' has relationship "
                f"'{member.relationship}', which is not in the list of "
                f"relationships covered under the family floater: "
                f"{', '.join(floater.covered_relationships)}."
            ),
            details={
                "member_id": member.member_id,
                "relationship": member.relationship,
                "covered_relationships": floater.covered_relationships,
            },
        )

    if member.primary_member_id:
        primary = policy.get_member(member.primary_member_id)
        if primary is None:
            return TraceEntry(
                stage="eligibility_check",
                component="RulesEngine.eligibility.dependent_coverage",
                status=TraceStatus.FAIL,
                message=(
                    f"Dependent '{member.name}' references primary member "
                    f"'{member.primary_member_id}', who was not found on "
                    f"this policy."
                ),
                details={"member_id": member.member_id, "primary_member_id": member.primary_member_id},
            )
        if member.member_id not in primary.dependents:
            return TraceEntry(
                stage="eligibility_check",
                component="RulesEngine.eligibility.dependent_coverage",
                status=TraceStatus.FAIL,
                message=(
                    f"Dependent '{member.name}' ({member.member_id}) is not "
                    f"listed in primary member '{primary.name}' "
                    f"({primary.member_id})'s dependents list. Coverage "
                    f"cannot be verified."
                ),
                details={
                    "member_id": member.member_id,
                    "primary_member_id": primary.member_id,
                    "primary_dependents": primary.dependents,
                },
            )

    return TraceEntry(
        stage="eligibility_check",
        component="RulesEngine.eligibility.dependent_coverage",
        status=TraceStatus.PASS,
        message=(
            f"Dependent '{member.name}' ({member.relationship}) is covered "
            f"under the family floater on policy '{policy.policy_id}'."
        ),
        details={"member_id": member.member_id, "relationship": member.relationship},
    )