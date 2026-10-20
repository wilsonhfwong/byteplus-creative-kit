---
name: byteplus-creative-workflow
description: Generate or edit images with Seedream, generate videos with Seedance, and import, list, reuse, rename or delete BytePlus image/video assets through TOS. Use for BytePlus creative and asset-library workflows.
---

Use this plugin's tools. If configuration is missing, use `creative_kit_setup`: credentials belong in the local browser form, never chat or tool arguments. Do not ask the user to run an installer or install Python/Docker. When a tool returns `preparing`, no cloud request was submitted: poll `creative_kit_status` about every 10 seconds until runtime=ready, then continue. If runtime fails, reopen setup rather than silently switching providers.

For images, use `seedream_generate`. For local image references, first use `seed_media_upload` and pass its temporary HTTPS source URL. Seedream does not accept Seedance `asset://` values here. Use optional `seed_text` only when requested and configured.

For reusable Seedance references:

1. List groups, follow pagination and reuse the intended group ID. Create an AIGC group for a new fictional subject. Real-person verification is console-based; an AIGC group is not a substitute for authorization.
2. Import with `seedance_library_import`, supplying exactly one local file or direct HTTPS URL. Image and Video are distinct types; do not infer an extensionless asset's type from its ID. Retain the import operation and asset IDs for reuse across chats.
3. Poll `seedance_library_get_asset` until Active/usable=true. Processing requires another poll; Failed requires reporting. If an import times out, inspect its recorded operation and recent assets before repeating creation. Reconcile a lost response instead of automatically resubmitting it.
4. Use `seedance_image_to_video`. Put Image assets in image_urls/first_frame_url and Video assets in video_urls. Preserve reference order. Refer to Image 1 / Video 1 in the prompt, and put asset:// IDs only in media URL fields. Use text-to-video without references; use edit/extend tools for those explicit modes.
5. Save the generation task ID. Poll `seedance_check_task` every 10–15 seconds to a terminal result. Use `seed_media_download` promptly to save output, and return the local path and task ID.

Only `preparing` before a cloud submission permits continuing the same creation after runtime becomes ready. A lost response or submission_unresolved after a cloud call may have created an asset or paid job. Retain IDs, inspect state/listings, and do not automatically repeat that cloud mutation.

Model lists are client presets, not proof of account access. Respect a requested model/provider; report access errors rather than silently substituting another. Keep signed source links out of shared records. Retain assets for reuse; rename with the update tool and delete only an explicitly requested asset with no running or unknown generation dependency. Deleting a library asset retains its source TOS object.
