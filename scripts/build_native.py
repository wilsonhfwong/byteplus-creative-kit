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
    portable = json.loads((ROOT / "plugin.template.json").read_text())
    catalog = []
    with tempfile.TemporaryDirectory(prefix="creative-kit-build-") as directory:
        outputs = []
        for system, arch in [("darwin", "arm64"), ("darwin", "amd64"), ("windows", "amd64")]:
            destination = Path(directory) / f"creative-kit-{system}-{arch}"
            flags = "-s -w" + (" -H=windowsgui" if system == "windows" else "")
            env = {**os.environ, "GOOS": system, "GOARCH": arch, "CGO_ENABLED": "0"}
            subprocess.run([go, "build", "-trimpath", "-ldflags", flags, "-o", str(destination), "."], cwd=ROOT / "native-launcher", env=env, check=True)
            outputs.append(destination)
        mac = Path(directory) / "creative-kit-universal"
        subprocess.run(["lipo", "-create", str(outputs[0]), str(outputs[1]), "-output", str(mac)], check=True)
        mac.chmod(0o755)
        subprocess.run(["codesign", "--force", "--sign", "-", str(mac)], check=True)
        for platform, label, binary, filename in [("mac", "Mac", mac, "creative-kit"), ("windows", "Windows", outputs[2], "creative-kit.exe")]:
            target = ROOT / "plugins" / ("byteplus-creative-kit-" + platform)
            target.mkdir(parents=True, exist_ok=True)
            for name in ["pyproject.toml", "uv.lock", "THIRD_PARTY_NOTICES.md", "licenses", "packages", "byteplus_creative", "skills"]:
                source, destination = ROOT / name, target / name
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "tests", ".pytest_cache"))
                else:
                    shutil.copyfile(source, destination)
            (target / "bin").mkdir(exist_ok=True)
            executable = target / "bin" / filename
            shutil.copyfile(binary, executable)
            if platform == "mac": executable.chmod(0o755)
            manifest = json.loads(json.dumps(portable))
            manifest["name"] += "-" + platform
            manifest["extensions"]["com.openai"]["interface"]["displayName"] += " · " + label
            (target / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            servers = {"byteplus_creative": {"type": "stdio", "command": "${PLUGIN_ROOT}/bin/" + filename, "cwd": "${PLUGIN_ROOT}"}}
            (target / "mcp.json").write_text(json.dumps({"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json", "mcpServers": servers}, indent=2) + "\n")
            compatibility = {key: manifest[key] for key in ["name", "version", "description", "repository", "homepage"]}
            compatibility.update(manifest["extensions"]["com.openai"])
            compatibility.update(skills="./skills/", mcpServers="./.mcp.json")
            (target / ".codex-plugin").mkdir(exist_ok=True)
            (target / ".codex-plugin/plugin.json").write_text(json.dumps(compatibility, ensure_ascii=False, indent=2) + "\n")
            (target / ".mcp.json").write_text(json.dumps({"mcpServers": {key: {**value, "startup_timeout_sec": 60, "tool_timeout_sec": 240} for key, value in servers.items()}}, indent=2) + "\n")
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            (target / "bin/SHA256SUMS").write_text(f"{digest}  bin/{filename}\n")
            catalog.append({"name": manifest["name"], "source": {"source": "local", "path": "./" + target.relative_to(ROOT).as_posix()}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Design"})
    marketplace = {"name": "byteplus-creative-kit", "interface": {"displayName": "BytePlus Creative Kit"}, "plugins": catalog}
    (ROOT / ".agents/plugins/marketplace.json").write_text(json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n")
    (ROOT / ".claude-plugin").mkdir(exist_ok=True)
    shutil.copyfile(ROOT / ".agents/plugins/marketplace.json", ROOT / ".claude-plugin/marketplace.json")
    print("Built Mac and Windows plugin entries with explicit native executable paths.")


if __name__ == "__main__":
    main()
