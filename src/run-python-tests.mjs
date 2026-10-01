import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

const managed = path.join(os.homedir(), '.local', 'share', 'taobao-search-product-form', '.venv', 'bin', 'python');
const python = process.env.TAOBAO_SEARCH_PYTHON || (fs.existsSync(managed) ? managed : 'python3');
const result = spawnSync(python, ['-m', 'unittest', 'discover', '-s', 'test', '-p', 'test_*.py'], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
