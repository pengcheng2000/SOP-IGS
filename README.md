# SOP-IGS

测试 SOP 智能生成系统。系统从固定的液冷户外柜 Word 母版出发，按项目选择保留测试章节、处理和排版照片，并生成可继续编辑的 DOCX。

## 本地开发

### 后端

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".\backend[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python -m app.bootstrap
.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8010
```

### 前端

```powershell
Set-Location frontend
npm install
npm run dev
```

### 文档任务 Worker

Word COM 需要在已登录且已激活 Microsoft Word 的 Windows 账号下运行：

```powershell
.\.venv\Scripts\python -m app.worker.word_worker
```

开发环境默认使用 SQLite；生产环境按 `.env.example` 配置 PostgreSQL、外部数据目录和 HTTPS。

完整的目标服务器安装、构建、服务注册和上线检查见
[`deploy/windows/README.md`](deploy/windows/README.md)。

## 关键约束

- 仅支持仓库内固定版本的 Word 母版。
- 测试项目使用稳定业务 ID，Word 章节编号只在生成时计算。
- LLM 只提供建议，故障不会阻止核心工作流。
- 生产发布前必须完成人工母版净化复核和 Word COM 稳定性验收。

## 照片与生成规则

- 模板会为消防、模块通讯、BMS、起吊、叉举和温升等章节创建固定照片分组。
- 母版明确写有“至少包含”的照片组属于必填；推荐照片缺失时可以确认后继续生成。
- 每个分组支持拖拽上传、照片排序和可选说明；用户还可以增加项目自定义分组。
- 生成页显示真实处理阶段、Word 分页等待时间、Worker 心跳和管理员诊断信息。
