// Nitro 同源代理:/api/** → engine(NUXT_ENGINE_URL,缺省 http://localhost:8000)。
// 前端统一用相对路径 /api,由此在服务端转发,天然规避 CORS。
const allowedMethods = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])

export default defineEventHandler(async (event) => {
  const method = event.method.toUpperCase()
  if (!allowedMethods.has(method)) {
    throw createError({ statusCode: 405, statusMessage: 'Method Not Allowed' })
  }

  const { engineUrl } = useRuntimeConfig()
  const target = `${engineUrl}${event.path}`

  const headers = new Headers()
  const auth = getHeader(event, 'authorization')
  if (auth) headers.set('authorization', auth)
  const contentType = getHeader(event, 'content-type')
  if (contentType) headers.set('content-type', contentType)

  return $fetch(target, {
    method: method as 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    headers,
    body: ['GET', 'HEAD'].includes(method) ? undefined : await readRawBody(event),
  })
})
