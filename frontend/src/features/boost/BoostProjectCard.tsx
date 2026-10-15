import { FileExcelOutlined } from "@ant-design/icons";
import { Card, Space, Tag, Typography } from "antd";
import type { BoostProject } from "./types";

const { Title, Paragraph } = Typography;

export default function BoostProjectCard({ project, onOpen }: { project: BoostProject; onOpen: (project: BoostProject) => void }) {
  const source = project.source_file;
  return (
    <Card className="project-card" hoverable onClick={() => onOpen(project)}>
      <div className="project-card-head">
        <div className="project-icon"><FileExcelOutlined /></div>
        <Space size={4}><Tag color="purple">升压一体机</Tag><Tag color={project.status === "active" ? "green" : "default"}>{project.status === "active" ? "进行中" : project.status}</Tag></Space>
      </div>
      <Title level={4}>{project.name}</Title>
      <Paragraph ellipsis={{ rows: 2 }}>{project.description || "尚未填写项目说明"}</Paragraph>
      <div className="project-stats">
        <span><b>{source?.chapter_count ?? 0}</b> 章节</span>
        <span><b>{source?.image_count ?? 0}</b> 图片</span>
        <span>{source ? (source.status === "parsed" ? "分类表可生成" : "分类表有错误") : "未上传分类表"}</span>
      </div>
    </Card>
  );
}
