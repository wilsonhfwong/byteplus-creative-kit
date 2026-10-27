"""Compose the shared Seedance and Seedream tools."""
from __future__ import annotations

import asyncio
import json
import sys

from .launcher import build_server
from .settings import DEFAULTS, configure_environment, load_settings
from .tools import guarded


def combined_server(settings: dict):
    server = build_server("seedance", settings)
    configure_environment(settings)
    from seedream_mcp import server as seedream
    for name in ("seedream_generate", "seedream_list_models", "seedream_ping"):
        server.tool()(guarded(getattr(seedream, name), settings))
    return server

