# plan.md

# MatrixOne 文档自动化系统开发计划

## 1. 项目目标

构建一套云端自动化系统：当 `matrixone` 发布新版本 tag 时，自动分析 `prev_tag..new_tag` 的代码变化，生成并审查 `matrixorigin.io` 文档改动，通过后自动创建 PR，人工仅在 PR 阶段确认并 merge。

---

## 2. 已冻结技术栈

- 语言与运行时：`Python 3.11`
- 编排：`LangGraph`
- 检索增强：`LangChain`（增量 RAG）
- 仓库/PR 操作：`GitHub MCP Server` + `git`
- 触发与调度：`GitHub Actions`（tag 触发 + 手动触发）
- 部署形态：云端单服务（VM + Docker）
- 状态管理：文件化状态与 artifacts
- Agent Skill：
  - `mo-doc-writer`
  - `mo-doc-reviewer`

---

## 3. 核心约束（必须满足）

- `matrixorigin.io` 文档会直接渲染到官网，**文档正文不得包含任何 AI 元信息**。
- 证据链、审查结论、风险信息仅出现在：
  - PR 描述
  - CI artifacts
  - 运行日志
- Reviewer 未通过时，必须阻断 PR 创建。
- 不允许自动 merge，始终人工 merge。
- 文档改动只允许在白名单路径中发生。

---

## 4. 系统架构

## 4.1 组件

1. **GitHub Actions（触发层）**
   - 监听 `matrixone` tag 发布事件
   - 调用云端执行入口
2. **Cloud Runner（执行层）**
   - 运行 LangGraph 工作流
   - 维护本地 `matrixorigin.io` main 最新镜像
3. **GitHub MCP（仓库层）**
   - 拉取 diff/commit/tag 信息
   - 创建分支、提交、发 PR
4. **File Artifacts（审计层）**
   - `evidence_bundle.json`
   - `claims.json`
   - `review_report.json`
   - `run_state.json`
   - `pipeline.log`

## 4.2 LangGraph 主流程

`trigger -> resolve_prev_tag -> sync_docs_repo -> collect_evidence -> writer_agent -> reviewer_agent -> quality_gate -> create_pr -> archive_notify`

失败分支：
- 任一异常：写入失败状态 + 上传 artifacts + 通知
- `quality_gate` 不通过：终止，不创建 PR

---

## 5. 双 Skill 设计

## 5.1 Skill A：`mo-doc-writer`

### 职责
- 读取 `prev_tag..new_tag` 的差异证据
- 识别文档影响点（MVP：SQL 语法、系统变量）
- 生成 Markdown 改动 patch（仅开发者可读内容）

### 输入
- `repo_code`, `repo_docs`
- `prev_tag`, `new_tag`
- `evidence_bundle`
- `path_mapping`

### 输出
- `doc_patch.diff`
- `change_summary.md`
- `claims.json`（机器审计用，不进入文档）

### 硬约束
- 无证据不写
- 禁止推断未在 diff 出现的行为变化
- 仅修改文档白名单路径

---

## 5.2 Skill B：`mo-doc-reviewer`

### 职责
- 对 Writer 的每条变更进行证据核验
- 拦截幻觉、越界结论、证据不足内容
- 输出 pass/fail 决策

### 输入
- `doc_patch.diff`
- `claims.json`
- `evidence_bundle`

### 输出
- `decision`: `pass | fail`
- `review_report.json`
- `blocking_issues`

### 硬约束
- 任何“无法证实”结论 -> fail
- 任何“超出 diff 范围”结论 -> fail
- 有 blocking issue -> fail

---

## 6. 仓库同步与分支策略（云端本地仓）

## 6.1 本地仓目录约定

- `/srv/repos/matrixorigin.io`：常驻文档仓本地镜像
- `/srv/workspaces/<run_id>`：任务临时工作区
- `/srv/runs/<run_id>`：运行结果与 artifacts

## 6.2 每次运行前

- 同步本地仓到 `origin/main` 最新状态
- 创建任务分支：`docs/auto/<new_tag>-<run_id>`

## 6.3 每次运行后

- 清理临时工作区
- 保留 artifacts 与日志
- 仅通过 PR 合入，不直接推 main

---

## 7. 文件化状态与幂等设计（无 DB/无 Redis）

## 7.1 幂等键

- `idempotency_key = <prev_tag>..<new_tag>`

## 7.2 状态文件

- `run_state.json` 示例字段：
  - `run_id`
  - `prev_tag`
  - `new_tag`
  - `stage`
  - `status`
  - `decision`
  - `artifacts`

## 7.3 幂等策略

- 若同一 `idempotency_key` 已成功创建 PR，后续触发直接跳过并记录日志
- 失败任务允许手动重跑（`workflow_dispatch`）

---

## 8. 项目目录建议（docs-agent-ops）

- `app/graph/`：LangGraph 状态机与节点
- `app/skills/`：Writer/Reviewer Skill 实现
- `app/retrieval/`：LangChain 增量检索
- `app/connectors/`：GitHub MCP 封装
- `app/core/`：schema、gate、utils
- `configs/path_mapping.yaml`：代码路径->文档路径映射
- `configs/quality_gates.yaml`：阻断规则
- `.github/workflows/`：触发与调度
- `runs/`：本地调试输出（生产可挂载卷）
- `docs/runbook.md`：运维手册

---

## 9. 分阶段开发计划与验收标准

## Phase 0：需求冻结与基础设计（1-2 天）

### 任务
- 冻结 MVP 范围：SQL 语法 + 系统变量
- 冻结白名单目录、PR 模板、质量门禁
- 冻结输出 schema（claims/review）

### 验收标准
- 形成书面范围文档
- 形成质量门禁清单（>= 8 条）
- 形成 PR 模板 v1

---

## Phase 1：工程初始化与云端部署（2-3 天）

### 任务
- 初始化 `docs-agent-ops` 仓库与目录
- 配置 Docker 运行环境
- 配置 GitHub/LLM secrets
- 建立云端目录结构与访问权限

### 验收标准
- 服务可在云端启动并健康检查通过
- 能读取 `matrixone`，能写 `matrixorigin.io` 分支
- Secrets 不落盘、权限最小化生效

---

## Phase 2：仓库同步与触发打通（2 天）

### 任务
- 实现 `sync_docs_repo_main` 节点
- 实现 run_id、idempotency_key
- GitHub Actions 实现手动触发 + tag 触发

### 验收标准
- 连续 20 次同步无脏仓
- 同一 tag 对重复触发具备幂等行为
- 触发链路端到端打通（到空跑）

---

## Phase 3：证据采集与增量 RAG（3-4 天）

### 任务
- 实现 `resolve_prev_tag` 与 `collect_evidence`
- 产出 `evidence_bundle.json`
- 实现增量检索（仅基于本次 tag 差异）

### 验收标准
- 同一 tag 对重跑证据一致
- 每条证据可追溯 commit/file/hunk
- 采集 + 检索耗时可控（目标 < 2 分钟）

---

## Phase 4：Writer Skill 开发（4-5 天）

### 任务
- 实现 `mo-doc-writer`（结构化输入输出）
- 生成 `doc_patch.diff`, `change_summary.md`, `claims.json`
- 增加白名单路径校验和正文污染检测

### 验收标准
- 历史 10 个 tag 回放可产出 patch
- 文档正文元信息污染 = 0
- 人工抽检事实准确率 >= 85%

---

## Phase 5：Reviewer Skill 开发（4-5 天）

### 任务
- 实现 `mo-doc-reviewer` claim-by-claim 审查
- 输出 `review_report.json` 与 `decision`
- 明确 P0/P1 阻断规则

### 验收标准
- 幻觉注入样本拦截率 >= 95%
- P0 事实错误漏检率 = 0（测试集）
- fail 原因可复现、可修复

---

## Phase 6：Gate + 自动 PR（3-4 天）

### 任务
- 实现程序硬门禁：
  - `decision == pass`
  - `blocking_issues == []`
  - 所有 claims 已验证
  - patch 白名单通过
- 通过后自动创建 PR
- PR 描述附摘要、证据、审查结果

### 验收标准
- reviewer fail 时 100% 不提 PR
- pass 时 100% 提 PR 成功（在测试样本上）
- PR 内容完整率 100%

---

## Phase 7：灰度上线与调优（2-4 周）

### 任务
- 在真实 release 上灰度运行
- 周度复盘驳回原因、漏检点、耗时、成本
- 迭代 path_mapping 与 prompts

### 验收标准
- 自动 PR 人工一次通过率 >= 70%
- 端到端平均时长 <= 30 分钟
- 无 P0 错误文档合入

---

## 10. 质量门禁（统一）

- `G1` 文档正文零污染（禁止 AI 元信息）
- `G2` 每条改动可在 claims/report 找到证据映射
- `G3` reviewer fail 必须阻断 PR
- `G4` 改动路径必须在白名单
- `G5` 每次运行必须产出 artifacts
- `G6` 禁止自动 merge

---

## 11. 监控与运维（无数据库版）

## 11.1 核心指标

- 流水线成功率
- PR 自动创建成功率
- 人工一次通过率
- 幻觉拦截率
- 单次运行时长
- 单次运行成本（token）

## 11.2 运维策略

- 失败自动通知（GitHub Action + Webhook/Slack）
- 手动重跑入口（`workflow_dispatch`）
- artifacts 保留策略（例如 30 天）
- 本地运行目录定期清理任务（cron）

---

## 12. 风险与缓解

- 幻觉风险：Reviewer 强阻断 + 无证据拒绝
- 漏更风险：持续迭代 path mapping + 历史回放
- 脏仓风险：运行前强同步 + 运行后清理
- 重复触发风险：幂等键去重
- PR 噪音风险：无实质改动不提 PR

---

## 13. Definition of Done（MVP）

满足以下条件视为 MVP 完成：

- 云端单服务稳定运行，支持 tag 自动触发
- 双 Skill（writer/reviewer）可独立执行并已接入 LangGraph
- reviewer 通过后自动创建 `matrixorigin.io` PR
- 文档正文无元信息污染
- reviewer fail 可稳定阻断 PR
- 人工只需在 PR 做最终确认并 merge