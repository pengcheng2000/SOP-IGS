import {
  ArrowLeftOutlined,
  FileWordOutlined,
  FolderOpenOutlined,
  KeyOutlined,
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
  Select,
  Skeleton,
  Space,
  Spin,
  Switch,
  Tag,
  Typography
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, setCsrfToken } from "./api";
import BrandLogo from "./components/BrandLogo";
import FeishuQrLogin from "./components/FeishuQrLogin";
import TestPeriodInput from "./components/TestPeriodInput";
import BoostProjectCard from "./features/boost/BoostProjectCard";
import BoostWorkspace, { useBoostConfig } from "./features/boost/BoostWorkspace";
import type { BoostProject } from "./features/boost/types";
import GenerationPanel from "./features/generation/GenerationPanel";
import PhotoWorkspace from "./features/photos/PhotoWorkspace";
import TestSelection from "./features/test-selection/TestSelection";
import type { ManagedUser, Project, TreeItem, User } from "./types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

function flatten(items: TreeItem[]): TreeItem[] {
  return items.flatMap((item) => [item, ...flatten(item.children)]);
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const { message } = AntApp.useApp();
  const [busy, setBusy] = useState(false);
  const [localLogin, setLocalLogin] = useState(false);
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: () => api<{ local: boolean; feishu: boolean }>("/api/auth/providers")
  });
  useEffect(() => {
    const error = new URLSearchParams(window.location.search).get("error");
    if (error) {
      message.error(`正泰飞讯登录失败：${error}`);
      window.history.replaceState({}, document.title, "/");
    }
  }, [message]);
  async function submit(values: { username: string; password: string }) {
    setBusy(true);
    try {
      const user = await api<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setCsrfToken(user.csrf_token);
      if (window.location.pathname !== "/") window.history.replaceState({}, document.title, "/");
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
        {providers.isLoading ? <Skeleton active /> : providers.data?.feishu && !localLogin ? (
          <>
            <FeishuQrLogin />
            <Button type="link" size="small" className="login-switch" onClick={() => setLocalLogin(true)}>管理员账号登录</Button>
          </>
        ) : (
          <>
            <Form layout="vertical" onFinish={submit} size="large">
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input autoComplete="username" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                <Input.Password autoComplete="current-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={busy} block>登录</Button>
            </Form>
            {providers.data?.feishu && <Button type="link" size="small" className="login-switch" onClick={() => setLocalLogin(false)}>返回正泰飞讯扫码登录</Button>}
          </>
        )}
      </Card>
    </div>
  );
}

type ProductKind = "cabinet" | "boost";

function ProjectList({ onOpen, onOpenBoost }: { onOpen: (project: Project) => void; onOpenBoost: (project: BoostProject) => void }) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [productKind, setProductKind] = useState<ProductKind>("cabinet");
  const [form] = Form.useForm();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/api/projects") });
  const boostProjects = useQuery({ queryKey: ["boost-projects"], queryFn: () => api<BoostProject[]>("/api/boost/projects") });
  const boostConfig = useBoostConfig();
  const listItems = [
    ...(projects.data ?? []).map((project) => ({ kind: "cabinet" as const, project, updatedAt: project.updated_at })),
    ...(boostProjects.data ?? []).map((project) => ({ kind: "boost" as const, project, updatedAt: project.updated_at }))
  ].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  const createBoost = useMutation({
    mutationFn: (values: { name: string; description: string }) =>
      api<BoostProject>("/api/boost/projects", { method: "POST", body: JSON.stringify(values) }),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["boost-projects"] });
      setModalOpen(false);
      form.resetFields();
      onOpenBoost(project);
    },
    onError: (error) => message.error(error.message)
  });
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
      {projects.isLoading || boostProjects.isLoading ? <Skeleton active /> : listItems.length ? (
        <Row gutter={[18, 18]}>
          {listItems.map((item) => item.kind === "boost" ? (
            <Col xs={24} lg={12} xl={8} key={item.project.id}><BoostProjectCard project={item.project} onOpen={onOpenBoost} /></Col>
          ) : (
            <Col xs={24} lg={12} xl={8} key={item.project.id}>
              <Card className="project-card" hoverable onClick={() => onOpen(item.project)}>
                <div className="project-card-head"><div className="project-icon"><FolderOpenOutlined /></div><Space size={4}><Tag color="blue">工商业柜</Tag><Tag color={item.project.status === "active" ? "green" : "default"}>{item.project.status === "active" ? "进行中" : item.project.status}</Tag></Space></div>
                <Title level={4}>{item.project.name}</Title>
                <Paragraph ellipsis={{ rows: 2 }}>{item.project.description || "尚未填写项目说明"}</Paragraph>
                <div className="project-stats"><span><b>{item.project.selected_test_item_ids.length}</b> 测试项</span><span><b>{item.project.photo_count}</b> 照片</span><span>版本 {item.project.document_version}</span></div>
              </Card>
            </Col>
          ))}
        </Row>
      ) : <Empty description="还没有 SOP 项目" />}
      <Modal title="新建 SOP 项目" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null}>
        <Form form={form} layout="vertical" onFinish={(values) => (productKind === "boost" ? createBoost : create).mutate(values)}>
          <Form.Item label="产品类型">
            <Segmented
              block
              value={productKind}
              onChange={(value) => setProductKind(value as ProductKind)}
              options={[{ value: "cabinet", label: "工商业柜" }, { value: "boost", label: "升压一体机", disabled: !boostConfig.data?.available }]}
            />
          </Form.Item>
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: "请输入项目名称" }]}><Input placeholder={productKind === "boost" ? "例如：某项目站点升压一体机测试需求" : "例如：125kW 液冷户外柜型式测试"} /></Form.Item>
          <Form.Item name="description" label="项目说明"><Input.TextArea rows={4} placeholder="说明产品、使用场景和本次测试差异" /></Form.Item>
          <Button type="primary" htmlType="submit" loading={create.isPending || createBoost.isPending} block>创建并进入</Button>
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
          <Col xs={24} md={12}><Form.Item name="test_period" label="测试时间"><TestPeriodInput /></Form.Item></Col>
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

function UserAdmin({ open, onClose, currentUserId }: { open: boolean; onClose: () => void; currentUserId: string }) {
  const { message } = AntApp.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api<ManagedUser[]>("/api/admin/users"), enabled: open });
  const create = useMutation({
    mutationFn: (values: Record<string, string>) => api("/api/admin/users", { method: "POST", body: JSON.stringify({ ...values, role: "user" }) }),
    onSuccess: () => { form.resetFields(); queryClient.invalidateQueries({ queryKey: ["admin-users"] }); message.success("账号已创建"); },
    onError: (error) => message.error(error.message)
  });
  const update = useMutation({
    mutationFn: ({ id, ...values }: { id: string; role?: string; is_active?: boolean }) =>
      api<ManagedUser>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(values) }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["admin-users"] }); message.success("权限已更新"); },
    onError: (error) => message.error(error.message)
  });
  return (
    <Modal title="账号与权限管理" open={open} onCancel={onClose} footer={null} width={640}>
      <List
        size="small"
        loading={users.isLoading}
        dataSource={users.data ?? []}
        renderItem={(item) => {
          const self = item.id === currentUserId;
          return (
            <List.Item
              extra={
                <Space>
                  <Select
                    size="small"
                    value={item.role}
                    disabled={self || update.isPending}
                    style={{ width: 96 }}
                    options={[{ value: "user", label: "普通用户" }, { value: "admin", label: "管理员" }]}
                    onChange={(role) => update.mutate({ id: item.id, role })}
                  />
                  <Switch
                    checked={item.is_active}
                    disabled={self || update.isPending}
                    checkedChildren="启用"
                    unCheckedChildren="停用"
                    onChange={(isActive) => update.mutate({ id: item.id, is_active: isActive })}
                  />
                </Space>
              }
            >
              <List.Item.Meta
                avatar={<Avatar>{item.display_name.slice(0, 1)}</Avatar>}
                title={<Space size={6}>{item.display_name}{item.providers.map((provider) => <Tag key={provider} color={provider === "feishu" ? "blue" : "default"}>{provider === "feishu" ? "正泰飞讯" : "本地"}</Tag>)}</Space>}
                description={item.username ?? "正泰飞讯账号"}
              />
            </List.Item>
          );
        }}
      />
      <Title level={5}>创建本地普通用户</Title>
      <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)}>
        <Row gutter={12}><Col span={12}><Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item></Col><Col span={12}><Form.Item name="display_name" label="显示名" rules={[{ required: true }]}><Input /></Form.Item></Col></Row>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 10 }]}><Input.Password /></Form.Item>
        <Button type="primary" htmlType="submit" loading={create.isPending}>创建账号</Button>
      </Form>
    </Modal>
  );
}

function ChangePassword({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = AntApp.useApp();
  const [form] = Form.useForm();
  const change = useMutation({
    mutationFn: (values: { current_password: string; new_password: string }) =>
      api("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password })
      }),
    onSuccess: () => { form.resetFields(); message.success("密码已修改，其他设备上的登录已失效"); onClose(); },
    onError: (error) => message.error(error.message)
  });
  return (
    <Modal title="修改密码" open={open} onCancel={() => { form.resetFields(); onClose(); }} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={(values) => change.mutate(values)}>
        <Form.Item name="current_password" label="当前密码" rules={[{ required: true, message: "请输入当前密码" }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: "请输入新密码" }, { min: 10, message: "新密码至少 10 位" }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label="确认新密码"
          dependencies={["new_password"]}
          rules={[
            { required: true, message: "请再次输入新密码" },
            ({ getFieldValue }) => ({
              validator: (_rule, value) => !value || value === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("两次输入的新密码不一致"))
            })
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={change.isPending} block>确认修改</Button>
      </Form>
    </Modal>
  );
}

function AppContent() {
  const [user, setUser] = useState<User>();
  const [checking, setChecking] = useState(true);
  const [activeProject, setActiveProject] = useState<Project>();
  const [activeBoostProject, setActiveBoostProject] = useState<BoostProject>();
  const [userModal, setUserModal] = useState(false);
  const [passwordModal, setPasswordModal] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => {
    api<User>("/api/auth/me")
      .then((value) => { setCsrfToken(value.csrf_token); setUser(value); })
      .catch((error) => { if (!(error instanceof ApiError) || error.status !== 401) console.error(error); })
      .finally(() => setChecking(false));
  }, []);
  if (checking) return <div className="center-screen"><Spin size="large" /></div>;
  if (!user) return <Login onLogin={setUser} />;
  async function logout() { await api("/api/auth/logout", { method: "POST" }); setCsrfToken(); setActiveProject(undefined); setActiveBoostProject(undefined); queryClient.clear(); setUser(undefined); }
  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <div className="header-brand"><BrandLogo compact /><div><b>SOP 智能生成</b><small>DOCUMENT ENGINE</small></div></div>
        <Space><Text>你好，{user.display_name}</Text>{user.role === "admin" && <Button type="text" icon={<UserAddOutlined />} onClick={() => setUserModal(true)}>账号</Button>}{user.can_change_password && <Button type="text" icon={<KeyOutlined />} onClick={() => setPasswordModal(true)}>修改密码</Button>}<Button type="text" icon={<LogoutOutlined />} onClick={logout}>退出</Button></Space>
      </Header>
      <Content>
        {activeProject ? <Workspace initial={activeProject} onBack={() => setActiveProject(undefined)} isAdmin={user.role === "admin"} />
          : activeBoostProject ? <BoostWorkspace initial={activeBoostProject} onBack={() => setActiveBoostProject(undefined)} isAdmin={user.role === "admin"} />
            : <ProjectList onOpen={setActiveProject} onOpenBoost={setActiveBoostProject} />}
      </Content>
      <UserAdmin open={userModal} onClose={() => setUserModal(false)} currentUserId={user.id} />
      <ChangePassword open={passwordModal} onClose={() => setPasswordModal(false)} />
    </Layout>
  );
}

export default function App() {
  return <AntApp><AppContent /></AntApp>;
}
