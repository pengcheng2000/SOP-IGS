# Windows 部署

仓库已包含后端、前端源码、净化后的 `master.docx`、数据库迁移和 Windows
部署示例。原始案例文档和含历史项目数据的 `source.docx` 不在公开仓库中，部署不依赖它们。

## 1. 前置条件

- 64 位 Python 3.11。
- Node.js 20 或更高版本。
- PostgreSQL 15 或更高版本。
- 已安装并激活 Microsoft Word 的专用 Windows 登录账号。
- Caddy 和 WinSW（或公司已有的等价服务管理工具）。

服务器账号不得同时用于人工编辑 Word 文档。Word Worker 必须在专用账号登录后运行，
不能注册成普通 Windows Service。

## 2. 安装与构建

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".\backend"

Push-Location frontend
npm ci
npm run build
Pop-Location

Copy-Item .env.example .env
```

编辑 `.env`，至少替换数据库密码、`SOP_SECRET_KEY`、管理员初始密码和 LLM 配置。
生产环境保持 `SOP_ENV=production`、`SOP_SESSION_COOKIE_SECURE=true`，并确认
`SOP_DATA_ROOT` 指向仓库外的独立数据盘目录。

## 3. 初始化与验证

```powershell
.\.venv\Scripts\python -m app.bootstrap
.\.venv\Scripts\python -m pytest
```

首次测试可分别启动 API 和 Worker：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
.\deploy\windows\task-scheduler\start-word-worker.ps1
```

访问 `http://127.0.0.1:8000/health/ready` 验证 API。正式用户通过 Caddy 配置的
HTTPS 域名访问，不直接暴露 8000 端口。

## 4. 注册长期运行组件

1. 按 `service/sop-api.xml` 配置 WinSW 并注册 FastAPI 服务。
2. 按 `caddy/Caddyfile.example` 配置公司证书和内网 DNS，再注册 Caddy 服务。
3. 使用专用 Word 账号执行 `task-scheduler/register-word-worker.ps1`。
4. 给 API 服务账号和 Word Worker 账号授予数据目录读写权限。
5. 按 `backup/backup.ps1` 配置 PostgreSQL 与文件每日备份，并至少做一次恢复演练。

业务确认净化后的 `master.docx` 后，由管理员调用
`POST /api/admin/templates/{template_id}/approve`。生产环境会拒绝使用未批准母版生成文档。

## 5. 上线检查

- 重启电脑后 API、Caddy 和登录态 Word Worker 能自动恢复。
- `/health/live` 与 `/health/ready` 正常，管理页能看到 Worker 心跳。
- 真实照片上传、预检查、生成、下载和 Word 重新打开均通过。
- 目标电脑完成 100 次连续 Word COM 稳定性测试，无残留 `WINWORD.exe`。
