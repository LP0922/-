import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const root = process.cwd();
const dir = path.join(root, 'batch_test');
const outDir = path.join(root, 'outputs', 'batch_test_summary');
await fs.mkdir(outDir, { recursive: true });

const rows = [];
for (const file of await fs.readdir(dir)) {
  if (!file.startsWith('feedback_') || !file.endsWith('.json')) continue;
  try {
    const j = JSON.parse(await fs.readFile(path.join(dir, file), 'utf8'));
    const target = Number(j.target_mass_mg);
    if (![100,200,300,400,500,600,700,800,900,1000].includes(target) || j.result === 'cancelled') continue;
    const m = /-s01r(\d+)-/.exec(j.run_id);
    rows.push([target, Number(j.final_mass_mg), Number(j.actual_duration_s), Number(m?.[1] ?? 0)]);
  } catch {}
}
rows.sort((a,b) => a[0]-b[0] || a[3]-b[3]);

const wb = Workbook.create();
const sh = wb.worksheets.add('实验记录');
sh.showGridLines = false;
sh.getRange('A1:D1').merge();
sh.getRange('A1').values = [['批量测试实验记录（精简版）']];
sh.getRange('A2:D2').merge();
sh.getRange('A2').values = [['正式实验共 100 次；已排除 700 mg 取消试跑。']];
sh.getRange('A4:D4').values = [['目标量 (mg)','实际量 (mg)','耗时 (s)','实验次数']];
sh.getRange(`A5:D${rows.length+4}`).values = rows.map(r => [r[0],r[1],r[2],r[3]]);
sh.getRange('A1:D1').format = { font:{name:'Arial',size:14,bold:true,color:'#1F2937'}, horizontalAlignment:'left' };
sh.getRange('A2:D2').format = { font:{name:'Arial',size:10,italic:true,color:'#6B7280'} };
sh.getRange('A4:D4').format = { fill:'#1F4E78', font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'}, horizontalAlignment:'center', verticalAlignment:'center' };
sh.getRange(`A4:D${rows.length+4}`).format.borders = { preset:'all', style:'thin', color:'#D9E2F3' };
sh.getRange(`A5:D${rows.length+4}`).format.numberFormat = '0.0';
sh.getRange(`A5:A${rows.length+4}`).format.numberFormat = '0';
sh.getRange(`D5:D${rows.length+4}`).format.numberFormat = '0';
sh.getRange(`A1:D${rows.length+4}`).format.verticalAlignment = 'center';
sh.getRange('A:A').format.columnWidth = 16; sh.getRange('B:B').format.columnWidth = 16; sh.getRange('C:C').format.columnWidth = 14; sh.getRange('D:D').format.columnWidth = 12;
sh.freezePanes.freezeRows(4);
wb.recalculate();
const preview = await wb.render({sheetName:'实验记录', autoCrop:'all', scale:1, format:'png'});
await fs.writeFile(path.join(outDir,'simple_preview.png'), new Uint8Array(await preview.arrayBuffer()));
const xlsx = await SpreadsheetFile.exportXlsx(wb);
const out = path.join(outDir,'batch_test_simple.xlsx');
await xlsx.save(out);
console.log(JSON.stringify({out, rows: rows.length}, null, 2));
