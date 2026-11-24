# Skill Installation Audit

Date: 2026-11-16

## Installed locations

- `C:\Users\L\.codex\skills\pfc-headless`
- `C:\Users\L\.codex\skills\pfc-scientific-visualization`

## Headless

- Repository: `D:\Python\itasca-mcp\PFC Visualization Skill\pfc-headless`
- Source/install core SHA-256 comparison: 61 files checked, 0 missing,
  0 changed.
- Installed connection type: physical directory, not a symlink.
- Installed tests: 44 PASS, 0 FAIL.
- Skill Creator validation: PASS.

## Visualization

- Repository:
  `D:\Python\itasca-mcp\PFC Visualization Skill\pfc-scientific-visualization`
- A clean installation was performed because the previous installed directory
  retained obsolete files from the former responsibility boundary.
- Previous installation backup:
  `C:\Users\L\.codex\skills\pfc-scientific-visualization.backup-20261116-pr9-pr14`
- Source/install core SHA-256 comparison: 64 files checked, 0 missing,
  0 changed.
- Installed connection type: physical directory, not a symlink.
- Installed tests: 66 PASS, 0 FAIL.
- Skill Creator validation: PASS.

## Runtime cleanup

After acceptance:

- no `pfc2d9_console.exe` process remained;
- no `pfc3d9_console.exe` process remained;
- no listener remained on ports 9001 or 9002.

The two PFC stops saved models and used the disclosed verified-PID fallback after
`program stop`; native graceful exit is not claimed.
