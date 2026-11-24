# Mock example data

`Mock_Experiment` is intentionally small and artificial. It is labeled
`data_boundary: MOCK` and must never be reported as a real PFC experiment.

It demonstrates:

- a dynamic Ball ID set (`101`–`104`);
- one real-looking fracture event in the fixture;
- per-frame Wall vertices;
- support for the existing capture CSV layout.

Use `pfc-headless/run_standardization.py` to convert this capture into the
read-only `pfc.standardized-experiment` handoff. The fixture is not evidence of
a real PFC experiment.
