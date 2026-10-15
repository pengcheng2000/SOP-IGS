import { CheckCircleFilled, FileWordOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App as AntApp, Avatar, Button, Card, Checkbox, Col, Collapse, Descriptions, List, Progress, Row, Statistic, Tag, Timeline, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { formatElapsed, formatLocalDateTime } from "../../time";
import type { BoostDocumentRecord, BoostPreflight, BoostProject, BoostTask } from "./types";

const { Title, Text } = Typography;

export default function BoostGenerationPanel({ project, isAdmin }: { project: BoostProject; isAdmin: boolean }) {
  const { message } = AntApp.useApp();
  const [taskId, setTaskId] = useState<string>();
  const [warningsAccepted, setWarningsAccepted] = useState(false);
  const preflight = useQuery({
    queryKey: ["boost-preflight", project.id],
    queryFn: () => api<BoostPreflight>(`/api/boost/projects/${project.id}/preflight`),
    refetchInterval: 5000
  });
  const documents = useQuery({
    queryKey: ["boost-documents", project.id],
    queryFn: () => api<BoostDocumentRecord[]>(`/api/boost/projects/${project.id}/documents`)
  });
  const task = useQuery({
    queryKey: ["boost-task", taskId],
    queryFn: () => api<BoostTask>(`/api/boost/generations/${taskId}`),
    enabled: Boolean(taskId),
    refetchInterval: (query) => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1000
  });
  useEffect(() => {
    if (task.data?.status === "succeeded") documents.refetch();
  }, [task.data?.status]);
  useEffect(() => setWarningsAccepted(false), [preflight.data?.warnings.length]);

  const generate = useMutation({
    mutationFn: () => api<BoostTask>(`/api/boost/projects/${project.id}/generations`, {
      method: "POST",
      body: JSON.stringify({ idempotency_key: `${project.id}-${project.revision}-${Date.now()}`, allow_warnings: warningsAccepted })
    }),
    onSuccess: (value) => { setTaskId(value.id); message.success("生成任务已提交"); },
    onError: (error) => message.error(error.message)
  });

  const current = task.data;
  const canGenerate = Boolean(preflight.data?.ready) && (!preflight.data?.warning_confirmation_required || warningsAccepted);
  const stats = preflight.data?.stats ?? {};

  return (
    <Row gutter={20}>
      <Col xs={24} lg={15}>
        <Card className="workspace-card" bordered={false}>
          <div className="section-heading">
            <div><Title level={3}>生成前检查</Title><Text type="secondary">必填字段缺失或分类表有错误会阻止生成；提醒需要明确确认。</Text></div>
            {preflight.data?.ready ? <Tag color="success" icon={<CheckCircleFilled />}>检查通过</Tag> : <Tag color="error">需要处理</Tag>}
          </div>
          <Row gutter={16} className="preflight-stats">
            <Col span={8}><Statistic title="章节" value={stats.chapter_count ?? 0} /></Col>
            <Col span={8}><Statistic title="表格" value={stats.table_count ?? 0} /></Col>
            <Col span={8}><Statistic title="图片" value={stats.image_count ?? 0} /></Col>
          </Row>
          {preflight.data?.blockers.map((item) => <Alert key={item.code} type="error" showIcon message={item.message} />)}
          {preflight.data?.warnings.map((item) => <Alert key={item.code} type="warning" showIcon message={item.message} />)}
          {preflight.data?.warning_confirmation_required && (
            <Checkbox className="warning-confirm" checked={warningsAccepted} onChange={(event) => setWarningsAccepted(event.target.checked)}>
              我已确认测试项分类表中的提醒，仍继续生成本次 DOCX
            </Checkbox>
          )}
          <Button type="primary" size="large" icon={<FileWordOutlined />} disabled={!canGenerate} loading={generate.isPending} onClick={() => generate.mutate()}>生成 DOCX</Button>

          {current && (
            <div className="task-progress">
              <div className="task-progress-head"><Text strong>{current.progress_message}</Text><Text type="secondary">已用时 {formatElapsed(current.elapsed_seconds)}</Text></div>
              <Progress
                percent={current.progress_percent}
                status={current.status === "failed" ? "exception" : current.status === "succeeded" ? "success" : "active"}
              />
              {current.stalled && <Alert type="error" showIcon message="任务可能已经卡住" description="超过 120 秒没有收到 Worker 心跳，请检查 Word Worker 是否在运行。" />}
              {current.error_detail && <Alert type="error" showIcon message={current.error_code || "生成失败"} description={current.error_detail} />}
              {isAdmin && (
                <Collapse ghost items={[{
                  key: "diagnostics",
                  label: "开发诊断信息",
                  children: <>
                    <Descriptions size="small" column={2} items={[
                      { key: "task", label: "任务 ID", children: current.id },
                      { key: "attempts", label: "尝试次数", children: current.attempts },
                      { key: "phase", label: "当前阶段", children: current.phase },
                      { key: "heartbeat", label: "最后心跳", children: formatLocalDateTime(current.heartbeat_at) },
                      { key: "diagnostics", label: "处理对象", children: JSON.stringify(current.diagnostics) }
                    ]} />
                    <Timeline items={current.events.map((event) => ({ children: <><Text>{event.message}</Text><br /><Text type="secondary">{formatLocalDateTime(event.created_at)} · {event.progress_percent}%</Text></> }))} />
                  </>
                }]} />
              )}
            </div>
          )}
        </Card>
      </Col>
      <Col xs={24} lg={9}>
        <Card className="workspace-card" bordered={false}>
          <Title level={4}>生成记录</Title>
          <List
            locale={{ emptyText: "尚未生成文档" }}
            dataSource={documents.data ?? []}
            renderItem={(document) => (
              <List.Item actions={[<a key="download" href={document.download_url}>下载</a>]}>
                <List.Item.Meta avatar={<Avatar icon={<FileWordOutlined />} />} title={formatLocalDateTime(document.created_at)} description={`SHA ${document.file_sha256.slice(0, 12)}…`} />
              </List.Item>
            )}
          />
        </Card>
      </Col>
    </Row>
  );
}
