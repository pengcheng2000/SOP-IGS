import { AppstoreOutlined, ArrowLeftOutlined, FileExcelOutlined, FileImageOutlined, RightOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Button, Form, Input, Modal, Tag, Typography } from "antd";
import { useState } from "react";
import { BUSINESSES, DOCUMENTS, type BusinessKind, type DocumentKind } from "../projectKinds";

const { Title, Text } = Typography;

export type NewProjectValues = {
  business: BusinessKind;
  document: DocumentKind;
  name?: string;
  description?: string;
};

type Props = {
  busy: boolean;
  boostAvailable: boolean;
  cabinetPlanAvailable: boolean;
  onCancel: () => void;
  onCreate: (values: NewProjectValues) => void;
};

export default function CreateProjectDialog({ busy, boostAvailable, cabinetPlanAvailable, onCancel, onCreate }: Props) {
  const [stage, setStage] = useState<"business" | "document" | "details">("business");
  const [business, setBusiness] = useState<BusinessKind>("cabinet");
  const [document, setDocument] = useState<DocumentKind>("report");
  const [form] = Form.useForm();
  const businessLabel = BUSINESSES.find(item => item.value === business)!.label;
  const documentLabel = DOCUMENTS.find(item => item.value === document)!.label;
  const isCabinetPlan = document === "plan";

  return (
    <Modal title="新建 SOP 项目" open onCancel={onCancel} footer={null} width={600} closable={!busy} maskClosable={!busy} keyboard={!busy}>
      <div className="project-create-step">
        <Text type="secondary">第 {stage === "business" ? 1 : stage === "document" ? 2 : 3} 步 / 共 3 步</Text>
        <Title level={4}>{stage === "business" ? "选择业务类型" : stage === "document" ? "选择文档类型" : "填写项目信息"}</Title>
      </div>

      {stage !== "business" && (
        <div className="project-create-path" aria-label="当前选择">
          <Button type="link" disabled={busy} onClick={() => setStage("business")}>{businessLabel}</Button>
          {stage === "details" && <><RightOutlined /><Button type="link" disabled={busy} onClick={() => setStage("document")}>{documentLabel}</Button></>}
        </div>
      )}

      {stage === "business" && (
        <div className="project-create-choices" aria-label="业务类型">
          {BUSINESSES.map(item => (
            <button className="project-create-choice" key={item.value} type="button" onClick={() => { setBusiness(item.value); setStage("document"); }}>
              <span className="project-create-choice-icon">{item.value === "cabinet" ? <AppstoreOutlined /> : <ThunderboltOutlined />}</span>
              <span className="project-create-choice-copy"><strong>{item.label}</strong><span>{item.value === "cabinet" ? "工商业储能户外柜相关测试" : "升压一体机相关测试"}</span></span>
              <RightOutlined className="project-create-choice-arrow" />
            </button>
          ))}
        </div>
      )}

      {stage === "document" && (
        <>
          <div className="project-create-choices" aria-label="文档类型">
            {DOCUMENTS.map(item => {
              const supported = BUSINESSES.find(entry => entry.value === business)!.documents.includes(item.value);
              const available = supported && (item.value === "report" || (business === "cabinet" ? cabinetPlanAvailable : boostAvailable));
              return (
                <button className="project-create-choice" key={item.value} type="button" disabled={!available} onClick={() => { setDocument(item.value); setStage("details"); }}>
                  <span className="project-create-choice-icon">{item.value === "report" ? <FileImageOutlined /> : <FileExcelOutlined />}</span>
                  <span className="project-create-choice-copy"><strong>{item.label}</strong><span>{!supported ? "该业务暂未开放测试报告" : !available ? "模板暂不可用，请联系管理员" : item.value === "report" ? "选择测试项目、上传照片，生成测试报告" : "上传编辑好的 Excel，生成测试方案"}</span></span>
                  {!supported ? <Tag>暂不支持</Tag> : !available ? <Tag>暂不可用</Tag> : <RightOutlined className="project-create-choice-arrow" />}
                </button>
              );
            })}
          </div>
          <div className="project-create-actions"><Button icon={<ArrowLeftOutlined />} onClick={() => setStage("business")}>返回选择业务</Button></div>
        </>
      )}

      <Form
        form={form}
        layout="vertical"
        hidden={stage !== "details"}
        onFinish={values => {
          if (stage === "details" && !busy) onCreate({ ...values, business, document });
        }}
      >
        {stage === "details" && <>
          <Form.Item name="name" label={isCabinetPlan ? "项目名称（可选）" : "项目名称"} rules={isCabinetPlan ? [] : [{ required: true, message: "请输入项目名称" }]}>
            <Input disabled={busy} placeholder={isCabinetPlan ? "留空即可，上传后自动读取 Excel 文档标题" : business === "boost" ? "例如：某项目站点升压一体机测试需求" : "例如：125kW 液冷户外柜型式测试"} />
          </Form.Item>
          <Form.Item name="description" label="项目说明"><Input.TextArea disabled={busy} rows={3} placeholder="说明产品、使用场景和本次测试差异" /></Form.Item>
          <div className="project-create-actions">
            <Button disabled={busy} icon={<ArrowLeftOutlined />} onClick={() => setStage("document")}>返回选择文档</Button>
            <Button type="primary" htmlType="submit" loading={busy}>创建并进入</Button>
          </div>
        </>}
      </Form>
    </Modal>
  );
}
