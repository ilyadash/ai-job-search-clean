import { apiFetchJson, mapVacancy, writeError, CliError, type HhVacancyDetail } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

/** Accept a raw vacancy id, an hh.ru vacancy URL, or an api.hh.ru URL. */
export function normalizeId(input: string): string | null {
  const match =
    input.match(/vacanc(?:y|ies)\/(\d+)/) ||
    input.match(/[?&]vacancyId=(\d+)/) ||
    input.match(/^\s*(\d+)\s*$/)
  return match ? match[1] : null
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(`Could not parse a vacancy ID from "${opts.id}"`, "BAD_ID")
    return 1
  }
  try {
    const vacancy = await apiFetchJson<HhVacancyDetail>(`/vacancies/${id}`, undefined, { allow404: true })
    if (!vacancy) {
      writeError("Job not found", "NOT_FOUND")
      return 1
    }
    const job = mapVacancy(vacancy)

    if (opts.format === "plain") {
      const lines = [
        job.title,
        `${job.company || "—"} · ${job.location || "—"} · ${job.date || "—"}`,
        "",
        job.experience ? `Experience: ${job.experience}` : "",
        job.employment ? `Employment: ${job.employment}` : "",
        job.workFormat?.length ? `Work format: ${job.workFormat.join(", ")}` : "",
        job.salary ? `Salary: ${formatSalary(job.salary)}` : "",
        job.keySkills?.length ? `Key skills: ${job.keySkills.join(", ")}` : "",
        `Status: ${job.isActive ? "ACTIVE" : "ARCHIVED / CLOSED"}`,
        `Apply: ${job.applyUrl || job.url || "—"}`,
        "",
        job.description || "(no description)",
        "",
        `URL: ${job.url || "—"}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(job, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    if (e instanceof CliError) {
      writeError(e.message, e.code)
      return 1
    }
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}

function formatSalary(salary: { from?: number | null; to?: number | null; currency?: string | null; gross?: boolean | null }): string {
  const range = [salary.from, salary.to].filter((v): v is number => typeof v === "number")
  const amount = range.length === 2 ? `${range[0]}–${range[1]}` : range.length === 1 ? `${range[0]}` : "?"
  return `${amount} ${salary.currency ?? ""}${salary.gross === false ? " net" : ""}`.trim()
}
