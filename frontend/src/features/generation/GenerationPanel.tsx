import { CheckCircleFilled, FileWordOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App as AntApp, Avatar, Button, Card, Checkbox, Col, Collapse, Descriptions, List, Progress, Row, Statistic, Tag, Timeline, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../../api";
import WorkerStatusAlert from "../../components/WorkerStatusAlert";
import { formatElapsed, formatLocalDateTime } from "../../time";
import type { GenerationTask, Preflight, Project } from "../../types";

const { Title, Text } = Typography;

export default function GenerationPanel({ project, isAdmin }: { project: Project; isAdmin: boolean }) {
  const { message } = AntApp.useApp();
  const [taskId, setTaskId] = useState<string>();
  const [warningsAccepted, setWarningsAccepted] = useState(false);
  const preflight = useQuery({
    queryKey: ["preflight", project.id],
    queryFn: () => api<Preflight>(`/api/projects/${project.id}/preflight`),
    refetchInterval: 5000
  });
  const documents = useQuery({
    queryKey: ["documents", project.id],
    queryFn: () => api<Array<{ id: string; created_at: string; download_url: string; file_sha256: string }>>(`/api/projects/${project.id}/generated-documents`)
  });
  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api<GenerationTask>(`/api/generations/${taskId}`),
    enabled: Boolean(taskId),
    refetchInterval: (query) => ["succeeded", "failed"].includes(query.state.data?.status ?? "") ? false : 1000
  });
  useEffect(() => {
    if (task.data?.status === "succeeded") documents.refetch();
  }, [task.data?.status]);
  useEffect(() => setWarningsAccepted(false), [preflight.data?.warnings.length]);

  const generate = useMutation({
    mutationFn: () => api<GenerationTask>(`/api/projects/${project.id}/generations`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: `${project.id}-${project.revision}-${Date.now()}`,
        allow_warnings: warningsAccepted
      })
    }),
    onSuccess: (value) => { setTaskId(value.id); message.success("生成任务已提交"); },
    onError: (error) => message.error(error.message)
  });

  const current = task.data;
  const slow = current && current.phase_elapsed_seconds >= 45 && !current.stalled;
  const canGenerate = Boolean(preflight.data?.ready) && (!preflight.data?.warning_confirmation_required || warningsAccepted);

  return (
    <Row gutter={20}>
      <Col xs={24} lg={15}>
        <Card className="workspace-card" bordered={false}>
          <div className="section-heading">
            <div><Title level={3}>生成前检查</Title><Text type="secondary">必填缺失会阻止生成；推荐缺失需要明确确认。</Text></div>
            {preflight.data?.ready ? <Tag color="success" icon={<CheckCircleFilled />}>结构检查通过</Tag> : <Tag color="error">需要处理</Tag>}
          </div>
          <Row gutter={16} className="preflight-stats">
            <Col span={8}><Statistic title="已选测试项" value={preflight.data?.selected_count ?? 0} /></Col>
            <Col span={8}><Statistic title="有效照片" value={preflight.data?.photo_count ?? 0} /></Col>
            <Col span={8}><Statistic title="无照片章节" value={preflight.data?.without_photos.length ?? 0} /></Col>
          </Row>
          {preflight.data?.blockers.map((item) => (
            <Alert key={item.code} type="error" showIcon message={item.message} description={item.photo_groups?.map((group) => `${group.title}（${group.photo_count}/${group.min_photos}）`).join("、")} />
          ))}
          {preflight.data?.warnings.map((item) => (
            <Alert key={item.code} type="warning" showIcon message={item.message} description={item.photo_groups?.map((group) => `${group.title}（${group.photo_count}/${Math.max(1, group.min_photos)} 张）`).join("、")} />
          ))}
          {preflight.data?.warning_confirmation_required && (
            <Checkbox className="warning-confirm" checked={warningsAccepted} onChange={(event) => setWarningsAccepted(event.target.checked)}>
              我已确认上述推荐照片暂缺，仍继续生成本次 DOCX
            </Checkbox>
          )}
          <Button type="primary" size="large" icon={<FileWordOutlined />} disabled={!canGenerate} loading={generate.isPending} onClick={() => generate.mutate()}>生成 DOCX</Button>

          {current && (
            <div className="task-progress">
              <div className="task-progress-head"><Text strong>{current.progress_message}</Text><Text type="secondary">已用时 {formatElapsed(current.elapsed_seconds)}</Text></div>
              <Progress
                percent={current.progress_percent}
                status={current.status === "failed" ? "exception" : current.status === "succeeded" ? "success" : "active"}
                strokeColor={current.phase === "word_finalizing" ? { from: "#0f766e", to: "#5eead4" } : undefined}
              />
              {slow && <Alert type="info" showIcon message="当前阶段耗时较长，但 Worker 心跳正常" description="Word 正在处理分页、图片和目录；图片越多，耗时越长。" />}
              {current.stalled && <Alert type="error" showIcon message="任务可能已经卡住" description="超过 120 秒没有收到 Worker 心跳，请查看诊断信息或重新启动 Word Worker。" />}
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
                      { key: "phaseTime", label: "阶段耗时", children: formatElapsed(current.phase_elapsed_seconds) },
                      { key: "diagnostics", label: "处理对象", children: JSON.stringify(current.diagnostics) }
                    ]} />
                    <Timeline items={current.events.map((event) => ({ children: <><Text>{event.message}</Text><br /><Text type="secondary">{formatLocalDateTime(event.created_at)} · {event.progress_percent}%</Text></> }))} />
                  </>
                }]} />
              )}
            </div>
          )}
          <WorkerStatusAlert />
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
                <List.Item.Meta
                  avatar={<Avatar icon={<FileWordOutlined />} />}
                  title={formatLocalDateTime(document.created_at)}
                  description={`SHA ${document.file_sha256.slice(0, 12)}…`}
                />
              </List.Item>
            )}
          />
        </Card>
      </Col>
    </Row>
  );
}
