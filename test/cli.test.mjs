import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import { install, status, update, pythonCandidatesFor } from '../src/cli.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const bin = path.join(root, 'bin', 'taobao-search-form.mjs');
const packageVersion = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8')).version;

test('version and source resolve to the bundled canonical Skill', () => {
  const version = spawnSync(process.execPath, [bin, 'version'], { encoding: 'utf8' });
  assert.equal(version.status, 0);
  assert.equal(version.stdout.trim(), packageVersion);
  const source = spawnSync(process.execPath, [bin, 'skill', 'source', '--json'], { encoding: 'utf8' });
  assert.equal(source.status, 0);
  assert.equal(JSON.parse(source.stdout).source, path.join(root, 'skill', 'taobao-search-product-form'));
});

test('installer never replaces an unmanaged target', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-search-form-test-'));
  try {
    assert.equal((await status(temp)).state, 'absent');
    const installed = await install(temp, 'copy');
    assert.equal(installed.state, 'current');
    const meta = JSON.parse(await fs.readFile(path.join(temp, 'taobao-search-product-form', '.install-meta.json'), 'utf8'));
    assert.equal(meta.title, '淘宝搜索商品形态研究');
    assert.equal((await update(temp)).action, 'unchanged');
    await assert.rejects(install(temp, 'copy'), { code: 'TARGET_EXISTS' });
    const other = path.join(temp, 'unmanaged');
    await fs.mkdir(path.join(other, 'taobao-search-product-form'), { recursive: true });
    await assert.rejects(install(other, 'copy'), { code: 'TARGET_EXISTS' });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('SealSeek target uses its managed workspace and keeps UI metadata on copy update', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-search-form-agent-'));
  let backup;
  try {
    const env = { ...process.env, SEALSEEK_HOME: temp };
    const installRun = spawnSync(process.execPath, [bin, 'skill', 'install', '--agent', 'sealseek', '--mode', 'copy'], { encoding: 'utf8', env });
    assert.equal(installRun.status, 0, installRun.stderr);
    const target = path.join(temp, 'workspace', 'skills', 'taobao-search-product-form');
    assert.equal((await fs.stat(path.join(target, 'SKILL.md'))).isFile(), true);
    await fs.writeFile(path.join(target, '.install-meta.json'), '{"title":"淘宝搜索选品","description":"自定义说明"}\n');
    const manifestPath = path.join(target, '.taobao-search-form-managed.json');
    const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
    manifest.sourceDigest = 'previous-package-digest';
    await fs.writeFile(manifestPath, JSON.stringify(manifest));
    const updated = await update(path.join(temp, 'workspace', 'skills'), { forceInPlace: true });
    backup = updated.backup;
    assert.equal(updated.state, 'current');
    assert.equal(updated.updateStrategy, 'in-place');
    assert.equal(JSON.parse(await fs.readFile(path.join(target, '.install-meta.json'), 'utf8')).title, '淘宝搜索选品');
    assert.equal((await fs.stat(updated.backup)).isDirectory(), true);
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
    if (backup) await fs.rm(backup, { recursive: true, force: true });
  }
});

test('modified managed files are not silently replaced', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-search-form-modified-'));
  try {
    await install(temp, 'copy');
    const skill = path.join(temp, 'taobao-search-product-form', 'SKILL.md');
    await fs.appendFile(skill, '\nlocal edit\n');
    assert.equal((await status(temp)).state, 'modified');
    await assert.rejects(update(temp, { forceInPlace: true }), { code: 'UNMANAGED_TARGET' });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('Python discovery includes the SealSeek managed runtime by platform', () => {
  const windows = pythonCandidatesFor('win32', 'C:\\Users\\worker', 'C:\\Users\\worker\\.sealseek');
  assert.ok(windows.some(candidate => candidate.endsWith(path.join('binaries', 'python', 'envs', 'default', 'Scripts', 'python.exe'))));
  const mac = pythonCandidatesFor('darwin', '/Users/worker', '/Users/worker/.sealseek');
  assert.ok(mac.some(candidate => candidate.endsWith(path.join('binaries', 'python', 'envs', 'default', 'bin', 'python'))));
});

test('doctor checks the bundled report runtime without requiring commerce-ui', () => {
  const run = spawnSync(process.execPath, [bin, 'doctor', '--json'], { encoding: 'utf8' });
  const result = JSON.parse(run.stdout);
  assert.equal(typeof result.ok, 'boolean');
  assert.ok(result.checks.some(check => check.id === 'python'));
  assert.equal(result.checks.find(check => check.id === 'report-runtime')?.ok, true);
  assert.equal(result.checks.some(check => check.id === 'report-skill' || check.id === 'report-renderer'), false);
});

test('bundled report renderer creates and validates a standalone HTML file', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-search-form-report-'));
  try {
    const input = path.join(temp, 'report.json');
    const output = path.join(temp, 'report.html');
    const conclusion = { type: 'conclusion', items: [
      { label: '优先', tone: 'positive', segments: [{ text: '先研究具体款式', emphasis: 'strong', tone: 'positive' }, { text: '，核对供应端。', emphasis: 'italic' }] },
      { label: '边界', tone: 'warning', segments: [{ text: '搜索快照不能证明利润', emphasis: 'strong', tone: 'warning' }, { text: '，需要另行测算。', emphasis: 'italic' }] },
    ] };
    await fs.writeFile(input, JSON.stringify({ contract: 'compact-workbench@1.0', meta: { title: '选品研究测试' }, views: [
      { id: 'summary', label: '结论', title: '结论', blocks: [conclusion] },
      { id: 'evidence', label: '证据', title: '证据', blocks: [{ type: 'card', title: '数据', blocks: [{ type: 'text', text: '样本数据' }] }] },
    ] }));
    const run = spawnSync(process.execPath, [bin, 'script', 'render_report.py', '--input', input, '--output', output], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    const result = JSON.parse(run.stdout.trim());
    assert.equal(result.validation.ok, true);
    const html = await fs.readFile(output, 'utf8');
    assert.match(html, /选品研究测试/);
    assert.match(html, /function\s+showView\s*\(/);
    const collision = spawnSync(process.execPath, [bin, 'script', 'render_report.py', '--input', input, '--output', output], { encoding: 'utf8' });
    assert.notEqual(collision.status, 0);
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});

test('cleaning keeps the first natural ID and all ad records', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-search-form-xlsx-'));
  try {
    const input = path.join(temp, 'input.xlsx'), output = path.join(temp, 'output.xlsx');
    const workbook = new ExcelJS.Workbook();
    const sheet = workbook.addWorksheet('搜索');
    sheet.addRow(['商品ID', '占位类型', '商品名称']);
    sheet.addRow(['123', '自然位', 'first']);
    sheet.addRow(['123', '广告位', 'ad A']);
    sheet.addRow(['123', '自然位', 'later']);
    sheet.addRow(['123', '广告位', 'ad B']);
    await workbook.xlsx.writeFile(input);
    const run = spawnSync(process.execPath, [bin, 'script', 'clean_search_export.mjs', input, output], { encoding: 'utf8' });
    assert.equal(run.status, 0, run.stderr);
    const counts = JSON.parse(run.stdout);
    assert.equal(counts.naturalDuplicateRowsRemoved, 1);
    assert.equal(counts.adRowsRetained, 2);
    const cleaned = new ExcelJS.Workbook();
    await cleaned.xlsx.readFile(output);
    assert.equal(cleaned.getWorksheet('自然位').rowCount, 2);
    assert.equal(cleaned.getWorksheet('自然位').getRow(2).getCell(3).value, 'first');
    assert.equal(cleaned.getWorksheet('广告位').rowCount, 3);
    const collision = spawnSync(process.execPath, [bin, 'script', 'clean_search_export.mjs', input, output], { encoding: 'utf8' });
    assert.notEqual(collision.status, 0);
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});
