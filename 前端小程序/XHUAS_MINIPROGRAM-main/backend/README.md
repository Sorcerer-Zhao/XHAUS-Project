# XHUAS 小程序后端

完整配置说明请看上一层目录的 `README.md`。

快速启动：

```bash
npm install
cp .env.example .env
npm start
```

Windows PowerShell：

```powershell
npm install
Copy-Item .env.example .env
notepad .env
npm start
```

启动前必须在 `.env` 里填写 `JWT_SECRET`。如果 XHAUS 不在默认同级目录，也要填写 `XHAUS_ROOT`。
