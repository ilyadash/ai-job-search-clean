// Data source: HeadHunter (hh.ru) public API v3 — https://api.hh.ru.
//
// Search and detail require an access token: anonymous requests to /vacancies
// are rejected with HTTP 403 (captcha), verified live 2026-10-01. The token is
// read only from HH_API_TOKEN, never from a CLI flag. hh.ru additionally
// requires a User-Agent header and an HH-User-Agent header naming the
// application and a contact email (see SKILL.md Setup).

export const DEFAULT_USER_AGENT = "hhru-search-cli/1.0 (personal job search)"

export class CliError extends Error {
  readonly code: string
  constructor(message: string, code: string) {
    super(message)
    this.code = code
  }
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

export function apiBase(): string {
  return (process.env.HH_API_BASE_URL ?? "https://api.hh.ru").replace(/\/+$/, "")
}

export interface Credentials {
  token: string
  userAgent: string
}

export function readCredentials(): Credentials {
  const token = (process.env.HH_API_TOKEN ?? "").trim()
  if (!token) {
    throw new CliError(
      "HH_API_TOKEN is not set. hh.ru vacancy search/detail requires an application or user token (anonymous requests get HTTP 403 captcha). Add HH_API_TOKEN=<token> (and HH_USER_AGENT=<app name + contact email>) to .env.docker in the repo root, then recreate the container. See the skill's SKILL.md Setup section.",
      "MISSING_CREDENTIALS",
    )
  }
  const userAgent = (process.env.HH_USER_AGENT ?? "").trim() || DEFAULT_USER_AGENT
  return { token, userAgent }
}

export function authHeaders(creds: Credentials): Record<string, string> {
  return {
    Authorization: `Bearer ${creds.token}`,
    "User-Agent": creds.userAgent,
    "HH-User-Agent": creds.userAgent,
    Accept: "application/json",
  }
}

interface ApiErrorBody {
  errors?: Array<{ type?: string; value?: string }>
  description?: string
  request_id?: string
}

function apiErrorDetail(body: ApiErrorBody | null): string {
  if (!body) return ""
  const parts: string[] = []
  if (body.errors?.length) {
    parts.push(body.errors.map((e) => [e.type, e.value].filter(Boolean).join("=")).join("; "))
  }
  if (body.description) parts.push(body.description)
  if (body.request_id) parts.push(`request_id=${body.request_id}`)
  return parts.length ? ` (${parts.join("; ")})` : ""
}

/**
 * Fetch JSON from the hh.ru API with exponential backoff on 429/5xx.
 * Returns null on 404 when `allow404` is set. Never logs the token.
 */
export async function apiFetchJson<T>(
  path: string,
  params?: URLSearchParams,
  opts: { allow404?: boolean } = {},
): Promise<T | null> {
  const creds = readCredentials()
  const qs = params && params.toString() ? `?${params.toString()}` : ""
  const url = `${apiBase()}${path}${qs}`
  const maxRetries = 6
  let delay = 500

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const response = await fetch(url, {
      headers: authHeaders(creds),
      redirect: "follow",
      signal: AbortSignal.timeout(20000),
    })

    if (response.status === 429 || response.status >= 500) {
      if (attempt === maxRetries) {
        throw new CliError(`Request failed: ${response.status} ${response.statusText}`, "HTTP_ERROR")
      }
      const jitter = Math.floor(Math.random() * 500)
      await new Promise((r) => setTimeout(r, delay + jitter))
      delay = Math.min(delay * 2, 8000)
      continue
    }
    if (response.status === 404) {
      if (opts.allow404) return null
      throw new CliError("Not found", "NOT_FOUND")
    }
    if (response.status === 401) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null
      throw new CliError(
        `hh.ru rejected the token (HTTP 401)${apiErrorDetail(body)}. Check HH_API_TOKEN.`,
        "UNAUTHORIZED",
      )
    }
    if (response.status === 403) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null
      const captcha = body?.errors?.some((e) => e.type?.includes("captcha"))
      throw new CliError(
        captcha
          ? `hh.ru requires captcha (HTTP 403)${apiErrorDetail(body)}. This usually means the token is missing or not valid for this method; check HH_API_TOKEN.`
          : `hh.ru denied the request (HTTP 403)${apiErrorDetail(body)}. Check HH_API_TOKEN and HH_USER_AGENT (app name + contact email).`,
        captcha ? "CAPTCHA_REQUIRED" : "FORBIDDEN",
      )
    }
    if (response.status === 400) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null
      throw new CliError(`hh.ru rejected the request parameters (HTTP 400)${apiErrorDetail(body)}`, "BAD_REQUEST")
    }
    if (!response.ok) {
      throw new CliError(`Request failed: ${response.status} ${response.statusText}`, "HTTP_ERROR")
    }
    return (await response.json()) as T
  }
  throw new CliError("Request failed after max retries", "HTTP_ERROR")
}

// ---------------------------------------------------------------------------
// Area (location) resolution
// ---------------------------------------------------------------------------

export interface HhAreaNode {
  id: string
  name: string
  areas?: HhAreaNode[]
}

/** Area ids that are stable and well-known; everything else resolves via /areas. */
export const AREA_ALIASES: Record<string, string> = {
  "москва": "1",
  "moscow": "1",
  "мск": "1",
  "msk": "1",
  "санкт-петербург": "2",
  "saint petersburg": "2",
  "st petersburg": "2",
  "st. petersburg": "2",
  "спб": "2",
  "spb": "2",
  "питер": "2",
}

export function areaAlias(input: string): string | null {
  return AREA_ALIASES[input.trim().toLowerCase()] ?? null
}

function collectAreas(nodes: HhAreaNode[], out: HhAreaNode[] = []): HhAreaNode[] {
  for (const node of nodes) {
    out.push(node)
    if (node.areas?.length) collectAreas(node.areas, out)
  }
  return out
}

/** Match a name against the /areas tree: exact, then prefix, then substring. */
export function findAreaId(countries: HhAreaNode[], name: string): string | null {
  const wanted = name.trim().toLowerCase()
  if (!wanted) return null
  const all = collectAreas(countries)
  for (const match of [all.filter((a) => a.name.toLowerCase() === wanted), all.filter((a) => a.name.toLowerCase().startsWith(wanted)), all.filter((a) => a.name.toLowerCase().includes(wanted))]) {
    if (match.length) return match[0].id
  }
  return null
}

export async function resolveAreaId(location: string): Promise<string> {
  const raw = location.trim()
  if (/^\d+$/.test(raw)) return raw
  const alias = areaAlias(raw)
  if (alias) return alias
  const countries = await apiFetchJson<HhAreaNode[]>("/areas")
  const id = countries ? findAreaId(countries, raw) : null
  if (!id) {
    throw new CliError(
      `Could not resolve location "${location}" to an hh.ru area id. Try "Москва"/"Moscow", a numeric area id, or a name from hh.ru's /areas dictionary.`,
      "AREA_NOT_FOUND",
    )
  }
  return id
}

// ---------------------------------------------------------------------------
// HTML / entity handling
// ---------------------------------------------------------------------------

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

/** Convert an hh.ru HTML fragment (description, snippet) to readable text. */
export function htmlToText(html: string): string {
  const withBreaks = html
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|ul|ol|div|h\d|tr)>/gi, "\n")
  return decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

// ---------------------------------------------------------------------------
// Response mapping
// ---------------------------------------------------------------------------

export interface HhIdName {
  id?: string | null
  name?: string | null
}

export interface HhSalary {
  from?: number | null
  to?: number | null
  currency?: string | null
  gross?: boolean | null
  mode?: HhIdName | null
}

export interface HhSnippet {
  requirement?: string | null
  responsibility?: string | null
}

export interface HhEmployer {
  id?: string | null
  name?: string | null
  alternate_url?: string | null
}

export interface HhSearchItem {
  id: string
  name?: string | null
  area?: HhIdName | null
  employer?: HhEmployer | null
  published_at?: string | null
  alternate_url?: string | null
  apply_alternate_url?: string | null
  url?: string | null
  salary?: HhSalary | null
  salary_range?: HhSalary | null
  experience?: HhIdName | null
  employment?: HhIdName | null
  employment_form?: HhIdName | null
  schedule?: HhIdName | null
  work_format?: HhIdName[] | null
  work_schedule_by_days?: HhIdName[] | null
  professional_roles?: HhIdName[] | null
  snippet?: HhSnippet | null
  archived?: boolean | null
}

/** Contract shape consumed by /scrape: id/title/company/location/date/url are guaranteed. */
export interface SearchResult {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string | null
  archived: boolean | null
  salary: HhSalary | null
  experience: string | null
  employment: string | null
  workFormat: string[] | null
  snippet: string | null
}

export function isoDate(value: string | null | undefined): string | null {
  return value ? value.slice(0, 10) : null
}

function idName(value: HhIdName | null | undefined): string | null {
  return value?.name ?? null
}

function idNames(values: HhIdName[] | null | undefined): string[] | null {
  if (!values?.length) return null
  const names = values.map((v) => v.name).filter((n): n is string => Boolean(n))
  return names.length ? names : null
}

export function snippetText(snippet: HhSnippet | null | undefined): string | null {
  if (!snippet) return null
  const parts = [snippet.requirement, snippet.responsibility]
    .filter((p): p is string => Boolean(p))
    .map((p) => htmlToText(p))
    .filter(Boolean)
  return parts.length ? parts.join(" · ") : null
}

export function mapSearchItem(item: HhSearchItem): SearchResult {
  return {
    id: item.id,
    title: item.name ?? "(untitled)",
    company: item.employer?.name ?? null,
    location: item.area?.name ?? null,
    date: isoDate(item.published_at),
    url: item.alternate_url ?? (item.id ? `https://hh.ru/vacancy/${item.id}` : null),
    archived: item.archived ?? null,
    salary: item.salary_range ?? item.salary ?? null,
    experience: idName(item.experience),
    employment: idName(item.employment_form) ?? idName(item.employment),
    workFormat: idNames(item.work_format),
    snippet: snippetText(item.snippet),
  }
}

export interface HhVacancyDetail extends HhSearchItem {
  description?: string | null
  key_skills?: Array<{ name?: string | null }> | null
  closed_for_applicants?: boolean | null
}

export interface JobDetail {
  id: string
  title: string
  company: string | null
  companyUrl: string | null
  location: string | null
  date: string | null
  url: string | null
  applyUrl: string | null
  description: string | null
  keySkills: string[] | null
  experience: string | null
  employment: string | null
  workFormat: string[] | null
  scheduleByDays: string[] | null
  professionalRoles: string[] | null
  salary: HhSalary | null
  publishedAt: string | null
  archived: boolean | null
  isActive: boolean
  deadline: null
}

export function mapVacancy(vacancy: HhVacancyDetail): JobDetail {
  const base = mapSearchItem(vacancy)
  const skills = vacancy.key_skills?.map((k) => k.name).filter((n): n is string => Boolean(n)) ?? null
  const archived = vacancy.archived ?? null
  return {
    ...base,
    companyUrl: vacancy.employer?.alternate_url ?? null,
    applyUrl: vacancy.apply_alternate_url ?? null,
    description: vacancy.description ? htmlToText(vacancy.description) : null,
    keySkills: skills?.length ? skills : null,
    scheduleByDays: idNames(vacancy.work_schedule_by_days),
    professionalRoles: idNames(vacancy.professional_roles),
    publishedAt: vacancy.published_at ?? null,
    archived,
    // hh.ru has no explicit "closed" banner; archived=true or
    // closed_for_applicants=true is the available signal.
    isActive: archived !== true && vacancy.closed_for_applicants !== true,
    // hh.ru vacancies carry no application-deadline field (verified against the
    // OpenAPI spec: only ChatsCommonFilesUploadLinksResponse has expires_at).
    deadline: null,
  }
}
