---
name: byteplus-creative-setup
description: Configure or troubleshoot BytePlus Creative Kit commands in a managed Linux cloud workspace, including credentials, dependencies, network access, and output storage.
---

This is a skills-only cloud plugin. It has no MCP server connection, desktop launcher, or browser setup form. Run its bundled commands with the cloud executor's shell/code tools. A chat without a cloud executor cannot run it; explain that requirement without directing the user to install the desktop app.

Resolve the plugin root from this skill's location: this file is `skills/byteplus-creative-setup/SKILL.md`; the runner is `../../scripts/run.py` relative to its containing directory. Use the resolved absolute runner path in every command, preserving the installed files. Do not assume `${PLUGIN_ROOT}` expands inside skill text. If the host exposes skills but has not materialized the supporting files, fetch the source from the user's repository branch `codex/byteplus-creative-kit-cloud`, subdirectory `plugins/byteplus-creative-kit-cloud`, into the cloud workspace. Explain if source access is unavailable rather than claiming installation succeeded.

Run `python3 <runner> --check` to inspect configuration flags without contacting BytePlus. The wrapper uses uv to install the frozen Python 3.12 environment into a writable workspace directory, then executes one command and exits. If uv is absent, install it using the cloud environment's supported package-manager flow into a writable workspace; do not ask the user to install desktop software. Missing Python or dependency network access is a cloud environment requirement.

Credentials belong in cloud environment secret settings, never chat, source, or command arguments. ARK_API_KEY enables generation. ARK_AK and ARK_SK enable asset-library access. Uploads additionally need SEEDANCE_TOS_BUCKET; defaults are ap-southeast-1 and tos-ap-southeast-1.bytepluses.com. Optional BYTEPLUS_TOS_AK/BYTEPLUS_TOS_SK override upload credentials. Optional BYTEPLUS_SEED_MODEL enables the text command. Report missing variable names only. Do not read, print or collect secret values. Each command reads the current environment; no daemon restart is needed.

Preserve proxy and CA settings and TLS verification. The configured API, asset, bucket and returned media hosts must be allowed by the environment's network policy. Use supported environment configuration for denied destinations. Do not bypass the proxy. Configuration flags do not prove provider access; do not submit paid generation to validate setup.

Outputs default to /workspace/output/byteplus-creative-kit and operation records to /workspace/.byteplus-creative-kit. Override BYTEPLUS_CREATIVE_OUTPUT_DIR and BYTEPLUS_CREATIVE_DATA_DIR when the environment uses different writable or user-downloadable directories. Use persistent storage for operation records where available; return downloadable links to saved results and preserve task/operation IDs. Ephemeral environments do not retain these files after deletion.
