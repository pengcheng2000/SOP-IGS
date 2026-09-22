import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#0f766e",
          borderRadius: 10,
          colorBgLayout: "#f3f5f4",
          fontFamily: "Inter, 'Microsoft YaHei', system-ui, sans-serif"
        }
      }}
    >
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </ConfigProvider>
  </React.StrictMode>
);

