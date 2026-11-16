#!/usr/bin/env bash
# 部署入口:在 CI 容器里跑,把仓库的 compose 与部署脚本经 SSH 送到目标机。
#
# 凭据由 .cnb.yml 的 imports 从密钥仓库注入为环境变量(本脚本不打印它们):
#   REMOTE_HOST / REMOTE_PORT / REMOTE_USER / REMOTE_KEY
#   PROXY_HOST / PROXY_PORT / PROXY_USER / PROXY_KEY   # 内网目标机才需要
#
# 数据流走 SSH stdin,不经过 CI 的 exports/settings 变量替换:
#   - compose 文件:base64 后在远端解码落盘(目标机不需要访问 CNB);
#   - 部署脚本:TAG / REPO_SLUG 以 bash 赋值写在头部,再经 stdin 送过去执行。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

: "${REMOTE_HOST:?需要 REMOTE_HOST}"
: "${REMOTE_USER:?需要 REMOTE_USER}"
: "${REMOTE_KEY:?需要 REMOTE_KEY}"
TAG="${1:?缺少要部署的 tag}"
REPO_SLUG="${2:?缺少仓库 slug}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf '%s\n' "$REMOTE_KEY" > "$TMP/id_ed25519"
chmod 600 "$TMP/id_ed25519"

SSH_OPTS=(
  -i "$TMP/id_ed25519"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=15
  -p "${REMOTE_PORT:-22}"
)

# 内网目标机:用 ProxyCommand 经跳板机连过去。跳板机的私钥单独落一个文件。
if [[ -n "${PROXY_HOST:-}" ]]; then
  : "${PROXY_USER:?配了 PROXY_HOST 就必须给 PROXY_USER}"
  : "${PROXY_KEY:?配了 PROXY_HOST 就必须给 PROXY_KEY}"
  printf '%s\n' "$PROXY_KEY" > "$TMP/proxy_id"
  chmod 600 "$TMP/proxy_id"
  SSH_OPTS+=(-o "ProxyCommand=ssh -i $TMP/proxy_id -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -W %h:%p -p ${PROXY_PORT:-22} ${PROXY_USER}@${PROXY_HOST}")
fi

SSH=(ssh "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}")

echo "==> 连接 ${REMOTE_USER}@${REMOTE_HOST},部署 ${REPO_SLUG}:${TAG}"

# 先把自包含的 compose 文件送到目标机。目标机上只放这一份编排,不叠加别的文件。
"${SSH[@]}" 'mkdir -p /opt/gwei && base64 -d > /opt/gwei/docker-compose.deploy.yml' \
  < "$ROOT/deploy/docker-compose.deploy.yml"

# 部署脚本经 stdin 送过去;TAG / REPO_SLUG 用 bash %q 转义后写在最前面。
{
  printf 'TAG=%q\n' "$TAG"
  printf 'REPO_SLUG=%q\n' "$REPO_SLUG"
  cat "$ROOT/deploy/ci/remote-deploy.sh"
} | "${SSH[@]}" 'bash -s'
