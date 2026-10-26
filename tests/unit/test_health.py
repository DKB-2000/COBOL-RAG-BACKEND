from fastapi.testclient import TestClient

from legacy_rag.main import create_app


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_response_schema_is_exposed_in_openapi() -> None:
    schema = create_app().openapi()

    health_response = schema["paths"]["/health"]["get"]["responses"]["200"]
    response_schema = health_response["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/HealthResponse"}
