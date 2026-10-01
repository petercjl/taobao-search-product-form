import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const NAME = 'taobao-search-product-form';
const SOURCE = path.join(ROOT, 'skill', NAME);
const MANIFEST = '.taobao-search-form-managed.json';
const PACKAGE = JSON.parse(await fs.readFile(path.join(ROOT, 'package.json'), 'utf8'));

export async function main(argv) {
  const [command, action, ...rest] = argv;
  const opts = parseOptions(rest);
  if (!command || ['-h', '--help', 'help'].includes(command)) return printHelp();
  if (command === 'version') return console.log(PACKAGE.version);
  if (command === 'capabilities') return print(JSON.parse(await fs.readFile(path.join(SOURCE, 'capabilities.json'), 'utf8')));
  if (command === 'doctor') return doctor();
  if (command === 'skill') {
    if (action === 'source') return print({ skill: NAME, source: SOURCE, sourceDigest: await digest(SOURCE), version: PACKAGE.version });
    if (action === 'status') return print(await status(targetRoot(opts)));
    if (action === 'install') return print(await install(targetRoot(opts), opts.mode || 'auto'));
    if (action === 'update') return print(await update(targetRoot(opts)));
  }
  if (command === 'update' && action === 'check') return updateCheck();
  if (command === 'update' && action === 'install') return updateInstall(opts);
  if (command === 'script' && action) return runScript(action, rest);
  throw error('USAGE', 'Unknown command. Run taobao-search-form --help.');
}

function printHelp() {
  console.log(`taobao-search-form ${PACKAGE.version}
  version
  capabilities --json
  doctor --json
  skill source --json
  skill status|install|update (--agent codex | --target-dir DIR) [--mode auto|link|copy]
  update check|install [--yes]
  script NAME [script arguments...]
The Skill's business workflow is in its SKILL.md. No external service is modified by this CLI.`);
}

function parseOptions(args) {
  const opts = {};
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (key === '--json') opts.json = true;
    else if (key === '--yes') opts.yes = true;
    else if (['--agent', '--target-dir', '--mode'].includes(key)) {
      if (!args[i + 1] || args[i + 1].startsWith('--')) throw error('USAGE', `${key} requires a value`);
      opts[key.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = args[++i];
    }
  }
  return opts;
}

function targetRoot(opts) {
  if (Boolean(opts.agent) === Boolean(opts.targetDir)) throw error('USAGE', 'Specify exactly one of --agent codex or --target-dir DIR');
  if (opts.agent) {
    if (opts.agent !== 'codex') throw error('PLATFORM_UNTESTED', 'Only the Codex adapter is supported by this preview');
    return path.join(process.env.CODEX_HOME || path.join(os.homedir(), '.codex'), 'skills');
  }
  return path.resolve(opts.targetDir);
}

export async function status(root) {
  const destination = path.join(root, NAME);
  const sourceDigest = await digest(SOURCE);
  const base = { skill: NAME, source: SOURCE, sourceDigest, destination };
  const stat = await lstatOrNull(destination);
  if (!stat) return { ...base, state: 'absent', managed: false };
  if (stat.isSymbolicLink()) {
    const resolved = await fs.realpath(destination).catch(() => null);
    const current = resolved === await fs.realpath(SOURCE);
    return { ...base, state: current ? 'current' : (resolved ? 'foreign-link' : 'broken-link'), mode: 'link', managed: current };
  }
  const manifest = await fs.readFile(path.join(destination, MANIFEST), 'utf8').then(JSON.parse).catch(() => null);
  const managed = manifest?.managedBy === PACKAGE.name && manifest?.skill === NAME;
  return { ...base, state: !managed ? 'unmanaged' : (manifest.sourceDigest === sourceDigest ? 'current' : 'stale'), mode: 'copy', managed };
}

export async function install(root, requestedMode = 'auto') {
  if (!['auto', 'link', 'copy'].includes(requestedMode)) throw error('USAGE', 'Mode must be auto, link or copy');
  const before = await status(root);
  if (before.state !== 'absent') throw error('TARGET_EXISTS', `Refusing to replace ${before.destination} (${before.state})`);
  const mode = requestedMode === 'auto' ? (process.platform === 'win32' ? 'copy' : 'link') : requestedMode;
  await fs.mkdir(root, { recursive: true });
  if (mode === 'link') await fs.symlink(SOURCE, before.destination, process.platform === 'win32' ? 'junction' : 'dir');
  else await managedCopy(before.destination);
  return { ...await status(root), action: 'installed' };
}

export async function update(root) {
  const before = await status(root);
  if (before.state === 'current') return { ...before, action: 'unchanged' };
  if (before.state !== 'stale' || before.mode !== 'copy' || !before.managed) throw error('UNMANAGED_TARGET', `Refusing to update ${before.destination} (${before.state})`);
  const backupRoot = path.join(os.homedir(), '.local', 'state', NAME, 'skill-backups');
  await fs.mkdir(backupRoot, { recursive: true });
  const backup = path.join(backupRoot, `${NAME}-${Date.now()}`);
  if (await lstatOrNull(backup)) throw error('TARGET_EXISTS', `Backup already exists: ${backup}`);
  await fs.rename(before.destination, backup);
  try { await managedCopy(before.destination); }
  catch (cause) { if (!(await lstatOrNull(before.destination))) await fs.rename(backup, before.destination); throw cause; }
  return { ...await status(root), action: 'updated', backup };
}

async function managedCopy(destination) {
  await fs.cp(SOURCE, destination, { recursive: true, errorOnExist: true, force: false });
  const manifest = { managedBy: PACKAGE.name, skill: NAME, sourceDigest: await digest(SOURCE), installedAt: new Date().toISOString() };
  await fs.writeFile(path.join(destination, MANIFEST), `${JSON.stringify(manifest, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
}

async function digest(root) {
  const hash = createHash('sha256');
  async function visit(dir) {
    for (const entry of (await fs.readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const absolute = path.join(dir, entry.name);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile() && entry.name !== MANIFEST) {
        hash.update(path.relative(root, absolute)); hash.update('\0');
        hash.update(await fs.readFile(absolute)); hash.update('\0');
      }
    }
  }
  await visit(root);
  return hash.digest('hex');
}

async function doctor() {
  const python = await resolvePython();
  const probe = spawnSync(python, ['-c', 'import pandas,numpy,openpyxl,PIL,jieba; print("ok")'], { encoding: 'utf8', timeout: 15000 });
  const checks = [
    { id: 'node', ok: Number(process.versions.node.split('.')[0]) >= 20, value: process.version },
    { id: 'skill', ok: Boolean(await lstatOrNull(path.join(SOURCE, 'SKILL.md'))), value: SOURCE },
    { id: 'exceljs', ok: Boolean(await import('@excel.js/exceljs').catch(() => null)), value: '@excel.js/exceljs' },
    { id: 'python', ok: probe.status === 0, value: probe.status === 0 ? python : (probe.error?.message || probe.stderr?.trim() || 'missing Python dependencies') },
  ];
  const result = { ok: checks.every(check => check.ok), version: PACKAGE.version, checks };
  print(result);
  if (!result.ok) process.exitCode = 1;
}

function updateCheck() {
  const result = spawnSync('npm', ['view', PACKAGE.name, 'dist-tags.next', '--json'], { encoding: 'utf8', timeout: 20000 });
  if (result.error || result.status !== 0) throw error('REGISTRY_UNAVAILABLE', result.error?.message || result.stderr?.trim() || 'npm view failed');
  const latest = JSON.parse(result.stdout.trim() || 'null');
  print({ package: PACKAGE.name, installed: PACKAGE.version, next: latest, updateAvailable: Boolean(latest && latest !== PACKAGE.version) });
}

function updateInstall(opts) {
  if (!opts.yes) throw error('CONFIRMATION_REQUIRED', 'Pass --yes to install the npm next version');
  const result = spawnSync('npm', ['install', '--global', `${PACKAGE.name}@next`], { stdio: 'inherit' });
  if (result.error) throw error('INSTALL_FAILED', result.error.message);
  process.exitCode = result.status ?? 1;
}

async function runScript(name, args) {
  if (!/^[a-z][a-z0-9_]*\.(py|mjs)$/.test(name)) throw error('USAGE', 'Invalid script name');
  const allowed = new Set(['clean_search_export.mjs', 'prepare.py', 'analyze.py', 'analyze_advertisers.py', 'analyze_geography.py', 'analyze_price_bands.py', 'analyze_title_roots.py', 'assemble_opportunity_evidence.py', 'build_report_viewmodel.py', 'build_visual_review_viewmodel.py', 'cluster_visual_forms.py', 'compile_style_prototypes.py', 'compile_visual_review.py', 'compile_visual_selection.py', 'validate_opportunity_cards.py', 'validate_report_viewmodel.py', 'visual_form_pipeline.py', 'visual_observation_batches.py', 'workflow_ledger.py']);
  if (!allowed.has(name)) throw error('USAGE', 'Script not in published command set');
  const binary = name.endsWith('.py') ? await resolvePython() : process.execPath;
  const scriptPath = path.join(SOURCE, 'scripts', name);
  const result = spawnSync(binary, [scriptPath, ...args], { stdio: 'inherit' });
  if (result.error) throw error('RUNTIME_UNAVAILABLE', result.error.message);
  process.exitCode = result.status ?? 1;
}

async function lstatOrNull(target) { return fs.lstat(target).catch(e => { if (e.code === 'ENOENT') return null; throw e; }); }
function error(code, message) { return Object.assign(new Error(message), { code }); }
function print(value) { console.log(JSON.stringify(value, null, 2)); }

async function resolvePython() {
  if (process.env.TAOBAO_SEARCH_PYTHON) return process.env.TAOBAO_SEARCH_PYTHON;
  const managed = path.join(os.homedir(), '.local', 'share', NAME, '.venv', 'bin', 'python');
  return await lstatOrNull(managed) ? managed : 'python3';
}
