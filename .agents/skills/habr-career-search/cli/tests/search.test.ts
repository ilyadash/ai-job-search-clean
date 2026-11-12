import { afterEach, describe, expect, test } from "bun:test";
import { runSearch } from "../src/commands/search";

const originalFetch = globalThis.fetch;
const originalStdoutWrite = process.stdout.write;

function card(id: number, iso: string, qualification: string) {
  return {
    id,
    href: `/vacancies/${id}`,
    title: `Vacancy ${id}`,
    publishedDate: { date: iso },
    company: { title: "Acme", href: "/companies/acme" },
    salary: { formatted: "" },
    locations: [{ title: "Москва", href: "/vacancies?city_id=678" }],
    skills: [],
    qualification,
    archived: false,
  };
}

function ssrPage(state: unknown): string {
  return `<script type="application/json" data-ssr-state="true">${JSON.stringify(state)}</script>`;
}

function captureStdout(): () => string {
  let out = "";
  process.stdout.write = ((chunk: string | Uint8Array) => {
    out += chunk.toString();
    return true;
  }) as typeof process.stdout.write;
  return () => out;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  process.stdout.write = originalStdoutWrite;
});

describe("runSearch", () => {
  test("--jobage filters client-side, sorts by date and sends qid + sort", async () => {
    const fresh = new Date(Date.now() - 2 * 86400_000).toISOString();
    const old = new Date(Date.now() - 40 * 86400_000).toISOString();
    const html = ssrPage({
      vacancies: {
        list: [card(1, fresh, "Middle"), card(2, old, "Middle")],
        meta: { totalResults: 2, perPage: 25, currentPage: 1, totalPages: 1 },
      },
    });
    let capturedUrl = "";
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      capturedUrl = typeof input === "string" ? input : input.toString();
      return new Response(html, { status: 200 });
    }) as typeof fetch;

    const stdout = captureStdout();
    const code = await runSearch({
      query: "python",
      location: "Москва",
      jobage: 14,
      levels: ["middle"],
      remote: false,
      page: 1,
      format: "json",
    });

    expect(code).toBe(0);
    const parsed = JSON.parse(stdout());
    expect(parsed.results).toHaveLength(1);
    expect(parsed.results[0].id).toBe("1");
    expect(capturedUrl).toContain("city_id=678");
    expect(capturedUrl).toContain("qid=4");
    expect(capturedUrl).toContain("sort=date");
    expect(capturedUrl).toContain("type=all");
  });

  test("multiple levels merge and dedupe by id", async () => {
    const iso = new Date(Date.now() - 1 * 86400_000).toISOString();
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      const qid = new URL(url).searchParams.get("qid");
      const list = qid === "3" ? [card(10, iso, "Junior")] : [card(10, iso, "Middle"), card(11, iso, "Middle")];
      return new Response(
        ssrPage({ vacancies: { list, meta: { totalResults: list.length, perPage: 25, currentPage: 1, totalPages: 1 } } }),
        { status: 200 },
      );
    }) as typeof fetch;

    const stdout = captureStdout();
    const code = await runSearch({
      query: "python",
      levels: ["junior", "middle"],
      remote: false,
      page: 1,
      format: "json",
    });

    expect(code).toBe(0);
    const ids = JSON.parse(stdout()).results.map((r: { id: string }) => r.id).sort();
    expect(ids).toEqual(["10", "11"]);
  });

  test("a page without parseable SSR data fails loudly, not empty", async () => {
    globalThis.fetch = (async () => new Response("<html>blocked</html>", { status: 200 })) as unknown as typeof fetch;

    captureStdout();
    const code = await runSearch({
      query: "python",
      levels: [],
      remote: false,
      page: 1,
      format: "json",
    });

    expect(code).toBe(1);
  });

  test("unknown level fails before any request", async () => {
    let called = false;
    globalThis.fetch = (async () => {
      called = true;
      return new Response("", { status: 200 });
    }) as unknown as typeof fetch;

    captureStdout();
    const code = await runSearch({
      query: "python",
      levels: ["principal"],
      remote: false,
      page: 1,
      format: "json",
    });

    expect(code).toBe(1);
    expect(called).toBe(false);
  });
});
