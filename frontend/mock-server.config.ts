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
type AdminRental = components['schemas']['AdminRental']
type AdminRentalPage = components['schemas']['AdminRentalPage']
type AdminUserRef = components['schemas']['AdminUserRef']
type VerificationRequest = components['schemas']['VerificationRequest']
type VerificationRequestPage = components['schemas']['VerificationRequestPage']
type Ticket = components['schemas']['Ticket']
type TicketPage = components['schemas']['TicketPage']

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
  makeLot(102, 'urban-two', 'Urban Two', 'Тот же класс, но с багажником и корзиной', EBikes, { power: 500, range: 65 }, 'daily', 130000),
  makeLot(103, 'trail-pro', 'Trail Pro', 'Внедорожник с усиленной рамой и амортизацией', EBikes, { power: 750, range: 90 }, 'daily', 180000),
  makeLot(104, 'cargo-max', 'Cargo Max', 'Грузовой байк для перевозки до 80 кг', EBikes, { power: 1000, range: 70 }, 'daily', 240000),
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

/** Демо-аккаунты: роль определяется по email, пароль — любой от 8 символов. */
const seedUsers: User[] = [
  mockUser,
  {
    id: uid(901),
    email: 'admin@example.com',
    name: 'Мария Админова',
    role: 'admin',
    verification_status: 'approved',
  },
  {
    id: uid(902),
    email: 'owner@example.com',
    name: 'Олег Владельцев',
    role: 'owner',
    verification_status: 'approved',
  },
  {
    id: uid(903),
    email: 'anna@example.com',
    name: 'Анна Смирнова',
    role: 'user',
    verification_status: 'pending',
  },
  {
    id: uid(904),
    email: 'pavel@example.com',
    name: 'Павел Кузнецов',
    role: 'user',
    verification_status: 'approved',
  },
]

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
  {
    id: uid(303),
    lot: rentalLot(lots[1]!),
    status: 'overdue',
    start_time: iso(-30 * HOUR),
    end_time: iso(-2 * HOUR),
    price_minor: 138000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: null,
  },
  {
    id: uid(304),
    lot: rentalLot(lots[3]!),
    status: 'completed',
    start_time: iso(-52 * HOUR),
    end_time: iso(-50 * HOUR),
    price_minor: 178000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: null,
  },
  {
    id: uid(305),
    lot: rentalLot(lots[4]!),
    status: 'booked',
    start_time: iso(6 * HOUR),
    end_time: iso(30 * HOUR),
    price_minor: 70000,
    currency: 'RUB',
    remaining_seconds: 21600,
    cancellation_deadline: iso(4 * HOUR),
  },
  {
    id: uid(306),
    lot: rentalLot(lots[3]!),
    status: 'active',
    start_time: iso(-26 * HOUR),
    end_time: iso(-3 * HOUR),
    price_minor: 356000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: null,
  },
  {
    id: uid(307),
    lot: rentalLot(lots[0]!),
    status: 'completed',
    start_time: iso(-10 * 24 * HOUR),
    end_time: iso(-9 * 24 * HOUR),
    price_minor: 900000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: null,
  },
]

const userById = (id: string): User => seedUsers.find(user => user.id === id) ?? mockUser

const userRef = (user: User): AdminUserRef => ({ id: user.id, name: user.name, email: user.email })

const rentalOwners = new Map<string, User>([
  [uid(301), userById(uid(903))],
  [uid(302), userById(uid(904))],
  [uid(303), userById(uid(903))],
  [uid(304), userById(uid(904))],
  [uid(305), userById(uid(903))],
  [uid(306), userById(uid(904))],
  [uid(307), userById(uid(903))],
])

const rentalVersions = new Map<string, number>([
  [uid(301), 1],
  [uid(302), 1],
  [uid(303), 1],
  [uid(304), 1],
  [uid(305), 1],
  [uid(306), 1],
  [uid(307), 1],
])

const verificationRequests: VerificationRequest[] = [
  {
    id: uid(501),
    user: userRef(userById(uid(903))),
    status: 'pending',
    passport: {
      full_name: 'Смирнова Анна Игоревна',
      birth_date: '1996-04-12',
      passport_number: '4510 123456',
      issued_by: 'ОВД Тверского района, 14.05.2016',
    },
    documents: [
      { purpose: 'verification_passport', url: 'https://example.com/docs/passport-501.jpg' },
      { purpose: 'verification_registration', url: 'https://example.com/docs/registration-501.jpg' },
      { purpose: 'verification_selfie', url: 'https://example.com/docs/selfie-501.jpg' },
    ],
    admin_comment: null,
    created_at: iso(-3 * HOUR),
    reviewed_at: null,
    version: 1,
  },
  {
    id: uid(502),
    user: {
      id: uid(905),
      email: 'kirill@example.com',
      name: 'Кирилл Орлов',
    },
    status: 'pending',
    passport: {
      full_name: 'Орлов Кирилл Владимирович',
      birth_date: '1991-11-02',
      passport_number: '5012 998877',
      issued_by: 'МФЦ Хамовники, 03.02.2019',
    },
    documents: [
      { purpose: 'verification_passport', url: 'https://example.com/docs/passport-502.jpg' },
      { purpose: 'verification_selfie', url: 'https://example.com/docs/selfie-502.jpg' },
    ],
    admin_comment: null,
    created_at: iso(-26 * HOUR),
    reviewed_at: null,
    version: 1,
  },
  {
    id: uid(503),
    user: userRef(userById(uid(904))),
    status: 'approved',
    passport: {
      full_name: 'Кузнецов Павел Андреевич',
      birth_date: '1989-07-21',
      passport_number: '4009 554433',
      issued_by: 'ОВД Арбат, 10.09.2012',
    },
    documents: [
      { purpose: 'verification_passport', url: 'https://example.com/docs/passport-503.jpg' },
    ],
    admin_comment: 'Документы в порядке',
    created_at: iso(-72 * HOUR),
    reviewed_at: iso(-70 * HOUR),
    version: 2,
  },
  {
    id: uid(504),
    user: {
      id: uid(906),
      email: 'olga@example.com',
      name: 'Ольга Белова',
    },
    status: 'rejected',
    passport: {
      full_name: 'Белова Ольга Сергеевна',
      birth_date: '1994-01-30',
      passport_number: '4514 112233',
      issued_by: 'ОВД Пресня, 22.03.2018',
    },
    documents: [
      { purpose: 'verification_passport', url: 'https://example.com/docs/passport-504.jpg' },
      { purpose: 'verification_selfie', url: 'https://example.com/docs/selfie-504.jpg' },
    ],
    admin_comment: 'Селфи не совпадает с фото в паспорте',
    created_at: iso(-120 * HOUR),
    reviewed_at: iso(-118 * HOUR),
    version: 2,
  },
]

const tickets: Ticket[] = [
  {
    id: uid(601),
    rental_id: uid(301),
    lot: rentalLot(lots[0]!),
    user: userRef(userById(uid(903))),
    category: 'no_power',
    description: 'Батарея не включается после зарядки, индикатор мигает красным',
    photo_urls: ['https://example.com/tickets/601-1.jpg'],
    status: 'submitted',
    admin_comment: null,
    created_at: iso(-2 * HOUR),
    resolved_at: null,
    version: 1,
  },
  {
    id: uid(602),
    rental_id: uid(302),
    lot: rentalLot(lots[2]!),
    user: userRef(userById(uid(904))),
    category: 'battery',
    description: 'Аккумулятор держит заряд примерно вдвое меньше заявленного',
    photo_urls: [],
    status: 'in_progress',
    admin_comment: 'Проверяем состояние на складе',
    created_at: iso(-20 * HOUR),
    resolved_at: null,
    version: 2,
  },
  {
    id: uid(603),
    rental_id: uid(301),
    lot: rentalLot(lots[1]!),
    user: userRef(userById(uid(903))),
    category: 'damage',
    description: 'На раме обнаружена трещина возле крепления двигателя',
    photo_urls: ['https://example.com/tickets/603-1.jpg', 'https://example.com/tickets/603-2.jpg'],
    status: 'resolved',
    admin_comment: 'Лот переведён в обслуживание',
    created_at: iso(-96 * HOUR),
    resolved_at: iso(-90 * HOUR),
    version: 3,
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

const toAdminRental = (rental: Rental): AdminRental => ({
  ...withRemaining(rental),
  user: userRef(rentalOwners.get(rental.id) ?? mockUser),
  version: rentalVersions.get(rental.id) ?? 1,
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

        const user: User = seedUsers.find(item => item.email === body.email)
          ?? { ...mockUser, email: body.email }
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
        rentalOwners.set(rental.id, user)
        rentalVersions.set(rental.id, 1)
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

      rest.get('/api/v1/admin/rentals', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const status = typeof query.status === 'string' ? query.status : undefined
        const lotId = typeof query.lot_id === 'string' ? query.lot_id : undefined
        const from = typeof query.from === 'string' ? Date.parse(query.from) : Number.NaN
        const to = typeof query.to === 'string' ? Date.parse(query.to) : Number.NaN
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = rentals
          .filter(rental =>
            (!status || rental.status === status)
            && (!lotId || rental.lot.id === lotId)
            && (!Number.isFinite(from) || Date.parse(rental.end_time) > from)
            && (!Number.isFinite(to) || Date.parse(rental.start_time) < to),
          )
          .map(toAdminRental)

        const page: AdminRentalPage = {
          items: filtered.slice(offset, offset + limit),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 80 }),

      rest.post('/api/v1/admin/rentals/:id/close', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const rental = rentals.find(item => item.id === params.request.params.id)

        if (!rental) {
          return fail(params, 404, problem('not_found', 404, 'Аренда не найдена'))
        }

        const body = (params.request.body ?? {}) as { comment?: string; lot_status?: string }
        const comment = body.comment?.trim() ?? ''

        if (comment.length < 3) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { comment: 'Минимум 3 символа' }),
          )
        }

        if (body.lot_status !== 'active' && body.lot_status !== 'maintenance') {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { lot_status: 'Выберите статус лота' }),
          )
        }

        if (!['booked', 'active', 'overdue'].includes(rental.status)) {
          return fail(params, 409, problem('rental_already_closed', 409, 'Аренда уже закрыта'))
        }

        rental.status = 'completed'
        rentalVersions.set(rental.id, (rentalVersions.get(rental.id) ?? 1) + 1)

        return toAdminRental(rental)
      }, { delay: 150 }),

      rest.post('/api/v1/admin/rentals/:id/cancel', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const rental = rentals.find(item => item.id === params.request.params.id)

        if (!rental) {
          return fail(params, 404, problem('not_found', 404, 'Аренда не найдена'))
        }

        const body = (params.request.body ?? {}) as { reason?: string }
        const reason = body.reason?.trim() ?? ''

        if (reason.length < 3) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { reason: 'Минимум 3 символа' }),
          )
        }

        if (rental.status !== 'booked' && rental.status !== 'active') {
          return fail(params, 409, problem('rental_not_active', 409, 'Аренду нельзя отменить в этом статусе'))
        }

        rental.status = 'cancelled'
        rentalVersions.set(rental.id, (rentalVersions.get(rental.id) ?? 1) + 1)

        return toAdminRental(rental)
      }, { delay: 150 }),

      rest.get('/api/v1/admin/verification-requests', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const status = typeof query.status === 'string' ? query.status : undefined
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = verificationRequests.filter(item => !status || item.status === status)

        const page: VerificationRequestPage = {
          items: filtered.slice(offset, offset + limit),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 80 }),

      rest.post('/api/v1/admin/verification-requests/:id/decision', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const request = verificationRequests.find(item => item.id === params.request.params.id)

        if (!request) {
          return fail(params, 404, problem('not_found', 404, 'Заявка не найдена'))
        }

        const body = (params.request.body ?? {}) as { decision?: string; comment?: string; version?: number }
        const comment = body.comment?.trim() ?? ''

        if (body.decision !== 'approved' && body.decision !== 'rejected') {
          return fail(params, 422, problem('validation_error', 422, 'Выберите решение'))
        }

        if (body.decision === 'rejected' && comment.length < 3) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { comment: 'Комментарий обязателен для отказа' }),
          )
        }

        if (body.version !== request.version) {
          return fail(params, 409, problem('stale_version', 409, 'Заявка уже изменилась'))
        }

        if (request.status !== 'pending') {
          return fail(params, 409, problem('already_processed', 409, 'Заявка уже обработана'))
        }

        request.status = body.decision
        request.admin_comment = comment || null
        request.reviewed_at = iso(0)
        request.version += 1

        const owner = seedUsers.find(item => item.id === request.user.id)

        if (owner) {
          owner.verification_status = body.decision
        }

        return request
      }, { delay: 150 }),

      rest.get('/api/v1/admin/tickets', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const status = typeof query.status === 'string' ? query.status : undefined
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = tickets.filter(item => !status || item.status === status)

        const page: TicketPage = {
          items: filtered.slice(offset, offset + limit),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 80 }),

      rest.patch('/api/v1/admin/tickets/:id', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const ticket = tickets.find(item => item.id === params.request.params.id)

        if (!ticket) {
          return fail(params, 404, problem('not_found', 404, 'Тикет не найден'))
        }

        const body = (params.request.body ?? {}) as {
          status?: string
          admin_comment?: string
          version?: number
        }
        const comment = body.admin_comment?.trim() ?? ''

        if (body.status !== 'in_progress' && body.status !== 'resolved') {
          return fail(params, 422, problem('validation_error', 422, 'Недопустимый статус'))
        }

        if (body.version !== ticket.version) {
          return fail(params, 409, problem('stale_version', 409, 'Тикет уже изменился'))
        }

        if (ticket.status === 'resolved') {
          return fail(params, 409, problem('ticket_already_resolved', 409, 'Тикет уже решён'))
        }

        if (body.status === 'resolved' && ticket.status !== 'in_progress') {
          return fail(params, 409, problem('validation_error', 409, 'Сначала возьмите тикет в работу'))
        }

        if (body.status === 'resolved' && comment.length < 3) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { admin_comment: 'Комментарий обязателен' }),
          )
        }

        ticket.status = body.status
        ticket.admin_comment = comment || ticket.admin_comment
        ticket.resolved_at = body.status === 'resolved' ? iso(0) : null
        ticket.version += 1

        return ticket
      }, { delay: 150 }),
    ],
  },
)
