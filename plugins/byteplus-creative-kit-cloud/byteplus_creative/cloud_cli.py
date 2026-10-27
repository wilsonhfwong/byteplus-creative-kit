"""One-shot cloud commands; never starts a server or desktop process."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .settings import DATA_DIR, OUTPUT_DIR, load_settings, redact
from .launcher import build_commands
from .tools import guarded


def status(settings):
    return {
        "runtime": "ready", "execution": "cloud-command", "configuration_source": "environment",
        "generation_configured": bool(settings.get("api_key")),
        "asset_library_configured": bool(settings.get("access_key") and settings.get("secret_key")),
        "tos_configured": bool(settings.get("tos_bucket") and
            (settings.get("tos_access_key") or settings.get("access_key")) and
            (settings.get("tos_secret_key") or settings.get("secret_key"))),
        "seed_text_configured": bool(settings.get("seed_model") and settings.get("api_key")),
        "data_directory": str(DATA_DIR), "output_directory": str(OUTPUT_DIR),
        "provider_connectivity": "not_checked",
        "note": "Configuration flags do not verify provider access. Each command reads the current environment.",
    }


def create_commands():
    settings = load_settings()
    commands = build_commands("seedance", settings)
    from seedream_mcp import server as seedream
    for name in ("seedream_generate", "seedream_list_models", "seedream_ping"):
        commands.tool()(guarded(getattr(seedream, name), settings))
    @commands.tool(annotations={"readOnlyHint": True})
    def creative_kit_status() -> dict:
        """Report configuration booleans and cloud workspace paths; no provider request or secret values."""
        return status(settings)
    return commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report configuration without contacting BytePlus")
    parser.add_argument("action", nargs="?", choices=["list", "call"])
    parser.add_argument("command", nargs="?")
    parser.add_argument("--arguments", type=Path, help="JSON arguments file; never put credentials here")
    args = parser.parse_args()
    settings = load_settings()
    try:
        if args.check:
            if args.action or args.command or args.arguments:
                parser.error("Use --check by itself")
            result = status(settings)
        elif args.action == "list" and not args.command and not args.arguments:
            result = {"commands": create_commands().list_commands()}
        elif args.action == "call" and args.command:
            arguments = json.loads(args.arguments.read_text(encoding="utf-8")) if args.arguments else {}
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be a JSON object.")
            result = create_commands().call(args.command, arguments)
        else:
            parser.error("Use --check, list, or call COMMAND [--arguments FILE]")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and result.get("status") == "error" else 0
    except Exception as exc:
        # Validation errors may contain raw argument values; keep them out of
        # output because those values can include temporary signed URLs.
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            message = "Invalid command arguments. Use list to inspect the input schema."
        else:
            message = redact(str(exc), settings)
        print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
