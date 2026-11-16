# 宝塔面板部署指南（step__glb_pdf）

面向 Linux 宝塔面板的生产部署步骤。本服务后端用 Flask + gunicorn，核心几何依赖
`pythonocc-core`（OCC 内核）**只能从 conda 安装**，不能用 pip，因此不能用宝塔自带的
"Python 项目管理器"（它只支持 venv + pip）。正确路线：

> Miniconda 建环境 → gunicorn 跑 → 宝塔"进程守护"保活 → 宝塔网站反向代理出域名 / HTTPS

---

## 0. 部署前须知（决定架构的关键事实）

- **后端入口**：`src/web/app.py` 中 `app = create_app()`，gunicorn 用 `web.app:app`，
  默认监听 **5001**（`STEP_HOST` 可改绑定地址，默认 `0.0.0.0`）。
- **前端**：`cad-viewer-app` 是 Vite 工程，**必须 `npm run build` 生成 `dist/`**，
  Flask 的 `/editor` 路由直接托管 `dist/`。未构建时该路由返回 503。
- **`.env`** 放在**项目根目录**（从 `.env.example` 拷贝），由 `load_env(PROJECT_ROOT)` 读取。
- **`output/`**（结果产物）与 **`data/`**（配置 / 模板）都在项目根，需随代码上传；
  `output/` 要放在持久盘并定期备份——"同型号复用跳过构建"的命中判断只读本地 `output/`。
- **依赖分两块**：
  - `pythonocc-core`：只能 `conda install -c conda-forge`，不在 `requirements.txt` 中。
  - 其余（Flask、reportlab、ezdxf、PyMuPDF、trimesh、numpy、openpyxl、svglib、boto3、
    pytest）都在 `requirements.txt`，用 pip 一次装齐。
- **运行数据不入库**：`library/`、`data/`、前端 `dist/` 与系列目录下的 xlsx 需随代码
  单独上传；`output/` 只建空目录，历史产物可按需保留。

---

## 1. 宝塔基础准备

1. 安装宝塔面板（LNMP 随意，本服务只需 Nginx 做反向代理）。
2. 安全 → 防火墙：只放行 80 / 443。gunicorn 按第 7 节绑 `127.0.0.1:5001`，
   由本机 Nginx 反代，不必对外开放 5001。
3. 计划任务：给 `output/` 加每日打包备份（可选但建议）。

---

## 2. 安装 Miniconda（OCC 的前提）

SSH 进服务器：

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -p /root/miniconda3
```

安装完成后会问 `Proceed with initialization?`（是否把 conda 写入 shell 启动文件）。
选 `yes` 即可让新终端直接用 `conda`；若错过了（Ctrl+C 跳过），手动补：

```bash
source /root/miniconda3/bin/activate
conda init bash
source ~/.bashrc
```

嫌每次登录前缀带 `(base)`，可执行 `conda config --set auto_activate_base false`。

### 2.1 接受 Anaconda 频道服务条款（一次性）

新版本 conda 默认频道（`repo.anaconda.com/pkgs/main`、`pkgs/r`）要求先同意 ToS，
非交互模式（`-y`）下没同意会直接报错 `CondaToSNonInteractiveError`。先接受：

```bash
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
```

（想彻底绕开官方频道，可执行 `conda config --add channels conda-forge &&
conda config --set channel_priority strict`，之后不再弹 ToS。）

---

## 3. 创建环境并安装依赖

```bash
conda create -n pdf1 python=3.10 -y
conda activate pdf1
# OCC 只能从 conda-forge 装
conda install -c conda-forge pythonocc-core -y
# 生产 WSGI 服务器
pip install gunicorn
```

验证环境装对（必须看到 `OCC ok` 且 gunicorn 指向 pdf1）：

```bash
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC ok')"
which gunicorn   # 应指向 /root/miniconda3/envs/pdf1/bin/gunicorn
```

> 注意：`pip install gunicorn` 必须在 `conda activate pdf1` **之后**执行，否则会装进 base 环境。

---

## 4. 上传代码

把整个项目传到服务器，例如 `/www/wwwroot/step__glb_pdf`（宝塔"文件" / sftp / git 均可）。
保持 `pdf1` 环境激活，安装 pip 依赖：

```bash
cd /www/wwwroot/step__glb_pdf
conda activate pdf1
pip install -r requirements.txt
```

---

## 5. 构建前端（二选一）

**方案 A：服务器上构建**（需 Node 20+，满足 Vite 8）：

```bash
cd /www/wwwroot/step__glb_pdf/cad-viewer-app
npm install
npm run build   # 生成 dist/
```

**方案 B（推荐，省服务器资源）：本地已 `npm run build` 过 → 直接把 `cad-viewer-app/dist/`
连同代码传上去**，服务器无需装 Node。

---

## 6. 配置 `.env`

```bash
cd /www/wwwroot/step__glb_pdf
cp .env.example .env
vi .env
```

默认 `STORAGE_BACKEND=local` 即可运行（纯本地，与改造前一致）。要上 OSS 见第 10 节。
`STEP_HOST` 只在直接跑 `python src/web/server.py` 时生效（`web/app.py` 的 `main()` 读取），
gunicorn 用 `web.app:app` 不读它，绑定地址完全由 `-b` 决定。生产按第 7 节用
`-b 127.0.0.1:5001` 即可，不必配 `STEP_HOST`。

`.env.example` 未列出出图与任务池参数，需手动补 `BUILD_POOL_WORKERS`、`DRAWING_ALGO`、
`DRAWING_POLY_DEFLECTION`、`DRAWING_POLY_DO_FIT`，否则线上出图算法与精度跟本地不一致。

---

## 7. 启动服务 + 宝塔"进程守护"保活

### 7.1 先手动验证一次

```bash
cd /www/wwwroot/step__glb_pdf/src
python -c "from web.app import app; print('import ok')"
/root/miniconda3/envs/pdf1/bin/gunicorn -w 1 -k gthread --threads 8 -b 127.0.0.1:5001 --timeout 600 web.app:app
```

能访问 `http://127.0.0.1:5001/` 后再交守护。

### 7.2 宝塔进程守护配置

软件商店 → 进程守护管理器（Supervisor）→ 新建：

- **名称**：`step-glb-pdf`
- **运行目录**：`/www/wwwroot/step__glb_pdf/src`
- **启动命令**（用你自己的 conda gunicorn 绝对路径）：

  ```bash
  /root/miniconda3/envs/pdf1/bin/gunicorn -w 1 -k gthread --threads 8 -b 127.0.0.1:5001 --timeout 600 --graceful-timeout 60 web.app:app
  ```

- **环境变量**（保险，确保 `web` 包可导入）：

  ```
  PYTHONPATH=/www/wwwroot/step__glb_pdf/src
  ```

- **进程数量：必须设为 1**（见下方"常见故障"）。

要点：
- **gunicorn 只能 `-w 1`**：`task_pool` 是进程内单例，任务字典不跨 worker 共享。
  开多个 worker 时 `POST /api/build` 落在 A、轮询 `/api/task/<id>` 落在 B 会查不到任务；
  且每个 worker 各自再开 OCC 子进程，内存按 worker 数翻倍。并发交给 `--threads`
  和任务池 `BUILD_POOL_WORKERS`（每个跑过任务的 worker 常驻 290–480 MB，按内存定）。
- `--timeout 600`：OCC 构建重型型号可能几十秒，防 gunicorn 误杀 worker。

---

## 8. 宝塔网站 + 反向代理（出域名 / HTTPS）

1. 网站 → 添加站点：填域名（如 `cad.example.com`），PHP 版本选"纯静态"。
2. 该站点 → **反向代理 → 添加反向代理**：
   - 代理名称：`step5001`
   - 目标 URL：`http://127.0.0.1:5001`
   - 发送域名：`$host`
3. 站点 → SSL → 申请 / 部署 Let's Encrypt，强制 HTTPS。
4. 反向代理"配置文件"建议加（避免大文件 glb/step 下载被缓冲卡住）：

   ```
   proxy_request_buffering off;
   proxy_buffering off;
   ```

访问 `https://cad.example.com/` 看装配面板，`/editor` 是 Vue 编辑器，`/viewer` 是 3D 查看器。

---

## 9. 验证部署

```bash
curl -k http://127.0.0.1:5001/
curl -k "http://127.0.0.1:5001/api/resources/<某已构建型号>"   # 验证本地缓存命中逻辑
```

页面能开、能触发构建、能下载产物即完成。

---

## 10. 可选：开启 OSS 对象存储

编辑 `.env`：

```ini
STORAGE_BACKEND=oss
OSS_ENDPOINT=https://oss-cn-xxx.aliyuncs.com
OSS_REGION=cn-xxx
OSS_BUCKET=your-bucket
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
OSS_PREFIX=step-output
# 私有桶留空（用签名 URL）；公共读填 CDN 基址
OSS_PUBLIC_BASE=
OSS_PRESIGN_EXPIRE=3600
```

效果说明：
- 本地 `output/` 仍是工作存储，**"同型号复用跳过构建"（`api_resources`）完全保留**，
  因为命中判断只读本地盘。
- 下载路由改为 **302 跳 OSS**，浏览器 / CDN 可加 `Cache-Control`，重复下载多一层 HTTP 缓存命中。
- 当前 OSS 是**单向镜像**（只写不回读）。若是**无状态 / 多实例**部署（容器重启清掉 `output/`），
  本地命中会失效而被迫重建；要让"OSS 命中直接返回"跨重启生效，需在 `api_resources` 里加一次
  OSS `HEAD Object` 探活。单机持久盘部署不需要。

---

## 11. 更新代码流程

```bash
cd /www/wwwroot/step__glb_pdf
git pull   # 或重新上传
conda activate pdf1
pip install -r requirements.txt   # 依赖有变时
cd cad-viewer-app && npm install && npm run build && cd ..   # 前端有变时
# 宝塔进程守护里点"重启" step-glb-pdf
```

---

## 12. 常见故障

### 端口被占用：`Connection in use (Errno 98)`
日志出现一堆 `Connection in use` / `Can't connect`，是**多个 gunicorn 抢同一端口 5001**：

- **最常见原因：宝塔进程守护"进程数量"设成了 2**。该字段是"启动几条相同命令"，
  设 2 会拉起 2 个 gunicorn master 都绑 5001，第二个失败并被不断重启刷屏。
  **改成 1**，并发交给 gunicorn 的 `--threads` 和任务池 `BUILD_POOL_WORKERS`。
- 也可能是"进程守护已在管一个，你又手动跑了一次 gunicorn"。清理成单一启动源：

  ```bash
  pkill -f "gunicorn.*web.app"
  sleep 2
  ps aux | grep gunicorn | grep -v grep   # 应为空，等 supervisor 拉起唯一一个
  ```

  然后只保留进程守护一种启动方式，不要同时手动跑。

### `CondaToSNonInteractiveError`
见第 2.1 节，先 `conda tos accept` 两个官方频道。

### `from OCC... import` 失败 / gunicorn 指向 base
说明 `pythonocc-core` 没装进 `pdf1`，或 `gunicorn` 装到了 base。重做第 3 节，
确认 `conda activate pdf1` 后再装，并用 `which gunicorn` 核对路径含 `envs/pdf1`。

### `/editor` 返回 503
前端没构建。回到第 5 节生成 `cad-viewer-app/dist/`。
