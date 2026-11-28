import { createServer } from 'node:http'
import { fetch } from 'node-fetch-native/node'
import { describe, expect, it } from 'vitest'
import { createApiClient } from '~/shared/api/client'

describe('API tenant authority', () => {
  it('keeps the original request Host on server-side calls to loopback', async () => {
    const hosts: (string | undefined)[] = []
    const server = createServer((request, response) => {
      hosts.push(request.headers.host)
      response.setHeader('Content-Type', 'application/json')
      response.end('{}')
    })
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject)
      server.listen(0, '127.0.0.1', resolve)
    })
    try {
      const address = server.address()
      if (!address || typeof address === 'string') throw new Error('Missing loopback port')
      const baseUrl = `http://127.0.0.1:${address.port}`
      await createApiClient(baseUrl, () => null, 'tenant.test:8443', fetch).GET('/api/v1/public/tenant')
      await createApiClient(baseUrl, () => null).GET('/api/v1/public/tenant')
      expect(hosts).toEqual(['tenant.test:8443', `127.0.0.1:${address.port}`])
    } finally {
      await new Promise<void>((resolve, reject) => {
        server.close(error => error ? reject(error) : resolve())
      })
    }
  })
})
