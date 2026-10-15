import { useMutation } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Col, DatePicker, Form, Input, Popover, Row, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect } from "react";
import { api } from "../../api";
import type { BoostConfig, BoostProject } from "./types";

const { Title, Text } = Typography;

type FormValues = Record<string, string | undefined>;

function initialValues(project: BoostProject, config: BoostConfig): FormValues {
  const values: FormValues = { name: project.name, description: project.description };
  for (const field of config.fields) {
    values[field.key] = field.column ? project[field.column] : project.fields[field.key] ?? "";
  }
  return values;
}

export default function BoostBasicInfo({ project, config, onSaved }: { project: BoostProject; config: BoostConfig; onSaved: (project: BoostProject) => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm<FormValues>();
  useEffect(() => form.setFieldsValue(initialValues(project, config)), [form, project, config]);
  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body: Record<string, unknown> = { revision: project.revision, name: values.name, description: values.description ?? "" };
      const fields: Record<string, string> = {};
      for (const field of config.fields) {
        const value = (values[field.key] ?? "").trim();
        if (field.column) body[field.column] = value;
        else fields[field.key] = value;
      }
      body.fields = fields;
      return api<BoostProject>(`/api/boost/projects/${project.id}`, { method: "PATCH", body: JSON.stringify(body) });
    },
    onSuccess: (value) => { message.success("基础信息已保存"); onSaved(value); },
    onError: (error) => message.error(error.message)
  });
  const multiline = config.fields.filter((field) => field.multiline);
  const single = config.fields.filter((field) => !field.multiline);
  return (
    <Card className="workspace-card" bordered={false}>
      <div className="section-heading">
        <div><Title level={3}>基础信息</Title><Text type="secondary">这些字段将写入文档标题、适用范围和标题栏。</Text></div>
        <Tag>自动映射 Word</Tag>
      </div>
      <Form form={form} layout="vertical" onFinish={(values) => save.mutate(values)}>
        <Row gutter={18}>
          <Col xs={24} md={12}><Form.Item name="name" label="项目名称（列表显示）" rules={[{ required: true }]}><Input /></Form.Item></Col>
          {single.map((field) => (
            <Col xs={24} md={field.key === "project_name" || field.key === "title_subject" ? 12 : 6} key={field.key}>
              {field.type === "month" ? (
                <Form.Item
                  name={field.key}
                  label={field.label}
                  getValueProps={(value?: string) => ({ value: value ? dayjs(value, "YYYY-MM") : null })}
                  normalize={(value: dayjs.Dayjs | null) => (value ? value.format("YYYY-MM") : "")}
                >
                  <DatePicker picker="month" format="YYYY-MM" placeholder="选择年月" style={{ width: "100%" }} />
                </Form.Item>
              ) : (
                <Form.Item name={field.key} label={field.label} rules={field.required ? [{ required: true, message: `请填写${field.label}` }] : undefined}>
                  <Input placeholder={field.placeholder} />
                </Form.Item>
              )}
            </Col>
          ))}
          {multiline.map((field) => (
            <Col xs={24} md={12} key={field.key}>
              <Form.Item
                name={field.key}
                label={field.label}
                extra={field.fixed_lines?.length ? (
                  <span className="boost-fixed-hint">
                    模板已内置 {field.fixed_lines.length} 条国标参考文献，这里只填项目专属文献。
                    <Popover
                      placement="topLeft"
                      title="模板已有的参考文献"
                      content={<ul className="boost-fixed-list">{field.fixed_lines.map((line) => <li key={line}>{line}</li>)}</ul>}
                    >
                      <a>查看</a>
                    </Popover>
                  </span>
                ) : undefined}
              >
                <Input.TextArea rows={3} placeholder={field.placeholder} />
              </Form.Item>
            </Col>
          ))}
          <Col xs={24} md={12}><Form.Item name="description" label="项目说明"><Input.TextArea rows={3} /></Form.Item></Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={save.isPending}>保存基础信息</Button>
      </Form>
    </Card>
  );
}
