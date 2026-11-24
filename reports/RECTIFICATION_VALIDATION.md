# PR9-PR14 Rectification Validation

Date: 2026-11-16  
Workspace: `pfc-headless/acceptance/rectification_20261116`

## Verdict

The four P1 architecture findings and the reviewed P2 gaps are implemented in
the code paths. The result is **strict architecture acceptance PASS for the
executed gates**, with the remaining item-specific limitations listed below.

## Unit and validation gates

| Gate | Result |
|---|---|
| Headless tests | 44 PASS, 0 FAIL |
| Visualization tests | 66 PASS, 0 FAIL |
| Python compile | PASS |
| Skill quick validation | PASS for both Skills |
| PFC/Bridge environment | PFC 9.0, Bridge 0.6.11, psutil 5.9.6 |

## MCP-only Run boundary

- `run prepare` creates and fingerprints the Run without submitting PFC work.
- The Agent Host calls `itasca_execute_task`.
- `run attach-task` verifies Run ID, nonce, entry script, unique task ID,
  instance ID and MCP connection before binding the task.
- `run status` and `run interrupt` emit MCP operations after resolving the
  route from Run Registry; neither accepts a user-supplied port.
- `run finalize` validates and standardizes local output without network calls.

The PFC2D and PFC3D normal Runs completed through this path.

## READY identity binding

Each instance received:

- a one-time readiness nonce;
- current PID, executable, command line, dimension and port fingerprint;
- MCP connection identity and expiry.

The evidence for the second PFC2D instance was deliberately submitted against
the PFC3D instance and was rejected.

## Multiple instances

Two Consoles ran concurrently:

| Instance | MCP connection | Task | Result |
|---|---|---|---|
| PFC3D `rect_pfc3d_9001` | desktop `codex_itasca_9001` | `45ba2c` | running after `6cc5e9` was interrupted |
| PFC2D `rect_pfc2d_9002` | independent official stdio MCP | `6cc5e9` | interrupted independently |

The PFC3D task remained running for the isolation check and was then separately
interrupted.

## Feedback

The state transitions are now:

```text
APPROVED -> PROPOSED -> RUNNING -> VALIDATED
                              `-> FAILED -> retry
```

Observed results:

- contact-free model -> producer Findings -> approval -> MCP rerun with 51 real
  contact observations -> `VALIDATED`;
- the earlier smoke Case remained without contacts -> `FAILED`, not `USED`.

## Data and recovery

- `rect_pfc2d_001`: 21 frames, 777 Ball observations.
- `rect_pfc3d_001`: 21 frames, 8253 Ball observations.
- `rect_contact_source_002`: 17 frames, zero contact rows.
- `rect_contact_feedback_001`: 17 frames, 51 contact rows.
- `rect_interrupt_001`: MCP-interrupted PFC3D task recovered 370 complete-index
  frames in 37 blocks.

All five standardized packages passed `data verify`.

## Cross-Skill closure

Visualization now runs `emit_findings.py` and writes the
`pfc.analysis-findings@1.0.0` contract. The Producer output includes the source
manifest hash, referenced artifacts, missing channels and a recommended
collection plan. Headless validates and ingests that file before approval.

## Remaining limitations

- Live unresolved timeout was not reproduced after the architecture change.
- Native non-empty Histories were not generated.
- New real fracture-event sampling was not verified.
- Clump membership remains intentionally unimplemented.
- Browser and publication visual acceptance were not rerun here.
