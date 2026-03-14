"""MCP server entry point — mounts all tool sub-servers."""

from fastmcp import FastMCP

mcp = FastMCP("team-memory-mcp")

# Sub-servers mounted here as they are implemented:
# from distill_mcp.tools.memory import memory_server
# mcp.mount("memory", memory_server)
