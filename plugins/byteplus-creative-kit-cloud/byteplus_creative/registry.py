"""Validated function dispatch for cloud commands; no transport or listening server."""
from __future__ import annotations
import inspect
from typing import get_type_hints
from pydantic import ConfigDict, create_model


class CommandRegistry:
    def __init__(self, instructions=""):
        self.instructions = instructions
        self.commands = {}

    def tool(self, *, annotations=None):
        def register(function):
            original = inspect.unwrap(function)
            hints = get_type_hints(original)
            fields = {}
            for name, parameter in inspect.signature(original).parameters.items():
                default = ... if parameter.default is inspect.Parameter.empty else parameter.default
                fields[name] = (hints.get(name, str), default)
            model = create_model(original.__name__ + "Arguments", __config__=ConfigDict(extra="forbid", strict=True), **fields)
            self.commands[original.__name__] = (function, model, inspect.getdoc(original) or "", annotations or {})
            return function
        return register

    def list_commands(self):
        return [{"name": name, "description": description, "inputSchema": model.model_json_schema(), "annotations": annotations}
            for name, (_, model, description, annotations) in self.commands.items()]

    def call(self, name, arguments):
        if name not in self.commands:
            raise ValueError("Unknown command; use list to discover supported names.")
        function, model, _, _ = self.commands[name]
        validated = model.model_validate(arguments)
        return function(**validated.model_dump())
