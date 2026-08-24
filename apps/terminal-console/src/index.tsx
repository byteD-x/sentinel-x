#!/usr/bin/env node

import { render } from 'ink'
import { TerminalApp } from './app.js'
import {
  describeConsoleInput,
  HELP_TEXT,
  parseConsoleArgs,
  selectDashboardFields,
} from './cli.js'
import { ConsoleDataHandler } from './handler.js'

async function main() {
  const parsed = parseConsoleArgs(process.argv.slice(2))

  if (parsed.kind === 'help') {
    process.stdout.write(HELP_TEXT)
    return
  }
  if (parsed.kind === 'describe') {
    writeJson({ success: true, schema: describeConsoleInput() })
    return
  }
  if (parsed.kind === 'error') {
    writeJson({ success: false, error: parsed.error }, process.stderr)
    process.exitCode = 2
    return
  }

  if (parsed.input.dryRun) {
    writeJson({ success: true, dry_run: true, request: parsed.input })
    return
  }

  const service = new ConsoleDataHandler()
  const output = process.stdout.isTTY && parsed.input.output === 'tui' ? 'tui' : 'json'
  if (output === 'json') {
    const result = await service.execute(parsed.input)
    if (result.success) {
      writeJson({ success: true, data: selectDashboardFields(result.data, parsed.input.fields) })
    } else {
      writeJson(result, process.stderr)
      process.exitCode = 1
    }
    return
  }

  render(<TerminalApp input={parsed.input} service={service} />)
}

function writeJson(value: unknown, stream: NodeJS.WriteStream = process.stdout) {
  stream.write(`${JSON.stringify(value)}\n`)
}

void main().catch((cause) => {
  writeJson({
    success: false,
    error: {
      code: 'INTERNAL_ERROR',
      message: cause instanceof Error ? cause.message : String(cause),
      recoverable: false,
    },
  }, process.stderr)
  process.exitCode = 1
})
