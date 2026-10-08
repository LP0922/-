import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const root = process.cwd();
const bt = path.join(root, 'batch_test');
const outDir = path.join(root, 'outputs', 'batch_test_summary');
await fs.mkdir(outDir, { recursive: true });

const files = (await fs.readdir(bt)).filter(f => f.startsWith('feedback_') && f.endsWith('.json'));
const records = [];
for (const file of files) {
  try {
    const j = JSON.parse(await fs.readFile(path.join(bt, file), 'utf8'));
    const target = Number(j.target_mass_mg);
    if (![100,200,300,400,500,600,700,800,900,1000].includes(target)) continue;
    records.push({
      target, run: j.run_id, result: j.result, final: Number(j.final_mass_mg ?? 0),
      low: Number(j.acceptance_min_mg ?? target - 10), high: Number(j.acceptance_max_mg ?? target + 10),
      duration: Number(j.actual_duration_s ?? 0), file,
      pass: Number(j.final_mass_mg) >= Number(j.acceptance_min_mg) && Number(j.final_mass_mg) <= Number(j.acceptance_max_mg) && j.result !== 'cancelled'
    });
  } catch {}
}
const official = records.filter(r => r.result !== 'cancelled').sort((a,b) => a.target-b.target || a.run.localeCompare(b.run));
const cancelled = records.filter(r => r.result === 'cancelled');
const targets = [100,200,300,400,500,600,700,800,900,1000];
const summaries = targets.map(target => {
  const rs = official.filter(r => r.target === target);
  const mean = rs.reduce((s,r)=>s+r.final,0)/rs.length;
  const errors = rs.map(r=>r.final-target);
  const bias = errors.reduce((s,x)=>s+x,0)/rs.length;
  const sd = Math.sqrt(errors.reduce((s,x)=>s+(x-bias)**2,0)/rs.length);
  return {target, runs: rs.length, pass: rs.filter(r=>r.pass).length, mean, bias, biasPct: bias/target, sd,
    min: Math.min(...rs.map(r=>r.final)), max: Math.max(...rs.map(r=>r.final)), avgDuration: rs.reduce((s,r)=>s+r.duration,0)/rs.length};
});

const wb = Workbook.create();
const summary = wb.worksheets.add('总体汇总');
const detail = wb.worksheets.add('逐次明细');
const notes = wb.worksheets.add('异常记录');
for (const sh of [summary, detail, notes]) { sh.showGridLines = false; sh.getUsedRange()?.format?.font && (sh.getUsedRange().format.font = { name: 'Arial', size: 10, color: '#1F2937' }); }

summary.getRange('A1:J1').merge();
summary.getRange('A1').values = [['批量测试总体汇总（2026-09-20）']];
summary.getRange('A2:J2').merge();
summary.getRange('A2').values = [['正式数据：100–1000 mg，每档 10 次；合格判定按各 JSON 中的 acceptance_min_mg / acceptance_max_mg。']];
summary.getRange('A4:J4').values = [['目标质量 (mg)','测试次数','合格次数','合格率','平均实测 (mg)','平均偏差 (mg)','平均偏差 (%)','标准差 (mg)','最小值 (mg)','最大值 (mg)']];
summary.getRange('A5:J14').values = summaries.map(s => [s.target,s.runs,s.pass,null,s.mean,s.bias,null,s.sd,s.min,s.max]);
summary.getRange('D5').formulas = [['=C5/B5']]; summary.getRange('D5:D14').fillDown();
summary.getRange('G5').formulas = [['=F5/A5']]; summary.getRange('G5:G14').fillDown();
summary.getRange('L4:M8').values = [
  ['总体指标','数值'],['正式测试总数',official.length],['总体合格数',official.filter(r=>r.pass).length],['总体合格率',null],['取消试跑数',cancelled.length]
];
summary.getRange('M7').formulas = [['=M6/M5']];
summary.getRange('A17').values = [['结论']];
summary.getRange('A18:J20').merge();
summary.getRange('A18').values = [['100 mg 表现最佳。200 mg 以上出现系统性偏高，500–900 mg 的平均偏差约为 +15 至 +18 mg，导致合格率明显下降。700 mg 的取消试跑已从正式统计中排除。']];

detail.getRange('A1:K1').values = [['目标质量 (mg)','运行编号','结果','最终质量 (mg)','偏差 (mg)','允许下限 (mg)','允许上限 (mg)','是否合格','实际时长 (s)','JSON 文件','说明']];
detail.getRange(`A2:K${official.length+1}`).values = official.map(r => [r.target,r.run,r.result,r.final,r.final-r.target,r.low,r.high,r.pass?'是':'否',r.duration,r.file,'正式测试']);
detail.getRange(`A${official.length+3}:K${official.length+3}`).values = [['取消记录','','','','','','','','','','见“异常记录”页']];

notes.getRange('A1:F1').values = [['记录类型','目标质量 (mg)','运行编号','JSON 文件','缺失/状态','处理']];
const noteRows = cancelled.map(r => ['多余取消试跑',r.target,r.run,r.file,'result=cancelled；final_mass=0；未生成 post_stop_samples.csv','已从正式统计排除；该条相关文件已删除']);
notes.getRange(`A2:F${Math.max(2,noteRows.length+1)}`).values = noteRows.length ? noteRows : [['无','','','','','']];
notes.getRange('A5:F7').merge();
notes.getRange('A5').values = [['已核对：正式 100 条记录均包含 JSON、samples.csv、post_stop_samples.csv。取消试跑在 server/logs 中也只有 JSON 和 samples.csv，没有可补回的 post_stop_samples.csv。']];

const headerFmt = { fill: '#1F4E78', font: { name:'Arial', size:10, bold:true, color:'#FFFFFF' }, horizontalAlignment:'center', verticalAlignment:'center', wrapText:true };
for (const [sh, range] of [[summary,'A4:J4'],[detail,'A1:K1'],[notes,'A1:F1'],[summary,'L4:M4']]) sh.getRange(range).format = headerFmt;
summary.getRange('A1:J1').format = { font:{name:'Arial',size:14,bold:true,color:'#1F2937'}, horizontalAlignment:'left' };
summary.getRange('A2:J2').format = { font:{name:'Arial',size:10,italic:true,color:'#6B7280'}, wrapText:true };
summary.getRange('A18:J20').format = { fill:'#F3F4F6', wrapText:true, verticalAlignment:'top' };
summary.getRange('A5:J14').format.borders = { preset:'all', style:'thin', color:'#D9E2F3' };
detail.getRange(`A1:K${official.length+1}`).format.borders = { preset:'all', style:'thin', color:'#D9E2F3' };
notes.getRange('A1:F3').format.borders = { preset:'all', style:'thin', color:'#D9E2F3' };
summary.getRange('A5:A14').format.numberFormat = '0'; summary.getRange('B5:C14').format.numberFormat='0'; summary.getRange('D5:D14').format.numberFormat='0.0%'; summary.getRange('E5:F14').format.numberFormat='0.0'; summary.getRange('G5:G14').format.numberFormat='0.00%'; summary.getRange('H5:J14').format.numberFormat='0.0';
summary.getRange('M7').format.numberFormat='0.0%';
detail.getRange(`A2:A${official.length+1}`).format.numberFormat='0'; detail.getRange(`D2:G${official.length+1}`).format.numberFormat='0.0'; detail.getRange(`I2:I${official.length+1}`).format.numberFormat='0.0';
for (const sh of [summary,detail,notes]) { sh.getUsedRange().format.verticalAlignment = 'center'; sh.getUsedRange().format.autofitColumns(); sh.getUsedRange().format.autofitRows(); }
summary.getRange('A:A').format.columnWidth = 16; summary.getRange('B:J').format.columnWidth = 14; summary.getRange('L:L').format.columnWidth = 18; summary.getRange('M:M').format.columnWidth = 14;
detail.getRange('B:B').format.columnWidth = 52; detail.getRange('J:J').format.columnWidth = 64; detail.getRange('K:K').format.columnWidth = 14; notes.getRange('C:C').format.columnWidth = 52; notes.getRange('D:D').format.columnWidth = 64; notes.getRange('E:F').format.columnWidth = 35;
summary.freezePanes.freezeRows(4); detail.freezePanes.freezeRows(1); notes.freezePanes.freezeRows(1);
summary.getRange('C5:C14').conditionalFormats.add('dataBar', { color:'#5B9BD5' });
detail.getRange(`H2:H${official.length+1}`).conditionalFormats.add('containsText', { text:'否', format:{ fill:'#FCE4D6', font:{color:'#9C0006',bold:true} } });

wb.recalculate();
const check = await wb.inspect({kind:'table', range:'总体汇总!A1:M14', include:'values,formulas', tableMaxRows:20, tableMaxCols:13, maxChars:8000});
await fs.writeFile(path.join(outDir,'inspect.ndjson'), check.ndjson ?? String(check));
const preview = await wb.render({sheetName:'总体汇总', autoCrop:'all', scale:1, format:'png'});
await fs.writeFile(path.join(outDir,'preview.png'), new Uint8Array(await preview.arrayBuffer()));
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(path.join(outDir,'batch_test_summary.xlsx'));
console.log(JSON.stringify({out:path.join(outDir,'batch_test_summary.xlsx'), official:official.length, cancelled:cancelled.length, pass:official.filter(r=>r.pass).length}, null, 2));
