# Media Link Downloader

输入分享链接，解析公开图片或视频资源并触发下载。项目分为 Python FastAPI 后端和 Vue3 前端。

当前主流程不使用数据库，也不保存用户下载的文件：

- 图片：前端流式下载并显示进度
- 视频：后端流式代理，前端交给浏览器下载器
- 多个资源：按顺序触发下载，不打包 zip

## 目录

```txt
backend/   Python FastAPI 接口
frontend/  Vue3 + Vite + pnpm 前端
```

## 本地开发

### 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端健康检查：

```txt
http://127.0.0.1:8000/health
```

### 前端

```bash
nvm use
cd frontend
pnpm install
pnpm dev
```

默认访问：

```txt
http://127.0.0.1:5173/
```

本地开发时不需要配置 `VITE_API_BASE_URL`，Vite 会把 `/api` 和 `/media` 代理到 `http://localhost:8000`。

## 环境变量

### 后端

```txt
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
YTDLP_COOKIE_FILE=/absolute/path/to/cookies.txt
DOWNLOAD_DIR=/absolute/path/to/downloads
ALLOW_PRIVATE_HOSTS=false
```

- `FRONTEND_ORIGINS`：允许访问后端的前端域名，部署后填 GitHub Pages 域名
- `YTDLP_COOKIE_FILE`：可选，给需要登录态的平台使用，cookie 文件不要放进仓库
- `DOWNLOAD_DIR`：可选，旧兜底下载目录；当前主流程不依赖长期保存
- `ALLOW_PRIVATE_HOSTS`：默认关闭，生产环境不要开启

### 前端

```txt
VITE_API_BASE_URL=https://your-backend.onrender.com
VITE_BASE_PATH=/your-repo-name/
```

- `VITE_API_BASE_URL`：部署后的后端地址
- `VITE_BASE_PATH`：GitHub Pages 项目路径，本地默认 `/`

## 部署

推荐：

```txt
前端：GitHub Pages
后端：Render Free
```

### Render 后端

仓库根目录已提供 `render.yaml`。在 Render 新建 Blueprint 或 Web Service 时使用：

```txt
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Render 环境变量：

```txt
PYTHON_VERSION=3.12.8
FRONTEND_ORIGINS=https://<你的 GitHub 用户名>.github.io,http://localhost:5173,http://127.0.0.1:5173
```

`FRONTEND_ORIGINS` 只写 origin，不带仓库路径。比如：

```txt
https://xiaomeng.github.io
```

### GitHub Pages 前端

仓库已提供 `.github/workflows/pages.yml`。

在 GitHub 仓库里设置：

```txt
Settings -> Pages -> Build and deployment -> Source -> GitHub Actions
```

再设置 Actions 变量：

```txt
Settings -> Secrets and variables -> Actions -> Variables
Name: VITE_API_BASE_URL
Value: https://<你的 Render 服务名>.onrender.com
```

推送到 `main` 后，GitHub Actions 会自动构建前端并发布到：

```txt
https://<你的 GitHub 用户名>.github.io/<仓库名>/
```

## 注意

- Render 免费服务会休眠，第一次访问可能需要等待冷启动。
- 免费平台有流量和超时限制，大视频下载自用可以，别当高并发服务。
- 不要提交 `.env`、cookie 文件、虚拟环境、`frontend/dist` 或 `frontend/node_modules`。
