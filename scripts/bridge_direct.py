#!/usr/bin/env python3
"""Direct HTTP client for itasca-mcp-bridge.

The MCP server binds a single bridge URL at startup (default localhost:9001),
but each PFC Console runs its own stdlib HTTP bridge on its own port.  This
client talks to *any* bridge port directly, bypassing the one-to-one MCP
server.  Proxy env vars are explicitly disabled (they otherwise break even
localhost requests on Clash-style setups).

Usage:
    python bridge_direct.py probe 9001
    python bridge_direct.py code 9001 "import sys; print(sys.executable)"
    python bridge_direct.py task 9001 <script_path> <description> [task_id]
    python bridge_direct.py status 9001 <task_id> [wait_seconds]
"""
import json
import sys
import time
import urllib.request
import uuid

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(port, command, payload, timeout=30):
    body = dict(payload)
    body.setdefault("request_id", str(uuid.uuid4()))
    body.setdefault("type", command)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/{command}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe(port):
    r = post(port, "execute_code", {
        "code": "import sys\nprint('EXE=' + sys.executable)\n"
                "try:\n import itasca\n print('DIM=' + str(getattr(itasca,'_dimension','?')))\n"
                "except Exception as e:\n print('DIMERR=' + str(e))",
        "timeout_ms": 10000,
    })
    out = r.get("data", {}).get("output", "")
    exe = "pfc3d" if "pfc3d" in out.lower() else ("pfc2d" if "pfc2d" in out.lower() else "?")
    print(f"port {port}: status={r.get('status')} engine={exe} output={out.strip()!r}")


def code(port, snippet):
    r = post(port, "execute_code", {"code": snippet, "timeout_ms": 20000}, timeout=40)
    print(json.dumps(r, ensure_ascii=False, indent=2))


def task(port, script, description, task_id=None):
    tid = task_id or str(uuid.uuid4())[:6]
    r = post(port, "execute_task", {
        "task_id": tid, "script_path": script, "description": description, "source": "direct-http",
    }, timeout=15)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("TASK_ID=" + tid)


def status(port, task_id, wait=0):
    deadline = time.time() + wait
    while True:
        r = post(port, "check_task_status", {"task_id": task_id, "limit": 8}, timeout=20)
        data = r.get("data", {})
        state = data.get("task_status") or data.get("state") or r.get("status")
        print(json.dumps(r, ensure_ascii=False)[:1200])
        if state in ("completed", "failed", "cancelled") or time.time() >= deadline:
            break
        time.sleep(3)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    cmd, port = sys.argv[1], int(sys.argv[2])
    if cmd == "probe":
        probe(port)
    elif cmd == "code":
        code(port, sys.argv[3])
    elif cmd == "task":
        task(port, sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "status":
        status(port, sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    else:
        print("unknown command:", cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
