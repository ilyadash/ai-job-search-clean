import { BASE_URL, htmlFetch, normalizeId, parseDetailPage, writeError } from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const id = normalizeId(opts.id)
  if (!id) {
    writeError(
      `could not parse a vacancy id from "${opts.id}" - pass a bare id or a ${BASE_URL}/vacancies/<id> URL`,
      "BAD_ID",
    )
    return 1
  }
  try {
    const html = await htmlFetch(`${BASE_URL}/vacancies/${id}`)
    if (!html) {
      writeError("Vacancy not found", "NOT_FOUND")
      return 1
    }
    const vacancy = parseDetailPage(html, id)
    if (!vacancy) {
      writeError(
        "career.habr.com returned a vacancy page with no parseable data - the SSR state contract may have changed (see url-reference.md)",
        "PARSE_FAILED",
      )
      return 1
    }

    if (opts.format === "plain") {
      const lines = [
        vacancy.title,
        `${vacancy.company || "—"} · ${vacancy.location || "—"}`,
        "",
        vacancy.qualification ? `Level: ${vacancy.qualification}` : "",
        vacancy.employment ? `Employment: ${vacancy.employment}` : "",
        vacancy.salary ? `Salary: ${vacancy.salary}` : "",
        vacancy.remoteWork ? "Remote: yes" : "",
        `Status: ${vacancy.isActive ? "ACTIVE" : "ARCHIVED / CLOSED"}`,
        "",
        vacancy.description || "(no description)",
        "",
        `URL: ${vacancy.url}`,
      ].filter((l) => l !== "")
      process.stdout.write(lines.join("\n") + "\n")
    } else {
      process.stdout.write(JSON.stringify(vacancy, null, 2) + "\n")
    }
    return 0
  } catch (e) {
    writeError(e instanceof Error ? e.message : String(e), "DETAIL_FAILED")
    return 1
  }
}
