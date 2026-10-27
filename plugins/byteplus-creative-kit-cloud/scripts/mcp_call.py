"""MCP client fallback for executors whose host cannot expose stdio tools."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', help="Tool name, or 'list'")
    parser.add_argument('--arguments', type=Path, help='JSON arguments file; do not include credentials')
    args = parser.parse_args()
    arguments = json.loads(args.arguments.read_text()) if args.arguments else {}
    if not isinstance(arguments, dict):
        parser.error('Arguments must be a JSON object')
    # Explicitly inherit configured cloud secrets and proxy/CA settings. The MCP
    # SDK default environment deliberately excludes custom environment variables.
    import os
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'byteplus_creative.cloud_server'],
        cwd=str(Path(__file__).resolve().parents[1]), env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if args.tool == 'list':
                result = await session.list_tools()
            else:
                result = await session.call_tool(args.tool, arguments)
            print(result.model_dump_json(by_alias=True, exclude_none=True, indent=2))
            if getattr(result, 'isError', False):
                raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
