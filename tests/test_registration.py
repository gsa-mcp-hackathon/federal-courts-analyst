"""MCP protocol: what the server advertises, over both protocol eras."""

from __future__ import annotations

from fastmcp import Client

from courts_analyst import SERVER_NAME, __version__

# Update these as tools, resources and prompts are added (P5).
EXPECTED_TOOLS = {"server_info"}
EXPECTED_RESOURCES: set[str] = set()
EXPECTED_PROMPTS: set[str] = set()


async def test_lists_expected_tools(client: Client) -> None:
    tools = await client.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_tool_order_is_deterministic(client: Client) -> None:
    # Spec 2026-07-28 asks for a stable tools/list order (prompt-cache friendly).
    first = [t.name for t in await client.list_tools()]
    second = [t.name for t in await client.list_tools()]
    assert first == second


async def test_lists_expected_resources_and_prompts(client: Client) -> None:
    resources = await client.list_resources()
    templates = await client.list_resource_templates()
    prompts = await client.list_prompts()
    assert {str(r.uri) for r in resources} | {
        t.uri_template for t in templates
    } == EXPECTED_RESOURCES
    assert {p.name for p in prompts} == EXPECTED_PROMPTS


async def test_every_tool_has_description_schema_and_annotations(
    client: Client,
) -> None:
    for tool in await client.list_tools():
        assert tool.description and len(tool.description) > 40, tool.name
        assert tool.output_schema, f"{tool.name} has no outputSchema"
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is True, tool.name


async def test_server_info_structured_output(client: Client) -> None:
    result = await client.call_tool("server_info", {})
    data = result.structured_content
    assert data is not None
    assert data["name"] == SERVER_NAME
    assert data["version"] == __version__
    assert data["protocol_versions"][0] == "2026-07-28"
    assert "2025-11-25" in data["protocol_versions"]
    assert data["tools"] == sorted(EXPECTED_TOOLS)
    assert data["data_status"] in {"ready", "not_built"}


async def test_server_info_output_matches_its_schema(client: Client) -> None:
    tool = next(t for t in await client.list_tools() if t.name == "server_info")
    result = await client.call_tool("server_info", {})
    assert tool.output_schema is not None
    assert set(tool.output_schema["required"]) <= set(result.structured_content or {})


async def test_legacy_clients_still_work(legacy_client: Client) -> None:
    tools = await legacy_client.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    result = await legacy_client.call_tool("server_info", {})
    assert result.structured_content is not None
    assert result.structured_content["name"] == SERVER_NAME


async def test_data_status_reflects_duckdb_file(
    client: Client, tmp_path, monkeypatch
) -> None:
    from courts_analyst.config import settings

    db = tmp_path / "courts.duckdb"
    monkeypatch.setattr(settings, "duckdb_path", db)

    result = await client.call_tool("server_info", {})
    assert result.structured_content["data_status"] == "not_built"

    db.write_bytes(b"")
    result = await client.call_tool("server_info", {})
    assert result.structured_content["data_status"] == "ready"
