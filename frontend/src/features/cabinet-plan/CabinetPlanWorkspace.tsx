import { ArrowLeftOutlined, CloudUploadOutlined, DownloadOutlined, FileExcelOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Collapse, DatePicker, Descriptions, Form, Input, Progress, Row, Segmented, Skeleton, Space, Tag, Typography, Upload } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { api, uploadWithProgress } from "../../api";
import BoostGenerationPanel from "../boost/BoostGenerationPanel";
import SourcePreview, { PreviewItem, PreviewItems } from "../boost/SourcePreview";
import type { SourceFile } from "../boost/types";
import type { CabinetPlanConfig, CabinetPlanDocument, CabinetPlanProject } from "./types";
import "../boost/boost.css";

const { Title, Text, Paragraph } = Typography;
const BASE = "/api/cabinet-plans";

export function useCabinetPlanConfig() {
  return useQuery({ queryKey: ["cabinet-plan-config"], queryFn: () => api<CabinetPlanConfig>(`${BASE}/config`), staleTime: 60_000 });
}

export function CabinetPlanCard({ project, onOpen }: { project: CabinetPlanProject; onOpen: (p: CabinetPlanProject) => void }) {
  return <Card className="project-card" hoverable onClick={() => onOpen(project)}>
    <div className="project-card-head"><div className="project-icon"><FileExcelOutlined /></div><Space size={4}><Tag color="blue">工商业柜</Tag><Tag color="cyan">测试方案</Tag></Space></div>
    <Title level={4}>{project.name}</Title><Paragraph ellipsis={{ rows: 2 }}>{project.description || "编辑 Excel，一键生成测试方案"}</Paragraph>
    <div className="project-stats"><span><b>{project.source_file?.chapter_count ?? 0}</b> 章节</span><span><b>{project.source_file?.image_count ?? 0}</b> 图片</span><span>{project.source_file ? project.source_file.status === "parsed" ? "已解析" : "需修正 Excel" : "待上传 Excel"}</span></div>
  </Card>;
}

function Information({ project, config, onSaved }: { project: CabinetPlanProject; config: CabinetPlanConfig; onSaved: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const imported = config.fields.filter(f => project.field_sources[f.key]?.kind === "excel");
  const missing = config.fields.filter(f => project.field_sources[f.key]?.kind !== "excel");
  useEffect(() => {
    form.resetFields();
    form.setFieldsValue({ name: project.name, description: project.description, ...project.fields });
  }, [project, form]);
  const save = useMutation({
    mutationFn: (values: Record<string, string>) => api(`${BASE}/projects/${project.id}`, {
      method: "PATCH", body: JSON.stringify({ revision: project.revision, ...(values.name !== project.name ? { name: values.name } : {}), description: values.description || "",
        fields: Object.fromEntries(missing.map(f => [f.key, values[f.key] || ""])) })
    }),
    onSuccess: () => { message.success("补充信息已保存"); onSaved(); },
    onError: (error) => message.error(error.message)
  });
  return <Card className="workspace-card" bordered={false}>
    <div className="section-heading"><div><Title level={3}>信息确认</Title><Text type="secondary">Excel 已填写的信息直接使用；需要修改时，请编辑 Excel 后重新上传。</Text></div><Tag color="green">只补缺项</Tag></div>
    {!project.source_file && <Alert type="info" showIcon message="请先上传测试需求表，系统将自动读取已有信息。" />}
    {project.source_file && <>
      <Descriptions title="已从 Excel 读取" column={{ xs: 1, md: 2 }} styles={{ label: { whiteSpace: "nowrap", width: 100 } }} bordered size="small" items={imported.map(f => ({ key: f.key, label: f.label, span: f.multiline || f.key === "document_title" ? { xs: 1, md: 2 } : 1,
        children: <><div style={{ whiteSpace: "pre-wrap" }}>{project.resolved_fields[f.key]}</div><Text type="secondary">{project.field_sources[f.key]?.cell}</Text></> }))} />
      <Form form={form} layout="vertical" onFinish={values => save.mutate(values)} style={{ marginTop: 24 }}>
        <Row gutter={18}><Col xs={24} md={12}><Form.Item name="name" label="列表显示名称" rules={[{ required: true }]}><Input /></Form.Item></Col><Col xs={24} md={12}><Form.Item name="description" label="项目说明（可选）"><Input /></Form.Item></Col></Row>
        <Title level={5}>Excel 缺少的信息</Title>
        <Row gutter={18}>{missing.map(f => <Col xs={24} md={f.multiline ? 24 : 12} key={f.key}>
          {f.type === "month" ? <Form.Item name={f.key} label={f.label} rules={f.required ? [{ required: true }] : undefined}
            getValueProps={(value?: string) => ({ value: value ? dayjs(`${value}-01`) : null })} normalize={(value: dayjs.Dayjs | null) => value?.format("YYYY-MM") || ""}>
            <DatePicker picker="month" format="YYYY-MM" style={{ width: "100%" }} />
          </Form.Item> : <Form.Item name={f.key} label={`${f.label}${f.required ? "" : "（可选）"}`} rules={f.required ? [{ required: true, message: `请补充${f.label}` }] : undefined}>
            {f.multiline ? <Input.TextArea rows={3} /> : <Input />}
          </Form.Item>}
        </Col>)}</Row>
        {!missing.length && <Text type="success">文档所需信息已全部在 Excel 中填写。</Text>}
        <div><Button type="primary" htmlType="submit" loading={save.isPending}>保存补充信息</Button></div>
      </Form>
    </>}
  </Card>;
}

function SourceStep({ project, onChanged }: { project: CabinetPlanProject; onChanged: () => void }) {
  const { message } = App.useApp();
  const cache = useQueryClient();
  const [progress, setProgress] = useState<{ percent: number; stage: string }>();
  const source = useQuery({ queryKey: ["cabinet-plan-source", project.id], queryFn: () => api<SourceFile & { document: CabinetPlanDocument | null } | null>(`${BASE}/projects/${project.id}/source-file`) });
  async function upload(file: File) {
    const body = new FormData(); body.append("file", file);
    setProgress({ percent: 0, stage: "uploading" });
    try {
      const result = await uploadWithProgress<SourceFile>(`${BASE}/projects/${project.id}/source-file`, body, (percent, stage) => setProgress({ percent, stage }));
      cache.setQueryData(["cabinet-plan-source", project.id], result);
      onChanged();
      if (result.status === "parsed") message.success("解析完成，请确认信息后生成方案");
      else message.error("Excel 有错误，请按提示修正后重新上传");
    } catch (error) { message.error(error instanceof Error ? error.message : "上传失败"); }
    finally { setProgress(undefined); }
  }
  const current = source.data;
  const document = current?.document;
  return <Card className="workspace-card" bordered={false}>
    <div className="section-heading"><div><Title level={3}>上传测试需求</Title><Text type="secondary">使用工商业柜标准模板，在 Excel 中完成测试内容取舍。上传后预览章节并检查信息。</Text></div></div>
    <div className="template-banner"><div><h4>工商业柜测试方案标准模板</h4><p>保留首页和目录示意，已标注标题、列表与表格格式；请阅读填写说明和内容核对。</p></div><Button type="primary" icon={<DownloadOutlined />} href={`${BASE}/input-template`}>下载标准模板</Button></div>
    <Upload.Dragger accept=".xlsx" showUploadList={false} disabled={Boolean(progress)} beforeUpload={file => { void upload(file); return false; }}>
      <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p><p className="ant-upload-text">{current ? "上传新的 Excel，替换当前输入版本" : "拖入或点击上传测试需求 Excel"}</p><p className="ant-upload-hint">A–N 列内容，O 列格式，P 列以后为填写说明；网页无需重复填写 Excel 已有信息。</p>
    </Upload.Dragger>
    {progress && <Progress percent={progress.stage === "processing" ? 100 : progress.percent} status="active" format={() => progress.stage === "processing" ? "解析中" : `${progress.percent}%`} />}
    {source.isLoading ? <Skeleton active /> : current && <div className="source-current">
      <Space wrap><a href={`${BASE}/source-files/${current.id}/original`}>{current.original_filename}</a><Tag color={current.status === "parsed" ? "green" : "red"}>{current.status === "parsed" ? "解析完成" : "需要修正"}</Tag><Text>{current.chapter_count || 0} 个测试章节 · {current.image_count || 0} 张图片</Text></Space>
      {current.issues.map((issue, i) => <Alert key={i} showIcon type={issue.severity} message={`${issue.sheet}${issue.cell ? `!${issue.cell}` : ""}：${issue.message}`} style={{ marginTop: 12 }} />)}
      {document && <>
        <Collapse style={{ marginTop: 18 }} items={[{ key: "home", label: "首页内容（1–4章）", children: <><p>{document.extra.fields.scope_text?.value}</p>{document.extra.references.map((s, i) => <p key={i}>{s}</p>)}{document.extra.environment && <PreviewItem item={document.extra.environment} />}{document.extra.instruments && <PreviewItem item={document.extra.instruments} />}</> }]} />
        <SourcePreview document={document} startNumber={1} />
        <Collapse items={[{ key: "closing", label: "6. 出厂配置确认", children: <PreviewItems items={document.extra.closing} /> }, { key: "version", label: "7. 版本修改记录", children: "日期将在提交生成任务时按北京时间自动生成，版本取首页或补充信息。" }]} />
      </>}
    </div>}
    {source.isError && <Alert type="error" message={source.error.message} />}
  </Card>;
}

export default function CabinetPlanWorkspace({ initial, onBack, isAdmin }: { initial: CabinetPlanProject; onBack: () => void; isAdmin: boolean }) {
  const [step, setStep] = useState("source");
  const cache = useQueryClient();
  const config = useCabinetPlanConfig();
  const projectQuery = useQuery({ queryKey: ["cabinet-plan-project", initial.id], queryFn: () => api<CabinetPlanProject>(`${BASE}/projects/${initial.id}`), initialData: initial });
  const project = projectQuery.data;
  function refresh() {
    cache.invalidateQueries({ queryKey: ["cabinet-plan-project", initial.id] });
    cache.invalidateQueries({ queryKey: ["cabinet-plan-projects"] });
    cache.invalidateQueries({ queryKey: ["cabinet-plan-preflight", initial.id] });
  }
  return <main className="workspace-shell">
    <div className="workspace-top"><Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack}>返回项目列表</Button><div><Text className="eyebrow">工商业柜 · 测试方案</Text><Title level={2}>{project.name}</Title></div><Tag color="cyan">Excel 生成方案</Tag></div>
    <Segmented className="workspace-nav" block value={step} onChange={v => setStep(String(v))} options={[{ value: "source", label: "01 上传测试需求" }, { value: "info", label: "02 信息确认" }, { value: "generate", label: "03 生成方案" }]} />
    {config.isLoading ? <Skeleton active /> : !config.data?.available ? <Alert showIcon type="error" message="工商业柜方案模板不可用，请联系管理员" /> : <>
      {step === "source" && <SourceStep project={project} onChanged={refresh} />}
      {step === "info" && <Information project={project} config={config.data} onSaved={refresh} />}
      {step === "generate" && <BoostGenerationPanel project={project} isAdmin={isAdmin} apiBase={BASE} queryPrefix="cabinet-plan" sourceLabel="测试需求表" />}
    </>}
  </main>;
}
