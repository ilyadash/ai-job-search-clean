import { describe, expect, test } from "bun:test"
import {
  areaAlias,
  findAreaId,
  htmlToText,
  isoDate,
  mapSearchItem,
  mapVacancy,
  snippetText,
  type HhAreaNode,
  type HhSearchItem,
} from "../src/helpers.js"
import { normalizeId } from "../src/commands/detail.js"
import { buildSearchParams, type SearchOpts } from "../src/commands/search.js"

const baseOpts: SearchOpts = { page: 1, perPage: 100, format: "json" }

describe("isoDate", () => {
  test("slices an ISO timestamp to a date", () => {
    expect(isoDate("2026-09-30T10:00:00+0300")).toBe("2026-09-30")
  })
  test("returns null for missing values", () => {
    expect(isoDate(null)).toBeNull()
    expect(isoDate(undefined)).toBeNull()
  })
})

describe("htmlToText", () => {
  test("strips tags, decodes entities, and keeps block breaks", () => {
    const html = "<p>Hello &amp; world</p><ul><li>one</li><li>two&nbsp;items</li></ul>"
    const text = htmlToText(html)
    expect(text).toBe("Hello & world\none\ntwo items")
  })
  test("drops <highlighttext> markers used in search snippets", () => {
    expect(htmlToText("Опыт с <highlighttext>Python</highlighttext> и SQL")).toBe("Опыт с Python и SQL")
  })
})

describe("snippetText", () => {
  test("joins requirement and responsibility", () => {
    expect(snippetText({ requirement: "Python", responsibility: "ML" })).toBe("Python · ML")
  })
  test("returns null when nothing is present", () => {
    expect(snippetText(null)).toBeNull()
    expect(snippetText({})).toBeNull()
  })
})

describe("mapSearchItem", () => {
  test("maps the contract fields from a full hh.ru item", () => {
    const item: HhSearchItem = {
      id: "1300000000",
      name: "ML-инженер",
      area: { id: "1", name: "Москва" },
      employer: { id: "42", name: "Acme", alternate_url: "https://hh.ru/employer/42" },
      published_at: "2026-09-30T10:00:00+0300",
      alternate_url: "https://hh.ru/vacancy/1300000000",
      salary_range: { from: 100000, to: 200000, currency: "RUR", gross: false },
      experience: { id: "between1And3", name: "От 1 до 3 лет" },
      employment_form: { id: "FULL", name: "Полная занятость" },
      work_format: [{ id: "REMOTE", name: "Из дома" }],
      snippet: { requirement: "Python, SQL", responsibility: "ML-модели" },
      archived: false,
    }
    const result = mapSearchItem(item)
    expect(result.id).toBe("1300000000")
    expect(result.title).toBe("ML-инженер")
    expect(result.company).toBe("Acme")
    expect(result.location).toBe("Москва")
    expect(result.date).toBe("2026-09-30")
    expect(result.url).toBe("https://hh.ru/vacancy/1300000000")
    expect(result.salary?.from).toBe(100000)
    expect(result.experience).toBe("От 1 до 3 лет")
    expect(result.employment).toBe("Полная занятость")
    expect(result.workFormat).toEqual(["Из дома"])
    expect(result.snippet).toBe("Python, SQL · ML-модели")
  })

  test("fills nulls and a fallback URL for a minimal item", () => {
    const result = mapSearchItem({ id: "7" })
    expect(result.title).toBe("(untitled)")
    expect(result.company).toBeNull()
    expect(result.location).toBeNull()
    expect(result.date).toBeNull()
    expect(result.url).toBe("https://hh.ru/vacancy/7")
    expect(result.salary).toBeNull()
    expect(result.workFormat).toBeNull()
  })
})

describe("mapVacancy", () => {
  test("cleans the description, extracts skills, and keeps deadline null", () => {
    const detail = mapVacancy({
      id: "7",
      name: "Data Scientist",
      employer: { name: "Acme", alternate_url: "https://hh.ru/employer/42" },
      description: "<p>Build <strong>ML</strong> models</p><ul><li>Python</li></ul>",
      key_skills: [{ name: "Python" }, { name: "SQL" }],
      apply_alternate_url: "https://hh.ru/applicant/vacancy_response?vacancyId=7",
      archived: false,
    })
    expect(detail.description).toBe("Build ML models\nPython")
    expect(detail.keySkills).toEqual(["Python", "SQL"])
    expect(detail.companyUrl).toBe("https://hh.ru/employer/42")
    expect(detail.applyUrl).toContain("vacancyId=7")
    expect(detail.deadline).toBeNull()
    expect(detail.isActive).toBe(true)
  })

  test("marks archived and closed-for-applicants vacancies inactive", () => {
    expect(mapVacancy({ id: "1", archived: true }).isActive).toBe(false)
    expect(mapVacancy({ id: "1", closed_for_applicants: true }).isActive).toBe(false)
  })
})

describe("normalizeId", () => {
  test.each([
    ["1300000000", "1300000000"],
    ["https://hh.ru/vacancy/1300000000", "1300000000"],
    ["https://hh.ru/vacancy/1300000000?query=x", "1300000000"],
    ["https://api.hh.ru/vacancies/999", "999"],
    ["https://hh.ru/applicant/vacancy_response?vacancyId=777", "777"],
  ])("parses %s", (input, expected) => {
    expect(normalizeId(input)).toBe(expected)
  })
  test("rejects garbage", () => {
    expect(normalizeId("not-a-vacancy")).toBeNull()
  })
})

describe("area resolution", () => {
  test("known aliases resolve without a network call", () => {
    expect(areaAlias("Москва")).toBe("1")
    expect(areaAlias("moscow")).toBe("1")
    expect(areaAlias("СПб")).toBe("2")
    expect(areaAlias("Казань")).toBeNull()
  })

  test("findAreaId prefers exact matches across the tree", () => {
    const tree: HhAreaNode[] = [
      {
        id: "113",
        name: "Россия",
        areas: [
          { id: "1", name: "Москва" },
          { id: "88", name: "Московская область", areas: [{ id: "1", name: "Москва" }] },
        ],
      },
      { id: "40", name: "Казахстан", areas: [{ id: "159", name: "Алматы" }] },
    ]
    expect(findAreaId(tree, "Алматы")).toBe("159")
    expect(findAreaId(tree, "москва")).toBe("1")
    expect(findAreaId(tree, "Московская")).toBe("88")
    expect(findAreaId(tree, "Атлантида")).toBeNull()
  })
})

describe("buildSearchParams", () => {
  test("maps flags to hh.ru parameters and disables magic rewriting", () => {
    const params = buildSearchParams(
      {
        ...baseOpts,
        query: "ML-инженер",
        jobage: 14,
        experience: ["between1And3"],
        employment: ["FULL", "PART"],
        workFormat: ["REMOTE"],
        orderBy: "publication_time",
        page: 2,
      },
      "1",
      1,
    )
    expect(params.get("text")).toBe("ML-инженер")
    expect(params.get("area")).toBe("1")
    expect(params.get("period")).toBe("14")
    // Multi-value filters are repeated keys, never comma-joined: hh.ru returns
    // HTTP 400 bad_argument for "experience=a,b" and the other list params.
    expect(params.getAll("experience")).toEqual(["between1And3"])
    expect(params.getAll("employment_form")).toEqual(["FULL", "PART"])
    expect(params.getAll("work_format")).toEqual(["REMOTE"])
    expect(params.get("order_by")).toBe("publication_time")
    expect(params.get("page")).toBe("1")
    expect(params.get("per_page")).toBe("100")
    expect(params.get("no_magic")).toBe("true")
  })

  test("omits optional filters when not set", () => {
    const params = buildSearchParams(baseOpts, null, 0)
    expect(params.get("text")).toBeNull()
    expect(params.get("area")).toBeNull()
    expect(params.get("period")).toBeNull()
    expect(params.get("page")).toBe("0")
  })
})
