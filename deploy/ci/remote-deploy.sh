#!/usr/bin/env bash
# 远端部署:在目标机上把服务切到本次 tag 的镜像,验健康;失败自动回滚。
#
# 本脚本由 CI 经 SSH stdin 送入目标机执行,不在 CI 容器里跑,也不存在目标机上。
# TAG / REPO_SLUG 由调用方(deploy-via-ssh.sh)在脚本头部注入。
# 凭据(.env.prod)始终留在目标机,不经过流水线。
#
# 切换前把当前 engine/web 的镜像记到 ROLLBACK_FILE,失败时按它还原。
set -euo pipefail

PROJECT_DIR="${DEPLOY_PROJECT_DIR:-/opt/gwei}"
COMPOSE_FILE="${DEPLOY_COMPOSE_FILE:-docker-compose.deploy.yml}"
ROLLBACK_FILE="${DEPLOY_ROLLBACK_FILE:-$PROJECT_DIR/.deploy-before.env}"
ENV_FILE="${DEPLOY_ENV_FILE:-$PROJECT_DIR/.env.prod}"
HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_ATTEMPTS="${DEPLOY_HEALTH_ATTEMPTS:-30}"
HEALTH_INTERVAL="${DEPLOY_HEALTH_INTERVAL:-2}"

: "${TAG:?缺少要部署的 tag}"
: "${REPO_SLUG:?缺少仓库 slug}"

cd "$PROJECT_DIR"
[[ -f $ENV_FILE ]] || { echo "缺少 $ENV_FILE" >&2; exit 1; }
[[ -f $COMPOSE_FILE ]] || { echo "缺少 $COMPOSE_FILE" >&2; exit 1; }

# .env.prod 里的凭据与镜像地址导出给 docker compose 用。
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
: "${CNB_REGISTRY:?需在 .env.prod 里设置 CNB_REGISTRY}"
: "${CNB_REGISTRY_USER:?需在 .env.prod 里设置 CNB_REGISTRY_USER}"
: "${CNB_REGISTRY_TOKEN:?需在 .env.prod 里设置 CNB_REGISTRY_TOKEN}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

health() {
  local i
  for ((i=1; i<=HEALTH_ATTEMPTS; i++)); do
    if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

# 记录切换前的镜像。镜像可能被手工切过,每次都重新记。
snapshot_images() {
  local engine_image web_image
  engine_image=$(compose ps -q engine 2>/dev/null | xargs -r docker inspect -f '{{.Config.Image}}' 2>/dev/null | head -1)
  web_image=$(compose ps -q web 2>/dev/null | xargs -r docker inspect -f '{{.Config.Image}}' 2>/dev/null | head -1)
  {
    echo "GWEI_ENGINE_IMAGE=${engine_image:-}"
    echo "GWEI_WEB_IMAGE=${web_image:-}"
  } > "$ROLLBACK_FILE"
}

# 部署失败要能被看见。这条必须由部署脚本发,不能由引擎发:失败时它可能正不可用,
# 或者正在被换成新版本。
report_alert() {
  local title="$1"
  local detail="$2"
  local token="${ALERTMANAGER_WEBHOOK_TOKEN:-}"
  local url="${DEPLOY_ALERT_URL:-http://127.0.0.1:8000/webhook/alertmanager}"
  if [ -z "$token" ]; then
    echo "    没配 ALERTMANAGER_WEBHOOK_TOKEN,这条失败不会变成议题" >&2
    return 0
  fi
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  curl -fsS -m 5 -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "X-Gwei-Token: $token" \
    -d "{\"alerts\":[{\"status\":\"firing\",\"fingerprint\":\"deploy-$TAG\",\"labels\":{\"alertname\":\"deploy_failed\",\"service\":\"gwei-engine\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"$title\",\"description\":\"$detail\"},\"startsAt\":\"$now\"}]}" \
    >/dev/null 2>&1 \
    && echo "    已报成议题(见议题板的\"等我\")" \
    || echo "    上报失败:引擎可能也不可用,去看 .deploy-before.env 与 compose logs" >&2
}

rollback() {
  echo "==> 部署未通过,开始回滚" >&2
  report_alert "部署 $TAG 失败,已回滚" \
    "健康检查未通过或部署中断;上一版镜像已恢复。切换前的镜像记在 .deploy-before.env"
  if [[ -f $ROLLBACK_FILE ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ROLLBACK_FILE"; set +a
    compose up -d --pull never --no-build || true
  fi
  compose ps || true
  compose logs --tail 50 engine || true
}

upsert() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# 按 digest 钉死,不按 tag:tag 会移动,一旦这次拉到的镜像起不来,
# 回滚点里记的若是同一个 tag,回滚就是再拉一遍那个坏镜像。
resolve_digest() {
  docker manifest inspect -v "$1" 2>/dev/null | python3 -c "import json,sys;d=json.load(sys.stdin);x=d[0] if isinstance(d,list) else d;print((x.get('Descriptor') or {}).get('digest',''))" 2>/dev/null || true
}

ENGINE_TAG="${CNB_REGISTRY}/${REPO_SLUG}:${TAG}"
WEB_TAG="${CNB_REGISTRY}/${REPO_SLUG}:${TAG}-web"
D_ENGINE="$(resolve_digest "$ENGINE_TAG")"
D_WEB="$(resolve_digest "$WEB_TAG")"
if [ -n "$D_ENGINE" ] && [ -n "$D_WEB" ]; then
  ENGINE_IMAGE="${CNB_REGISTRY}/${REPO_SLUG}@${D_ENGINE}"
  WEB_IMAGE="${CNB_REGISTRY}/${REPO_SLUG}@${D_WEB}"
else
  # 读不到 digest 就退回 tag:那种情况下宁可部署,也不要因为探测失败而停摆
  ENGINE_IMAGE="$ENGINE_TAG"
  WEB_IMAGE="$WEB_TAG"
fi
upsert GWEI_ENGINE_IMAGE "$ENGINE_IMAGE"
upsert GWEI_WEB_IMAGE "$WEB_IMAGE"
# 让本次 compose 用到刚写入的镜像(而不是 .env.prod 里的旧值)。
export GWEI_ENGINE_IMAGE="$ENGINE_IMAGE" GWEI_WEB_IMAGE="$WEB_IMAGE"

trap rollback ERR

echo "==> 登录制品库"
printf '%s' "$CNB_REGISTRY_TOKEN" | docker login "$CNB_REGISTRY" -u "$CNB_REGISTRY_USER" --password-stdin

snapshot_images

echo "==> 拉取镜像"
compose pull

# 迁移只进不退:引擎容器的 entrypoint 会 alembic upgrade head,回滚镜像不会把
# schema 退回去。所以切换之前先留一份库,失败时至少能按它重建。
echo "==> 迁移前备份"
mkdir -p "$PROJECT_DIR/backups"
BACKUP="$PROJECT_DIR/backups/gwei-$(date +%Y%m%d-%H%M%S).sql.gz"
if compose exec -T postgres pg_dump -U gwei gwei 2>/dev/null | gzip > "$BACKUP"; then
  echo "    $BACKUP ($(du -h "$BACKUP" | cut -f1))"
else
  # 备份失败不拦部署:它不在恢复目标里,但要说出来,不能悄悄没有。
  echo "    备份失败,继续部署(这份备份不是部署的前置)" >&2
fi
# 只留最近 10 份
ls -1t "$PROJECT_DIR"/backups/*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f

# 不 force-recreate:compose 只重建镜像变了的服务(engine/web),
# postgres/redis 镜像没变就不动,避免每次部署都把数据库重启一遍。
echo "==> 切换容器"
compose up -d --remove-orphans

echo "==> 健康检查: $HEALTH_URL"
if ! health; then
  echo "健康检查未通过" >&2
  exit 1
fi

trap - ERR
echo "==> 部署成功:${TAG}"
compose ps
