import { toApiError, unwrap, type ApiClient } from '~/shared/api'
import type { components } from '~/shared/api/schema'

export type NotificationPreferences = components['schemas']['NotificationPreferencesResponse']
export type NotificationPreferencePatch = components['schemas']['UpdateNotificationPreferencesRequest']
export type RegisteredPushSubscription = components['schemas']['PushSubscriptionResponse']
export type PushSubscriptionPayload = components['schemas']['UpsertPushSubscriptionRequest']

export const fetchNotificationPreferences = async (api: ApiClient) =>
  unwrap(await api.GET('/api/v1/me/notification-preferences'))

export const saveNotificationPreferences = async (api: ApiClient, body: NotificationPreferencePatch) =>
  unwrap(await api.PUT('/api/v1/me/notification-preferences', { body }))

export const listPushSubscriptions = async (api: ApiClient) =>
  unwrap(await api.GET('/api/v1/me/push-subscriptions'))

export const registerPushSubscription = async (api: ApiClient, body: PushSubscriptionPayload) =>
  unwrap(await api.POST('/api/v1/me/push-subscriptions', { body }))

export const deletePushSubscription = async (api: ApiClient, subscriptionId: string) => {
  const result = await api.DELETE('/api/v1/me/push-subscriptions/{subscription_id}', {
    params: { path: { subscription_id: subscriptionId } },
  })
  if (!result.response.ok) {
    throw toApiError(result.error, result.response)
  }
}
