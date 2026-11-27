# Versioning and release process

## Scheme

Use [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

- `MAJOR`: breaking change to Run / Dataset / Manifest / schema contracts.
- `MINOR`: backward-compatible capability addition.
- `PATCH`: bug fix or documentation-only correction with no contract change.

Tags are prefixed with `v`, for example `v1.0.0`. Pre-release tags use
`v1.0.0-rc.1` and must be marked as pre-release on GitHub.

## Current state

No tag has been published. The first proposed tag is `v1.0.0`, but it is
blocked; see `docs/RELEASE_NOTES_DRAFT.md`.

## Release checklist

1. Close all P0 rows in `docs/OPEN_SOURCE_READINESS.md` on `main`.
2. Run `python scripts/run_tests.py` and `python -m unittest discover -s tests`.
3. Record real PFC evidence separately when claiming `REAL_ENV_VERIFIED`.
4. Move `[Unreleased]` items in `CHANGELOG.md` into a version section with date.
5. Finalize `docs/RELEASE_NOTES_DRAFT.md` and rename it to the versioned file.
6. Create the tag from the verified commit.
7. Create a GitHub Release from the tag; attach the Skill package only if its
   contents were verified.

## Never

- Do not tag a commit that still has an open authorization bypass.
- Do not describe a design or protocol check as `REAL_ENV_VERIFIED`.
- Do not publish a Release whose notes claim capabilities that live only in an
  unmerged branch.
