## Summary

<!-- What changes and why? Link the issue if there is one. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] New capability inside this Skill's boundary
- [ ] Contract / schema change (additive)
- [ ] Contract / schema change (breaking — requires explicit review)
- [ ] Documentation / repository configuration
- [ ] Test-only change

## Verification

Commands run and results:

```text
python scripts/run_tests.py
# ...
```

- [ ] Unit / contract tests pass
- [ ] Real PFC / bridge evidence attached **if** claiming `REAL_ENV_VERIFIED`
- [ ] Simulated data is labelled as such
- [ ] No `NOT_RUN` / `UNKNOWN` / `WARNING` was promoted to `PASS`

## Responsibility and data contract

- [ ] Change stays within Execution / Data Pipeline boundary
- [ ] No user discussion, chart rendering or scientific validation added here
- [ ] RAW data remains immutable; corrections create new objects
- [ ] Schema/manifest changes are reflected in `schema/` and docs
- [ ] Status vocabulary follows `CONTRIBUTING.md`

## Documentation

- [ ] README / SKILL.md updated if behavior changed
- [ ] `CHANGELOG.md` entry added under `[Unreleased]`
- [ ] Acceptance or capability report updated when evidence changes
- [ ] Known limitations stated honestly

## Reviewer notes

<!-- Any risk, rollback plan, or follow-up PR that must be tracked. -->
