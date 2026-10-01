#!/usr/bin/env node
import { main } from '../src/cli.mjs';

main(process.argv.slice(2)).catch(error => {
  console.error(JSON.stringify({ ok: false, error: error.code || 'COMMAND_FAILED', message: error.message }));
  process.exitCode = 1;
});
