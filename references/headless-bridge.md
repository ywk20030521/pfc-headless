# Console Bridge Guide

## Execution chain

```text
Agent -> itasca-mcp -> itasca-mcp-bridge HTTP/SSE -> PFC Console main thread
```

Headless emits official MCP operation descriptors and records evidence. It does
not implement another MCP server, MCP/Bridge execution client, task queue or
engine runtime.

## Launch rule

PFC Console accepts a script file through `--run`:

```powershell
pfc3d9_console.exe --run "<bootstrap.py>"
```

Redirected stdin is not an input channel and must not be used. Stdout and stderr
may be logged.

The bootstrap starts the installed Bridge with:

```python
itasca_mcp_bridge.start(
    host="127.0.0.1",
    port=port,
    mode="console",
    auto_upgrade=False,
)
```

## Verification

```powershell
Invoke-RestMethod http://127.0.0.1:9001/health
```

Expected fields include:

```json
{"status":"success","version":"0.6.11","runtime_mode":"console"}
```

Then run a real PFC probe through `itasca_execute_code` in `itasca-mcp`, for
example:

```python
import itasca
print(itasca.dim(), itasca.cycle(), itasca.ball.count())
```

The probe must echo the current instance readiness nonce. Record the response
in `connection record-mcp`; verification also compares PID, executable,
command line, dimension, port, MCP connection and expiry.

## Multiple instances

Each instance has its own state directory and port. A single MCP *server*
configuration binds one Bridge URL at startup, but the Bridge itself is a plain
stdlib HTTP endpoint and can be reached directly without the MCP server. So
multiple engines are supported in two ways:

1. **HTTP direct (recommended for multi-engine work).** Each Console runs its
   own Bridge on its own port (e.g. 9001 = PFC3D, 9002 = PFC2D). Call the Bridge
   over HTTP directly with `scripts/bridge_direct.py` — no MCP process needed,
   any number of ports at once:

   ```bash
   python scripts/bridge_direct.py probe 9001          # identify engine on a port
   python scripts/bridge_direct.py code 9002 "print('hi')"
   python scripts/bridge_direct.py task 9002 <capture_case.py> <desc> <task_id>
   python scripts/bridge_direct.py status 9002 <task_id> 90
   ```

   The protocol is `POST /<command>` with a JSON envelope (`type`,
   `request_id`, command fields); responses are JSON. `execute_code`,
   `execute_task`, `check_task_status`, `list_tasks`, `interrupt_task` are all
   stateless. `GET /events` (SSE) is only an optional doorbell. The client
   disables proxy env vars (`ProxyHandler({})`) because Clash-style proxy
   setups otherwise route even localhost through the proxy and surface as
   `bridge_unavailable`.

2. **Separate MCP servers.** Register one `itasca-mcp` per port via
   `--bridge-port 9002` (or `ITASCA_MCP_BRIDGE_URL`), each as its own MCP
   server entry. This requires a session restart to take effect.

Either way, headless Run evidence carries `instance_id` + `identity_fingerprint`,
so two Runs on different bridges stay independent and verifiable.

## Scripts

```powershell
pwsh -File scripts\discover-engine.ps1 -Dimension 3
pwsh -File scripts\start-bridge.ps1 -WorkDir "<runtime>" -Dimension 3 -Port 9001
pwsh -File scripts\stop-bridge.ps1 -WorkDir "<runtime>" -Dimension 3 -Port 9001
```

`scripts/bridge_direct.py` is the multi-port HTTP client (see Multiple
instances). The stop script calls the shared safe-stop implementation; it does
not kill processes by executable name.

## Logs

- `<workdir>/.pfc-console/console_stdout.log`
- `<workdir>/.pfc-console/console_stderr.log`
- `<workdir>/.pfc-console/lifecycle_audit.jsonl`
- `<workdir>/.itasca-mcp-bridge/bridge.log`

