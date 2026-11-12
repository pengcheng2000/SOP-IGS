import { DeleteOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { App as AntApp, Button, Popconfirm } from "antd";
import { api } from "../api";

// Rendered inside a clickable project card: events from the button and its confirm popup must not open the project.
export default function ProjectDeleteButton({ name, path, onDeleted }: { name: string; path: string; onDeleted: () => void }) {
  const { message } = AntApp.useApp();
  const remove = useMutation({
    mutationFn: () => api<void>(path, { method: "DELETE" }),
    onSuccess: () => { message.success("项目已删除"); onDeleted(); },
    onError: (error) => message.error(error.message)
  });
  return (
    <span onClick={(event) => event.stopPropagation()}>
      <Popconfirm
        title="删除项目"
        description={`将永久删除“${name}”及其上传资料、照片和已生成的文档，无法恢复。`}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: remove.isPending }}
        onConfirm={() => remove.mutateAsync().catch(() => undefined)}
      >
        <Button type="text" size="small" danger icon={<DeleteOutlined />}>删除</Button>
      </Popconfirm>
    </span>
  );
}
