# Validation Report

Date: 2026-11-16  
Scope: Windows, PFC 9.0, `itasca-mcp-bridge` 0.6.11

## Static tests

| Check | Result |
|---|---|
| Python compile of all Skill modules | PASS |
| JSON Schemas and preserved data schemas load | PASS |
| Console-only source boundary | PASS |
| No GUI acceptance/autostart files | PASS |

## Unit and contract tests

Command:

```powershell
& "D:\Itasca\PFC900\exe64\python310\python.exe" scripts\run_tests.py
```

Result: **34 tests PASS**.

Coverage includes entity schemas, Project/Case/Run snapshots, immutable
packages, tamper rejection, Console discovery, GUI rejection, dynamic entity
offsets, capture recovery, feedback approval and new-Run preparation.

## Simulated tests

The existing Mock_Experiment input passed conversion, metadata generation,
manifest validation, NPZ offset checks and Visualization contract validation.
Mock data is labelled `MOCK`; it is not counted as PFC acceptance.

## Real environment

| Gate | PFC2D | PFC3D |
|---|---|---|
| Console executable discovered by content | PASS | PASS |
| GUI rejection | PASS | PASS |
| Engine-local Python | PASS | PASS |
| Bridge 0.6.11 dependency | PASS | PASS |
| Console process identity | PASS | PASS |
| `/health` and `runtime_mode=console` | PASS | PASS |
| Bridge PFC execution | PASS | PASS |
| Real `itasca-mcp` execution | PASS | PASS |

## Real PFC tests

| Test | Result | Evidence |
|---|---|---|
| PFC2D main smoke | PASS | `run_pfc2d_001`, task `b9b2bc`, 21 frames, 777 particle observations |
| PFC2D feedback rerun | PASS | `run_pfc2d_002`, task `35b72e`, 21 frames |
| PFC2D contact capture | PASS | `run_pfc2d_contact_002`, task `f4e181`, 17 frames, 51 contact observations |
| PFC3D main smoke | PASS | `run_pfc3d_001`, task `18678e`, 21 frames, 8253 particle observations |
| PFC3D mechanical-time sampling | PASS | `run_pfc3d_time_sampling`, task `bdf860`, 6 frames at 0.005 s interval |
| Short task via `itasca_execute_code` | PASS | PFC2D/PFC3D MCP probes |
| Long tracked task | PASS | all `execute_task` Runs above |
| Task status query | PASS | completed Run reconciliation |
| Real task interrupt | PASS | task `95769f`, final local state `INTERRUPTED` |
| Timeout unresolved state | PASS | `run_timeout_probe` recorded `TIMEOUT_UNKNOWN`; no resubmit |

No automated resubmission occurred after timeout.

## Data integrity

- Raw files remained separate from standardized files.
- Variable-length frame offsets matched particle observations.
- Real 2D z values remained numeric embedding zero.
- Real 3D coordinates remained three-dimensional.
- Original and rerun deliverables have different manifests and hashes.
- `data verify` returned PASS for the 2D, contact, and 3D packages.
- A tampered package test returned FAIL.

## Downstream delivery

| Package | Visualization result |
|---|---|
| `run_pfc2d_001` | Generated analysis, Viewer and output metadata |
| `run_pfc2d_002` | Generated again with a different source manifest |
| `run_pfc2d_contact_002` | `contact_network=SUPPORTED` |
| `run_pfc3d_001` | Generated 3D analysis, Viewer and output metadata |

The downstream pipeline consumed only `pfc.standardized-experiment@1.0.0`.

## End-to-end feedback loop

1. Real PFC2D Run produced a standardized package.
2. Visualization consumed it and reported `contact_network=NOT_CAPTURED`.
3. Headless ingested and validated the structured feedback.
4. Approval was recorded with reviewer and rationale.
5. Headless created and executed `run_pfc2d_002` without modifying the source.
6. Visualization consumed the new delivery.

The same Case did not itself contain active contacts, so the rerun preserved the
missing-contact finding. A separate real contact Case proved the collector can
capture contacts when the model actually has them.

## Not verified

- Browser interaction/performance acceptance for generated Viewer.
- More than one installed PFC version on this machine.
- Simultaneous multi-instance operation.
- 3D contact capture on a real 3D contact model.
- Non-empty native History capture after this split.
- New real fracture-event sampling.
- Current code path for one-shot `direct` transport after this split.

## Known limitations

- PFC `program stop` did not terminate either acceptance process within 20 s.
  Both stops used verified PID termination after model save. Reports therefore
  set `native_graceful_exit_claimed=false`.
- One MCP process routes to one Bridge URL; separate MCP processes are needed
  for concurrent engines.
- Contact capture is opt-in and can be expensive for dense models.
- Clump membership is not part of the baseline collector.

## PR9-PR14 rectification revalidation

Date: 2026-11-16  
Workspace: `acceptance/rectification_20261116`

### Test totals

- Headless unit/contract tests: **44 PASS**.
- Visualization unit/contract tests: **66 PASS**.
- Python compile: PASS for both Skill script trees.
- Skill Creator quick validation: PASS for both Skills.

### Real PFC and MCP

| Gate | Result | Evidence |
|---|---|---|
| PFC2D READY with current nonce | PASS | instance `rect_pfc2d_9001`, PID 29824 |
| PFC3D READY with current nonce | PASS | instance `rect_pfc3d_9001`, PID 30532 |
| Second PFC2D READY through independent stdio MCP | PASS | instance `rect_pfc2d_9002`, PID 32060 |
| PFC2D standard Run | PASS | `rect_pfc2d_001`, task `2ef8c6`, 21 frames, 777 Ball observations |
| PFC3D standard Run | PASS | `rect_pfc3d_001`, task `005566`, 21 frames, 8253 Ball observations |
| Contact-free source | PASS | `rect_contact_source_002`, 17 frames, 0 contacts |
| Contact feedback rerun | PASS | `rect_contact_feedback_001`, 51 contact observations |
| Feedback success path | PASS | `feedback_rect_contact_source_002=VALIDATED` |
| Feedback failure/retry path | PASS | `feedback_rect_pfc2d_001=FAILED` with retry preserved |
| Real MCP interrupt | PASS | tasks `6f19f6`, `45ba2c`, `6cc5e9` |
| Multi-instance isolation | PASS | `6cc5e9` interrupted while `45ba2c` remained running |
| Recovery after interrupt | PASS | 370 complete-index frames, 37 blocks; no science derivation |
| Cross-Skill Findings Producer | PASS | real PFC2D and PFC3D Findings contracts |
| Data package verification | PASS | five generated packages, zero errors |

### Remaining unverified

- A new live timeout-after-request condition was not reproduced in this pass.
- No new non-empty native History was generated.
- No new real fracture event was generated.
- Clump membership remains not implemented.
- Browser/Viewer visual acceptance remains a Visualization responsibility.

