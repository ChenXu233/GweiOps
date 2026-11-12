// Nitro 同源代理:/api/** → engine(NUXT_ENGINE_URL,缺省 http://localhost:8000)。
// 前端统一用相对路径 /api,由此在服务端转发,天然规避 CORS。
//
// 这里**不注入任何凭据**:浏览器带的是自己的会话 cookie,原样转给引擎,
// 由引擎判断你是谁。以前这里替浏览器塞一个 operate 令牌,那样登录页就没有意义了。
const allowedMethods = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])

export default defineEventHandler(async (event) => {
  const method = event.method.toUpperCase()
  if (!allowedMethods.has(method)) {
    throw createError({ statusCode: 405, statusMessage: 'Method Not Allowed' })
  }

  const { engineUrl } = useRuntimeConfig()
  const target = `${engineUrl}${event.path}`

  const headers = new Headers()
  const cookie = getHeader(event, 'cookie')
  if (cookie) headers.set('cookie', cookie)
  const auth = getHeader(event, 'authorization')
  if (auth) headers.set('authorization', auth)
  const contentType = getHeader(event, 'content-type')
  if (contentType) headers.set('content-type', contentType)
  // 引擎用它决定 cookie 要不要加 Secure
  headers.set('x-forwarded-proto', getHeader(event, 'x-forwarded-proto') || 'http')

  try {
    const res = await $fetch.raw(target, {
      method: method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
      headers,
      body: ['GET', 'HEAD'].includes(method) ? undefined : await readRawBody(event),
      ignoreResponseError: true,
    })

    // 登录、登出、改密码都会下发 Set-Cookie;不转发出去,登录就永远不生效
    const cookies = res.headers.getSetCookie?.() ?? []
    if (cookies.length) setResponseHeader(event, 'set-cookie', cookies)

    if (res.status >= 400) {
      throw createError({
        statusCode: res.status,
        statusMessage: res.statusText || 'Upstream error',
        data: res._data,
      })
    }
    return res._data
  } catch (err) {
    // 上游的 4xx/5xx 要原样回给浏览器:422 里带着"哪个字段为什么不合法",
    // 吞成 Nitro 的 unhandled error 等于把原因变成 500。
    const e = err as { statusCode?: number; status?: number; statusText?: string; data?: unknown }
    if (e.statusCode) throw err
    throw createError({
      statusCode: e.status || 502,
      statusMessage: e.statusText || 'Upstream error',
      data: e.data,
    })
  }
})
