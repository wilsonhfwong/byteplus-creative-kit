---
name: byteplus-creative-setup
description: Configure or troubleshoot BytePlus Creative Kit in a Linux cloud executor, including missing secrets, workspace storage and network access.
---

This package runs a stdio MCP process inside a cloud executor with Python 3.12 and uv. It is not a hosted HTTPS MCP endpoint. The current web plugin installer routes this stdio connection to the desktop app. Uploading this ZIP does not register its tools in the browser cloud host. Use the bundled CLI to run them explicitly in a Linux cloud workspace; browser-native MCP tools require separate HTTPS hosting.

Call creative_kit_status if available. Report missing configuration by variable name only. ARK_API_KEY enables generation; ARK_AK and ARK_SK enable the asset library. TOS uploads additionally require SEEDANCE_TOS_BUCKET; region/endpoint default to ap-southeast-1. Optional BYTEPLUS_TOS_AK/BYTEPLUS_TOS_SK override upload credentials. Optional BYTEPLUS_SEED_MODEL enables seed_text after restart.

Use the cloud environment's secret settings to enter credentials, never chat or tool arguments. Do not inspect, print or collect secret values. Do not launch the desktop browser setup. Restart the MCP process after changes; then check status. Configuration flags do not prove provider access. Do not start paid generation just to validate installation.

If MCP tools are not exposed by this host, follow README.md to use the bundled MCP CLI in the executor; never claim tools are installed merely because the ZIP uploaded. Preserve inherited proxy and TLS settings. BytePlus, TOS, and result media hosts must be allowed by the environment's network policy. Request supported configuration changes for denied hosts; do not bypass the proxy.

Outputs default to /workspace/output/byteplus-creative-kit and operation records to /workspace/.byteplus-creative-kit. Paths can be changed with BYTEPLUS_CREATIVE_OUTPUT_DIR and BYTEPLUS_CREATIVE_DATA_DIR. Keep operation records on persistent storage when possible and download outputs before the environment is discarded. Lost submission responses must be reconciled rather than blindly retried.
