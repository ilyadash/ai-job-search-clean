import { Plugin } from "@opencode/plugin"

const DESCRIPTION = [
  "Drive the hh.ru vacancy response form for /submit via tools/hh_apply.py.",
  "action=check previews what the form requires without sending; action=apply",
  "submits the response (no cover letter unless letter is set); action=attach",
  "adds a cover letter to an already-submitted response; action=status reports",
  "the current state. Returns the driver's JSON (status APPLIED, ALREADY_APPLIED,",
  "ACTION_REQUIRED, NEEDS_LOGIN, NOT_APPLIED or ERROR).",
].join(" ")

const ACTIONS = ["check", "apply", "attach", "status"] as const

type HhApplyInput = {
  action: (typeof ACTIONS)[number]
  url: string
  letter?: string
}

export default Plugin.define({
  id: "hh-apply",
  async setup(ctx) {
    const directory = ctx.location.directory
    const python = Bun.which("python3") ?? Bun.which("python") ?? "python3"

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "hh_apply",
        description: DESCRIPTION,
        input: {
          type: "object",
          properties: {
            action: { type: "string", enum: [...ACTIONS] },
            url: {
              type: "string",
              description: "hh.ru vacancy URL or numeric vacancy id",
            },
            letter: {
              type: "string",
              description:
                "Path to a plain-text cover letter; required for action=attach",
            },
          },
          required: ["action", "url"],
          additionalProperties: false,
        },
        async execute(raw) {
          const input = raw as HhApplyInput
          const args = [input.action, "--url", input.url, "--json"]
          if (input.letter) args.push("--letter", input.letter)
          const proc = Bun.spawn({
            cmd: [python, `${directory}/tools/hh_apply.py`, ...args],
            cwd: directory,
            stdout: "pipe",
            stderr: "pipe",
          })
          const [stdout, stderr, exitCode] = await Promise.all([
            new Response(proc.stdout).text(),
            new Response(proc.stderr).text(),
            proc.exited,
          ])
          const output = stdout.trim()
          if (exitCode === 0 && output) return { content: output }
          const detail = stderr.trim() ? `: ${stderr.trim()}` : ""
          return {
            content: `{"status":"ERROR","message":"hh_apply exited ${exitCode}${detail}"}`,
          }
        },
      })
    })
  },
})
