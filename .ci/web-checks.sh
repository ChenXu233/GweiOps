#!/usr/bin/env bash
# 前端校验:按锁文件装依赖 → 构建 → 类型检查。
#
# 先 build 再 vue-tsc,顺序不能反:Nuxt 的类型别名、自动导入、组件声明都在
# `nuxt prepare` 产出的 .nuxt/tsconfig.json 里,没有它 vue-tsc 只会报一堆
# "找不到导入"。build 顺带完成 prepare。
#
# node 与 pnpm 不在这里装:这一段的镜像已经是 node:22 + pnpm 10.15。
set -euo pipefail

cd "$(dirname "$0")/../frontend"

pnpm install --frozen-lockfile --prefer-offline
pnpm build:selfhost
./apps/selfhost/node_modules/.bin/vue-tsc --noEmit -p apps/selfhost/.nuxt/tsconfig.json
