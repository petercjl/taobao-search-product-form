import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import ExcelJS from '@excel.js/exceljs';
import { install, status, update } from '../src/cli.mjs';

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
    assert.equal((await update(temp)).action, 'unchanged');
    await assert.rejects(install(temp, 'copy'), { code: 'TARGET_EXISTS' });
    const other = path.join(temp, 'unmanaged');
    await fs.mkdir(path.join(other, 'taobao-search-product-form'), { recursive: true });
    await assert.rejects(install(other, 'copy'), { code: 'TARGET_EXISTS' });
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
