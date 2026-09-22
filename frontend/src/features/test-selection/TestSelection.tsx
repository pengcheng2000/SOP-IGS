import { CheckCircleFilled, CloudSyncOutlined, RobotOutlined, WarningFilled } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App as AntApp, Button, Card, Col, List, Row, Space, Spin, Tag, Tree, Typography } from "antd";
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { api } from "../../api";
import type { Project, TreeItem } from "../../types";

const { Title, Text, Paragraph } = Typography;

type Advice = {
  id: string;
  status: string;
  error_code?: string;
  response?: {
    recommended_test_items: Array<{ test_item_id: string; confidence: number; reason: string }>;
    warnings: Array<{ code: string; message: string; related_test_item_ids: string[] }>;
    photo_suggestions: Array<{ test_item_id: string; message: string }>;
  };
};

type SelectionResult = {
  revision: number;
  selected_test_item_ids: string[];
  display_numbers: Record<string, string>;
};

function flatten(items: TreeItem[]): TreeItem[] {
  return items.flatMap((item) => [item, ...flatten(item.children)]);
}

function equalIds(left: string[], right: string[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export default function TestSelection({
  project,
  tree,
  onSaved,
  flushRef
}: {
  project: Project;
  tree: TreeItem[];
  onSaved: (data: SelectionResult) => void;
  flushRef: MutableRefObject<(() => Promise<boolean>) | null>;
}) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const all = useMemo(() => flatten(tree), [tree]);
  const leaves = useMemo(
    () => new Set(all.filter((item) => item.node_type === "LEAF").map((item) => item.id)),
    [all]
  );
  const [draft, setDraft] = useState(project.selected_test_item_ids);
  const [saveState, setSaveState] = useState<"saved" | "dirty" | "saving" | "error">("saved");
  const revisionRef = useRef(project.revision);
  const draftRef = useRef(draft);
  const timerRef = useRef<number | undefined>(undefined);
  const queueRef = useRef<Promise<boolean>>(Promise.resolve(true));

  useEffect(() => {
    revisionRef.current = project.revision;
  }, [project.revision]);
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);
  useEffect(() => () => window.clearTimeout(timerRef.current), []);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (saveState === "dirty" || saveState === "saving" || saveState === "error") {
        event.preventDefault();
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [saveState]);

  const advice = useQuery<Advice>({
    queryKey: ["advice", project.id],
    queryFn: () => api(`/api/projects/${project.id}/ai-advice`),
    retry: false,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 1500 : false)
  });

  function persist(ids: string[]): Promise<boolean> {
    const snapshot = [...ids];
    queueRef.current = queueRef.current
      .catch(() => false)
      .then(async () => {
        setSaveState("saving");
        try {
          const result = await api<SelectionResult>(`/api/projects/${project.id}/selection`, {
            method: "PUT",
            body: JSON.stringify({
              revision: revisionRef.current,
              test_item_ids: snapshot,
              source: "manual"
            })
          });
          revisionRef.current = result.revision;
          onSaved(result);
          if (equalIds(draftRef.current, snapshot)) setSaveState("saved");
          return true;
        } catch (error) {
          setSaveState("error");
          message.error(error instanceof Error ? error.message : "测试项目保存失败");
          return false;
        }
      });
    return queueRef.current;
  }

  function schedule(ids: string[]) {
    setDraft(ids);
    setSaveState("dirty");
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => persist(ids), 350);
  }

  async function flushPending() {
    window.clearTimeout(timerRef.current);
    return saveState === "saved" ? true : persist(draftRef.current);
  }
  flushRef.current = flushPending;
  useEffect(() => () => { flushRef.current = null; }, [flushRef]);

  const requestAdvice = useMutation({
    mutationFn: () => api<Advice>(`/api/projects/${project.id}/ai-advice`, { method: "POST" }),
    onSuccess: () => {
      message.success("AI 正在分析项目");
      queryClient.invalidateQueries({ queryKey: ["advice", project.id] });
    },
    onError: (error) => message.warning(error.message)
  });
  const recommended = new Map(
    advice.data?.response?.recommended_test_items.map((item) => [item.test_item_id, item]) ?? []
  );
  const treeData = tree.map(function convert(item): any {
    const recommendation = recommended.get(item.id);
    return {
      key: item.id,
      title: (
        <div className="tree-title">
          <span>{project.display_numbers[item.id] ? `${project.display_numbers[item.id]} ` : ""}{item.title}</span>
          {recommendation && <Tag color="cyan">AI {Math.round(recommendation.confidence * 100)}%</Tag>}
        </div>
      ),
      children: item.children.map(convert)
    };
  });

  function acceptAdvice() {
    const ids = new Set(draftRef.current);
    recommended.forEach((_value, key) => ids.add(key));
    schedule([...ids]);
  }

  const saveIndicator = {
    saved: <Tag color="success" icon={<CheckCircleFilled />}>已自动保存</Tag>,
    dirty: <Tag icon={<CloudSyncOutlined />}>等待保存</Tag>,
    saving: <Tag color="processing" icon={<CloudSyncOutlined />}>保存中</Tag>,
    error: <Tag color="error" icon={<WarningFilled />}>保存失败</Tag>
  }[saveState];

  return (
    <>
      <Row gutter={20}>
        <Col xs={24} lg={15}>
          <Card className="workspace-card" bordered={false}>
            <div className="section-heading">
              <div><Title level={3}>选择测试项目</Title><Text type="secondary">选择会自动保存；父节点会联动全部子项。</Text></div>
              <Space>
                {saveIndicator}
                {saveState === "error" && <Button type="link" size="small" onClick={() => persist(draftRef.current)}>重试</Button>}
                <Tag>{draft.length} 个叶子项目</Tag>
              </Space>
            </div>
            <Tree
              className="test-tree"
              checkable
              defaultExpandAll
              checkedKeys={draft}
              treeData={treeData}
              onCheck={(keys) => schedule((keys as React.Key[]).map(String).filter((key) => leaves.has(key)))}
            />
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card className="ai-card" bordered={false}>
            <div className="ai-orb"><RobotOutlined /></div>
            <Title level={4} className="ai-title">AI 辅助建议</Title>
            <Paragraph className="ai-body">AI 只根据项目描述提醒可能遗漏的测试项，不会自动决定最终 SOP。</Paragraph>
            {advice.data?.status === "succeeded" ? (
              <>
                <List
                  size="small"
                  dataSource={advice.data.response?.recommended_test_items ?? []}
                  renderItem={(item) => (
                    <List.Item>
                      <div><Text strong className="ai-title">{all.find((node) => node.id === item.test_item_id)?.title}</Text><br /><Text className="ai-muted">{item.reason}</Text></div>
                    </List.Item>
                  )}
                />
                <Button type="primary" ghost onClick={acceptAdvice} disabled={!recommended.size}>采纳全部推荐</Button>
              </>
            ) : advice.data?.status === "pending" ? (
              <Spin tip="AI 正在分析" />
            ) : (
              <Alert className="ai-alert" type="info" showIcon message="AI 建议暂时不可用" description="不影响手工选择和 DOCX 生成。" />
            )}
            <Button icon={<RobotOutlined />} loading={requestAdvice.isPending} onClick={() => requestAdvice.mutate()} block>刷新 AI 建议</Button>
          </Card>
        </Col>
      </Row>
    </>
  );
}
