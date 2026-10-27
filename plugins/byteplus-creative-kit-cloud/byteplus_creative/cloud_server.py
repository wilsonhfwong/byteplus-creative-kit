"""Cloud stdio MCP entrypoint; can start before credentials are configured."""
from __future__ import annotations
import argparse
import asyncio
import json
from .settings import DATA_DIR, OUTPUT_DIR, load_settings
from .plugin_server import combined_server


def status(settings):
    return {
        "runtime": "ready", "transport": "stdio", "configuration_source": "environment",
        "generation_configured": bool(settings.get("api_key")),
        "asset_library_configured": bool(settings.get("access_key") and settings.get("secret_key")),
        "tos_configured": bool(settings.get("tos_bucket") and
            (settings.get("tos_access_key") or settings.get("access_key")) and
            (settings.get("tos_secret_key") or settings.get("secret_key"))),
        "seed_text_configured": bool(settings.get("seed_model") and settings.get("api_key")),
        "data_directory": str(DATA_DIR), "output_directory": str(OUTPUT_DIR),
        "provider_connectivity": "not_checked",
        "note": "Restart the MCP process after changing environment variables. Configuration flags do not verify provider access.",
    }


def create_server():
    from mcp.types import ToolAnnotations
    settings = load_settings()
    server = combined_server(settings)
    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def creative_kit_status() -> dict:
        """Report cloud configuration booleans and workspace paths, without secrets or provider requests."""
        return status(settings)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Print configuration status without contacting BytePlus")
    parser.add_argument("--export-tools", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(status(load_settings()), indent=2))
        return
    server = create_server()
    if args.export_tools:
        print(json.dumps([t.model_dump(by_alias=True, exclude_none=True) for t in asyncio.run(server.list_tools())], indent=2))
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
