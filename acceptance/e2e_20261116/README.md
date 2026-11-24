# PFC Headless E2E Acceptance - 2026-11-16

This directory preserves real execution records for PFC 9.0 and
`itasca-mcp-bridge` 0.6.11.

## Primary evidence

| Item | Location |
|---|---|
| PFC2D environment | `../../reports/environment_pfc2d.json` |
| PFC3D environment | `../../reports/environment_pfc3d.json` |
| 2D instance | `instances/pfc2d_accept` |
| 3D instance | `instances/pfc3d_accept` |
| 2D Run | `runs/run_pfc2d_001` |
| Feedback rerun | `runs/run_pfc2d_002` |
| 2D contact capture | `runs/run_pfc2d_contact_002` |
| 3D Run | `runs/run_pfc3d_001` |
| 3D time sampling | `runs/run_pfc3d_time_sampling` |
| Interrupt probe | `runs/run_interrupt_probe3` |
| Timeout probe | `runs/run_timeout_probe` |
| Project audit | `audit/project_audit.jsonl` |
| Visualizations | `analysis/*_visualization` |
| Data verification | `analysis/*_verification.json` |

## Standardized deliveries

```text
deliveries/
|-- run_pfc2d_001/
|-- run_pfc2d_002/
|-- run_pfc2d_contact_002/
|-- run_pfc3d_001/
`-- run_pfc3d_time_sampling/
```

Each delivery contains the downstream contract, package metadata, complete file
manifest and quality report.

## Notes

- `run_pfc2d_002` is the real feedback-created rerun. Its same Case is the
  original packed smoke model, which has no active contacts despite enabling
  contact capture; the missing-data declaration is therefore preserved.
- `run_pfc2d_contact_002` uses a dedicated overlapping-contact model and proves
  the collector itself works when contacts exist.
- `run_interrupt_probe`, `run_interrupt_probe2`, and `run_timeout_probe` retain
  failed/unresolved probe history intentionally. They must not be reported as
  successful production Runs.
- Both authoritative Console processes were stopped safely with model save and
  audited fallback termination.

## Re-run tests

```powershell
& "D:\Itasca\PFC900\exe64\python310\python.exe" `
  "..\..\scripts\run_tests.py"
```

