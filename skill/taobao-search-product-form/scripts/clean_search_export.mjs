#!/usr/bin/env node
/** Split an XLSX search export into first-seen natural products and all advertising appearances. */
import fs from 'node:fs/promises';
import path from 'node:path';
import ExcelJS from '@excel.js/exceljs';

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath || !outputPath) throw new Error('Usage: node clean_search_export.mjs SOURCE.xlsx OUTPUT.xlsx');
if (!(await fs.stat(sourcePath)).isFile()) throw new Error('Source is not a file');
if (await fs.stat(outputPath).then(() => true, e => { if (e.code === 'ENOENT') return false; throw e; })) {
  throw new Error(`Output already exists: ${outputPath}`);
}

const source = new ExcelJS.Workbook();
await source.xlsx.readFile(sourcePath);
const input = source.worksheets[0];
if (!input) throw new Error('Source workbook has no worksheet');
const headers = input.getRow(1).values.slice(1).map(value => String(value ?? '').trim());
const idColumn = headers.indexOf('商品ID');
const placementColumn = headers.indexOf('占位类型');
if (idColumn < 0 || placementColumn < 0) throw new Error('Source requires 商品ID and 占位类型 columns');

const natural = [], ads = [], seenNatural = new Set();
let duplicateNatural = 0;
for (let rowIndex = 2; rowIndex <= input.rowCount; rowIndex++) {
  const row = input.getRow(rowIndex);
  const values = headers.map((_, columnIndex) => row.getCell(columnIndex + 1).value);
  if (values.every(value => value === null || value === undefined || value === '')) continue;
  const id = String(values[idColumn] ?? '').trim();
  const placement = String(values[placementColumn] ?? '').trim();
  if (!id) throw new Error(`Blank 商品ID at source row ${rowIndex}`);
  values[idColumn] = id;
  if (placement === '自然位') {
    if (seenNatural.has(id)) { duplicateNatural++; continue; }
    seenNatural.add(id);
    natural.push(values);
  } else if (placement === '广告位') ads.push(values);
  else throw new Error(`Unknown 占位类型 at source row ${rowIndex}: ${placement}`);
}

const output = new ExcelJS.Workbook();
for (const [name, data] of [['自然位', natural], ['广告位', ads]]) {
  const sheet = output.addWorksheet(name, { views: [{ state: 'frozen', ySplit: 1 }] });
  sheet.addRow(headers);
  for (const values of data) sheet.addRow(values);
  sheet.getColumn(idColumn + 1).numFmt = '@';
  sheet.getRow(1).font = { name: 'Arial', size: 10, bold: true, color: { argb: 'FFFFFFFF' } };
  sheet.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F3A5F' } };
  sheet.autoFilter = { from: { row: 1, column: 1 }, to: { row: data.length + 1, column: headers.length } };
  sheet.columns.forEach((column, index) => { column.width = index === 2 ? 48 : 20; });
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
await output.xlsx.writeFile(outputPath);
console.log(JSON.stringify({
  sourceRows: natural.length + ads.length + duplicateNatural,
  naturalSourceRows: natural.length + duplicateNatural,
  naturalRetainedRows: natural.length,
  naturalDuplicateRowsRemoved: duplicateNatural,
  adRowsRetained: ads.length,
  output: outputPath,
}, null, 2));
