# BytePlus Creative Kit · Cloud

Version 0.1.0 adapts the supplied desktop source for a Linux cloud executor. It retains Seedream image generation, Seedance video generation and polling, the persistent asset library, private TOS uploads, and result downloads. No desktop binaries, browser setup, or credentials are packaged.

## Install and run

Upload **byteplus-creative-kit-cloud.zip** as one plugin. Its root contains `plugin.json`, `mcp.json`, skills, and the Python source. The current web plugin installer offers this stdio MCP connection through **Open in desktop app**. Linux-compatible code does not change that host restriction. This package is source for execution in a Linux workspace with Python 3.12 and `uv` on PATH; uploading it does not register its tools in the browser cloud host. It is not a remotely hosted HTTPS MCP service. Browser-native tool integration requires a separately hosted HTTPS MCP endpoint, or a separate skills-only package without a stdio MCP declaration.

The configured command is `python3 ${PLUGIN_ROOT}/scripts/run.py`. The wrapper uses `uv run --frozen --no-dev` to install the bundled workspace packages and locked dependencies, then launches the server. First startup needs package-manager access and may take longer than later starts. The virtual environment and uv cache live in the configured data directory, not the plugin installation directory.

To use the source directly, extract the ZIP in the cloud workspace, open its folder, and run:

```sh
python3 scripts/run.py --check
```

This reports configuration flags only and does not contact BytePlus.

If the host accepts skills but does not expose the cloud MCP tools, the agent can run the included MCP client from the extracted plugin folder:

```sh
uv run --frozen --no-dev python scripts/mcp_call.py list
uv run --frozen --no-dev python scripts/mcp_call.py creative_kit_status
uv run --frozen --no-dev python scripts/mcp_call.py seedream_generate --arguments /workspace/work/image-request.json
```

The last command submits a paid image generation when credentials are configured. Example request JSON: `{"prompt":"A watercolor mountain landscape","model":"seedream-4-5-251128","size":"2K"}`. Tool arguments never contain credentials. For video, retain the returned task ID and poll `seedance_check_task`; do not resubmit a timed-out mutation blindly.

## Cloud environment settings

Set credential values through the environment's secret settings, not chat, source files, or command arguments. The actual MCP process must inherit these settings. Restart it after changes.

| Setting | Purpose |
| --- | --- |
| `ARK_API_KEY` | Secret; image/video generation |
| `ARK_AK`, `ARK_SK` | Secrets; asset-library API |
| `ARK_SESSION_TOKEN` | Optional temporary IAM session token |
| `SEEDANCE_TOS_BUCKET` | Existing private bucket for uploads |
| `SEEDANCE_TOS_REGION` | Default `ap-southeast-1` |
| `SEEDANCE_TOS_ENDPOINT` | Default `tos-ap-southeast-1.bytepluses.com` |
| `BYTEPLUS_TOS_AK`, `BYTEPLUS_TOS_SK`, `BYTEPLUS_TOS_SESSION_TOKEN` | Optional separate upload secrets; otherwise use IAM credentials |
| `ARK_BASE_URL` | Default `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `SEEDANCE_PROJECT_NAME` | Default `default` |
| `SEEDREAM_MODEL` | Default `seedream-4-5-251128`; requests may explicitly select another model |
| `BYTEPLUS_SEED_MODEL` | Optional enabled text model/endpoint ID; enables `seed_text` |
| `BYTEPLUS_CREATIVE_WORKSPACE` | Default `/workspace` |
| `BYTEPLUS_CREATIVE_DATA_DIR` | Default `<workspace>/.byteplus-creative-kit`; contains SQLite import records, venv and cache |
| `BYTEPLUS_CREATIVE_OUTPUT_DIR` | Default `<workspace>/output/byteplus-creative-kit` |

Use persistent storage for the data directory when possible. Operation records support reconciliation across restarts, but will be lost if an ephemeral workspace is discarded. Download outputs before discarding the environment. Local file paths refer to the cloud filesystem; user attachments must be transferred there first.

Allow outbound HTTPS to the configured API, asset, and TOS hosts through your cloud environment's network configuration:

- `ark.ap-southeast.bytepluses.com`
- `ark.ap-southeast-1.byteplusapi.com`
- `tos-ap-southeast-1.bytepluses.com` and your bucket's actual hostname
- Provider-returned media/download hosts used by your results
- `pypi.org` and `files.pythonhosted.org` for first dependency installation

Keep the executor's proxy, TLS verification and CA settings. Add denied destinations using the environment's supported network configuration; do not bypass its proxy. The project does not create a bucket or enable models/services on the account.

## Verification and limits

`creative_kit_status` reports presence of settings, not validity of keys, account access, network connectivity, or enabled models. Listing models is a preset list, not an account entitlement check. API calls may incur charges. The included automated tests cover environment configuration/redaction, MCP startup/discovery and credential-free failure paths, mocked generation responses, and download behavior. Live generation requires the user's secrets and network access and is not covered by those checks.

Run development checks with `uv run --frozen pytest -q`. The inherited vendor source and attribution are in `packages/`, `licenses/`, and `THIRD_PARTY_NOTICES.md`. This is an adaptation of the uploaded BytePlus Creative Kit source, not a claim of official BytePlus distribution.
