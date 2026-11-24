# PFC Headless PR9-PR14 定向整改任务书

日期：2026-11-16  
适用对象：执行整改的代码 Agent  
当前基线：PR1-PR8 已实现，并通过既有单元测试和真实 PFC2D/PFC3D 验收  
当前结论：功能可用，严格架构验收未通过

## 0. 执行总则

本任务书是定向整改，不是二次架构重写。执行 Agent 必须：

1. 保留 PR1-PR8 中已经通过真实 PFC 验证的功能、数据和验收资产。
2. 先阅读现有源码、测试、Schema 和实际调用链，再作最小必要修改。
3. 不删除历史 Run、原始数据、模型、日志和既有验收报告。
4. 不把“34 项测试通过”当作冻结架构验收通过。
5. 不把历史真实 PFC 报告当成本次修改后的重新验收。
6. 每个 PR 独立实现、独立测试、独立更新执行报告。
7. 未实际执行的真实 PFC、多实例或跨 Skill 测试必须标为 `NOT_VERIFIED`。
8. Console-only、Run 不可覆盖、超时不自动重提、原始数据不可修改等规则继续有效。

整改主线：

```text
Agent Host
  |-- pfc-headless：Project / Case / Run / Instance / Data / Feedback 管理
  `-- itasca-mcp
        `-- itasca-mcp-bridge
              `-- PFC Console
```

Headless 负责准备执行请求、登记 MCP 结果、校验证据和整理数据；不得在执行路径中
重新承担 MCP 工具调用或通用 Bridge HTTP 客户端职责。

## 1. 已冻结且必须保留的能力

- PFC2D/PFC3D Console 内容识别和 GUI 拒绝。
- 独立实例工作目录、PID/可执行文件/命令行身份检查。
- Project、Case、Run Registry，唯一 Run ID 和不可覆盖输入快照。
- 脚本嵌入式 Cycle、time 和已注册事件采集。
- Ball、Wall、contact 的已有真实采集能力。
- 原始数据、标准数据和下游分析产物的目录隔离。
- 标准包 Schema、Manifest、哈希、偏移和篡改拒绝。
- 超时进入 `TIMEOUT_UNKNOWN` 且不自动重提。
- 中断后保留本地状态，等待 MCP 终态确认。

下列内容不在本任务中擅自扩展：

- 不为 Clump membership 虚构一个跨版本“通用 API”。
- 不承诺任意用户自定义事件触发；只支持经过验证的事件注册表。
- 不在 Headless 内实现科学分析或代替 Visualization 生成 Findings。

## 2. 统一执行契约

PR9 完成后，Run 的正式执行流程必须是：

1. `pfc-headless run prepare` 创建 Run、输入快照和嵌入采集脚本，返回：
   - 绝对 `entry_script`；
   - 唯一 `execution_nonce`；
   - 描述文本；
   - `instance_id` 和实例身份摘要；
   - 建议的 MCP 工具名和参数。
2. Agent Host 调用 `itasca_execute_task`。
3. Agent 保存工具返回和请求参数，调用 `pfc-headless run attach-task`。
4. Headless 校验 Run、Instance、任务描述、入口脚本和 nonce 后登记 `task_id`。
5. Agent 调用 `itasca_check_task_status`。
6. Agent 调用 `pfc-headless run record-status` 登记状态和结果证据。
7. 任务完成后调用 `pfc-headless run finalize`，执行数据完整性检查和标准化。
8. 中断由 Agent 调用 `itasca_interrupt_task`，随后用
   `pfc-headless run record-interrupt` 和 `run record-status` 记录结果。

Headless 可以输出“应调用的 MCP 操作描述”，但不能自行执行该 MCP 工具。
如果旧 CLI 仍然存在，只能作为兼容入口返回明确迁移错误，不能继续直接提交任务。

## 3. PR9：MCP 唯一执行接口适配

### 目标

从 Run 提交、轮询和中断路径中移除 Bridge HTTP 执行客户端，使 Headless 成为
执行准备和证据管理组件。

### 必读文件

- `scripts/pfc_headless/simulation.py`
- `scripts/run_case.py`
- `scripts/console_runtime.py`
- `scripts/headless.py`
- `schema/run.schema.json`
- `tests/test_project_simulation_contract.py`
- `references/task-management.md`
- `references/architecture.md`

### 实施要求

1. 将 `run_case.py` 中“执行”和“完成后的验证/标准化”拆开：
   - 保留准备嵌入脚本、验证原始数据和标准化的纯本地能力；
   - 删除 Run 路径对 `submit_task`、`wait_task`、`check_task`、
     `interrupt_task` 的依赖；
   - `simulation.py` 不再从执行路径调用 `BridgeClient`。
2. 新增正式 CLI：

```text
run prepare
run attach-task
run status
run record-status
run interrupt
run record-interrupt
run finalize
```

3. 明确区分 CLI 的“操作请求”和“结果登记”：
   - `run status` 只解析目标 Run/Instance 并输出应执行的 MCP 查询描述；
   - `run interrupt` 只生成中断请求意图并输出 MCP 操作描述；
   - `run record-status` 和 `run record-interrupt` 接收 Agent 保存的 MCP 证据。
4. `run attach-task` 至少校验：
   - Run 状态为 `PREPARED`；
   - `entry_script` 位于该 Run 自己的输入目录；
   - task 描述包含该 Run 的 `run_id` 和 `execution_nonce`；
   - 当前 Instance 身份仍与登记时一致；
   - `task_id` 未被其他 Run 占用。
5. MCP 证据文件至少包含：
   - 工具名；
   - 请求参数；
   - 原始响应；
   - 响应哈希；
   - `observed_utc`；
   - `mcp_connection_id`；
   - `instance_id`；
   - `run_id`；
   - `task_id`；
   - 当前进程身份摘要。
6. `run finalize` 只根据已登记的终态和 `completed` 证据执行原始数据验证、
   Manifest 生成和标准包发布。
7. 超时、未知终态和中断不得因 Agent 重放证据而触发脚本重提。

### 测试

- 单元测试证明 Run 路径不会发生 HTTP 请求。
- 旧 `run start/execute` 路径不再直接提交任务，并返回迁移提示。
- 错误 task ID、错误 Run nonce、错误入口脚本均被拒绝。
- 同一 task ID 不能绑定到两个 Run。
- `completed` 之外的状态不能触发标准包发布。
- `TIMEOUT_UNKNOWN` 不产生自动重提。

### 验收

- 新执行路径中不存在 Headless 发起的 Run 提交、状态查询或中断 HTTP 请求。
- Agent Host 通过官方 MCP 工具完成一次真实 PFC 任务提交、查询和完成登记。
- 原有嵌入采集和标准化功能保持工作。

## 4. PR10：READY 证据与实例身份绑定

### 目标

保证 READY 只证明“当前这个 Console 实例”可用，不能复用历史、过期或
其他实例的 MCP 成功证据。

### 必读文件

- `scripts/pfc_headless/connection.py`
- `scripts/pfc_headless/instance.py`
- `scripts/console_runtime.py`
- `schema/instance.schema.json`
- `tests/test_console_runtime_contract.py`
- `references/engine-lifecycle.md`

### 实施要求

1. 为 Instance 增加稳定身份字段：
   - `identity_fingerprint`：PID、可执行文件、命令行、端口和维度的摘要；
   - `mcp_connection_id`；
   - `readiness_nonce`；
   - `mcp_verified_utc`；
   - `mcp_evidence_expires_utc`；
   - `evidence_status`。
2. 启动或重新验证实例时生成一次性 `readiness_nonce`，写入隔离实例工作目录。
3. MCP 探测证据必须回显该 nonce，并包含当前 PID、可执行文件、维度、
   版本、Bridge URL、MCP connection ID 和探测时间。
4. `verify_connection` 必须重新获取并比较当前实例身份指纹：
   - 实例重启；
   - PID 改变；
   - 可执行文件或命令行改变；
   - 维度改变；
   - 端口/Bridge URL 改变；
   - nonce 不匹配；
   - 证据超时；
   任一条件成立都不得进入 READY。
5. 旧格式证据只允许失败关闭并提示重新探测，不得默认升级为 READY。
6. 如保留 `/health` 诊断，必须将其限定为独立诊断能力，不能把通用 HTTP 客户端
   重新放回 Run 执行路径。

### 测试

- 当前 nonce 和当前身份全部匹配时进入 READY。
- 替换 PID、exe、命令行、维度、端口或 nonce 时任何一项失败都拒绝 READY。
- 证据过期后拒绝 READY。
- 重启实例后旧证据被拒绝。
- 其他实例的证据不能用于当前实例。

### 验收

- 真实 PFC2D/PFC3D 实例分别生成当前实例唯一 READY 证据。
- 旧验收目录中的历史 MCP 证据不能使新启动实例进入 READY。

## 5. PR11：Run-Instance 自动绑定与多实例隔离

### 目标

Run 必须自动解析自己的 Instance 和 MCP connection，不依赖人工提供端口；
两个 Console 同时运行时不得发生交叉查询或误中断。

### 必读文件

- `scripts/headless.py`
- `scripts/pfc_headless/simulation.py`
- `scripts/pfc_headless/instance.py`
- `schema/run.schema.json`
- `schema/instance.schema.json`
- `references/task-management.md`

### 实施要求

1. `run status` 和 `run interrupt` 只接受 `--project` 和 `--run-id`，
   不再接受客户端自定端口。
2. 增加统一解析函数：

```text
run_id
  -> instance_id
  -> current identity fingerprint
  -> mcp_connection_id
  -> task_id / MCP operation request
```

3. Run Registry 保存：
   - instance snapshot；
   - identity fingerprint；
   - MCP connection ID；
   - execution nonce；
   - task ID；
   - 最近一次 MCP 状态证据。
4. 每次 status、interrupt 和 finalize 前重新检查实例身份。实例被替换时返回
   `INSTANCE_IDENTITY_MISMATCH`，不得以“端口仍在监听”为由继续。
5. 一个 MCP connection 只对应一个 Bridge URL。不同实例必须使用不同 MCP
   connection 或 Agent Host 明确提供的连接身份。
6. 中断请求只影响绑定到该 Run 的 task ID；执行中断前校验 Run 状态和 task ID。

### 多实例测试

- 两个 Console 同时运行。
- 分别准备两个 Run 并绑定两个 task ID。
- 分别查询状态，结果不得串线。
- 只中断 Run A，Run B 必须继续运行。
- 交换 Run 与 MCP connection 的负向测试必须失败。
- Run 对应实例停止或被新 PID 替换后，禁止 status/interrupt。

### 验收

- `run status --run-id` 和 `run interrupt --run-id` 无端口参数也能解析正确实例。
- 两个真实实例的并发状态和中断隔离通过；不能只用 Mock 代替 L2 验收。

## 6. PR12：Feedback 状态机与失败重试

### 目标

把“反馈已提出”“Run 正在执行”“反馈已消费”分开，失败后可安全重试，
并防止同一 Feedback 被并发重复消费。

### 必读文件

- `scripts/pfc_headless/feedback.py`
- `schema/feedback.schema.json`
- `tests/test_feedback_manager.py`
- `references/architecture.md`

### 实施要求

1. 新状态机：

```text
RECEIVED
  -> PENDING_APPROVAL
  -> APPROVED
  -> PROPOSED
  -> RUNNING
  -> VALIDATED
     or FAILED
```

2. `prepare_feedback_run` 只执行 `APPROVED -> PROPOSED`，创建候选 Run，
   不得直接写 `USED`。
3. Run 绑定 task 后进入 `RUNNING`。
4. Run 完成、数据验证通过且交付发布成功后，才允许进入 `VALIDATED`。
5. 执行、验证或交付失败时进入 `FAILED`，保留失败 attempt，并允许重试。
6. Feedback 保存 `attempts[]`，至少记录：
   - `run_id`；
   - 状态；
   - 创建、开始、结束时间；
   - 失败原因；
   - 数据验证和交付结果。
7. 同一 Feedback 同时只允许一个活动 attempt；创建新 attempt 必须原子化并写审计。
8. 旧 `USED` 记录保留用于历史读取，不直接迁移或覆盖历史验收证据。
9. 检查 Feedback 的目标缺失通道是否已不再为 `NOT_CAPTURED`。仍未采集或标记
   `NOT_SUPPORTED` 时，不得无条件声称反馈目标已满足。

### 测试

- 只创建 Run 不进入 VALIDATED。
- Run 失败后 Feedback 为 FAILED，可创建下一 attempt。
- 成功完成和新包验证后才进入 VALIDATED。
- 两个并发 prepare 只能有一个活动 attempt。
- `USED` 不会在 `prepare-run` 时出现。
- 历史 `USED` 文档仍可读取，但测试不得将其当作新状态流。

### 验收

- 真实执行一次成功反馈重跑，并观察
  `APPROVED -> PROPOSED -> RUNNING -> VALIDATED`。
- 另外构造一次失败重跑，确认进入 `FAILED` 后能够重试。

## 7. PR13：采集计划、字段配置与输入快照可信度

### 目标

让 Agent 可以显式选择已支持的数据通道和事件，而不是依赖固定的默认字段；
缺失输入必须显式失败或登记，不能静默遗漏。

### 必读文件

- `schema/case.schema.json`
- `scripts/pfc_headless/project.py`
- `scripts/capture_case.py`
- `scripts/run_case.py`
- `tests/test_environment_and_collector.py`
- `references/data-collection.md`
- `references/data-contract.md`

### 实施要求

1. 在 Case 和 Run 快照中增加版本化 `collection_plan`。至少包含：
   - `plan_version`；
   - sampling mode 和 interval；
   - `channels`；
   - `events`；
   - 每个通道的 `required` 和启用状态；
   - 维度或版本不支持时的预期状态。
2. 通道定义采用白名单，不采用任意 Python 表达式。建议初始集合：

```text
ball.position
ball.radius
ball.velocity
ball.spin
wall.geometry
wall.contact_force
contact.id
contact.endpoints
contact.force
history.<explicit-name>
fracture.event
```

3. 事件定义使用已实现注册表：

```text
cycle
time
solve
fracture
```

不得接受任意回调代码作为配置。
4. 配置验证必须在执行前完成。以下情况直接阻止准备 Run：
   - 未支持通道却被标记为 required；
   - 无名称的 History；
   - 无触发条件的事件；
   - PFC2D/PFC3D 不支持的组合；
   - 无效时间或 Cycle 间隔。
5. 不可用但因非 required 而跳过的通道，在交付中明确写
   `NOT_SUPPORTED` 或 `NOT_CAPTURED`，禁止零填充。
6. `source_files` 中每个声明文件都必须存在且可读取。缺失时：
   - 阻止 Run 进入 PREPARED；或
   - 在 `snapshot_manifest.json` 中写入明确的 `missing_inputs` 并阻止执行。

   推荐采用失败关闭，不允许静默跳过。
7. Clump membership 不属于本 PR 的默认承诺。只有在 PFC 9.0 文档、实际 API
   和真实模型均可验证后，才增加独立通道和验收项。

### 测试

- 只选择 Ball position 时不宣称未选通道已采集。
- required 且 unsupported 的通道阻止准备。
- 可选 unsupported 通道状态明确。
- fracture 事件只在真实断键时产生记录。
- History 为空时不能写 PASS 历史证据。
- `source_files` 缺失时禁止静默通过。
- 现有 2D/3D 默认采集兼容路径保持通过。

### 验收

- 至少一个真实 Run 使用显式非默认通道清单。
- 至少一个真实事件 Run 验证注册事件，若无法构造则明确 `NOT_VERIFIED`。
- 现有 PFC2D contact 和 PFC3D time-sampling Run 回归通过。

## 8. PR14：Recovery、Findings 契约与最终集成验收

### 目标

把已有恢复能力接入 Run 生命周期，清理 Headless 的分析职责，并由
Visualization 生成稳定 Findings，完成跨 Skill 自动化闭环。

### 必读文件

- `scripts/recover_run.py`
- `scripts/finalize_run.py`
- `scripts/capture_store.py`
- `scripts/pfc_headless/simulation.py`
- `scripts/pfc_headless/feedback.py`
- Visualization 的 `SKILL.md`、分析 pipeline 和 testing 入口
- 两份 Skill 的标准化数据契约文档

### A. Run Recovery

1. 增加 Registry 集成命令：

```text
run recover --project <project> --run-id <run_id> --reason <reason>
```

2. 命令必须：
   - 校验 Run 和当前 Instance；
   - 不重提 PFC task；
   - 扫描完整行和已提交块；
   - 拒绝损坏的非尾部块；
   - 写显式恢复状态和审计；
   - 不把部分数据伪装成完整 Run。
3. 原 `recover_run.py` 的内部扫描逻辑可以保留，但不得继续绕过 Run Registry。

### B. 分析职责隔离

1. 从 Headless 的最终交付路径中移除应力、应变等派生科学量。
2. `finalize_run.py` 和 `recover_run.py` 中已有 load/displacement/stress 派生逻辑
   不再写入标准交付的必需字段。
3. 如需兼容旧案例，必须通过显式 legacy 开关读取，并标记：

```text
legacy_analysis=true
approved_for_delivery=false
```

4. 新的科学计算和图表只由 Visualization 生成。

### C. Findings Producer

1. 定义版本化 Findings 契约，建议：

```text
pfc.analysis-findings@1.0.0
```

2. Producer 位于 `pfc-scientific-visualization`，不从 Headless 反向实现分析。
3. Findings 至少包含：
   - `source_run_id`；
   - 输入标准包 manifest 哈希；
   - 分析输出根和引用 artifact 哈希；
   - findings；
   - missing_data；
   - recommended_sampling；
   - recommended_parameters/actions；
   - producer 版本和时间。
4. Visualization 提供可调用入口和一个自动化测试，生成 Schema-valid Findings。
5. Headless 只消费该文件，验证运行、artifact、通道和时间范围引用。
6. 不允许 Acceptance 测试继续依赖手工编辑的 Findings JSON 来冒充 Producer 输出。

### D. 最终真实验收

必须重新执行，不得只引用旧报告：

1. 单元/Contract tests 全通过。
2. 真实 PFC2D：

```text
instance READY
-> run prepare
-> Agent itasca_execute_task
-> run attach-task
-> Agent status evidence
-> run record-status
-> run finalize
-> data verify
```

3. 真实 PFC3D 执行同样闭环。
4. 两个 Console 同时运行，分别绑定 MCP connection，完成无交叉的状态和中断测试。
5. 真实中断：
   - Agent 调 `itasca_interrupt_task`；
   - Headless 记录中断；
   - 后续状态证据进入 `INTERRUPTED`；
   - 部分数据只走显式 recovery。
6. 超时：
   - 进入 `TIMEOUT_UNKNOWN`；
   - 查询状态；
   - 不自动重提。
7. 跨 Skill：

```text
Standardized package
-> Visualization analysis
-> automated Findings Producer
-> Headless feedback ingest/approve
-> APPROVED -> PROPOSED -> RUNNING -> VALIDATED
-> new delivered package
```

8. 所有真实 PFC Run 保留为独立 Run，不覆盖历史验收目录。

## 9. PR9-PR14 依赖关系

```text
PR9 -> PR10 -> PR11
                  \
                   -> PR14
PR12 -> PR13 -----/
```

- PR9 必须首先完成，因为后续状态和中断证据都依赖统一执行契约。
- PR10 不得通过扩大 HTTP 客户端来规避身份验证。
- PR11 的真实多实例测试依赖 PR10 的当前实例证据。
- PR12 和 PR13 可以并行，但 PR14 必须等待二者完成。
- PR14 是集成验收 PR，不以补几份报告代替真实重新运行。

## 10. 每个 PR 的交付格式

每次 PR 完成必须报告：

1. 修改文件清单和最小理由。
2. 保留但未修改的关键路径。
3. 新增或更新的 Schema。
4. 单元测试命令和结果。
5. 真实 PFC 测试命令、Run ID、task ID 和证据路径。
6. 负向测试结果。
7. `IMPLEMENTED`、`UNIT_VERIFIED`、`REAL_PFC_VERIFIED`、
   `MULTI_INSTANCE_VERIFIED`、`CROSS_SKILL_VERIFIED` 的明确区分。
8. 未验证项和已知限制。
9. 是否触及历史验收资产；正常情况必须为“未覆盖、未修改”。

## 11. 全局停止条件

出现以下任一情况，执行 Agent 必须停止并报告，不得猜测通过：

- 当前 MCP 工具无法返回能绑定 Run 的 task ID 或状态。
- Agent Host 无法区分多个 MCP connection。
- 当前 PFC 版本不支持被标记为 required 的通道或事件。
- 必须重新实现 MCP Client 或复刻 Bridge 队列才能继续。
- 真实 Run 的输入文件缺失。
- 任务状态未知，却需要决定是否重提非幂等脚本。
- Findings 契约无法引用稳定的输入 manifest 和输出 artifact。

## 12. 最终通过条件

只有同时满足以下条件，才可报告“严格架构验收通过”：

- Run 执行路径不再由 Headless 直接调用 Bridge HTTP。
- READY 证据与当前实例身份、nonce 和有效期绑定。
- Run 自动绑定 Instance 和 MCP connection。
- 两个真实 Console 的并发操作无交叉。
- Feedback 不再过早标记消费，失败可重试。
- 采集字段和注册事件可按计划配置，缺失输入不会静默遗漏。
- Recovery 已进入 Run Registry 工作流。
- Headless 不再生成新的科学分析结果。
- Visualization 自动生产 Findings。
- PFC2D、PFC3D、多实例、中断、超时和跨 Skill 闭环均已在本轮重新验收。
