"""Only the shared run-bound stdio MCP tools are callable by the model."""
from contextlib import asynccontextmanager
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from goalflow_world.store import ROOT

ALLOWED_TOOLS = frozenset({'get_world', 'get_activity', 'send_message', 'advance_clock',
    'record_decision', 'update_task', 'publish_brief', 'read_brief', 'report_outcome'})


class MCPBridge:
    def __init__(self, session, tools):
        self.session = session
        self.tools = tools

    async def call(self, name, arguments):
        if name not in ALLOWED_TOOLS:
            return {'ok': False, 'error': 'Tool is not allowed'}
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            return {'ok': False, 'error': 'Tool input failed MCP validation; check the advertised schema'}
        payload = json.loads(result.content[0].text)
        if not isinstance(payload, dict) or not isinstance(payload.get('ok'), bool):
            raise ValueError('Unexpected MCP result envelope')
        return payload


@asynccontextmanager
async def connect_world(run_path):
    folder = run_path/'baseline'
    folder.mkdir(exist_ok=True)
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT/'tools/world_server.py'), '--run', run_path.name, '--runs-root', str(run_path.parent)],
        cwd=str(ROOT), env={'PYTHONNOUSERSITE': '1'})
    # The SDK inherits a small default environment, not .env; no API credential is passed.
    with (folder/'mcp-stderr.log').open('a') as stderr:
        async with stdio_client(params, errlog=stderr) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                if {t.name for t in listed.tools} != ALLOWED_TOOLS:
                    raise ValueError('Unexpected MCP capability set')
                tools = [{'type': 'function', 'name': t.name, 'description': t.description or '',
                          'parameters': t.inputSchema, 'strict': False} for t in listed.tools]
                # Dynamic requirement dictionaries cannot use strict structured output schemas.
                # The shared MCP server still validates every call with Pydantic.
                yield MCPBridge(session, tools)
