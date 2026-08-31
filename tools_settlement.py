import csv
import os
from strands import tool

DATA_DIR = "data"
TOLERANCE = 1  # KRW rounding tolerance

# Owner-side source of truth. Never taken from the platform's statement.
CONTRACT_RATES = {
    "baemin": 0.068,
    "coupangeats": 0.099,
    "yogiyo": 0.126,
}

# Run-scoped working state, keyed by platform.
# Tools hand data to each other through this store, so numbers never
# round-trip through the language model.
STATE: dict = {}


def _get(platform: str, key: str):
    return STATE.get(platform, {}).get(key)


@tool
def load_settlement(platform: str) -> dict:
    """Load a delivery platform's settlement statement into working state.

    Args:
        platform: One of 'baemin', 'coupangeats', 'yogiyo'.

    Returns:
        Row count and order ids loaded. Full rows stay in working state.
    """
    path = os.path.join(DATA_DIR, f"{platform}_2026-08.csv")
    if not os.path.exists(path):
        return {"error": f"No statement found for platform '{platform}'"}

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "order_id": r["order_id"],
                "order_date": r["order_date"],
                "order_amount": int(r["order_amount"]),
                "stated_rate": float(r["commission_rate"]),
                "commission": int(r["commission"]),
                "delivery_fee": int(r["delivery_fee"]),
                "promo_discount": int(r["promo_discount"]),
                "settlement": int(r["settlement"]),
            })
    STATE[platform] = {"rows": rows}
    return {
        "platform": platform,
        "row_count": len(rows),
        "order_ids": [r["order_id"] for r in rows],
    }


@tool
def recompute_deductions(platform: str) -> dict:
    """Recompute commission and net settlement for every loaded order using
    the OWNER'S CONTRACT RATE, not the rate printed on the statement.

    Args:
        platform: Platform whose statement was loaded.

    Returns:
        Count checked and ids with any delta. Details stay in working state.
    """
    rows = _get(platform, "rows")
    if rows is None:
        return {"error": f"load_settlement('{platform}') must run first"}
    contract_rate = CONTRACT_RATES.get(platform)
    if contract_rate is None:
        return {"error": f"no contract rate on file for '{platform}'"}

    results = []
    for r in rows:
        expected_commission = round(r["order_amount"] * contract_rate)
        expected_settlement = (
            r["order_amount"]
            - expected_commission
            - r["delivery_fee"]
            - r["promo_discount"]
        )
        results.append({
            "order_id": r["order_id"],
            "order_date": r["order_date"],
            "order_amount": r["order_amount"],
            "contract_rate": contract_rate,
            "stated_rate": r["stated_rate"],
            "rate_mismatch": abs(r["stated_rate"] - contract_rate) > 1e-9,
            "stated_commission": r["commission"],
            "expected_commission": expected_commission,
            "commission_delta": r["commission"] - expected_commission,
            "stated_settlement": r["settlement"],
            "expected_settlement": expected_settlement,
            "settlement_delta": r["settlement"] - expected_settlement,
        })
    STATE[platform]["results"] = results

    with_deltas = [
        x["order_id"] for x in results
        if x["rate_mismatch"]
        or abs(x["commission_delta"]) > TOLERANCE
        or abs(x["settlement_delta"]) > TOLERANCE
    ]
    return {
        "platform": platform,
        "checked": len(results),
        "orders_with_deltas": with_deltas,
    }


@tool
def flag_discrepancies(platform: str) -> dict:
    """Flag orders whose figures do not reconcile against the owner's
    contract. Each flag carries two SEPARATE signals:
      - confidence: how certain the check is that a real discrepancy exists,
        driven by the TYPE of evidence, never by the amount
      - amount_at_stake: materiality in KRW

    Args:
        platform: Platform whose deductions were recomputed.

    Returns:
        Flagged orders with evidence type, reasons, amount, and confidence.
    """
    results = _get(platform, "results")
    if results is None:
        return {"error": f"recompute_deductions('{platform}') must run first"}

    flagged = []
    for r in results:
        c_delta = abs(r["commission_delta"])
        s_delta = abs(r["settlement_delta"])
        reasons = []

        if r["rate_mismatch"]:
            evidence, confidence = "rate_mismatch", 0.95
            reasons.append(
                f"statement rate {r['stated_rate']} differs from "
                f"contract rate {r['contract_rate']}"
            )
        elif c_delta > TOLERANCE:
            evidence, confidence = "arithmetic_error", 0.90
        elif s_delta > TOLERANCE:
            evidence, confidence = "unexplained_settlement_gap", 0.55
            reasons.append(
                "commission matches contract but net settlement does not; "
                "cause unknown"
            )
        else:
            continue

        if c_delta > TOLERANCE:
            reasons.append(f"commission off by {r['commission_delta']:+d} KRW")
        if s_delta > TOLERANCE:
            reasons.append(f"settlement off by {r['settlement_delta']:+d} KRW")

        flagged.append({
            "order_id": r["order_id"],
            "evidence": evidence,
            "reasons": reasons,
            "amount_at_stake": max(c_delta, s_delta),
            "confidence": confidence,
        })
    STATE[platform]["flagged"] = flagged
    return {
        "platform": platform,
        "flagged_count": len(flagged),
        "clean_count": len(results) - len(flagged),
        "flagged": flagged,
    }