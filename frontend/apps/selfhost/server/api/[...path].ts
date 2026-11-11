// Nitro 同源代理:/api/** → engine(NUXT_ENGINE_URL,缺省 http://localhost:8000)。
// 前端统一用相对路径 /api,由此在服务端转发,天然规避 CORS。
const allowedMethods = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])

export default defineEventHandler(async (event) => {
  const method = event.method.toUpperCase()
  if (!allowedMethods.has(method)) {
    throw createError({ statusCode: 405, statusMessage: 'Method Not Allowed' })
  }

  const { engineUrl, engineToken } = useRuntimeConfig()
  const target = `${engineUrl}${event.path}`

  const headers = new Headers()
  const auth = getHeader(event, 'authorization')
  if (auth) headers.set('authorization', auth)
  // 控制台令牌只存在服务端:浏览器不带令牌,由这里补上。
  // 浏览器自己带了就尊重它(例如以后接入真正的登录)。
  if (!getHeader(event, 'x-gwei-token')) {
    const token = (engineToken as string) || ''
    if (token) headers.set('x-gwei-token', token)
  }
  const contentType = getHeader(event, 'content-type')
  if (contentType) headers.set('content-type', contentType)

  try {
    return await $fetch(target, {
      method: method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
      headers,
      body: ['GET', 'HEAD'].includes(method) ? undefined : await readRawBody(event),
    })
  } catch (err) {
    // 上游的 4xx/5xx 要原样回给浏览器:422 里带着"哪个字段为什么不合法",
    // 吞成 Nitro 的 unhandled error 等于把原因变成 500。
    const e = err as { status?: number; statusText?: string; data?: unknown }
    throw createError({
      statusCode: e.status || 502,
      statusMessage: e.statusText || 'Upstream error',
      data: e.data,
    })
  }
})
