import { describe, expect, test } from "bun:test"
import { parseError, runCLI } from "./helpers.js"

// Unreachable API base guarantees these cases never depend on the network:
// every assertion below must fail during validation, before any fetch.
const NO_NETWORK = { HH_API_TOKEN: "test-token", HH_API_BASE_URL: "http://127.0.0.1:9" }

describe("flag validation", () => {
  test("unknown flag exits 1 with UNKNOWN_FLAG", async () => {
    const result = await runCLI(["search", "--bogus", "x"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("UNKNOWN_FLAG")
  })

  test("missing HH_API_TOKEN exits 1 with MISSING_CREDENTIALS", async () => {
    const result = await runCLI(["search", "-q", "ML"], { ...NO_NETWORK, HH_API_TOKEN: undefined })
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("MISSING_CREDENTIALS")
  })

  test("jobage outside 1-30 is rejected", async () => {
    const result = await runCLI(["search", "-q", "ML", "--jobage", "31"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ARG")
  })

  test("location and area together are rejected", async () => {
    const result = await runCLI(["search", "-l", "Москва", "-a", "1"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("CONFLICTING_AREA_FLAGS")
  })

  test("non-numeric area is rejected", async () => {
    const result = await runCLI(["search", "-a", "Москва"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ARG")
  })

  test("unknown work-format value is rejected", async () => {
    const result = await runCLI(["search", "-q", "ML", "--work-format", "teleport"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ARG")
  })

  test("unknown order-by value is rejected", async () => {
    const result = await runCLI(["search", "-q", "ML", "--order-by", "fun"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ARG")
  })

  test("unknown format is rejected", async () => {
    const result = await runCLI(["search", "-q", "ML", "--format", "yaml"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ARG")
  })

  test("detail without an id is rejected", async () => {
    const result = await runCLI(["detail"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("NO_ID")
  })

  test("detail with an unparsable id is rejected", async () => {
    const result = await runCLI(["detail", "not-a-vacancy"], NO_NETWORK)
    expect(result.exitCode).toBe(1)
    expect(parseError(result).code).toBe("BAD_ID")
  })

  test("search --help prints usage and exits 0", async () => {
    const result = await runCLI(["search", "--help"], NO_NETWORK)
    expect(result.exitCode).toBe(0)
    expect(result.stdout).toContain("USAGE")
  })
})
