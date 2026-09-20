#!/usr/bin/env bash
# KnowBase 裸机部署 / 升级脚本
#
# 用法（root）：
#   sudo bash deploy/baremetal/deploy.sh                 # 首次部署或完整升级
#   sudo bash deploy/baremetal/deploy.sh --skip-deps     # 只更新代码、迁移、重启（不重装依赖）
#
# 可调环境变量：
#   PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/    # pip 源
#   SKIP_LOCAL_EMBEDDING=1                               # 不装 torch/sentence-transformers，改用远程 embedding
#   KEEP_NGINX_CONF=1                                    # 不改写 /etc/nginx/nginx.conf
#   APP_DIR=/opt/knowbase  DATA_DIR=/var/lib/knowbase  RUN_USER=knowbase
#
# 前置：已执行 deploy/baremetal/install.sh（swap、Python、Redis、nginx、运行用户）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="${APP_DIR:-/opt/knowbase}"
DATA_DIR="${DATA_DIR:-/var/lib/knowbase}"
RUN_USER="${RUN_USER:-knowbase}"
VENV="$APP_DIR/.venv"
PIP_INDEX="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
PYTHON_BIN="${PYTHON_BIN:-}"
SKIP_DEPS=0

for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
    -h|--help)   sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

ok()   { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "请用 root 运行：sudo bash $0"
[[ "$REPO_ROOT" == "$APP_DIR" ]] || die "systemd 单元里写死了 $APP_DIR，请把仓库放在该目录再执行：
  sudo mkdir -p $APP_DIR && sudo rsync -a --exclude .venv --exclude node_modules $REPO_ROOT/ $APP_DIR/"
[[ "$(id -u "$RUN_USER" 2>/dev/null || true)" != "" ]] || die "运行用户 $RUN_USER 不存在，请先执行 deploy/baremetal/install.sh"
cd "$REPO_ROOT"

# ---------------------------------------------------------------- 1. 环境文件
if [[ ! -f "$APP_DIR/.env" ]]; then
  install -m 0600 -o root -g root deploy/baremetal/env.example "$APP_DIR/.env"
  warn "已生成 $APP_DIR/.env，请填写后再运行本脚本："
  warn "  DEEPSEEK_API_KEY=<你的 key>（也可以首次进页面后在「设置」里填）"
  warn "  CORS_ORIGINS=http://<公网IP>（可选，走 nginx 同源访问时影响不大）"
  exit 1
fi
env_value() { grep -E "^$1=" "$APP_DIR/.env" | head -1 | cut -d= -f2- | tr -d '"'; }

# .env 里的 DATA_ROOT 必须和 systemd 的 StateDirectory 一致，否则服务用户可能没有写权限
env_data_root="$(env_value DATA_ROOT || true)"
if [[ -n "$env_data_root" && "$env_data_root" != "$DATA_DIR" ]]; then
  warn ".env 中 DATA_ROOT=$env_data_root，与 systemd 的 $DATA_DIR 不一致；请确认该目录存在且属主为 $RUN_USER"
fi
grep -qE '^HF_ENDPOINT=' "$APP_DIR/.env" || warn "未设置 HF_ENDPOINT，本地 embedding 模型会去 HuggingFace 下载（国内通常失败），建议加 HF_ENDPOINT=https://hf-mirror.com"

# ------------------------------------------------------------ 2. Python 环境
detect_python() {
  local cand
  for cand in "${PYTHON_BIN}" python3.12 python3.11; do
    [[ -n "$cand" ]] || continue
    command -v "$cand" >/dev/null 2>&1 || continue
    "$cand" -c 'import venv' >/dev/null 2>&1 || continue
    command -v "$cand"
    return 0
  done
  return 1
}
PY="$(detect_python)" || die "找不到 Python 3.11/3.12，请先执行 deploy/baremetal/install.sh"

if [[ ! -x "$VENV/bin/python" ]]; then
  ok "创建虚拟环境：$VENV（$("$PY" -V 2>&1)）"
  "$PY" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"

ok "Python：$("$VENV/bin/python" -V 2>&1)"

if (( SKIP_DEPS == 0 )); then
  "$PIP" install --no-cache-dir -U pip setuptools wheel -i "$PIP_INDEX"

  install_torch_cpu() {
    ok "安装 CPU 版 PyTorch（不加这一步会拉到几 GB 的 CUDA 版本）"
    if "$PIP" install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; then
      return 0
    fi
    warn "PyTorch 官方 CPU 源不可用，改用阿里云 pytorch-wheels 镜像"
    "$PIP" install --no-cache-dir torch -f https://mirrors.aliyun.com/pytorch-wheels/cpu/ -i "$PIP_INDEX"
  }

  if [[ "${SKIP_LOCAL_EMBEDDING:-0}" == "1" ]]; then
    warn "SKIP_LOCAL_EMBEDDING=1：跳过 torch 与 sentence-transformers，部署后需在网页「设置」里改用远程 embedding"
    REQ_FILE="$(mktemp)"
    trap 'rm -f "$REQ_FILE"' EXIT
    grep -v '^sentence-transformers' backend/requirements.txt > "$REQ_FILE"
  else
    install_torch_cpu || die "PyTorch 安装失败。可改用 SKIP_LOCAL_EMBEDDING=1 重跑，并在网页设置里切换到远程 embedding"
    REQ_FILE="backend/requirements.txt"
  fi

  ok "安装后端依赖（约 3~4 GiB，首次较慢）"
  "$PIP" install --no-cache-dir -i "$PIP_INDEX" -r "$REQ_FILE"
  # 中文分词：Dockerfile 里是单独装的，这里保持一致
  "$PIP" install --no-cache-dir -i "$PIP_INDEX" jieba==0.42.1

  ok "安装飞书机器人依赖"
  "$PIP" install --no-cache-dir -i "$PIP_INDEX" -r feishu-bot/requirements.txt
else
  ok "跳过依赖安装（--skip-deps）"
fi

# ---------------------------------------------------------------- 3. 前端产物
DIST="$APP_DIR/frontend/dist"
if [[ ! -f "$DIST/index.html" ]]; then
  if command -v npm >/dev/null 2>&1; then
    ok "服务器上没有构建产物，用本机 npm 现场构建"
    ( cd "$APP_DIR/frontend" && npm ci --no-audit --no-fund && npm run build )
  else
    die "缺少 $DIST/index.html，且服务器上没有 npm。请在本机构建后上传：
  cd frontend && npm ci && npm run build
  scp -r frontend/dist root@<公网IP>:$APP_DIR/frontend/"
  fi
fi
ok "前端产物就绪：$DIST"

# SELinux：让 nginx 能读这个目录
if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" == "Enforcing" ]]; then
  chcon -R -t httpd_sys_content_t "$DIST" 2>/dev/null || warn "chcon 失败，如遇 403 请手动执行：chcon -R -t httpd_sys_content_t $DIST"
  setsebool -P httpd_can_network_connect 1 2>/dev/null || true
fi

# ------------------------------------------------------------------ 4. 迁移
ok "执行数据库迁移（以 $RUN_USER 身份）"
runuser -u "$RUN_USER" -- /bin/bash -c \
  "set -a; . '$APP_DIR/.env'; set +a; cd '$APP_DIR/backend' && '$VENV/bin/python' -m app.cli migrate"
ok "迁移完成"

# -------------------------------------------------------- 5. systemd 服务单元
ok "安装 systemd 服务"
install -m 0644 deploy/baremetal/knowbase-backend.service    /etc/systemd/system/knowbase-backend.service
install -m 0644 deploy/baremetal/knowbase-worker.service     /etc/systemd/system/knowbase-worker.service
install -m 0644 deploy/baremetal/knowbase-feishu-bot.service /etc/systemd/system/knowbase-feishu-bot.service
systemctl daemon-reload

# ------------------------------------------------------------------- 6. nginx
if [[ "${KEEP_NGINX_CONF:-0}" != "1" ]]; then
  NGINX_USER=nginx
  id -u nginx >/dev/null 2>&1 || NGINX_USER=www-data
  if [[ ! -f /etc/nginx/nginx.conf.knowbase-orig ]]; then
    cp -a /etc/nginx/nginx.conf /etc/nginx/nginx.conf.knowbase-orig
    ok "已备份原 nginx 主配置到 /etc/nginx/nginx.conf.knowbase-orig"
  fi
  cat > /etc/nginx/nginx.conf <<EOF
# 由 KnowBase deploy/baremetal/deploy.sh 生成：本机只跑一个站点。
# 原配置保存在 /etc/nginx/nginx.conf.knowbase-orig，恢复时覆盖回来即可。
user ${NGINX_USER};
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                    '\$status \$body_bytes_sent "\$http_referer" '
                    '"\$http_user_agent"';

    access_log /var/log/nginx/access.log main;
    sendfile on;
    keepalive_timeout 65;
    server_tokens off;

    include /etc/nginx/conf.d/*.conf;
}
EOF
fi

install -m 0644 deploy/baremetal/nginx-knowbase.conf /etc/nginx/conf.d/knowbase.conf

if ! nginx -t; then
  if [[ -f /etc/nginx/nginx.conf.knowbase-orig ]]; then
    cp -a /etc/nginx/nginx.conf.knowbase-orig /etc/nginx/nginx.conf
    warn "nginx 配置校验失败，已回滚主配置"
  fi
  die "nginx 配置有误，请检查 /etc/nginx/conf.d/knowbase.conf"
fi
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx 2>/dev/null || systemctl restart nginx
ok "nginx 已加载站点配置"

# --------------------------------------------------------------- 7. 启动服务
ok "启动/重启服务"
for unit in knowbase-backend knowbase-worker knowbase-feishu-bot; do
  systemctl enable "$unit.service" >/dev/null 2>&1 || true
  systemctl restart "$unit.service"
done

# --------------------------------------------------------------- 8. 健康检查
ok "等待后端就绪（最长 3 分钟）"
BACKEND_OK=0
deadline=$(( SECONDS + 180 ))
while (( SECONDS < deadline )); do
  if curl -fsS -o /dev/null http://127.0.0.1:9000/ 2>/dev/null; then
    BACKEND_OK=1
    break
  fi
  sleep 5
done

if (( BACKEND_OK == 0 )); then
  warn "后端未在预期时间内就绪，最近日志："
  journalctl -u knowbase-backend.service -n 40 --no-pager || true
  die "部署未完成"
fi
ok "后端已就绪"

if ! curl -fsS -o /dev/null http://127.0.0.1/ 2>/dev/null; then
  warn "通过 nginx 访问首页失败，请检查：nginx -t、journalctl -u nginx、$DIST 是否存在"
else
  ok "nginx 已能返回前端首页"
fi

systemctl --no-pager --lines=0 status knowbase-backend.service knowbase-worker.service knowbase-feishu-bot.service || true

# ------------------------------------------------------------------ 9. 收尾
public_ip="$(curl -fsS --max-time 3 http://100.100.100.200/latest/meta-data/eipv4 2>/dev/null || true)"
[[ -n "$public_ip" ]] || public_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$public_ip" ]] || public_ip="<服务器IP>"

cat <<EOF

部署完成：
  1) 浏览器打开 http://${public_ip}
  2) 首次进入会引导创建唯一账号
  3) 「设置」里填模型 API Key；飞书机器人在「设置 → 飞书机器人」里配

常用命令：
  systemctl status knowbase-backend knowbase-worker knowbase-feishu-bot
  journalctl -u knowbase-backend -f          # 后端日志
  journalctl -u knowbase-worker  -f          # worker 日志
  journalctl -u knowbase-feishu-bot -f       # 机器人日志
  systemctl restart knowbase-worker          # 改完 .env 后逐个重启生效

数据与备份：$DATA_DIR（sqlite/ uploads/ media/ chroma/ secrets/ backups/）
EOF
