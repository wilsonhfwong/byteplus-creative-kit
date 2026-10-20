"""Maintainer build only; customers run the checked-in native launcher."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    go = os.environ.get("CREATIVE_KIT_BUILD_GO") or shutil.which("go")
    if not go:
        raise SystemExit("Go is required only on the maintainer's build computer.")
    target = ROOT / "bin"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="creative-kit-build-") as directory:
        outputs = []
        for system, arch in [("darwin", "arm64"), ("darwin", "amd64"), ("windows", "amd64")]:
            destination = Path(directory) / f"creative-kit-{system}-{arch}"
            flags = "-s -w" + (" -H=windowsgui" if system == "windows" else "")
            env = {**os.environ, "GOOS": system, "GOARCH": arch, "CGO_ENABLED": "0"}
            subprocess.run([go, "build", "-trimpath", "-ldflags", flags, "-o", str(destination), "."], cwd=ROOT / "native-launcher", env=env, check=True)
            outputs.append(destination)
        subprocess.run(["lipo", "-create", str(outputs[0]), str(outputs[1]), "-output", str(target / "creative-kit")], check=True)
        (target / "creative-kit").chmod(0o755)
        subprocess.run(["codesign", "--force", "--sign", "-", str(target / "creative-kit")], check=True)
        shutil.copyfile(outputs[2], target / "creative-kit.exe")
    portable = json.loads((ROOT / "plugin.json").read_text())
    extension = portable["extensions"]["com.openai"]
    compatibility = {key: portable[key] for key in ["name", "version", "description", "repository", "homepage"]}
    compatibility.update(extension)
    compatibility.update(skills="./skills/", mcpServers="./.mcp.json")
    path = ROOT / ".codex-plugin" / "plugin.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(compatibility, ensure_ascii=False, indent=2) + "\n")
    servers = json.loads((ROOT / "mcp.json").read_text())["mcpServers"]
    servers = {key: {**value, "startup_timeout_sec": 60, "tool_timeout_sec": 240} for key, value in servers.items()}
    (ROOT / ".mcp.json").write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n")
    (ROOT / ".claude-plugin").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / ".agents/plugins/marketplace.json", ROOT / ".claude-plugin/marketplace.json")
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}" for path in [target / "creative-kit", target / "creative-kit.exe"]]
    (target / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print("Built native Mac universal and Windows x64 launchers and compatibility manifests.")


if __name__ == "__main__":
    main()
