const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, ShadingType,
  PageBreak, LevelFormat, Header, Footer, PageNumber
} = require("docx");

// ── Helpers ──────────────────────────────────────────────────────
const F = "Microsoft YaHei";
const S = 21, SS = 18, ST = 16;

function H(text, lv = HeadingLevel.HEADING_1) {
  return new Paragraph({ heading: lv, children: [new TextRun({ text, font: F })] });
}
function P(text, opts = {}) {
  const c = [new TextRun({ text, font: F, size: opts.size || S, bold: !!opts.bold, color: opts.color })];
  return new Paragraph({ spacing: { after: 100 }, alignment: opts.align, children: c });
}
function B(text) { return P(text, { bold: true }); }
function E() { return new Paragraph({ spacing: { after: 60 }, children: [] }); }
function Bul(text) {
  return new Paragraph({
    spacing: { after: 40 }, bullet: { level: 0 }, indent: { left: 720 },
    children: [new TextRun({ text, font: F, size: S })]
  });
}

function C(text, opts = {}) {
  const lines = Array.isArray(text) ? text : [text];
  return new TableCell({
    width: opts.w ? { size: opts.w, type: WidthType.DXA } : undefined,
    shading: opts.s ? { fill: opts.s, type: ShadingType.CLEAR } : undefined,
    verticalAlign: "center",
    children: lines.map(t => new Paragraph({
      children: [new TextRun({ text: String(t ?? ""), font: F, size: SS, bold: !!opts.bold })]
    }))
  });
}
function HC(text, w) { return C(text, { bold: true, s: "D9E2F3", w }); }

function T(headers, rows, widths) {
  const tw = widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: tw, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ children: headers.map((h, i) => HC(h, widths[i])) }),
      ...rows.map(row => new TableRow({ children: row.map((c, i) => C(c, { w: widths[i] })) }))
    ]
  });
}

function BR() { return new Paragraph({ children: [new PageBreak()] }); }

// ── Section wrapper: auto-push helpers inside section callbacks ──
const children = [];
let _sectionDepth = 0;

function section(title, lv, fn) {
  const isL1 = (lv === HeadingLevel.HEADING_1);
  children.push(isL1 ? BR() : E(), H(title, lv));

  _sectionDepth++;
  if (_sectionDepth === 1) {
    // Wrap P/B/E/Bul/T so they auto-push to children.
    // B calls rawP directly (not wrapped P) to avoid double-push.
    const _P = P, _B = B, _E = E, _Bul = Bul, _T = T;
    P = function(text, opts) { const r = _P(text, opts); children.push(r); return r; };
    B = function(text) { const r = _P(text, { bold: true }); children.push(r); return r; };
    E = function() { const r = _E(); children.push(r); return r; };
    Bul = function(text) { const r = _Bul(text); children.push(r); return r; };
    T = function(h, r, w) { const t = _T(h, r, w); children.push(t); return t; };
    fn();
    P = _P; B = _B; E = _E; Bul = _Bul; T = _T;
  } else {
    fn();
  }
  _sectionDepth--;
}
// ──────────────────────────────────────────────────────────────────

// ═══════════════════════ TITLE PAGE ══════════════════════════════
for (let i = 0; i < 6; i++) children.push(E());
children.push(
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 200 },
    children: [new TextRun({ text: "粉末自动装样设备", font: F, size: 48, bold: true, color: "1F3864" })]
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 300 },
    children: [new TextRun({ text: "下一阶段研发方案", font: F, size: 40, bold: true, color: "2E75B6" })]
  }),
  E(), E(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "设备表征 + 开放式粉体工作空间 + 自动方法生成 + 闭环验证", font: F, size: 22, color: "555555" })]
  }),
  E(), E(), E(), E(),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "2026年8月12日", font: F, size: 24, color: "333333" })]
  })
);

// ═══════════════════════ 目录 ════════════════════════════════════
children.push(BR());
section("目  录", HeadingLevel.HEADING_1, () => {
  const toc = [
    "一、总体技术路线",
    "二、设备物理特性摸底实验",
    "三、开放式粉体工作空间设计",
    "四、已有代码资产与合并",
    "五、三周开发详细计划",
    "六、人工测试操作指南（预案）",
    "七、关键风险与里程碑",
  ];
  toc.forEach(t => { P(t); E(); });
});

// ═══════════════════════ 一、总体技术路线 ════════════════════════
section("一、总体技术路线", HeadingLevel.HEADING_1, () => {

  P("本方案的核心思路是：先搞清楚设备本身的物理行为（设备表征），再建立可扩展的粉末知识体系（开放式粉体工作空间），然后用规则+优化的方式自动生成加粉方法，最后通过闭环控制验证执行。整个过程不是一次性建设，而是渐进积累——每增加一种新粉末，知识库就丰富一分。");

  E();
  B("总体链路：");
  E();

  T(
    ["阶段", "核心内容", "产出", "耗时"],
    [
      ["设备表征", "系统扫描频率/占空比/窗口\n建立参数→流量→稳定性映射", "工作空间粗图\n调参决策树", "半天"],
      ["标准粉建档", "对4种代表性粉末执行\n启流+稳态+尾量实验", "4份粉体特性档案", "2周"],
      ["新粉快速接入", "跑探针→提取特征→\n最近邻匹配→继承参数→微调", "新粉可用预设\n自动入库", "1小时/种"],
      ["方法自动生成", "从工作空间+档案中\n自动推导加粉方法", "目标质量→方法映射", "第3周"],
      ["闭环验证", "执行方法并验证精度\n数据反馈入库", "通过率数据\n持续改进", "持续"],
    ],
    [2000, 3000, 2800, 1200]
  );

  E();
  P("与原始方案的关系：本方案是原《10mg绝对误差级粉末自动装样设备总体研发方案》的阶段1-2的具体实施版本。核心理念一致（设备表征→工作空间→方法生成→验证），但做了两个关键调整：① 粉体工作空间从封闭式改为开放式（标准粉+历史粉持续积累），② 新粉接入从完整表征改为快速探针+最近邻匹配（1小时而非1周）。");
});

// ═══════════════════════ 二、设备物理特性摸底 ════════════════════
section("二、设备物理特性摸底实验", HeadingLevel.HEADING_1, () => {

  P("在写任何自动化代码之前，必须系统性地理解振动频率、占空比、窗口开度、振幅这四个控制变量各自的影响。本章是后续所有工作的基础——自动实验调度器用它决定扫哪些参数，方法生成器用它约束搜索空间，人工操作者用它判断「出了什么问题调哪个参数」。");

  E();
  section("2.1  四个控制变量已知信息", HeadingLevel.HEADING_2, () => {
    P("以下是从现有代码、preset配置和测试数据中提取的初步认知。标记为「待确认」的条目需要在本实验中验证。");

    E(); B("频率（Frequency）"); E();
    T(
      ["属性", "当前认知", "置信度"],
      [
        ["硬件范围", "10-80 Hz（R12寄存器）", "确认"],
        ["调节速度", "不可在线调节（当前闭环中锁定）", "确认"],
        ["主要作用", "决定工作区域和共振状态", "确认"],
        ["10Hz", "极低流量，High-flow粉末专用", "确认"],
        ["40-50Hz", "中低流量，可能存在共振", "待确认"],
        ["60-70Hz", "稳定工作区，多数粉末适用", "确认"],
        ["80Hz", "高流量，快速粗加", "确认"],
        ["共振", "某些频段CV异常升高，流量大幅度振荡", "待定量"],
        ["最佳频段", "取决于粉末和加粉头组合，尚无通用规律", "待确认"],
      ],
      [2400, 4800, 1600]
    );

    E(); B("占空比（Duty）"); E();
    T(
      ["属性", "当前认知", "置信度"],
      [
        ["硬件范围", "1000-5000（代码限制为1000-2500）", "确认"],
        ["调节速度", "快（0.5秒更新，PI回路主要调节变量）", "确认"],
        ["主要作用", "较快的流量调节；可能等价于振幅/驱动强度", "部分确认"],
        ["最低有效值", "约 1000，低于此值几乎不出粉", "确认"],
        ["与流量关系", "大致线性，但在高频段可能出现饱和", "待确认"],
        ["与振幅关系", "LA10-D上可能直接控制驱动强度=等价振幅", "待确认"],
      ],
      [2400, 4800, 1600]
    );

    E(); B("窗口开度（Aperture / Window）"); E();
    T(
      ["属性", "当前认知", "置信度"],
      [
        ["硬件范围", "步进电机驱动，100-750 units", "确认"],
        ["调节速度", "慢（~1mm/s机械移动，2秒+完成一次）", "确认"],
        ["主要作用", "较慢的大范围流量调节", "确认"],
        ["与流量关系", "窗口越大流量越大，大致线性", "待定量"],
        ["回差", "正向vs反向移动到同一位置，流量可能不一致", "待确认"],
        ["最小有效值", "约 100 units，再小可能完全挡住出粉口", "待确认"],
        ["动态调节", "默认关闭，仅High-flow粉末启用", "确认"],
      ],
      [2400, 4800, 1600]
    );

    E(); B("振幅（Amplitude / Drive）"); E();
    T(
      ["属性", "当前认知", "置信度"],
      [
        ["是否独立可控", "LA10-D上是否存在独立寄存器——未知", "待确认"],
        ["与占空比关系", "如果无独立寄存器，duty变化可能在物理上等价于振幅", "待确认"],
        ["方案定位", "启流、粗细流切换的重要变量", "方案推测"],
        ["确认方法", "扫描LA10-D全部寄存器；查阅完整手册", "建议"],
      ],
      [2400, 4800, 1600]
    );
  });

  E();
  section("2.2  12个核心实验问题", HeadingLevel.HEADING_2, () => {
    const qs = [
      ["频率", [
        "频率-流量曲线？固定duty=2000, window=200，10-80Hz扫描",
        "频率和占空比有交互吗？低频+高duty vs 高频+低duty能否产生相同流量？哪种更稳定？",
        "频率是否影响启流？10/40/70Hz冷启动各需多久出粉？是否存在硬门槛？",
        "频率是否影响尾量？高频率停机 vs 低频率停机，尾量有差异吗？",
      ]],
      ["占空比", [
        "占空比-流量曲线？固定freq=60Hz, window=200，1000-2500扫描",
        "占空比变化→流量的响应速度？一个稳态跳到另一个，流量多久跟上？",
        "占空比是否等价于振幅？能否覆盖高振幅启动→低振幅维持的需求？",
      ]],
      ["窗口", [
        "窗口-流量曲线？固定freq=60Hz, duty=2000，100-750扫描",
        "窗口回差多大？200→500（正向）vs 500→200（反向），流量一致吗？",
        "窗口与频率/占空比有交互吗？小窗口+高频 vs 大窗口+低频？",
      ]],
      ["振幅", [
        "振幅是否独立可控？扫描LA10-D寄存器0x00-0x50",
        "如果可控，振幅-流量曲线如何？类似占空比扫描",
      ]],
    ];
    qs.forEach(([cat, items]) => {
      B(`关于${cat}的核心问题：`);
      items.forEach((q, i) => { Bul(`${i + 1}. ${q}`); });
      E();
    });
  });

  E();
  section("2.3  实验矩阵设计", HeadingLevel.HEADING_2, () => {
    P("使用现有的 Constant Rate Test 模式（Dashboard上直接操作），预计总耗时约2.5小时。");

    E(); B("实验A：频率-占空比全矩阵扫描（32组，约1.5小时）"); E();
    P("固定条件：window = 200 units，每组15秒 × 2次重复。表格中每个格子的格式为：流量(mg/s) / CV(%)。");
    E();

    // Build the 8-row frequency-duty matrix properly
    const freqLabels = ["10 Hz", "20 Hz", "30 Hz", "40 Hz", "50 Hz", "60 Hz", "70 Hz", "80 Hz"];
    const dutyHeaders = ["频率 \\ 占空比", "1000", "1500", "2000", "2500"];
    const freqDutyRows = freqLabels.map(f =>
      [f, "流量/CV", "流量/CV", "流量/CV", "流量/CV"]
    );
    T(dutyHeaders, freqDutyRows, [1800, 1700, 1700, 1700, 1700]);

    E();
    P("完成后用颜色标记：绿色（CV<15%，无断流）、黄色（CV 15-25%）、红色（CV>25%或振荡）、白色（不出粉）。绿色区域 = 后续所有自动实验的安全搜索空间。");

    E(); B("实验B：窗口开度扫描（9组，约20分钟）"); E();
    P("固定：实验A中CV最低的(freq, duty)组合。扫描：100, 150, 200, 250, 300, 400, 500, 600, 750 units。画出窗口-流量曲线，标注线性区。");

    E(); B("实验C：关键单点验证（约20分钟）"); E();
    Bul("冷启动对比：最优/最差稳定点，冷vs热启动的启流延迟差异");
    Bul("同流量不同路径：两种参数组合产生相同流量，对比CV和稳定性");
    Bul("停机流速-尾量：高duty vs 低duty停机，尾量差异");
    Bul("窗口回差：正向vs反向移动到同一位置，流量是否一致");
  });

  E();
  section("2.4  预期产出：调参决策树", HeadingLevel.HEADING_2, () => {
    P("以下为待实验数据填充的决策树模板。它将是自动实验调度器和自动方法生成器的规则基础——程序不会「思考」，但可以根据这张表做「检测到X现象 → 调整Y参数」的决策。");

    E();
    T(
      ["现象", "首选操作", "备选操作", "依据"],
      [
        ["不出粉（启流失效）", "提高占空比 +300~500", "提高频率 +20Hz\n或高频启动后降回", "实验A死区边界\n实验C冷启动"],
        ["流速偏低", "提高占空比（PI自动）", "增大窗口 +50\n提高频率 +10Hz", "实验A duty曲线\n实验B 窗口曲线"],
        ["流速偏高/过冲", "降低占空比\n（PI/overspeed自动）", "减小窗口 -50", "实验A duty曲线"],
        ["流速振荡（CV>20%）", "避开当前频率\n换频率 ±15Hz", "降低占空比\n增大窗口", "实验A共振区"],
        ["架桥/断流（rate=0>3s）", "提高占空比冲破架桥", "降低频率\n无效则停机、轻敲料斗", "实验A断流统计"],
        ["尾量偏大", "提前taper开始位置", "降低停机时占空比\n减小force_stop_offset", "实验C尾量"],
        ["冷启动不稳定", "提高启动占空比/频率", "热启动策略\n（先高频短暂振动）", "实验C冷启动"],
        ["多次结果不一致", "检查窗口回差\n检查料斗装粉量", "检查天平稳定性", "实验C回差"],
      ],
      [2600, 2400, 2400, 2000]
    );
  });
});

// ═══════════════════════ 三、开放式粉体工作空间 ══════════════════
section("三、开放式粉体工作空间设计", HeadingLevel.HEADING_1, () => {

  P("粉体工作空间采用开放式设计：用已测试过的4种粉末作为标准粉和初始知识库，后续新粉末通过快速探针+特征匹配的方式接入，无需每次从头做完整表征。随着新粉不断加入，知识库持续积累，匹配精度和推荐质量自然提升。");

  E();
  section("3.1  整体架构", HeadingLevel.HEADING_2, () => {

    P("工作空间 = 标准粉档案（4份）+ 历史新粉档案（持续增长 N份）");
    E();
    P("每份档案包含：");
    Bul("身份信息：粉末名称、批次、日期、外观描述");
    Bul("特征向量：startup_delay, steady_rate, CV, tail_mass, flow_gain（探针提取）");
    Bul("完整档案：启流区、稳定区、低流区、危险区、尾量曲线（标准粉有，新粉可选）");
    Bul("推荐参数：起始频率/占空比/窗口、观测器上限、控制器增益");
    E();
    P("标准粉（4种）需要完整表征，建立高质量基准档案。新粉只需跑快速探针，通过特征匹配找到最近邻，继承参数后微调。");
  });

  E();
  section("3.2  新粉接入流程（6步）", HeadingLevel.HEADING_2, () => {

    B("步骤1：快速探针（15-20分钟）");
    P("跑3-5个频点 × 2档占空比（共6-10个组合），每个组合15秒稳态。记录：启流延迟、稳态平均流量、CV、停机尾量。频点选择和探针具体参数后续详细设计。");
    E();

    B("步骤2：提取特征向量");
    P("从探针数据中计算5维特征向量：");
    E();
    T(
      ["特征", "含义", "提取方法", "量纲"],
      [
        ["startup_delay", "启流响应速度", "振动启动→首次质量增加的时间", "秒"],
        ["steady_rate", "给料效率", "探针各点的平均流量", "mg/s"],
        ["CV", "给料稳定性", "探针各点CV的均值", "%"],
        ["tail_mass", "停机残留", "各探针点停机后的平均尾量", "mg"],
        ["flow_gain", "对占空比的敏感度", "Δrate/Δduty的斜率", "mg/s/1000duty"],
      ],
      [2200, 2000, 3200, 2000]
    );
    E();

    B("步骤3：最近邻匹配");
    P("与库内4种标准粉 + N种历史粉计算特征空间中的距离。距离度量采用标准化欧氏距离（每个维度先做Z-score归一化，消除量纲差异）。");
    Bul("找最近邻1-2个（k=2，既保证效率又提供备选）");
    Bul("如果最近邻距离超过阈值（如 > 3倍平均类内距离），标记为「异常新粉」，回退到完整表征流程或人工判断");
    E();

    B("步骤4：参数继承");
    P("从最近邻（或两个最近邻的加权平均）继承以下参数：");
    Bul("推荐起始频率、占空比、窗口位置");
    Bul("最大流速上限（maximum_flow_rate_mg_s）");
    Bul("控制器增益参数（duty_step_per_update, emergency_duty_step_per_update）");
    Bul("position_feedback_enabled 标志");
    Bul("force_stop_offset、fixed_tail_mass 等停机参数");
    E();

    B("步骤5：局部微调（2-3轮闭环验证）");
    P("用继承的参数跑2-3次闭环加粉（例如100mg目标），观察实际表现：");
    Bul("如果偏轻：减小force_stop_offset或提高coarse_rate");
    Bul("如果偏重：增大force_stop_offset或降低coarse_rate");
    Bul("如果不稳定：根据决策树调整频率或占空比");
    Bul("每轮微调后验证一次，通常2-3轮即可收敛");
    E();

    B("步骤6：入库");
    P("将新粉的探针数据、特征向量、最终采用的参数、验证结果打包存入工作空间库。新粉档案自动成为后续新粉匹配的候选。");
  });

  E();
  section("3.3  特征归一化策略", HeadingLevel.HEADING_2, () => {
    P("5个特征的量纲完全不同，直接计算欧氏距离会导致大数值特征主导匹配结果。采用Z-score标准化：对每个特征维度，用库内所有粉末的均值和标准差进行归一化。新粉加入后，均值和标准差动态更新。");
    E();
    P("如果库内粉末数量较少（<10），可以先用min-max归一化（缩放到[0,1]），待积累更多数据后切换到Z-score。");
  });

  E();
  section("3.4  与代码模块的对应", HeadingLevel.HEADING_2, () => {
    T(
      ["流程步骤", "对应代码模块", "状态"],
      [
        ["步骤1：快速探针", "新模块：powder_probe.py\n或多频探针配置脚本", "待开发"],
        ["步骤2：特征提取", "powder_fingerprint.py\n（已有设计，需实现）", "设计完成\n待实施"],
        ["步骤3：最近邻匹配", "method_library/search.py\n（Week 3开发）", "待开发"],
        ["步骤4：参数继承", "method_generator/generator.py\n（Week 3开发）", "待开发"],
        ["步骤5：局部微调", "Run Controller\n（feedback_controller.py）", "已完成"],
        ["步骤6：入库", "Method & Data Library\n（Week 3开发）", "待开发"],
      ],
      [2600, 3200, 2400]
    );
  });
});

// ═══════════════════════ 四、已有代码资产 ═════════════════════════
section("四、已有代码资产与合并", HeadingLevel.HEADING_1, () => {

  P("以下12项成果是在新方案基础上可以直接复用的资产，不是从零开始。");

  E();
  T(
    ["#", "成果", "成熟度", "在新方案中的位置"],
    [
      ["1", "ContinuousFeedbackController\n（三阶段+PI+overspeed+taper\n+settle+force_stop+stall）", "高", "Run Controller模块\n= 方案完整实现"],
      ["2", "MassMotionEstimator\n（α-β-γ滤波器，含预测）", "高", "Run Controller信号处理层"],
      ["3", "Profile插值（100-1000mg，\n6字段线性插值+clamp）", "高", "Method Generator的\n插值基础"],
      ["4", "粉末分类（Low/Medium/\nHigh-flow+unstable/sticky）", "中", "工作空间的分类维度\n探针匹配的初始特征"],
      ["5", "粉末特征码设计\n（探针→特征→分类→映射）", "设计完成", "改为探针→特征→\n近邻匹配→继承参数"],
      ["6", "ConstantRateController\n（定速+频率锁定+振荡检测）", "高", "设备表征实验执行器\n探针实验执行器"],
      ["7", "11个预设（presets）", "中", "工作空间初始种子\n标准粉的预设来源"],
      ["8", "粉末对比数据\n（小苏打vs熟石灰，10倍速差）", "数据已有", "标准粉候选的基础数据"],
      ["9", "device_control_server.py\n（三种模式）", "高", "硬件driver层\n（保留不动）"],
      ["10", "Taper stall escape逻辑", "已修改\n待验证", "Run Controller的\nDeceleration实现"],
      ["11", "Settle确认+速率脉冲防御", "高", "Run Controller的\n停机安全机制"],
      ["12", "33次100mg闭环数据", "已记录", "标准粉验证数据"],
    ],
    [500, 3400, 1200, 2800]
  );
});

// ═══════════════════════ 五、三周开发计划 ═════════════════════════
section("五、三周开发详细计划", HeadingLevel.HEADING_1, () => {

  P("以下计划以周为单位设定目标和产出，具体每日任务由实际情况灵活安排。前置条件：先确认 LA10-D 振幅寄存器是否存在，并跑完第二章的设备摸底实验。");

  E();
  section("5.1  第一周：设备表征与自动实验调度器", HeadingLevel.HEADING_2, () => {

    B("目标");
    P("完成设备物理特性摸底，建立频率-占空比-窗口的工作空间粗图，搭建自动实验调度器框架。");
    E();
    B("核心任务");
    Bul("扫描 LA10-D 全部可访问寄存器，确认振幅是否独立可控");
    Bul("执行频率-占空比全矩阵扫描（32组×2重复），标注安全区/危险区/死区");
    Bul("执行窗口开度扫描（9点），结合已有 80Hz 窗口扫描数据形成完整窗口-流量曲线");
    Bul("执行启流实验（冷/热启动对比）和状态转换实验（路径依赖验证）");
    Bul("关键单点验证：同流量不同路径对比、停机流速-尾量关系、窗口回差");
    Bul("搭建 Experiment Orchestrator 框架，实现参数矩阵的自动排队和结果记录");
    E();
    B("交付物");
    Bul("频率-占空比热力图（绿色安全区 / 黄色过渡区 / 红色危险区）");
    Bul("窗口-流量曲线与线性区标注");
    Bul("调参决策树 v1：8-10 条「现象→调整」规则，每条有实验数据支撑");
    Bul("Experiment Orchestrator 代码（可自动执行参数矩阵扫描并记录数据）");
    Bul("硬件能力确认文档（振幅是否存在、寄存器完整映射、窗口回差数据）");
  });

  E();
  section("5.2  第二周：标准粉建档与特性表征引擎", HeadingLevel.HEADING_2, () => {

    B("目标");
    P("为 4 种标准粉末建立完整的粉体-加粉头特性档案，实现 Characterization Engine 自动执行四类标准实验。");
    E();
    B("核心任务");
    Bul("确定 4 种标准粉（候选：小苏打/熟石灰/膨润土/淀粉），覆盖 High/Medium/Low/Ultra-low 四档");
    Bul("搭建 Characterization Engine，实现启流、稳态、状态转换、停机尾量四类实验的自动执行");
    Bul("对每种标准粉执行 80-90 次自动实验，产出一份完整特性档案（含启流门槛、稳定工作区、危险区、路径依赖、尾量特性）");
    Bul("执行停机与尾量专项实验（4种流速×10次重复），建立流速-尾量校准曲线");
    Bul("提取 4 种标准粉的探针特征基线（5维特征向量），为后续新粉匹配提供参考基准");
    E();
    B("交付物");
    Bul("4 份标准粉特性档案（每份含：启流区、粗加稳定区、低流稳定区、危险区、路径依赖、尾量曲线）");
    Bul("Characterization Engine 代码（支持四类实验的自动参数配置、执行和结果汇总）");
    Bul("流速-尾量校准曲线（核心交付物，直接用于方法生成器的停机逻辑参数化）");
    Bul("标准粉特征基线（4×5 维特征向量 + 统计分布）");
  });

  E();
  section("5.3  第三周：方法生成器与探针接入原型", HeadingLevel.HEADING_2, () => {

    B("目标");
    P("实现加粉方法生成器 v0，完成多目标验证；跑通新粉探针接入的完整链路。");
    E();
    B("核心任务");
    Bul("设计 Dosing Method Generator，定义方法数据结构（阶段序列、参数映射、约束条件）");
    Bul("实现生成器核心逻辑：从特性档案推导 100/300/500mg 的加粉方法（启流→粗加→减速→精加→停机）");
    Bul("多目标闭环验证：100mg×20次、300mg×20次、500mg×20次，对比生成器 vs 手动方法的通过率");
    Bul("鲁棒性测试：不同装粉量、不同加粉角度、连续多次运行，评估方法稳定性");
    Bul("实现探针模块框架（powder_probe.py）和特征提取+最近邻匹配算法");
    Bul("搭建 Method & Data Library 基础结构（粉体、批次、方法版本的存储与检索）");
    E();
    B("交付物");
    Bul("Dosing Method Generator v0（可从特性档案自动生成 100/300/500mg 加粉方法）");
    Bul("100/300/500mg 验证数据集（各≥20次，含通过率、偏差分布、耗时统计）");
    Bul("探针模块原型（多频探针执行 + 5维特征提取 + k-NN 匹配 + 参数继承）");
    Bul("Method & Data Library 基础代码（JSON/SQLite 存储，支持增删查）");
    Bul("阶段总结报告（含三周全部实验数据、代码清单、遗留问题和后续建议）");
  });

  E();
  section("5.4  交付物汇总", HeadingLevel.HEADING_2, () => {
    T(
      ["#", "交付物", "对应方案要求", "周"],
      [
        ["1", "频率-占空比热力图 + 窗口-流量曲线", "设备表征", "W1"],
        ["2", "调参决策树 v1", "设备表征", "W1"],
        ["3", "Experiment Orchestrator", "自动实验调度器", "W1"],
        ["4", "4份标准粉特性档案", "粉体-加粉头工作空间", "W2"],
        ["5", "Characterization Engine", "特性表征引擎", "W2"],
        ["6", "流速-尾量校准曲线", "停机/尾量实验", "W2"],
        ["7", "Dosing Method Generator v0", "自动方法生成", "W3"],
        ["8", "100/300/500mg验证数据集", "多目标验证", "W3"],
        ["9", "探针模块原型 + 匹配算法", "新粉快速接入", "W3"],
        ["10", "Method & Data Library", "数据资源库", "W3"],
        ["11", "阶段总结报告", "文档", "W3"],
      ],
      [500, 3200, 2800, 800]
    );
  });
});

// ═══════════════════════ 六、人工操作预案 ═════════════════════════
section("六、人工测试操作指南（预案）", HeadingLevel.HEADING_1, () => {

  P("如果自动实验调度器或方法生成器未能按时完成，用户可通过以下四步人工流程为新粉末寻找稳定参数。这套流程也是自动系统的验证工具——生成器给出的方法是否可靠，通过人工流程跑一遍即可判断。");

  E();
  P("① 粗扫描找安全区：固定窗口，频率×占空比矩阵扫描，按CV标记绿色/黄色/红色区域。② 细调选最佳预设：在绿色区选3-5个候选点，覆盖高/中/低三档流速，重复测试选CV最低的组合。③ 闭环验证：用选定预设跑5-10次闭环加粉，根据偏差方向微调 force_stop_offset。④ 记录入库：保存参数和测试数据，积累历史经验。");

  E();
  P("常见问题的经验调整方向可参照第二章的调参决策树。所有手动测试数据均应保存——这些数据是后续训练自动系统的贵重样本。手动→积累数据→训练自动→取代手动，是健康的迭代路径。");
});

// ═══════════════════════ 七、风险与里程碑 ═════════════════════════
section("七、关键风险与里程碑", HeadingLevel.HEADING_1, () => {

  section("7.1  关键风险", HeadingLevel.HEADING_2, () => {
    T(
      ["风险", "概率", "影响", "缓解措施"],
      [
        ["振幅硬件不支持", "中", "中", "Day 1确认，用占空比替代"],
        ["taper改动导致尾量不可控", "中", "高", "W2尾量实验快速暴露"],
        ["生成器方法通过率低于手动", "中", "高", "W3有对比实验可调整"],
        ["探针匹配找不到近邻", "低", "中", "回退到完整表征"],
        ["料斗装粉量影响大", "低", "中", "W3鲁棒性测试覆盖"],
        ["仅1台设备无法做迁移", "确定", "已知", "纳入后续阶段"],
      ],
      [2800, 800, 800, 4400]
    );
  });

  E();
  section("7.2  里程碑", HeadingLevel.HEADING_2, () => {
    T(
      ["时间", "里程碑", "判定标准"],
      [
        ["第零周", "设备摸底完成", "决策树10行规则有实验数据支撑"],
        ["W1结束", "工作空间粗图+Orchestrator", "频率-占空比热力图完成\nOrchestrator可自动执行扫描"],
        ["W2结束", "4份标准粉档案", "每份含启流/稳态/尾量完整数据"],
        ["W3结束", "方法生成器+探针原型", "100/300/500mg自动方法通过率≥60%\n探针+匹配链路跑通"],
      ],
      [1600, 3200, 4400]
    );
  });
});

// ── Build document ──────────────────────────────────────────────────

const validChildren = children.filter(Boolean);
console.log("Total children: " + validChildren.length + " (raw: " + children.length + ")");

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: F, size: S } },
    },
  },
  numbering: {
    config: [{
      reference: "b",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "\u2022",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } }
      }],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 },
      },
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.RIGHT,
          children: [new TextRun({ text: "粉末自动装样设备 — 下一阶段研发方案", font: F, size: ST, color: "888888" })],
        })],
      }),
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "第 ", font: F, size: ST, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: F, size: ST, color: "888888" }),
            new TextRun({ text: " 页", font: F, size: ST, color: "888888" }),
          ],
        })],
      }),
    },
    children: validChildren,
  }],
});

// ── Write ───────────────────────────────────────────────────────────

const outPath = "c:/Users/22371/Downloads/出粉/powder_sampling_control/powder_sampling_control/docs/下一阶段研发方案.docx";
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("OK: " + outPath + " (" + (buf.length / 1024).toFixed(1) + " KB)");
}).catch(err => {
  console.error("ERROR:", err.message);
  process.exit(1);
});
