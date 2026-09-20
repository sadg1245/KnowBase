# 部署到阿里云 ECS

面向 **2 vCPU / 2 GiB** 起步的 ECS（Alibaba Cloud Linux 3）。整套服务由 Docker Compose 拉起，
共 6 个容器：backend、worker、feishu-bot、frontend、chromadb、redis。

## 一、前置：安全组

| 端口 | 是否放行 | 用途 |
|---|---|---|
| 22 | 是 | SSH / 控制台「网页连接」（Workbench） |
| 3000 | 是 | Web 界面（没有域名时先用它访问） |
| 80 / 443 | 有域名时 | 宿主机 Nginx + HTTPS |
| 9000 / 9001 / 6379 | 否 | 后端 API、ChromaDB、Redis，只允许本机访问 |

## 二、部署顺序

```bash
# 1) 取代码（二选一）；脚本在仓库里，所以这一步必须在最前面
cd /opt && git clone https://github.com/sadg1245/KnowBase.git knowbase
#    或本机上传（务必排除 .venv / node_modules / dist）
#    scp -r backend frontend feishu-bot docker-compose*.yml pyproject.toml uv.lock root@<IP>:/opt/knowbase/

# 2) 初始化系统：Docker、镜像加速、4 GiB swap、日志限制
#    加速地址在「容器镜像服务 ACR → 镜像工具 → 镜像加速器」里复制
cd /opt/knowbase
sudo ACR_MIRROR=https://xxxx.mirror.aliyuncs.com bash deploy/ecs-init.sh

# 3) 配置环境变量
cp .env.example .env && vi .env

# 4) 构建并启动
bash deploy/deploy.sh
```

`.env` 里必须确认的三项：

```env
DEEPSEEK_API_KEY=<你的 key>
HF_ENDPOINT=https://hf-mirror.com        # 不填的话本地 embedding 模型下载不下来
CORS_ORIGINS=http://<公网IP>:3000        # 有域名后改成 https://你的域名
```

`JWT_SECRET` 与 `SERVICE_TOKEN` 留空即可，程序会自己生成到数据卷的 `secrets/` 并复用。

## 三、首次访问

1. 浏览器打开 `http://<公网IP>:3000`，按引导创建**唯一一个账号**（建号后设置入口关闭）。
2. 进入「设置」填模型 API Key（也可以在这里改模型和 embedding）。
3. 飞书机器人在「设置 → 飞书机器人」里填 App ID / Secret —— 它走 WebSocket 出站连接，不需要开放入站端口。

## 四、针对 2C2G 做的调整

`docker-compose.prod.yml` 相比默认配置改了四处：

| 改动 | 原因 |
|---|---|
| worker 并发 4 → 1，且 `--max-tasks-per-child=20` | 每个 Celery 子进程会各自加载一份 embedding 模型，4 份直接 OOM |
| backend 端口改为 `127.0.0.1:9000` | 默认绑在 `0.0.0.0:9000`，等于把 API 暴露到公网 |
| 所有容器加日志轮转（10m × 3） | 小系统盘很容易被 JSON 日志写满 |
| chromadb 镜像支持用 `CHROMA_IMAGE` 固定版本 | `latest` 可能拉到和客户端不兼容的版本 |

如果直接把本机的 `.env` 拷到服务器，建议再调低资料富化的并发（`.env.example` 里没有这两项，
所以按示例新建的 `.env` 不受影响）：

```env
RAG_ENRICH_ENABLED=false
RAG_ENRICH_CONCURRENCY=1
```

另外 `deploy/ecs-init.sh` 会创建 4 GiB swap —— 2 GiB 物理内存跑 6 个容器要靠它兜底。
部署后用 `docker compose -f docker-compose.yml -f docker-compose.prod.yml stats` 观察占用；
如果 backend + worker 常态超过 1.5 GiB，建议把 embedding 换成远程 API（设置页可切换，
切换 embedding 模型后需要重新索引已有资料）。

## 五、日常运维

```bash
cd /opt/knowbase
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$COMPOSE ps                      # 状态
$COMPOSE logs -f backend         # 后端日志
$COMPOSE restart feishu-bot      # 重启机器人
bash deploy/deploy.sh --pull     # 更新代码并重新部署
bash deploy/deploy.sh --no-build # 只改了 .env，按新配置重建容器
```

备份（数据库、媒体、密钥都在 backend_data 卷里）：

```bash
docker run --rm -v knowbase_backend_data:/data -v /opt/backups:/backup alpine \
  tar czf /backup/backend_data-$(date +%F).tar.gz -C /data .
docker run --rm -v knowbase_backend_uploads:/data -v /opt/backups:/backup alpine \
  tar czf /backup/backend_uploads-$(date +%F).tar.gz -C /data .
docker run --rm -v knowbase_chroma_data:/data -v /opt/backups:/backup alpine \
  tar czf /backup/chroma_data-$(date +%F).tar.gz -C /data .

# 磁盘清理（镜像和构建缓存会占几个 G）
docker system prune -af
```

## 六、常见故障

| 现象 | 处理 |
|---|---|
| `deploy.sh` 报 Compose 版本过旧 | `dnf upgrade -y docker-compose-plugin`（`!override` 需要 2.24+） |
| backend 反复重启 | `$COMPOSE logs --tail=100 backend`，多为迁移失败或内存不足 |
| 上传资料后一直处理中 | worker 挂了或被 OOM kill：`docker inspect knowbase-worker --format '{{.State.OOMKilled}}'` |
| embedding 报错、模型下载卡住 | 确认 `.env` 有 `HF_ENDPOINT=https://hf-mirror.com`，然后 `$COMPOSE restart backend worker` |
| 页面能开但接口全 502 | backend 未就绪，`$COMPOSE ps` 看健康状态 |
| 登录后立刻掉线 / 跨域报错 | `.env` 的 `CORS_ORIGINS` 与实际访问地址不一致，改完执行 `bash deploy/deploy.sh --no-build` |

## 七、安全提醒

仓库里的 `.env.example` 曾经包含真实的飞书 App Secret 与 DeepSeek Key，且已经提交进 Git 历史。
请到飞书开放平台和 DeepSeek 控制台**重置这两个密钥**，重置后只写进服务器上的 `.env`
（该文件已被 `.gitignore` 忽略）。真实密钥不要写回 `.env.example`。
