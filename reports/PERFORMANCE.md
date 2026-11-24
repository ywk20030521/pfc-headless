# Performance and applicability (2026-11-24)

This report records the measured performance of the offline standardization
cleaning module after the PR-1..PR-4 upgrade, and its applicability to real PFC
experiments. All numbers are measured, not estimated.

## 1. Cleaning performance: end-to-end A/B

Environment: Python 3.13, NumPy 2.5.5, `tracemalloc` peak Python allocation.
Baseline = exact `git HEAD` code before the upgrade, restored via `git archive`.

Synthetic run: 200 frames x 1000 balls = 200,000 ball rows, no contacts.

| Variant | Wall time | Peak Python memory | vs baseline |
|---|---|---|---|
| baseline (HEAD) | 15.16 s | 283.1 MB | 1.00x / 1.00x |
| PR-1 default (preallocation) | 15.87 s | 283.1 MB | 0.95x / 1.00x |
| PR-1 `--fast-reader` | 15.41 s | 163.3 MB | 0.98x / 1.73x |
| PR-2 `--columnar` | 9.90 s | 29.4 MB | 1.53x / 9.6x |

The columnar path reads ball CSV directly into preallocated ndarray columns and
skips the `ball_frames` dict-of-dicts intermediate, which was the true memory
bottleneck. `--auto` selects it automatically; the decision and the estimated
scale are written into `conversion_report.json`.

The earlier micro-benchmark suggested 4.6x; the honest end-to-end figure for the
full conversion pipeline is 1.73x for `--fast-reader` and 9.6x for `--columnar`.

## 2. Output equivalence

- Four acceptance runs (PFC2D, PFC3D, contact, time-sampling) x four modes
  (default / fast / columnar / auto): every NPZ channel matched the pre-change
  golden byte-for-byte (`np.array_equal(..., equal_nan=True)`).
- Synthetic 200k-row run: 28/28 channels identical across all variants.
- Full test suite: 63 tests OK.
- `data verify`: PASS on every upgraded delivery.

## 3. Real-experiment validation (user workspace)

Workspace contains 12 PFC project directories, 47 raw runs with
`data/raw/ball_frames.csv`, and 35 shipped deliveries (3D + 2D).

- All 35 shipped deliveries pass `verify_delivery`.
- All 47 raw runs were re-converted with `--auto`: 39 succeeded, 8 were rejected.
  All 8 rejected runs have **no shipped delivery** (failed, incomplete, or
  superseded attempts such as `_r1` before `_r2`), so rejection is the correct
  data-integrity behaviour, not a regression.
- Five representative real experiments re-converted in `--auto` mode matched
  their shipped deliveries channel-for-channel:
  - `run_case14_realistic_ratio_break_r1` (3D, 599,830 ball rows, 1,211,213
    contact rows): 40/40 identical
  - `run_case16_granite_like_confined_ucs_r1`: 29/29
  - `run_case13_blueplate_break_bonded_r2`: 40/40
  - `run_case10_inclusions_matrix` (2D): 32/32
  - `run_case08_cantilever_beam_r2` (2D): 20/20

### Bug fixed during validation

Real experiments contain contact rows whose endpoint is a Wall/Facet, written
as `-1` by the capture engine. Legacy NumPy silently wrapped `-1` into the
uint64 sentinel `18446744073709551615`; NumPy 2.x raises `OverflowError`
instead, making case14 (15,788 such rows) impossible to re-convert. The
converter now maps `-1` to the same uint64 sentinel explicitly, preserving the
exact bytes of existing deliveries while remaining valid under NumPy 2.x.

## 4. Module maturity

| Module | Score | Evidence |
|---|---|---|
| Environment discovery | 9/10 | Console content fingerprint, 2D/3D check |
| Engine lifecycle | 9/10 | Registered PID/cmdline, safe stop, real PFC |
| Connection verification | 10/10 | Four evidence layers + instance nonce |
| Project management | 9/10 | Unique Case/Run IDs, atomic JSON, 9 test files |
| Simulation management | 9/10 | Watchdog, TIMEOUT_UNKNOWN, no auto-resubmit |
| Data collection | 8/10 | Embedded FISH capture, float32 blocks + CRC/SHA; CSV spool is the remaining text bottleneck |
| Data management | 9/10 | This upgrade: 9.6x memory, sentinel fix, auto dispatch |
| Feedback management | 9/10 | APPROVED→PROPOSED→RUNNING→VALIDATED state machine |

## 5. Applicability

Fully applicable to Itasca PFC 2D/3D Console experiments on Windows with a
licensed PFC 9.x: triaxial/compression, fragmentation, wave propagation,
repose, hopper discharge, fault slip, cantilever, footing, inclusions, etc.
All 12 user project directories and 47 raw runs fall in this scope.

Not applicable, by design, to other DEM/FEM/CFD codes, non-Windows platforms,
unlicensed PFC, or clump models (clump support is explicitly deferred until a
target-version API and real model are verified).

Overall: a deep, narrow, research-grade data production layer for PFC, not a
general-purpose simulation frontend. After the upgrade its cleaning throughput
is no longer the limiting factor for 10k-50k particle experiments.
