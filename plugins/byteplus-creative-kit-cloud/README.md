# BytePlus Creative Kit Cloud

Version 0.2.1 is a **skills-only plugin for a managed Linux cloud executor**. ChatGPT reads the bundled skills and executes one-shot Python commands in its cloud workspace. There is no declared MCP server, local daemon, desktop launcher, or separately hosted service.

The plugin retains Seedream image generation, Seedance video submission and polling, the asset library, private TOS uploads, and output downloads. The bundled SDK modules still use the `mcp` Python library for their internal definitions; nothing registers or launches an MCP transport.

## Install

Upload **byteplus-creative-kit-cloud.zip** as one plugin and start a conversation with a managed cloud execution environment. Ask “Configure BytePlus Creative Kit Cloud” or describe the image/video you want.

The package includes two skills and their Python source. The new package has **no `mcp.json`** and no compatibility stdio declaration. Version 0.1.0's desktop prompt came from its stdio server declaration; 0.2.0 removes that dependency. Cloud execution requires shell/code tools, Python 3.12, uv, environment secrets, and network access. A plain chat without an executor cannot run the commands. Browser UI installation still needs validation in the target host.

If updating the existing personal plugin, remove the old stdio connection as well as replacing its files. If the uploader keeps old components during an update, uninstall/remove the old 0.1.0 plugin and upload 0.2.0 as a fresh package. Do not keep its old MCP connection. There should be two skills and no MCP server listed for 0.2.0.

If a host exposes the skills without materializing their supporting files, the agent can fetch this repository's `plugins/byteplus-creative-kit-cloud` source into the executor. All paths refer to the cloud filesystem, not the user's computer.

## Execution

Resolve the installed plugin root and run its wrapper:

```sh
python3 scripts/run.py --check
python3 scripts/run.py list
python3 scripts/run.py call creative_kit_status
python3 scripts/run.py call seedream_generate --arguments /workspace/work/image-request.json
```

The last command submits a paid image request when configured. Example JSON arguments:

```json
{"prompt":"A watercolor mountain landscape","model":"seedream-4-5-251128","size":"2K"}
```

Use `list` for every command's exact input schema. For video, preserve the returned task ID and poll `seedance_check_task` with a separate command. Downloads use `seed_media_download`. Exit status 1 with `status:error` reports a failure; do not repeat a mutation whose submission outcome is unknown.

`--check` runs without uv or network access. The setup skill includes a SHA-256-verified runtime recovery bundle in its own supporting resources, so missing workspace files can be restored without GitHub access. This bundle contains source, not installed dependencies: first-time dependency installation and provider API calls still require a working workspace proxy. A proxy connection error with `Operation not permitted` may come from the command sandbox: use the execution tool's supported network permission and keep the proxy and destination policy intact. If a dependency command succeeds with that permission, the proxy itself was not the failure.

For generation commands the wrapper uses `uv run --frozen --no-dev` and installs dependencies in a writable cloud data directory. It does not require writes to the plugin installation folder. First execution needs package-manager access; subsequent commands reuse the environment. Every invocation reads current secrets and exits after returning JSON.

## Environment settings

Configure credentials in the cloud environment's secret settings, never chat, source files, argument JSON, or shell arguments. The actual execution process must inherit these settings.

| Variable | Purpose |
| --- | --- |
| `ARK_API_KEY` | Secret; image/video generation |
| `ARK_AK`, `ARK_SK` | Secrets; asset-library API |
| `ARK_SESSION_TOKEN` | Optional temporary IAM session token |
| `SEEDANCE_TOS_BUCKET` | Existing private bucket for workspace file uploads |
| `SEEDANCE_TOS_REGION` | Default `ap-southeast-1` |
| `SEEDANCE_TOS_ENDPOINT` | Default `tos-ap-southeast-1.bytepluses.com` |
| `BYTEPLUS_TOS_AK`, `BYTEPLUS_TOS_SK`, `BYTEPLUS_TOS_SESSION_TOKEN` | Optional separate upload secrets; otherwise use IAM credentials |
| `ARK_BASE_URL` | Default `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `SEEDANCE_PROJECT_NAME` | Default `default` |
| `SEEDREAM_MODEL` | Default `seedream-4-5-251128`; individual requests may choose a model |
| `BYTEPLUS_SEED_MODEL` | Optional enabled text model/endpoint ID |
| `BYTEPLUS_CREATIVE_WORKSPACE` | Default `/workspace` |
| `BYTEPLUS_CREATIVE_DATA_DIR` | Default `<workspace>/.byteplus-creative-kit`; import records, Python environment and cache |
| `BYTEPLUS_CREATIVE_OUTPUT_DIR` | Default `<workspace>/output/byteplus-creative-kit`; use the host's downloadable output directory if different |

Persist the data directory when possible. It contains the SQLite operation records needed to reconcile imports across command invocations. Download outputs before an ephemeral environment is discarded. Transfer user attachments into the cloud workspace before referencing file paths.

Allow HTTPS to `ark.ap-southeast.bytepluses.com`, `ark.ap-southeast-1.byteplusapi.com`, the configured TOS endpoint and bucket hostname, and provider-returned media hosts. First installation also needs `pypi.org` and `files.pythonhosted.org`. Preserve the inherited proxy, CA trust and TLS verification; add denied destinations through supported environment settings. The project does not create a bucket or enable models/services on the account.

## Build and verify

From the repository root:

```sh
python scripts/package_cloud.py
```

This produces `dist/byteplus-creative-kit-cloud.zip` with exactly one plugin and no MCP declaration or runtime state. From this plugin folder:

```sh
uv run --frozen pytest -q
```

Tests cover real one-shot command execution, input validation and failure exit codes, environment isolation/redaction, mocked image/video requests, download handling, and the absence of an MCP declaration. They do not prove live model access or browser installation. `--check` reports configuration presence rather than key validity or provider connectivity. Source attribution is in `THIRD_PARTY_NOTICES.md` and `licenses/`.
