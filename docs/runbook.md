# docs-agent-ops 运行手册（MVP）

## 1. 环境准备

- Python 3.11
- Docker / Docker Compose
- 可访问 `matrixone` 与 `matrixorigin.io` 仓库的 GitHub 凭证

## 2. 本地初始化

1. 复制环境变量模板：
   - `cp .env.example .env`
2. 填写 `.env` 中的 `DOCS_REPO_TOKEN` 与模型密钥
3. 执行：
   - `./scripts/setup_dev.sh`

## 3. 健康检查

- 本地进程方式：
  - `python -m app.main`
  - `curl http://127.0.0.1:8080/healthz`
- Docker 方式：
  - `docker compose up --build`
  - `curl http://127.0.0.1:8080/healthz`

## 4. 目录约定

- `/srv/repos/matrixorigin.io`：文档仓本地镜像（生产）
- `/srv/workspaces/<run_id>`：任务临时空间（生产）
- `/srv/runs/<run_id>`：运行产物（生产）
- `./runs/`：本地调试产物

## 5. 故障排查

- 如果 `python3.11` 不存在，先安装 Python 3.11，再重跑 `setup_dev.sh`
- 如果容器启动失败，执行：
  - `docker compose build --no-cache`
- 如果健康检查失败，检查端口占用：
  - `lsof -i :8080`

## 6. 灰度期周报生成（Phase 7）

- 单次运行会在 `runs/<run_id>/` 产出 `run_metrics.json`
- 所有运行会聚合到 `runs/metrics_history.jsonl`
- 每周可执行：
  - `python scripts/generate_metrics_report.py`
- 输出：
  - `runs/phase7_report.json`（成功率、PR 创建率、平均时长、主要失败类型）
