FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid rag --no-create-home --home-dir /app rag \
    && mkdir -p /var/lib/legacy-rag/chroma /app/data/samples /models \
    && chown -R rag:rag /var/lib/legacy-rag

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir ".[openai,reranking]"
COPY logging.json ./

USER 10001:10001
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "legacy_rag.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--log-config", "/app/logging.json"]
