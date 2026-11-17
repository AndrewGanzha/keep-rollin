import { mock, rest } from 'mock-config-server'
import { addDays, dayKeyOf, zonedDayStartIso } from './app/shared/lib/calendar'
import type { components } from './app/shared/api/schema'
import { peakUsage, type BatteryCommit } from './mock/capacity'
import {
  computePrice,
  minAllowedUnits,
  priceForRange,
  priceFromOf,
  PricingError,
  UNIT_MS,
  validateAllowedDurations,
  validateVariants,
  type PriceTier,
  type RangePrice,
  type RentalUnit,
} from './mock/pricing'

type Tenant = components['schemas']['Tenant']
type Category = components['schemas']['Category']
type Lot = components['schemas']['Lot']
type LotPage = components['schemas']['LotPage']
type LotVariant = components['schemas']['LotVariant']
type LotVariantInput = components['schemas']['LotVariantInput']
type Quote = components['schemas']['Quote']
type UpdateLotRequest = components['schemas']['UpdateLotRequest']
type LotBlock = components['schemas']['LotBlock']
type CreateLotBlockRequest = components['schemas']['CreateLotBlockRequest']
type AdminSchedule = components['schemas']['AdminSchedule']
type ScheduleRentalInterval = components['schemas']['ScheduleRentalInterval']
type ScheduleBlockInterval = components['schemas']['ScheduleBlockInterval']
type BatteryStock = components['schemas']['BatteryStock']
type Availability = components['schemas']['Availability']
type Problem = components['schemas']['Problem']
type User = components['schemas']['User']
type Session = components['schemas']['Session']
type LoginResponse = components['schemas']['LoginResponse']
type Rental = components['schemas']['Rental']
type RentalPage = components['schemas']['RentalPage']
type CreateRentalRequest = components['schemas']['CreateRentalRequest']
type CreateLotRequest = components['schemas']['CreateLotRequest']
type LotStatusRequest = components['schemas']['LotStatusRequest']
type AnalyticsSummary = components['schemas']['AnalyticsSummary']
type AnalyticsBucket = components['schemas']['AnalyticsBucket']
type AnalyticsRevenue = components['schemas']['AnalyticsRevenue']
type AnalyticsLotDetail = components['schemas']['AnalyticsLotDetail']
type AdminRental = components['schemas']['AdminRental']
type AdminRentalPage = components['schemas']['AdminRentalPage']
type AdminUserRef = components['schemas']['AdminUserRef']
type VerificationRequest = components['schemas']['VerificationRequest']
type VerificationRequestPage = components['schemas']['VerificationRequestPage']
type Ticket = components['schemas']['Ticket']
type TicketPage = components['schemas']['TicketPage']
type UpdateBatteryStockRequest = components['schemas']['UpdateBatteryStockRequest']

/** Лот в состоянии мока: `price_from` всегда вычисляется при выдаче. */
type MockLot = Omit<Lot, 'price_from'>

const HOUR = 60 * 60 * 1000
const uid = (n: number): string => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
const iso = (offsetMs: number): string => new Date(Date.now() + offsetMs).toISOString()

const translit: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y',
  к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f',
  х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
}

const slugify = (value: string): string => value
  .toLowerCase()
  .split('')
  .map(char => translit[char] ?? char)
  .join('')
  .replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '') || 'lot'

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

const priceTier = (minUnits: number, priceMinor: number): PriceTier => ({
  min_units: minUnits,
  price_per_unit_minor: priceMinor,
})

const makeVariant = (
  id: number,
  batteryCount: number,
  priceTiers: PriceTier[],
  isActive = true,
): LotVariant => ({
  id: uid(id),
  battery_count: batteryCount,
  is_active: isActive,
  price_tiers: priceTiers,
})

const makeLot = (
  n: number,
  slug: string,
  name: string,
  description: string,
  categoryId: string,
  characteristics: Record<string, string | number>,
  rentalUnit: RentalUnit,
  batteryType: string | null,
  allowedDurations: number[],
  variants: LotVariant[],
  status: Lot['status'] = 'active',
): MockLot => ({
  id: uid(n),
  slug,
  name,
  description,
  category_id: categoryId,
  photos: [],
  characteristics,
  rental_unit: rentalUnit,
  battery_type: batteryType,
  variants,
  allowed_durations: allowedDurations,
  currency: 'RUB',
  status,
  is_bookable: status === 'active',
  version: 1,
})

const lots: MockLot[] = [
  makeLot(
    101,
    'urban-one',
    'Urban One',
    'Лёгкий городской байк для ежедневных поездок',
    EBikes,
    { power: 500, range: 60 },
    'day',
    '48v',
    [1, 3, 7, 30],
    [
      makeVariant(1001, 1, [priceTier(1, 130000), priceTier(7, 40000), priceTier(30, 40000)]),
      makeVariant(1002, 2, [priceTier(1, 150000), priceTier(7, 50000), priceTier(30, 40000)]),
    ],
  ),
  makeLot(
    102,
    'urban-two',
    'Urban Two',
    'Тот же класс, но с багажником и корзиной',
    EBikes,
    { power: 500, range: 65 },
    'day',
    '48v',
    [1, 7, 30],
    [makeVariant(1003, 1, [priceTier(1, 130000), priceTier(7, 40000), priceTier(30, 40000)])],
  ),
  makeLot(
    103,
    'trail-pro',
    'Trail Pro',
    'Внедорожник с усиленной рамой и амортизацией',
    EBikes,
    { power: 750, range: 90 },
    'day',
    '48v',
    [1, 3, 7],
    [makeVariant(1004, 1, [priceTier(1, 180000), priceTier(3, 150000), priceTier(7, 130000)])],
  ),
  makeLot(
    104,
    'cargo-max',
    'Cargo Max',
    'Грузовой байк для перевозки до 80 кг',
    EBikes,
    { power: 1000, range: 70 },
    'day',
    '48v',
    [1, 3, 7, 30],
    [
      makeVariant(1005, 1, [priceTier(1, 240000), priceTier(7, 200000), priceTier(30, 180000)]),
      makeVariant(1006, 2, [priceTier(1, 290000), priceTier(7, 240000), priceTier(30, 220000)]),
    ],
  ),
  makeLot(
    105,
    'spare-48v',
    'Spare 48V',
    'Запасной аккумулятор 48 В, 720 Вт·ч',
    Batteries,
    { capacity: 720 },
    'day',
    null,
    [1, 7, 30],
    [makeVariant(1007, 0, [priceTier(1, 35000), priceTier(7, 30000), priceTier(30, 25000)])],
  ),
  makeLot(
    106,
    'spare-36v',
    'Spare 36V',
    'Компактный аккумулятор 36 В, 480 Вт·ч',
    Batteries,
    { capacity: 480 },
    'day',
    null,
    [1],
    [makeVariant(1008, 0, [priceTier(1, 25000)])],
    'maintenance',
  ),
]

let lotVariantSeq = 2001

/** Цена «от» и подпись в каталоге считаются сервером при каждой выдаче (D-22). */
const toLot = (lot: MockLot): Lot => ({
  ...lot,
  price_from: priceFromOf(lot.variants, lot.rental_unit),
})

interface LotFieldsInput {
  name: string
  categoryId: string | null
  characteristics: Record<string, string | number> | undefined
  rentalUnit: string | undefined
  allowedDurations: unknown
  variants: LotVariantInput[] | undefined
  batteryType: string | null
  photos: string[]
}

/** Общие проверки POST и PATCH лота: P-1…P-6 плюс обязательные характеристики. */
const lotFields = (input: LotFieldsInput): Record<string, string> => {
  const fields: Record<string, string> = {}
  const category = categories.find(item => item.id === input.categoryId)

  if (input.name.trim().length < 2) {
    fields.name = 'Минимум 2 символа'
  }

  if (!category) {
    fields.category_id = 'Выберите категорию'
  }

  if (input.rentalUnit !== 'day' && input.rentalUnit !== 'hour') {
    fields.rental_unit = 'Выберите единицу срока'
  }

  const allowedError = validateAllowedDurations(input.allowedDurations)

  if (allowedError) {
    fields.allowed_durations = allowedError
  } else {
    Object.assign(
      fields,
      validateVariants(input.variants, input.allowedDurations as number[], input.batteryType),
    )
  }

  if (category) {
    const characteristics = input.characteristics ?? {}
    const missing = category.characteristics.filter(item =>
      item.is_required
      && (characteristics[item.code] === undefined || characteristics[item.code] === ''),
    )

    if (missing.length > 0) {
      fields.characteristics = `Заполните: ${missing.map(item => item.name).join(', ')}`
    }
  }

  const invalidPhoto = input.photos.find((url) => {
    try {
      const parsed = new URL(url)

      return parsed.protocol !== 'http:' && parsed.protocol !== 'https:'
    } catch {
      return true
    }
  })

  if (invalidPhoto) {
    fields.photos = `Ссылка должна быть http(s)-адресом: ${invalidPhoto}`
  }

  return fields
}

const tenantToday = dayKeyOf(new Date(), tenant.timezone)
const tenantDayStart = (day: string): string => zonedDayStartIso(day, tenant.timezone)
let blockSeq = 810

const blocks: LotBlock[] = [
  {
    id: uid(801),
    lot_id: lots[0]!.id,
    start_time: tenantDayStart(addDays(tenantToday, 2)),
    end_time: tenantDayStart(addDays(tenantToday, 4)),
    reason: 'Техобслуживание',
    created_by: uid(902),
    created_at: iso(-HOUR),
  },
  {
    id: uid(802),
    lot_id: lots[2]!.id,
    start_time: tenantDayStart(addDays(tenantToday, 1)),
    end_time: tenantDayStart(addDays(tenantToday, 2)),
    reason: 'Плановый осмотр',
    created_by: uid(902),
    created_at: iso(-2 * HOUR),
  },
]

/**
 * Остатки АКБ (D-23). 48V = 3 при одном двухаккумуляторном лоте в брони:
 * вторая пара не проходит (пик 4 > 3), одиночная АКБ ещё влезает.
 * `peak_committed` считается при выдаче и в состоянии не хранится.
 */
const batteryStock: BatteryStock[] = [
  { battery_type: '48v', name: '48V 720 Вт·ч', quantity: 3, peak_committed: 0 },
  { battery_type: '36v', name: '36V 480 Вт·ч', quantity: 4, peak_committed: 0 },
]

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

const rentalLot = (lot: Pick<Lot, 'id' | 'slug' | 'name' | 'photos'>): Rental['lot'] => ({
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
  {
    id: uid(308),
    lot: rentalLot(lots[3]!),
    status: 'booked',
    start_time: tenantDayStart(addDays(tenantToday, 10)),
    end_time: tenantDayStart(addDays(tenantToday, 14)),
    price_minor: 1160000,
    currency: 'RUB',
    remaining_seconds: 0,
    cancellation_deadline: null,
  },
]

const userById = (id: string): User => seedUsers.find(user => user.id === id) ?? mockUser

const userRef = (user: User): AdminUserRef => ({ id: user.id, name: user.name, email: user.email })

const rentalOwners = new Map<string, User>([
  [uid(301), userById(uid(900))],
  [uid(302), userById(uid(900))],
  [uid(303), userById(uid(903))],
  [uid(304), userById(uid(904))],
  [uid(305), userById(uid(903))],
  [uid(306), userById(uid(904))],
  [uid(307), userById(uid(900))],
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

const rentalBatteries = new Map<string, number>([
  // Демо-пара 48V: лот cargo-max забронирован «с двумя» (D-23).
  [uid(308), 2],
])

/** Занятость пула считаем по броням и активным арендам; остальным seed-арендам достаётся 1 АКБ. */
const batteryCommits = (): BatteryCommit[] =>
  rentals.flatMap((rental) => {
    if (rental.status !== 'booked' && rental.status !== 'active') {
      return []
    }

    const lot = lots.find(item => item.id === rental.lot.id)
    const count = rentalBatteries.get(rental.id) ?? 1

    return lot?.battery_type && count > 0
      ? [{
          battery_type: lot.battery_type,
          count,
          start_ms: Date.parse(rental.start_time),
          end_ms: Date.parse(rental.end_time),
        }]
      : []
  })

const peakCommitted = (batteryType: string): number => peakUsage(batteryCommits(), batteryType)

/** Пик с кандидатом не должен превышать остаток (D-23). */
const capacityFits = (
  batteryType: string | null,
  count: number,
  startMs: number,
  endMs: number,
): boolean => {
  if (!batteryType || count <= 0) {
    return true
  }

  const stock = batteryStock.find(item => item.battery_type === batteryType)

  if (!stock) {
    return false
  }

  const extra: BatteryCommit = { battery_type: batteryType, count, start_ms: startMs, end_ms: endMs }

  return peakUsage(batteryCommits(), batteryType, extra) <= stock.quantity
}

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

let ticketSeq = 700

const tickets: Ticket[] = [
  {
    id: uid(601),
    rental_id: uid(301),
    lot: rentalLot(lots[0]!),
    user: userRef(userById(uid(900))),
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
    user: userRef(userById(uid(900))),
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
    lot: rentalLot(lots[0]!),
    user: userRef(userById(uid(900))),
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

/** Слот занят арендой или блокировкой — для quote и POST /rentals. */
const bookingsOverlap = (lotId: string, startMs: number, endMs: number): boolean =>
  rentals.some(rental =>
    rental.lot.id === lotId
    && ['booked', 'active', 'overdue'].includes(rental.status)
    && Date.parse(rental.start_time) < endMs
    && Date.parse(rental.end_time) > startMs,
  ) || blocks.some(block =>
    block.lot_id === lotId
    && Date.parse(block.start_time) < endMs
    && Date.parse(block.end_time) > startMs,
  )

lots.forEach((lot, lotIndex) => {
  for (let index = 1; index <= 8; index += 1) {
    const startMs = Date.now() - (index * 11 + lotIndex * 2) * 24 * HOUR - (index % 5) * HOUR
    const baseUnits = lot.rental_unit === 'hour' ? 2 + (index % 4) * 2 : 1 + (index % 3)
    const units = Math.max(baseUnits, minAllowedUnits(lot.allowed_durations))
    const endMs = startMs + units * UNIT_MS[lot.rental_unit]
    const status: Rental['status'] = index === 3 && lotIndex % 2 === 0 ? 'cancelled' : 'completed'
    const id = uid(400 + lotIndex * 10 + index)
    const variant = lot.variants[0]!

    rentals.push({
      id,
      lot: rentalLot(lot),
      status,
      start_time: new Date(startMs).toISOString(),
      end_time: new Date(endMs).toISOString(),
      price_minor: computePrice(variant.price_tiers, units).totalMinor,
      currency: tenant.currency,
      remaining_seconds: 0,
      cancellation_deadline: null,
    })
    rentalOwners.set(id, userById(lotIndex % 2 === 0 ? uid(903) : uid(904)))
    rentalVersions.set(id, 1)
    rentalBatteries.set(id, variant.battery_count)
  }
})

const REVENUE_STATUSES: Rental['status'][] = ['active', 'overdue', 'completed']

const dayKeyFor = (timeMs: number): string => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: tenant.timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(timeMs))
  const read = (type: string): string => parts.find(part => part.type === type)?.value ?? ''

  return `${read('year')}-${read('month')}-${read('day')}`
}

const rentalsInPeriod = (fromMs: number, toMs: number, lotId?: string): Rental[] =>
  rentals.filter(rental =>
    Date.parse(rental.start_time) >= fromMs
    && Date.parse(rental.start_time) < toMs
    && (!lotId || rental.lot.id === lotId),
  )

const billed = (list: Rental[]): Rental[] => list.filter(rental => REVENUE_STATUSES.includes(rental.status))

const occupancyMinutes = (list: Rental[], fromMs: number, toMs: number): number =>
  billed(list).reduce((sum, rental) => {
    const start = Math.max(Date.parse(rental.start_time), fromMs)
    const end = Math.min(Date.parse(rental.end_time), toMs)

    return sum + Math.max(end - start, 0) / 60000
  }, 0)

const utilization = (
  scoped: Rental[],
  fromMs: number,
  toMs: number,
  fleetSize: number,
): number => {
  const available = Math.max(((toMs - fromMs) / 60000) * Math.max(fleetSize, 1), 1)

  return Math.min(100, Math.round((occupancyMinutes(scoped, fromMs, toMs) / available) * 1000) / 10)
}

const analyticsSummary = (fromMs: number, toMs: number, lotId?: string): AnalyticsSummary => {
  const scoped = rentalsInPeriod(fromMs, toMs, lotId)
  const revenue = billed(scoped).reduce((sum, rental) => sum + rental.price_minor, 0)
  const cancelled = scoped.filter(rental => rental.status === 'cancelled').length
  const billableCount = scoped.length - cancelled
  const fleetSize = lotId ? 1 : lots.filter(lot => lot.status !== 'archived').length

  return {
    from: new Date(fromMs).toISOString(),
    to: new Date(toMs).toISOString(),
    revenue_minor: revenue,
    rentals_count: scoped.length,
    cancelled_count: cancelled,
    overdue_count: scoped.filter(rental => rental.status === 'overdue').length,
    avg_rental_minor: billableCount > 0 ? Math.round(revenue / billableCount) : 0,
    utilization_pct: utilization(scoped, fromMs, toMs, fleetSize),
  }
}

const makeBucket = (
  key: string,
  label: string,
  scoped: Rental[],
  fromMs: number,
  toMs: number,
  fleetSize: number,
): AnalyticsBucket => ({
  key,
  label,
  rentals_count: scoped.length,
  cancelled_count: scoped.filter(rental => rental.status === 'cancelled').length,
  revenue_minor: billed(scoped).reduce((sum, rental) => sum + rental.price_minor, 0),
  utilization_pct: utilization(scoped, fromMs, toMs, fleetSize),
})

const analyticsBuckets = (
  groupBy: 'lot' | 'category' | 'day',
  fromMs: number,
  toMs: number,
  lotId?: string,
): AnalyticsBucket[] => {
  if (groupBy === 'lot') {
    return lots
      .map(lot => makeBucket(
        lot.id,
        lot.name,
        rentalsInPeriod(fromMs, toMs, lot.id),
        fromMs,
        toMs,
        1,
      ))
      .sort((left, right) => right.revenue_minor - left.revenue_minor)
  }

  if (groupBy === 'category') {
    return categories
      .map(category => makeBucket(
        category.id,
        category.name,
        rentalsInPeriod(fromMs, toMs, lotId).filter(rental =>
          lots.find(lot => lot.id === rental.lot.id)?.category_id === category.id,
        ),
        fromMs,
        toMs,
        Math.max(lots.filter(lot => lot.category_id === category.id && lot.status !== 'archived').length, 1),
      ))
      .sort((left, right) => right.revenue_minor - left.revenue_minor)
  }

  const buckets: AnalyticsBucket[] = []
  let cursor = fromMs

  while (cursor < toMs) {
    const next = Math.min(cursor + 24 * HOUR, toMs)
    const key = dayKeyFor(cursor)

    buckets.push(makeBucket(
      key,
      key,
      rentalsInPeriod(cursor, next, lotId),
      cursor,
      next,
      1,
    ))
    cursor = next
  }

  return buckets
}

const parseAnalyticsRange = (
  query: Record<string, unknown>,
): { fromMs: number; toMs: number } | null => {
  const fromMs = typeof query.from === 'string' ? Date.parse(query.from) : Number.NaN
  const toMs = typeof query.to === 'string' ? Date.parse(query.to) : Number.NaN

  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
    return null
  }

  if (toMs <= fromMs || toMs - fromMs > 366 * 24 * HOUR) {
    return null
  }

  return { fromMs, toMs }
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
          items: filtered.slice(offset, offset + limit).map(toLot),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 120 }),

      rest.get('/api/v1/public/lots/:slug', (params) => {
        const lot = lots.find(item => item.slug === params.request.params.slug)

        return lot ? toLot(lot) : fail(params, 404, problem('not_found', 404, 'Лот не найден'))
      }),

      rest.get('/api/v1/public/lots/:slug/quote', (params) => {
        const lot = lots.find(item => item.slug === params.request.params.slug)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const query = params.request.queries as Record<string, unknown>
        const startMs = Date.parse(String(query.start ?? ''))
        const endMs = Date.parse(String(query.end ?? ''))

        if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте интервал', undefined, {
              start: 'Конец должен быть позже начала',
            }),
          )
        }

        const units = Math.ceil((endMs - startMs) / UNIT_MS[lot.rental_unit])
        const minUnits = minAllowedUnits(lot.allowed_durations)

        if (units < minUnits) {
          return fail(
            params,
            422,
            problem(
              'rental_period_not_allowed',
              422,
              'Слишком короткий срок',
              `Минимальный срок аренды — ${minUnits} ${lot.rental_unit === 'day' ? 'сут.' : 'ч'}`,
            ),
          )
        }

        const quote: Quote = {
          lot_id: lot.id,
          start: new Date(startMs).toISOString(),
          end: new Date(endMs).toISOString(),
          units,
          rental_unit: lot.rental_unit,
          variants: lot.variants
            .filter(variant => variant.is_active)
            .map((variant) => {
              const price = computePrice(variant.price_tiers, units)
              const slotTaken = bookingsOverlap(lot.id, startMs, endMs)
              const capacityOk = capacityFits(lot.battery_type, variant.battery_count, startMs, endMs)

              return {
                variant_id: variant.id,
                battery_count: variant.battery_count,
                price_total_minor: price.totalMinor,
                currency: lot.currency,
                tier_min_units: price.tierMinUnits,
                available: !slotTaken && capacityOk,
                unavailable_reason: slotTaken
                  ? 'slot_taken'
                  : capacityOk
                    ? null
                    : 'battery_unavailable',
              }
            }),
        }

        params.setHeader('Cache-Control', 'no-store')

        return quote
      }, { delay: 120 }),

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
          ...blocks
            .filter(block => block.lot_id === lot.id)
            .map(block => ({ start: block.start_time, end: block.end_time, kind: 'block' as const })),
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
          .filter(rental => rentalOwners.get(rental.id)?.id === user.id)
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

        if (!body.lot_id || !body.variant_id || !body.start_time || !body.end_time) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Нужны лот, вариант и интервал', undefined, {
              variant_id: 'Выберите вариант',
            }),
          )
        }

        const lot = lots.find(item => item.id === body.lot_id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        if (!lot.is_bookable) {
          return fail(params, 409, problem('lot_unavailable', 409, 'Лот недоступен для брони'))
        }

        const variant = lot.variants.find(item => item.id === body.variant_id && item.is_active)

        if (!variant) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              variant_id: 'Вариант недоступен',
            }),
          )
        }

        const startMs = Date.parse(body.start_time)
        const endMs = Date.parse(body.end_time)

        if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
          return fail(params, 422, problem('validation_error', 422, 'Конец должен быть позже начала'))
        }

        let price: RangePrice

        try {
          price = priceForRange(variant.price_tiers, lot.allowed_durations, lot.rental_unit, startMs, endMs)
        } catch (caught) {
          if (caught instanceof PricingError) {
            return fail(params, 422, problem(caught.code, 422, caught.message, undefined, caught.fields))
          }

          throw caught
        }

        if (bookingsOverlap(lot.id, startMs, endMs)) {
          return fail(params, 409, problem('slot_taken', 409, 'Слот занят', 'Лот занят в выбранном интервале'))
        }

        if (!capacityFits(lot.battery_type, variant.battery_count, startMs, endMs)) {
          return fail(
            params,
            409,
            problem(
              'battery_unavailable',
              409,
              'Аккумуляторов не хватает',
              'Свободных аккумуляторов на эти даты нет',
            ),
          )
        }

        const rental: Rental = {
          id: `rental-${Math.random().toString(36).slice(2, 10)}`,
          lot: rentalLot(lot),
          status: 'booked',
          start_time: new Date(startMs).toISOString(),
          end_time: new Date(endMs).toISOString(),
          price_minor: price.totalMinor,
          currency: lot.currency,
          remaining_seconds: Math.round((endMs - Date.now()) / 1000),
          cancellation_deadline: iso(24 * HOUR),
        }

        rentals.unshift(rental)
        rentalOwners.set(rental.id, user)
        rentalVersions.set(rental.id, 1)
        rentalBatteries.set(rental.id, variant.battery_count)
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

      rest.post('/api/v1/me/rentals/:id/tickets', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const rental = rentals.find(item => item.id === params.request.params.id)

        if (!rental) {
          return fail(params, 404, problem('not_found', 404, 'Бронь не найдена'))
        }

        if (rentalOwners.get(rental.id)?.id !== user.id) {
          return fail(params, 403, problem('not_your_rental', 403, 'Это не ваша аренда'))
        }

        if (rental.status !== 'active') {
          return fail(params, 409, problem('ticket_not_allowed', 409, 'Сообщить о неполадке можно только по активной аренде'))
        }

        const body = (params.request.body ?? {}) as {
          category?: string
          description?: string
          photo_urls?: string[]
        }
        const categories: Ticket['category'][] = ['no_power', 'no_drive', 'battery', 'damage', 'other']
        const description = body.description?.trim() ?? ''

        if (!body.category || !categories.includes(body.category as Ticket['category'])) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { category: 'Выберите категорию' }),
          )
        }

        if (description.length < 10 || description.length > 1000) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { description: 'Описание от 10 до 1000 символов' }),
          )
        }

        const since = Date.now() - 24 * HOUR
        const createdToday = tickets.filter(ticket =>
          ticket.rental_id === rental.id && ticket.user.id === user.id && Date.parse(ticket.created_at) > since,
        ).length

        if (createdToday >= 5) {
          return fail(params, 429, problem('ticket_limit', 429, 'Лимит обращений: не более 5 в сутки по одной аренде'))
        }

        const ticket: Ticket = {
          id: uid(ticketSeq++),
          rental_id: rental.id,
          lot: rental.lot,
          user: userRef(user),
          category: body.category as Ticket['category'],
          description,
          photo_urls: Array.isArray(body.photo_urls)
            ? body.photo_urls.filter((url): url is string => typeof url === 'string').slice(0, 3)
            : [],
          status: 'submitted',
          admin_comment: null,
          created_at: iso(0),
          resolved_at: null,
          version: 1,
        }

        tickets.unshift(ticket)
        params.setStatusCode(201)

        return ticket
      }, { delay: 150 }),

      rest.get('/api/v1/me/tickets', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        const query = params.request.queries as Record<string, unknown>
        const status = typeof query.status === 'string' ? query.status : undefined
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = tickets.filter(ticket =>
          ticket.user.id === user.id && (!status || ticket.status === status),
        )

        const page: TicketPage = {
          items: filtered.slice(offset, offset + limit),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 80 }),

      rest.get('/api/v1/admin/analytics/summary', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const range = parseAnalyticsRange(query)

        if (!range) {
          return fail(params, 422, problem('validation_error', 422, 'Проверьте период'))
        }

        return analyticsSummary(range.fromMs, range.toMs)
      }, { delay: 100 }),

      rest.get('/api/v1/admin/analytics/revenue', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const range = parseAnalyticsRange(query)
        const groupBy = query.group_by

        if (!range) {
          return fail(params, 422, problem('validation_error', 422, 'Проверьте период'))
        }

        if (groupBy !== 'lot' && groupBy !== 'category' && groupBy !== 'day') {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { group_by: 'Недопустимая группировка' }),
          )
        }

        const response: AnalyticsRevenue = {
          group_by: groupBy,
          buckets: analyticsBuckets(groupBy, range.fromMs, range.toMs),
        }

        return response
      }, { delay: 100 }),

      rest.get('/api/v1/admin/analytics/lots/:lot_id', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const range = parseAnalyticsRange(query)

        if (!range) {
          return fail(params, 422, problem('validation_error', 422, 'Проверьте период'))
        }

        const lot = lots.find(item => item.id === params.request.params.lot_id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const scoped = rentalsInPeriod(range.fromMs, range.toMs, lot.id)
          .slice()
          .sort((left, right) => right.start_time.localeCompare(left.start_time))

        const detail: AnalyticsLotDetail = {
          lot: toLot(lot),
          from: new Date(range.fromMs).toISOString(),
          to: new Date(range.toMs).toISOString(),
          summary: analyticsSummary(range.fromMs, range.toMs, lot.id),
          daily: analyticsBuckets('day', range.fromMs, range.toMs, lot.id),
          rentals: scoped.map(rental => ({
            id: rental.id,
            start_time: rental.start_time,
            end_time: rental.end_time,
            status: rental.status,
            price_minor: rental.price_minor,
            currency: rental.currency,
            user: userRef(rentalOwners.get(rental.id) ?? mockUser),
          })),
        }

        return detail
      }, { delay: 120 }),

      rest.get('/api/v1/admin/lots', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const category = typeof query.category_id === 'string' ? query.category_id : undefined
        const status = typeof query.status === 'string' ? query.status : undefined
        const search = typeof query.q === 'string' ? query.q.toLowerCase() : ''
        const limit = Number(query.limit ?? 20)
        const offset = Number(query.offset ?? 0)

        const filtered = lots.filter(lot =>
          (!category || lot.category_id === category)
          && (!status || lot.status === status)
          && (!search || lot.name.toLowerCase().includes(search) || lot.slug.includes(search)),
        )

        const page: LotPage = {
          items: filtered.slice(offset, offset + limit).map(toLot),
          total: filtered.length,
          limit,
          offset,
        }

        return page
      }, { delay: 80 }),

      rest.post('/api/v1/admin/lots', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const body = (params.request.body ?? {}) as Partial<CreateLotRequest>
        const name = body.name?.trim() ?? ''
        const batteryType = body.battery_type ?? null
        const photos = Array.isArray(body.photos)
          ? body.photos.filter(url => typeof url === 'string' && url.trim().length > 0)
          : []
        const fields = lotFields({
          name,
          categoryId: body.category_id ?? null,
          characteristics: body.characteristics,
          rentalUnit: body.rental_unit,
          allowedDurations: body.allowed_durations,
          variants: body.variants,
          batteryType,
          photos,
        })

        if (Object.keys(fields).length > 0) {
          return fail(params, 422, problem('validation_error', 422, 'Проверьте поля', undefined, fields))
        }

        const status = body.status === 'archived' || body.status === 'maintenance' ? body.status : 'active'
        const baseSlug = slugify(name)
        let slug = baseSlug
        let suffix = 1

        while (lots.some(item => item.slug === slug)) {
          suffix += 1
          slug = `${baseSlug}-${suffix}`
        }

        const lot: MockLot = {
          id: uid(110 + lots.length),
          slug,
          name,
          description: body.description?.trim() ?? '',
          category_id: body.category_id!,
          photos,
          characteristics: body.characteristics ?? {},
          rental_unit: body.rental_unit as RentalUnit,
          battery_type: batteryType,
          variants: (body.variants ?? []).map(variant => ({
            id: uid(lotVariantSeq++),
            battery_count: variant.battery_count,
            is_active: variant.is_active ?? true,
            price_tiers: variant.price_tiers,
          })),
          allowed_durations: body.allowed_durations ?? [],
          currency: tenant.currency,
          status,
          is_bookable: status === 'active',
          version: 1,
        }

        lots.unshift(lot)
        params.setStatusCode(201)

        return toLot(lot)
      }, { delay: 150 }),

      rest.patch('/api/v1/admin/lots/:id', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const lot = lots.find(item => item.id === params.request.params.id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const body = (params.request.body ?? {}) as Partial<UpdateLotRequest>

        if (typeof body.version !== 'number' || !Number.isInteger(body.version)) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { version: 'Укажите версию лота' }),
          )
        }

        if (body.version !== lot.version) {
          return fail(
            params,
            409,
            problem('stale_version', 409, 'Лот изменён', 'Лот изменён другим администратором'),
          )
        }

        const name = body.name?.trim() ?? lot.name
        const characteristics = body.characteristics ?? lot.characteristics
        const batteryType = body.battery_type !== undefined ? body.battery_type : lot.battery_type
        const allowedDurations = body.allowed_durations ?? lot.allowed_durations
        const photos = Array.isArray(body.photos)
          ? body.photos.filter(url => typeof url === 'string' && url.trim().length > 0)
          : lot.photos
        const mergedVariants: LotVariantInput[] = body.variants ?? lot.variants.map(variant => ({
          battery_count: variant.battery_count,
          is_active: variant.is_active,
          price_tiers: variant.price_tiers,
        }))
        const fields = lotFields({
          name,
          categoryId: body.category_id ?? lot.category_id,
          characteristics,
          rentalUnit: body.rental_unit ?? lot.rental_unit,
          allowedDurations,
          variants: mergedVariants,
          batteryType,
          photos,
        })

        if (Object.keys(fields).length > 0) {
          return fail(params, 422, problem('validation_error', 422, 'Проверьте поля', undefined, fields))
        }

        lot.name = name
        lot.category_id = body.category_id ?? lot.category_id
        lot.description = body.description !== undefined ? body.description.trim() : lot.description
        lot.photos = photos
        lot.characteristics = characteristics
        lot.rental_unit = (body.rental_unit ?? lot.rental_unit) as RentalUnit
        lot.battery_type = batteryType
        lot.allowed_durations = allowedDurations
        lot.variants = mergedVariants.map((variant, index) => ({
          id: lot.variants[index]?.id ?? uid(lotVariantSeq++),
          battery_count: variant.battery_count,
          is_active: variant.is_active ?? true,
          price_tiers: variant.price_tiers,
        }))

        if (body.status) {
          lot.status = body.status
          lot.is_bookable = body.status === 'active'
        }

        lot.version += 1

        return toLot(lot)
      }, { delay: 150 }),

      rest.post('/api/v1/admin/lots/:id/status', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const lot = lots.find(item => item.id === params.request.params.id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const body = (params.request.body ?? {}) as Partial<LotStatusRequest>
        const status = body.status

        if (status !== 'active' && status !== 'archived' && status !== 'maintenance') {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, { status: 'Недопустимый статус' }),
          )
        }

        const hasActiveRentals = rentals.some(rental =>
          rental.lot.id === lot.id && ['booked', 'active', 'overdue'].includes(rental.status),
        )

        if (status === 'archived' && hasActiveRentals) {
          return fail(
            params,
            409,
            problem('lot_has_active_rental', 409, 'У лота есть активные аренды'),
          )
        }

        lot.status = status
        lot.is_bookable = status === 'active'
        lot.version += 1

        return toLot(lot)
      }, { delay: 120 }),

      rest.post('/api/v1/admin/lots/:id/blocks', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const lot = lots.find(item => item.id === params.request.params.id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const body = (params.request.body ?? {}) as Partial<CreateLotBlockRequest>
        const reason = body.reason?.trim() ?? ''

        if (reason.length < 3 || reason.length > 200) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              reason: 'Причина от 3 до 200 символов',
            }),
          )
        }

        const startMs = Date.parse(body.start_time ?? '')
        const endMs = Date.parse(body.end_time ?? '')

        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              start_time: 'Укажите период',
            }),
          )
        }

        const startIso = tenantDayStart(dayKeyOf(new Date(startMs), tenant.timezone))
        const endIso = tenantDayStart(dayKeyOf(new Date(endMs), tenant.timezone))
        const start = Date.parse(startIso)
        const end = Date.parse(endIso)

        if (end <= start) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              end_time: 'Конец должен быть позже начала',
            }),
          )
        }

        const rentalConflict = rentals.some(rental =>
          rental.lot.id === lot.id
          && ['booked', 'active'].includes(rental.status)
          && Date.parse(rental.start_time) < end
          && Date.parse(rental.end_time) > start,
        )
        const blockConflict = blocks.some(block =>
          block.lot_id === lot.id
          && Date.parse(block.start_time) < end
          && Date.parse(block.end_time) > start,
        )

        if (rentalConflict || blockConflict) {
          return fail(params, 409, problem('slot_taken', 409, 'Слот занят', 'В эти дни лот занят'))
        }

        const block: LotBlock = {
          id: uid(blockSeq++),
          lot_id: lot.id,
          start_time: startIso,
          end_time: endIso,
          reason,
          created_by: user.id,
          created_at: iso(0),
        }

        blocks.push(block)
        params.setStatusCode(201)

        return block
      }, { delay: 120 }),

      rest.delete('/api/v1/admin/lots/:id/blocks/:block_id', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const lot = lots.find(item => item.id === params.request.params.id)

        if (!lot) {
          return fail(params, 404, problem('not_found', 404, 'Лот не найден'))
        }

        const index = blocks.findIndex(block =>
          block.id === params.request.params.block_id && block.lot_id === lot.id,
        )

        if (index === -1) {
          return fail(params, 404, problem('not_found', 404, 'Блокировка не найдена'))
        }

        blocks.splice(index, 1)
        params.setStatusCode(204)

        return null
      }, { delay: 80 }),

      rest.get('/api/v1/admin/schedule', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'admin' && user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Недостаточно прав'))
        }

        const query = params.request.queries as Record<string, unknown>
        const from = typeof query.from === 'string' ? query.from : ''
        const to = typeof query.to === 'string' ? query.to : ''
        const datePattern = /^\d{4}-\d{2}-\d{2}$/
        const fromMs = Date.parse(`${from}T00:00:00Z`)
        const toMs = Date.parse(`${to}T00:00:00Z`)

        if (
          !datePattern.test(from)
          || !datePattern.test(to)
          || !Number.isFinite(fromMs)
          || !Number.isFinite(toMs)
          || toMs <= fromMs
          || toMs - fromMs > 90 * 24 * HOUR
        ) {
          return fail(params, 422, problem('validation_error', 422, 'Окно не должно превышать 90 дней'))
        }

        const rangeStart = Date.parse(tenantDayStart(from))
        const rangeEnd = Date.parse(tenantDayStart(to))
        const category = typeof query.category_id === 'string' ? query.category_id : undefined
        const scopedLots = lots.filter(lot => !category || lot.category_id === category)
        const lotIds = new Set(scopedLots.map(lot => lot.id))

        const intervals: (ScheduleRentalInterval | ScheduleBlockInterval)[] = [
          ...rentals
            .filter(rental =>
              rental.status !== 'cancelled'
              && lotIds.has(rental.lot.id)
              && Date.parse(rental.start_time) < rangeEnd
              && Date.parse(rental.end_time) > rangeStart,
            )
            .map(rental => ({
              id: rental.id,
              lot_id: rental.lot.id,
              kind: 'rental' as const,
              start_time: rental.start_time,
              end_time: rental.end_time,
              rental_id: rental.id,
              status: rental.status,
              battery_count: rentalBatteries.get(rental.id) ?? 1,
              user_name: (rentalOwners.get(rental.id) ?? mockUser).name,
            })),
          ...blocks
            .filter(block =>
              lotIds.has(block.lot_id)
              && Date.parse(block.start_time) < rangeEnd
              && Date.parse(block.end_time) > rangeStart,
            )
            .map(block => ({
              id: block.id,
              lot_id: block.lot_id,
              kind: 'block' as const,
              start_time: block.start_time,
              end_time: block.end_time,
              block_id: block.id,
              reason: block.reason,
            })),
        ].sort((left, right) => left.start_time.localeCompare(right.start_time))

        const schedule: AdminSchedule = {
          lots: scopedLots.map(lot => ({
            id: lot.id,
            name: lot.name,
            category_id: lot.category_id,
            status: lot.status,
            battery_type: lot.battery_type,
            rental_unit: lot.rental_unit,
          })),
          intervals,
          battery_stock: batteryStock.map(item => ({
            ...item,
            peak_committed: peakCommitted(item.battery_type),
          })),
        }

        params.setHeader('Cache-Control', 'no-store')

        return schedule
      }, { delay: 120 }),

      rest.get('/api/v1/admin/batteries', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Раздел доступен только владельцу'))
        }

        params.setHeader('Cache-Control', 'no-store')

        return batteryStock.map(item => ({
          ...item,
          peak_committed: peakCommitted(item.battery_type),
        }))
      }, { delay: 80 }),

      rest.patch('/api/v1/admin/batteries/:battery_type', (params) => {
        const user = currentUser(params)

        if (!user) {
          return fail(params, 401, problem('token_invalid', 401, 'Требуется вход'))
        }

        if (user.role !== 'owner') {
          return fail(params, 403, problem('forbidden_role', 403, 'Раздел доступен только владельцу'))
        }

        const stock = batteryStock.find(item => item.battery_type === params.request.params.battery_type)

        if (!stock) {
          return fail(params, 404, problem('not_found', 404, 'Тип аккумулятора не найден'))
        }

        const body = (params.request.body ?? {}) as Partial<UpdateBatteryStockRequest>
        const quantity = body.quantity
        const peak = peakCommitted(stock.battery_type)

        if (typeof quantity !== 'number' || !Number.isInteger(quantity) || quantity < 0) {
          return fail(
            params,
            422,
            problem('validation_error', 422, 'Проверьте поля', undefined, {
              quantity: 'Целое число от 0',
            }),
          )
        }

        if (quantity < peak) {
          return fail(
            params,
            409,
            problem(
              'stock_below_committed',
              409,
              'Нельзя уменьшить остаток',
              `Нельзя уменьшить: ${peak} шт. уже забронированы`,
              { quantity: `Занято ${peak} шт. — уменьшить нельзя` },
            ),
          )
        }

        stock.quantity = quantity

        return { ...stock, peak_committed: peak }
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
