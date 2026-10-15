import { CloudUploadOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Card, Descriptions, Progress, Skeleton, Space, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { api, uploadWithProgress } from "../../api";
import { formatLocalDateTime } from "../../time";
import type { BoostConfig, BoostProject, ParseIssue, SourceFile } from "./types";
import SourcePreview from "./SourcePreview";

const { Title, Text } = Typography;

function IssueList({ issues, templateAvailable }: { issues: ParseIssue[]; templateAvailable: boolean }) {
  if (!issues.length) return null;
  const bySheet = new Map<string, ParseIssue[]>();
  for (const issue of issues) bySheet.set(issue.sheet || "工作簿", [...(bySheet.get(issue.sheet || "工作簿") ?? []), issue]);
  return (
    <div className="source-issues">
      {[...bySheet.entries()].map(([sheet, entries]) => (
        <Alert
          key={sheet}
          type={entries.some((issue) => issue.severity === "error") ? "error" : "warning"}
          showIcon
          message={sheet}
          action={templateAvailable && entries.some((issue) => issue.code === "NO_FORMAT_COLUMN") ? (
            <Button type="primary" danger icon={<DownloadOutlined />} href="/api/boost/input-template">下载标准模板</Button>
          ) : undefined}
          description={
            <ul>
              {entries.map((issue, index) => (
                <li key={index}>
                  {issue.cell && <Tag color={issue.severity === "error" ? "red" : "orange"}>{issue.cell}</Tag>}
                  {issue.message}
                </li>
              ))}
            </ul>
          }
        />
      ))}
    </div>
  );
}

export default function SourceFileStep({ project, config, onChanged }: { project: BoostProject; config: BoostConfig; onChanged: (source: SourceFile) => void }) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<{ percent: number; stage: "uploading" | "processing" }>();
  const source = useQuery({
    queryKey: ["boost-source-file", project.id],
    queryFn: () => api<SourceFile | null>(`/api/boost/projects/${project.id}/source-file`)
  });

  async function upload(file: File) {
    const body = new FormData();
    body.append("file", file);
    setProgress({ percent: 0, stage: "uploading" });
    try {
      const result = await uploadWithProgress<SourceFile>(`/api/boost/projects/${project.id}/source-file`, body, (percent, stage) => setProgress({ percent, stage }));
      queryClient.setQueryData(["boost-source-file", project.id], result);
      queryClient.invalidateQueries({ queryKey: ["boost-preflight", project.id] });
      onChanged(result);
      if (result.status === "parsed") message.success(result.warning_count ? `解析完成，有 ${result.warning_count} 条提醒` : "解析完成");
      else message.error(`分类表有 ${result.error_count} 个错误，请修正后重新上传`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      setProgress(undefined);
    }
  }

  const current = source.data;
  return (
    <Card className="workspace-card" bordered={false}>
      <div className="section-heading">
        <div><Title level={3}>测试项分类表</Title><Text type="secondary">每个工作表生成一个 5.x 章节；A 列为三级标题，J 列「格式」决定标题、列表、表格和注意事项。</Text></div>
      </div>
      {config.input_template_available && (
        <div className="template-banner">
          <div className="template-banner-text">
            <FileTextOutlined className="template-banner-icon" />
            <div>
              <h4>请先下载标准模板，按模板里的「填写说明」填写后再上传</h4>
              <p>没有「格式」列的旧版表格无法识别标题、列表和表格，会被拒绝上传。模板已包含完整的章节结构，只需要修改内容即可。</p>
            </div>
          </div>
          <Button type="primary" size="large" icon={<DownloadOutlined />} href="/api/boost/input-template">下载标准模板</Button>
        </div>
      )}
      <Upload.Dragger
        accept=".xlsx"
        showUploadList={false}
        disabled={Boolean(progress)}
        beforeUpload={(file) => { void upload(file); return false; }}
      >
        <p className="ant-upload-drag-icon"><CloudUploadOutlined /></p>
        <p className="ant-upload-text">{current ? "拖入新的分类表以替换当前版本" : "拖入或点击上传测试项分类表（.xlsx）"}</p>
        <p className="ant-upload-hint">请上传按标准模板填写的 .xlsx；上传后立即解析，问题会定位到具体工作表和单元格。</p>
      </Upload.Dragger>
      {progress && <Progress percent={progress.stage === "processing" ? 100 : progress.percent} status="active" format={() => (progress.stage === "processing" ? "解析中" : `${progress.percent}%`)} />}
      {source.isLoading ? <Skeleton active /> : current && (
        <div className="source-current">
          <Descriptions
            size="small"
            column={{ xs: 1, md: 3 }}
            items={[
              { key: "file", label: "文件", children: <Space><FileExcelOutlined /><a href={`/api/boost/source-files/${current.id}/original`}>{current.original_filename}</a></Space> },
              { key: "time", label: "上传时间", children: formatLocalDateTime(current.created_at ?? undefined) },
              { key: "status", label: "状态", children: current.status === "parsed" ? <Tag color="success">可生成</Tag> : <Tag color="error">有错误</Tag> },
              { key: "chapters", label: "章节", children: current.chapter_count ?? 0 },
              { key: "tables", label: "表格", children: current.table_count ?? 0 },
              { key: "images", label: "图片", children: current.image_count ?? 0 }
            ]}
          />
          <IssueList issues={current.issues} templateAvailable={config.input_template_available} />
          {current.document && <SourcePreview document={current.document} />}
        </div>
      )}
    </Card>
  );
}
