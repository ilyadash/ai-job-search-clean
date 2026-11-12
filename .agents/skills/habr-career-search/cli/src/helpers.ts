// Data source: career.habr.com public listing and vacancy pages. No credentials.
//
// Both page types embed their full server-side state in one
//   <script type="application/json" data-ssr-state="true">{ ... }</script>
// tag. This CLI parses that JSON, not the rendered markup: the state blob
// carries more fields than the cards render (qualification, salary,
// locations, archived) and survives presentational HTML changes - only the
// state field names matter. Schema and observed values: url-reference.md.

export const BASE_URL = "https://career.habr.com"

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

const UA = "Mozilla/5.0 (compatible; habr-career-search-cli/1.0)"

/** Fetch HTML with exponential backoff on 429/5xx. Returns "" on a 404. */
export async function htmlFetch(url: string): Promise<string> {
  const maxRetries = 5
  let delay = 500
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: {
        "User-Agent": UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
      },
      redirect: "follow",
      signal: AbortSignal.timeout(15000),
    })
    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Request failed: ${response.status} ${response.statusText}`)
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) return ""
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status} ${response.statusText}`)
    }
    return response.text()
  }
  throw new Error("Request failed after max retries")
}

// ---- SSR state extraction -------------------------------------------------

const SSR_RE = /<script type="application\/json" data-ssr-state="true">([\s\S]*?)<\/script>/i

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

/**
 * Extract the page's embedded SSR state. Returns null when the page carries no
 * state blob or it is not valid JSON - the caller must treat that as a parse
 * failure, never as "no results" (a bot-wall or error page renders no blob).
 */
export function extractSsrState(html: string): Record<string, unknown> | null {
  const match = SSR_RE.exec(html)
  if (!match) return null
  try {
    return asRecord(JSON.parse(match[1]))
  } catch {
    return null
  }
}

/** "2026-09-29T10:23:58+03:00" -> "2026-09-29" */
export function isoDay(value: unknown): string | null {
  const s = str(value)
  if (!s) return null
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/)
  return m ? m[1] : null
}

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

/** Convert a vacancy description's HTML to plain text, keeping block breaks. */
export function htmlToText(html: string): string {
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/\s*(p|li|ul|ol|div|h[1-6])>/gi, "\n")
  return decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

// ---- models ---------------------------------------------------------------

export interface HabrCard {
  id: string
  title: string
  company: string | null
  companyUrl: string | null
  location: string | null
  date: string | null
  url: string
  publishedAt: string | null
  qualification: string | null
  salary: string | null
  remoteWork: boolean
  skills: string[]
  archived: boolean
}

export interface HabrDetail extends HabrCard {
  description: string | null
  employment: string | null
  /** Habr vacancies carry no application deadline; postings are archived instead. */
  deadline: null
  /** false when the vacancy is archived and no longer accepting responses. */
  isActive: boolean
}

function formatLocations(v: Record<string, unknown>): string | null {
  const names = asArray(v.locations)
    .map((l) => str(asRecord(l)?.title))
    .filter((t): t is string => t !== null)
  if (names.length > 0) return names.join(", ")
  return str(asRecord(v.location)?.title)
}

function toCard(v: Record<string, unknown>): HabrCard | null {
  const id = num(v.id)
  const title = str(v.title)
  if (id === null || !title) return null
  const company = asRecord(v.company)
  const companyHref = str(company?.href)
  const publishedDate = asRecord(v.publishedDate)
  const salary = asRecord(v.salary)
  const href = str(v.href)
  return {
    id: String(id),
    title: str(v.title) ?? "(untitled)",
    company: str(company?.title),
    companyUrl: companyHref ? `${BASE_URL}${companyHref}` : null,
    location: formatLocations(v),
    date: isoDay(publishedDate?.date),
    url: href ? `${BASE_URL}${href}` : `${BASE_URL}/vacancies/${id}`,
    publishedAt: str(publishedDate?.date),
    qualification: str(v.qualification),
    salary: str(salary?.formatted),
    remoteWork: v.remoteWork === true,
    skills: asArray(v.skills)
      .map((s) => str(asRecord(s)?.title))
      .filter((t): t is string => t !== null),
    archived: v.archived === true,
  }
}

export interface SearchMeta {
  totalResults: number | null
  perPage: number | null
  currentPage: number | null
  totalPages: number | null
}

export interface SearchPage {
  results: HabrCard[]
  meta: SearchMeta
}

/** Parse a /vacancies listing page. null = the SSR state contract was not found. */
export function parseSearchPage(html: string): SearchPage | null {
  const state = extractSsrState(html)
  if (!state) return null
  const vacancies = asRecord(state.vacancies)
  if (!vacancies) return null
  const results = asArray(vacancies.list)
    .map((entry) => toCard(asRecord(entry) ?? {}))
    .filter((card): card is HabrCard => card !== null)
  const meta = asRecord(vacancies.meta) ?? {}
  return {
    results,
    meta: {
      totalResults: num(meta.totalResults),
      perPage: num(meta.perPage),
      currentPage: num(meta.currentPage),
      totalPages: num(meta.totalPages),
    },
  }
}

/** Parse a /vacancies/{id} page. null = the SSR state contract was not found. */
export function parseDetailPage(html: string, fallbackId: string): HabrDetail | null {
  const state = extractSsrState(html)
  if (!state) return null
  const v = asRecord(state.vacancy)
  if (!v) return null
  const card: HabrCard = toCard(v) ?? {
    id: fallbackId,
    title: "(untitled)",
    company: null,
    companyUrl: null,
    location: null,
    date: null,
    url: `${BASE_URL}/vacancies/${fallbackId}`,
    publishedAt: null,
    qualification: null,
    salary: null,
    remoteWork: false,
    skills: [],
    archived: false,
  }
  return {
    ...card,
    location: str(v.humanCityNames) ?? card.location,
    description: htmlToText(str(v.description) ?? "") || null,
    employment: str(v.employment),
    deadline: null,
    isActive: v.archived !== true,
  }
}

// ---- filters --------------------------------------------------------------

/**
 * Qualification ids observed live (2026-10-01): intern=1, junior=3, middle=4,
 * senior=5, lead=6. The param accepts one value per request, so multi-level
 * searches issue one request per level and merge (see commands/search.ts).
 */
export const LEVEL_QID: Record<string, number> = {
  intern: 1,
  junior: 3,
  middle: 4,
  senior: 5,
  lead: 6,
}

export function resolveLevels(levels: string[]): number[] | null {
  const qids: number[] = []
  for (const level of levels) {
    const qid = LEVEL_QID[level.toLowerCase()]
    if (qid === undefined) return null
    qids.push(qid)
  }
  return qids
}

/**
 * City ids verified against live listing hrefs (city_id in each card's
 * locations[].href). Unknown names are rejected rather than silently
 * searching the whole country; numeric ids pass through for anything else.
 */
export const CITY_ALIASES: Record<string, string> = {
  "москва": "678",
  "moscow": "678",
  "санкт-петербург": "679",
  "санкт петербург": "679",
  "спб": "679",
  "питер": "679",
  "saint petersburg": "679",
  "st petersburg": "679",
  "st. petersburg": "679",
  "екатеринбург": "693",
  "пермь": "722",
  "томск": "736",
  "уфа": "740",
  "сочи": "3394",
  "липецк": "712",
}

export function resolveCityId(input: string): string | null {
  const trimmed = input.trim()
  if (/^\d+$/.test(trimmed)) return trimmed
  return CITY_ALIASES[trimmed.toLowerCase()] ?? null
}

/** Accept a bare vacancy id or a career.habr.com/vacancies/<id> URL. */
export function normalizeId(input: string): string | null {
  const url = input.match(/\/vacancies\/(\d{6,})(?:[/?#]|$)/)
  if (url) return url[1]
  const bare = input.match(/^\d{6,}$/)
  if (bare) return input
  return null
}

/** True when a posting's timestamp is inside the last N days. */
export function isWithinWindow(
  publishedAt: string | null,
  date: string | null,
  days: number,
  now: number = Date.now(),
): boolean {
  const stamp = publishedAt ?? (date ? `${date}T00:00:00+03:00` : null)
  if (!stamp) return false
  const ts = Date.parse(stamp)
  if (Number.isNaN(ts)) return false
  return now - ts <= days * 86400_000
}
