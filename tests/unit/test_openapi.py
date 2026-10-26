from legacy_rag.main import create_app


def test_openapi_exposes_index_and_search_contracts() -> None:
    schema = create_app().openapi()

    index_operation = schema["paths"]["/documents/index"]["post"]
    assert index_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/IndexDocumentsRequest"
    }
    assert index_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/IndexDocumentsResponse"
    }

    search_operation = schema["paths"]["/search"]["post"]
    assert search_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SearchRequest"
    }
    assert search_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SearchResponse"
    }
