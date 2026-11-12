import {
  BASE_URL,
  htmlFetch,
  isWithinWindow,
  parseSearchPage,
  resolveCityId,
  resolveLevels,
  writeError,
  type HabrCard,
} from "../helpers.js"

export interface SearchOpts {
  query?: string
  /** City name (alias table) or numeric hh city_id. Omit for all of Russia. */
  location?: string
  /** Client-side freshness window in days (the site has no recency filter). */
  jobage?: number
  /** Qualification names: intern | junior | middle | senior | lead. */
  levels: string[]
  /** Remote-only filter (site's remote=true). */
  remote: boolean
  sort?: "relevance" | "date"
  page: number
  limit?: number
  format: "json" | "table" | "plain"
}

// The listing is paginated 25/page; cap how many pages one command may fetch
// so a broad query with --jobage can never turn into an unbounded crawl.
const MAX_PAGES = 10

function effectiveSort(opts: SearchOpts): "relevance" | "date" {
  return opts.sort ?? (opts.jobage !== undefined ? "date" : "relevance")
}

function buildUrl(opts: SearchOpts, qid: number | undefined, page: number): string {
  const params = new URLSearchParams()
  if (opts.query) params.set("q", opts.query)
  params.set("type", "all")
  if (opts.location) {
    const cityId = resolveCityId(opts.location)
    if (cityId) params.set("city_id", cityId)
  }
  if (qid !== undefined) params.set("qid", String(qid))
  if (opts.remote) params.set("remote", "true")
  if (effectiveSort(opts) === "date") params.set("sort", "date")
  if (page > 1) params.set("page", String(page))
  return `${BASE_URL}/vacancies?${params.toString()}`
}

function renderTable(cards: HabrCard[]): string {
  if (cards.length === 0) return "No results."
  const rows = cards.map((c) => {
    const title = (c.title || "").slice(0, 40).padEnd(40)
    const company = (c.company || "—").slice(0, 24).padEnd(24)
    const loc = (c.location || "—").slice(0, 22).padEnd(22)
    const qual = (c.qualification || "—").padEnd(8)
    const date = c.date || "—"
    return `${c.id.padEnd(11)} ${title} ${company} ${loc} ${qual} ${date}`
  })
  const header =
    "ID".padEnd(11) +
    " " +
    "TITLE".padEnd(40) +
    " " +
    "COMPANY".padEnd(24) +
    " " +
    "LOCATION".padEnd(22) +
    " " +
    "LEVEL".padEnd(8) +
    " DATE"
  return [header, "-".repeat(header.length), ...rows].join("\n")
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  try {
    const qids: (number | undefined)[] =
      opts.levels.length > 0 ? (resolveLevels(opts.levels) ?? []) : [undefined]
    if (qids.length === 0) {
      writeError(
        `unknown --level value(s) "${opts.levels.join(",")}" - use intern, junior, middle, senior, lead`,
        "BAD_LEVEL",
      )
      return 1
    }
    if (opts.location && !resolveCityId(opts.location)) {
      writeError(
        `could not resolve --location "${opts.location}" to a known city - use a known city name or its numeric city id`,
        "BAD_LOCATION",
      )
      return 1
    }

    const sort = effectiveSort(opts)
    const want = opts.limit ?? Number.POSITIVE_INFINITY
    const collected = new Map<string, HabrCard>()
    let total: number | null = null

    for (const qid of qids) {
      let page = opts.page
      for (let fetched = 0; fetched < MAX_PAGES && collected.size < want; fetched++) {
        const html = await htmlFetch(buildUrl(opts, qid, page))
        const parsed = html ? parseSearchPage(html) : null
        if (!parsed) {
          if (fetched === 0) {
            throw new Error(
              "career.habr.com returned a page with no parseable vacancy data - the SSR state contract may have changed (see url-reference.md)",
            )
          }
          break
        }
        if (total === null && parsed.meta.totalResults !== null) total = parsed.meta.totalResults

        const windowed =
          opts.jobage !== undefined
            ? parsed.results.filter((c) => isWithinWindow(c.publishedAt, c.date, opts.jobage as number))
            : parsed.results
        for (const card of windowed) {
          if (!collected.has(card.id)) collected.set(card.id, card)
        }

        const pageAllOlder =
          opts.jobage !== undefined &&
          parsed.results.length > 0 &&
          parsed.results.every((c) => !isWithinWindow(c.publishedAt, c.date, opts.jobage as number))
        if (pageAllOlder) break
        if (parsed.meta.totalPages !== null && page >= parsed.meta.totalPages) break
        page++
      }
    }

    let results = [...collected.values()]
    if (sort === "date") {
      results.sort(
        (a, b) =>
          (Date.parse(b.publishedAt ?? b.date ?? "") || 0) -
          (Date.parse(a.publishedAt ?? a.date ?? "") || 0),
      )
    }
    if (opts.limit !== undefined) results = results.slice(0, opts.limit)

    if (opts.format === "table") {
      process.stdout.write(renderTable(results) + "\n")
    } else if (opts.format === "plain") {
      process.stdout.write(
        results
          .map(
            (c) =>
              `${c.title}\n  ${c.company || "—"} · ${c.location || "—"} · ${c.qualification || "—"} · ${c.date || "—"}${c.remoteWork ? " · remote" : ""}\n  id: ${c.id}\n  ${c.url}`,
          )
          .join("\n\n") + "\n",
      )
    } else {
      process.stdout.write(
        JSON.stringify({ meta: { count: results.length, page: opts.page, total }, results }, null, 2) + "\n",
      )
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "SEARCH_FAILED")
    return 1
  }
}
