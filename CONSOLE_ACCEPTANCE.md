# Real Console Acceptance

## PFC2D

- Engine: `D:\Itasca\PFC900\exe64\pfc2d9_console.exe`
- SHA-256: `20ffb56da3f3acc4bc51c05043a9c6f31d796ce8b13cc7ee6f7f8626392f3f40`
- Bridge: 0.6.11, `runtime_mode=console`
- Process: PID 33204
- Instance: `pfc2d_accept`
- MCP execution: PASS
- Main Run: `run_pfc2d_001`, task `b9b2bc`
- Frames: 21
- Particle observations: 777
- Feedback rerun: `run_pfc2d_002`, task `35b72e`
- Contact capture: `run_pfc2d_contact_002`, task `f4e181`,
  17 frames / 51 contacts

## PFC3D

- Engine: `D:\Itasca\PFC900\exe64\pfc3d9_console.exe`
- SHA-256: `e4e15cfbf8c4ea97d6ba1fe4fb4c35f45dc850a28074dfd50dcaf1fc5d2ac673`
- Bridge: 0.6.11, `runtime_mode=console`
- Process: PID 5500
- Instance: `pfc3d_accept`
- MCP execution: PASS
- Main Run: `run_pfc3d_001`, task `18678e`
- Frames: 21
- Particle observations: 8253
- Mechanical-time sampling: `run_pfc3d_time_sampling`, task `bdf860`,
  6 frames at 0.005 s

## Task control

- Interrupt: task `95769f`, final local state `INTERRUPTED`.
- Timeout: `run_timeout_probe` entered `TIMEOUT_UNKNOWN`; no automatic resubmit.

## Safe stop

Both instances:

- checked active tasks;
- executed `model save`;
- re-verified PID, executable and command line;
- requested PFC `program stop`;
- remained alive after the 20 s wait;
- used verified PID termination as the disclosed fallback.

`native_graceful_exit_claimed=false` in both audit records.

Evidence workspace:
[acceptance/e2e_20261116](acceptance/e2e_20261116).

