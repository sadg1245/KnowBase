# 裸机部署（不用 Docker）

面向 **2 vCPU / 2 GiB** 的 ECS，直接把项目跑在系统上：3 个 systemd 服务 + Redis + nginx。
比容器方案少一个 ChromaDB 服务（改成进程内嵌模式）、少一层 dockerd，2 GiB 机器大约能多出 400 MB 余量。

## 架构

| 组件 | 形态 | 端口 |
|---|---|---|
| nginx | 系统服务，托管前端静态文件 + 反代 `/api` | 80（有域名再加 443） |
| backend | `knowbase-backend.service`（uvicorn） | 127.0.0.1:9000 |
| worker | `knowbase-worker.service`（Celery） | — |
| feishu-bot | `knowbase-feishu-bot.service` | — |
| redis | 系统服务 | 127.0.0.1:6379 |
| 向量库 | 跑在 backend/worker 进程内的 ChromaDB 嵌入模式 | — |

> Redis 和 worker 是**不能省**的：`backend/app/collector/tasks.py` 明确不接受内联执行，
> 没有 worker 时上传的资料会直接失败并标记 `Queue dispatch failed`。

## 目录约定

| 路径 | 内容 |
|---|---|
| `/opt/knowbase` | 代码 + `.venv` + `.env`（属主 root，服务只读） |
| `/var/lib/knowbase` | 数据：`sqlite/` `uploads/` `media/` `chroma/` `secrets/` `backups/` `huggingface/`（属主 `knowbase`） |
| `/etc/nginx/conf.d/knowbase.conf` | 站点配置 |
| `/etc/systemd/system/knowbase-*.service` | 三个服务单元 |

## 部署步骤

### 1. 把代码放到 /opt/knowbase

```bash
sudo mkdir -p /opt/knowbase
cd /opt && sudo git clone https://github.com/sadg1245/KnowBase.git knowbase
# 或本机上传（务必排除 .venv / node_modules / dist，否则要传 1.4 GB）
```

脚本就在仓库里，所以先取代码；服务器没有 git 时先 `sudo dnf install -y git`。
`deploy.sh` 与 systemd 单元里写死了 `/opt/knowbase`，换目录要同时改脚本和单元文件。

### 2. 系统初始化（每台机器一次）

```bash
cd /opt/knowbase && sudo bash deploy/baremetal/install.sh
```

它会：加 4 GiB swap、装 Python 3.12/3.11、装并启动 Redis 与 nginx、创建运行用户 `knowbase` 和数据目录。
如果仓库里没有 3.12/3.11，按提示二选一：用 uv 装解释器（推荐），或者 `sudo BUILD_PYTHON=1 bash deploy/baremetal/install.sh` 源码编译。

### 3. 配置 .env

```bash
sudo cp /opt/knowbase/deploy/baremetal/env.example /opt/knowbase/.env
sudo vi /opt/knowbase/.env
sudo chmod 600 /opt/knowbase/.env
```

要确认的项：

```env
DEEPSEEK_API_KEY=<你的 key>          # 留空也行，首次进页面后在「设置」里填
CORS_ORIGINS=http://<公网IP>         # 走 nginx 同源访问时影响不大，按实际地址填更稳妥
HF_ENDPOINT=https://hf-mirror.com    # 已预置，本地 embedding 模型靠它下载
```

`JWT_SECRET`、`SERVICE_TOKEN` 留空即可，后端首次启动会自动生成到 `/var/lib/knowbase/secrets/`。

### 4. 部署

```bash
# 前端建议在本机构建好再上传，服务器就不用装 Node
cd frontend && npm ci && npm run build
scp -r dist root@<公网IP>:/opt/knowbase/frontend/

sudo bash /opt/knowbase/deploy/baremetal/deploy.sh
```

`deploy.sh` 会建 venv、装依赖（CPU 版 torch + 后端 + 机器人）、跑 Alembic 迁移、安装 systemd 单元和 nginx 配置、重启服务，最后做健康检查。
服务器上如果装了 npm，它会直接现场构建前端，省掉上传步骤。

### 5. 首次访问

浏览器打开 `http://<公网IP>` → 创建唯一账号 → 在「设置」里填模型 Key 和飞书凭证。
飞书机器人走 WebSocket 出站连接，不需要开放任何入站端口。

## 日常运维

```bash
systemctl status knowbase-backend knowbase-worker knowbase-feishu-bot
journalctl -u knowbase-backend -f        # 后端日志
journalctl -u knowbase-worker -f         # worker 日志
journalctl -u knowbase-feishu-bot -f     # 机器人日志
journalctl -u knowbase-worker -n 100     # 看最近 100 行

# 改了 .env 后逐个重启（三个服务都读同一个文件）
sudo systemctl restart knowbase-backend knowbase-worker knowbase-feishu-bot

# 升级代码
cd /opt/knowbase && sudo git pull
sudo bash deploy/baremetal/deploy.sh                 # 依赖有变化时
sudo bash deploy/baremetal/deploy.sh --skip-deps     # 只更新代码/配置
```

备份（数据全在 `/var/lib/knowbase`）：

```bash
sudo tar czf /opt/backups/knowbase-$(date +%F).tar.gz -C /var/lib/knowbase .
# 恢复：先停服务，解包覆盖，再起服务
```

## 内存不够时的两个开关

| 开关 | 作用 |
|---|---|
| `SKIP_LOCAL_EMBEDDING=1` | 不装 torch 与 sentence-transformers（省约 1.5 GB 磁盘、运行时不加载模型），但要进网页「设置」把 embedding 改成远程 API；换 embedding 模型后需要重新索引已有资料 |
| `RAG_ENRICH_ENABLED=false` | 已在 `env.example` 里默认关闭：索引期富化会并发调模型，2 GiB 机器容易同时打满内存和 API 配额 |

## 与容器方案的关系

两套配置并存，互不影响：`docker-compose*.yml` + `deploy/ecs-init.sh` + `deploy/deploy.sh` 是容器路线，
本目录是裸机路线。裸机的优点是省内存、没有镜像层、日志直接进 journald；
代价是依赖版本不固化，升级要手动 `pip install`，换机器时得重跑一遍 `install.sh`。

## 常见故障

| 现象 | 处理 |
|---|---|
| `deploy.sh` 报"找不到 Python 3.11/3.12" | 先跑 `install.sh`；或按提示用 uv 装解释器后 `PYTHON_BIN=... sudo -E bash deploy/baremetal/deploy.sh` |
| backend 启动即退出 | `journalctl -u knowbase-backend -n 50`；迁移失败时 API 不会启动，这是设计行为 |
| 上传资料一直"处理中" | `systemctl status knowbase-worker`；worker 挂了或被 OOM kill 会出现这种情况 |
| embedding 报错、模型下载卡住 | 确认 `.env` 里有 `HF_ENDPOINT=https://hf-mirror.com`，然后重启 backend 和 worker |
| 页面能开但接口 502 | backend 没起来：`curl -v http://127.0.0.1:9000/`、`journalctl -u knowbase-backend` |
| 页面 403 或空白 | SELinux 拦了静态目录：`chcon -R -t httpd_sys_content_t /opt/knowbase/frontend/dist` |
| nginx -t 报 duplicate default server | 你保留了系统自带配置：删掉 `/etc/nginx/nginx.conf` 里 `listen 80 default_server` 的 server 块，或去掉 `KEEP_NGINX_CONF=1` 让脚本托管 |
| 登录后立刻掉线 / 跨域报错 | `.env` 的 `CORS_ORIGINS` 与实际访问地址不一致，改完重启三个服务 |
| 想回到原始 nginx 配置 | `sudo cp -a /etc/nginx/nginx.conf.knowbase-orig /etc/nginx/nginx.conf && sudo systemctl reload nginx` |
