# Contributing to PFC Headless

Thanks for contributing. This repository is the execution and data-production
layer of the PFC Scientific Research Agent. Please keep changes inside that
boundary.

## Scope boundary

This Skill owns:

- PFC2D/PFC3D Console discovery and verified execution requests;
- Project / Case / Run lifecycle, failure and recovery context;
- script-embedded capture, immutable RAW data, STANDARDIZED delivery and manifests;
- mechanical data-quality checks and downstream delivery.

This Skill does **not** own user discussion or authorization (Interaction),
derived quantities, statistics, charts or Viewer rendering (Visualization), or
scientific validation, Evidence and Finding (Research Evidence Skill). Do not
add those capabilities here.

## Before you start

- Python 3.10+ (the codebase uses `str | Path` style annotations).
- No PFC license is required for unit tests. Real PFC acceptance is a separate,
  explicitly labelled activity.
- Read [SKILL.md](SKILL.md), [README.md](README.md),
  [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md) and
  [docs/OPEN_SOURCE_READINESS.md](docs/OPEN_SOURCE_READINESS.md) first.

## Development and tests

```powershell
python scripts/run_tests.py
python -m unittest discover -s tests
```

When changing schemas or manifests, run the contract tests and update
`schema/` plus `reports/` together. Never "fix" a failing contract test by
weakening validation.

## Scientific integrity rules

1. Use the capability vocabulary exactly: `IMPLEMENTED`, `TESTED`,
   `REAL_ENV_VERIFIED`, `NOT_VERIFIED`, `NOT_IMPLEMENTED`, `DEPRECATED`.
   `TESTED` is never `REAL_ENV_VERIFIED`.
2. `NOT_RUN`, `UNKNOWN`, `WARNING` and `NOT_APPLICABLE` must not be promoted to
   `PASS`. A Run that merely completed is not scientific validation.
3. RAW data is immutable. Corrections create a new STANDARDIZED or DERIVED
   object, never an overwrite.
4. Run status, data-integrity status and scientific validity are three
   different states. Do not collapse them into one boolean.
5. Real PFC evidence requires a real `tool_task_id` and a traceable record;
   simulated data must be labelled as such.

## Pull requests

- Fork and open a PR against `main`; use a short branch name such as
  `fix/...`, `docs/...` or `feat/...`.
- Fill in `.github/PULL_REQUEST_TEMPLATE.md` completely.
- Add or update tests for behavioral changes, and update documentation in the
  same PR.
- Add an entry to `CHANGELOG.md` under `[Unreleased]`.
- Describe the verification command and its result; list any real-environment
  verification separately.
- Keep commits focused. Do not mix security/gate changes with documentation
  cleanup in one PR.

## Issues

Use the bug report or feature request templates. Include the exact command,
Python version, PFC/bridge version when relevant, and the observable evidence.
Do not attach proprietary model files.

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Do not open a public issue for an exploitable defect.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
