"""Proof that MCP can perform successive edits in one persistent NX session."""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from nxcli import LIVE_STATE, live_action


root = Path(__file__).resolve().parent
requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-03-26", "capabilities": {},
    "clientInfo": {"name": "nx12-live-proof", "version": "1.0"}}}]
for identifier, action, other in [
    (2, "start", {}),
    (3, "status", {}),
    (4, "create", {"outer_d": 50, "height": 40}),
    (5, "bore", {"bore_d": 18}),
    (6, "info", {}),
    (7, "save", {}),
    (8, "stop", {}),
]:
    requests.append({"jsonrpc": "2.0", "id": identifier, "method": "tools/call",
                     "params": {"name": "nx_live_session", "arguments": {"action": action, **other}}})

responses = []
try:
    with subprocess.Popen([sys.executable, str(root / "nxcli.py"), "mcp"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8") as child:
        assert child.stdin and child.stdout and child.stderr
        for request in requests:
            child.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            child.stdin.flush()
            response = json.loads(child.stdout.readline())
            if response.get("result", {}).get("isError"):
                raise RuntimeError(response["result"]["content"][0]["text"])
            responses.append(response)
        child.stdin.close()
        child.wait(timeout=15)
        if child.returncode or child.stderr.read().strip():
            raise RuntimeError("MCP server process failed")
finally:
    if LIVE_STATE.exists():
        live_action("stop")

details = [json.loads(item["result"]["content"][0]["text"]) for item in responses[1:]]
pid = details[0]["nx_pid"]
assert details[1]["nx_pid"] == pid
assert details[2]["response"][1] == str(pid)
assert details[3]["response"][1] == str(pid)
assert details[4]["nx_pid"] == pid
assert details[5]["nx_pid"] == pid and details[5]["passed"]
assert float(details[3]["response"][5]) < float(details[2]["response"][5])
trace = {"verified_at_utc": datetime.now(timezone.utc).isoformat(),
         "requests": requests, "responses": responses, "nx_pid": pid,
         "model": details[5]["model"], "independent_reopen": details[5]["independent_reopen"]}
path = root / "mcp_live_evidence.json"
path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": True, "trace": str(path), "model": details[5]["model"],
                  "nx_pid": pid}, ensure_ascii=False))
