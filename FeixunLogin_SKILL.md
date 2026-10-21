---
name: feishu-login
description: 飞书 OAuth 登录集成 skill — 沉淀自两个真实项目（think-meta-v1 零依赖 Node、bom-smart-management Express+tRPC+JWT Cookie），可移植到任意 Node.js 后端 + 任意前端工程。覆盖配置、后端回调三步换 token（app_access_token / user_access_token / user_info）、网页版重定向登录、扫码登录（LarkSSOSDKWebQRCode）、会话创建、open_id 用户自动建档、管理员白名单、反向代理协议还原、错误回跳。触发词："飞书登录"、"feishu login"、"飞书扫码"、"飞书授权"、"Feishu OAuth"、"接入飞书"、"Lark 登录"。
---

# feishu-login · 飞书 OAuth 登录集成

将飞书 OAuth2 授权登录（网页版重定向 + 扫码）集成到 Node.js 后端项目。
本 skill 沉淀自真实项目实践，含可直接套用的参考代码（按你的框架微调）。

## 何时触发

- 需要在 Web 项目中接入飞书登录（重定向或扫码）
- 用户提到"飞书登录 / 飞书扫码 / 飞书授权 / Feishu OAuth / 接入飞书"
- 需要在已有鉴权体系中加入飞书登录通道

## 两种登录形态

| 形态 | 场景 | 实现成本 |
|------|------|----------|
| **网页版重定向**（推荐默认） | 点按钮跳飞书授权页；已登录飞书网页版免扫码直接确认 | 最低，无需引 SDK |
| **扫码登录** | PC 登录页内嵌二维码，飞书 App 扫码 | 需引入 LarkSSOSDKWebQRCode CDN 脚本 |

两种形态最终都走同一个后端 `callback` 路由，用 `code` 换 user_access_token。

## 一、配置

```bash
# .env
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxx
# 可选：命中者登录时授予 admin 角色（逗号分隔 open_id）
FEISHU_ADMIN_OPEN_IDS=
```

- `appId` / `appSecret` 在[飞书开放平台](https://open.feishu.cn/app) → 应用 → 凭证与基础信息获取
- **必做**：应用「安全设置 → 重定向 URL」登记 `${域名}/api/auth/feishu/callback`，否则授权页报 redirect_uri 非法
- 应用需开通「通过 code 获取用户身份」权限（`authen:v1` scope）

## 二、后端核心（Express 版参考实现）

三步换 token，唯一标识用 **`open_id`**（跨应用稳定，不要用 user_id）：

```ts
// routes: GET /api/auth/feishu/url  +  GET /api/auth/feishu/callback?code=xxx
const FEISHU_BASE = "https://open.feishu.cn/open-apis";

// 反向代理下必须用 x-forwarded-proto 还原 https，否则飞书拒绝回调
function resolveProto(req: Request): string {
  const fwd = req.headers["x-forwarded-proto"];
  return typeof fwd === "string" && fwd ? fwd.split(",")[0].trim() : req.protocol || "http";
}
function buildRedirectUri(req: Request): string {
  const host = req.headers["x-forwarded-host"] ?? req.headers.host ?? "localhost";
  return `${resolveProto(req)}://${host}/api/auth/feishu/callback`;
}
function redirectToLogin(res: Response, message: string) {
  res.redirect(302, `/login?error=${encodeURIComponent(message)}`);
}

// 1. 返回授权页 URL
app.get("/api/auth/feishu/url", (req, res) => {
  if (!ENV.feishuAppId || !ENV.feishuAppSecret) {
    res.status(500).json({ error: "FEISHU_APP_ID / FEISHU_APP_SECRET 未配置。" });
    return;
  }
  const redirectUri = encodeURIComponent(buildRedirectUri(req));
  res.json({
    url: `${FEISHU_BASE}/authen/v1/authorize?app_id=${encodeURIComponent(ENV.feishuAppId)}`
       + `&redirect_uri=${redirectUri}&state=feishu_login`,
  });
});

// 2. 回调：三步换 token → 建用户 → 建会话 → 302 回首页
app.get("/api/auth/feishu/callback", async (req, res) => {
  try {
    const code = typeof req.query.code === "string" ? req.query.code : "";
    if (!code) { redirectToLogin(res, "飞书回调缺少授权码 code"); return; }

    // Step 1: app_access_token（内部应用）
    const tokenData = await (await fetch(`${FEISHU_BASE}/auth/v3/app_access_token/internal`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ app_id: ENV.feishuAppId, app_secret: ENV.feishuAppSecret }),
    })).json() as { code: number; msg?: string; app_access_token?: string };
    if (tokenData.code !== 0 || !tokenData.app_access_token)
      throw new Error(tokenData.msg || "获取 app_access_token 失败");

    // Step 2: code 换 user_access_token
    const userTokenData = await (await fetch(`${FEISHU_BASE}/authen/v1/oidc/access_token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Authorization: `Bearer ${tokenData.app_access_token}`,
      },
      body: JSON.stringify({ grant_type: "authorization_code", code }),
    })).json() as { code: number; msg?: string; data?: { access_token?: string } };
    if (userTokenData.code !== 0 || !userTokenData.data?.access_token)
      throw new Error(userTokenData.msg || "获取 user_access_token 失败");

    // Step 3: 用户信息
    const userInfoData = await (await fetch(`${FEISHU_BASE}/authen/v1/user_info`, {
      headers: { Authorization: `Bearer ${userTokenData.data.access_token}` },
    })).json() as { code: number; msg?: string; data?: { open_id?: string; name?: string; email?: string; avatar_url?: string } };
    if (userInfoData.code !== 0 || !userInfoData.data?.open_id)
      throw new Error(userInfoData.msg || "获取飞书用户信息失败");

    const openId = userInfoData.data.open_id as string;
    const isAdmin = ENV.feishuAdminOpenIds.includes(openId);

    // 用户自动建档（首见创建，再登录更新）；role 仅命中名单时传入，避免覆盖既有角色
    await upsertUser({
      openId,
      name: userInfoData.data.name ?? null,
      email: userInfoData.data.email ?? null,
      loginMethod: "feishu",
      lastSignedIn: new Date(),
      ...(isAdmin ? { role: "admin" as const } : {}),
    });

    // 建会话：二选一
    // A. 服务端会话（推荐，httpOnly cookie 更安全）：
    const sessionToken = await createSessionToken(openId, { name: userInfoData.data.name ?? "" });
    res.cookie(COOKIE_NAME, sessionToken, { httpOnly: true, path: "/", maxAge: ONE_YEAR_MS,
      sameSite: req.secure ? "none" : "lax", secure: req.secure });
    res.redirect(302, "/");
    // B. 无状态 token（零依赖项目）：token 回跳首页 URL，前端写 localStorage
    // res.redirect(302, `${basePath}/?token=${sessionToken}`);
  } catch (err) {
    console.error("[Auth] Feishu login failed:", err);
    redirectToLogin(res, err instanceof Error ? err.message : "飞书登录失败");
  }
});
```

**关键约定**
- 飞书 API 成功码为 `code === 0`，统一按此判断
- 用户唯一键 `open_id`（`ou_` 开头，~32 字符，注意 DB 列长度 ≥ 64）
- 首见用户默认 `role: "user"`；`FEISHU_ADMIN_OPEN_IDS` 命中者授 admin（每次登录幂等提升）
- 失败一律 302 回登录页带 `?error=`，不落 500 裸页
- `appSecret` 只在后端使用，绝不暴露到前端

## 三、前端

### A. 网页版重定向（推荐）

React 示例：

```tsx
const handleFeishuLogin = async () => {
  const res = await fetch("/api/auth/feishu/url");
  const data = await res.json();
  if (!res.ok || !data.url) throw new Error(data.error ?? "获取飞书登录链接失败");
  window.location.href = data.url;  // 跳飞书授权页，回调后自动返回
};

// 回调失败回跳 /login?error=...，展示一次并清理地址栏
useEffect(() => {
  const error = new URLSearchParams(window.location.search).get("error");
  if (error) {
    toast.error(`飞书登录失败：${error}`);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}, []);
```

登录成功后走项目既有鉴权链路（如 tRPC `auth.me` / `useAuth` hook），无需特殊处理。

### B. 扫码登录（LarkSSOSDKWebQRCode）

index.html 引入 SDK：

```html
<script src="https://lf-package-cn.feishucdn.com/obj/feishu-static/lark/passport/qrcode/LarkSSOSDKWebQRCode-1.0.3.js"></script>
```

```js
// DOM 需有容器 <div id="feishu_qrcode_container"></div>
async function initFeishuQRCode() {
  const container = document.getElementById("feishu_qrcode_container");
  if (!container || typeof window.QRLogin === "undefined") return;  // SDK 失败降级到重定向按钮
  const { appId } = await (await fetch("api/auth/feishu/url")).json();

  const redirectUri = encodeURIComponent(window.location.origin + "/api/auth/feishu/callback");
  const gotoUrl = `https://passport.feishu.cn/suite/passport/oauth/authorize?client_id=${appId}`
    + `&redirect_uri=${redirectUri}&response_type=code&state=feishu_qr`;

  const qr = window.QRLogin({ id: "feishu_qrcode_container", goto: gotoUrl,
    width: "300", height: "300", style: "width:100%;height:100%;border:none;background:transparent;" });

  // 防重复绑定；扫码确认后 SDK postMessage 推送 tmp_code，拼接后跳转触发回调
  window.addEventListener("message", event => {
    if (qr.matchOrigin(event.origin) && qr.matchData(event.data)) {
      window.location.href = `${gotoUrl}&tmp_code=${event.data.tmp_code}`;
    }
  }, false);
}
```

### C. token 型会话的接收（方案 B 适用）

```js
function checkUrlToken() {
  const token = new URLSearchParams(window.location.search).get("token");
  if (token) {
    localStorage.setItem("session-token", token);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}
```

## 四、接口约定速查

| 项 | 值 |
|----|----|
| 拉取授权 URL | `GET /api/auth/feishu/url` → `{ url }` |
| 授权页（重定向形态） | `https://open.feishu.cn/open-apis/authen/v1/authorize` |
| 授权页（扫码形态） | `https://passport.feishu.cn/suite/passport/oauth/authorize` |
| 回调地址 | `GET /api/auth/feishu/callback?code=xxx` |
| app_access_token | `POST /open-apis/auth/v3/app_access_token/internal` |
| user_access_token | `POST /open-apis/authen/v1/oidc/access_token`（Bearer app_access_token） |
| 用户信息 | `GET /open-apis/authen/v1/user_info`（Bearer user_access_token） |
| 扫码 SDK | `LarkSSOSDKWebQRCode-1.0.3.js`（飞书 CDN） |
| 成功码 | `code === 0` |
| 用户标识 | `open_id` |

## 五、常见坑位（实战沉淀）

1. **重定向 URL 协议错误**：反向代理下必须用 `x-forwarded-proto`（和 `x-forwarded-host`）还原真实地址，否则飞书拒绝回调或报 redirect_uri 非法。
2. **回调 URL 未登记**：开放平台「安全设置 → 重定向 URL」必须精确登记 `${域名}/api/auth/feishu/callback`，本地开发登记 `http://localhost:端口/api/auth/feishu/callback`。未登记时授权页不报错直到登录后确认阶段才失败——先用假 code 调回调可提前验证凭证有效性。
3. **open_id vs user_id**：跨应用稳定唯一键用 `open_id`；user_id 仅在同应用内稳定。
4. **role 覆盖**：upsert 用户时不要每次传 role，仅命中管理员白名单时传入，否则会把手工调整的角色覆盖回默认值。
5. **SDK 加载失败**：内网可能加载不了飞书 CDN，扫码页要有降级按钮（重定向登录）。
6. **监听器重复绑定**：扫码 message 监听用标志位（如 `window.feishuQrListenerAttached`）防重复。
7. **Token 安全**：`appSecret` 只在后端；会话优先 httpOnly cookie（URL 带 token 会被历史记录/日志泄漏）。
8. **预验证技巧**：`GET /api/auth/feishu/callback?code=fake` 能走到「获取 user_access_token 失败」即证明 app_access_token 步骤通、凭证有效、网络可达——不需要真实账号即可测通前两环。

## 六、验证清单

1. `GET /api/auth/feishu/url` 返回含正确 app_id 与 redirect_uri 的授权 URL
2. 回调缺 code → 302 回登录页带错误信息
3. 伪造 code → 302 回登录页「获取 user_access_token 失败」（证明 Step 1 通）
4. 真实登录 → 回跳首页 → `auth.me` 返回飞书用户（loginMethod='feishu'）→ DB 自动建档
5. 管理员白名单用户登录 → role=admin
