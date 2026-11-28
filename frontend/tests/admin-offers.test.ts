import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { OfferPage, OfferVersion, PublicOffer } from '~/entities/offer'
import { useAdminOffers } from '~/features/admin-offers'
import { ApiError } from '~/shared/api'

const requests = vi.hoisted(() => ({
  listAdminOffers: vi.fn(),
  createOffer: vi.fn(),
  updateOffer: vi.fn(),
  fetchCurrentOffer: vi.fn(),
  publishOffer: vi.fn(),
}))

vi.mock('~/entities/offer', () => requests)
vi.mock('~/shared/api', async (original) => ({
  ...await original<object>(),
  useApi: () => api,
}))

const api = {}
const timestamp = '2026-11-28T12:00:00Z'
const current: PublicOffer = { id: 'current-2', version: 2, title: 'Действующая', body: 'Условия', published_at: timestamp }
const draft: OfferVersion = {
  id: 'draft-4', version: 4, title: 'Черновик', body: '# Условия', status: 'draft',
  published_at: null, created_at: timestamp, updated_at: timestamp,
}

beforeEach(() => {
  vi.resetAllMocks()
  requests.listAdminOffers.mockImplementation((_api, limit, offset) => ({ items: [draft], total: 21, limit, offset }))
  requests.fetchCurrentOffer.mockResolvedValue(current)
  vi.stubGlobal('useAsyncData', (_key: string, load: () => Promise<OfferPage>) => {
    const data = ref<OfferPage>()
    const error = ref<unknown>()
    const pending = ref(false)
    const refresh = async () => {
      pending.value = true
      try {
        data.value = await load()
        error.value = undefined
      } catch (caught) {
        error.value = caught
      } finally {
        pending.value = false
      }
    }
    return Object.assign(refresh(), { data, error, pending, refresh })
  })
})

afterEach(() => vi.unstubAllGlobals())

const start = async () => {
  const flow = useAdminOffers()
  await flow.request
  return flow
}

describe('owner offer history and drafts', () => {
  it('loads another history page from the API and refreshes page one after creating a draft', async () => {
    const flow = await start()
    expect(requests.listAdminOffers).toHaveBeenCalledExactlyOnceWith(api, 20, 0)
    expect(flow.pageCount.value).toBe(2)
    await flow.changePage(2)
    expect(flow.page.value).toBe(2)
    expect(requests.listAdminOffers).toHaveBeenLastCalledWith(api, 20, 20)

    flow.openEditor()
    expect(flow.canSave.value).toBe(false)
    flow.editor.value!.title = '📄'.repeat(201)
    flow.editor.value!.body = '# New terms\n\n**Details**'
    expect(flow.canSave.value).toBe(false)
    flow.editor.value!.title = '📄'.repeat(200)
    expect(flow.canSave.value).toBe(true)

    const deferred = Promise.withResolvers<OfferVersion>()
    requests.createOffer.mockReturnValue(deferred.promise)
    const saving = flow.save()
    await flow.save()
    expect(requests.createOffer).toHaveBeenCalledExactlyOnceWith(api, {
      title: '📄'.repeat(200), body: '# New terms\n\n**Details**',
    })
    deferred.resolve({ ...draft, version: 5 })
    await saving

    expect(flow.editor.value).toBeNull()
    expect(flow.page.value).toBe(1)
    expect(requests.listAdminOffers).toHaveBeenLastCalledWith(api, 20, 0)
    expect(requests.publishOffer).not.toHaveBeenCalled()
  })

  it('saves changes to a draft and exposes published or archived versions as read-only', async () => {
    const flow = await start()
    flow.openEditor(draft)
    flow.editor.value!.body = '# Updated Markdown'
    requests.updateOffer.mockResolvedValue({ ...draft, body: flow.editor.value!.body })
    await flow.save()

    expect(requests.updateOffer).toHaveBeenCalledExactlyOnceWith(api, draft.id, { title: draft.title, body: '# Updated Markdown' })
    expect(requests.listAdminOffers).toHaveBeenCalledTimes(2)

    for (const status of ['active', 'archived'] as const) {
      const immutable: OfferVersion = { ...draft, status, published_at: timestamp }
      flow.openEditor(immutable)
      expect(flow.editable.value).toBe(false)
      expect(flow.canSave.value).toBe(false)
      await flow.save()
      flow.closeEditor()
      await flow.preparePublish(immutable)
      await flow.confirmPublish()
    }

    expect(requests.updateOffer).toHaveBeenCalledOnce()
    expect(requests.fetchCurrentOffer).not.toHaveBeenCalled()
    expect(requests.publishOffer).not.toHaveBeenCalled()
  })

  it('retains the local text if the backend reports that somebody else already published the draft', async () => {
    const flow = await start()
    flow.openEditor(draft)
    flow.editor.value!.body = '# Unsaved changes'
    requests.updateOffer.mockRejectedValue(new ApiError({ code: 'offer_not_editable' }, 409))

    await flow.save()

    expect(flow.editor.value?.body).toBe('# Unsaved changes')
    expect(flow.canSave.value).toBe(false)
    expect(flow.actionError.value).toMatch(/скопировать текст/)
    expect(requests.listAdminOffers).toHaveBeenCalledTimes(2)
  })
})

describe('owner offer publishing', () => {
  it('identifies the active version independently of history and publishes only an explicitly confirmed draft', async () => {
    const flow = await start()
    await flow.preparePublish(draft)
    expect(flow.confirmation.value).toEqual({ draft, current })
    expect(requests.publishOffer).not.toHaveBeenCalled()

    flow.closeConfirmation()
    await flow.confirmPublish()
    expect(requests.publishOffer).not.toHaveBeenCalled()

    await flow.preparePublish(draft)
    requests.publishOffer.mockResolvedValue({ ...draft, status: 'active' })
    await flow.confirmPublish()

    expect(requests.publishOffer).toHaveBeenCalledExactlyOnceWith(api, draft.id)
    expect(requests.listAdminOffers).toHaveBeenCalledTimes(2)
    expect(flow.confirmation.value).toBeNull()
    expect(flow.notice.value).toContain(`№${draft.version}`)
  })

  it('requires reconfirmation if a different version becomes active while the confirmation is open', async () => {
    const newCurrent = { ...current, id: 'current-3', version: 3 }
    const flow = await start()
    await flow.preparePublish(draft)
    requests.fetchCurrentOffer.mockResolvedValue(newCurrent)
    requests.publishOffer.mockResolvedValue({ ...draft, status: 'active' })

    await flow.confirmPublish()
    expect(flow.confirmation.value).toEqual({ draft, current: newCurrent })
    expect(flow.actionError.value).toMatch(/подтвердите публикацию ещё раз/)
    expect(requests.publishOffer).not.toHaveBeenCalled()

    await flow.confirmPublish()
    expect(requests.publishOffer).toHaveBeenCalledExactlyOnceWith(api, draft.id)
  })

  it('only treats 404 as first publication and retains a retryable error for lookup failures', async () => {
    const flow = await start()
    requests.fetchCurrentOffer.mockRejectedValue(new ApiError({ code: 'service_unavailable' }, 503))
    await flow.preparePublish(draft)
    expect(flow.confirmation.value).toBeNull()
    expect(flow.actionError.value).toMatch(/Не удалось проверить/)
    expect(requests.publishOffer).not.toHaveBeenCalled()

    requests.fetchCurrentOffer.mockRejectedValue(new ApiError({ code: 'not_found' }, 404))
    await flow.preparePublish(draft)
    expect(flow.confirmation.value).toEqual({ draft, current: null })
    requests.publishOffer.mockResolvedValue({ ...draft, status: 'active' })
    await flow.confirmPublish()
    expect(requests.publishOffer).toHaveBeenCalledExactlyOnceWith(api, draft.id)
  })
})
