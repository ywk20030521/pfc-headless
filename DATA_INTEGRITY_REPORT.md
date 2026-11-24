# Data Integrity Report

## Real packages

| Run | Dimension | Frames | Records | Package check |
|---|---:|---:|---|---|
| `run_pfc2d_001` | 2 | 21 | 777 Ball observations | PASS |
| `run_pfc2d_002` | 2 | 21 | 861 Ball observations | PASS |
| `run_pfc2d_contact_002` | 2 | 17 | 51 contacts (51 Ball observations) | PASS |
| `run_pfc3d_001` | 3 | 21 | 8253 Ball observations | PASS |
| `run_pfc3d_time_sampling` | 3 | 6 | time-interval samples | PASS |

## Gates

- Original raw files are retained outside the standardized package.
- Cycle and mechanical time are strictly increasing.
- Frame Ball sets are represented by explicit variable-length offsets.
- Added and removed Ball IDs are retained.
- Real velocity and angular velocity are present for every captured Ball row.
- Optional contact samples include ID, endpoints, position, model and force.
- PFC2D z is numeric embedding zero; PFC3D z is physical.
- `metadata.json` and `manifest.json` agree with actual files.
- SHA-256 and size mismatches fail verification.
- A tampered package test produced `FAIL`.
- Visualization consumed the standardized manifest without reading raw/internal
  Headless implementation.

All package verification reports are in
`acceptance/e2e_20261116/analysis/*_verification.json`.

