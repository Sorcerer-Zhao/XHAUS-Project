# XHAUS Backend

## Setup

1. Copy the env template:

```
cp .env.example .env
```

2. Fill the required values in `.env`.

3. Install dependencies:

```
npm install
```

4. Run the server:

```
npm run dev
```

The server listens on `http://127.0.0.1:3000` by default.

## 发布注意

如果这个后端要给微信小程序正式环境使用，请不要直接暴露局域网地址。建议给 `3000` 端口前面挂一层公网 `HTTPS` 反向代理或隧道，再把小程序前端的 `apiBase` 指向这个公网域名。`openclaw` 仍然可以保留在内网 `http` 端口，由后端网关代为访问。
