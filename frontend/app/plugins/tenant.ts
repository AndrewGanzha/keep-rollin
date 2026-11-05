import { fetchTenant, useTenant } from '~/entities/tenant'
import { useApi } from '~/shared/api'

export default defineNuxtPlugin(async () => {
  const tenant = useTenant()

  useHead(() => ({
    style: tenant.value
      ? [{
          innerHTML: `:root{--p-primary-color:${tenant.value.primary_color};--p-primary-hover-color:${tenant.value.primary_color}}`,
        }]
      : [],
  }))

  try {
    tenant.value = await fetchTenant(useApi())
  } catch {
    tenant.value = null
  }
})
