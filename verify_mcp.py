"""Exercise the MCP adapter through the same CLI core and save the transcript."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


root = Path(__file__).resolve().parent
requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "nx12-cli-proof", "version": "1.0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "nx_doctor", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "nx_create_tube",
        "arguments": {"outer_d": 52, "bore_d": 20, "height": 35}}},
]
responses = []
with subprocess.Popen([sys.executable, str(root / "nxcli.py"), "mcp"],
                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, text=True, encoding="utf-8") as child:
    assert child.stdin and child.stdout and child.stderr
    for request in requests:
        child.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        child.stdin.flush()
        if "id" in request:
            responses.append(json.loads(child.stdout.readline()))
    child.stdin.close()
    child.wait(timeout=30)
    stderr = child.stderr.read()
    if child.returncode or stderr.strip():
        raise RuntimeError(f"MCP process exit={child.returncode}: {stderr}")

assert responses[0]["result"]["serverInfo"]["name"] == "nx12-cli-mcp"
assert {x["name"] for x in responses[1]["result"]["tools"]} == {"nx_doctor", "nx_create_tube", "nx_live_session"}
assert json.loads(responses[2]["result"]["content"][0]["text"])["ready"]
result = json.loads(responses[3]["result"]["content"][0]["text"])
assert result["passed"] and result["measurement"]["BODIES"] == "1"
trace = {"verified_at_utc": datetime.now(timezone.utc).isoformat(),
         "requests": requests, "responses": responses,
         "native_part_evidence": result["evidence_path"]}
path = root / "mcp_call_evidence.json"
path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": True, "trace": str(path), "native_part": result["output"]}, ensure_ascii=False))
