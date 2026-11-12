import { Plugin } from "@opencode/plugin"

const DESCRIPTION = [
  "Fetch and normalize a job posting for /apply from a single http(s) URL or",
  "hh vacancy id. Returns a brief with STATUS, metadata, salary benchmark,",
  "tracker/archive state, the posting_guard verdict and the cleaned posting",
  "posting text; paste the text directly into /apply instead.",
].join(" ")

export default Plugin.define({
  id: "apply-prefetch",
  async setup(ctx) {
    const directory = ctx.location.directory
    const python = Bun.which("python3") ?? Bun.which("python") ?? "python3"

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "posting_prefetch",
        description: DESCRIPTION,
        input: {
          type: "object",
          properties: {
            ref: {
              type: "string",
              description: "A single http(s) URL or hh.ru vacancy id. Not pasted text.",
            },
          },
          required: ["ref"],
          additionalProperties: false,
        },
        async execute(raw) {
          const { ref } = raw as { ref: string }
          const proc = Bun.spawn({
            cmd: [python, `${directory}/tools/apply_prefetch.py`, "--ref", ref],
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
          return { content: `STATUS: error\nREASON: prefetch exited ${exitCode}${detail}` }
        },
      })
    })
  },
})
