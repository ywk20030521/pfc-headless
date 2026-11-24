# Engine Lifecycle

## Discovery

Discovery scans configured installation roots, verifies PFC2D/PFC3D product
markers and Console markers inside the executable, and excludes GUI names.
Runtime identity remains authoritative.

The engine-local Python environment must provide `psutil` for PID, executable
and command-line verification before reuse or stop.

## Start

`ConsoleRuntime` writes an isolated bootstrap under
`<workdir>/.pfc-console/`, starts:

```text
pfc*d*_console.exe --run <bootstrap.py>
```

stdin is `DEVNULL`. The Bridge starts with `mode="console"` and
`auto_upgrade=False`.

The runtime records PID, executable hash, command line, workdir, port, probe
result and timestamps. An existing listener is reused only if product,
dimension, executable and working directory all match.

Each start also creates a one-time readiness nonce and stable identity
fingerprint. A probe from an earlier process can never promote a restarted
instance to READY.

## Ready

An instance is not `READY` after `/health`. It requires:

- process identity;
- Bridge health;
- Bridge PFC execution;
- external `itasca-mcp` execution evidence that echoes the current nonce and
  matches the current identity fingerprint and expiry.

## Stop

The safe sequence is:

1. verify registered PID/executable/command line;
2. list tasks and interrupt any pending/running task;
3. request `model save`;
4. verify identity again;
5. request PFC `program stop` through the public Bridge execution API;
6. wait, then use verified PID termination only as a disclosed fallback;
7. record the method in the lifecycle audit.

The Bridge package does not expose a remote `/stop` HTTP route. A fallback
process termination is never described as PFC's native graceful exit.

