#!/usr/bin/env bun
// Self-contained CLI for searching jobs on hh.ru (HeadHunter) via the official
// public API (https://api.hh.ru), zero runtime dependencies beyond bun.
//
// Vacancy search/detail require an access token (anonymous requests are
// rejected with HTTP 403 captcha) plus an HH-User-Agent header naming the app
// and a contact email. The token is read only from HH_API_TOKEN — never from a
// CLI flag (flags leak into shell history and process listings).

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { writeError } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit", a: "area" }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith("--") || a.startsWith("-")) {
      const key = alias[a.replace(/^-+/, "")] ?? a.replace(/^-+/, "")
      const next = argv[i + 1]
      if (next === undefined || next.startsWith("-")) {
        flags[key] = true
      } else {
        flags[key] = next
        i++
      }
    } else {
      ;(flags._ as string[]).push(a)
    }
  }
  return flags
}

const HELP = `hhru-cli — search jobs on hh.ru (Russia) via the official HeadHunter API

SETUP (required)
  Vacancy search/detail need an access token; anonymous requests get HTTP 403.
  Put in .env.docker (repo root, gitignored):
    HH_API_TOKEN=<your token>
    HH_USER_AGENT=hhru-search-cli/1.0 (your@email)
  then recreate the container so the variables reach the process.

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>        Keywords (job title, skill, role). Optional.
  --location, -l <place>    City/region: "Москва", "Moscow", "Санкт-Петербург", or a
                            numeric hh.ru area id. Optional.
  --area, -a <id>           Numeric hh.ru area id (alternative to --location). Optional.
  --jobage <days>           Posted within N days (1-30). Maps to hh.ru period.
  --experience <ids>        Comma-separated: noExperience, between1And3,
                            between3And6, moreThan6.
  --employment <ids>        Comma-separated: full, part, project, fly-in-fly-out.
  --work-format <ids>       Comma-separated: remote, hybrid, onsite, field-work.
  --schedule-by-days <ids>  Comma-separated: five-on-two-off, seven-on-zero-off.
  --order-by <mode>         relevance (default) | publication_time | salary_desc | salary_asc.
  --page <n>                1-indexed page. Default 1.
  --per-page <n>            Results per request, 1-100. Default 100.
  --limit, -n <n>           Cap results emitted (client-side; may fetch extra pages).
  --format <fmt>            json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "ML-инженер" -l Москва --jobage 14 --limit 20 --format table
  bun run src/cli.ts search -q "NLP" -l "Санкт-Петербург" --work-format remote --format json
  bun run src/cli.ts detail 12345678 --format plain
`

// Long-form flag names each command accepts (parseFlags resolves the short
// aliases q/l/a/n before validation). Unknown flags are rejected, never
// silently ignored: a discarded filter changes what the search returns.
const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "location", "area", "query", "jobage", "experience", "employment", "work-format",
    "schedule-by-days", "order-by", "page", "per-page", "limit", "format", "help", "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

const EXPERIENCE_IDS = new Map([
  ["noexperience", "noExperience"],
  ["between1and3", "between1And3"],
  ["between3and6", "between3And6"],
  ["morethan6", "moreThan6"],
])
const EMPLOYMENT_IDS = new Map([
  ["full", "FULL"],
  ["part", "PART"],
  ["project", "PROJECT"],
  ["fly-in-fly-out", "FLY_IN_FLY_OUT"],
  ["flyinflyout", "FLY_IN_FLY_OUT"],
])
const WORK_FORMAT_IDS = new Map([
  ["remote", "REMOTE"],
  ["hybrid", "HYBRID"],
  ["onsite", "ON_SITE"],
  ["on-site", "ON_SITE"],
  ["field-work", "FIELD_WORK"],
  ["fieldwork", "FIELD_WORK"],
])
const SCHEDULE_DAYS_IDS = new Map([
  ["five-on-two-off", "FIVE_ON_TWO_OFF"],
  ["5/2", "FIVE_ON_TWO_OFF"],
  ["seven-on-zero-off", "SEVEN_ON_ZERO_OFF"],
  ["7/0", "SEVEN_ON_ZERO_OFF"],
])
const ORDER_BY_IDS = new Set(["relevance", "publication_time", "salary_desc", "salary_asc"])

function parseEnumList(
  flag: string,
  raw: string | boolean | string[],
  map: Map<string, string>,
): string[] | null {
  const items = typeof raw === "string" ? raw.split(",").map((s) => s.trim()).filter(Boolean) : []
  const allowed = [...new Set(map.values())].join(", ")
  if (items.length === 0) {
    writeError(`--${flag} requires at least one value (allowed: ${allowed})`, "BAD_ARG")
    return null
  }
  const out: string[] = []
  for (const item of items) {
    const mapped = map.get(item.toLowerCase())
    if (!mapped) {
      writeError(`--${flag} got unknown value "${item}" (allowed: ${allowed})`, "BAD_ARG")
      return null
    }
    out.push(mapped)
  }
  return out
}

function parseIntFlag(name: string, raw: string | boolean | string[], min: number, max: number): number | null {
  const value = typeof raw === "string" ? Number(raw.trim()) : NaN
  if (!Number.isInteger(value) || value < min || value > max) {
    writeError(`--${name} must be a whole number between ${min} and ${max}, got "${raw}"`, "BAD_ARG")
    return null
  }
  return value
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      writeError(
        `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
        "UNKNOWN_FLAG",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const location = typeof flags.location === "string" ? flags.location.trim() : undefined
    const area = typeof flags.area === "string" ? flags.area.trim() : undefined
    if (location && area) {
      writeError("pass only one of --location/-l (name) and --area/-a (numeric id)", "CONFLICTING_AREA_FLAGS")
      return 1
    }
    if (area && !/^\d+$/.test(area)) {
      writeError(`--area/-a must be a numeric hh.ru area id, got "${area}"; use --location/-l for names`, "BAD_ARG")
      return 1
    }

    const fmt = (flags.format as string) || "json"
    if (!["json", "table", "plain"].includes(fmt)) {
      writeError(`--format must be json, table, or plain, got "${fmt}"`, "BAD_ARG")
      return 1
    }

    const experience = flags.experience !== undefined ? parseEnumList("experience", flags.experience, EXPERIENCE_IDS) : undefined
    if (experience === null) return 1
    const employment = flags.employment !== undefined ? parseEnumList("employment", flags.employment, EMPLOYMENT_IDS) : undefined
    if (employment === null) return 1
    const workFormat = flags["work-format"] !== undefined ? parseEnumList("work-format", flags["work-format"], WORK_FORMAT_IDS) : undefined
    if (workFormat === null) return 1
    const scheduleByDays = flags["schedule-by-days"] !== undefined ? parseEnumList("schedule-by-days", flags["schedule-by-days"], SCHEDULE_DAYS_IDS) : undefined
    if (scheduleByDays === null) return 1

    let orderBy: string | undefined
    if (flags["order-by"] !== undefined) {
      const rawOrder = typeof flags["order-by"] === "string" ? flags["order-by"].toLowerCase() : ""
      if (rawOrder === "distance") {
        writeError("--order-by distance needs coordinates and is not supported by this CLI; use relevance, publication_time, salary_desc, or salary_asc", "BAD_ARG")
        return 1
      }
      if (!ORDER_BY_IDS.has(rawOrder)) {
        writeError(`--order-by got unknown value "${rawOrder}" (allowed: relevance, publication_time, salary_desc, salary_asc)`, "BAD_ARG")
        return 1
      }
      orderBy = rawOrder
    }

    let jobage: number | undefined
    if (flags.jobage !== undefined) {
      const v = parseIntFlag("jobage", flags.jobage, 1, 30)
      if (v === null) return 1
      jobage = v
    }
    let page = 1
    if (flags.page !== undefined) {
      const v = parseIntFlag("page", flags.page, 1, 1_000_000)
      if (v === null) return 1
      page = v
    }
    let perPage = 100
    if (flags["per-page"] !== undefined) {
      const v = parseIntFlag("per-page", flags["per-page"], 1, 100)
      if (v === null) return 1
      perPage = v
    }
    let limit: number | undefined
    if (flags.limit !== undefined) {
      const v = parseIntFlag("limit", flags.limit, 1, 2000)
      if (v === null) return 1
      limit = v
    }

    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      location,
      area,
      jobage,
      experience: experience ?? undefined,
      employment: employment ?? undefined,
      workFormat: workFormat ?? undefined,
      scheduleByDays: scheduleByDays ?? undefined,
      page,
      perPage,
      limit,
      orderBy,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      writeError("detail requires an <id|url>", "NO_ID")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    if (!["json", "plain"].includes(fmt)) {
      writeError(`--format must be json or plain, got "${fmt}"`, "BAD_ARG")
      return 1
    }
    const opts: DetailOpts = { id, format: fmt as DetailOpts["format"] }
    return runDetail(opts)
  }

  writeError(`Unknown command "${cmd}"`, "BAD_CMD")
  return 1
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    writeError(e instanceof Error ? e.message : String(e), "INTERNAL_ERROR")
    process.exit(1)
  })
