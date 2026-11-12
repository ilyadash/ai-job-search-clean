import { join } from "path"

const CLI_PATH = join(import.meta.dir, "../src/cli.ts")

export interface CLIResult {
  stdout: string
  stderr: string
  exitCode: number
}

/**
 * Run the CLI with an optional env overlay. A key set to `undefined` is
 * removed from the child environment (used to test MISSING_CREDENTIALS
 * deterministically even when the parent shell has HH_API_TOKEN set).
 */
export async function runCLI(args: string[], env?: Record<string, string | undefined>): Promise<CLIResult> {
  const merged: Record<string, string> = { ...(process.env as Record<string, string>) }
  if (env) {
    for (const [key, value] of Object.entries(env)) {
      if (value === undefined) delete merged[key]
      else merged[key] = value
    }
  }
  const proc = Bun.spawn(["bun", "run", CLI_PATH, ...args], {
    stdout: "pipe",
    stderr: "pipe",
    env: merged,
  })

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])

  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode }
}

export function parseJSON<T = unknown>(result: CLIResult): T {
  if (result.exitCode !== 0) {
    throw new Error(`CLI exited with code ${result.exitCode}. stderr: ${result.stderr}`)
  }
  try {
    return JSON.parse(result.stdout) as T
  } catch {
    throw new Error(`Failed to parse JSON. stdout: ${result.stdout}\nstderr: ${result.stderr}`)
  }
}

export function parseError(result: CLIResult): { error: string; code: string } {
  try {
    return JSON.parse(result.stderr) as { error: string; code: string }
  } catch {
    throw new Error(`stderr is not JSON: ${result.stderr}`)
  }
}
