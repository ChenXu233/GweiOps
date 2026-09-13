# Phase B3 子计划:iframe 页面协议

> 状态:已实施 | 母本:[docs/plan/README.md](README.md) Phase B(第三轮)
> 依据:platform-architecture §4.4 —— 复杂页面用 iframe 沙箱,插件自持 Web 资源,
> 经 engine 提供(将来鉴权令牌的挂钩点在 engine 侧),任意语言/技术栈可写,隔离干净。

## 设计要点

- 资产归 engine 服务:`GET /api/plugins/{name}/ui/{path}` 从插件目录的 `ui/`
  返回静态文件;插件代码永不进入前端 bundle;
- 前端固定命名空间路由 `/plugins/{manifest.name}`,渲染
  `<iframe sandbox="allow-scripts" src="/api/plugins/{name}/ui/{entry}">`——
  opaque origin 隔离,无法触碰主应用 DOM/存储;
- **已知边界(下轮)**:沙箱 opaque origin 下,插件页面直接 fetch engine API 属
  跨域,需要 postMessage 桥 + capability 收窄令牌(随认证阶段);
- 路径安全:manifest 校验 entry(禁绝对路径/`..`/反斜杠),engine resolve 后必须
  仍在 ui 目录内。

## B3-1 Engine

- [x] `manifest.py`:`UiPage(title, entry)` 数据类替代 ui_pages 裸透传;
      entry 校验:非空、无 `..` 段、非绝对路径、无反斜杠,缺省 index.html;
- [x] `registry.py`:发现时记录插件目录(`_dirs`),新增 `plugin_dir(name)`;
- [x] `plugins.py`:`GET /api/plugins/{name}/ui/{file_path:path}` ——
      安全 resolve → FileResponse(mimetype 猜测),插件/文件缺失 404,
      resolve 后越界 404(不泄露存在性);
- [x] `plugins/builtin/agents/observer/ui/index.html`:静态演示页
      (观测主题指标卡,中文);
- [x] `test_plugin_api.py` 增补:清单含 observer pages、资产 200 + text/html、
      路径穿越被拒、未知插件 404。

## B3-2 Frontend

- [x] `pages/plugins/[name].vue`:经 `/api/plugins` 解析清单找 page,
      渲染沙箱 iframe;插件/页面不存在时错误态;
- [x] `Plugin` 类型增可选 `pageTitle?`;`useRepoList.toPlugin` 映射首格 page;
- [x] marketplace 卡片:`plugin.pageTitle` 存在时显示"打开页面"链接
      → `/plugins/{id}`。

## B3-3 验证

- [x] 全量回归全绿;
- [x] 冒烟:engine 资产 200 + text/html;前端(USE_MOCK=false)
      `/plugins/observer-agent` 200 含 iframe,代理资产 200;
      `pnpm build:selfhost` 通过。

## B3-4 明确不做

postMessage 桥与能力令牌(随认证阶段)、插件资产构建工具链、scheduler 循环、
计费插件。
