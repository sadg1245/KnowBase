#!/usr/bin/env bash
# KnowBase 裸机部署 —— 系统初始化（每台机器只跑一次）
#
# 适用：阿里云 ECS / Alibaba Cloud Linux 3（RHEL8 系）、CentOS、RHEL、Ubuntu、Debian
# 目标规格：2 vCPU / 2 GiB 起步（会加 swap，否则装依赖和加载 embedding 模型容易 OOM）
#
# 做五件事：
#   1. 加 swap
#   2. 安装 Python 3.12 / 3.11（项目要求 ≥3.12，容器镜像用 3.11，两者都支持）
#   3. 安装并启动 Redis（Celery 队列 + 机器人状态）
#   4. 安装并启动 nginx（托管前端静态文件 + 反代 /api）
#   5. 创建运行用户 knowbase 与数据目录 /var/lib/knowbase
#
# 用法（root）：
#   sudo bash deploy/baremetal/install.sh
#   sudo BUILD_PYTHON=1 bash deploy/baremetal/install.sh   # 仓库里没有 3.12/3.11 时源码编译
#
# 幂等：可重复执行。

set -euo pipefail

SWAP_SIZE_MB="${SWAP_SIZE_MB:-4096}"
RUN_USER="${RUN_USER:-knowbase}"
RUN_GROUP="${RUN_GROUP:-$RUN_USER}"
DATA_DIR="${DATA_DIR:-/var/lib/knowbase}"
APP_DIR="${APP_DIR:-/opt/knowbase}"
BUILD_PYTHON="${BUILD_PYTHON:-0}"
PYTHON_SRC_VERSION="${PYTHON_SRC_VERSION:-3.12.7}"
PYTHON_BIN="${PYTHON_BIN:-}"

ok()   { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "请用 root 运行：sudo bash $0"
[[ -r /etc/os-release ]] || die "无法识别发行版（缺少 /etc/os-release）"
# shellcheck disable=SC1091
. /etc/os-release

case "${ID}${ID_LIKE:-}" in
  *alinux*|*centos*|*rhel*|*fedora*) PKG=dnf ;;
  *debian*|*ubuntu*)                 PKG=apt ;;
  *) die "未适配的发行版：${PRETTY_NAME:-unknown}" ;;
esac
ok "发行版：${PRETTY_NAME:-unknown}（包管理器 $PKG）"

# --------------------------------------------------------------- 1. 磁盘与 swap
free_mb=$(df -Pm / | awk 'NR==2 {print $4}')
(( free_mb >= 10240 )) || die "系统盘剩余 ${free_mb} MiB，不足 10 GiB（Python 依赖约 3~4 GiB）"
ok "系统盘可用：$(( free_mb / 1024 )) GiB"

swap_kb_now=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
want_kb=$(( SWAP_SIZE_MB * 1024 ))
if (( swap_kb_now >= want_kb )); then
  ok "swap 已满足要求（$(( swap_kb_now / 1024 )) MiB）"
elif [[ -f /swapfile ]]; then
  swapon /swapfile 2>/dev/null && ok "已启用现有 /swapfile" || warn "存在 /swapfile 但无法启用，请手动检查"
else
  ok "创建 ${SWAP_SIZE_MB} MiB swap"
  if ! fallocate -l "${SWAP_SIZE_MB}M" /swapfile 2>/dev/null; then
    warn "fallocate 不可用，改用 dd（较慢）"
    dd if=/dev/zero of=/swapfile bs=1M count="${SWAP_SIZE_MB}" status=progress
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
  ok "swap 已创建并写入 /etc/fstab"
fi

if [[ ! -f /etc/sysctl.d/99-knowbase.conf ]]; then
  printf 'vm.swappiness = 10\n' > /etc/sysctl.d/99-knowbase.conf
  sysctl --system >/dev/null
  ok "vm.swappiness 已设为 10"
fi

# ------------------------------------------------------------- 2. 基础工具链
ok "安装基础工具链与编译依赖"
if [[ "$PKG" == dnf ]]; then
  dnf install -y dnf-utils curl wget gcc gcc-c++ make tar xz
  dnf install -y zlib-devel bzip2-devel openssl-devel readline-devel sqlite-devel libffi-devel
else
  apt-get update
  apt-get install -y ca-certificates curl wget build-essential tar xz-utils
  apt-get install -y zlib1g-dev libbz2-dev libssl-dev libreadline-dev libsqlite3-dev libffi-dev
fi

# ------------------------------------------------------------------ 3. Python
detect_python() {
  local cand
  for cand in "${PYTHON_BIN}" python3.12 python3.11 python3; do
    [[ -n "$cand" ]] || continue
    command -v "$cand" >/dev/null 2>&1 || continue
    "$cand" -c 'import venv, ensurepip' >/dev/null 2>&1 || continue
    "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || continue
    command -v "$cand"
    return 0
  done
  return 1
}

PY=""
if PY="$(detect_python)"; then
  ok "已找到可用 Python：$PY（$("$PY" -V 2>&1)）"
else
  ok "尝试用包管理器安装 Python 3.12 / 3.11"
  if [[ "$PKG" == dnf ]]; then
    dnf install -y python3.12 python3.12-devel 2>/dev/null || true
    dnf install -y python3.11 python3.11-devel 2>/dev/null || true
  else
    apt-get install -y python3.12 python3.12-venv python3.12-dev 2>/dev/null || true
    apt-get install -y python3.11 python3.11-venv python3.11-dev 2>/dev/null || true
  fi
  if PY="$(detect_python)"; then
    ok "已安装 Python：$PY（$("$PY" -V 2>&1)）"
  elif [[ "$BUILD_PYTHON" != "1" ]]; then
    die "仓库里没有 Python 3.11/3.12。两个选择：
  1) 用 uv 装独立解释器（推荐，不用编译）：
       curl -LsSf https://astral.sh/uv/install.sh | sh
       /root/.local/bin/uv python install 3.12
       sudo PYTHON_BIN=/root/.local/bin/python3.12 bash $0
  2) 让本脚本源码编译（约 10~20 分钟，需已加 swap）：
       sudo BUILD_PYTHON=1 bash $0"
  else
    ok "源码编译 Python ${PYTHON_SRC_VERSION}（会花十几分钟）"
    mkdir -p /usr/local/src && cd /usr/local/src
    src="Python-${PYTHON_SRC_VERSION}.tgz"
    if ! curl -fL --retry 3 -o "$src" "https://mirrors.huaweicloud.com/python/${PYTHON_SRC_VERSION}/${src}"; then
      curl -fL --retry 3 -o "$src" "https://www.python.org/ftp/python/${PYTHON_SRC_VERSION}/${src}"
    fi
    tar xf "$src"
    cd "Python-${PYTHON_SRC_VERSION}"
    # 不用 --enable-optimizations：PGO 会让 2 核机器编译时间翻几倍，收益有限
    ./configure --prefix=/usr/local --with-ensurepip=install
    make -j"$(nproc)"
    make altinstall
    hash -r
    PY="$(detect_python)" || die "源码编译完成但仍未找到可用 Python，请检查 /usr/local/bin/python3.12"
    ok "已编译安装：$PY（$("$PY" -V 2>&1)）"
  fi
fi

# ------------------------------------------------------------------- 4. Redis
ok "检查 Redis"
if ! command -v redis-server >/dev/null 2>&1; then
  if [[ "$PKG" == dnf ]]; then
    dnf install -y redis || dnf install -y redis6 || dnf install -y valkey || die "Redis 安装失败，请手动安装后重跑"
  else
    apt-get install -y redis-server || die "Redis 安装失败，请手动安装后重跑"
  fi
fi

REDIS_UNIT=""
for unit in redis redis-server valkey; do
  if systemctl cat "${unit}.service" >/dev/null 2>&1; then
    REDIS_UNIT="$unit"
    break
  fi
done
[[ -n "$REDIS_UNIT" ]] || die "找不到 Redis 的 systemd 服务，请手动确认后重跑"
systemctl enable --now "$REDIS_UNIT"
ok "Redis 服务已启动：${REDIS_UNIT}.service"

# ------------------------------------------------------------------- 5. nginx
ok "检查 nginx"
if ! command -v nginx >/dev/null 2>&1; then
  if [[ "$PKG" == dnf ]]; then
    dnf install -y nginx || die "nginx 安装失败，请手动安装后重跑"
  else
    apt-get install -y nginx || die "nginx 安装失败，请手动安装后重跑"
  fi
fi
systemctl enable nginx
ok "nginx 已安装：$(nginx -v 2>&1)"

# SELinux：默认策略会挡住 nginx 反代到本机 9000 端口
if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" == "Enforcing" ]]; then
  warn "SELinux 处于 Enforcing，放行 nginx 的网络访问与静态目录"
  setsebool -P httpd_can_network_connect 1 || warn "setsebool 失败，请手动执行：setsebool -P httpd_can_network_connect 1"
  ok "SELinux 已配置"
fi

# ------------------------------------------------------------ 6. 用户与目录
if id "$RUN_USER" >/dev/null 2>&1; then
  ok "运行用户已存在：$RUN_USER"
else
  nologin=/sbin/nologin
  [[ -x "$nologin" ]] || nologin=/usr/sbin/nologin
  useradd --system --shell "$nologin" --home-dir "$DATA_DIR" --create-home "$RUN_USER"
  ok "已创建系统用户：$RUN_USER"
fi

install -d -m 0755 -o root -g root "$APP_DIR"
install -d -m 0700 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR"
for sub in sqlite uploads media secrets backups huggingface; do
  install -d -m 0750 -o "$RUN_USER" -g "$RUN_GROUP" "$DATA_DIR/$sub"
done
ok "目录已就绪：代码 $APP_DIR，数据 $DATA_DIR（属主 $RUN_USER）"

# ---------------------------------------------------------------- 7. 自检输出
echo
ok "环境自检"
printf 'Python: %s\n' "$PY ($("$PY" -V 2>&1))"
printf 'Redis : %s\n' "$(redis-server --version | head -1)"
printf 'nginx : %s\n' "$(nginx -v 2>&1)"
printf 'CPU: %s 核   内存: %s   swap: %s\n' \
  "$(nproc)" \
  "$(awk '/^MemTotal:/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)" \
  "$(awk '/^SwapTotal:/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
df -h / | tail -1

if systemctl is-active --quiet firewalld 2>/dev/null; then
  warn "firewalld 正在运行：需要放行 80/443，例如 firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload"
fi

cat <<EOF

下一步：
  1) 把代码放到 $APP_DIR（git clone 或上传，注意排除 .venv / node_modules）
  2) cp $APP_DIR/deploy/baremetal/env.example $APP_DIR/.env && vi $APP_DIR/.env
     - 填 DEEPSEEK_API_KEY（也可以首次进页面后在「设置」里填）
     - HF_ENDPOINT 已预置为国内镜像
  3) 本机构建前端并上传：cd frontend && npm ci && npm run build，然后上传 frontend/dist
  4) sudo bash $APP_DIR/deploy/baremetal/deploy.sh

安全组只需放行 22 和 80（有域名再加 443）；9000 只监听 127.0.0.1，不需要放行。
EOF
