import { ref, shallowRef } from 'vue'
import type { NotificationPreferencePatch, NotificationPreferences } from '../api/notifications'

export const createNotificationPreferences = (
  load: () => Promise<NotificationPreferences>,
  save: (patch: NotificationPreferencePatch) => Promise<NotificationPreferences>,
) => {
  const data = shallowRef<NotificationPreferences | null>(null)
  const pending = ref(false)
  const saving = ref(false)
  const loadFailed = ref(false)
  const saveFailed = ref(false)
  let revision = 0

  const reset = () => {
    revision++
    data.value = null
    pending.value = false
    saving.value = false
    loadFailed.value = false
    saveFailed.value = false
  }

  const refresh = async () => {
    if (pending.value || saving.value) return
    const request = ++revision
    pending.value = true
    loadFailed.value = false
    try {
      const received = await load()
      if (revision === request) data.value = received
    } catch {
      if (revision === request) loadFailed.value = true
    } finally {
      if (revision === request) pending.value = false
    }
  }

  const update = async (patch: NotificationPreferencePatch, optimistic: NotificationPreferences) => {
    const previous = data.value
    if (!previous || pending.value || saving.value) return

    const request = ++revision
    saving.value = true
    saveFailed.value = false
    data.value = optimistic
    try {
      const received = await save(patch)
      if (revision === request) data.value = received
    } catch {
      if (revision === request) {
        data.value = previous
        saveFailed.value = true
      }
    } finally {
      if (revision === request) saving.value = false
    }
  }

  const setEmail = (event: string, enabled: boolean) => {
    const previous = data.value
    if (!previous || !Object.hasOwn(previous.email_by_event, event) || previous.locked_events.includes(event)) return
    return update(
      { email_by_event: { [event]: enabled } },
      { ...previous, email_by_event: { ...previous.email_by_event, [event]: enabled } },
    )
  }

  const setPush = (enabled: boolean) => {
    const previous = data.value
    if (!previous) return
    return update({ push_enabled: enabled }, { ...previous, push_enabled: enabled })
  }

  return { data, pending, saving, loadFailed, saveFailed, refresh, reset, setEmail, setPush }
}
