"""Prove several incremental edits in one persistent NX 12 process."""

import hashlib
import json
import math
import os
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nxcli import NX, ROOT, VERIFY, run_journal, sha256


job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-live-" + uuid.uuid4().hex[:6]
root = ROOT / "artifacts" / "live"
job = root / job_id
job.mkdir(parents=True, exist_ok=False)
stage = job / "staging"
stage.mkdir()
model = job / "live_tube.prt"
with socket.socket() as choice:
    choice.bind(("127.0.0.1", 0))
    port = choice.getsockname()[1]
token = uuid.uuid4().hex
server_log = job / "live_server.stdout.txt"
server_error = job / "live_server.stderr.txt"
evidence_file = job / "live_evidence.json"
env = os.environ.copy()
env.update({"UGII_BASE_DIR": str(NX), "UGII_TMP_DIR": str(stage),
            "UGII_TMP": str(stage), "TMP": str(stage), "TEMP": str(stage)})
calls = []
process = None


def call(*fields: str, record=True) -> list[str]:
    result = subprocess.run([str(ROOT / "pipe_client.exe"), str(port), token, *fields],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=7)
    if result.returncode:
        raise RuntimeError(f"pipe call {fields[0]}: {result.stderr or result.stdout}")
    data = result.stdout.strip().split("\t")
    if not data or data[0] != "OK":
        raise RuntimeError(f"pipe returned {data}")
    if record:
        calls.append({"command": fields[0], "arguments": list(fields[1:]),
                      "response": data, "at_utc": datetime.now(timezone.utc).isoformat()})
    return data


evidence = {"job_id": job_id, "loopback_port": port,
            "mode": "persistent headless NX 12 session over an authenticated loopback bridge",
            "source_sha256": sha256(ROOT / "journals" / "LivePipe.cs"),
            "calls": calls, "model": str(model), "passed": False}
try:
    with server_log.open("w", encoding="utf-8") as stdout, server_error.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [str(NX / "NXBIN" / "run_journal.exe"), str(ROOT / "journals" / "LivePipe.cs"),
             "-args", str(port), token, str(root)],
            cwd=stage, env=env, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 45
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"NX live server exited early: {process.returncode}")
            try:
                ping = call("PING")
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("NX live loopback bridge did not become ready")
                time.sleep(1)
        pid = ping[1]
        before = call("CREATE", "40", "60")
        after = call("BORE", "16")
        info = call("INFO")
        saved = call("SAVE", str(model))
        assert before[1] == after[1] == info[1] == saved[1] == pid
        assert before[3] == after[3] == info[3] == "1"
        assert int(after[4]) > int(before[4])
        before_volume = float(before[5])
        after_volume = float(after[5])
        expected = math.pi * (40**2 - 16**2) * 60 / 4
        assert after_volume < before_volume and abs(after_volume - expected) / expected < 0.005
        assert model.is_file()
        part_hash = sha256(model)
        call("STOP")
        process.wait(timeout=15)
        if process.returncode != 0:
            raise RuntimeError(f"NX service exit={process.returncode}")

    verifier = run_journal(VERIFY, [str(model), "40", "16", "60"], job_id + "-reopen", job)
    assert part_hash == sha256(model)
    evidence.update({"nx_pid": pid, "volume_before_mm3": before_volume,
                     "volume_after_mm3": after_volume, "expected_volume_mm3": expected,
                     "part_sha256": part_hash, "independent_reopen": verifier,
                     "server_stdout": str(server_log), "server_stderr": str(server_error),
                     "passed": True})
finally:
    if process is not None and process.poll() is None:
        try:
            call("STOP")
            process.wait(timeout=5)
        except Exception:
            process.terminate()
            process.wait(timeout=5)
    evidence_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"passed": True, "evidence": str(evidence_file),
                  "model": str(model), "nx_pid": evidence["nx_pid"]}, ensure_ascii=False))
