"""One NX 12 modeling core for both a human CLI and a local MCP tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NX = Path(os.environ.get("NX12_ROOT", r"E:\Program Files\Siemens\NX 12.0"))
ARTIFACTS = ROOT / "artifacts"
CREATE = ROOT / "journals" / "CreateTube.cs"
VERIFY = ROOT / "journals" / "VerifyTube.cs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def doctor() -> dict:
    checks = {
        "nx_12_journal": (NX / "NXBIN" / "run_journal.exe").is_file(),
        "nxopen_managed": (NX / "NXBIN" / "managed" / "NXOpen.dll").is_file(),
        "create_journal": CREATE.is_file(),
        "verify_journal": VERIFY.is_file(),
        "live_bridge_journal": (ROOT / "journals" / "LivePipe.cs").is_file(),
        "live_bridge_client": (ROOT / "pipe_client.exe").is_file(),
    }
    active = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "@(Get-Process -Name ugraf -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True, timeout=10,
    )
    try:
        gui_count = int(active.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        gui_count = None
    return {
        "checks": checks,
        "nx_gui_process_count": gui_count,
        "mode": "NX 12 batch and persistent headless bridge; visible GUI attachment not yet verified",
        "ready": all(checks.values()),
    }


def validate_dimensions(outer_d: float, bore_d: float, height: float) -> None:
    if not all(math.isfinite(value) for value in (outer_d, bore_d, height)):
        raise ValueError("dimensions must be finite")
    if not 1 <= bore_d < outer_d <= 300:
        raise ValueError("require 1 <= bore_d < outer_d <= 300 mm")
    if not 1 <= height <= 500:
        raise ValueError("require 1 <= height <= 500 mm")


def run_journal(source: Path, arguments: list[str], tag: str, job: Path) -> dict:
    staging = job / "staging"
    staging.mkdir(exist_ok=True)
    command = [str(NX / "NXBIN" / "run_journal.exe"), str(source), "-args", *arguments]
    env = os.environ.copy()
    env.update({"UGII_BASE_DIR": str(NX), "UGII_TMP_DIR": str(staging),
                "UGII_TMP": str(staging), "TMP": str(staging), "TEMP": str(staging)})
    started = time.monotonic()
    process = subprocess.run(command, cwd=staging, env=env, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=210)
    elapsed = round(time.monotonic() - started, 3)
    stdout_file = job / f"{tag}.runner.stdout.txt"
    stderr_file = job / f"{tag}.runner.stderr.txt"
    stdout_file.write_text(process.stdout, encoding="utf-8")
    stderr_file.write_text(process.stderr, encoding="utf-8")
    report = {
        "journal": source.name,
        "exit_code": process.returncode,
        "duration_s": elapsed,
        "stdout": str(stdout_file),
        "stderr": str(stderr_file),
        "passed": process.returncode == 0 and "RESULT: PASS" in process.stdout
        and "Compilation failed" not in process.stdout,
    }
    if not report["passed"]:
        raise RuntimeError(f"{source.name} failed; see {stdout_file} and {stderr_file}")
    return report


def build_tube(outer_d: float, bore_d: float, height: float) -> dict:
    validate_dimensions(outer_d, bore_d, height)
    status = doctor()
    if not status["ready"]:
        raise RuntimeError("NX CLI is not ready: " + json.dumps(status["checks"]))
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    job = ARTIFACTS / job_id
    job.mkdir(parents=True, exist_ok=False)
    output = job / "tube.prt"
    args = [str(output), f"{outer_d:.9g}", f"{bore_d:.9g}", f"{height:.9g}"]
    evidence = {
        "job_id": job_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs_mm": {"outer_d": outer_d, "bore_d": bore_d, "height": height},
        "mode": "two independent NX 12 journal processes",
        "output": str(output),
        "source_sha256": {CREATE.name: sha256(CREATE), VERIFY.name: sha256(VERIFY)},
    }
    report_path = job / "evidence.json"
    try:
        evidence["create"] = run_journal(CREATE, args, job_id + "-create", job)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("NX reported success but no non-empty .prt was saved")
        before = sha256(output)
        evidence["verify"] = run_journal(VERIFY, args, job_id + "-verify", job)
        after = sha256(output)
        if before != after:
            raise RuntimeError("Independent verification modified the saved .prt")
        verify_text = Path(evidence["verify"]["stdout"]).read_text(encoding="utf-8")
        measurements = dict(re.findall(r"^(BODIES|FEATURES|SUPPRESSED|VOLUME_MM3|EXPECTED_MM3|RELATIVE_ERROR)=([^\r\n]+)", verify_text, re.M))
        if measurements.get("BODIES") != "1" or measurements.get("SUPPRESSED") != "0":
            raise RuntimeError("Independent NX geometry report failed")
        evidence["measurement"] = measurements
        evidence["part_sha256"] = after
        evidence["part_bytes"] = output.stat().st_size
        evidence["passed"] = True
    except Exception as error:
        evidence["passed"] = False
        evidence["error"] = str(error)
        raise
    finally:
        report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["evidence_path"] = str(report_path)
    return evidence


LIVE_ROOT = ARTIFACTS / "live"
LIVE_STATE = LIVE_ROOT / "session.json"


def read_live_state() -> dict:
    if not LIVE_STATE.is_file():
        raise RuntimeError("No live NX session. Run live-start first.")
    return json.loads(LIVE_STATE.read_text(encoding="utf-8"))


def write_live_state(state: dict) -> None:
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = LIVE_STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(LIVE_STATE)


def bridge_call(state: dict, *fields: str) -> list[str]:
    process = subprocess.run(
        [str(ROOT / "pipe_client.exe"), str(state["port"]), state["token"], *fields],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
    )
    if process.returncode:
        raise RuntimeError(f"NX live {fields[0]}: {process.stderr or process.stdout}")
    answer = process.stdout.strip().split("\t")
    if not answer or answer[0] != "OK":
        raise RuntimeError(f"NX live {fields[0]} returned {answer}")
    return answer


def record_live(state: dict, action: str, response: list[str]) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(),
             "action": action, "response": response}
    path = Path(state["session_dir"]) / "cli_events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def live_action(action: str, **values: float) -> dict:
    if action == "start":
        if LIVE_STATE.exists():
            state = read_live_state()
            try:
                bridge_call(state, "PING")
            except RuntimeError:
                raise RuntimeError(f"Stale live session file: {LIVE_STATE}; inspect before restarting")
            raise RuntimeError("Live NX session already running")
        if not doctor()["ready"] or not (ROOT / "pipe_client.exe").is_file():
            raise RuntimeError("NX 12 or local bridge client missing")
        LIVE_ROOT.mkdir(parents=True, exist_ok=True)
        with socket.socket() as selected:
            selected.bind(("127.0.0.1", 0))
            port = selected.getsockname()[1]
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        session_dir = LIVE_ROOT / session_id
        session_dir.mkdir()
        staging = session_dir / "staging"
        staging.mkdir()
        state = {"session_id": session_id, "port": port, "token": uuid.uuid4().hex,
                 "session_dir": str(session_dir), "created_at_utc": datetime.now(timezone.utc).isoformat(),
                 "dimensions_mm": {}}
        env = os.environ.copy()
        env.update({"UGII_BASE_DIR": str(NX), "UGII_TMP_DIR": str(staging),
                    "UGII_TMP": str(staging), "TMP": str(staging), "TEMP": str(staging)})
        with (session_dir / "server.stdout.txt").open("w", encoding="utf-8") as out, \
             (session_dir / "server.stderr.txt").open("w", encoding="utf-8") as err:
            child = subprocess.Popen(
                [str(NX / "NXBIN" / "run_journal.exe"), str(ROOT / "journals" / "LivePipe.cs"),
                 "-args", str(port), state["token"], str(LIVE_ROOT)],
                cwd=staging, env=env, stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError(f"NX live server exited; see {session_dir / 'server.stdout.txt'}")
            try:
                ping = bridge_call(state, "PING")
                state["nx_pid"] = int(ping[1])
                write_live_state(state)
                record_live(state, "start", ping)
                return {"session_id": session_id, "nx_pid": state["nx_pid"],
                        "mode": "persistent headless NX 12", "state": str(LIVE_STATE)}
            except RuntimeError:
                time.sleep(1)
        child.terminate()
        raise TimeoutError("NX live bridge did not start within 45 seconds")

    state = read_live_state()
    if action in {"status", "info"}:
        reply = bridge_call(state, "PING" if action == "status" else "INFO")
        record_live(state, action, reply)
        return {"session_id": state["session_id"], "nx_pid": int(reply[1]),
                "response": reply, "dimensions_mm": state["dimensions_mm"]}
    if action == "create":
        outer, height = values.get("outer_d"), values.get("height")
        if outer is None or height is None:
            raise ValueError("create requires outer_d and height")
        validate_dimensions(float(outer), 1, float(height))
        reply = bridge_call(state, "CREATE", str(outer), str(height))
        record_live(state, action, reply)
        state["dimensions_mm"] = {"outer_d": outer, "height": height}
        write_live_state(state)
        return {"session_id": state["session_id"], "response": reply}
    if action == "bore":
        bore = values.get("bore_d")
        if bore is None or not state["dimensions_mm"]:
            raise ValueError("bore requires bore_d after create")
        validate_dimensions(float(state["dimensions_mm"]["outer_d"]), float(bore),
                            float(state["dimensions_mm"]["height"]))
        reply = bridge_call(state, "BORE", str(bore))
        record_live(state, action, reply)
        state["dimensions_mm"]["bore_d"] = bore
        write_live_state(state)
        return {"session_id": state["session_id"], "response": reply}
    if action == "save":
        dims = state["dimensions_mm"]
        if set(dims) != {"outer_d", "bore_d", "height"}:
            raise ValueError("create and bore must finish before save")
        output = Path(state["session_dir"]) / "live_tube.prt"
        reply = bridge_call(state, "SAVE", str(output))
        record_live(state, action, reply)
        original = sha256(output)
        verification = run_journal(VERIFY, [str(output), str(dims["outer_d"]),
                                            str(dims["bore_d"]), str(dims["height"])],
                                   state["session_id"] + "-independent", Path(state["session_dir"]))
        if sha256(output) != original:
            raise RuntimeError("Independent verification changed the model")
        result = {"session_id": state["session_id"], "nx_pid": state["nx_pid"],
                  "model": str(output), "part_sha256": original,
                  "response": reply, "independent_reopen": verification, "passed": True}
        events_file = Path(state["session_dir"]) / "cli_events.jsonl"
        result["events"] = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
        evidence_path = Path(state["session_dir"]) / "cli_live_evidence.json"
        evidence_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["evidence_path"] = str(evidence_path)
        return result
    if action == "stop":
        reply = bridge_call(state, "STOP")
        record_live(state, action, reply)
        LIVE_STATE.unlink()
        return {"session_id": state["session_id"], "response": reply}
    raise ValueError("Unknown live action")


TOOLS = [
    {"name": "nx_doctor", "description": "Read local NX 12 CLI readiness and GUI process status.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "nx_create_tube", "description": "Create and independently reopen-check a new NX 12 tube part.",
     "inputSchema": {"type": "object", "properties": {
         "outer_d": {"type": "number", "minimum": 1, "maximum": 300},
         "bore_d": {"type": "number", "minimum": 1, "maximum": 300},
         "height": {"type": "number", "minimum": 1, "maximum": 500}},
         "required": ["outer_d", "bore_d", "height"], "additionalProperties": False}},
    {"name": "nx_live_session", "description": "Operate one persistent headless NX 12 session in separate steps.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["start", "status", "create", "bore", "info", "save", "stop"]},
         "outer_d": {"type": "number", "minimum": 2, "maximum": 300},
         "bore_d": {"type": "number", "minimum": 1, "maximum": 299},
         "height": {"type": "number", "minimum": 1, "maximum": 500}},
         "required": ["action"], "additionalProperties": False}},
]


def mcp_result(request: dict) -> dict | None:
    request_id = request.get("id")
    if request_id is None:
        return None
    method = request.get("method")
    if method == "initialize":
        value = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                 "serverInfo": {"name": "nx12-cli-mcp", "version": "0.1.0"}}
    elif method == "tools/list":
        value = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "nx_doctor":
                if arguments:
                    raise ValueError("nx_doctor accepts no arguments")
                details = doctor()
            elif name == "nx_create_tube":
                if set(arguments) != {"outer_d", "bore_d", "height"}:
                    raise ValueError("exactly outer_d, bore_d, height are required")
                details = build_tube(**arguments)
            elif name == "nx_live_session":
                action = arguments.get("action")
                allowed = {"create": {"action", "outer_d", "height"},
                           "bore": {"action", "bore_d"}}
                if set(arguments) != allowed.get(action, {"action"}):
                    raise ValueError("unexpected arguments for live action")
                details = live_action(action, **{k: v for k, v in arguments.items() if k != "action"})
            else:
                raise ValueError("unknown tool")
            value = {"content": [{"type": "text", "text": json.dumps(details, ensure_ascii=False)}]}
        except Exception as error:
            value = {"isError": True, "content": [{"type": "text", "text": str(error)}]}
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def serve_mcp() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = mcp_result(request)
        except Exception as error:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": str(error)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="NX 12 CAD CLI with independent native verification")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read local dependencies and NX GUI status")
    build = sub.add_parser("build-tube", help="Create a new native .prt and verify it in a separate NX process")
    build.add_argument("--outer-d", type=float, required=True, help="Outer diameter in mm")
    build.add_argument("--bore-d", type=float, required=True, help="Through bore diameter in mm")
    build.add_argument("--height", type=float, required=True, help="Height in mm")
    sub.add_parser("mcp", help="Run the stdio MCP adapter")
    live = sub.add_parser("live", help="Operate a persistent headless NX session")
    live.add_argument("action", choices=["start", "status", "create", "bore", "info", "save", "stop"])
    live.add_argument("--outer-d", type=float)
    live.add_argument("--bore-d", type=float)
    live.add_argument("--height", type=float)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "build-tube":
            result = build_tube(args.outer_d, args.bore_d, args.height)
        elif args.command == "live":
            supplied = {key: value for key, value in
                        {"outer_d": args.outer_d, "bore_d": args.bore_d, "height": args.height}.items()
                        if value is not None}
            result = live_action(args.action, **supplied)
        else:
            serve_mcp()
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ready", True) else 1
    except Exception as error:
        print(json.dumps({"passed": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
