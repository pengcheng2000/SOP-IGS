import { ArrowLeftOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Segmented, Skeleton, Tag, Typography } from "antd";
import { useState } from "react";
import { api } from "../../api";
import "./boost.css";
import BoostBasicInfo from "./BoostBasicInfo";
import BoostGenerationPanel from "./BoostGenerationPanel";
import SourceFileStep from "./SourceFileStep";
import type { BoostConfig, BoostProject } from "./types";

const { Title, Text } = Typography;

const STEPS = [
  { value: "basic", label: "01 基础信息" },
  { value: "source", label: "02 测试项分类表" },
  { value: "generate", label: "03 生成文档" }
];

export function useBoostConfig() {
  return useQuery({ queryKey: ["boost-config"], queryFn: () => api<BoostConfig>("/api/boost/config"), staleTime: 60_000 });
}

export default function BoostWorkspace({ initial, onBack, isAdmin }: { initial: BoostProject; onBack: () => void; isAdmin: boolean }) {
  const [project, setProject] = useState(initial);
  const [step, setStep] = useState("basic");
  const config = useBoostConfig();
  return (
    <main className="workspace-shell">
      <div className="workspace-top">
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack}>返回项目列表</Button>
        <div><Text className="eyebrow">升压一体机 · 测试需求</Text><Title level={2}>{project.name}</Title></div>
        <Tag color="purple">升压一体机</Tag>
      </div>
      <Segmented className="workspace-nav" block options={STEPS} value={step} onChange={(value) => setStep(String(value))} />
      {config.isLoading ? <Skeleton active /> : !config.data?.available ? (
        <Alert type="error" showIcon message="升压一体机母版尚未部署或校验失败，请联系管理员" />
      ) : (
        <>
          {step === "basic" && <BoostBasicInfo project={project} config={config.data} onSaved={setProject} />}
          {step === "source" && (
            <SourceFileStep project={project} config={config.data} onChanged={(source) => setProject((current) => ({ ...current, source_file: source }))} />
          )}
          {step === "generate" && <BoostGenerationPanel project={project} isAdmin={isAdmin} />}
        </>
      )}
    </main>
  );
}
