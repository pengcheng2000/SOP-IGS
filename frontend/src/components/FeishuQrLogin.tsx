import { Button, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api";

const SDK_URL = "https://lf-package-cn.feishucdn.com/obj/feishu-static/lark/passport/qrcode/LarkSSOSDKWebQRCode-1.0.3.js";
const CONTAINER_ID = "feishu_qrcode_container";

type QRLoginInstance = {
  matchOrigin: (origin: string) => boolean;
  matchData: (data: unknown) => boolean;
};

declare global {
  interface Window {
    QRLogin?: (options: { id: string; goto: string; width: string; height: string; style?: string }) => QRLoginInstance;
  }
}

let sdkPromise: Promise<void> | undefined;

function loadSdk(): Promise<void> {
  if (window.QRLogin) return Promise.resolve();
  sdkPromise ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.onload = () => (window.QRLogin ? resolve() : reject(new Error("QRLogin missing")));
    script.onerror = () => {
      sdkPromise = undefined;
      script.remove();
      reject(new Error("正泰飞讯扫码组件加载失败"));
    };
    document.head.appendChild(script);
  });
  return sdkPromise;
}

export default function FeishuQrLogin() {
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [round, setRound] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let onMessage: ((event: MessageEvent) => void) | undefined;
    const container = document.getElementById(CONTAINER_ID);
    setStatus("loading");
    Promise.all([api<{ goto: string; refresh_seconds: number }>("/api/auth/feishu/qr"), loadSdk()])
      .then(([{ goto, refresh_seconds }]) => {
        if (cancelled || !container || !window.QRLogin) return;
        container.innerHTML = "";
        const qr = window.QRLogin({
          id: CONTAINER_ID,
          goto,
          width: "260",
          height: "290",
          style: "width:260px;height:290px;border:none;background:transparent;"
        });
        onMessage = (event: MessageEvent) => {
          if (qr.matchOrigin(event.origin) && qr.matchData(event.data)) {
            const tmpCode = (event.data as { tmp_code: string }).tmp_code;
            window.location.href = `${goto}&tmp_code=${encodeURIComponent(tmpCode)}`;
          }
        };
        window.addEventListener("message", onMessage);
        // Re-issue before the server-side state expires so a page left open keeps working.
        timer = window.setTimeout(() => setRound((value) => value + 1), refresh_seconds * 1000);
        setStatus("ready");
      })
      .catch(() => { if (!cancelled) setStatus("failed"); });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (onMessage) window.removeEventListener("message", onMessage);
      if (container) container.innerHTML = "";
    };
  }, [round]);

  return (
    <div className="feishu-qr">
      <div id={CONTAINER_ID} className="feishu-qr-frame" hidden={status === "failed"} />
      {status === "loading" && <div className="feishu-qr-loading"><Spin /></div>}
      {status === "failed" ? (
        <div className="feishu-qr-fallback">
          <Typography.Text type="secondary">二维码加载失败，可能无法访问正泰飞讯 CDN</Typography.Text>
          <Button type="primary" href="/api/auth/feishu/login" block>跳转正泰飞讯授权登录</Button>
          <Button type="link" onClick={() => setRound((value) => value + 1)}>重新加载二维码</Button>
        </div>
      ) : (
        <Typography.Text type="secondary" className="feishu-qr-hint">打开正泰飞讯 App 扫一扫登录</Typography.Text>
      )}
    </div>
  );
}
