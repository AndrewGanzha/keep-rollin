import type { Lot, Quote } from '~/entities/lot'
import { fetchQuote } from '~/entities/lot'
import { ApiError, useApi } from '~/shared/api'

const DEBOUNCE_MS = 250

/** Цена и доступность вариантов: дебаунс + отмена устаревшего запроса. */
export const useQuote = (
  lot: Ref<Lot>,
  start: Ref<Date | null>,
  end: Ref<Date | null>,
  enabled: Ref<boolean>,
) => {
  const api = useApi()

  const quote = ref<Quote | null>(null)
  const pending = ref(false)
  const error = ref<ApiError | null>(null)

  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null
  let requestId = 0

  const load = async () => {
    if (!start.value || !end.value || end.value.getTime() <= start.value.getTime()) {
      controller?.abort()
      quote.value = null
      error.value = null
      pending.value = false

      return
    }

    const currentId = ++requestId
    controller?.abort()
    controller = new AbortController()
    pending.value = true
    error.value = null

    try {
      const response = await fetchQuote(
        api,
        lot.value.slug,
        start.value.toISOString(),
        end.value.toISOString(),
        controller.signal,
      )

      if (currentId === requestId) {
        quote.value = response
      }
    } catch (caught) {
      if (currentId === requestId && !controller.signal.aborted) {
        quote.value = null
        error.value = caught instanceof ApiError
          ? caught
          : new ApiError({ title: 'Не удалось рассчитать цену' }, 0)
      }
    } finally {
      if (currentId === requestId) {
        pending.value = false
      }
    }
  }

  const schedule = () => {
    clearTimeout(timer)

    if (!enabled.value) {
      controller?.abort()
      pending.value = false

      return
    }

    timer = setTimeout(load, DEBOUNCE_MS)
  }

  watch([lot, start, end], schedule, { immediate: true })
  watch(enabled, schedule)

  onScopeDispose(() => {
    clearTimeout(timer)
    controller?.abort()
  })

  return { quote, pending, error, refresh: load }
}
