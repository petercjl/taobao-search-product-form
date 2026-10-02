import { createHash } from 'node:crypto';
import { constants as fsConstants } from 'node:fs';
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
  skill status|install|update (--agent codex|sealseek | --target-dir DIR) [--mode auto|link|copy]
  update check|install [--yes] [--agent codex|sealseek | --target-dir DIR]
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
  if (Boolean(opts.agent) === Boolean(opts.targetDir)) throw error('USAGE', 'Specify exactly one of --agent codex|sealseek or --target-dir DIR');
  if (opts.agent) {
    if (opts.agent === 'codex') return path.join(process.env.CODEX_HOME || path.join(os.homedir(), '.codex'), 'skills');
    if (opts.agent === 'sealseek') return path.join(process.env.SEALSEEK_HOME || path.join(os.homedir(), '.sealseek'), 'workspace', 'skills');
    throw error('PLATFORM_UNTESTED', `Unknown Agent: ${opts.agent}`);
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
  try {
    await managedCopy(before.destination);
    const oldMeta = path.join(backup, '.install-meta.json');
    const newMeta = path.join(before.destination, '.install-meta.json');
    if (await lstatOrNull(oldMeta) && !(await lstatOrNull(newMeta))) await fs.copyFile(oldMeta, newMeta, fsConstants.COPYFILE_EXCL);
  }
  catch (cause) {
    if (await lstatOrNull(before.destination)) await fs.rm(before.destination, { recursive: true, force: true });
    await fs.rename(backup, before.destination);
    throw cause;
  }
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
  const probe = python ? probePython(python) : null;
  const report = spawnSync(process.platform === 'win32' ? 'where.exe' : 'which', ['commerce-ui'], { encoding: 'utf8', timeout: 5000 });
  const reportSkillCandidates = [
    process.env.COMPACT_COMMERCE_UI_SKILL,
    path.join(process.env.CODEX_HOME || path.join(os.homedir(), '.codex'), 'skills', 'compact-commerce-ui', 'SKILL.md'),
    path.join(os.homedir(), '.agents', 'skills', 'compact-commerce-ui', 'SKILL.md'),
    path.join(process.env.SEALSEEK_HOME || path.join(os.homedir(), '.sealseek'), 'workspace', 'skills', 'compact-commerce-ui', 'SKILL.md'),
  ].filter(Boolean);
  let reportSkill = null;
  for (const candidate of reportSkillCandidates) if (await lstatOrNull(candidate)) { reportSkill = candidate; break; }
  const checks = [
    { id: 'node', ok: Number(process.versions.node.split('.')[0]) >= 20, value: process.version },
    { id: 'skill', ok: Boolean(await lstatOrNull(path.join(SOURCE, 'SKILL.md'))), value: SOURCE },
    { id: 'exceljs', ok: Boolean(await import('@excel.js/exceljs').catch(() => null)), value: '@excel.js/exceljs' },
    { id: 'python', ok: probe?.status === 0, value: probe?.status === 0 ? python : 'Python with pandas, numpy, openpyxl, Pillow and jieba unavailable' },
    { id: 'report-skill', ok: Boolean(reportSkill), value: reportSkill || 'compact-commerce-ui Skill unavailable' },
    { id: 'report-renderer', ok: report.status === 0, value: report.status === 0 ? report.stdout.trim().split(/\r?\n/)[0] : 'commerce-ui unavailable; HTML report stage requires compact-commerce-ui Skill and CLI' },
  ];
  const result = { ok: checks.every(check => check.ok), version: PACKAGE.version, checks };
  print(result);
  if (!result.ok) process.exitCode = 1;
}

function updateCheck() {
  const tag = PACKAGE.publishConfig.tag || 'latest';
  const result = runNpm(['view', PACKAGE.name, `dist-tags.${tag}`, '--json'], { encoding: 'utf8', timeout: 20000 });
  if (result.error || result.status !== 0) throw error('REGISTRY_UNAVAILABLE', result.error?.message || result.stderr?.trim() || 'npm view failed');
  const availableVersion = JSON.parse(result.stdout.trim() || 'null');
  print({ package: PACKAGE.name, installed: PACKAGE.version, tag, availableVersion, updateAvailable: Boolean(availableVersion && availableVersion !== PACKAGE.version) });
}

async function updateInstall(opts) {
  if (!opts.yes) throw error('CONFIRMATION_REQUIRED', 'Pass --yes to install the npm package update');
  const root = targetRoot(opts);
  const before = await status(root);
  if (!before.managed) throw error('UNMANAGED_TARGET', `Refusing to update ${before.destination} (${before.state})`);
  const tag = PACKAGE.publishConfig.tag || 'latest';
  const installed = runNpm(['install', '--global', `${PACKAGE.name}@${tag}`], { encoding: 'utf8', timeout: 180000 });
  if (installed.error || installed.status !== 0) throw error('INSTALL_FAILED', installed.error?.message || installed.stderr?.trim() || 'npm install failed');
  const npmRoot = runNpm(['root', '--global'], { encoding: 'utf8', timeout: 20000 });
  if (npmRoot.error || npmRoot.status !== 0) throw error('INSTALL_FAILED', npmRoot.error?.message || npmRoot.stderr?.trim() || 'npm root failed');
  const freshBin = path.join(npmRoot.stdout.trim(), ...PACKAGE.name.split('/'), 'bin', 'taobao-search-form.mjs');
  const updated = spawnSync(process.execPath, [freshBin, 'skill', 'update', '--target-dir', root], { encoding: 'utf8', timeout: 30000 });
  if (updated.error || updated.status !== 0) throw error('SKILL_SYNC_FAILED', updated.error?.message || updated.stderr?.trim() || 'Skill sync failed');
  const version = spawnSync(process.execPath, [freshBin, 'version'], { encoding: 'utf8', timeout: 5000 });
  if (version.error || version.status !== 0) throw error('INSTALL_FAILED', 'Updated CLI version check failed');
  print({ package: PACKAGE.name, tag, skill: JSON.parse(updated.stdout), version: version.stdout.trim() });
}

function runNpm(args, options) {
  return spawnSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', args, { ...options, shell: process.platform === 'win32' });
}

async function runScript(name, args) {
  if (!/^[a-z][a-z0-9_]*\.(py|mjs)$/.test(name)) throw error('USAGE', 'Invalid script name');
  const allowed = new Set(['clean_search_export.mjs', 'prepare.py', 'analyze.py', 'analyze_advertisers.py', 'analyze_geography.py', 'analyze_price_bands.py', 'analyze_title_roots.py', 'assemble_opportunity_evidence.py', 'build_report_viewmodel.py', 'build_visual_review_viewmodel.py', 'cluster_visual_forms.py', 'compile_style_prototypes.py', 'compile_visual_review.py', 'compile_visual_selection.py', 'validate_opportunity_cards.py', 'validate_report_viewmodel.py', 'visual_form_pipeline.py', 'visual_observation_batches.py', 'workflow_ledger.py']);
  if (!allowed.has(name)) throw error('USAGE', 'Script not in published command set');
  const binary = name.endsWith('.py') ? await resolvePython() : process.execPath;
  if (!binary) throw error('RUNTIME_UNAVAILABLE', 'Python with required packages is unavailable; run doctor --json');
  const scriptPath = path.join(SOURCE, 'scripts', name);
  const result = spawnSync(binary, binary === 'py' ? ['-3', scriptPath, ...args] : [scriptPath, ...args], { stdio: 'inherit' });
  if (result.error) throw error('RUNTIME_UNAVAILABLE', result.error.message);
  process.exitCode = result.status ?? 1;
}

async function lstatOrNull(target) { return fs.lstat(target).catch(e => { if (e.code === 'ENOENT') return null; throw e; }); }
function error(code, message) { return Object.assign(new Error(message), { code }); }
function print(value) { console.log(JSON.stringify(value, null, 2)); }

async function resolvePython() {
  const configured = process.env.TAOBAO_SEARCH_PYTHON;
  if (configured) return configured;
  const venv = path.join(os.homedir(), '.local', 'share', NAME, '.venv');
  const candidates = process.platform === 'win32'
    ? [path.join(venv, 'Scripts', 'python.exe'), 'py', 'python', 'python3']
    : [path.join(venv, 'bin', 'python'), 'python3', 'python'];
  for (const candidate of candidates) if (probePython(candidate).status === 0) return candidate;
  return null;
}

function probePython(binary) {
  const args = binary === 'py' ? ['-3', '-c', 'import pandas,numpy,openpyxl,PIL,jieba'] : ['-c', 'import pandas,numpy,openpyxl,PIL,jieba'];
  return spawnSync(binary, args, { encoding: 'utf8', timeout: 15000 });
}
