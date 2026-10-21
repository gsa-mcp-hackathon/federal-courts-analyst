from fastmcp import FastMCP

mcp = FastMCP("courts-mcp")


@mcp.tool
def hello(name: str) -> str:
    """Say hello. A placeholder to check the server works."""
    return f"Hello, {name}! The courts-mcp server is running."


if __name__ == "__main__":
    mcp.run()