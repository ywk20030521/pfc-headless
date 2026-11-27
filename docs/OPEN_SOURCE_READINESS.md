# Open-source readiness and three-Skill standards alignment

**Repository:** `ywk20030521/pfc-headless`
**Date:** 2026-11-27
**Standard sources:** PFC-SRA-ARCH-001 / ARCH-002 / REM-001, plus the
corresponding item in the overall three-step plan.
**Status key:** `PASS` = present on `main`; `ADDED IN THIS PR`; `GAP` = still
missing; `PARTIAL` = present but incomplete.

## 1. GitHub repository configuration

| # | Requirement | Standard source | Current compliance | Gap / action | Priority |
|---|---|---|---|---|---|
| 1 | MIT LICENSE | GitHub OSS baseline | `PASS` — MIT, 2026 | None | — |
| 2 | README with scope and non-goals | ARCH-002 §1.2 | `PASS` | Add contributing/CoC/release links | P2 |
| 3 | CONTRIBUTING guide | GitHub OSS baseline | `ADDED IN THIS PR` | Include scientific-integrity rules | — |
| 4 | Code of Conduct | GitHub OSS baseline | `ADDED IN THIS PR` | None | — |
| 5 | Security policy | GitHub OSS baseline | `ADDED IN THIS PR` | None | — |
| 6 | Issue templates (bug / feature / config) | GitHub OSS baseline | `ADDED IN THIS PR` | None | — |
| 7 | Pull-request template | GitHub OSS baseline | `ADDED IN THIS PR` | None | — |
| 8 | Changelog | GitHub OSS baseline | `ADDED IN THIS PR` | Keep updated each PR | P1 |
| 9 | Release-note config + draft | GitHub OSS baseline | `ADDED IN THIS PR` | Must not be published while blocked | P0 |
| 10 | Version tag + public Release | GitHub OSS baseline | `GAP` — no tags or Releases | Propose `v1.0.0` after blockers clear; no tag created in this PR | P0 |
| 11 | Versioning policy | Keep a Changelog / SemVer | `ADDED IN THIS PR` (in CHANGELOG) | None | — |

## 2. Three-Skill standard alignment

| Standard item | Requirement | Current compliance | Gap / action | Priority |
|---|---|---|---|---|
| ARCH-002 §3 rule 5 — execution gate | Formal Run carries bound authorization; no authorization means explicit `--pilot` | `GAP` on `main`; implemented in open PR #1 | Merge PR #1, re-run 71+ tests, synchronize installed Skill | **P0** |
| ARCH-002 §3 rule 6 — state honesty | Run status, data integrity and scientific validity separated | `PARTIAL` — reports distinguish them; code remediation not on `main` | Merge REM-001 R03/R04 changes adding `data_integrity_status` / `scientific_validity` | P0 |
| ARCH-002 §3 rule 9 — idempotency | `request_id` + `idempotency_key` on every cross-Skill call | `GAP` — no shared envelope | Define `pfc.skill-invocation@1.0.0` (REM-001 R11) | P1 |
| ARCH-002 §5.3 — canonical layers | `RAW / STANDARDIZED / DERIVED` with migration mapping | `PARTIAL` — `layer_contract.py` in remediation worktree, not `main` | Merge REM-001 R06; enforce canonical writes after RE contract freeze | P0 |
| ARCH-002 §5.3 — stable IDs | Feedback IDs must be stable and unique | `PARTIAL` — UUID fix in remediation worktree, not `main` | Merge REM-001 R07; add idempotency key at envelope layer | P1 |
| ARCH-002 §2.1 — object ownership | Execution owns Run / RAW / STANDARDIZED | `PASS` | Do not add Analysis or Finding objects here | — |
| ARCH-002 §3 rule 12 — capability status vocabulary | Every capability labelled with one of six states | `PARTIAL` — `CAPABILITY_MATRIX.md` uses prose levels | Normalize to the six exact tokens in docs and reports | P1 |
| REM-001 R03/R04 — scientific adjudication leakage | `finalize_run` must not decide scientific validity | `GAP` on `main`; fixed in gate worktree | Merge and verify boundary markers | **P0** |
| REM-001 R06 — dataset layer vocabulary | Canonical layer contract in Headless and Viz | `GAP` on `main` | Ship in the same release window as Viz | **P0** |
| REM-001 R07 — feedback ID | UUID-based ID | `GAP` on `main` | Merge with R06 | P1 |
| Overall plan §8 / RE §11 — no fake PASS | `NOT_RUN / UNKNOWN / WARNING` not promoted to `PASS` | `PARTIAL` — contract layer enforces; execution docs need explicit statement | Add explicit rule to `SKILL.md` and review checklist | P0 |

## 3. Release decision

**Do not tag or publish a Release from `main` yet.** Tag `v1.0.0` only after
P0 rows are closed on `main` and the installation package is synchronized.
This PR adds repository configuration only; it does not change runtime code.

## 4. Verification of this PR

```text
python scripts/run_tests.py          # Ran 63 tests ... OK
python -m unittest discover -s tests # Ran 63 tests ... OK
```

No runtime module, schema or test was modified. The authorization-gate PR (#1)
remains separate and unmerged.
