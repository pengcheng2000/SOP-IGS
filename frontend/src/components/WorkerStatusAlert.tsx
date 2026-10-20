import { useQuery } from "@tanstack/react-query";
import { Alert } from "antd";
import { api } from "../api";
import { formatLocalDateTime } from "../time";

/** Warns under the generation panel when no Word worker has reported in recently. */
export default function WorkerStatusAlert() {
  const status = useQuery({
    queryKey: ["worker-status"],
    queryFn: () => api<{ online: boolean; last_seen: string | null }>("/api/worker/status"),
    refetchInterval: 5000
  });
  if (!status.isSuccess || status.data.online) return null;
  return (
    <Alert
      className="worker-offline-alert"
      type="error"
      showIcon
      message="Word Worker 未启动，提交的生成任务将一直排队"
      description={
        <>
          请在已登录并已激活 Microsoft Word 的 Windows 账号下启动 Worker：在项目目录运行 <code>.\.venv\Scripts\python -m app.worker.word_worker</code>。
          {status.data.last_seen ? `最后一次收到 Worker 心跳：${formatLocalDateTime(status.data.last_seen)}。` : "尚未收到过 Worker 心跳。"}
        </>
      }
    />
  );
}
