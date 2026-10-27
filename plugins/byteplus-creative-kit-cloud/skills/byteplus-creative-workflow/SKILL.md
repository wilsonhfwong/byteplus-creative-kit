---
name: byteplus-creative-workflow
description: Generate or edit Seedream images and Seedance videos, upload references, and manage reusable BytePlus image/video assets by executing bundled commands in a managed cloud workspace.
---

Use the cloud executor's shell/code tool to run the bundled Python commands. This plugin intentionally has no MCP connection; command names below refer to Python operations, not host tools. Resolve the plugin root as two directories above this skill's containing directory, and use the absolute path to `scripts/run.py`. If supporting files are unavailable, follow the setup skill's source-retrieval instructions.

1. Run `python3 <runner> --check` before first use. Missing configuration belongs in environment secret settings; never request or expose credentials in chat or arguments. Each invocation uses the current environment.
2. Run `python3 <runner> list` to obtain all operation names and exact JSON input schemas. Model listings are presets, not account entitlement checks.
3. Write the desired operation's JSON arguments to a temporary file inside the workspace (without credentials), then run `python3 <runner> call <operation> --arguments <absolute-json-path>`. For no-argument operations omit --arguments. Avoid inline JSON shell quoting. Exit code 0 means the operation returned successfully; exit code 1 and `status:error` mean failure. A successful video submission is not a completed video.
4. Read the returned JSON, preserve IDs, and continue the user's workflow. Return downloadable links to saved outputs, not paths on the user's desktop.

For images, call `seedream_generate`. Upload cloud workspace reference files with `seed_media_upload` first and use the returned temporary HTTPS source_url in image_urls. Seedream does not accept Seedance asset:// references. Use `seed_text` only when requested and configured.

For reusable Seedance references:

- List groups and follow pagination, reusing the intended group. Create an AIGC group only for a new fictional subject. Real-person verification belongs in the provider console.
- Import exactly one workspace file or direct HTTPS URL with `seedance_library_import`. Image and Video are distinct types. Preserve operation and asset IDs.
- Poll `seedance_library_get_asset` until Active/usable=true. Processing requires another check; Failed requires reporting. Inspect recorded imports and recent assets after a timeout; reconcile a lost response rather than resubmitting an unresolved creation.
- Call `seedance_image_to_video`, putting Image assets in image_urls/first_frame_url and Video assets in video_urls. Preserve order. Refer to Image 1 / Video 1 in prompt text and use asset:// IDs only in media URL fields. Use text-to-video without references and edit/extend operations for those explicit modes.
- Preserve the returned generation task ID. Run `seedance_check_task` in a separate invocation every 10–15 seconds until terminal status. Download results promptly with `seed_media_download` because provider links expire.

Keep requests within the user's authorized creative task. Provider errors may leave a paid submission's outcome unknown: do not automatically repeat a mutation. Respect the requested model/provider and report access failures instead of switching silently. Keep signed URLs out of shared records. Retain reusable assets; rename with the update operation and delete only an explicitly requested asset with no running or unknown generation dependency. Deleting a library asset retains its source TOS object.
