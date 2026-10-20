# Source and license notices

This kit adapts the user's supplied Mittul Seedance and Seedream MCP/SDK source packages. It is not an official new BytePlus SDK release.

| Source archive | SHA-256 | Package license declaration |
|---|---|---|
| `byteplus-seedance-mcp-main-20260807.zip` | `3d80c0c40047d86160bb4dea0bb8a8c042757fe78c4eb072dc7cb5dddd8abf4f` | MIT (`seedance-sdk` / `seedance-mcp` package metadata) |
| `byteplus-seedream-mcp_2026.zip` | `a17b51acaa19e58135159ade4868da617ba7639633a3d3edac4f8651548d8072` | MIT (`seedream-sdk` / `seedream-mcp` package metadata) |

The supplied archives did not contain a separate upstream LICENSE file. Their package metadata and source notices are preserved. The standard MIT permission text is reproduced in `licenses/MIT.txt`; it does not assign new ownership of the upstream code.

The asset API request shapes were adapted with reference to the user's supplied Anna `seed-studio-v4.zip` and Olga `SEEDANCE_ASSET_LIBRARY_AGENT_GUIDE.md`, then checked against the official API documentation. Their complete bundles, internal skills, customer examples and credential files are not included.

Local changes include a native desktop MCP entry point, browser-based local configuration, automatic environment preparation, credential isolation, typed image/video asset import, asset management, persisted import records, output download and optional Seed text calls. Ambiguous generation submissions are not automatically retried. Upstream's SDK and MCP package version metadata is retained for compatibility; the outer plugin is version 0.2.0.

Runtime dependencies are installed from the locked package versions in `uv.lock` and retain their own package license metadata. The official TOS SDK (`tos`) is Apache-2.0. See those projects for their distribution notices.

## Native desktop launcher

The desktop launcher is built with Go. Go runtime and standard-library notices are retained in `licenses/Go-BSD-3-Clause.txt`. The launcher downloads uv 0.12.5 from Astral's official releases on first setup and verifies a pinned SHA-256 before use. uv and the managed Python runtime are not committed to this repository.

