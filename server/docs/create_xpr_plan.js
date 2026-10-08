const docx = require('docx');
const fs = require('fs');

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, BorderStyle, ShadingType,
  TableLayoutType, PageBreak, PageNumber, Header, Footer
} = docx;

const F = 'Microsoft YaHei';
const borderThin = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const cb = { top: borderThin, bottom: borderThin, left: borderThin, right: borderThin };

function hc(text, w) {
  return new TableCell({
    width: { size: w, type: WidthType.DXA }, borders: cb,
    shading: { type: ShadingType.CLEAR, fill: '2B579A' },
    children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text, bold: true, color: 'FFFFFF', font: F, size: 18 })] })]
  });
}
function dc(text, w) {
  let runs;
  if (Array.isArray(text)) {
    runs = text.flatMap((t, i) => i === 0 ? [new TextRun({ text: t, font: F, size: 18 })] :
      [new TextRun({ text: '\n', font: F, size: 18 }), new TextRun({ text: t, font: F, size: 18 })]);
  } else {
    runs = [new TextRun({ text, font: F, size: 18 })];
  }
  return new TableCell({ width: { size: w, type: WidthType.DXA }, borders: cb,
    children: [new Paragraph({ children: runs, spacing: { before: 30, after: 30 } })] });
}
function tbl(headers, rows, widths) {
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: widths, layout: TableLayoutType.FIXED,
    rows: [new TableRow({ children: headers.map((h, i) => hc(h, widths[i])) }),
      ...rows.map(r => new TableRow({ children: r.map((c, i) => dc(c, widths[i])) }))]
  });
}
function h1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 300, after: 120 },
  children: [new TextRun({ text: t, font: F, bold: true, size: 28, color: '1A3A6B' })] }); }
function h2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 80 },
  children: [new TextRun({ text: t, font: F, bold: true, size: 22, color: '2B579A' })] }); }
function p(t) { return new Paragraph({ spacing: { before: 60, after: 60 },
  children: [new TextRun({ text: t, font: F, size: 18 })] }); }
function b(t) { return new Paragraph({ spacing: { before: 30, after: 30 }, indent: { left: 480 },
  children: [new TextRun({ text: '• ' + t, font: F, size: 18 })] }); }
function sp() { return new Paragraph({ spacing: { before: 100, after: 0 }, children: [] }); }

const C = [];

// Title
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 },
  children: [new TextRun({ text: '梅特勒 XPR 系统分析借鉴计划', font: F, bold: true, size: 36, color: '1A3A6B' })] }));
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 300 },
  children: [new TextRun({ text: '基于 XPR204-AC · US20180178937A1 专利 · SLAS Technology 2026 论文\n项目：powder_sampling_control（LA10-D 振动加粉 + AT8811C 天平）', font: F, size: 16, color: '888888', italics: true })] }));

// ── 一 ──
C.push(h1('一、加粉头构型'));

C.push(h2('1.1 XPR 专利核心设计'));
C.push(tbl(['部件', '功能', '关键特征'],
  [['闭合部', '物理封死出口，零残留滴粉', '圆柱端面与圆形出口精密配合'],
   ['输送体/刮板', '旋转主动推粉 + 刮擦内壁自清洁', '一体成型于输送部上'],
   ['输送面', '低阻力粉末通道', '双曲率凹曲面，出料角 α=15°-25°'],
   ['轴向平移', '连续改变出口开度', '粗加大开口 → 精加小开口 → 关断密封']],
  [1800, 3200, 4000]));

C.push(sp());
C.push(h2('1.2 论文加粉头实测对比'));
C.push(tbl(['型号', '机制', '设计范围', '实测上限', '结论'],
  [['LNCT', '搅拌 + 垂直脉动', '1-8g', '自由流动 100g\n粘性 25-50g', '中量程首选'],
   ['LNLW', '仅搅拌', '0.2-1g', '效率低于 LNCT\n25g 以上常失败', '不适用于本项目场景'],
   ['SCN/SCL', '小剂量专用', 'mg 级', '论文未测试', '微量加粉专用']],
  [1400, 1800, 1200, 2000, 1600]));

C.push(sp());
C.push(h2('1.3 与你项目的差距'));
C.push(tbl(['维度', 'XPR Q3', 'LA10-D（你）', '影响'],
  [['输送', '旋转刮板主动推粉', '纯振动被动等粉', '粘性粉末不可用'],
   ['出口', '可变开度 + 物理关断', '无控制，始终全开', '残留滴粉无法消除'],
   ['破拱', '垂直脉动打散结拱', '无', '架桥时束手无策'],
   ['清洁', '刮板自清洁', '静态壁面，粉末累积', '长期运行恶化']],
  [1400, 2800, 2800, 2000]));

// ── 二 ──
C.push(new Paragraph({ children: [new PageBreak()] }));
C.push(h1('二、天平响应速度'));

C.push(tbl(['参数', 'XPR204/AC', 'AT8811C（你）', '影响'],
  [['可读性', '0.1 mg', '0.1 mg', '✅ 同级'],
   ['重复性', '0.04 mg', '待实测', '决定微量追加可行性'],
   ['稳定时间', '1.5 s', '待实测', '决定加粉循环频率上限'],
   ['校准', 'FACT 全自动', '手动触发', '需软件层补偿'],
   ['防静电', 'StaticDetect', '无', '粉末飞散的可能原因'],
   ['称盘', 'SmartGrid 减风阻', '标准', '振动环境表现待评估']],
  [2000, 2200, 2400, 2400]));

C.push(sp());
C.push(p('实测优先项：① AT8811C 不同负载下的稳定时间（Status bit 8 延迟）② 重复性（10 次同砝码）③ 振动运行时天平噪声水平'));

// ── 三 ──
C.push(h1('三、软件控制方法'));

C.push(h2('3.1 控制链路对比'));
C.push(p('XPR：PC → SOAP/TCP → 天平固件（内置完整加粉算法 + Active ML）→ Q3 模块'));
C.push(p('你：  PC → Modbus RTU → ESP32-S3 → AT8811C + LA10-D（所有逻辑在 PC 端）'));
C.push(p('结论：XPR 是黑盒调用，你是白盒自建——算法灵活但需从零实现。'));

C.push(sp());
C.push(h2('3.2 可借鉴：三层状态机'));
C.push(tbl(['阶段', '重量阈值', 'LA10 参数', '目的'],
  [['粗加', '0 → 75% 目标', '50-60Hz, 30-40% 占空比', '快速逼近'],
   ['精加', '75% → 95% 目标', '20-35Hz, 15-25% 占空比', '降速微调'],
   ['点动', '95% → 100% 目标', '10-15Hz, 10% 占空比, 0.1s 脉冲', '逐粒追加'],
   ['判定', '每段之间', '停止振动，等 stable', '超差 → 回到精加重试']],
  [1200, 1800, 3000, 2000]));

C.push(sp());
C.push(h2('3.3 可借鉴：异常检测'));
C.push(tbl(['异常', '检测方法', '处理'],
  [['架桥/堵塞', '重量 N 秒不增长（偏离线性曲线）', '触发高频脉动或电磁敲击'],
   ['粉末耗尽', '连续 M 周期增量 < 最低阈值', '报警 → 暂停 → 提示更换'],
   ['过冲', '重量 > 目标 + 公差', '记录 → 不追加 → 标记超差'],
   ['超时', '总时间 > 预设上限', '停止 → 记录当前结果']],
  [1600, 3400, 3200]));

// ── 四 ──
C.push(new Paragraph({ children: [new PageBreak()] }));
C.push(h1('四、加粉节奏'));

C.push(h2('4.1 论文实测数据（Tris + LNCT）'));
C.push(tbl(['目标量', '时间', '误差', '出粉速率'],
  [['5g', '26.7s', '0.32%', '187 mg/s'],
   ['25g', '110.0s', '1.18%', '227 mg/s'],
   ['50g', '192.3s', '0.52%', '260 mg/s'],
   ['100g', '377.3s', '0.31%', '265 mg/s']],
  [1600, 1600, 1600, 1600]));
C.push(p('规律：① 速率随目标量增大而趋近恒定（粗加占比增大）② 误差反而减小（精加影响相对变小）③ 可加粉粉末呈线性时间曲线——可做时间预估和异常检测'));

C.push(sp());
C.push(h2('4.2 XPR 四段节奏 → LA10 映射'));
C.push(tbl(['XPR 阶段', '时长占比', '机械动作', 'LA10 等效'],
  [['粗加', '~50%', '快转 + 大开口', '高频高占空比连续振动'],
   ['精加', '~35%', '慢转 + 小开口', '中低频中占空比连续振动'],
   ['稳定+判定', '~10%', '停一切，等读数', '停止振动，等 stable bit'],
   ['追加', '~5%', '最小开口单次脉冲', '最低频低占空比 × 0.1s 脉冲']],
  [1600, 1200, 2800, 3200]));

// ── 五 ──
C.push(h1('五、使用逻辑'));
C.push(tbl(['XPR 做法', '你的借鉴'],
  [['每种粉末专用加粉头，RFID 自动识别', '每种粉末独立漏斗 + 二维码贴纸\n扫码加载 JSON 参数文件'],
   ['RFID 每次加粉后自动更新余量', 'JSON 维护 remaining_mg，每次更新'],
   ['FACT 全自动内部校准', '软件层定期校准提醒 + 校准历史记录'],
   ['ErgoClip 多种容器适配器', '3D 打印目标容器转接件'],
   ['防风罩 + StaticDetect 防静电', '简易亚克力防风罩'],
   ['LabX + 21 CFR Part 11 数据合规', 'CSV 加粉日志（时间/粉末/目标/实际/误差）']],
  [3800, 5200]));

// ── 六 ──
C.push(new Paragraph({ children: [new PageBreak()] }));
C.push(h1('六、实施路线图'));

C.push(tbl(['阶段', '内容', '工作量', '依赖'],
  [['A. 实测摸底', '天平稳定时间 / LA10 出粉速率曲线\n至少 2 种粉末基准测试', '2-3 天', '—'],
   ['B. 三段式控制', '粗加→精加→点动状态机\n公差回环 + 异常处理', '3-5 天', 'A'],
   ['C. 线性监控', '时间-重量曲线记录\n偏离检测 + 报警', '1-2 天', 'A'],
   ['D. 粉末参数库', 'JSON 参数文件 + 二维码识别\n余量追踪 + 加粉日志', '2-3 天', 'A, B'],
   ['E. 硬件优化', 'PTFE 涂层漏斗 / 不同锥角 / 电磁敲击\n容器转接件 / 防风罩', '1-2 周', 'A'],
   ['F. 对标测试', '按论文方法：N 粉末 × 5 目标量 × 3 重复', '3-5 天', 'B, C, D']],
  [1600, 3600, 1400, 1000]));

C.push(sp());
C.push(p('核心 KPI：精度 <1%（自由流动）/ 时间 100mg <30s·500mg <60s / 架桥检测准确率 >90%'));

// ── 七 ──
C.push(new Paragraph({ children: [new PageBreak()] }));
C.push(h1('七、与本项目的核心差异'));

C.push(tbl(['维度', 'XPR 系统', '本项目', '差距性质'],
  [['输送', '旋转刮板主动推送', '振动 + 重力被动', '根本性——决定粉末适应性上限'],
   ['关断', '轴向平移物理密封', '停止振动，残留滴粉', '结构性——无法纯软件补偿'],
   ['破拱', '垂直脉动 + 刮板', '无', '机械性——LA10 纯水平振动无效'],
   ['清洁', '刮板自清洁', '静态壁面', '维护性——长期运行恶化'],
   ['算法', '内置固件 + Active ML', 'PC 端自研', '灵活性——白盒可控但需自建'],
   ['校准', 'FACT 全自动', '手动/软件触发', '运维性——需软件层管理'],
   ['粉末识别', 'RFID 自动', '人工/二维码', '便利性——可低成本替代'],
   ['数据', 'LabX + 21 CFR Part 11', '自研 CSV 日志', '合规性——工业场景需补']],
  [1600, 2600, 2600, 2200]));

C.push(sp());
C.push(p('根本结论：差距不在软件，在加粉头的机械设计。XPR 是"主动控制"（粉末行为由机械动作决定），LA10 是"被动引导"（粉末行为由自身特性决定）。软件策略可以补偿但不能消除机械差距。'));

// ── 八 ──
C.push(h1('八、可借鉴内容汇总'));
C.push(p('按可实现性排序。"投入"含开发+测试。'));

C.push(sp());
C.push(h2('纯软件（零硬件改动，立即可做）'));
C.push(tbl(['#', '内容', '来源', '投入', '效果'],
  [['S1', '三段式变速加粉', 'XPR 固件', '3-5天', '精度直接提升，减少过冲'],
   ['S2', '公差回环（超差自动追加）', 'XPR + sample_new 多段加液', '1天', '一次成功率提高'],
   ['S3', '线性曲线监控（偏离=报警）', '论文 Fig 2', '1-2天', '首次实现堵塞自动检测'],
   ['S4', '粉末参数 JSON + 二维码', 'XPR RFID', '2-3天', '消除人工选参错误'],
   ['S5', '余量自动追踪', 'XPR RFID', '1天', '防止中途断粉'],
   ['S6', '加粉日志 CSV', 'LabX', '0.5天', '数据可追溯']],
  [600, 2400, 2400, 1000, 2400]));

C.push(sp());
C.push(h2('低成本硬件（近期可实施）'));
C.push(tbl(['#', '内容', '来源', '投入', '效果'],
  [['H1', 'PTFE 涂层漏斗', '论文：KCl 壁面附着', '1天', '减少粘壁'],
   ['H2', '电磁敲击破拱', '论文 Fig 3 + LNCT 脉动', '3天', '解决结拱'],
   ['H3', '3D 打印不同锥角漏斗', '专利 15-25° 出料角', '2天', '匹配粉末流动特性'],
   ['H4', '简易防风罩', 'XPR 防风罩', '0.5天', '读数稳定'],
   ['H5', '容器转接件', 'XPR ErgoClip', '1天', '减少飞溅']],
  [600, 2400, 2400, 1000, 2400]));

C.push(sp());
C.push(h2('方法论（同步进行）'));
C.push(tbl(['#', '内容', '来源', '说明'],
  [['M1', '实证测试优先', '论文核心发现：参数无法预测，必须实测', '每种新粉末上线前实测验证'],
   ['M2', '粉末分类体系', '论文：自由流动 vs 粘性两大类', '与粉末特征码设计衔接'],
   ['M3', '一种粉末一个漏斗', '论文 + XPR', '零交叉污染，参数不混淆']],
  [600, 2400, 2400, 3600]));

C.push(sp());
C.push(h2('长期方向（结构性改造）'));
C.push(tbl(['#', '内容', '思路', '价值'],
  [['L1', '旋转刮板', '漏斗内加步进电机驱动刮板', '根本解决被动出粉'],
   ['L2', '机械快门', '出口下方电磁铁挡片', '物理关断，消除残留滴粉'],
   ['L3', '可变出口', '舵机控制可调孔径', '出粉速率范围扩大数倍']],
  [600, 1600, 4000, 2800]));

C.push(sp());
C.push(p('实施原则：先软件后硬件，先低成本后结构性，先实测后决策。S1-S6 + M1-M3 总计约 8-12 天，全部可立即启动。'));

C.push(sp());
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200 },
  children: [new TextRun({ text: '— 完 —', font: F, size: 16, color: 'AAAAAA', italics: true })] }));

// ── build ──
const doc = new Document({
  styles: { default: { document: { run: { font: F, size: 18 }, paragraph: { spacing: { line: 260 } } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1000, bottom: 900, left: 1000, right: 1000 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: 'XPR 分析借鉴计划', font: F, size: 14, color: 'BBBBBB', italics: true })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: '第 ', font: F, size: 14, color: '999999' }),
        new TextRun({ children: [PageNumber.CURRENT], font: F, size: 14, color: '999999' }),
        new TextRun({ text: ' 页', font: F, size: 14, color: '999999' })] })] }) },
    children: C
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('c:/Users/22371/Downloads/出粉/powder_sampling_control/powder_sampling_control/docs/XPR分析借鉴计划.docx', buf);
  console.log('OK');
});
