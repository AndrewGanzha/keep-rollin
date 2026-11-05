import { mock, rest } from 'mock-config-server'
import type { components } from './app/shared/api/schema'

type Tenant = components['schemas']['Tenant']
type Category = components['schemas']['Category']
type Lot = components['schemas']['Lot']
type LotPage = components['schemas']['LotPage']
type Availability = components['schemas']['Availability']
type BusyInterval = components['schemas']['BusyInterval']
type Problem = components['schemas']['Problem']
type User = components['schemas']['User']
type Session = components['schemas']['Session']
type LoginResponse = components['schemas']['LoginResponse']
type Rental = components['schemas']['Rental']
type RentalPage = components['schemas']['RentalPage']
type CreateRentalRequest = components['schemas']['CreateRentalRequest']

const HOUR = 60 * 60 * 1000
const uid = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const iso = (offsetMs: number): string => new Date(Date.now() + offsetMs).toISOString()

const tenant: Tenant = {
  id: uid(1),
  name: 'Северный ветер',
  slug: 'severny-veter',
  logo_url: null,
  primary_color: '#0f766e',
  timezone: 'Europe/Moscow',
  currency: 'RUB',
  vapid_public_key: null,
  policies: {
    booking_horizon_days: 60,
    min_rental_minutes: 60,
    max_rental_days: 30,
    cancellation_free_hours: 24,
    reminder_hours_before: 1,
    tickets_per_rental_per_day: 5,
  },
}

const categories: Category[] = [
  {
    id: uid(10),
    name: 'Электробайки',
    slug: 'ebikes',
    description: 'Городские и внедорожные модели',
    is_archived: false,
    characteristics: [
      { id: uid(11), code: 'power', name: 'Мощность', type: 'number', unit: 'Вт', is_required: true, options: [], sort: 1 },
      { id: uid(12), code: 'range', name: 'Запас хода', type: 'number', unit: 'км', is_required: false, options: [], sort: 2 },
    ],
  },
  {
    id: uid(20),
    name: 'Аккумуляторы',
    slug: 'batteries',
    description: 'Сменные батареи для дальних поездок',
    is_archived: false,
    characteristics: [
      { id: uid(21), code: 'capacity', name: 'Ёмкость', type: 'number', unit: 'Вт·ч', is_required: true, options: [], sort: 1 },
    ],
  },
]

const EBikes = categories[0]!.id
const Batteries = categories[1]!.id

const makeLot = (
  n: number,
  slug: string,
  name: string,
  description: string,
  categoryId: string,
  characteristics: Record<string, string | number>,
  rentalModel: Lot['rental_model'],
  priceMinor: number,
  status: Lot['status'] = 'active',
): Lot => ({
  id: uid(n),
  slug,
  name,
  description,
  category_id: categoryId,
  photos: [],
  characteristics,
  rental_model: rentalModel,
  price_minor: priceMinor,
  currency: 'RUB',
  status,
  is_bookable: status === 'active',
})

const lots: Lot[] = [
  makeLot(101, 'urban-one', 'Urban One', 'Лёгкий городской байк для ежедневных поездок', EBikes, { power: 500, range: 60 }, 'hourly', 45000),
  makeLot(102, 'urban-two', 'Urban Two', 'Тот же класс, но с багажником и корзиной', EBikes, { power: 500, range: 65 }, 'hourly', 47000),
  makeLot(103, 'trail-pro', 'Trail Pro', 'Внедорожник с усиленной рамой и амортизацией', EBikes, { power: 750, range: 90 }, 'hourly', 69000),
  makeLot(104, 'cargo-max', 'Cargo Max', 'Грузовой байк для перевозки до 80 кг', EBikes, { power: 1000, range: 70 }, 'hourly', 89000),
  makeLot(105, 'spare-48v', 'Spare 48V', 'Запасной аккумулятор 48 В, 720 Вт·ч', Batteries, { capacity: 720 }, 'daily', 35000),
  makeLot(106, 'spare-36v', 'Spare 36V', 'Компактный аккумулятор 36 В, 480 Вт·ч', Batteries, { capacity: 480 }, 'daily', 25000, 'maintenance'),
]

const blocks: Record<string, BusyInterval[]> = {
  [lots[0]!.id]: [{ start: iso(2 * HOUR), end: iso(6 * HOUR), kind: 'busy' }],
  [lots[2]!.id]: [{ start: iso(26 * HOUR), end: iso(30 * HOUR), kind: 'busy' }],
}

const mockUser: User = {
  id: uid(900),
  email: 'rider@example.com',
  name: 'Иван Петров',
  role: 'user',
  verification_status: 'approved',
}

const tokens = new Map<string, User>()

const rentalLot = (lot: Lot): Rental['lot'] => ({
  id: lot.id,
  slug: lot.slug,
  name: lot.name,
  photo_url: lot.photos[0] ?? null,
})

const rentals: Rental[] = [
  {
    id: uid(301),
    lot: rentalLot(lots[0]!),
    status: 'booked',
    start_time: iso(20 * HOUR),
    end_time: iso(24 * HOUR),
    price_minor: 180000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: iso(18 * HOUR),
  },
  {
    id: uid(302),
    lot: rentalLot(lots[2]!),
    status: 'active',
    start_time: iso(-HOUR),
    end_time: iso(HOUR),
    price_minor: 69000,
    currency: 'RUB',
    remaining_seconds: 3600,
    cancellation_deadline: null,
  },
]

const permissions = (user: User): string[] =>
  user.role === 'owner'
    ? ['catalog.manage', 'settings.manage', 'admins.manage', 'offers.manage', 'calendar.view', 'analytics.view', 'audit.view']
    : user.role === 'admin'
      ? ['calendar.view', 'verification.review', 'tickets.manage', 'rentals.manage', 'analytics.view']
      : []

interface Responder {
  setStatusCode: (status: number) => void
  setHeader: (name: string, value?: string | string[]) => void
}

interface AuthorizedRequest {
  getRequestHeader: (name: string) => number | string | string[] | undefined
}

const problem = (
  code: string,
  status: number,
  title: string,
  detail?: string,
  fields?: Record<string, string>,
): Problem => ({
  type: `urn:keeprollin:error:${code}`,
  title,
  status,
  code,
  detail,
  trace_id: 'mock-trace',
  fields,
})

const fail = (responder: Responder, status: number, body: Problem): Problem => {
  responder.setStatusCode(status)
  responder.setHeader('Content-Type', 'application/problem+json')
  return body
}

const currentUser = (request: AuthorizedRequest): User | null => {
  const header = request.getRequestHeader('authorization')
  const token = typeof header === 'string' ? header.replace(/^Bearer\s+/i, '') : ''

  return tokens.get(token) ?? null
}

const withRemaining = (rental: Rental): Rental => ({
  ...rental,
  remaining_seconds: Math.round((Date.parse(rental.end_time) - Date.now()) / 1000),
})

const priceFor = (lot: Lot, startMs: number, endMs: number): number => {
  const minutes = Math.ceil((endMs - startMs) / 60000)
  const units = lot.rental_model === 'daily' ? Math.ceil(minutes / 1440) : Math.ceil(minutes / 60)

  return Math.max(units, 1) * lot.price_minor
}

export default mock(
  { port: 7777 },
  {
    name: 'rest',
    configs: [
      rest.get('/api/v1/public/tenant', () => tenant, { delay: 60 }),

      rest.get('/api/v1/public/categories', () => categories, { delay: 60 }),

      rest.get('/api/v1/public/lots', (params) => {
        const query = params.request.queries as Record<string, unknown>
        const category = typeof query.category_id === 'string' ? query.category_id : undefined
        const search = typeof query.q === 'string' ? query.q.toLowerCase() : ''
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = lots.filter(lot =>
          lot.status === 'active'
          && (!category || lot.category_id === category)
          && (!search || lot.name.toLowerCase().includes(search)),
        )

        const page: LotPage = {
          items: filtered.slice(offset, offset + limit),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 120 }),

      rest.get('/api/v1/public/lots/:slug', (params) => {
        const lot = lots.find(item => item.slug === params.request.params.slug)

        return lot ?? fail(params, 404, problem('not_found', 404, 'Лот не найден'))
      }),

      rest.get('/api/v1/public/lots/:slug/availability', (params) => {
        const lot = lots.find(item => item.slug === params.request.params.slug)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const query = params.request.queries as Record<string, unknown>
        const from = String(query.from ?? iso(-HOUR))
        const to = String(query.to ?? iso(14 * 24 * HOUR))
        const fromMs = Date.parse(from)
        const toMs = Date.parse(to)

        const busy = [
          ...(blocks[lot.id] ?? []),
          ...rentals
            .filter(rental => rental.lot.id === lot.id && ['booked', 'active', 'overdue'].includes(rental.status))
            .map(rental => ({ start: rental.start_time, end: rental.end_time, kind: 'busy' as const })),
        ]
          .filter(interval => Date.parse(interval.end) > fromMs && Date.parse(interval.start) < toMs)
          .sort((left, right) => left.start.localeCompare(right.start))

        const lastEnd = busy.length > 0 ? busy[busy.length - 1]!.end : from
        const availability: Availability = {
          lot_id: lot.id,
          from,
          to,
          busy,
          next_free: Date.parse(lastEnd) < toMs ? { start: lastEnd, end: to } : null,
        }

        return availability
      }, { delay: 100 }),

      rest.post('/api/v1/auth/login', (params) => {
        const body = (params.request.body ?? {}) as { email?: string; password?: string }

        if (!body.email || !body.password || body.password.length < 8) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              email: 'Укажите email',
              password: 'Минимум 8 символов',
            }),
          )
        }

        const user: User = { ...mockUser, email: body.email }
        const token = `mock-${Math.random().toString(36).slice(2, 10)}`
        tokens.set(token, user)

        const response: LoginResponse = {
          access_token: token,
          expires_in: 900,
          user,
          role: user.role,
          permissions: permissions(user),
        }

        return response
      }),

      rest.get('/api/v1/auth/session', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const session: Session = {
          user,
          role: user.role,
          permissions: permissions(user),
          offer_accepted: true,
        }

        return session
      }),

      rest.get('/api/v1/me/rentals', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const query = params.request.queries as Record<string, unknown>
        const status = typeof query.status === 'string' ? query.status : undefined
        const filtered = rentals
          .filter(rental => !status || rental.status === status)
          .map(withRemaining)

        const page: RentalPage = {
          items: filtered,
          total: filtered.length,
          limit: 20,
          offset: 0,
        }

        return page
      }, { delay: 80 }),

      rest.post('/api/v1/rentals', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const body = (params.request.body ?? {}) as Partial<CreateRentalRequest>

        if (!body.lot_id || !body.start_time || !body.end_time) {
          return fail(params, 422, problem('validation_error', 422, 'Нужны лот и интервал'))
        }

        const lot = lots.find(item => item.id === body.lot_id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        if (!lot.is_bookable) {
          return fail(params, 409, problem('lot_unavailable', 409, 'Лот недоступен для брони'))
        }

        const startMs = Date.parse(body.start_time)
        const endMs = Date.parse(body.end_time)

        if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
          return fail(params, 422, problem('validation_error', 422, 'Конец должен быть позже начала'))
        }

        const overlap = rentals.some(rental =>
          rental.lot.id === lot.id
          && ['booked', 'active', 'overdue'].includes(rental.status)
          && Date.parse(rental.start_time) < endMs
          && Date.parse(rental.end_time) > startMs,
        )

        if (overlap) {
          return fail(params, 409, problem('slot_taken', 409, 'Слот занят', 'Лот занят в выбранном интервале'))
        }

        const rental: Rental = {
          id: `rental-${Math.random().toString(36).slice(2, 10)}`,
          lot: rentalLot(lot),
          status: 'booked',
          start_time: new Date(startMs).toISOString(),
          end_time: new Date(endMs).toISOString(),
          price_minor: priceFor(lot, startMs, endMs),
          currency: lot.currency,
          remaining_seconds: Math.round((endMs - Date.now()) / 1000),
          cancellation_deadline: iso(24 * HOUR),
        }

        rentals.unshift(rental)
        params.setStatusCode(201)

        return rental
      }, { delay: 150 }),

      rest.post('/api/v1/me/rentals/:id/cancel', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const rental = rentals.find(item => item.id === params.request.params.id)

        if (!rental) {
          return fail(params, 404, problem('not_found', 404, 'Бронь не найдена'))
        }

        if (rental.status !== 'booked') {
          return fail(params, 409, problem('rental_not_active', 409, 'Отменить можно только бронь'))
        }

        if (rental.cancellation_deadline && Date.parse(rental.cancellation_deadline) < Date.now()) {
          return fail(params, 409, problem('cancellation_not_allowed', 409, 'Дедлайн отмены прошёл'))
        }

        rental.status = 'cancelled'

        return withRemaining(rental)
      }, { delay: 120 }),
    ],
  },
)
