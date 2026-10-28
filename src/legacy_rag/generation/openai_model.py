from typing import TYPE_CHECKING

from legacy_rag.generation.models import GeneratedAnswer, GenerationRequest

if TYPE_CHECKING:
    from openai import OpenAI


class OpenAIGenerationModel:
    def __init__(self, *, client: "OpenAI", model: str, max_output_tokens: int) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    def generate(self, request: GenerationRequest) -> GeneratedAnswer:
        # Character guard includes the serialized context and system instructions.
        # This is not an exact tokenizer or a monetary budget.
        if len(request.system_prompt) + len(request.user_prompt) > 16000:
            raise ValueError("generation input too large")
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            text_format=GeneratedAnswer,
            max_output_tokens=self._max_output_tokens,
            reasoning={"effort": "none"},
            store=False,
        )
        # A provider safety refusal is not evidence of an insufficient-code answer.
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("generation response unavailable")
        return GeneratedAnswer.model_validate(response.output_parsed.model_dump())

    def close(self) -> None:
        self._client.close()


def create_openai_model(
    *, api_key: str, model: str, timeout_seconds: float, max_output_tokens: int,
) -> OpenAIGenerationModel:
    # Lazy import keeps disabled generation usable before the optional SDK is installed.
    import httpx
    from openai import DefaultHttpxClient, OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
        http_client=DefaultHttpxClient(trust_env=False),
    )
    return OpenAIGenerationModel(client=client, model=model, max_output_tokens=max_output_tokens)
