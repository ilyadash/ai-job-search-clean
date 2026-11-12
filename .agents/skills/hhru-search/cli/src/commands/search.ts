import {
  apiFetchJson,
  mapSearchItem,
  resolveAreaId,
  writeError,
  CliError,
  type HhSearchItem,
  type SearchResult,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  location?: string
  area?: string
  jobage?: number
  experience?: string[]
  employment?: string[]
  workFormat?: string[]
  scheduleByDays?: string[]
  page: number
  perPage: number
  limit?: number
  orderBy?: string
  format: "json" | "table" | "plain"
}

interface HhSearchResponse {
  found?: number
  pages?: number
  per_page?: number
  page?: number
  items?: HhSearchItem[]
}

/** hh.ru caps pagination at 2000 results regardless of per_page. */
export const MAX_DEPTH = 2000

export function buildSearchParams(opts: SearchOpts, areaId: string | null, apiPage: number): URLSearchParams {
  const params = new URLSearchParams()
  if (opts.query) params.set("text", opts.query)
  if (areaId) params.set("area", areaId)
  if (opts.jobage !== undefined) params.set("period", String(opts.jobage))
  // hh.ru's multi-value parameters are repeated query keys
  // (experience=a&experience=b). A comma-joined single value is rejected with
  // HTTP 400 bad_argument on every one of them - verified 2026-10-01.
  for (const value of opts.experience ?? []) params.append("experience", value)
  for (const value of opts.employment ?? []) params.append("employment_form", value)
  for (const value of opts.workFormat ?? []) params.append("work_format", value)
  for (const value of opts.scheduleByDays ?? []) params.append("work_schedule_by_days", value)
  if (opts.orderBy) params.set("order_by", opts.orderBy)
  params.set("page", String(apiPage))
  params.set("per_page", String(opts.perPage))
  // Deterministic results: never let hh.ru's "magic" query rewriting inject
  // filters the caller did not ask for (the CLI contract is that flags are
  // never silently transformed).
  params.set("no_magic", "true")
  return params
}

function renderTable(rows: SearchResult[]): string {
  if (rows.length === 0) return "No results."
  const header =
    "ID".padEnd(10) + " " + "TITLE".padEnd(40) + " " + "COMPANY".padEnd(26) + " " + "LOCATION".padEnd(22) + " DATE"
  const lines = rows.map((r) =>
    [
      r.id.padEnd(10),
      (r.title || "—").slice(0, 40).padEnd(40),
      (r.company || "—").slice(0, 26).padEnd(26),
      (r.location || "—").slice(0, 22).padEnd(22),
      r.date || "—",
    ].join(" "),
  )
  return [header, "-".repeat(header.length), ...lines].join("\n")
}

function renderPlain(rows: SearchResult[]): string {
  return (
    rows
      .map(
        (r) =>
          `${r.title}\n  ${r.company || "—"} · ${r.location || "—"} · ${r.date || "—"}\n  id: ${r.id}\n  ${r.url}`,
      )
      .join("\n\n") + "\n"
  )
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    let areaId: string | null = null
    if (opts.location) {
      areaId = await resolveAreaId(opts.location)
    } else if (opts.area) {
      areaId = opts.area
    }

    const target = opts.limit ?? opts.perPage
    const results: SearchResult[] = []
    let found = 0
    let pages = 0
    let apiPage = opts.page - 1

    for (;;) {
      if ((apiPage + 1) * opts.perPage > MAX_DEPTH) {
        throw new CliError(
          `page ${apiPage + 1} with per_page ${opts.perPage} exceeds hh.ru's ${MAX_DEPTH}-result pagination depth`,
          "BAD_ARG",
        )
      }
      const data = await apiFetchJson<HhSearchResponse>("/vacancies", buildSearchParams(opts, areaId, apiPage))
      if (!data) break
      found = data.found ?? 0
      pages = data.pages ?? 0
      const items = (data.items ?? []).map(mapSearchItem)
      results.push(...items)
      if (results.length >= target || apiPage + 1 >= pages || items.length === 0) break
      apiPage++
    }

    const limited = opts.limit !== undefined ? results.slice(0, opts.limit) : results

    if (opts.format === "table") {
      process.stdout.write(renderTable(limited) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(renderPlain(limited))
    } else {
      process.stdout.write(
        JSON.stringify(
          {
            meta: { count: limited.length, found, page: opts.page, pages, per_page: opts.perPage },
            results: limited,
          },
          null,
          2,
        ) + "\n",
      )
    }
    return 0
  } catch (e) {
    if (e instanceof CliError) {
      writeError(e.message, e.code)
      return 1
    }
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
