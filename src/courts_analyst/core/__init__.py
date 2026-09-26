"""Pure domain logic: provenance, measures, cohorts, explain, reconcile, guardrails.

Rule: nothing in this package may import fastmcp, mcp, starlette, fastapi or
any other adapter. MCP tools and REST endpoints call into core/, never the
other way round. tests/test_architecture.py enforces this.
"""
