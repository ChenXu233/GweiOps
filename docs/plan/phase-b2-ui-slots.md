# Phase B2 子计划:UI 插槽协议 v1 + 第一个真实前后端接口

> 状态:已实施 | 母本:[docs/plan/README.md](README.md) Phase B(第二轮)
> 依据:platform-architecture §4.4(UI 扩展 = 声明式 schema 由核心渲染 + iframe 沙箱)
> 与 §5 第 5 步。

## 探索结论

前端真实模式(`USE_MOCK=false`)的 `/api/*` 请求打在 Nuxt 自身,无代理——生产
compose 里前后端通路是断的。本轮以 Nitro 服务端代理打通(同源,免除 CORS),
并落地第一个真实接口 `GET /api/plugins`(marketplace 页早已在调用)。

## B2-1 Engine

- [x] `manifest.py` 增 ui 字段:
  - `ui.widgets[]`:slot(必填)/ kind(metric|list)/ span(1-4)/ title /
    metrics[label,value,sub?,variant?](metric)/ items[text](list);非法值拒绝;
  - `ui.pages[]`:v1 仅预留透传(iframe 资产服务下轮);
- [x] 新增 `engine/api/routes/plugins.py`:
  - `GET /api/plugins` → 全部清单(name/version/type/description/capabilities/
    widgets/pages);注册表未发现时返回 [];
  - `GET /api/plugins/widgets?slot=...` → 该槽位 widget(附 plugin 名);
- [x] `app.py` 注册路由;
- [x] observer yaml 加演示 widget(`dashboard.bento`,静态数据 v1——观测数据
  接口下轮接入);
- [x] 测试 `test_plugin_api.py`(无 DB):真实 builtin 发现 → 列表含
  sensor-agent;槽位查询返回 observer widget;未知槽位返回空。

## B2-2 Frontend

- [x] `apps/selfhost/server/api/[[...path]].ts`:Nitro 同源代理 →
  `engineUrl`(NUXT_ENGINE_URL,缺省 http://localhost:8000)+ event.path,
  方法/体透传——prod/dev 统一 `/api` 相对路径,CORS 免除;
- [x] `nuxt.config.ts` runtimeConfig 增 `engineUrl`;
- [x] core:`PluginWidget` 类型;`PluginsApi.widgets(slot)`;
  `PluginWidgetCard.vue`(metric→MetricCard,list→行列表);
  mock 增 `mockPluginWidgets`;
- [x] `usePluginWidgets(slot)`:USE_MOCK 走 mock,真实模式失败**静默降级为空**
  (插槽是增强,不破坏 dashboard);
- [x] `dashboard.vue`:BentoGrid 末尾渲染插件 widget(span 透传);
- [x] `useRepoList.ts` 真实分支:engine DTO → 既有 Plugin 形状映射
  (icon 🧩 / author official / installed true / price null),marketplace 真实数据即通。

## B2-3 验证

- [x] 全量回归全绿(新增 plugin_api 测试);
- [x] 冒烟:engine `/api/plugins`、`/api/plugins/widgets?slot=dashboard.bento`
  返回真实清单;前端(USE_MOCK=false)`/api/plugins` 经代理返回同 JSON,
  `/dashboard` 200;`pnpm build:selfhost` 通过。

## B2-4 明确不做

iframe 页面资产服务与鉴权代理(pages 字段预留)、scheduler 循环、自动 Scope
注册、gRPC server、计费插件。
