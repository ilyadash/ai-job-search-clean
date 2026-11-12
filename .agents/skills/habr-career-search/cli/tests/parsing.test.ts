import { describe, expect, test } from "bun:test";
import {
  LEVEL_QID,
  extractSsrState,
  htmlToText,
  isWithinWindow,
  isoDay,
  normalizeId,
  parseDetailPage,
  parseSearchPage,
  resolveCityId,
  resolveLevels,
} from "../src/helpers";

function ssrPage(state: unknown): string {
  return `<!doctype html><html><body><script type="application/json" data-ssr-state="true">${JSON.stringify(state)}</script></body></html>`;
}

const SEARCH_STATE = {
  vacancies: {
    list: [
      {
        id: 1000168684,
        href: "/vacancies/1000168684",
        title: "ML-инженер (Python)",
        remoteWork: true,
        publishedDate: { date: "2026-09-29T10:23:58+03:00", title: "29 сентября" },
        company: { title: "Урал Логистика", href: "/companies/ulgroup" },
        salary: { from: null, to: null, currency: null, formatted: "" },
        locations: [
          { title: "Москва", href: "/vacancies?city_id=678" },
          { title: "Томск", href: "/vacancies?city_id=736" },
        ],
        skills: [{ title: "Python" }, { title: "PyTorch" }],
        qualification: "Middle",
        archived: false,
      },
      {
        id: 1000168741,
        href: "/vacancies/1000168741",
        title: "Python Developer / AI Engineer",
        publishedDate: { date: "2026-09-24T14:47:11+03:00" },
        company: { title: "AYROSA", href: "/companies/ayrosa-agency" },
        salary: { formatted: "от 200 000 ₽" },
        locations: [],
        skills: [],
        qualification: "Senior",
        archived: true,
      },
    ],
    meta: { totalResults: 2, perPage: 25, currentPage: 1, totalPages: 1 },
  },
};

const DETAIL_STATE = {
  vacancy: {
    id: 1000168741,
    href: "/vacancies/1000168741",
    title: "Python Developer / AI Engineer (Document Processing)",
    remoteWork: true,
    publishedDate: { date: "2026-09-24T14:47:11+03:00" },
    company: { title: "AYROSA", href: "/companies/ayrosa-agency" },
    salary: { formatted: "" },
    locations: [],
    humanCityNames: "Москва, Санкт-Петербург, Самара",
    skills: [{ title: "Python" }, { title: "FastAPI" }],
    qualification: "Middle",
    employment: "full_time",
    archived: false,
    description: "<p>Ищем <strong>Python</strong>-разработчика.</p><ul><li>FastAPI</li><li>PostgreSQL</li></ul>",
  },
};

describe("extractSsrState", () => {
  test("returns the parsed state object", () => {
    const state = extractSsrState(ssrPage({ hello: "world" }));
    expect(state).toEqual({ hello: "world" });
  });

  test("returns null for a page without a state blob", () => {
    expect(extractSsrState("<html><body>nope</body></html>")).toBeNull();
  });

  test("returns null for invalid JSON in the blob", () => {
    const html =
      '<script type="application/json" data-ssr-state="true">{oops</script>';
    expect(extractSsrState(html)).toBeNull();
  });
});

describe("parseSearchPage", () => {
  test("maps the SSR vacancy list to the /scrape contract fields", () => {
    const page = parseSearchPage(ssrPage(SEARCH_STATE));
    expect(page).not.toBeNull();
    expect(page!.meta.totalResults).toBe(2);
    expect(page!.meta.totalPages).toBe(1);

    const card = page!.results[0];
    expect(card.id).toBe("1000168684");
    expect(card.title).toBe("ML-инженер (Python)");
    expect(card.company).toBe("Урал Логистика");
    expect(card.companyUrl).toBe("https://career.habr.com/companies/ulgroup");
    expect(card.location).toBe("Москва, Томск");
    expect(card.date).toBe("2026-09-29");
    expect(card.url).toBe("https://career.habr.com/vacancies/1000168684");
    expect(card.qualification).toBe("Middle");
    expect(card.remoteWork).toBe(true);
    expect(card.skills).toEqual(["Python", "PyTorch"]);
    expect(card.archived).toBe(false);
  });

  test("falls back to locations[0] and empty salary -> null", () => {
    const page = parseSearchPage(ssrPage(SEARCH_STATE));
    const card = page!.results[0];
    expect(card.salary).toBeNull();
  });

  test("returns null when the page carries no search state", () => {
    expect(parseSearchPage("<html></html>")).toBeNull();
    expect(parseSearchPage(ssrPage({ search: {} }))).toBeNull();
  });
});

describe("parseDetailPage", () => {
  test("maps description text and activity from the vacancy state", () => {
    const detail = parseDetailPage(ssrPage(DETAIL_STATE), "1000168741");
    expect(detail).not.toBeNull();
    expect(detail!.title).toBe("Python Developer / AI Engineer (Document Processing)");
    expect(detail!.location).toBe("Москва, Санкт-Петербург, Самара");
    expect(detail!.employment).toBe("full_time");
    expect(detail!.isActive).toBe(true);
    expect(detail!.deadline).toBeNull();
    expect(detail!.description).toContain("Python");
    expect(detail!.description).toContain("FastAPI");
    expect(detail!.description).toContain("\n");
  });

  test("archived vacancy is not active", () => {
    const archived = {
      vacancy: { ...DETAIL_STATE.vacancy, archived: true },
    };
    expect(parseDetailPage(ssrPage(archived), "1")!.isActive).toBe(false);
  });

  test("returns null without the vacancy state", () => {
    expect(parseDetailPage("<html></html>", "1")).toBeNull();
  });
});

describe("filters and helpers", () => {
  test("level map covers the observed qid values", () => {
    expect(LEVEL_QID).toEqual({ intern: 1, junior: 3, middle: 4, senior: 5, lead: 6 });
    expect(resolveLevels(["junior", "middle"])).toEqual([3, 4]);
    expect(resolveLevels(["seniorx"])).toBeNull();
  });

  test("city aliases resolve known names and numeric ids", () => {
    expect(resolveCityId("Москва")).toBe("678");
    expect(resolveCityId("moscow")).toBe("678");
    expect(resolveCityId("СПб")).toBe("679");
    expect(resolveCityId("123")).toBe("123");
    expect(resolveCityId("Казань")).toBeNull();
  });

  test("normalizeId accepts bare ids and vacancy URLs", () => {
    expect(normalizeId("1000168741")).toBe("1000168741");
    expect(normalizeId("https://career.habr.com/vacancies/1000168741")).toBe("1000168741");
    expect(normalizeId("/vacancies/1000168741?foo=1")).toBe("1000168741");
    expect(normalizeId("abc")).toBeNull();
  });

  test("isoDay truncates to the date part", () => {
    expect(isoDay("2026-09-29T10:23:58+03:00")).toBe("2026-09-29");
    expect(isoDay(null)).toBeNull();
  });

  test("isWithinWindow compares against the injected now", () => {
    const now = Date.parse("2026-10-01T12:00:00+03:00");
    expect(isWithinWindow("2026-09-29T10:00:00+03:00", null, 14, now)).toBe(true);
    expect(isWithinWindow("2026-09-01T10:00:00+03:00", null, 14, now)).toBe(false);
    expect(isWithinWindow(null, null, 14, now)).toBe(false);
  });

  test("htmlToText keeps block breaks and decodes entities", () => {
    const text = htmlToText("<p>A &amp; B</p><ul><li>C</li></ul>");
    expect(text).toBe("A & B\nC");
  });
});
