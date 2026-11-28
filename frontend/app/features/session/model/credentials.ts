import { z } from 'zod'
import type { components } from '~/shared/api/schema'

const text = (message: string) => z.string().refine(value => !value.includes('\0'), message)
const within = (min: number, max: number) => (value: string) => {
  const length = [...value].length
  return length >= min && length <= max
}

const email = z.string().trim().toLowerCase().refine(
  value => within(1, 254)(value) && !value.includes('\0') && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value),
  'Введите корректный email.',
)
const password = text('Пароль содержит недопустимый символ.')
  .refine(within(8, 128), 'Пароль должен содержать от 8 до 128 символов.')

export const loginCredentials = z.object({ email, password }) satisfies z.ZodType<components['schemas']['LoginRequest']>

export const registrationCredentials = loginCredentials.extend({
  name: text('Имя содержит недопустимый символ.')
    .transform(value => value.trim() || undefined)
    .refine(value => value === undefined || within(1, 120)(value), 'Имя может содержать до 120 символов.'),
  phone: text('Телефон содержит недопустимый символ.')
    .transform(value => value.trim() || undefined)
    .refine(value => value === undefined || within(1, 32)(value), 'Телефон может содержать до 32 символов.'),
}) satisfies z.ZodType<components['schemas']['RegisterRequest']>
