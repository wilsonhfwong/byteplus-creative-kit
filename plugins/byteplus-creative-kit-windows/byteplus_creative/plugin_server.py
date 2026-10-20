"""Private worker launched by the native desktop plugin, never by a customer."""
from __future__ import annotations

import asyncio
import json
import sys

from .launcher import build_server
from .settings import DEFAULTS, configure_environment, load_settings
from .tools import guarded


def combined_server(settings: dict):
    server = build_server("seedance", settings)
    configure_environment(settings)
    from seedream_mcp import server as seedream
    for name in ("seedream_generate", "seedream_list_models", "seedream_ping"):
        server.tool()(guarded(getattr(seedream, name), settings))
    return server


def main():
    if "--export-tools" in sys.argv:
        # Include the optional text tool in the facade's stable discovery list.
        server = combined_server({**DEFAULTS, "seed_model": "schema-export-only"})
        tools = asyncio.run(server.list_tools())
        print(json.dumps([tool.model_dump(by_alias=True, exclude_none=True) for tool in tools], ensure_ascii=False, indent=2))
    else:
        combined_server(load_settings()).run(transport="stdio")


if __name__ == "__main__":
    main()
