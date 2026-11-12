import { describe, expect, test } from "bun:test"
import { parseJSON, runCLI } from "./helpers.js"

// Live smoke test: skipped automatically when HH_API_TOKEN is not set (CI),
// runs in the local container once .env.docker provides a token and the
// container has been recreated.
const liveTest = process.env.HH_API_TOKEN ? test : test.skip

interface SearchPayload {
  meta: { count: number; found: number }
  results: Array<{ id: string; title: string; url: string | null }>
}

describe("live hh.ru API", () => {
  liveTest("search returns real results for a profile query", async () => {
    const result = await runCLI([
      "search", "-q", "ML-инженер", "-l", "Москва", "--jobage", "30", "--limit", "5", "--format", "json",
    ])
    expect(result.exitCode).toBe(0)
    const data = parseJSON<SearchPayload>(result)
    expect(data.results.length).toBeGreaterThan(0)
    for (const item of data.results) {
      expect(item.id).toBeTruthy()
      expect(item.title).toBeTruthy()
    }
  })

  liveTest("detail returns a readable description for the first search hit", async () => {
    const search = await runCLI(["search", "-q", "ML-инженер", "-l", "Москва", "--limit", "1", "--format", "json"])
    const first = parseJSON<SearchPayload>(search).results[0]
    const detail = await runCLI(["detail", first.id, "--format", "json"])
    expect(detail.exitCode).toBe(0)
    const job = JSON.parse(detail.stdout) as { id: string; description: string | null; deadline: null }
    expect(job.id).toBe(first.id)
    expect(job.description).toBeTruthy()
    expect(job.deadline).toBeNull()
  })
})
