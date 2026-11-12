import { Plugin } from "@opencode/plugin"

const DESCRIPTION = [
  "Read or update the SQLite job-search state. Use action=show or update with a",
  "vacancy URL; updates touch only the application, its stages, and its events.",
  "Use action=query for read-only SELECT/WITH SQL, action=stats for weekly metrics.",
  "Never use update for job lifecycle changes; use /scrape or /rank for jobs.",
].join(" ")

const COVER_LETTER = ["used", "not_used", "not_required", "unknown"] as const
const FORMATS = ["markdown", "json"] as const

type StateDbInput = {
  action: "show" | "update" | "query" | "stats"
  url?: string
  application_id?: number
  status?: string
  cover_letter_used?: (typeof COVER_LETTER)[number]
  applied_on?: string
  first_response_date?: string
  date_resolved?: string
  stages?: string[]
  note?: string
  cv_version_id?: number
  cv_path?: string
  archive_path?: string
  outcome_note_path?: string
  sql?: string
  limit?: number
  format?: (typeof FORMATS)[number]
}

export default Plugin.define({
  id: "state-db",
  async setup(ctx) {
    const directory = ctx.location.directory
    const python = Bun.which("python3") ?? Bun.which("python") ?? "python3"

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "state_db",
        description: DESCRIPTION,
        input: {
          type: "object",
          properties: {
            action: {
              type: "string",
              enum: ["show", "update", "query", "stats"],
            },
            url: { type: "string", description: "Vacancy or posting URL" },
            application_id: {
              type: "integer",
              description: "Application id for an ambiguous URL",
            },
            status: { type: "string", description: "Canonical application status" },
            cover_letter_used: { type: "string", enum: [...COVER_LETTER] },
            applied_on: {
              type: "string",
              description: "YYYY-MM-DD, or 'unknown' to clear",
            },
            first_response_date: { type: "string", description: "YYYY-MM-DD" },
            date_resolved: { type: "string", description: "YYYY-MM-DD" },
            stages: {
              type: "array",
              items: { type: "string" },
              description: "Stage labels, optionally with (YYYY-MM-DD)",
            },
            note: { type: "string" },
            cv_version_id: { type: "integer" },
            cv_path: { type: "string" },
            archive_path: { type: "string" },
            outcome_note_path: { type: "string" },
            sql: {
              type: "string",
              description: "Read-only SELECT/WITH/EXPLAIN",
            },
            limit: { type: "integer" },
            format: { type: "string", enum: [...FORMATS] },
          },
          required: ["action"],
          additionalProperties: false,
        },
        async execute(raw) {
          const input = raw as StateDbInput
          const args: string[] = []
          if (input.action === "show") {
            if (!input.url && input.application_id === undefined) {
              return { content: '{"status":"error","message":"show needs url or application_id"}' }
            }
            args.push("application-show")
            if (input.url) args.push("--url", input.url)
            if (input.application_id !== undefined) args.push("--application-id", String(input.application_id))
          } else if (input.action === "update") {
            if (!input.url && input.application_id === undefined) {
              return { content: '{"status":"error","message":"update needs url or application_id"}' }
            }
            args.push("application-update")
            if (input.url) args.push("--url", input.url)
            if (input.application_id !== undefined) args.push("--application-id", String(input.application_id))
            if (input.status) args.push("--status", input.status)
            if (input.cover_letter_used) args.push("--cover-letter-used", input.cover_letter_used)
            if (input.applied_on) args.push("--applied-on", input.applied_on)
            if (input.first_response_date) args.push("--first-response-date", input.first_response_date)
            if (input.date_resolved) args.push("--date-resolved", input.date_resolved)
            for (const stage of input.stages ?? []) args.push("--stage", stage)
            if (input.note) args.push("--note", input.note)
            if (input.cv_version_id !== undefined) args.push("--cv-version", String(input.cv_version_id))
            if (input.cv_path) args.push("--cv-path", input.cv_path)
            if (input.archive_path) args.push("--archive-path", input.archive_path)
            if (input.outcome_note_path) args.push("--outcome-note-path", input.outcome_note_path)
          } else if (input.action === "query") {
            if (!input.sql) return { content: '{"status":"error","message":"query needs sql"}' }
            args.push("query", "--sql", input.sql)
            if (input.limit !== undefined) args.push("--limit", String(input.limit))
          } else {
            args.push("stats", "--format", input.format ?? "markdown")
          }

          const proc = Bun.spawn({
            cmd: [python, `${directory}/tools/state_db.py`, ...args],
            cwd: directory,
            stdout: "pipe",
            stderr: "pipe",
          })
          const [stdout, stderr, exitCode] = await Promise.all([
            new Response(proc.stdout).text(),
            new Response(proc.stderr).text(),
            proc.exited,
          ])
          if (exitCode === 0) return { content: stdout.trim() }
          const message = (stderr || stdout).trim()
          return {
            content: JSON.stringify({ status: "error", exit_code: exitCode, message }),
          }
        },
      })
    })
  },
})
