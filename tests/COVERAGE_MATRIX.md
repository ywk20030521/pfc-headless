# Test Coverage Matrix

Current automated suite: **34 PASS, 0 FAIL** on 2026-11-16.

| Area | Test module | Result |
|---|---|---|
| Project/Case/Instance/Run/Feedback schemas | `test_headless_contracts.py` | PASS |
| Project creation and state persistence | `test_project_simulation_contract.py` | PASS |
| Unique Run and input snapshots | `test_project_simulation_contract.py` | PASS |
| Parameter substitution | `test_project_simulation_contract.py` | PASS |
| Metadata/manifest/downstream contract | `test_data_package_contract.py` | PASS |
| Tamper detection | `test_data_package_contract.py` | PASS |
| Feedback ingest/approve/new Run | `test_feedback_manager.py` | PASS |
| Dynamic Console filename by content | `test_environment_and_collector.py` | PASS |
| Collector field declarations | `test_environment_and_collector.py` | PASS |
| GUI rejection | `test_console_runtime_contract.py` | PASS |
| Loopback-only Bridge client | `test_console_runtime_contract.py` | PASS |
| Capture block recovery | `test_capture_store.py` | PASS |
| Corrupt-tail rejection | `test_capture_store.py` | PASS |
| Dynamic Ball add/remove | `test_standardization_dynamic.py` | PASS |
| Variable-length NPZ delivery | `test_standardization_dynamic.py` | PASS |
| Immutable output/overwrite guards | `test_standardization_dynamic.py` | PASS |
| Channel source and offset invariants | `test_schema_integrity.py` | PASS |
| Console/capture ownership boundary | `test_capture_boundary.py` | PASS |

Real acceptance is separate from this automated suite. See
`../reports/VALIDATION_REPORT.md` and
`../acceptance/e2e_20261116/README.md`.

