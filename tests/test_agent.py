import json
from types import SimpleNamespace

import openai
import pytest

from app.agent import groq_agent, scripted_agent
from app.config import get_settings


def test_scripted_agent_hits_all_three_outcomes(guard):
    log = scripted_agent.run(guard, confirm=lambda tx: True)
    assert [tx.decision for _, tx in log.steps] == ["approve", "approve", "confirm", "reject"]
    assert [tx.status for _, tx in log.steps] == ["executed", "executed", "executed", "rejected"]


def test_scripted_agent_with_human_saying_no(guard):
    log = scripted_agent.run(guard, confirm=lambda tx: False)
    statuses = [tx.status for _, tx in log.steps]
    assert statuses == ["executed", "executed", "denied", "executed"]  # denial freed the capacity


def call(args, id_="c1"):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name="propose_payment", arguments=json.dumps(args)))


def reply(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


class FakeLLM:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def item(merchant, amount, category="software"):
    return {"merchant": merchant, "category": category, "description": "x", "amount": amount, "currency": "EUR"}


@pytest.fixture
def settings():
    return get_settings().model_copy(update={"groq_api_key": "gsk_test"})


def test_llm_agent_proposals_go_through_the_guard(guard, settings):
    llm = FakeLLM(
        reply(tool_calls=[call(item("Groq Cloud", "20.00"), "a"), call(item("PyCon", "149.00", "events"), "b")]),
        reply(tool_calls=[call(item("Lambda", "40.00", "compute"), "c")]),
        reply("Bought credits and the ticket; GPU hours were rejected by the daily cap."),
    )
    asked = []
    log, summary = groq_agent.run(guard, lambda tx: asked.append(tx.id) or True, settings, llm=llm)
    assert [tx.status for _, tx in log.steps] == ["executed", "executed", "rejected"]
    assert len(asked) == 1  # only the over-cap payment went to the human
    assert "rejected" in summary
    assert llm.requests[0]["model"] == "llama-3.3-70b-versatile"
    rejected_result = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert rejected_result["status"] == "rejected" and "daily cap" in rejected_result["reason"]


def test_llm_agent_cannot_approve_itself(guard, settings):
    """The only tool is propose_payment: there is no approve/confirm tool to call."""
    assert [t["function"]["name"] for t in [groq_agent.TOOL]] == ["propose_payment"]
    llm = FakeLLM(reply(tool_calls=[SimpleNamespace(id="x", function=SimpleNamespace(
        name="confirm_payment", arguments="{}"))]), reply("ok"))
    log, _ = groq_agent.run(guard, lambda tx: True, settings, llm=llm)
    assert log.steps == [] and "unknown tool" in llm.requests[1]["messages"][-1]["content"]


def test_llm_bad_arguments_reported_back(guard, settings):
    llm = FakeLLM(reply(tool_calls=[call({"merchant": "X", "amount": "abc", "description": "d",
                                          "category": "c", "currency": "EUR"})]), reply("done"))
    groq_agent.run(guard, lambda tx: True, settings, llm=llm)
    assert "invalid arguments" in llm.requests[1]["messages"][-1]["content"]


def test_llm_failure_raises(guard, settings):
    with pytest.raises(groq_agent.AgentError):
        groq_agent.run(guard, lambda tx: True, settings, llm=FakeLLM(openai.APIConnectionError(request=None)))
