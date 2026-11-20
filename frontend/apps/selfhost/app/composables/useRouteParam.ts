// 页面自己的路径参数。
//
// 带工作区段的地址(`/workspaces/{slug}/issues/{id}`)由
// `pages/workspaces/[slug]/[...path].vue` 把后面那一段解析成页面挂上:页面组件是
// 被它当子组件渲染的,`useRoute()` 读到的是那条 catch-all 路由的参数 —— 自己的
// `id` / `name` 不在里面。catch-all 把解析出来的那一条的 params provide 下来,
// 这里先读路由自己的,没有再看它:直接命中 `/issues/{id}` 与带工作区段两种地址
// 因此拿到同一个值。
import type { ComputedRef, InjectionKey } from 'vue'

type RouteParams = Record<string, string | string[]>

export const SCOPED_ROUTE_PARAMS: InjectionKey<ComputedRef<RouteParams>> = Symbol(
  'gwei:scoped-route-params',
)

export function useRouteParam(name: string): ComputedRef<string> {
  const route = useRoute()
  const scoped = inject(SCOPED_ROUTE_PARAMS, null)
  return computed(() => {
    const value = route.params[name] ?? scoped?.value[name] ?? ''
    return Array.isArray(value) ? String(value[0] ?? '') : String(value)
  })
}
