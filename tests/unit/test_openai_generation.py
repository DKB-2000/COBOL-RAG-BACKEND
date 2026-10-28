from types import SimpleNamespace

import pytest

from legacy_rag.generation.models import AnswerClaim, GeneratedAnswer, GenerationRequest
from legacy_rag.generation.openai_model import OpenAIGenerationModel


class Responses:
    def __init__(self, *, output=None, status="completed", error=None):
        self.output = output
        self.status = status
        self.error = error
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(status=self.status, output_parsed=self.output)


def model_for(responses):
    return OpenAIGenerationModel(
        client=SimpleNamespace(responses=responses), model="gpt-6-luna", max_output_tokens=1000,
    )


def test_openai_adapter_preserves_structured_claims_and_uses_bounded_stateless_request():
    expected = GeneratedAnswer(
        status="answered", claims=[AnswerClaim(text="초기화한다.", chunk_ids=["c1"])],
    )
    responses = Responses(output=expected)
    request = GenerationRequest("system instructions", '{"question":"초기화?"}')
    assert model_for(responses).generate(request) == expected
    sent = responses.calls[0]
    assert sent["input"] == [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": request.user_prompt},
    ]
    assert sent["text_format"] is GeneratedAnswer
    assert sent["store"] is False
    assert sent["max_output_tokens"] == 1000
    assert sent["reasoning"] == {"effort": "none"}
    assert "tools" not in sent and "previous_response_id" not in sent


@pytest.mark.parametrize("reason", ["insufficient_evidence", "conflicting_evidence"])
def test_openai_adapter_preserves_grounding_refusal(reason):
    expected = GeneratedAnswer(status="refused", reason=reason)
    assert model_for(Responses(output=expected)).generate(GenerationRequest("s", "u")) == expected


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_incomplete_response_is_rejected_even_when_partial_output_parsed(status):
    output = GeneratedAnswer(status="refused", reason="insufficient_evidence")
    with pytest.raises(ValueError, match="generation response unavailable"):
        model_for(Responses(output=output, status=status)).generate(GenerationRequest("s", "u"))


def test_missing_parsed_output_including_provider_safety_refusal_is_unavailable():
    with pytest.raises(ValueError, match="generation response unavailable"):
        model_for(Responses()).generate(GenerationRequest("s", "u"))


def test_adapter_revalidates_instances_that_bypass_pydantic_validation():
    malformed = GeneratedAnswer.model_construct(status="answered", claims=[], reason=None)
    with pytest.raises(ValueError):
        model_for(Responses(output=malformed)).generate(GenerationRequest("s", "u"))


def test_oversized_serialized_prompt_is_rejected_before_provider_call():
    responses = Responses()
    with pytest.raises(ValueError, match="generation input too large"):
        model_for(responses).generate(GenerationRequest("s", "x" * 16000))
    assert responses.calls == []
