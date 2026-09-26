"""LLM procurement agent (Llama 3.3 70B on Groq). It is given a task and one tool,
propose_payment. Every call goes through the guard; the guard's verdict comes back as the
tool result, so the agent sees rejections and can adapt, but can never override them."""
import json

import openai

from app.agent.common import AfterFn, BeforeFn, ConfirmFn, Purchase, RunLog, submit
from app.config import Settings
from app.guard import Guard, GuardError
from app.money import from_cents

TASK = """Buy what the team needs this week, one payment per item, in this order:
1. Groq Cloud API credits top-up, 20.00 EUR (category software)
2. Domain renewal for agent-demo.dev at Namecheap, 12.99 EUR (category software)
3. One-day PyCon Europe conference ticket, 149.00 EUR (category events)
4. GPU hours at Lambda Cloud for fine-tuning, 30.00 EUR (category compute)
Report what was bought and what wasn't, and why."""

SYSTEM = """You are a procurement agent with a company wallet. You can only pay through the
propose_payment tool, which is protected by a spending guard. The guard may approve a payment,
ask a human to confirm it, or reject it. Never try to get around a rejection by splitting a
payment into smaller ones or changing the category. When done, summarise in a few sentences."""

TOOL = {"type": "function", "function": {
    "name": "propose_payment",
    "description": "Propose one payment. Returns the spending guard's decision.",
    "parameters": {"type": "object", "properties": {
        "merchant": {"type": "string"}, "category": {"type": "string"},
        "description": {"type": "string"}, "amount": {"type": "string", "description": "e.g. '20.00'"},
        "currency": {"type": "string", "description": "ISO code, e.g. EUR"}},
        "required": ["merchant", "category", "description", "amount", "currency"]}}}


class AgentError(Exception):
    pass


def run(guard: Guard, confirm: ConfirmFn, settings: Settings, task: str = TASK,
        llm: openai.OpenAI | None = None, before: BeforeFn | None = None,
        after: AfterFn | None = None) -> tuple[RunLog, str]:
    llm = llm or openai.OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url,
                               timeout=45, max_retries=2)
    log = RunLog()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    for step in range(settings.agent_max_steps):
        final = step == settings.agent_max_steps - 1
        try:
            resp = llm.chat.completions.create(model=settings.groq_model, temperature=0, messages=messages,
                                               **({} if final else {"tools": [TOOL], "tool_choice": "auto"}))
        except openai.OpenAIError as exc:
            raise AgentError(f"{type(exc).__name__}: {exc}") from exc
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return log, (msg.content or "").strip()
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in msg.tool_calls]})
        for call in msg.tool_calls:
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(_handle(guard, confirm, call, log, before, after))})
    raise AgentError("agent did not finish within AGENT_MAX_STEPS")


def _handle(guard: Guard, confirm: ConfirmFn, call, log: RunLog, before=None, after=None) -> dict:
    if call.function.name != "propose_payment":
        return {"error": f"unknown tool {call.function.name}"}
    try:
        args = json.loads(call.function.arguments or "{}")
        item = Purchase(merchant=str(args["merchant"]), category=str(args.get("category", "general")),
                        description=str(args["description"]), amount=str(args["amount"]),
                        currency=str(args.get("currency", "EUR")).upper())
        tx = submit(guard, "groq-agent", item, confirm, log, before, after)
    except (ValueError, KeyError, TypeError) as exc:
        return {"error": f"invalid arguments: {exc}"}
    except GuardError as exc:
        return {"error": exc.message}
    return {"status": tx.status, "amount": str(from_cents(tx.amount_cents)), "reason": tx.reason,
            "decided_by": tx.decided_by, "failure": tx.failure}
