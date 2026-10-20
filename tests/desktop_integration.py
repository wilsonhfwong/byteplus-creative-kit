"""Exercise the checked-in native plugin without any BytePlus credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / ("byteplus-creative-kit-windows" if os.name == "nt" else "byteplus-creative-kit-mac")


def physical_windows_file(path):
    """Resolve a real opened file, including MSIX redirection, without guessing a PFN."""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    function.restype = wintypes.DWORD
    with path.open("rb") as opened:
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(msvcrt.get_osfhandle(opened.fileno()), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
    value = buffer.value
    return Path("\\\\" + value[8:] if value.startswith("\\\\?\\UNC\\") else value.removeprefix("\\\\?\\"))


def main(require_virtualization=False):
    with tempfile.TemporaryDirectory(prefix="Creative Kit desktop test ") as temporary:
        data = Path(temporary)
        if require_virtualization:
            assert os.name == "nt"
            data = Path(os.environ["APPDATA"]) / ("BytePlusCreativeKit-CI-" + uuid.uuid4().hex)
            data.mkdir()
            marker = data / "physical-path-probe.txt"
            marker.write_text("synthetic MSIX fixture", encoding="utf-8")
            actual = physical_windows_file(marker).parent
            assert str(actual).casefold() != str(data).casefold(), "Probe did not exercise AppData redirection"
            assert "localcache" in str(actual).casefold(), "Probe has no MSIX private storage"
            # Preserve a genuine dangling legacy junction, as on the repaired
            # customer installation. The replacement runtime must ignore it.
            legacy = actual / "python"
            legacy.mkdir()
            (legacy / "cpython-3.12.14-windows-x86_64-none").mkdir()
            subprocess.run(["cmd", "/c", "mklink", "/J", str(legacy / "cpython-3.12-windows-x86_64-none"), str(data / "missing-logical-target")], check=True, capture_output=True)
            print("PASS: real MSIX AppData redirection and dangling legacy junction are present.", flush=True)
        env = {**os.environ, "BYTEPLUS_CREATIVE_DATA_DIR": str(data), "BYTEPLUS_CREATIVE_NO_BROWSER": "1"}
        env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32") if os.name == "nt" else "/usr/bin:/bin"
        manifest = json.loads((PLUGIN / "mcp.json").read_text(encoding="utf-8"))
        declared = manifest["mcpServers"]["byteplus_creative"]["command"]
        assert declared.startswith("./"), "Agent Plugins commands do not expand PLUGIN_ROOT; use a contained ./ path"
        command = (PLUGIN / declared[2:]).resolve()
        assert command.is_relative_to(PLUGIN.resolve()), "Native executable escapes the plugin package"
        process = subprocess.Popen([str(command)], cwd=PLUGIN, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        incoming = queue.Queue()

        def read():
            for line in process.stdout:
                incoming.put(json.loads(line))
            incoming.put(None)

        threading.Thread(target=read, daemon=True).start()
        counter = 0

        def request(method, params=None):
            nonlocal counter
            counter += 1
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": counter, "method": method, "params": params or {}}) + "\n")
            process.stdin.flush()
            result = incoming.get(timeout=120)
            assert result is not None, "Native launcher closed the connection"
            assert result.get("id") == counter and "error" not in result, result
            return result["result"]

        def tool(name, arguments=None):
            result = request("tools/call", {"name": name, "arguments": arguments or {}})
            value = result.get("structuredContent")
            if value is None:
                value = json.loads(next(c["text"] for c in result["content"] if c.get("type") == "text"))
            return value

        try:
            started = time.monotonic()
            request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "desktop-acceptance", "version": "1"}})
            tools = request("tools/list")["tools"]
            assert {"creative_kit_setup", "creative_kit_status", "seedream_generate", "seedance_image_to_video", "seedance_library_import", "seedance_library_delete_asset"} <= {t["name"] for t in tools}
            assert time.monotonic() - started < 15, "Discovery waited for runtime downloads"
            initial = tool("creative_kit_status")
            assert initial["version"] == json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))["version"]
            assert initial["runtime"] == "not_prepared" and initial["generation_configured"] is False
            blocked = tool("seedream_generate", {"prompt": "No cloud request must be made"})
            assert blocked["status"] == "setup_required"
            setup = tool("creative_kit_setup")
            url = setup["setup_url"]
            assert urllib.parse.urlsplit(url).hostname == "127.0.0.1"
            with urllib.request.urlopen(url, timeout=15) as response:
                assert response.headers["Referrer-Policy"] == "same-origin", "Native setup policy breaks browser Origin validation"
                page = response.read().decode()
            assert "type=\"password\"" in page and "无需打开终端" in page
            token = urllib.parse.urlsplit(url).path.strip("/")
            values = {"csrf": token, "api_key": "dummy-api-acceptance-sentinel", "access_key": "dummy-iam-acceptance-sentinel", "secret_key": "dummy-secret-acceptance-sentinel", "project": "default", "tos_bucket": "dummy-private-bucket"}
            body = urllib.parse.urlencode(values).encode()
            origin = "http://" + urllib.parse.urlsplit(url).netloc
            post = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": origin})
            saved = urllib.request.urlopen(post, timeout=15).read().decode()
            for key in ["api_key", "access_key", "secret_key"]:
                assert values[key] not in saved, "Secret echoed into page"
            deadline = time.monotonic() + 900
            previous = None
            while time.monotonic() < deadline:
                status = tool("creative_kit_status")
                if status["runtime"] != previous:
                    print("Runtime:", status["runtime"], flush=True)
                    previous = status["runtime"]
                if status["runtime"] == "failed":
                    log = data / "runtime-install.log"
                    details = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "No runtime log was created."
                    raise AssertionError(f"{status}\n{details}")
                assert all(v not in json.dumps(status) for k, v in values.items() if k in {"api_key", "access_key", "secret_key"})
                if status["runtime"] == "ready":
                    break
                time.sleep(2)
            else:
                raise AssertionError("Runtime installation did not complete")
            result = tool("seedream_list_models")
            assert "seedream" in json.dumps(result).lower()
            invalid = tool("seedance_library_import", {"group_id": "local-validation-only"})
            assert "exactly one" in json.dumps(invalid), invalid
            assert tool("seed_text", {"prompt": "Do not call a cloud model"})["status"] == "setup_required"
            if os.name != "nt":
                assert (data / "settings.json").stat().st_mode & 0o777 == 0o600
            if require_virtualization:
                environments = list((actual / "runtime").glob("*/venv/pyvenv.cfg"))
                assert len(environments) == 1
                home = next(line.removeprefix("home = ") for line in environments[0].read_text(encoding="utf-8").splitlines() if line.startswith("home = "))
                assert Path(home).is_relative_to(actual), "Python venv retained a logical AppData target"
                assert (legacy / "cpython-3.12.14-windows-x86_64-none").is_dir(), "Legacy runtime was deleted"
                print("PASS: packaged bootstrap and Python worker use physical storage; old download is retained.", flush=True)
            assert not (PLUGIN / ".runtime").exists(), "Runtime was written into plugin package"
            print("PASS: native discovery, local setup, own Python installation, private credentials, and Python MCP tools; no BytePlus calls.", flush=True)
        finally:
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if process.returncode:
                print(process.stderr.read(), file=sys.stderr)


if __name__ == "__main__":
    import argparse
    import contextlib
    import traceback

    parser = argparse.ArgumentParser()
    parser.add_argument("--msix-report", type=Path)
    arguments = parser.parse_args()
    if arguments.msix_report:
        report = arguments.msix_report
        report.write_text(json.dumps({"state": "running"}), encoding="utf-8")
        with report.with_suffix(".log").open("w", encoding="utf-8", buffering=1) as output, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                main(require_virtualization=True)
            except Exception:
                traceback.print_exc()
                state = "failed"
            else:
                state = "passed"
        report.write_text(json.dumps({"state": state}), encoding="utf-8")
        sys.exit(0 if state == "passed" else 1)
    main()
