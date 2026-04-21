# 开发环境交接说明（供下一位 Agent 使用）

本文档用于快速接手 `mo_doc_guard` 项目的实际开发阶段，基于当前仓库状态总结开发环境与可用入口。

## 1. 当前环境状态

- 项目路径：`/Users/yanghaoyang/repo/mo_doc_guard`
- Python 版本：已可使用 `Python 3.11`（`scripts/setup_dev.sh` 已验证通过）
- 包安装方式：`pip install -e ".[dev]"`（editable 安装）
- 依赖管理：`pyproject.toml`
- 容器支持：`Dockerfile` + `docker-compose.yml` 已就绪

## 2. 已完成的工程初始化

- Python 工程基础：
  - `.python-version`
  - `pyproject.toml`
  - `.gitignore`
  - `Makefile`
- 应用目录骨架（与 `plan.md` 对齐）：
  - `app/graph`
  - `app/skills`
  - `app/retrieval`
  - `app/connectors`
  - `app/core`
- 配置与文档：
  - `configs/path_mapping.yaml`
  - `configs/quality_gates.yaml`
  - `.env.example`
  - `docs/runbook.md`
- CI 验证骨架：
  - `.github/workflows/dev-sanity.yml`

## 3. 关键修复记录

已修复 `setup_dev.sh` 安装失败问题：

- 现象：`setuptools` 报错 `Multiple top-level packages discovered in a flat-layout`
- 原因：自动发现把 `app`、`runs`、`configs` 都当作顶层包
- 修复：在 `pyproject.toml` 中显式限制包发现范围，仅包含 `app*`
  - `[tool.setuptools.packages.find]`
  - `include = ["app*"]`
  - `namespaces = false`

## 4. 启动与验证命令

### 本地开发

```bash
bash scripts/setup_dev.sh
source .venv/bin/activate
python -m app.main
```

健康检查：

```bash
curl http://127.0.0.1:8080/healthz
```

### Docker

```bash
docker compose up --build
```

## 5. 当前代码入口（MVP 骨架）

- 服务入口：`app/main.py`（提供 `/healthz`）
- 环境配置：`app/core/settings.py`
- 工作流规划节点：`app/graph/workflow.py`（当前为 planned nodes 占位）
- Skill 占位实现：
  - `app/skills/mo_doc_writer.py`
  - `app/skills/mo_doc_reviewer.py`

## 6. 进入实际开发的建议顺序（对齐 plan.md）

建议从 Phase 2 开始：

1. 实现 `run_id`、`idempotency_key` 生成与状态落盘（`run_state.json`）
2. 实现 `sync_docs_repo_main` 节点（先空跑，再真实同步）
3. 打通 GitHub Actions 的 `workflow_dispatch` 与 tag 触发输入
4. 在 `runs/` 中沉淀最小 artifacts（至少含状态与日志）

## 7. 注意事项

- 文档正文严禁 AI 元信息（见 `plan.md` 约束）
- 只允许在白名单文档路径写入
- `reviewer` 未通过必须阻断 PR 创建
- 目前 Skill/Graph 仍为骨架，尚未实现业务逻辑

