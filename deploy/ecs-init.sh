#!/usr/bin/env bash
# KnowBase ECS 初始化脚本
#
# 适用：阿里云 ECS（Alibaba Cloud Linux 3 / CentOS / RHEL / Ubuntu / Debian）
# 目标规格：2 vCPU / 2 GiB 起步
#
# 做四件事：安装 Docker + Compose 插件、配置镜像加速、加 swap、限制 Docker 日志体积。
#
# 用法（root）：
#   sudo ACR_MIRROR=https://xxxx.mirror.aliyuncs.com bash deploy/ecs-init.sh
#   # 不传 ACR_MIRROR 就跳过镜像加速配置
#
# 幂等：重复执行不会重复创建 swap；改写 daemon.json 前会先备份。

set -euo pipefail

SWAP_SIZE_MB="${SWAP_SIZE_MB:-4096}"
ACR_MIRROR="${ACR_MIRROR:-}"

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

# --------------------------------------------------------------- 1. Docker
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "Docker 与 Compose 插件已安装：$(docker --version)"
else
  ok "安装 Docker + Compose 插件（走阿里云镜像站）"
  if [[ "$PKG" == dnf ]]; then
    dnf install -y dnf-utils curl
    dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
    # Alibaba Cloud Linux 3 的 $releasever 是 3，而 docker-ce 仓库只有 7/8/9，必须改写
    [[ -f /etc/yum.repos.d/docker-ce.repo ]] && sed -i 's/\$releasever/8/' /etc/yum.repos.d/docker-ce.repo
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://mirrors.aliyun.com/docker-ce/linux/ubuntu ${UBUNTU_CODENAME:-${VERSION_CODENAME}} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
fi

systemctl enable --now docker

# -------------------------------------------------------- 2. 镜像加速与日志
if [[ -n "$ACR_MIRROR" ]]; then
  ok "写入 /etc/docker/daemon.json（镜像加速：$ACR_MIRROR）"
  mkdir -p /etc/docker
  if [[ -f /etc/docker/daemon.json ]]; then
    cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s)"
    warn "已备份原 daemon.json"
  fi
  cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["${ACR_MIRROR}"],
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
  systemctl restart docker
else
  warn "未提供 ACR_MIRROR，跳过镜像加速（国内直连 Docker Hub 拉镜像可能非常慢）"
  warn "加速地址：容器镜像服务 ACR 控制台 → 镜像工具 → 镜像加速器"
  warn "补配方式：sudo ACR_MIRROR=https://xxxx.mirror.aliyuncs.com bash $0"
fi

# ------------------------------------------------------------------- 3. swap
swap_kb_now=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
want_kb=$(( SWAP_SIZE_MB * 1024 ))

if (( swap_kb_now >= want_kb )); then
  ok "swap 已满足要求（$(( swap_kb_now / 1024 )) MiB）"
elif [[ -f /swapfile ]]; then
  if swapon /swapfile 2>/dev/null; then
    ok "已启用现有 /swapfile"
  else
    warn "存在 /swapfile 但无法启用（可能已挂载或已损坏），请手动检查后重跑"
  fi
else
  free_mb=$(df -Pm / | awk 'NR==2 {print $4}')
  need_mb=$(( SWAP_SIZE_MB + 2048 ))
  (( free_mb >= need_mb )) || die "系统盘剩余 ${free_mb} MiB，不足（swap 加镜像至少需要约 ${need_mb} MiB）"
  ok "创建 ${SWAP_SIZE_MB} MiB swap（完成后系统盘约剩 $(( free_mb - SWAP_SIZE_MB )) MiB）"
  if ! fallocate -l "${SWAP_SIZE_MB}M" /swapfile 2>/dev/null; then
    warn "fallocate 不可用，改用 dd（较慢）"
    dd if=/dev/zero of=/swapfile bs=1M count="${SWAP_SIZE_MB}" status=progress
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
  ok "swap 已创建并写入 /etc/fstab（重启后自动挂载）"
fi

# 内存吃紧时优先用 swap，但尽量不把热数据换出去
if [[ ! -f /etc/sysctl.d/99-knowbase.conf ]]; then
  printf 'vm.swappiness = 10\n' > /etc/sysctl.d/99-knowbase.conf
  sysctl --system >/dev/null
  ok "vm.swappiness 已设为 10"
fi

# ------------------------------------------------------------------ 4. 自检
echo
ok "环境自检"
docker --version
docker compose version
printf 'CPU: %s 核   内存: %s   swap: %s\n' \
  "$(nproc)" \
  "$(awk '/^MemTotal:/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)" \
  "$(awk '/^SwapTotal:/ {printf "%.1f GiB", $2/1048576}' /proc/meminfo)"
df -h / | tail -1

cat <<'EOF'

下一步：
  1) 把代码放到 /opt/knowbase（git clone 或 scp）
  2) cd /opt/knowbase && cp .env.example .env && vi .env
     - 填 DEEPSEEK_API_KEY
     - 加 HF_ENDPOINT=https://hf-mirror.com
     - CORS_ORIGINS 改成 http://<公网IP>:3000
  3) bash deploy/deploy.sh

安全组只需放行 22 / 3000（有域名再加 80、443），不要放行 9000 / 9001 / 6379。
EOF
