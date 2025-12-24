# main.py
import os
import uuid
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents import Agent, Runner, function_tool  # Agents SDK :contentReference[oaicite:4]{index=4}
from pega_client import PegaClient


# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="MCR Agent Service", version="1.0.0")
pega = PegaClient()


@app.get("/health")
def health():
    return {"ok": True}


# ----------------------------
# Request/Response Models
# ----------------------------
class AgentRunRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    # optional context from Pega (user id, ticket, locale, etc.)
    context: Dict[str, Any] = Field(default_factory=dict)
    # output format: "html" or "json"
    output: str = "json"


class AgentRunResponse(BaseModel):
    correlation_id: str
    output: Any
    # optional debug trace summary (safe)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)


# ----------------------------
# Tool wrappers -> Pega REST services
# ----------------------------
# IMPORTANT: These are "thin tools" that call Pega. Pega owns business logic.

@function_tool
async def checking_ticket_eligibility(ticket_number: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to check if a ticket is eligible for online processing."""
    return await pega.post(
        "/mcr/tickets/eligibility",
        {"ticketNumber": ticket_number},
        correlation_id=correlation_id,
    )

@function_tool
async def checking_ticket_details(ticket_number: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to fetch ticket details."""
    return await pega.post(
        "/mcr/tickets/details",
        {"ticketNumber": ticket_number},
        correlation_id=correlation_id,
    )

@function_tool
async def creating_plea_online_case(ticket_number: str, plea: str, defendant_email: Optional[str] = None,
                                   correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to create a Plea Online case."""
    return await pega.post(
        "/mcr/cases/plea-online",
        {"ticketNumber": ticket_number, "plea": plea, "defendantEmail": defendant_email},
        correlation_id=correlation_id,
    )

@function_tool
async def creating_request_plea_offer_case(ticket_number: str, reason: str, defendant_email: Optional[str] = None,
                                          correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to create a Request Plea Offer case."""
    return await pega.post(
        "/mcr/cases/request-plea-offer",
        {"ticketNumber": ticket_number, "reason": reason, "defendantEmail": defendant_email},
        correlation_id=correlation_id,
    )

@function_tool
async def initiating_prosecutor_plea_offer_case(ticket_number: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to initiate prosecutor plea offer workflow."""
    return await pega.post(
        "/mcr/cases/prosecutor-offer/initiate",
        {"ticketNumber": ticket_number},
        correlation_id=correlation_id,
    )

@function_tool
async def show_prosecutor_plea_offer_list(ticket_number: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """Call Pega to retrieve prosecutor offer list."""
    return await pega.post(
        "/mcr/tickets/prosecutor-offers",
        {"ticketNumber": ticket_number},
        correlation_id=correlation_id,
    )

@function_tool
async def send_email_with_case_confirmation(case_id: str, to_email: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Call Pega to generate/queue an email confirmation.
    Recommended: Pega returns preview payload (subject/body/template vars) instead of sending directly.
    """
    return await pega.post(
        f"/mcr/cases/{case_id}/email/preview",
        {"toEmail": to_email},
        correlation_id=correlation_id,
    )


# ----------------------------
# Agent instructions
# ----------------------------
AGENT_INSTRUCTIONS = """
You are the Municipal Case Resolution assistant for NJ Courts.

You must use tools to do work. Do NOT invent outcomes.
Workflow rules:
1) If creating/initiating a case, call checking_ticket_eligibility first.
   - If ineligible, stop and return a clear result.
2) If user pleads guilty/not guilty: 
   - call creating_plea_online_case.
   - call send_email_with_case_confirmation.
3) If user requests prosecutor offer / disputes: 
   - call creating_request_plea_offer_case.
   - call send_email_with_case_confirmation.
4) If user asks to initiate prosecutor workflow: 
   - call initiating_prosecutor_plea_offer_case.
   - call send_email_with_case_confirmation.
5) If user asks to email confirmation/details:
   - Only do it by calling send_email_with_case_confirmation after you have a case_id.
Output:
- If output format requested is JSON: return a short JSON UI model with "cards".
- If output format requested is HTML: return a single HTML fragment, no scripts.
"""


agent = Agent(
    name="MCR Tools Agent",
    instructions=AGENT_INSTRUCTIONS,
    model=os.getenv("OPENAI_MODEL", "gpt-5-nano"),
    tools=[
        checking_ticket_eligibility,
        checking_ticket_details,
        creating_plea_online_case,
        creating_request_plea_offer_case,
        initiating_prosecutor_plea_offer_case,
        show_prosecutor_plea_offer_list,
        send_email_with_case_confirmation,
    ],
)


def _extract_text(run_result) -> str:
    # best-effort across SDK versions
    for attr in ("final_output", "output_text", "final_response", "text"):
        if hasattr(run_result, attr):
            v = getattr(run_result, attr)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(run_result).strip()


# ----------------------------
# REST endpoint: Pega -> Agent Service
# ----------------------------
@app.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(req: AgentRunRequest):
    correlation_id = req.correlation_id or str(uuid.uuid4())

    # Provide correlation_id to the agent via prompt/context.
    # Simplest approach: append it to the prompt and ensure tools accept correlation_id param.
    prompt = (
        f"[correlation_id={correlation_id}]\n"
        f"[output_format={req.output}]\n"
        f"{req.prompt}"
    )

    try:
        # Agents SDK built-in loop handles multi-tool sequences :contentReference[oaicite:5]{index=5}
        rr = await Runner.run(agent, prompt)
        final = _extract_text(rr)

        # Optional: extract tool calls if available (varies by SDK version)
        tool_calls = []
        for attr in ("new_items", "items", "steps", "trace"):
            if hasattr(rr, attr):
                val = getattr(rr, attr)
                # Keep it simple/safe: don't dump everything; you can customize later.
                tool_calls = [{"debug_attr": attr}]
                break

        # Return either raw HTML or JSON UI model (your agent instructions should follow this)
        return AgentRunResponse(correlation_id=correlation_id, output=final, tool_calls=tool_calls)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent run failed: {e}")
