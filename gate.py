import json
import os
from datetime import datetime, timezone
from strands import tool
from tools_settlement import STATE

LEDGER_PATH = os.path.join("data", "ledger.jsonl")
ESCALATION_PATH = os.path.join("data", "escalations.jsonl")
CONFIDENCE_THRESHOLD = 0.85  # below this, the agent refuses to act alone


# ---------- storage helpers (append-only, latest record wins) ----------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _append(path: str, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _in_ledger(platform: str, order_id: str) -> bool:
    return any(
        r.get("platform") == platform and r.get("order_id") == order_id
        for r in _read(LEDGER_PATH)
    )


def _latest_escalation(order_id: str):
    latest = None
    for r in _read(ESCALATION_PATH):
        if r.get("order_id") == order_id:
            latest = r
    return latest


def _owner_question(amount) -> str:
    return (
        f"{amount:,} KRW gap, cause unknown. "
        f"Do you know of a refund or adjustment on this order? "
        f"Reply 'approve' to file a dispute or 'dismiss' to close."
    )


# ---------- tools ----------

@tool
def decide_actions(platform: str) -> dict:
    """Fail-closed gate. For each flagged order in working state, decide
    whether the agent may act on its own (file a dispute in the ledger) or
    must stop and escalate to the owner.

    The decision uses ONLY the tool-computed confidence. Narrative reasoning,
    hypotheses, or hunches never change the verdict.

    Idempotent: an order already in the ledger, already awaiting the owner,
    or already dismissed by the owner is skipped, never re-filed or re-asked.

    Args:
        platform: Platform whose discrepancies were flagged.

    Returns:
        Summary counts and per-order verdicts.
    """
    flagged = STATE.get(platform, {}).get("flagged")
    if flagged is None:
        return {"error": f"flag_discrepancies('{platform}') must run first"}

    verdicts = []
    for f in flagged:
        conf = f.get("confidence") or 0.0
        order_id = f["order_id"]
        base = {
            "ts": _now(),
            "platform": platform,
            "order_id": order_id,
            "evidence": f.get("evidence"),
            "reasons": f.get("reasons", []),
            "amount_at_stake": f.get("amount_at_stake"),
            "confidence": conf,
        }

        if _in_ledger(platform, order_id):
            verdicts.append({**base, "action": "skipped_already_filed"})
            continue

        esc = _latest_escalation(order_id)
        if esc and esc.get("status") == "pending_owner":
            verdicts.append({**base, "action": "skipped_awaiting_owner"})
            continue
        if esc and esc.get("status") == "resolved_dismissed":
            verdicts.append({**base, "action": "skipped_dismissed_by_owner"})
            continue

        if conf >= CONFIDENCE_THRESHOLD:
            _append(LEDGER_PATH, {
                **base, "status": "dispute_filed", "decided_by": "agent",
            })
            verdicts.append({**base, "action": "auto_dispute"})
        else:
            question = _owner_question(f.get("amount_at_stake") or 0)
            _append(ESCALATION_PATH, {
                **base, "status": "pending_owner",
                "question_for_owner": question,
            })
            verdicts.append({
                **base, "action": "escalated",
                "question_for_owner": question,
            })

    STATE[platform]["verdicts"] = verdicts
    return {
        "threshold": CONFIDENCE_THRESHOLD,
        "auto_disputed": sum(1 for v in verdicts if v["action"] == "auto_dispute"),
        "escalated": sum(1 for v in verdicts if v["action"] == "escalated"),
        "skipped": sum(1 for v in verdicts if v["action"].startswith("skipped")),
        "verdicts": verdicts,
    }


@tool
def record_owner_decision(order_id: str, decision: str, note: str = "") -> dict:
    """Record the owner's decision on an escalated order. This is the ONLY
    path by which a low-confidence flag can become a filed dispute.

    Refuses if the order was never escalated or is already resolved.

    Args:
        order_id: The escalated order.
        decision: 'approve' to file the dispute, 'dismiss' to close it.
        note: Optional owner note, e.g. 'confirmed double deduction'.

    Returns:
        The recorded resolution, or an error.
    """
    decision = decision.strip().lower()
    if decision not in ("approve", "dismiss"):
        return {"error": "decision must be 'approve' or 'dismiss'"}

    esc = _latest_escalation(order_id)
    if esc is None:
        return {"error": f"{order_id} was never escalated; nothing to decide"}
    if esc.get("status") != "pending_owner":
        return {"error": f"{order_id} is already resolved ({esc['status']})"}

    status = "resolved_approved" if decision == "approve" else "resolved_dismissed"
    resolution = {
        "ts": _now(),
        "platform": esc.get("platform"),
        "order_id": order_id,
        "evidence": esc.get("evidence"),
        "amount_at_stake": esc.get("amount_at_stake"),
        "confidence": esc.get("confidence"),
        "status": status,
        "decided_by": "owner",
        "note": note,
    }
    _append(ESCALATION_PATH, resolution)

    if decision == "approve":
        _append(LEDGER_PATH, {
            "ts": _now(),
            "platform": esc.get("platform"),
            "order_id": order_id,
            "evidence": esc.get("evidence"),
            "reasons": esc.get("reasons", []),
            "amount_at_stake": esc.get("amount_at_stake"),
            "confidence": esc.get("confidence"),
            "status": "dispute_filed",
            "decided_by": "owner",
            "note": note,
        })
    return resolution


@tool
def list_pending_escalations(scope: str) -> dict:
    """List every order still waiting for the owner's decision.

    Args:
        scope: 'all' for every platform, or a platform name to filter.

    Returns:
        Pending escalations, each with the exact question for the owner.
    """
    scope = scope.strip().lower()
    latest = {}
    for r in _read(ESCALATION_PATH):
        latest[r["order_id"]] = r
    pending = [
        r for r in latest.values()
        if r.get("status") == "pending_owner"
        and (scope == "all" or r.get("platform") == scope)
    ]
    return {"scope": scope, "pending_count": len(pending), "pending": pending}