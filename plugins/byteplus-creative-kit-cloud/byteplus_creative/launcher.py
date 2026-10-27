"""Compose cloud-executor commands from the bundled SDKs."""
from __future__ import annotations

import argparse
import importlib.metadata
import logging
import sys
import tomllib
from pathlib import Path

from .settings import DEFAULTS, ROOT, SETTINGS_PATH, configure_environment, load_settings, redact


class RedactFilter(logging.Filter):
    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings

    def filter(self, record):
        record.msg = redact(record.getMessage(), self.settings)
        record.args = ()
        return True


def build_commands(service: str, settings: dict):
    configure_environment(settings)
    from .registry import CommandRegistry
    from .tools import guarded, register
    if service == "seedance":
        from seedance_mcp import server as upstream
        names = ["seedance_text_to_video", "seedance_image_to_video", "seedance_edit_video", "seedance_extend_video", "seedance_check_task", "seedance_list_tasks", "seedance_cancel_task", "seedance_list_models", "seedance_ping"]
        instructions = (
            "Use seedance_library_* for persistent image/video library operations. "
            "Create/reuse an AIGC group for a fictional subject; import local media with seedance_library_import, "
            "then poll seedance_library_get_asset until usable=true. Processing is not failure. "
            "Pass Image assets through image_urls or first_frame_url and Video assets through video_urls "
            "in seedance_image_to_video. Preserve input order. Put Image 1 / Video 1 in prompt text, "
            "and asset:// IDs only in media URL fields. Choose an enabled model explicitly when known. "
            "Built-in model lists are client presets, not proof of account access. "
            "Seedance submit returns task_id; poll seedance_check_task and save output with seed_media_download. "
            "Retain library assets for reuse. Delete only an explicitly requested asset without active dependencies. "
            "Real-person onboarding is deferred to the console; do not register actual people as fictional characters."
        )
    elif service == "seedream":
        from seedream_mcp import server as upstream
        names = ["seedream_generate", "seedream_list_models", "seedream_ping"]
        instructions = (
            "Generate images using seedream_generate. For local image references first call the companion "
            "seed_media_upload and pass its signed HTTPS source_url in image_urls. Seedream does not use "
            "Seedance asset:// references here. Save outputs using the companion seed_media_download. "
            "Built-in model lists describe presets, not account-specific availability."
        )
    else:
        raise ValueError("Unknown service.")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactFilter(settings))
    server = CommandRegistry(instructions=instructions)
    for name in names:
        server.tool()(guarded(getattr(upstream, name), settings))
    if service == "seedance":
        register(server, settings)
    return server

