# Security Policy

## Supported versions

| Version | Status |
|---|---|
| `main` | Development baseline; security fixes are applied here first. |
| Published tags | Receive fixes only when a maintenance release is cut. |

This repository has no published tag yet. See
[docs/RELEASE_NOTES_DRAFT.md](docs/RELEASE_NOTES_DRAFT.md) for the proposed
first tag and its release blockers.

## Reporting a vulnerability

Please **do not** open a public issue for an exploitable defect. Use GitHub's
private vulnerability reporting for this repository (`Security` →
`Report a vulnerability`), or contact the maintainers privately through the
account listed in the repository profile.

Include:

- affected version or commit;
- reproduction steps and the smallest non-proprietary model/config;
- impact (for example: an unauthorized Run reaching `itasca_execute_task`);
- whether a public disclosure already occurred.

You should receive an acknowledgement within a few working days. We will
coordinate disclosure and credit once a fix is available.

## Security-relevant boundaries

The following are treated as security boundaries, not optional checks:

- a formal Run must carry a bound user authorization and be re-checked before
  submission;
- `--pilot` must be explicit and marked `UNACCEPTED_TECHNICAL_PILOT`;
- historical or tampered Run records must be rejected, never silently repaired;
- unknown status must remain `UNKNOWN` / `RECOVERY_REQUIRED`.
