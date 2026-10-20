"""Check the package through Codex's real plugin parser and MCP discovery.

Maintainer test: pass --codex /path/to/codex. Uses an isolated CODEX_HOME,
local marketplace, and empty kit data. No login, setup, or generation calls.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    args = parser.parse_args()
    codex = str(Path(args.codex).resolve())
    platform = "windows" if os.name == "nt" else "mac"
    plugin_name = "byteplus-creative-kit-" + platform
    with tempfile.TemporaryDirectory(prefix="creative-kit-host-") as temporary:
        env = {**os.environ, "CODEX_HOME": temporary,
               "BYTEPLUS_CREATIVE_DATA_DIR": str(Path(temporary) / "kit-data"),
               "BYTEPLUS_CREATIVE_NO_BROWSER": "1"}
        for command in [
            ["plugin", "marketplace", "add", str(ROOT), "--json"],
            ["plugin", "add", plugin_name + "@byteplus-creative-kit", "--json"],
        ]:
            result = subprocess.run([codex, *command], env=env, cwd=temporary,
                                    capture_output=True, text=True, encoding="utf-8", timeout=90)
            assert result.returncode == 0, result.stderr
        incoming = queue.Queue()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            process = subprocess.Popen([codex, "app-server", "--stdio"], env=env, cwd=temporary,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                       text=True, encoding="utf-8")

            def read():
                for line in process.stdout:
                    incoming.put(json.loads(line))
                incoming.put(None)

            threading.Thread(target=read, daemon=True).start()
            counter = 0

            def request(method, params):
                nonlocal counter
                counter += 1
                process.stdin.write(json.dumps({"id": counter, "method": method, "params": params}) + "\n")
                process.stdin.flush()
                while True:
                    response = incoming.get(timeout=90)
                    assert response is not None, "App server closed its output"
                    if response.get("id") != counter:
                        continue
                    assert "error" not in response, response
                    return response["result"]

            try:
                request("initialize", {"clientInfo": {"name": "creative-kit-host-test", "version": "1"},
                                       "capabilities": {"experimentalApi": True}})
                process.stdin.write('{"method":"initialized"}\n')
                process.stdin.flush()
                for system in ["mac", "windows"]:
                    name = "byteplus-creative-kit-" + system
                    detail = request("plugin/read", {"marketplacePath": str(ROOT / ".agents/plugins/marketplace.json"), "pluginName": name})
                    servers = detail["plugin"]["mcpServers"]
                    print(name, "host-parsed MCP servers:", servers, flush=True)
                    assert "byteplus_creative" in servers, f"{name}: host discarded the MCP configuration"
                status = request("mcpServerStatus/list", {"detail": "toolsAndAuthOnly"})
                encoded = json.dumps(status)
                for name in ["creative_kit_setup", "creative_kit_status", "seedream_generate", "seedance_library_import"]:
                    assert name in encoded, f"Host did not discover {name}: {status}"
                print("PASS: real Codex parser accepts both packages and discovers the native MCP tools; no BytePlus calls.", flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                errors.seek(0)
                for line in errors:
                    if "failed to parse plugin MCP server" in line or "Agent Plugins stdio command" in line:
                        print(line.strip())


if __name__ == "__main__":
    main()
