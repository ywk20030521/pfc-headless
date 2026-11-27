# PR — 执行授权闸门（Formal Run Authorization Gate）

**分支：** `fix/execution-authorization-gate`
**目标仓库：** `ywk20030521/pfc-headless`
**日期：** 2026-11-27
**状态：** 可合并（单元测试 71/71 通过；真实 PFC 执行未验证）

---

## 1. 变更动机

`PFC_INTERACTION_FAILURE_DIAGNOSIS_2026-11-27` 确认存在一条可绕过用户确认的旁路：
`headless.py run prepare → itasca_execute_task` 不检查 `pfc-interaction` 的决策或授权记录。
协议层的“有授权网关”不等于所有执行都经过该网关。本 PR 把授权校验下沉到**不可绕过的执行边界**。

## 2. 目标 / 非目标

**目标**

- 正式 Run 必须绑定用户已批准的授权元数据（授权 ID、研究任务、决策、模型/参数/矩阵版本）。
- 授权元数据写入不可变 Run 记录（`run.json`），并在提交前二次校验。
- 仅允许显式 `--pilot --pilot-reason` 作为技术试跑，结果标记为 `UNACCEPTED_TECHNICAL_PILOT`。
- 历史/无授权 Run 在提交边界被拒绝，不自动补授权、不静默推断成功。

**非目标**

- 不实现用户交互、卡片或决策生成（属 `pfc-interaction`）。
- 不调用 `itasca-mcp` / Bridge / PFC Console，也不改真实执行逻辑。
- 不改变 Run 数据采集与标准化 Schema。
- 不在本 PR 宣称真实 PFC 端到端验证。

## 3. 文件变更

| 文件 | 变更 |
|---|---|
| `scripts/pfc_headless/authorization.py` | 新增：`RunAuthorization`、`resolve_authorization()`、`gate_run_record()`；正式/Pilot 状态常量与字段级校验 |
| `scripts/headless.py` | `run start` / `run prepare` 增加授权参数；`run prepare` 写入授权块；提交前调用闸门 |
| `scripts/pfc_headless/project.py` | `new_run(..., authorization=...)` 持久化并校验授权块 |
| `scripts/pfc_headless/simulation.py` | `prepare_project_case()` 透传授权；`execute_planned_run()` 提交前二次校验 |
| `schema/run.schema.json` | Run 记录新增 `authorization` 对象字段 |
| `tests/test_run_authorization_gate.py` | 新增 8 条闸门回归测试（正式授权、缺字段、Pilot、CLI、历史 Run、篡改记录） |
| `README.md` / `SKILL.md` | 更新用法与边界；正式 Run 与 Pilot 的区分 |
| `benchmarks/benchmark_authorization_gate.py` | 新增可复现性能基准脚本 |
| `benchmarks/results.json` / `benchmarks/PERFORMANCE_REPORT.md` | 新增基准原始数据与分析报告 |
| `docs/PR_EXECUTION_AUTHORIZATION_GATE.md` | 本文档 |

## 4. 行为变更（破坏性说明）

- **破坏性**：`run prepare` / `run start` 缺少完整正式授权参数时直接失败，错误信息包含缺失字段名。
- **破坏性**：`run execute` 对历史 Run 或无 `authorization` 块的 Run 拒绝提交，错误码语义为“未授权正式 Run”。
- **兼容出口**：显式 `--pilot --pilot-reason "..."` 可创建技术试跑；不得与 `--authorization-id` 混用，且不得作为正式科研交付。
- **字段忽略**：持久化记录回读时 `status` 由代码派生，不接受外部传入的 `status`，避免伪造授权。

## 5. 验证结果

### 5.1 单元测试

```
python -m unittest discover -s tests -v
Ran 71 tests in 11.108s
OK
```

其中 `test_run_authorization_gate.py` 8/8 通过，覆盖：

1. 无授权正式 Run 被拒；
2. 六个绑定字段逐个缺失均被拒；
3. Pilot 必须给出理由且不能携带授权 ID；
4. 正式授权与模型/参数/矩阵版本绑定；
5. CLI `run prepare` 无授权失败；
6. 历史无授权 Run 在提交边界被拒；
7. 正式授权与 Pilot Run 均能通过落盘与复核；
8. 被篡改/不完整的授权记录被拒。

### 5.2 性能检测

```
python benchmarks/benchmark_authorization_gate.py --rounds 5
```

- 纯闸门路径：授权解析均值 **0.0052 ms**（P95 0.0082 ms）；Run 记录复核均值 **0.0007 ms**（P95 0.0011 ms）。
- 落盘路径：Run 准备 + 授权复核均值 **48.96 ms**（P95 55.13 ms）。
- CLI 无授权拒绝：均值 **160.93 ms**（P95 176.78 ms），开销来自参数解析与模块初始化。
- 稳定性：7 个场景 **0 次非预期异常、输出全部确定、无单调内存增长**。
- 详情与改进建议见 `benchmarks/PERFORMANCE_REPORT.md`。

### 5.3 未验证项

- 未连接真实 `itasca-mcp` / Bridge / PFC Console；本 PR 状态为 `TESTED`，**不是** `REAL_ENV_VERIFIED`。
- 未验证真实 PFC Run 的端到端授权链（需与 `pfc-interaction` 授权字段联调）。
- 未覆盖并发写入和多进程场景。

## 6. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 既有脚本未传授权导致工作流中断 | 错误信息指出缺失字段；技术试跑可用显式 `--pilot` |
| Pilot 被误用为正式实验 | 状态 `UNACCEPTED_TECHNICAL_PILOT` 写入不可变记录；下游应按状态拒绝 |
| 历史 Run 无法补授权 | 设计上不允许回填；需经 Interaction 重新走用户确认并创建新 Run |
| 本地文件存储无并发锁 | 已在性能报告列为 P1 改进项，本 PR 不扩大范围 |

**回滚**：回退本分支提交即可恢复旧行为；回退后授权旁路重新出现，因此不建议在真实科研环境长期回滚。

## 7. 合并检查清单

- [x] 变更有明确问题来源与边界说明
- [x] 文档（README / SKILL / schema）同步更新
- [x] 全套单元测试通过（71/71）
- [x] 关键场景性能与稳定性已记录
- [x] 破坏性行为与 Pilot 出口明确标注
- [x] 真实环境未验证如实标注
- [x] 与 `pfc-interaction` 运行时闸门 PR 的接口字段一致
