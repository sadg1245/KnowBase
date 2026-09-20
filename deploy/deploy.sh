#!/usr/bin/env bash
# KnowBase 生产部署脚本（目标机器：2 vCPU / 2 GiB 的 ECS）
#
# 用法：
#   bash deploy/deploy.sh               # 构建镜像并启动
#   bash deploy/deploy.sh --pull        # 先 git pull --ff-only 再部署
#   bash deploy/deploy.sh --no-build    # 不重新构建，只按新配置重建容器（改完 .env 用）
#
# 前置：已执行 deploy/ecs-init.sh（Docker + Compose 插件 + swap）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
BACKEND_HEALTH_URL="http://127.0.0.1:9000/"
PULL=0
BUILD=1

for arg in "$@"; do
  case "$arg" in
    --pull)     PULL=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help)  sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------- 运行环境检查
command -v docker >/dev/null 2>&1 || die "未安装 Docker，请先执行：sudo bash deploy/ecs-init.sh"
docker compose version >/dev/null 2>&1 || die "缺少 Compose 插件，请先执行：sudo bash deploy/ecs-init.sh"

if ! docker info >/dev/null 2>&1 && [[ ${EUID} -ne 0 ]]; then
  die "当前用户没有 Docker 权限。请用 sudo 运行，或执行 sudo usermod -aG docker \$USER 后重新登录"
fi

# backend 的 ports: !override 需要 Compose 2.24+
compose_version="$(docker compose version --short 2>/dev/null || echo 0.0.0)"
if [[ "$(printf '%s\n2.24.0\n' "$compose_version" | sort -V | head -1)" != "2.24.0" ]]; then
  die "Docker Compose ${compose_version} 过旧（docker-compose.prod.yml 需要 2.24+），请升级 docker-compose-plugin"
fi

# ------------------------------------------------------------------ .env 检查
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "已从 .env.example 生成 .env，请先填写后再运行本脚本："
  warn "  DEEPSEEK_API_KEY=<你的 key>"
  warn "  HF_ENDPOINT=https://hf-mirror.com"
  warn "  CORS_ORIGINS=http://<公网IP>:3000"
  exit 1
fi

env_value() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '"'; }

llm_key_ok=0
for key in OPENAI_API_KEY DEEPSEEK_API_KEY DASHSCOPE_API_KEY ZHIPU_API_KEY; do
  value="$(env_value "$key" || true)"
  case "$value" in
    ""|*your-*|*your_*|*sk-your-*) ;;
    *) llm_key_ok=1 ;;
  esac
done
(( llm_key_ok == 1 )) || warn "四个模型 API Key 都还是占位值，首次进页面后需要在「设置」里填写"

if [[ -z "$(env_value FEISHU_APP_ID || true)" || -z "$(env_value FEISHU_APP_SECRET || true)" ]]; then
  warn "FEISHU_APP_ID / FEISHU_APP_SECRET 未填，机器人会停在「等待填写凭证」；在网页「设置 → 飞书机器人」里填即可，填完立即生效、不用重启"
fi

cors="$(env_value CORS_ORIGINS || true)"
case "$cors" in
  *__PUBLIC_URL__*) warn "CORS_ORIGINS 还是占位符 __PUBLIC_URL__，请替换成 http://<公网IP>:3000 或 https://你的域名" ;;
  *localhost*)      warn "CORS_ORIGINS 仍是默认的 localhost（${cors}），公网访问请改成 http://<公网IP>:3000 或 https://你的域名" ;;
esac

grep -qE '^HF_ENDPOINT=' .env || warn "未设置 HF_ENDPOINT，本地 embedding 模型会去 HuggingFace 下载（国内通常失败），建议加 HF_ENDPOINT=https://hf-mirror.com"

# --------------------------------------------------------------------- 部署
if (( PULL )); then
  ok "更新代码：git pull --ff-only"
  git -C "$REPO_ROOT" pull --ff-only
fi

if (( BUILD )); then
  ok "构建并启动（首次要拉 torch 和依赖，2C2G 机器约 5~15 分钟）"
  "${COMPOSE[@]}" up -d --build
else
  ok "复用现有镜像，按新配置重建容器"
  "${COMPOSE[@]}" up -d
fi

# ---------------------------------------------------------------- 健康检查
ok "等待后端迁移与启动（最长 5 分钟）"
deadline=$(( SECONDS + 300 ))
until curl -fsS -o /dev/null "$BACKEND_HEALTH_URL" 2>/dev/null; do
  if (( SECONDS > deadline )); then
    warn "后端未在预期时间内就绪，最近 60 行日志："
    "${COMPOSE[@]}" logs --tail=60 backend || true
    die "部署未完成，请根据上面的日志排查"
  fi
  sleep 5
done
ok "后端已就绪"

"${COMPOSE[@]}" ps

# ---------------------------------------------------------------- 收尾信息
public_ip="$(curl -fsS --max-time 3 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null || true)"
[[ -n "$public_ip" ]] || public_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$public_ip" ]] || public_ip="<服务器IP>"

cat <<EOF

部署完成，接下来：
  1) 浏览器打开 http://${public_ip}:3000
  2) 首次进入会引导创建唯一账号
  3) 「设置」里填模型 API Key；飞书机器人在「设置 → 飞书机器人」里配

常用命令：
  ${COMPOSE[*]} ps                    # 查看各容器状态
  ${COMPOSE[*]} logs -f backend       # 查看后端日志
  ${COMPOSE[*]} stats                 # 查看内存占用（2 GiB 机器重点看这个）
  bash deploy/deploy.sh --no-build    # 改完 .env 后热重启
EOF
