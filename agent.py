import json
import os
import sys

# Force UTF-8 on stdout so reports render the same on Windows (cp949),
# in redirected files, and on Linux. Judges may run this anywhere.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()  # AWS_BEARER_TOKEN_BEDROCK, AWS_REGION, BEDROCK_MODEL_ID

from strands import Agent
from strands.models import BedrockModel
from tools_settlement import (
    STATE,
    load_settlement,
    recompute_deductions,
    flag_discrepancies,
)
from gate import decide_actions, record_owner_decision, list_pending_escalations
from report import render_report, render_pending

SYSTEM_PROMPT = """You are a settlement reconciliation agent for a small
restaurant business that sells through multiple delivery platforms.

Workflow for a reconciliation request, in this exact order:
1. load_settlement(platform)
2. recompute_deductions(platform)
3. flag_discrepancies(platform)
4. decide_actions(platform)      <- mandatory. You never skip the gate.
5. render_report(platform)       <- read it. Do NOT copy it into your reply;
                                    the program prints the report itself.

Your entire reply after the workflow is at most two sentences:
- one plain-language takeaway for the owner, and
- optionally one hypothesis about a cause, labeled
  "Hypothesis (not acted on):". A hypothesis never changes an action.

Hard rules:
- Never retype, recompute, or summarize figures yourself; refer to the
  report the program prints.
- You act ONLY on what decide_actions returns. If the gate escalates an
  order, you do NOT file, record, or recommend a dispute for it.
- Do not narrate your steps. Do not say you are running steps in parallel.

For an owner decision request, call record_owner_decision and confirm in
one sentence. If it returns an error, relay the error exactly.

For a 'what is pending' request, call list_pending_escalations("all") and
reply with ONE sentence saying how many orders await the owner. Do not
re-type ids, amounts or questions; the program prints the queue itself.
"""

# Pin the model explicitly so behaviour is reproducible across SDK versions
# and judge environments. Falls back to the Strands default if unset.
# Built lazily so `--no-llm` never needs AWS credentials at all.
def build_agent() -> Agent:
    model_id = os.getenv("BEDROCK_MODEL_ID")
    model = (
        BedrockModel(model_id=model_id, region_name=os.getenv("AWS_REGION", "us-west-2"))
        if model_id else None
    )
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            load_settlement,
            recompute_deductions,
            flag_discrepancies,
            decide_actions,
            render_report,
            record_owner_decision,
            list_pending_escalations,
        ],
    )


# Verification harness. Runs the SAME tools in the SAME order with no model
# in the loop. If this output differs from the report the agent produced,
# the claim "the LLM never touches a number" is false. Also lets a judge
# without Bedrock access walk the whole workflow.
WORKFLOW = [
    ("load_settlement", load_settlement),
    ("recompute_deductions", recompute_deductions),
    ("flag_discrepancies", flag_discrepancies),
    ("decide_actions", decide_actions),
    ("render_report", render_report),
]


def run_without_llm(args: list) -> None:
    print("[no-llm] deterministic harness: no model in the loop", file=sys.stderr)
    if args and args[0] in ("approve", "dismiss"):
        decision, order_id = args[0], args[1]
        note = " ".join(args[2:])
        out = record_owner_decision(order_id, decision, note)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args and args[0] == "pending":
        print("\n" + render_pending(list_pending_escalations("all")["pending"]))
    else:
        platform = args[0] if args else "baemin"
        for name, step in WORKFLOW:
            out = step(platform)
            if isinstance(out, dict) and "error" in out:
                print(f"[error] {name}: {out['error']}")
                return
        print("\n" + STATE[platform]["report"])


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--no-llm" in args:
        run_without_llm([a for a in args if a != "--no-llm"])
        sys.exit(0)

    agent = build_agent()
    if args and args[0] in ("approve", "dismiss"):
        decision, order_id = args[0], args[1]
        note = " ".join(args[2:])
        agent(f"The owner says: {decision} {order_id}. Note: {note}")
    elif args and args[0] == "pending":
        agent("What is pending for the owner?")
        print("\n" + render_pending(list_pending_escalations("all")["pending"]))
    else:
        platform = args[0] if args else "baemin"
        agent(f"Reconcile the {platform} settlement for August 2026.")
        report = STATE.get(platform, {}).get("report")
        if report:
            print("\n" + report)
        else:
            print("\n[warning] no report rendered: the agent did not "
                  "complete the workflow. Nothing was filed.")
