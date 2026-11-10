"""Validation-retry behavior with a stub client. The malformed outputs here are INJECTED faults:
native structured outputs make malformed JSON rare in practice."""

import json
from types import SimpleNamespace

import pytest

from app.llm import LLMError, call_model
from tests.helpers import model_output_dict


def _resp(text: str, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1500, output_tokens=400, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )


class StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


VALID = json.dumps(model_output_dict())


def test_malformed_json_is_retried_then_succeeds():
    client = StubClient([_resp(VALID[:120]), _resp(VALID)])  # first response truncated mid-JSON
    out, tally = call_model([b"img"], model_id="claude-sonnet-5-5", effort="medium", client=client)
    assert tally.attempts == 2
    assert tally.input_tokens == 3000 and tally.output_tokens == 800  # both attempts are billed
    assert out.vehicle.make.value == "Toyota"
    retry_text = client.requests[1]["messages"][0]["content"][-1]["text"]
    assert "failed validation" in retry_text


def test_semantic_error_is_retried_with_reason():
    bad = model_output_dict()
    bad["damage"][0]["photo_index"] = 7  # photo 7 doesn't exist
    client = StubClient([_resp(json.dumps(bad)), _resp(VALID)])
    _, tally = call_model([b"img"], model_id="claude-sonnet-5-5", effort="medium", client=client)
    assert tally.attempts == 2
    assert "don't exist" in client.requests[1]["messages"][0]["content"][-1]["text"]


def test_gives_up_after_two_retries():
    client = StubClient([_resp("{not json")] * 3)
    with pytest.raises(LLMError, match="after 3 attempts") as e:
        call_model([b"img"], model_id="claude-sonnet-5-5", effort="medium", client=client)
    assert e.value.usage.attempts == 3


def test_refusal_is_not_retried_and_not_fabricated():
    client = StubClient([_resp("", stop_reason="refusal")])
    with pytest.raises(LLMError, match="declined"):
        call_model([b"img"], model_id="claude-sonnet-5-5", effort="medium", client=client)
    assert len(client.requests) == 1


def test_request_uses_native_structured_output_not_forced_tools():
    client = StubClient([_resp(VALID)])
    call_model([b"img"], model_id="claude-sonnet-5-5", effort="medium", client=client)
    req = client.requests[0]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in req and "tools" not in req and "temperature" not in req
