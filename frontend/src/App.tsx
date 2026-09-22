import {
  ArrowLeftOutlined,
  FileWordOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  UserAddOutlined
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App as AntApp,
  Avatar,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Layout,
  List,
  Modal,
  Row,
  Segmented,
  Skeleton,
  Space,
  Spin,
  Tag,
  Typography
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, setCsrfToken } from "./api";
import BrandLogo from "./components/BrandLogo";
import GenerationPanel from "./features/generation/GenerationPanel";
import PhotoWorkspace from "./features/photos/PhotoWorkspace";
import TestSelection from "./features/test-selection/TestSelection";
import type { Project, TreeItem, User } from "./types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

function flatten(items: TreeItem[]): TreeItem[] {
  return items.flatMap((item) => [item, ...flatten(item.children)]);
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const { message } = AntApp.useApp();
  const [busy, setBusy] = useState(false);
  async function submit(values: { username: string; password: string }) {
    setBusy(true);
    try {
      const user = await api<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setCsrfToken(user.csrf_token);
      onLogin(user);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-brand">
        <BrandLogo />
        <Title>把测试资料，变成可交付的 Word SOP</Title>
        <div className="login-points">
          <span><SafetyCertificateOutlined /> 原始模板结构受保护</span>
          <span><ThunderboltOutlined /> 图片自动旋转与排版</span>
          <span><FileWordOutlined /> 生成后仍可继续编辑</span>
        </div>
      </div>
      <Card className="login-card" bordered={false}>
        <Text type="secondary">欢迎回来</Text>
        <Title level={2}>登录 SOP 工作台</Title>
        <Form layout="vertical" onFinish={submit} initialValues={{ username: "admin" }} size="large">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={busy} block>登录</Button>
        </Form>
      </Card>
    </div>
  );
}

function ProjectList({ onOpen }: { onOpen: (project: Project) => void }) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const create = useMutation({
    mutationFn: (values: { name: string; description: string }) =>
      api<Project>("/api/projects", { method: "POST", body: JSON.stringify(values) }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setModalOpen(false);
      form.resetFields();
      onOpen(project);
    },
    onError: (error) => message.error(error.message)
  });
  return (
    <main className="page-shell">
      <section className="hero-row">
        <div>
          <Text className="eyebrow">PROJECT WORKSPACE</Text>
          <Title>测试 SOP 项目</Title>
          <Paragraph>从业务选择到照片排版，保持每一次生成都可追溯、可复现。</Paragraph>
        </div>
        <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建项目</Button>
      </section>
      {projects.isLoading ? <Skeleton active /> : projects.data?.length ? (
        <Row gutter={[18, 18]}>
          {projects.data.map((project) => (
            <Col xs={24} lg={12} xl={8} key={project.id}>
              <Card className="project-card" hoverable onClick={() => onOpen(project)}>
                <div className="project-card-head"><div className="project-icon"><FolderOpenOutlined /></div><Tag color={project.status === "active" ? "green" : "default"}>{project.status === "active" ? "进行中" : project.status}</Tag></div>
                <Title level={4}>{project.name}</Title>
                <Paragraph ellipsis={{ rows: 2 }}>{project.description || "尚未填写项目说明"}</Paragraph>
                <div className="project-stats"><span><b>{project.selected_test_item_ids.length}</b> 测试项</span><span><b>{project.photo_count}</b> 照片</span><span>版本 {project.document_version}</span></div>
              </Card>
            </Col>
          ))}
        </Row>
      ) : <Empty description="还没有 SOP 项目" />}
      <Modal title="新建 SOP 项目" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null}>
        <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)}>
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}><Input placeholder="例如：125kW 液冷户外柜型式测试" /></Form.Item>
          <Form.Item name="description" label="项目说明"><Input.TextArea rows={4} placeholder="说明产品、使用场景和本次测试差异" /></Form.Item>
          <Button type="primary" htmlType="submit" loading={create.isPending} block>创建并进入</Button>
        </Form>
      </Modal>
    </main>
  );
}

function BasicInfo({ project, onSaved }: { project: Project; onSaved: (project: Project) => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm();
  useEffect(() => form.setFieldsValue(project), [form, project]);
  const save = useMutation({
    mutationFn: (values: Record<string, string>) => api<Project>(`/api/projects/${project.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...values, revision: project.revision })
    }),
    onSuccess: (value) => { message.success("基础信息已保存"); onSaved(value); },
    onError: (error) => message.error(error.message)
  });
  return (
    <Card className="workspace-card" bordered={false}>
      <div className="section-heading"><div><Title level={3}>基础信息</Title><Text type="secondary">这些字段将写入封面、审批信息和样品信息表。</Text></div><Tag>自动映射 Word</Tag></div>
      <Form form={form} layout="vertical" onFinish={(values) => save.mutate(values)}>
        <Row gutter={18}>
          <Col xs={24} md={12}><Form.Item name="name" label="项目名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="document_title" label="文档名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="document_number" label="文档编号"><Input /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="document_version" label="版本"><Input /></Form.Item></Col>
          <Col xs={24} md={8}><Form.Item name="product_phase" label="产品阶段"><Input /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="test_period" label="测试时间"><Input placeholder="2026-09-01 至 2026-09-05" /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="test_location" label="测试地点"><Input /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="testers" label="测试人员"><Input /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="product_model" label="产品型号"><Input /></Form.Item></Col>
          <Col xs={24} md={6}><Form.Item name="product_serial_no" label="产品序列号"><Input /></Form.Item></Col>
          <Col span={24}><Form.Item name="description" label="项目描述"><Input.TextArea rows={3} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="product_info" label="产品信息（用于 AI 建议）"><Input.TextArea rows={4} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="project_differences" label="项目差异（用于 AI 建议）"><Input.TextArea rows={4} /></Form.Item></Col>
        </Row>
        <Button type="primary" htmlType="submit" loading={save.isPending}>保存基础信息</Button>
      </Form>
    </Card>
  );
}

function Workspace({ initial, onBack, isAdmin }: { initial: Project; onBack: () => void; isAdmin: boolean }) {
  const [project, setProject] = useState(initial);
  const [step, setStep] = useState("basic");
  const selectionFlushRef = useRef<(() => Promise<boolean>) | null>(null);
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<{ items: TreeItem[] }>("/api/templates/1/test-items") });
  const flat = useMemo(() => flatten(catalog.data?.items ?? []), [catalog.data]);
  const selectedLeaves = flat.filter((item) => item.node_type === "LEAF" && project.selected_test_item_ids.includes(item.id));
  const steps = [
    { value: "basic", label: "01 基础信息" },
    { value: "tests", label: "02 测试项目" },
    { value: "photos", label: "03 测试资料" },
    { value: "generate", label: "04 生成文档" }
  ];
  async function changeStep(value: string) {
    if (step === "tests" && value !== "tests" && selectionFlushRef.current) {
      const saved = await selectionFlushRef.current();
      if (!saved) return;
    }
    setStep(value);
  }
  return (
    <main className="workspace-shell">
      <div className="workspace-top"><Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack}>返回项目列表</Button><div><Text className="eyebrow">SOP PROJECT</Text><Title level={2}>{project.name}</Title></div><Tag color="green">编辑中 · 已保存</Tag></div>
      <Segmented className="workspace-nav" block options={steps} value={step} onChange={(value) => void changeStep(String(value))} />
      {step === "basic" && <BasicInfo project={project} onSaved={(updated) => { setProject(updated); api(`/api/projects/${project.id}/ai-advice`, { method: "POST" }).catch(() => undefined); }} />}
      {step === "tests" && (catalog.isLoading ? <Skeleton active /> : (
        <TestSelection
          project={project}
          tree={catalog.data?.items ?? []}
          onSaved={(data) => setProject((current) => ({ ...current, ...data }))}
          flushRef={selectionFlushRef}
        />
      ))}
      {step === "photos" && <PhotoWorkspace project={project} leafItems={selectedLeaves} />}
      {step === "generate" && <GenerationPanel project={project} isAdmin={isAdmin} />}
    </main>
  );
}

function UserAdmin({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<Array<{ id: string; username: string; display_name: string; role: string }>>("/api/admin/users"), enabled: open });
  const create = useMutation({
    mutationFn: (values: Record<string, string>) => api("/api/admin/users", { method: "POST", body: JSON.stringify({ ...values, role: "user" }) }),
    onSuccess: () => { form.resetFields(); queryClient.invalidateQueries({ queryKey: ["admin-users"] }); message.success("账号已创建"); },
    onError: (error) => message.error(error.message)
  });
  return (
    <Modal title="本地账号管理" open={open} onCancel={onClose} footer={null}>
      <List size="small" loading={users.isLoading} dataSource={users.data ?? []} renderItem={(item) => <List.Item extra={<Tag>{item.role}</Tag>}><List.Item.Meta avatar={<Avatar>{item.display_name.slice(0, 1)}</Avatar>} title={item.display_name} description={item.username} /></List.Item>} />
      <Title level={5}>创建普通用户</Title>
      <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)}>
        <Row gutter={12}><Col span={12}><Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={12}><Form.Item name="display_name" label="显示名" rules={[{ required: true }]}><Input /></Form.Item></Col></Row>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 10 }]}><Input.Password /></Form.Item>
        <Button type="primary" htmlType="submit" loading={create.isPending}>创建账号</Button>
      </Form>
    </Modal>
  );
}

function AppContent() {
  const [user, setUser] = useState<User>();
  const [checking, setChecking] = useState(true);
  const [activeProject, setActiveProject] = useState<Project>();
  const [userModal, setUserModal] = useState(false);
  useEffect(() => {
    api<User>("/api/auth/me")
      .then((value) => { setCsrfToken(value.csrf_token); setUser(value); })
      .catch((error) => { if (!(error instanceof ApiError) || error.status !== 401) console.error(error); })
      .finally(() => setChecking(false));
  }, []);
  if (checking) return <div className="center-screen"><Spin size="large" /></div>;
  if (!user) return <Login onLogin={setUser} />;
  async function logout() { await api("/api/auth/logout", { method: "POST" }); setCsrfToken(); setUser(undefined); }
  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <div className="header-brand"><BrandLogo compact /><div><b>SOP 智能生成</b><small>DOCUMENT ENGINE</small></div></div>
        <Space><Text>你好，{user.display_name}</Text>{user.role === "admin" && <Button type="text" icon={<UserAddOutlined />} onClick={() => setUserModal(true)}>账号</Button>}<Button type="text" icon={<LogoutOutlined />} onClick={logout}>退出</Button></Space>
      </Header>
      <Content>{activeProject ? <Workspace initial={activeProject} onBack={() => setActiveProject(undefined)} isAdmin={user.role === "admin"} /> : <ProjectList onOpen={setActiveProject} />}</Content>
      <UserAdmin open={userModal} onClose={() => setUserModal(false)} />
    </Layout>
  );
}

export default function App() {
  return <AntApp><AppContent /></AntApp>;
}
