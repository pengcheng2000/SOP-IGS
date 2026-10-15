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
生产环境保持 `SOP_ENV=production`，并确认 `SOP_DATA_ROOT` 指向仓库外的独立数据盘目录。

当前同事通过内网 HTTP 直接访问 `http://10.122.3.224:8010`（同机 8000 端口已被其他项目占用），
`.env` 需设置：

```dotenv
SOP_PUBLIC_BASE_URL=http://10.122.3.224:8010
SOP_SESSION_COOKIE_SECURE=false
```

`SOP_PUBLIC_BASE_URL` 决定飞书回调地址，必须与飞书后台登记的地址一致。生产配置只有在显式声明
`http://` 公共地址时才允许关闭安全 Cookie。以后改用 HTTPS 域名时，改为 `https://` 地址并设置
`SOP_SESSION_COOKIE_SECURE=true`，再按下文配置 Caddy 和证书。

放行防火墙入站端口（管理员 PowerShell）：

```powershell
New-NetFirewallRule -DisplayName "SOP-IGS 8010" -Direction Inbound -Protocol TCP -LocalPort 8010 -Action Allow -Profile Domain,Private
```

## 3. 初始化与验证

```powershell
.\.venv\Scripts\python -m app.bootstrap
.\.venv\Scripts\python -m pytest
```

首次测试可分别启动 API 和 Worker：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
.\deploy\windows\task-scheduler\start-word-worker.ps1
```

访问 `http://127.0.0.1:8010/api/health/ready` 验证 API，再从其他电脑打开
`http://10.122.3.224:8010/login` 确认能看到飞书二维码。

## 4. 注册长期运行组件

1. 按 `service/sop-api.xml` 配置 WinSW 并注册 FastAPI 服务（监听 `0.0.0.0:8010`）。
2. 仅在改用 HTTPS 域名时：按 `caddy/Caddyfile.example` 配置公司证书和内网 DNS，注册 Caddy 服务，
   并把 `sop-api.xml` 的 `--host` 改回 `127.0.0.1`。
3. 使用专用 Word 账号执行 `task-scheduler/register-word-worker.ps1`。
4. 给 API 服务账号和 Word Worker 账号授予数据目录读写权限。
5. 按 `backup/backup.ps1` 配置 PostgreSQL 与文件每日备份，并至少做一次恢复演练。

### HTTPS 证书（仅 HTTPS 域名部署）

浏览器提示“你的连接不是专用连接”（`NET::ERR_CERT_AUTHORITY_INVALID`）说明服务器证书
不是由访问电脑信任的 CA 签发，例如自签名证书或 Caddy `tls internal` 生成的证书。
不要让用户点“高级 → 继续访问”，应按以下任一方式处理：

- **推荐**：向公司 IT 申请由企业内部 CA（域内电脑已默认信任）签发的服务器证书，
  证书 SAN 必须包含用户实际访问的主机名（如 `chengpeng3-pc.chintpower.com`），
  再把 `server.crt`（含中间证书链）和 `server.key` 配置到 Caddyfile 的 `tls` 行。
- 临时测试：继续使用 Caddy 内部 CA，但需把 Caddy 根证书（`caddy trust` 生成的
  `root.crt`）导入每台访问电脑的“受信任的根证书颁发机构”，或由 IT 通过组策略下发。

更换证书后执行 `caddy reload`，并在客户端确认地址栏不再显示“不安全”。

### 飞书登录

1. 在 `.env` 配置 `SOP_FEISHU_APP_ID`、`SOP_FEISHU_APP_SECRET`。
2. 在飞书开放平台该应用的「安全设置 → 重定向 URL」中登记（协议、主机、端口必须完全一致）：
   - `http://127.0.0.1:8010/api/auth/feishu/callback`（本机测试）
   - `http://10.122.3.224:8010/api/auth/feishu/callback`（部署机）
3. 应用需开通 `authen` 获取用户身份权限，并在「可用范围」中包含需要登录的员工。
4. 登录页直接显示飞书二维码（SDK 来自 `lf-package-cn.feishucdn.com`，客户端需能访问；
   加载失败时页面提供「跳转飞书授权登录」备用入口）。
5. 任何在可用范围内的员工扫码即自动建档为普通用户并可直接使用，无需管理员审批。
   管理员可在「账号与权限」中设为管理员或停用；`SOP_FEISHU_ADMIN_OPEN_IDS` 中的 open_id
   登录时自动成为管理员。
6. 本地 `admin` 账号保留为应急登录方式，入口是登录页底部的「管理员账号登录」。

业务确认净化后的 `master.docx` 后，由管理员调用
`POST /api/admin/templates/{template_id}/approve`。生产环境会拒绝使用未批准母版生成文档。

## 5. 上线检查

- 重启电脑后 API、Caddy 和登录态 Word Worker 能自动恢复。
- `/health/live` 与 `/health/ready` 正常，管理页能看到 Worker 心跳。
- 真实照片上传、预检查、生成、下载和 Word 重新打开均通过。
- 目标电脑完成 100 次连续 Word COM 稳定性测试，无残留 `WINWORD.exe`。
