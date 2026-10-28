from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from legacy_rag.api.dependencies import close_generation_model
from legacy_rag.api.routes.documents import router as documents_router
from legacy_rag.api.routes.health import router as health_router
from legacy_rag.api.routes.query import router as query_router
from legacy_rag.api.routes.search import router as search_router
from legacy_rag.api.runtime import SafeRequestMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        close_generation_model()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Legacy Code RAG Backend",
        version="0.1.0",
        description="Evidence-backed search and answers for legacy source code.",
        lifespan=lifespan,
    )
    app.add_middleware(SafeRequestMiddleware)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(query_router)
    return app


app = create_app()
