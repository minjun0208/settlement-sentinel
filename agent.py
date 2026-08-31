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
from report import render_report

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
show each pending order as: platform, order id, amount at stake, then its
question_for_owner VERBATIM. Do not rewrite the question.
"""

# Pin the model explicitly so behaviour is reproducible across SDK versions
# and judge environments. Falls back to the Strands default if unset.
_model_id = os.getenv("BEDROCK_MODEL_ID")
_model = (
    BedrockModel(model_id=_model_id, region_name=os.getenv("AWS_REGION", "us-west-2"))
    if _model_id else None
)

agent = Agent(
    model=_model,
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

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in ("approve", "dismiss"):
        decision, order_id = args[0], args[1]
        note = " ".join(args[2:])
        agent(f"The owner says: {decision} {order_id}. Note: {note}")
    elif args and args[0] == "pending":
        agent("What is pending for the owner?")
    else:
        platform = args[0] if args else "baemin"
        agent(f"Reconcile the {platform} settlement for August 2026.")
        report = STATE.get(platform, {}).get("report")
        if report:
            print("\n" + report)
        else:
            print("\n[warning] no report rendered: the agent did not "
                  "complete the workflow. Nothing was filed.")