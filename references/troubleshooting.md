# Troubleshooting

| Symptom | Check | Action |
|---|---|---|
| No Console found | environment report | Set `PFC2D_CONSOLE`/`PFC3D_CONSOLE` or pass `--engine`; do not use GUI |
| Bridge dependency missing | environment report | Install `itasca-mcp-bridge` into the engine-visible Python user site |
| Port busy | instance health | Identify the owner; reuse only if process/workdir identity matches |
| `/health` works but tasks fail | task status | Treat as not ready; inspect Bridge and Console logs |
| MCP unavailable | MCP config/status | Start matching MCP process; do not infer routing across ports |
| Task times out | task history | Query upstream status; keep `TIMEOUT_UNKNOWN`, do not auto-resubmit |
| Contact rows empty | model contacts | Contact capture is enabled only when active contacts exist; model setup may need contact model/detection |
| PFC2D z appears everywhere | dimension metadata | It is numeric embedding for vector APIs, not physical 3D data |
| Stop remains alive | lifecycle audit | The command may have used verified fallback termination; inspect saved model and method |
| Package hash fails | manifest report | Treat as immutable-contract failure; regenerate a new package, never patch in place |

When sandboxing hides user site-packages, run environment checks in a normal,
unrestricted terminal before installing or changing dependencies.

