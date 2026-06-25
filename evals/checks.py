"""
checks — Tier 1 deterministic eval checks (docs/evals/email-triage.md).

These are cheap, fast, model-free assertions that run on every structured
output. Phase 1 covers email-triage only; other agents get their own checks
later. Each check returns (passed, message). run_all_checks() rolls them up into
the list-of-dicts shape the eval logger writes to Supabase.

Severity note: confidence_sanity is advisory ("warning, not hard fail" in the
spec) — it reports passed=False when it flags something so the signal is
queryable, but it is not meant to fail a run on its own. The remaining checks
are hard checks.
"""

from typing import List, Tuple

from agents.schemas import TriageOutput, HealthOutput, DigestOutput


def check_schema_valid(output: TriageOutput) -> Tuple[bool, str]:
    """
    Tier 1, check 1 — schema validity. Pydantic already enforces this upstream:
    if we hold a TriageOutput at all, the model parsed correctly. This exists so
    the check appears in the recorded results for every run rather than being
    silently implicit.
    """
    return True, "Schema valid"


def check_conservation(
    output: TriageOutput, input_email_ids: List[str]
) -> Tuple[bool, str]:
    """
    Tier 1, check 2 — conservation. Every input email_id must appear exactly
    once across all buckets (urgent + opportunities + sales + uncategorized).
    Catches dropped emails (in input, missing from output), invented emails
    (in output, not in input), and duplicates (listed in more than one bucket).
    """
    buckets = (
        output.urgent + output.opportunities + output.sales + output.uncategorized
    )
    out_ids = [item.email_id for item in buckets]

    input_set = set(input_email_ids)
    out_set = set(out_ids)

    counts: dict = {}
    for i in out_ids:
        counts[i] = counts.get(i, 0) + 1

    dropped = sorted(input_set - out_set)
    invented = sorted(out_set - input_set)
    duplicated = sorted(i for i, c in counts.items() if c > 1)

    if not (dropped or invented or duplicated):
        return True, f"all {len(input_set)} input emails accounted for exactly once"

    parts = []
    if dropped:
        parts.append(f"{len(dropped)} dropped {dropped[:5]}")
    if invented:
        parts.append(f"{len(invented)} invented {invented[:5]}")
    if duplicated:
        parts.append(f"{len(duplicated)} duplicated {duplicated[:5]}")
    return False, "; ".join(parts)


def check_confidence_sanity(output: TriageOutput) -> Tuple[bool, str]:
    """
    Tier 1, check 3 — confidence sanity (advisory). Flags any urgent item with
    confidence below 0.5: if the agent isn't sure it's urgent, it probably
    shouldn't be in the bucket that pings the user. This is a warning, not a
    hard fail — it's logged for review.
    """
    flagged = [
        f"{item.subject[:40]!r} (conf {item.confidence:.2f})"
        for item in output.urgent
        if item.confidence < 0.5
    ]
    if not flagged:
        return True, "all urgent items at or above 0.5 confidence"
    return False, (
        f"warning: {len(flagged)} urgent item(s) below 0.5 confidence: "
        + "; ".join(flagged)
    )


def run_all_checks(
    output: TriageOutput, input_email_ids: List[str]
) -> List[dict]:
    """
    Run every Tier 1 check and return a flat list of results:
        [{"check": str, "passed": bool, "message": str}, ...]

    The eval logger consumes this list as-is (it defaults these to tier 1).
    """
    schema_passed, schema_msg = check_schema_valid(output)
    cons_passed, cons_msg = check_conservation(output, input_email_ids)
    conf_passed, conf_msg = check_confidence_sanity(output)

    return [
        {"check": "schema_valid", "passed": schema_passed, "message": schema_msg},
        {"check": "conservation", "passed": cons_passed, "message": cons_msg},
        {"check": "confidence_sanity", "passed": conf_passed, "message": conf_msg},
    ]


# ── Email digest ─────────────────────────────────────────────────────────────

def check_digest_delta_validity(output: DigestOutput) -> Tuple[bool, str]:
    """
    Tier 1 — delta validity. is_delta=True asserts this summary builds on a prior
    one, so it must name the prior context it builds on (delta_basis). A claimed
    delta with a null basis is a hallucinated continuity — the agent says it's
    updating something it can't point to — so we fail it.
    """
    violations = []
    for item in output.isw + output.research:
        if item.is_delta and not item.delta_basis:
            violations.append(item.title)
    if violations:
        return False, f"is_delta=True but delta_basis is null for: {violations}"
    return True, "Delta validity check passed"


def check_digest_summaries_not_empty(output: DigestOutput) -> Tuple[bool, str]:
    """
    Tier 1 — summary content. Every surfaced item must carry a real summary. An
    empty or near-empty summary means the agent put something in the digest
    without saying anything about it, which is worse than dropping it.
    """
    empty = []
    for item in output.isw + output.research:
        if not item.summary or len(item.summary.strip()) < 20:
            empty.append(item.title)
    if empty:
        return False, f"Empty or near-empty summaries found: {empty}"
    return True, "All summaries have content"


def run_digest_checks(output: DigestOutput) -> List[dict]:
    """
    Run every Tier 1 email-digest check and return the flat list-of-dicts shape
    the eval logger writes to Supabase.
    """
    results = []
    for fn, name in [
        (check_digest_delta_validity, "delta_validity"),
        (check_digest_summaries_not_empty, "summaries_not_empty"),
    ]:
        passed, msg = fn(output)
        results.append(
            {"check": name, "tier": 1, "passed": passed, "message": msg}
        )
    return results


# ── Health sync ──────────────────────────────────────────────────────────────

def check_health_numeric_consistency(output: HealthOutput) -> Tuple[bool, str]:
    """
    Tier 1 — numeric consistency. The week_* totals are computed in Python from
    the activity list (Claude only writes the narrative), so they must agree with
    the activities they were derived from. This catches a mismatch slipping in if
    the totals and the activity list ever drift apart.
    """
    # Verify week_distance_miles equals sum of activity distances.
    computed = sum(a.distance_miles for a in output.activities)
    if abs(computed - output.week_distance_miles) > 0.1:
        return False, (
            f"week_distance_miles {output.week_distance_miles} does not match "
            f"sum of activities {computed:.2f}"
        )

    # Verify week_activity_count equals len(activities).
    if output.week_activity_count != len(output.activities):
        return False, (
            f"week_activity_count {output.week_activity_count} does not match "
            f"activity count {len(output.activities)}"
        )

    return True, "Numeric consistency checks passed"


def run_health_checks(output: HealthOutput) -> List[dict]:
    """
    Run every Tier 1 health-sync check and return the flat list-of-dicts shape
    the eval logger writes to Supabase.
    """
    results = []
    passed, msg = check_health_numeric_consistency(output)
    results.append(
        {"check": "numeric_consistency", "tier": 1, "passed": passed, "message": msg}
    )
    return results
