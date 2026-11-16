#!/usr/bin/env bash
# 引擎校验:先确认 lock 与 pyproject 一致,再让 engine-tests.py 查契约、迁移并
# 跑测试(仓库根,pytest 的 testpaths 在 engine/pyproject.toml 里)。
#
# 不设 GWEI_TEST_DATABASE_URL:需要真实 Postgres 的用例自己跳过。它们不是
# "悄悄没跑",靠门控变量显式 skip,日志里数得出来。
#
# 注意 uv 的一个脾气:`uv sync --frozen` 不比对 pyproject 与 lock,只按 lock
# 装包。改了依赖却忘了 uv lock 时它是静的,静到等 CI 用旧依赖测一份新代码。
# 所以 --frozen 之外还要一次 `uv lock --check`。
#
# 工作目录必须是仓库根:不少用例按相对路径找 plugins/,换目录会挂。
set -euo pipefail

cd "$(dirname "$0")/.."

# uv 不预装:这一段跑在 python:3.12 里。装法照官方安装脚本,版本钉死——
# lock 跟着 uv 的解析规则走,换版本可能整份重写。
#
# 拉安装脚本要重试:这一段只有一次 HTTPS 请求,失败即整阶段红。构建节点到
# astral.sh 的 TLS 偶发中断(curl 35),与代码无关,重跑才绿——那种红法会让人
# 去翻一份没有问题的提交。--retry 覆盖超时与连接被断,不动成功路径。
UV_VERSION="${UV_VERSION:-0.13.8}"
if ! command -v uv >/dev/null 2>&1; then
  curl -fsSL --retry 5 --retry-delay 2 --retry-all-errors \
    "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi
export PATH="${HOME}/.local/bin:${PATH}"

uv lock --check --directory engine
uv sync --frozen --extra dev --directory engine

# --project 指定项目,工作目录留在这里不切
uv run --project engine python .ci/engine-tests.py
