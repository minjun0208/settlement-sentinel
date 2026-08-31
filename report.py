from strands import tool
from tools_settlement import STATE

PLATFORM_NAMES = {
    "baemin": "Baemin",
    "coupangeats": "Coupang Eats",
    "yogiyo": "Yogiyo",
}

STATUS_LABELS = {
    "auto_dispute": "Disputed (auto)",
    "escalated": "Escalated to owner",
    "skipped_already_filed": "Already filed",
    "skipped_awaiting_owner": "Awaiting owner",
    "skipped_dismissed_by_owner": "Dismissed by owner",
}


def _won(n) -> str:
    return f"{n:,}"


def _delta(n) -> str:
    return f"{n:+,}" if n else "0"


def _pct(r) -> str:
    return f"{r * 100:.1f}%"


@tool
def render_report(platform: str) -> str:
    """Render the final reconciliation report from working state and store
    it for the program to print. Every number comes straight from tool
    output; nothing is retyped by the model.

    Args:
        platform: Platform that went through the full workflow.

    Returns:
        The markdown report (for the model to read, not to copy).
    """
    st = STATE.get(platform, {})
    results = st.get("results")
    verdicts = st.get("verdicts")
    if results is None or verdicts is None:
        return ("ERROR: run load_settlement, recompute_deductions, "
                "flag_discrepancies and decide_actions first.")

    by_order = {v["order_id"]: v for v in verdicts}
    name = PLATFORM_NAMES.get(platform, platform)

    def status_of(order_id: str) -> str:
        v = by_order.get(order_id)
        return "Clean" if v is None else STATUS_LABELS.get(v["action"], v["action"])

    out = [f"## {name} — August 2026 Reconciliation", "", "### (a) Orders"]
    out.append(
        "| Order | Date | Amount | Stated rate | Contract rate | "
        "Stated comm. | Expected comm. | Comm. Δ | "
        "Stated settle. | Expected settle. | Settle. Δ | Status |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in results:
        out.append("| " + " | ".join([
            r["order_id"], r["order_date"], _won(r["order_amount"]),
            _pct(r["stated_rate"]), _pct(r["contract_rate"]),
            _won(r["stated_commission"]), _won(r["expected_commission"]),
            _delta(r["commission_delta"]),
            _won(r["stated_settlement"]), _won(r["expected_settlement"]),
            _delta(r["settlement_delta"]),
            status_of(r["order_id"]),
        ]) + " |")

    out += ["", "### (b) Gate verdicts"]
    if not verdicts:
        out.append("No discrepancies. Nothing to decide.")
    else:
        out.append("| Order | Evidence | Confidence | Amount at stake | Action |")
        out.append("|---|---|---:|---:|---|")
        for v in verdicts:
            out.append(
                f"| {v['order_id']} | {v['evidence']} | {v['confidence']:.2f} | "
                f"{_won(v['amount_at_stake'])} | {v['action']} |"
            )

    out += ["", "### (c) Questions for the owner"]
    questions = [v for v in verdicts if v["action"] == "escalated"]
    if not questions:
        out.append("None.")
    for v in questions:
        out.append(f"- **{v['order_id']}** — {v['question_for_owner']}")

    auto = sum(v["amount_at_stake"] for v in verdicts if v["action"] == "auto_dispute")
    esc = sum(v["amount_at_stake"] for v in verdicts if v["action"] == "escalated")
    skipped = sum(v["amount_at_stake"] for v in verdicts if v["action"].startswith("skipped"))
    out += [
        "", "### (d) Amount at stake (KRW)",
        f"- Auto-disputed: {_won(auto)}",
        f"- Escalated (awaiting owner): {_won(esc)}",
        f"- Already handled: {_won(skipped)}",
        f"- **Total: {_won(auto + esc + skipped)}**",
    ]
    text = "\n".join(out)
    STATE[platform]["report"] = text
    return text


def render_pending(pending: list) -> str:
    """Render the owner queue. Plain function (not a tool): the program
    prints this itself so the model never re-types an id, amount or question."""
    if not pending:
        return "### Pending for the owner\nNone."
    out = ["### Pending for the owner"]
    for p in pending:
        name = PLATFORM_NAMES.get(p.get("platform"), p.get("platform"))
        out.append(
            f"- **{p['order_id']}** ({name}) — {_won(p.get('amount_at_stake', 0))} KRW at stake\n"
            f"  {p.get('question_for_owner', '')}"
        )
    return "\n".join(out)
