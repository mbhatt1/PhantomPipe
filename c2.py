#!/usr/bin/env python3
"""
Lightweight MCP-based EDR C2 Server with Internet Exposure via ngrok
---------------------------------------------------------------------------
• SSE C2 endpoint exposed via ngrok on public internet
• In-memory agent/command/result storage for PoC
• MCP Tools:
    - register_agent(agent_id) → {'ok': True}
    - enqueue_command(agent_id, command, args) → {'ok': True}
    - get_next_command(agent_id) → {command_id, command, args}
    - upload_result(agent_id, command_id, exit_code, output) → {'ok': True}
    - get_results(agent_id) → list of {command_id, exit_code, output, completed_at}
• Resource: file://<path> → Base64 content of server-side file
• Dependencies: mcp, pyngrok (pip install mcp pyngrok)
"""
import uuid
import time
import base64
import threading
from pathlib import Path
from pyngrok import ngrok
from mcp.server.fastmcp import FastMCP

# In-memory stores
agents: dict[str, float] = {}          # agent_id -> last_seen
command_queue: dict[str, list[dict]] = {}  # agent_id -> commands
results: dict[str, dict] = {}         # command_id -> result data

# Initialize MCP server
app = FastMCP(
    name="Lightweight-C2",
    host="0.0.0.0",
    port=8000,
    sse_path="/mcp",
    message_path="/mcp/messages/"
)

# Tool: register_agent
@app.tool()
def register_agent(params: dict) -> dict:
    aid = params['agent_id']
    agents[aid] = time.time()
    print(f"[+] Registered agent: {aid}")
    return {'ok': True}
register_agent.inputSchema = {'type':'object','properties':{'agent_id':{'type':'string'}},'required':['agent_id']}
register_agent.outputSchema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}

# Tool: enqueue_command
@app.tool()
def enqueue_command(params: dict) -> dict:
    aid = params['agent_id']
    cid = str(uuid.uuid4())
    env = {'command_id':cid,'command':params['command'],'args':params.get('args',[])}
    command_queue.setdefault(aid, []).append(env)
    print(f"[+] Enqueued {cid} for {aid}: {env}")
    return {'ok': True}
enqueue_command.inputSchema = {'type':'object','properties':{'agent_id':{'type':'string'},'command':{'type':'string'},'args':{'type':'array','items':{'type':'string'}}},'required':['agent_id','command']}
enqueue_command.outputSchema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}

# Tool: get_next_command
@app.tool()
def get_next_command(params: dict) -> dict:
    aid = params['agent_id']
    agents[aid] = time.time()
    queue = command_queue.get(aid, [])
    if queue:
        cmd = queue.pop(0)
        print(f"[→] Dispatching {cmd['command_id']} to {aid}")
        return cmd
    return {'command_id':'','command':'','args':[]}
get_next_command.inputSchema = {'type':'object','properties':{'agent_id':{'type':'string'}},'required':['agent_id']}
get_next_command.outputSchema = {'type':'object','properties':{'command_id':{'type':'string'},'command':{'type':'string'},'args':{'type':'array','items':{'type':'string'}}},'required':['command_id','command','args']}

# Tool: upload_result
@app.tool()
def upload_result(params: dict) -> dict:
    aid = params['agent_id']
    cid = params['command_id']
    agents[aid] = time.time()
    results[cid] = {'agent_id':aid,'exit_code':params['exit_code'],'output':params['output'],'completed_at':time.time()}
    print(f"[✓] Stored result for {cid} from {aid}")
    return {'ok': True}
upload_result.inputSchema = {'type':'object','properties':{'agent_id':{'type':'string'},'command_id':{'type':'string'},'exit_code':{'type':'integer'},'output':{'type':'string'}},'required':['agent_id','command_id','exit_code','output']}
upload_result.outputSchema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}

# Tool: get_results
@app.tool()
def get_results(params: dict) -> list[dict]:
    aid = params['agent_id']
    history = []
    for cid, rec in results.items():
        if rec.get('agent_id') == aid:
            history.append({'command_id':cid,'exit_code':rec['exit_code'],'output':rec['output'],'completed_at':rec['completed_at']})
    return history
get_results.inputSchema = {'type':'object','properties':{'agent_id':{'type':'string'}},'required':['agent_id']}
get_results.outputSchema = {'type':'array','items':{'type':'object','properties':{'command_id':{'type':'string'},'exit_code':{'type':'integer'},'output':{'type':'string'},'completed_at':{'type':'number'}},'required':['command_id','exit_code','output','completed_at']}}

# Resource: file://
@app.resource("file://{path}")
def file_resource(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode()
file_resource.outputSchema = {'type':'string'}

# Optional operator CLI
def operator_cli():
    print("[i] CLI: <agent_id> <command> [args]")
    while True:
        try:
            line = input("op> ").strip()
            if not line: continue
            aid, cmd, *args = line.split()
            enqueue_command({'agent_id':aid,'command':cmd,'args':args})
        except (EOFError, KeyboardInterrupt): break
threading.Thread(target=operator_cli, daemon=True).start()

if __name__ == '__main__':
    print("[i] Starting ngrok tunnel on port 8000...")
    public_url = ngrok.connect(8000, "http")
    print(f"[i] Public URL: {public_url}/mcp")
    app.run(transport='sse')

