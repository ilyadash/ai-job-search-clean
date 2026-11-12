#!/usr/bin/env bun
// Self-contained CLI for searching jobs on Career.Habr (career.habr.com).
// No external CLI framework and zero runtime dependencies, so it runs anywhere
// `bun` is available with nothing beyond the repo clone.
//
// Search and detail only. Responding to a vacancy ("Откликнуться") happens on
// the site behind a login and is deliberately not automated: this CLI never
// authenticates, never touches the site's response endpoints, and the workflow
// hands the user the vacancy URL to submit manually.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { LEVEL_QID } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  const alias: Record<string, string> = { q: "query", l: "location", n: "limit" }
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

const HELP = `habr-career-search-cli — search jobs on Career.Habr (career.habr.com)

USAGE
  bun run src/cli.ts search [flags]
  bun run src/cli.ts detail <id|url> [--format json|plain]

SEARCH FLAGS
  --query, -q <text>      Keywords (job title, skill, role). Optional.
  --location, -l <place>  City name ("Москва", "Moscow", "СПб") or numeric
                          city_id. Omit to search all of Russia.
  --level <names>         Comma-separated: intern, junior, middle, senior, lead.
  --remote                Remote-only vacancies.
  --jobage <days>         Posted within N days (client-side; Habr has no
                          recency filter). Implies --sort date.
  --sort <mode>           relevance (default) | date.
  --page <n>              1-indexed page (25 results/page). Default 1.
  --limit, -n <n>         Cap results emitted (client-side).
  --format <fmt>          json (default) | table | plain.

EXAMPLES
  bun run src/cli.ts search -q "python" -l Москва --level junior,middle --jobage 14 --limit 20
  bun run src/cli.ts search -q "NLP" --level junior,middle --remote --format table
  bun run src/cli.ts detail 1000168741 --format plain

Personal use only — reads public pages; keep volume low, no bulk collection.
Responses ("Откликнуться") are submitted manually on career.habr.com.
`

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set([
    "query", "location", "level", "remote", "jobage", "sort", "page", "limit", "format", "help", "h",
  ]),
  detail: new Set(["format", "help", "h"]),
}

function badArg(message: string): number {
  process.stderr.write(JSON.stringify({ error: message, code: "BAD_ARG" }) + "\n")
  return 1
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (flags.help || flags.h) {
    process.stdout.write(HELP)
    return 0
  }
  if (!cmd) {
    process.stdout.write(HELP)
    return 1
  }

  // Reject unknown flags instead of silently discarding them: a discarded
  // filter changes what the search returns with no error. The portal-skill
  // contract requires a bogus flag to exit 1 with a JSON error on stderr.
  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({
          error: `unknown flag --${key} for '${cmd}' - flags are never silently ignored, because a discarded filter changes what the search returns; see --help for the supported flags`,
          code: "UNKNOWN_FLAG",
        }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const parseIntFlag = (name: string, raw: string | boolean | string[]): number | null => {
      const val = typeof raw === "string" ? Number(raw.trim()) : NaN
      if (!Number.isInteger(val) || val < 1) return null
      return val
    }

    for (const name of ["query", "location", "level", "sort", "format"]) {
      if (flags[name] === true) return badArg(`--${name} requires a value`)
    }
    for (const name of ["jobage", "page", "limit"]) {
      if (flags[name] !== undefined) {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return badArg(`--${name} must be a whole number of at least 1, got "${flags[name]}"`)
        flags[name] = String(v)
      }
    }

    const levels =
      typeof flags.level === "string"
        ? flags.level.split(",").map((s) => s.trim().toLowerCase()).filter((s) => s !== "")
        : []
    for (const level of levels) {
      if (LEVEL_QID[level] === undefined) {
        process.stderr.write(
          JSON.stringify({
            error: `unknown --level value "${level}" - use intern, junior, middle, senior, lead`,
            code: "BAD_LEVEL",
          }) + "\n",
        )
        return 1
      }
    }

    if (flags.sort !== undefined && flags.sort !== "relevance" && flags.sort !== "date") {
      return badArg(`--sort must be "relevance" or "date", got "${flags.sort}"`)
    }

    const fmt = (flags.format as string) || "json"
    const opts: SearchOpts = {
      query: typeof flags.query === "string" ? flags.query : undefined,
      location: typeof flags.location === "string" ? flags.location : undefined,
      jobage: flags.jobage ? parseInt(flags.jobage as string, 10) : undefined,
      levels,
      remote: flags.remote === true,
      sort: flags.sort === "date" ? "date" : flags.sort === "relevance" ? "relevance" : undefined,
      page: flags.page ? parseInt(flags.page as string, 10) : 1,
      limit: flags.limit ? parseInt(flags.limit as string, 10) : undefined,
      format: (["json", "table", "plain"].includes(fmt) ? fmt : "json") as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires an <id|url>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = (flags.format as string) || "json"
    const opts: DetailOpts = {
      id,
      format: (fmt === "plain" ? "plain" : "json") as DetailOpts["format"],
    }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: "INTERNAL_ERROR",
      }) + "\n",
    )
    process.exit(1)
  })
