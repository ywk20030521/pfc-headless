# Release Notes — DRAFT (not published)

**Repository:** `ywk20030521/pfc-headless`
**Proposed tag:** `v1.0.0` — **NOT CREATED**
**Status:** `DRAFT / BLOCKED`
**Date:** 2026-11-27

## 1. Status

This file is a release-note draft for the first public tag. No Git tag and no
GitHub Release have been created. Do not cite this document as a published
release.

## 2. Release blockers

| Blocker | Evidence | Required action |
|---|---|---|
| Execution authorization gate is not merged into `main` | PR `fix/execution-authorization-gate` (#1), currently open | Merge and verify no authorization bypass remains |
| Installed Skill directories do not yet contain the gate | Remediation report REM-001 §2 R01 | Synchronize installation packages after merge |
| Dataset layer canonical vocabulary and stable feedback IDs are in separate worktrees | REM-001 R06/R07 | Merge the corresponding remediation changes and run contract tests |
| Cross-Skill invocation envelope (`request_id` / `idempotency_key`) is not defined | REM-001 R11 | Agree schema with Interaction and Visualization before tagging a breaking contract |

## 3. Capabilities included in the proposed tag (current `main`)

- Verified PFC2D/PFC3D Console discovery and isolated instance handling.
- MCP-only Run orchestration: prepare / submit / attach / status / interrupt.
- Project, Case and unique Run management with immutable records and hashes.
- Script-embedded capture, STANDARDIZED delivery and downstream contract
  compatibility with `pfc-scientific-visualization`.
- Mechanical data-quality checks, manifests and failure/recovery context.

## 4. Compatibility

Compatibility claims must come from the recorded acceptance reports rather
than from this draft. See `reports/CAPABILITY_MATRIX.md`,
`CONSOLE_ACCEPTANCE.md` and `DATA_INTEGRITY_REPORT.md` for exact versions and
verification state. Do not restate a historical `REAL_ENV_VERIFIED` result as
a verification of this draft tag.

## 5. Verification to repeat before publishing

```powershell
python scripts/run_tests.py
python -m unittest discover -s tests
```

Then record: unit/contract result, real PFC evidence (with `tool_task_id` when
applicable), and the exact commit being tagged.

## 6. Known limitations at draft time

- No formal tag or Release exists yet.
- Authorization gate, canonical layer vocabulary and stable feedback IDs are
  pending merge.
- Legacy `frame_metrics` outputs are technical artifacts only; they must not
  be used as scientific conclusions.
- Scientific validation, Evidence and Finding belong to the Research Evidence
  Skill and are explicitly out of scope.
