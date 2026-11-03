# Codex 部署提示词（报告与方案三工作流）

在项目电脑上用 Codex 打开仓库根目录，把下面「提示词」整段发给它。

---

## 提示词

你在项目电脑（Windows）上部署/升级 SOP-IGS。先读 `AGENTS.md`、`PROJECT_STATE.md`、`TODO.md`、`deploy/windows/README.md`，再动手。本次升级新增「工商业柜 / 测试方案」（独立模块 `backend/app/cabinet_plan/`，接口 `/api/cabinet-plans`，新表 `cabinet_plan_*`），创建项目按业务和文档类型两层分类。既有工商业柜报告、升压一体机方案继续可用。本次升压方案首页模板及格式修正已确认生产发布，批准哈希随 manifest 提交；工商业柜方案也已在开发机完成发布核验并登记批准哈希，生产电脑只执行部署，不再安排模板审核。

### 硬性约束

1. 不要打印、提交或回显 `.env` 里的任何密钥（SOP_SECRET_KEY、数据库密码、SOP_FEISHU_APP_SECRET、SOP_LLM_API_KEY）。
2. 不要修改 Windows 系统/安全设置、注册表、防火墙，除非我明确同意；需要改时先说明内容并等我确认。
3. 不要删除数据库、数据目录（`SOP_DATA_ROOT`）或备份；升级前先备份（`deploy/windows/backup/backup.ps1`，或至少复制数据目录并 `pg_dump`）。
4. 不要 `git reset --hard` / `git clean`，不要覆盖本地 `.env`。
5. 仓库是公开的：不要把 `SOP_CASE/`、`source.docx`、真实项目数据提交进 git。

### 步骤

1. **升级准备**：确认生产目录、当前提交和数据目录，先暂停 Worker 的恢复触发器，确认队列无在途任务后停止 API 和旧 Worker 的完整 Python 子进程树（只停计划任务可能遗留消费者）。备份数据库、配置和 originals/processed/outputs/boost/cabinet_plan；`git status` 确认干净后 `git pull --ff-only origin main`，记录新提交。不要自动清理生产电脑的本地改动。
2. **后端依赖**：
   ```powershell
   .\.venv\Scripts\python -m pip install -e ".\backend[dev]"
   ```
3. **前端构建**：`cd frontend; npm ci; npm run build`（后端从 `frontend/dist` 提供页面）。
4. **`.env` 检查**（对照 `.env.example`，只补缺失项，不动已有值）：
   - `SOP_ENV=production`，`SOP_DATA_ROOT` 在仓库外。
   - 访问地址相关：`SOP_PUBLIC_BASE_URL`（与飞书后台重定向 URL 完全一致）、`SOP_SESSION_COOKIE_SECURE`。
   - 飞书：`SOP_FEISHU_APP_ID`、`SOP_FEISHU_APP_SECRET`、`SOP_FEISHU_ADMIN_OPEN_IDS`。
   - AI 建议：`SOP_LLM_BASE_URL/API_KEY/MODEL`，建议加 `SOP_LLM_TIMEOUT_SECONDS=90`（默认 10 秒太短会超时）。
   - 两种方案无需额外变量；如需覆盖默认设置，分别使用 `SOP_BOOST_*` 和 `SOP_CABINET_PLAN_*`。
5. **数据库**：工商业柜方案的 `cabinet_plan_projects/source_files/generation_tasks/generated_documents` 四张表由 API 和 Worker 启动时的 `bootstrap_cabinet_plan()` 自动创建；也提供 Alembic `0007`。现有生产库由 bootstrap 管理且没有迁移基线，继续使用启动初始化，不要执行整个 Alembic 迁移链。原有项目表无需搬迁。备份应包含 `originals`、`processed`、`outputs`、`boost`、`cabinet_plan` 及数据库。
6. **跑测试**：使用隔离测试环境执行 `.\.venv\Scripts\python -m pytest -q`，必须全绿；通过数以实际输出为准。失败就停下来报告，不要跳过。
7. **重启服务**：
   - API：重启 WinSW 服务（`deploy/windows/service/sop-api.xml`，监听 `0.0.0.0:8010`）。重启后确认没有旧的 uvicorn 进程占着 8010（`netstat -ano | findstr :8010`），旧进程不加载新代码是常见坑。
   - **Word Worker 必须重启**：它是在专用 Windows 账号的登录会话里运行的计划任务/终端进程（`task-scheduler/start-word-worker.ps1`），不能当普通服务，也不能从后台无界面进程启动（后台启动的进程拉不起 Word）。停掉旧 Worker 再启动新的。同一个 Worker 进程轮询工商业柜报告、升压一体机方案和工商业柜方案三条队列，每次执行一个任务。
8. **Word 环境检查（升压一体机最容易卡在这里）**：
   - 专用账号已登录、Word 已激活，且账号不用于人工编辑 Word。
   - 如果生成任务卡在“等待 Word Worker”或 Word 进程一直不退出，先查是否装了 **OfficePLUS** 之类的 Word VSTO 加载项——它会让无界面 Word 卡住。开发机上的处理是把该加载项在当前用户下禁用（`HKCU\Software\Microsoft\Office\Word\Addins\<加载项>\LoadBehavior=0`）。这属于修改注册表：**先告诉我现象和要改的键，等我确认再改**。
   - 生成失败后检查残留的 `WINWORD.exe`，必要时只结束 Worker 账号下的残留进程。
9. **模板批准**：以每个模板 manifest 的 `approved_master_sha256` 为准。升压新版的 approved_master_sha256 应与 master_sha256 和实际文件 SHA256 相同，启动后 /api/boost/config 应为 approved。工商业柜方案同样已批准，/api/cabinet-plans/config 应为 approved。三种工作流的批准哈希均已提交，部署机无需手动批准；若状态不符，排查代码、模板目录和哈希是否一致，不能要求用户重新审核来绕过版本不一致。
10. **冒烟验证**（用管理员登录，浏览器操作）：
    - `/api/health/ready` 正常，管理页能看到 Worker 心跳。
    - 新建项目先选「工商业柜 / 升压一体机」，再选「测试报告 / 测试方案」；升压报告暂不支持，旧项目的业务及文档类型显示正确。
    - 工商业柜：原流程（勾选测试项 → 上传照片 → 生成）不受影响。
    - 升压一体机：项目名称留空创建 → 下载新标准模板 → 在首页填写信息（电子文件名在 C52，区别于编码）→ 上传 → 只读信息预览及 11 个测试章节 → 生成 → 下载 docx。检查标题/适用范围无重复、环境和仪器来自首页、表头不加粗、PCS及主变/辅变列表显示1)/2)、编号缩进合理、版本修改记录为一级标题且左侧无黑点。无首页的旧标准文件保留原基础信息入口。
    - 工商业柜方案：不填写项目名创建 → 下载标准模板 → 上传 → 预览16章、功率曲线和内容核对提醒 → 信息确认只补缺项 → 生成并下载；首页、目录、正文分别从第1/2/3页开始，正文连续编号，标题栏及总页数正确。
    - 上传一个没有「格式」列的旧表格，应被拒绝并提示下载对应标准模板。
11. **收尾**：确认只运行一个 Word Worker、恢复其原有恢复触发器；不要额外创建第二个消费者。按 `AGENTS.md` 更新 `PROJECT_STATE.md`（部署状态、已知问题）和 `TODO.md`（遗留项），不要写成流水账。

### 汇报格式

完成后用中文给我：① 实际执行的命令与结果；② 测试通过数；③ 冒烟验证每项的通过/失败；④ 需要我决定或确认的事项（注册表修改、飞书后台配置等）；⑤ 遇到的问题和没做完的部分。不要在没验证的情况下说“部署成功”。
