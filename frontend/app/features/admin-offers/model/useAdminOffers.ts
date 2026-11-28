import { computed, ref } from 'vue'
import {
  createOffer,
  fetchCurrentOffer,
  listAdminOffers,
  publishOffer,
  updateOffer,
  type OfferVersion,
} from '~/entities/offer'
import { ApiError, useApi } from '~/shared/api'

const PAGE_SIZE = 20

interface OfferEditor {
  offer?: OfferVersion
  title: string
  body: string
  stale: boolean
}

interface PublishConfirmation {
  draft: OfferVersion
  current: Awaited<ReturnType<typeof fetchCurrentOffer>> | null
}

const fieldIssue = (value: string, max: number): string => {
  if (value.includes('\0')) return 'Удалите недопустимый символ из текста'
  if (!value.trim()) return 'Заполните поле'
  if (Array.from(value).length > max) return `Допустимо до ${max} символов`
  return ''
}

const isStaleDraft = (error: unknown): boolean =>
  error instanceof ApiError && (error.status === 404 || error.code === 'offer_not_editable')

export const useAdminOffers = () => {
  const api = useApi()
  const offset = ref(0)
  const request = useAsyncData('admin-offers', () => listAdminOffers(api, PAGE_SIZE, offset.value))
  const { data: history, error: historyError, pending: historyPending, refresh } = request

  const editor = ref<OfferEditor | null>(null)
  const confirmation = ref<PublishConfirmation | null>(null)
  const action = ref<'save' | 'prepare' | 'publish' | null>(null)
  const actionError = ref('')
  const notice = ref('')

  const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
  const pageCount = computed(() => Math.max(1, Math.ceil((history.value?.total ?? 0) / PAGE_SIZE)))
  const busy = computed(() => action.value !== null)
  const editable = computed(() => editor.value !== null && (!editor.value.offer || editor.value.offer.status === 'draft'))
  const titleIssue = computed(() => fieldIssue(editor.value?.title ?? '', 200))
  const bodyIssue = computed(() => fieldIssue(editor.value?.body ?? '', 20000))
  const canSave = computed(() =>
    editable.value && !editor.value?.stale && !titleIssue.value && !bodyIssue.value && !busy.value,
  )

  const clearFeedback = () => {
    actionError.value = ''
    notice.value = ''
  }

  const changePage = async (value: number) => {
    if (busy.value || historyPending.value || value === page.value || value < 1 || value > pageCount.value) return
    offset.value = (value - 1) * PAGE_SIZE
    await refresh()
  }

  const openEditor = (offer?: OfferVersion) => {
    if (busy.value || confirmation.value) return
    clearFeedback()
    editor.value = { offer, title: offer?.title ?? '', body: offer?.body ?? '', stale: false }
  }

  const closeEditor = () => {
    if (busy.value) return
    editor.value = null
    actionError.value = ''
  }

  const save = async () => {
    const draft = editor.value
    if (!draft || !canSave.value) return

    clearFeedback()
    action.value = 'save'
    const payload = { title: draft.title, body: draft.body }

    try {
      const saved = draft.offer
        ? await updateOffer(api, draft.offer.id, payload)
        : await createOffer(api, payload)

      editor.value = null
      notice.value = `Черновик версии №${saved.version} сохранён`
      if (!draft.offer) offset.value = 0
      await refresh()
    } catch (error) {
      if (draft.offer && isStaleDraft(error)) {
        draft.stale = true
        actionError.value = 'Эта версия больше недоступна для редактирования. Вы можете скопировать текст черновика.'
        await refresh()
      } else {
        actionError.value = 'Не удалось сохранить черновик. Повторите попытку.'
      }
    } finally {
      action.value = null
    }
  }

  const loadCurrentOffer = async () => {
    try {
      return await fetchCurrentOffer(api)
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null
      throw error
    }
  }

  const preparePublish = async (draft: OfferVersion) => {
    if (busy.value || editor.value || confirmation.value || draft.status !== 'draft') return

    clearFeedback()
    action.value = 'prepare'
    try {
      confirmation.value = { draft, current: await loadCurrentOffer() }
    } catch {
      actionError.value = 'Не удалось проверить действующую оферту. Повторите попытку.'
    } finally {
      action.value = null
    }
  }

  const closeConfirmation = () => {
    if (busy.value) return
    confirmation.value = null
    actionError.value = ''
  }

  const confirmPublish = async () => {
    const target = confirmation.value
    if (busy.value || !target) return

    actionError.value = ''
    action.value = 'publish'
    try {
      const current = await loadCurrentOffer()
      if (current?.id !== target.current?.id) {
        confirmation.value = { draft: target.draft, current }
        actionError.value = 'Действующая оферта изменилась. Проверьте версию и подтвердите публикацию ещё раз.'
        return
      }

      const published = await publishOffer(api, target.draft.id)
      confirmation.value = null
      notice.value = `Оферта версии №${published.version} опубликована`
      await refresh()
    } catch (error) {
      if (isStaleDraft(error)) {
        confirmation.value = null
        actionError.value = 'Черновик больше недоступен для публикации. История версий обновлена.'
        await refresh()
      } else {
        actionError.value = 'Не удалось опубликовать оферту. Повторите попытку.'
      }
    } finally {
      action.value = null
    }
  }

  return {
    request, history, historyError, historyPending, refresh, page, pageCount, changePage,
    editor, editable, titleIssue, bodyIssue, canSave, openEditor, closeEditor, save,
    confirmation, preparePublish, closeConfirmation, confirmPublish, action, busy, actionError, notice,
  }
}
