# Phase C 子计划:前端单应用模式门控

> 状态:已实施(`5cf6cb1` 子计划,`58d2823` 门控,`9468b7d` 清理) | 母本:[docs/plan/README.md](README.md) Phase C

## 探索结论

`index.vue` 是 SaaS 营销落地页(假 logo/假数据/GitHub OAuth 入口),selfhost 用户
落地看到它不符合"selfhost 是特化前端"的定位 → selfhost 档 `/` 直接重定向进
`/dashboard`,saas 档才显示营销页。README 许可证清单中 dashboard 的 FSL-1.1 标注
为旧 React 面板遗留,按三层协议改为 frontend: AGPL-3.0。

## C1 模式门控

- [x] `nuxt.config.ts`:runtimeConfig.public 增
      `mode: process.env.NUXT_PUBLIC_DEPLOYMENT_MODE || 'selfhost'`;
- [x] 新增 `middleware/mode.global.ts`:全局路由中间件,`to.meta.modes` 存在且
      不含当前 mode 时 `navigateTo('/dashboard', { replace: true })`;
- [x] `pages/index.vue` / `pages/login.vue`:`definePageMeta({ modes: ['saas'] })`
      (index 保留 layout:false);
- [x] `layouts/default.vue`:侧栏底部按 mode 分支——saas 显示租户卡片,
      selfhost 显示 Self-hosted 徽标;navItems 保留 modes 字段机制。

## C2 卫生清理

- [x] 删除 `dashboard/` 目录(仅 .next + node_modules 尸体);
- [x] `frontend/package.json` 删除 `dev:saas` / `build:saas` 死脚本;
- [x] README:删 "### dashboard/" 小节与 FSL 许可行,改 `frontend/: AGPL-3.0`;
- [x] 新增 `frontend/LICENSE`(AGPL-3.0,复制自根 LICENSE,platform-architecture
      §1 待办);
- [x] `docker-compose.prod.yml` web env 显式 `NUXT_PUBLIC_DEPLOYMENT_MODE: "selfhost"`。

## C3 验证

- [x] `pnpm build:selfhost` 构建通过;
- [x] dev 冒烟(3100 端口,3000 被其他项目占用):selfhost 档 `GET /` 重定向
      `/dashboard`;saas 档 `GET /` 200 含"免费开始"、`/login` 200;
- [x] compose/CI/README 无残留引用。
