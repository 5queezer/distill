"""Entry point — starts the MCP server via stdio."""

from distill_mcp.server import mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
