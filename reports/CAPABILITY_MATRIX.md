# Capability Matrix

`Implemented` means code/contracts exist. `Verified` identifies the strongest
acceptance actually executed in this implementation.

| Capability | Status | Evidence |
|---|---|---|
| PFC2D Console discovery | Implemented / Verified | environment report, real executable |
| PFC3D Console discovery | Implemented / Verified | environment report, real executable |
| GUI executable rejection | Implemented / Verified | contract tests |
| Multiple installed versions | Implemented / NOT_VERIFIED | only PFC 9.0 installed |
| Dynamic Console filename by content | Implemented / Verified | unit fixture |
| Bridge dependency diagnosis | Implemented / Verified | Bridge 0.6.11 in engine user site |
| MCP configuration diagnosis | Implemented / Verified | Codex config detected |
| Isolated Console instance | Implemented / Verified | PID 33204, PID 5500 |
| Bridge `/health` verification | Implemented / Verified | 2D and 3D, `runtime_mode=console` |
| PFC execution probe | Implemented / Verified | Bridge probe |
| Real `itasca-mcp` round trip | Implemented / Verified | `itasca_execute_code` for 2D and 3D |
| Four-layer READY gate | Implemented / Verified | instance verification records |
| Simultaneous multi-instance | Implemented / Verified | PR9-PR14 rectification: tasks 45ba2c and 6cc5e9; selective interrupt while 45ba2c kept running |
| Multiple MCP routing on one process | NOT_SUPPORTED | one Bridge URL per MCP process |
| Project/Case management | Implemented / Verified | project audit and case records |
| Unique Run IDs and input snapshots | Implemented / Verified | independent Run directories |
| Short `execute_code` task | Implemented / Verified | MCP PFC probes |
| Long `execute_task` + polling | Implemented / Verified | five completed tracked tasks |
| Status query and reconciliation | Implemented / Verified | completed and interrupted Runs |
| Task interrupt | Implemented / Verified | task `95769f` |
| Timeout without auto-resubmit | Implemented / Verified | `run_timeout_probe` entered `TIMEOUT_UNKNOWN` |
| Safe stop audit | Implemented / Verified | model saved; fallback termination disclosed |
| Cycle-stride capture | Implemented / Verified | 21-frame 2D/3D Runs |
| Mechanical-time interval capture | Implemented / Verified | 6-frame 3D Run |
| Fracture-event sampling | Implemented / NOT_VERIFIED | no new real fracture event |
| Ball position/radius | Implemented / Verified | 2D and 3D Runs |
| Ball velocity/spin | Implemented / Verified | 2D and 3D Runs |
| Wall vertices/platen data | Implemented / Verified | 2D and 3D Runs |
| Contact ID/endpoints/force | Implemented / Verified | 51 real 2D contact observations |
| Contact capture in 3D | Implemented / NOT_VERIFIED | 3D acceptance disabled contacts |
| Native Histories | Implemented / NOT_VERIFIED | no new non-empty History |
| Clump membership capture | NOT_IMPLEMENTED | future capture extension |
| Raw persistence and hashes | Implemented / Verified | all delivered Runs |
| Variable-length NPZ offsets | Implemented / Verified | contract tests and real packages |
| `metadata.json` and `manifest.json` | Implemented / Verified | all delivered Runs |
| `delivery_manifest.json` compatibility | Implemented / Verified | Visualization reads every tested package |
| Immutable package verification | Implemented / Verified | tamper test and real packages |
| Analysis Feedback schema | Implemented / Verified | feedback review |
| Feedback approval and new Run | Implemented / Verified | `run_pfc2d_002` |
| Visualization reads standardized package | Implemented / Verified | 2D and 3D pipelines |
| Feedback rerun delivered again | Implemented / Verified | `run_pfc2d_002_visualization` |
| Viewer/browser visual acceptance | NOT_VERIFIED | Visualization Skill responsibility |

## PR9-PR14 rectification

| Capability | Status | Evidence |
|---|---|---|
| Run submission through official MCP tools | Implemented / Verified | PFC2D task `2ef8c6`, PFC3D task `005566` |
| Headless Run path without Bridge HTTP client | Implemented / Verified | source-boundary test; local-only finalization |
| MCP task binding and nonce checks | Implemented / Verified | wrong-script and duplicate-task tests |
| READY nonce and current identity binding | Implemented / Verified | PID 29824/PFC2D, PID 30532/PFC3D, PID 32060/second PFC2D |
| Stale/cross-instance evidence rejection | Implemented / Verified | PFC2D-9002 evidence rejected for PFC3D-9001 |
| Run-to-Instance automatic resolution | Implemented / Verified | `run status/interrupt` without `--port` |
| Simultaneous multi-instance isolation | Implemented / Verified | tasks `45ba2c` and `6cc5e9` |
| Selective interrupt isolation | Implemented / Verified | `6cc5e9` interrupted while `45ba2c` remained running |
| Feedback retryable state machine | Implemented / Verified | failed and validated real feedback attempts |
| Contact feedback rerun | Implemented / Verified | source 0 contacts -> rerun 51 contacts |
| Collection plan allow-list | Implemented / Verified | explicit base-only plan and recommended contact plan |
| Registered event selection | Implemented / Unit Verified | fracture remains `NOT_VERIFIED` on a new real event |
| Missing source fail-closed | Implemented / Verified | test rejects missing declared file |
| Registry-integrated recovery | Implemented / Verified | interrupted PFC3D task, 370 frames / 37 blocks |
| Headless analysis boundary | Implemented / Verified | legacy metrics gated; new finalization emits none |
| Visualization Findings Producer | Implemented / Verified | real PFC2D and PFC3D producer outputs |
| Cross-Skill feedback closure | Implemented / Verified | headless ingest -> approval -> MCP rerun -> validated |
| Timeout evidence mapping without resubmission | Implemented / Unit Verified | real unresolved live timeout not reproduced |
| Native non-empty History | NOT_VERIFIED | current smoke Cases define no native History |
| Clump membership | NOT_IMPLEMENTED | intentionally excluded pending version API verification |
| Browser visual acceptance | NOT_VERIFIED | owns by Visualization acceptance workflow |

