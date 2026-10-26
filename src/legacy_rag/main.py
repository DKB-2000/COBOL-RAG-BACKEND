from fastapi import FastAPI

from legacy_rag.api.routes.documents import router as documents_router
from legacy_rag.api.routes.health import router as health_router
from legacy_rag.api.routes.query import router as query_router
from legacy_rag.api.routes.search import router as search_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Legacy Code RAG Backend",
        version="0.1.0",
        description="Evidence-backed search and answers for legacy source code.",
    )
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(query_router)
    return app


app = create_app()
