# Codex 部署提示词（升压一体机版本）

在项目电脑上用 Codex 打开仓库根目录，把下面「提示词」整段发给它。

---

## 提示词

你在项目电脑（Windows）上部署/升级 SOP-IGS。先读 `AGENTS.md`、`PROJECT_STATE.md`、`TODO.md`、`deploy/windows/README.md`，再动手。本次升级新增了第二个产品「升压一体机」（独立模块 `backend/app/boost/`，接口 `/api/boost`，新表 `boost_*`），并包含飞书扫码登录。工商业柜行为不变。

### 硬性约束

1. 不要打印、提交或回显 `.env` 里的任何密钥（SOP_SECRET_KEY、数据库密码、SOP_FEISHU_APP_SECRET、SOP_LLM_API_KEY）。
2. 不要修改 Windows 系统/安全设置、注册表、防火墙，除非我明确同意；需要改时先说明内容并等我确认。
3. 不要删除数据库、数据目录（`SOP_DATA_ROOT`）或备份；升级前先备份（`deploy/windows/backup/backup.ps1`，或至少复制数据目录并 `pg_dump`）。
4. 不要 `git reset --hard` / `git clean`，不要覆盖本地 `.env`。
5. 仓库是公开的：不要把 `SOP_CASE/`、`source.docx`、真实项目数据提交进 git。

### 步骤

1. **拉代码**：`git status` 确认干净后 `git pull origin main`。
2. **后端依赖**（新增了 `openpyxl`，必须重装）：
   ```powershell
   .\.venv\Scripts\python -m pip install -e ".\backend"
   ```
3. **前端构建**：`cd frontend; npm ci; npm run build`（后端从 `frontend/dist` 提供页面）。
4. **`.env` 检查**（对照 `.env.example`，只补缺失项，不动已有值）：
   - `SOP_ENV=production`，`SOP_DATA_ROOT` 在仓库外。
   - 访问地址相关：`SOP_PUBLIC_BASE_URL`（与飞书后台重定向 URL 完全一致）、`SOP_SESSION_COOKIE_SECURE`。
   - 飞书：`SOP_FEISHU_APP_ID`、`SOP_FEISHU_APP_SECRET`、`SOP_FEISHU_ADMIN_OPEN_IDS`。
   - AI 建议：`SOP_LLM_BASE_URL/API_KEY/MODEL`，建议加 `SOP_LLM_TIMEOUT_SECONDS=90`（默认 10 秒太短会超时）。
   - 升压一体机无需额外变量（可选 `SOP_BOOST_TEMPLATE_DIR`、`SOP_BOOST_MAX_SOURCE_FILE_BYTES`）。
5. **数据库**：升压一体机的 4 张表（`boost_projects`、`boost_source_files`、`boost_generation_tasks`、`boost_generated_documents`）会在 API 启动时由 `bootstrap_boost()` 自动创建，也有 Alembic 迁移 `0004`。若生产库由 Alembic 管理，在 `backend` 目录执行 `alembic upgrade head`；否则运行 `.\.venv\Scripts\python -m app.bootstrap`。不要改动已有的 `projects` 等表。
6. **跑测试**：`.\.venv\Scripts\python -m pytest -q`，必须全绿（应为 76 个）。失败就停下来报告，不要跳过。
7. **重启服务**：
   - API：重启 WinSW 服务（`deploy/windows/service/sop-api.xml`，监听 `0.0.0.0:8010`）。重启后确认没有旧的 uvicorn 进程占着 8010（`netstat -ano | findstr :8010`），旧进程不加载新代码是常见坑。
   - **Word Worker 必须重启**：它是在专用 Windows 账号的登录会话里运行的计划任务/终端进程（`task-scheduler/start-word-worker.ps1`），不能当普通服务，也不能从后台无界面进程启动（后台启动的进程拉不起 Word）。停掉旧 Worker 再启动新的。同一个 Worker 进程同时处理两个产品的任务（先工商业柜队列，再升压一体机队列）。
8. **Word 环境检查（升压一体机最容易卡在这里）**：
   - 专用账号已登录、Word 已激活，且账号不用于人工编辑 Word。
   - 如果生成任务卡在“等待 Word Worker”或 Word 进程一直不退出，先查是否装了 **OfficePLUS** 之类的 Word VSTO 加载项——它会让无界面 Word 卡住。开发机上的处理是把该加载项在当前用户下禁用（`HKCU\Software\Microsoft\Office\Word\Addins\<加载项>\LoadBehavior=0`）。这属于修改注册表：**先告诉我现象和要改的键，等我确认再改**。
   - 生成失败后检查残留的 `WINWORD.exe`，必要时只结束 Worker 账号下的残留进程。
9. **模板批准**：无需任何操作。母版是否批准由 `manifest.yaml` 里的 `approved_master_sha256` 决定，随代码发布，启动时自动生效。如果部署后生产环境仍提示“母版未批准”，不要手动改数据库，汇报现象（`GET /api/boost/config` 的 `template_status`、manifest 里的哈希与实际 `master.docx` 哈希）即可。
10. **冒烟验证**（用管理员登录，浏览器操作）：
    - `/api/health/ready` 正常，管理页能看到 Worker 心跳。
    - 新建项目时能选「工商业柜 / 升压一体机」，项目列表两种都显示。
    - 工商业柜：原流程（勾选测试项 → 上传照片 → 生成）不受影响。
    - 升压一体机：填基础信息（归档日期是月份选择器）→ 下载「标准模板」→ 原样上传 → 预览出章节 → 生成 → 下载 docx，用 Word 打开检查：标题栏、电子文件名文本框、共 N 页、5.x.y.z 三级标题编号连续。
    - 上传一个没有「格式」列的旧表格，应被拒绝并提示下载标准模板。
11. **收尾**：按 `AGENTS.md` 更新 `PROJECT_STATE.md`（部署状态、已知问题）和 `TODO.md`（遗留项），不要写成流水账。

### 汇报格式

完成后用中文给我：① 实际执行的命令与结果；② 测试通过数；③ 冒烟验证每项的通过/失败；④ 需要我决定或确认的事项（注册表修改、飞书后台配置等）；⑤ 遇到的问题和没做完的部分。不要在没验证的情况下说“部署成功”。
