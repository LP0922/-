const docx = require('docx');
const fs = require('fs');

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, BorderStyle, ShadingType,
  TableLayoutType, PageNumber, Header, Footer
} = docx;

const F = 'Microsoft YaHei';
const bd = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const cb = { top: bd, bottom: bd, left: bd, right: bd };

function hc(t, w) { return new TableCell({ width: { size: w, type: WidthType.DXA }, borders: cb,
  shading: { type: ShadingType.CLEAR, fill: '2B579A' },
  children: [new Paragraph({ alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: t, bold: true, color: 'FFFFFF', font: F, size: 18 })] })] }); }
function dc(t, w) {
  const arr = Array.isArray(t) ? t : [t];
  const runs = arr.flatMap((s, i) => i === 0 ? [new TextRun({ text: s, font: F, size: 18 })] :
    [new TextRun({ text: '\n', font: F, size: 18 }), new TextRun({ text: s, font: F, size: 18 })]);
  return new TableCell({ width: { size: w, type: WidthType.DXA }, borders: cb,
    children: [new Paragraph({ children: runs, spacing: { before: 30, after: 30 } })] }); }
function tbl(headers, rows, widths) {
  return new Table({ width: { size: widths.reduce((a,b)=>a+b,0), type: WidthType.DXA },
    columnWidths: widths, layout: TableLayoutType.FIXED,
    rows: [new TableRow({ children: headers.map((h,i) => hc(h, widths[i])) }),
      ...rows.map(r => new TableRow({ children: r.map((c,i) => dc(c, widths[i])) }))] }); }
function h1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 280, after: 100 },
  children: [new TextRun({ text: t, font: F, bold: true, size: 28, color: '1A3A6B' })] }); }
function h2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 200, after: 80 },
  children: [new TextRun({ text: t, font: F, bold: true, size: 22, color: '2B579A' })] }); }
function h3(t) { return new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 150, after: 60 },
  children: [new TextRun({ text: t, font: F, bold: true, size: 20, color: '3A6B8A' })] }); }
function p(t) { return new Paragraph({ spacing: { before: 50, after: 50 },
  children: [new TextRun({ text: t, font: F, size: 18 })] }); }
function b(t) { return new Paragraph({ spacing: { before: 25, after: 25 }, indent: { left: 480 },
  children: [new TextRun({ text: '• ' + t, font: F, size: 18 })] }); }
function sp() { return new Paragraph({ spacing: { before: 80, after: 0 }, children: [] }); }
function code(t) { return new Paragraph({ spacing: { before: 50, after: 50 }, indent: { left: 480 },
  children: [new TextRun({ text: t, font: 'Consolas', size: 16, color: '333333' })] }); }

const C = [];

// Title
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
  children: [new TextRun({ text: '粉末自动装样设备', font: F, bold: true, size: 36, color: '1A3A6B' })] }));
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: '阶段1-2详细研发方案（3周）', font: F, bold: true, size: 28, color: '2B579A' })] }));
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [new TextRun({ text: '2026-08-12 至 2026-08-30（15个工作日）', font: F, size: 20, color: '666666' })] }));

C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
  children: [new TextRun({ text: '核心目标：建立设备/粉体表征体系 + 4种参考粉工作空间 + 方法生成器v0', font: F, size: 18, color: '888888', italics: true })] }));

// 一、总体架构确认
C.push(h1('一、总体架构确认'));

C.push(h2('1.1 系统分层'));

C.push(p('本方案基于开放式工作空间库架构，不推倒现有Preset体系，而是在其上叠加粉体特征匹配层：'));

C.push(code('粉体工作空间库（powder_library/）'));
C.push(code('  ├─ 熟石灰.json (Low-flow + 高卡粉)'));
C.push(code('  ├─ 膨润土.json (Medium-flow + 稳定)'));
C.push(code('  ├─ 小苏打.json (High-flow + 易溢)'));
C.push(code('  ├─ 玉米淀粉.json (Ultra-low + 高启动阈值)'));
C.push(code('  └─ 未来客户粉.json ...'));
C.push(sp());
C.push(code('        ↓ 新粉匹配（特征向量KNN）'));
C.push(sp());
C.push(code('方法生成器 (dosing_method_generator.py)'));
C.push(code('  输入: 粉体特征 + 目标质量'));
C.push(code('  输出: preset_id + profile + 控制器参数'));
C.push(sp());
C.push(code('        ↓ 推荐参数'));
C.push(sp());
C.push(code('Preset层 (DISPENSE_PRESETS) - 已有，叠加筛选'));
C.push(sp());
C.push(code('        ↓ 具体执行'));
C.push(sp());
C.push(code('控制器层 (ContinuousFeedbackController)'));
C.push(sp());
C.push(code('        ↓ 硬件指令'));
C.push(sp());
C.push(code('执行器层 (LA10 + AT8811C)'));
C.push(code('  四控制变量: 频率 / 占空比 / 窗口 / 振幅'));

C.push(sp());
C.push(h2('1.2 核心设计决策'));

C.push(tbl(['决策点', '方案'],
  [['振幅控制', '通过LA10新寄存器实现（D1调研确认）'],
   ['工作空间定位', '叠加在preset之上做筛选，不推倒现有体系'],
   ['参考粉数量', '4种（熟石灰/膨润土/小苏打/淀粉），覆盖4种失效模式'],
   ['分类体系', '开放式工作空间库，不强制三分类，新粉通过相似度匹配'],
   ['表征策略', '复用已有数据，增量补测缺失部分']],
  [2400, 6800]));

// 二、第1周
C.push(sp());
C.push(h1('二、第1周：设备表征 + Bug修复（D1-D5）'));

C.push(h2('D1（8月12日）：振幅控制能力调研'));

C.push(h3('目标'));
C.push(p('确认LA10-D是否支持振幅/驱动强度软件控制，明确寄存器地址和协议。'));

C.push(h3('执行步骤'));
C.push(b('查阅LA10-D完整技术文档（ESP32-S3网关 + LA10执行器），搜索关键词：amplitude、drive、voltage、VRMS、power level'));
C.push(b('联系供应商技术支持，询问是否存在独立的振幅控制寄存器、调节范围和单位、与频率/占空比的交互关系'));
C.push(b('如果确认存在，在la10_modbus_rtu.py临时添加读写测试代码，固定频率40Hz/占空比20%，扫描振幅0-100%，观察流速变化'));

C.push(h3('预期产出'));
C.push(b('✅ 振幅可控 → 产出《LA10振幅寄存器规格》文档（寄存器地址、范围、单位）'));
C.push(b('❌ 振幅不可控 → 产出《振幅控制降级方案》（振幅暂不纳入四控制变量，标注为硬件约束）'));

C.push(h3('风险'));
C.push(p('如果振幅不可控，PDF方案里"高振幅启动+低振幅维持"策略无法实施，需调整为"高频启动+低频维持"替代方案。'));

C.push(sp());
C.push(h2('D2（8月13日）：已知Bug修复'));

C.push(h3('目标'));
C.push(p('修复影响表征数据质量的三个bug。'));

C.push(h3('Bug清单'));

C.push(p('Bug 1: force_continue_min_mass_mg = 0 导致堵转检测失效'));
C.push(b('位置：feedback_controller.py 第269-295行'));
C.push(b('问题：force_continue_min_mass_mg = 0 → stall检测条件 mass < 0 永远不满足'));
C.push(b('修复：在FeedbackControllerSettings.__post_init__()增加校验，要求 0 < force_continue < force_stop'));

C.push(sp());
C.push(p('Bug 2: cross_set_summary引用未定义变量'));
C.push(b('位置：device_control_server.py _run_dispense_batch()'));
C.push(b('问题：target_mg 变量在cross_set_summary计算时未定义'));
C.push(b('修复：从batch payload提取target_mg并传入summary计算'));

C.push(sp());
C.push(p('Bug 3: CV计算始终为0%（已于2026-08-06修复，回归测试）'));
C.push(b('位置：device_control_server.py _run_constant_rate_test()'));
C.push(b('状态：已修复，改为汇总所有原始rate_mg_s计算CV'));
C.push(b('任务：用今天(0812)5个新日志文件验证CV不再为0'));

C.push(h3('预期产出'));
C.push(b('3个bug修复的PR，各自带回归测试'));
C.push(b('CV验证报告（对比修复前后的logs）'));

C.push(sp());
C.push(h2('D3-D4（8月14-15日）：窗口零点/行程/回差表征'));

C.push(h3('目标'));
C.push(p('量化窗口执行器的机械特性，为工作空间中"窗口"维度提供边界。'));

C.push(h3('实验设计'));

C.push(tbl(['实验组', '窗口指令序列', '测量指标'],
  [['往返精度', '100→500→100 重复10次', '到位误差、重复性标准差'],
   ['回差测试', '100→500(正向) vs 500→100(反向) 到同一目标300', '正反向到位差'],
   ['分辨率', '250→251→252... 单步进', '最小可分辨步距'],
   ['行程极限', '0→最大值（直到堵转或到限位）', '安全行程范围']],
  [2000, 3400, 3800]));

C.push(h3('执行方式'));
C.push(b('使用现有move_relative()接口 + wait_until_stopped()'));
C.push(b('记录每次指令的LA10Status.position_units和last_result'));
C.push(b('不加粉，纯机械测试'));

C.push(h3('预期产出'));
C.push(b('《窗口执行器表征报告》（到位精度±X units、回差Y units、安全行程0-800 units）'));
C.push(b('数据写入data/characterization/window_characterization.json'));

C.push(sp());
C.push(h2('D5（8月16日）：启动/停止/参数切换动态响应表征'));

C.push(h3('目标'));
C.push(p('测量指令发出到实际生效的延迟和抖动。'));

C.push(h3('实验清单'));

C.push(p('实验1：振动启停响应'));
C.push(b('发送start_vibration(40Hz, 2000) → 记录is_running=True的时刻 → 延迟1'));
C.push(b('发送stop_vibration() → 记录is_running=False的时刻 → 延迟2'));
C.push(b('重复20次，计算均值±标准差'));

C.push(sp());
C.push(p('实验2：频率热切换'));
C.push(b('振动中从40Hz切换到60Hz（update_vibration_frequency(60)）'));
C.push(b('通过定速出粉测试观察流速何时变化（需要天平数据辅助判断）'));
C.push(b('估算参数生效延迟'));

C.push(sp());
C.push(p('实验3：占空比热切换'));
C.push(b('振动中从20%切换到30%（update_vibration_duty(3000)）'));
C.push(b('同样通过流速变化判断生效时刻'));

C.push(h3('预期产出'));
C.push(b('《动态响应表征报告》（启动延迟<200ms、停止延迟<100ms、参数切换延迟<500ms）'));
C.push(b('结论写入data/characterization/dynamic_response.json'));

// 三、第2周
C.push(sp());
C.push(h1('三、第2周：4种参考粉工作空间建立（D6-D10）'));

C.push(h2('D6（8月19日）：淀粉补测方案设计 + 历史数据分析'));

C.push(h3('任务1：分析现有淀粉数据'));
C.push(b('读取logs里所有starch-70hz-p200的测试文件（~20次100mg闭环加粉）'));
C.push(b('提取：平均加粉时长、停机前稳态流速、最终质量误差分布、通过率'));
C.push(b('反推70Hz/20%/窗100下淀粉的稳态流速（估算值）'));

C.push(h3('任务2：设计淀粉扫描实验'));
C.push(p('目标：确定淀粉的"可靠启动频率下限"和"稳定工作区间"。'));

C.push(tbl(['频率(Hz)', '占空比(%)', '窗口(units)', '时长(s)', '重复次数'],
  [['50', '20', '250', '15', '1 (验证是否启动)'],
   ['55', '20', '250', '15', '3'],
   ['60', '20', '250', '15', '3'],
   ['65', '20', '250', '15', '3'],
   ['70', '20', '250', '15', '3'],
   ['75', '20', '250', '15', '3'],
   ['70', '16', '250', '15', '3'],
   ['70', '24', '250', '15', '3']],
  [1400, 1600, 1800, 1400, 2000]));

C.push(p('共22组测试，预计耗时：22 × 15s + 间隔 ≈ 8-10分钟。使用批量队列自动执行。'));

C.push(h3('预期产出'));
C.push(b('淀粉历史数据分析报告（70Hz下估算流速、通过率）'));
C.push(b('淀粉扫描实验配置JSON（供D7批量执行）'));

C.push(sp());
C.push(h2('D7（8月20日）：执行淀粉扫描实验'));

C.push(h3('执行步骤'));
C.push(b('准备淀粉样品（足量，至少50g）'));
C.push(b('天平标零'));
C.push(b('加载D6设计的批量队列配置'));
C.push(b('启动批量测试，监控：是否出粉（50Hz组）、流速稳定性（其他组的CV）、是否有超速/堵塞'));
C.push(b('实时记录异常（如果某频点明显不稳定，可手动中止该组）'));

C.push(h3('数据处理'));
C.push(b('读取所有测试的JSON日志'));
C.push(b('对每个(频率, 占空比)组合计算：平均流速、CV、启动延迟、是否有断流'));
C.push(b('绘制工作空间热图：X轴频率，Y轴占空比，颜色表示CV'));

C.push(h3('预期产出'));
C.push(b('淀粉定速测试原始日志（~22个JSON文件）'));
C.push(b('淀粉工作空间初稿JSON文件'));

C.push(sp());
C.push(h2('D8（8月21日）：熟石灰 + 膨润土多点扫描'));

C.push(h3('熟石灰扫描'));

C.push(tbl(['频率', '占空比', '窗口', '时长', '重复'],
  [['40', '20', '250', '20', '3'],
   ['40', '16', '250', '20', '3'],
   ['55', '20', '250', '20', '3'],
   ['55', '16', '250', '20', '3'],
   ['65', '20', '250', '20', '3'],
   ['65', '16', '250', '20', '3']],
  [1400, 1600, 1400, 1400, 1400]));

C.push(p('共18组，预计30分钟。'));

C.push(h3('膨润土扫描'));
C.push(p('参数同上。已有40Hz/20%单点数据（35.5 mg/s, CV 24.3%），补测55Hz、65Hz。'));

C.push(h3('预期产出'));
C.push(b('data/powder_library/熟石灰.json'));
C.push(b('data/powder_library/膨润土.json'));

C.push(sp());
C.push(h2('D9（8月22日）：小苏打低频扫描'));

C.push(h3('目标'));
C.push(p('验证小苏打能否在低频下稳定控制在Medium-flow区间（30-60 mg/s）。'));

C.push(h3('扫描参数'));

C.push(tbl(['频率', '占空比', '窗口', '时长', '重复', '预期流速'],
  [['15', '10', '250', '20', '3', '~20 mg/s?'],
   ['20', '10', '250', '20', '3', '~40 mg/s?'],
   ['25', '10', '250', '20', '3', '~60 mg/s?'],
   ['30', '10', '250', '20', '3', '~80 mg/s?'],
   ['20', '12', '250', '20', '3', '验证占空比影响'],
   ['25', '12', '250', '20', '3', '验证占空比影响']],
  [1200, 1600, 1400, 1400, 1200, 2400]));

C.push(p('共18组，预计30分钟。'));

C.push(h3('关键验证'));
C.push(b('小苏打在40Hz/20%下流速119 mg/s（High-flow）'));
C.push(b('如果15-25Hz能稳定在30-60 mg/s且CV<30%，说明可以通过降频控制'));
C.push(b('如果仍然>80 mg/s或CV>40%，说明小苏打天生就是High-flow，无法降到Medium'));

C.push(h3('预期产出'));
C.push(b('data/powder_library/小苏打.json'));
C.push(b('结论：小苏打的"可控下限"是多少Hz'));

C.push(sp());
C.push(h2('D10（8月23日）：方法生成器v0骨架搭建'));

C.push(h3('目标'));
C.push(p('实现从粉体特征到参数推荐的自动映射。'));

C.push(h3('新建文件'));
C.push(p('src/powder_sampling_control/dispensing_algorithm/dosing_method_generator.py'));

C.push(h3('核心函数'));

C.push(code('def generate_dispense_method('));
C.push(code('    powder_feature_vector: dict,'));
C.push(code('    target_mass_mg: int,'));
C.push(code('    powder_library_path: str = "data/powder_library"'));
C.push(code(') -> dict:'));
C.push(code('    """'));
C.push(code('    输入：粉体特征 + 目标质量'));
C.push(code('    输出：{preset_id, profile, controller_settings, observer_settings}'));
C.push(code('    '));
C.push(code('    算法：'));
C.push(code('    1. 加载powder_library/下所有参考粉的工作空间'));
C.push(code('    2. 计算新粉特征向量与每个参考粉的欧氏距离'));
C.push(code('    3. 找最近的k=2个参考粉'));
C.push(code('    4. 加权平均它们的推荐参数（权重=1/距离）'));
C.push(code('    5. 用interpolate_profile(target_mass_mg)生成profile'));
C.push(code('    6. 返回完整方法'));
C.push(code('    """'));

C.push(h3('V0简化'));
C.push(b('只实现KNN匹配 + 参数继承，不做优化'));
C.push(b('匹配结果直接返回最近邻的preset_id和控制器参数'));
C.push(b('Profile仍使用现有的interpolate_profile()'));

C.push(h3('集成到前端'));
C.push(b('粉末指纹探针完成后，自动调用generate_dispense_method()'));
C.push(b('推荐参数显示在UI上，用户可接受或手动调整'));

C.push(h3('预期产出'));
C.push(b('dosing_method_generator.py（~200行）'));
C.push(b('单元测试：用已知的小苏打特征向量，验证匹配到"小苏打"参考粉'));
C.push(b('集成测试：跑一次完整的探针→匹配→加粉流程'));

// 四、第3周
C.push(sp());
C.push(h1('四、第3周：验证 + 收尾（D11-D15）'));

C.push(h2('D11-D12（8月26-27日）：4种参考粉闭环加粉验证'));

C.push(h3('目标'));
C.push(p('验证方法生成器v0推荐的参数是否比手工调参更好。'));

C.push(h3('实验设计'));

C.push(tbl(['粉体', '目标质量', '参数来源', '重复次数'],
  [['熟石灰', '100mg', '方法生成器推荐', '5'],
   ['熟石灰', '300mg', '方法生成器推荐', '5'],
   ['膨润土', '100mg', '方法生成器推荐', '5'],
   ['膨润土', '300mg', '方法生成器推荐', '5'],
   ['小苏打', '100mg', '方法生成器推荐', '5'],
   ['小苏打', '300mg', '方法生成器推荐', '5'],
   ['淀粉', '100mg', '方法生成器推荐', '5'],
   ['淀粉', '300mg', '方法生成器推荐', '5']],
  [1800, 1800, 2000, 2600]));

C.push(p('共40次测试，预计每次3-5分钟，总耗时3-4小时（两天完成）。'));

C.push(h3('对比基线'));
C.push(b('上阶段数据（100mg高通过率、300mg 33%、500mg 43%）'));
C.push(b('现有固定preset（slow-40hz-p250、slow-60hz-p250等）'));

C.push(h3('数据分析'));
C.push(b('通过率（90-110mg为通过）'));
C.push(b('平均误差'));
C.push(b('标准差'));
C.push(b('加粉时长'));

C.push(h3('预期产出'));
C.push(b('《4种参考粉验证报告》'));
C.push(b('结论：方法生成器v0是否比固定preset更优（预期至少持平或略优5-10%）'));

C.push(sp());
C.push(h2('D13（8月28日）：重复性验证 + CV修复回归测试'));

C.push(h3('任务1：同参数重复性测试'));
C.push(b('选1种粉（膨润土，最稳定）'));
C.push(b('固定参数：60Hz/20%/窗250'));
C.push(b('连续跑10次定速测试（每次20秒）'));
C.push(b('计算10次结果的：流速均值的标准差（反映系统噪声）、每次内部CV（反映单次波动）'));

C.push(h3('任务2：CV计算修复验证'));
C.push(b('从logs/读取修复前（0806之前）和修复后（0806之后）的定速测试日志'));
C.push(b('统计overall_cv_pct字段：修复前应该大部分为0.0或None，修复后应该有合理分布（10%-50%）'));
C.push(b('生成对比图表'));

C.push(h3('预期产出'));
C.push(b('《重复性表征报告》（同参数10次流速标准差<5 mg/s）'));
C.push(b('《CV修复验证报告》（修复后CV不再为0）'));

C.push(sp());
C.push(h2('D14（8月29日）：阶段总结报告 + 六项验收能力清单'));

C.push(h3('产出1：《阶段1-2总结报告》'));

C.push(p('包含以下章节：'));
C.push(b('设备表征结果：振幅控制能力、窗口执行器特性、动态响应特性'));
C.push(b('4种参考粉工作空间：熟石灰（Low-flow）、膨润土（Medium-flow）、小苏打（High-flow）、淀粉（Ultra-low-flow）'));
C.push(b('方法生成器v0：架构、验证结果'));
C.push(b('Bug修复记录：force_continue堵转检测、cross_set_summary、CV计算'));

C.push(h3('产出2：《六项验收能力清单》'));

C.push(p('对照PDF方案第11页的要求：'));

C.push(tbl(['验收项', '完成度', '证据'],
  [['1. 四控制变量软件可控可记录', '100%（振幅待确认）', 'la10_modbus_rtu.py扩展 + 日志记录'],
   ['2. 确定参考设备/头/标准粉', '100%', '4种参考粉档案'],
   ['3. 自动实验调度器', '80%', '批量队列可用，但无DOE/BO优化'],
   ['4. 建立代表粉工作空间', '100%', 'powder_library/下4份完整档案'],
   ['5. 方法生成器100/300/500mg', '70%', 'v0可用但未优化，500mg未验证'],
   ['6. 多设备迁移验证', '0%', '排期到下一阶段（需要第二台设备）']],
  [3800, 2000, 3400]));

C.push(sp());
C.push(h2('D15（8月30日）：缓冲日 + 文档整理'));

C.push(h3('任务'));
C.push(b('处理D11-D14发现的遗留问题'));
C.push(b('补充代码注释和README'));
C.push(b('整理powder_library/目录结构'));
C.push(b('准备下阶段规划草案（多设备迁移 + 方法优化）'));

// 五、关键里程碑与交付物
C.push(sp());
C.push(h1('五、关键里程碑与交付物'));

C.push(tbl(['里程碑', '日期', '交付物'],
  [['M1: 设备表征完成', 'D5 (8/16)', '振幅调研结论 + 窗口表征 + 动态响应报告 + 3个bug修复'],
   ['M2: 工作空间建立', 'D9 (8/22)', '4种参考粉的powder_library档案'],
   ['M3: 方法生成器上线', 'D10 (8/23)', 'dosing_method_generator.py + 集成测试通过'],
   ['M4: 验证完成', 'D13 (8/28)', '40次闭环加粉验证报告 + CV/重复性验证'],
   ['M5: 阶段总结', 'D14 (8/29)', '阶段1-2总结报告 + 六项验收清单']],
  [2600, 1800, 4800]));

// 六、风险与应对
C.push(sp());
C.push(h1('六、风险与应对'));

C.push(tbl(['风险', '概率', '影响', '应对方案'],
  [['振幅不可控', '中', '高', '降级为三控制变量，用"高频启动"替代"高振幅启动"'],
   ['淀粉55Hz仍无响应', '低', '中', '扩大扫描范围到80-90Hz，或标记为"不可控粉体"'],
   ['方法生成器推荐参数不如手工', '中', '低', 'v0是baseline，下阶段迭代DOE/BO优化'],
   ['D11-D12验证耗时超预期', '高', '低', '减少重复次数从5→3，或延用到D15缓冲日'],
   ['第二台设备未到货', '高', '高', '阶段3多设备迁移推迟，改为方法优化+新粉扩充']],
  [2800, 800, 800, 4800]));

// 七、下阶段预留问题
C.push(sp());
C.push(h1('七、下阶段预留问题（不在本3周范围）'));

C.push(b('DOE/BO优化：当前方法生成器只做KNN匹配，未实现PDF里的"试验设计+贝叶斯优化"'));
C.push(b('多设备迁移验证：需要第二台设备（阶段3核心目标）'));
C.push(b('ILC跨任务学习：PDF提到的"历史学习+漂移检测"'));
C.push(b('加速度计/IMU：PDF明确留作专项研究，不强制加入'));
C.push(b('粉体物理性质测试：休止角、堆密度、粒径分布等（需要额外测试设备）'));

C.push(sp());
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200 },
  children: [new TextRun({ text: '— 完 —', font: F, size: 16, color: 'AAAAAA', italics: true })] }));

// build document
const doc = new Document({
  styles: { default: { document: { run: { font: F, size: 18 }, paragraph: { spacing: { line: 260 } } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1000, bottom: 900, left: 1000, right: 1000 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: '阶段1-2详细研发方案', font: F, size: 14, color: 'BBBBBB', italics: true })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: '第 ', font: F, size: 14, color: '999999' }),
        new TextRun({ children: [PageNumber.CURRENT], font: F, size: 14, color: '999999' }),
        new TextRun({ text: ' 页', font: F, size: 14, color: '999999' })] })] }) },
    children: C
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('docs/阶段1-2详细研发方案_3周.docx', buf);
  console.log('OK');
});
