import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

const venv = path.join(os.homedir(), '.local', 'share', 'taobao-search-product-form', '.venv');
const managed = process.platform === 'win32' ? path.join(venv, 'Scripts', 'python.exe') : path.join(venv, 'bin', 'python');
const python = process.env.TAOBAO_SEARCH_PYTHON || (fs.existsSync(managed) ? managed : (process.platform === 'win32' ? 'python' : 'python3'));
const result = spawnSync(python, ['-m', 'unittest', 'discover', '-s', 'test', '-p', 'test_*.py'], { stdio: 'inherit' });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
