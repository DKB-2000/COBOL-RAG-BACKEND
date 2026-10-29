import httpx

from legacy_rag.generation.models import GeneratedAnswer, GenerationRequest


class OllamaGenerationModel:
    """Local Qwen3 adapter; parse only the completed final JSON, never thinking text."""

    def __init__(self, *, client: httpx.Client, max_output_tokens: int) -> None:
        self._client = client
        self._max_output_tokens = max_output_tokens

    def generate(self, request: GenerationRequest) -> GeneratedAnswer:
        # Character guard, not an exact tokenizer or context-window guarantee.
        if len(request.system_prompt) + len(request.user_prompt) > 16000:
            raise ValueError("generation input too large")
        schema = GeneratedAnswer.model_json_schema()
        # Match the required output fields used by the OpenAI strict-schema adapter.
        schema["required"] = list(schema["properties"])
        response = self._client.post(
            "/api/chat",
            json={
                "model": "qwen3:4b",
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                "format": schema,
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "temperature": 0, "num_ctx": 8192,
                    "num_predict": self._max_output_tokens,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("done") is not True or payload.get("done_reason") != "stop":
            raise ValueError("generation response unavailable")
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("generation response unavailable")
        return GeneratedAnswer.model_validate_json(message.get("content"))

    def close(self) -> None:
        self._client.close()


def create_ollama_model(
    *, timeout_seconds: float, max_output_tokens: int,
) -> OllamaGenerationModel:
    # A fixed loopback endpoint/model avoids remote hosts, cloud tags and environment proxies.
    client = httpx.Client(
        base_url="http://127.0.0.1:11434",
        timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
        trust_env=False,
        follow_redirects=False,
    )
    return OllamaGenerationModel(client=client, max_output_tokens=max_output_tokens)
