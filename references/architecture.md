# Headless Architecture

The Headless Skill is the management layer between an agent-facing request and
the scientific consumer. It does not replace the ITASCA MCP server or its
in-process HTTP bridge.

## Eight modules

| Module | Responsibility | Owns |
|---|---|---|
| Environment Manager | Discover and validate PFC2D/PFC3D Console builds and dependencies | environment reports |
| Engine Manager | Start, identify, reuse and stop isolated Console instances | instance state and process audit |
| Connection Manager | Verify process identity, `/health`, and PFC execution | readiness evidence |
| Project Manager | Manage Project, Case, parameters and source snapshots | `project.json`, `cases/` |
| Simulation Manager | Submit, monitor, interrupt and recover Runs | `runs/`, MCP task mapping |
| Data Collector | Embed capture callbacks into prepared PFC Cases | immutable `raw/` capture |
| Data Manager | Validate, standardize, hash and index Run outputs | `deliveries/`, manifests |
| Feedback Manager | Validate downstream findings and propose a new Run | `analysis/feedback/` |

## Dependency boundary

```text
Agent Host
  |-- pfc-headless: Project / Case / Run / Instance / Data / Feedback state
  `-- itasca-mcp
        `-- itasca-mcp-bridge
              `-- PFC2D/PFC3D Console process

Headless emits MCP operation requests and records Agent-supplied evidence. It
does not implement another MCP client, task queue, Bridge execution client or
engine runtime.
```

## Entity relationships

```text
Project 1--N Case
Project 1--N Engine Instance
Case    1--N Run
Run     N--1 Engine Instance (nullable)
Run     1--1 Data Package
Run     1--N Analysis Feedback
Feedback 1--0..1 Proposed Run
```

## Ownership

| Data | Owner | Mutation policy |
|---|---|---|
| `runs/<run>/input/` | Project/Simulation Manager | immutable after submission |
| `runs/<run>/data/raw/` | Data Collector | append only during execution; immutable after finalization |
| `runs/<run>/metadata/` | Headless | append/update with audit history |
| `deliveries/<run>/` | Data Manager | immutable after publication |
| `analysis/` | Visualization | Headless reads feedback only |

No Headless operation writes Three.js, ECharts, chart or publication artifacts.

## Console-only rule

Only validated PFC Console executables are accepted. A filename containing
`console` is insufficient by itself: discovery also checks product markers in
the executable and runtime identity after launch. GUI executables are excluded.

## Version negotiation

- JSON contracts use `schema_version: "1.0.0"`.
- The scientific data interface is `pfc.standardized-experiment@1.0.0`.
- Engine discovery records the inferred install version but treats executable
  identity and runtime probe output as the authoritative capability evidence.
- Unknown Bridge fields are preserved. Unknown required capabilities stop the
  operation with an actionable error instead of being guessed.

