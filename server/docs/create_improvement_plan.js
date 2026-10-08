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
function p(t) { return new Paragraph({ spacing: { before: 50, after: 50 },
  children: [new TextRun({ text: t, font: F, size: 18 })] }); }
function b(t) { return new Paragraph({ spacing: { before: 25, after: 25 }, indent: { left: 480 },
  children: [new TextRun({ text: '• ' + t, font: F, size: 18 })] }); }
function sp() { return new Paragraph({ spacing: { before: 80, after: 0 }, children: [] }); }

const C = [];

// Title
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
  children: [new TextRun({ text: '粉末加粉头改进方案', font: F, bold: true, size: 36, color: '1A3A6B' })] }));
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: '从被动振动到主动输送：机械结构与控制策略重构', font: F, size: 22, color: '2B579A' })] }));
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [new TextRun({ text: '参考文献：El Hariry et al., SLAS Technology 38 (2026) 100406\nUS Patent 20180178937A1, Mettler-Toledo GmbH', font: F, size: 16, color: '888888', italics: true })] }));

// ── 1. 现有加粉头的缺陷 ──
C.push(h1('一、重力式-漏斗形-振动驱动型加粉头的缺陷分析'));

C.push(p('El Hariry 等（2026）对 Mettler Toledo Q3 加粉模块（LNCT/LNLW 型加粉头）在中量程（5–100 g）场景下进行了系统性评估。尽管 Q3 模块已具备旋转搅拌与垂直脉动功能，论文仍揭示了此类"漏斗形+机械辅助+重力出粉"架构的共性失效模式。本文所讨论的 LA10-D 纯振动加粉装置因缺少搅拌与关断机构，以下问题更为严重。'));

C.push(sp());
C.push(h2('1.1 被动出粉——对粉末流动性的根本依赖'));
C.push(p('加粉驱动力为重力与振动能量，粉末是否下落、下落速率完全取决于粉末自身的流变特性。当粉末休止角大于漏斗锥角、或颗粒间内聚力超过重力分量时，粉末停滞于漏斗内，系统无任何主动干预手段。El Hariry 等的实验表明，13 种粉末中有 7 种（54%）完全无法在 Q3 模块上加粉，包括因高含水量导致粘结成块的 K₂HPO₄、MgCl₂·6H₂O 及因小粒径导致压实的 HEPES 等。对纯振动装置而言，预期失败率将更高。'));

C.push(sp());
C.push(h2('1.2 出口结拱——振动能量的方向性失效'));
C.push(p('粉末在漏斗出口上方形成拱形空腔（arching/jamming），拱体承受上方粉体的压应力而自锁，外部振动能量因方向性失配（水平振动对垂直拱体无效）而无法破拱。论文 Fig. 3 记录了 KH₂PO₄ 与 NaCl 在加粉头出口处的结拱形貌。LNCT 型加粉头通过垂直脉动周期性地敲击拱体实现破拱，而 LNLW（无脉动）对 KH₂PO₄ 完全失效——这直接证明了纯水平振动在破拱能力上的根本性不足。'));

C.push(sp());
C.push(h2('1.3 壁面附着与死区形成'));
C.push(p('粘性粉末（如 KCl）附着于漏斗内壁后不再参与流动，形成"死区"。随着加粉进行，有效粉体体积持续缩减，出粉速率衰减，加粉时间变得不可预测。论文中 KCl 是唯一不服从线性时间曲线的粉末，其 5 g 与 25 g 加粉时间呈现极大方差。振动无法解决壁面附着问题，因为静态壁面本身不参与振动能量传递。'));

C.push(sp());
C.push(h2('1.4 关断不精确——残留粉末的惯性滴落'));
C.push(p('振动停止不构成物理关断。出口附近的松散粉末在惯性力和重力作用下仍将持续下落，导致"关断后余粉"误差。现有系统通过提前停机（duty-first 策略）进行经验补偿，但补偿精度依赖于粉末的一致性——当粉末因湿度、压实度变化而改变流动行为时，补偿量随即失效。Mettler Toledo 专利 US20180178937A1 的轴向平移闭合部通过将圆柱端面嵌入出口孔实现物理密封，这一能力是纯振动装置无法企及的。'));

C.push(sp());
C.push(h2('1.5 出粉速率调节范围受限'));
C.push(p('纯振动仅有两个可调变量——频率（10–80 Hz）与占空比（10–50%）。低频低占空比下粉末可能停滞不动；高频高占空比下粉末飞溅失控。调节窗口窄且与粉末类型强耦合。专利所述的可变出口开度（轴向平移连续调节出口有效面积）从根本上扩展了速率调节范围——粗加时大开口、精加时小开口、关断时密封——这是纯振动方案在原理上无法实现的。'));

C.push(sp());
C.push(h2('1.6 振动对粉末的负面效应'));
C.push(p('对于小粒径高内聚力粉末（如论文中的 HEPES，d₅₀ 极小且粒径分布跨度大），振动不仅不能促进流动，反而通过颗粒重排使粉体更加密实。这种现象称为振动致密化（vibration-induced compaction），在振动输送领域已有充分文献记载。对这类粉末，振动是反向作用，持续振动只会加剧问题。'));

// ── 2. 改进方向 ──
C.push(new Paragraph({ children: [] })); // manual break for layout
C.push(h1('二、新型加粉头设计需求'));

C.push(h2('2.1 搅拌-破拱机构'));
C.push(p('在储料腔内引入旋转搅拌器，实现以下功能：'));

C.push(b('主动搅散——旋转刮板/搅拌叶片强制打散粉末团块与架桥结构，使粉末持续处于松散状态。Mettler Toledo 专利中的输送体（Conveyor Body, 103）即兼作刮板，在旋转过程中不仅输送粉末、同时刮擦漏斗内壁，阻止附着层的形成与生长。'));
C.push(b('垂直脉动——搅拌器在旋转的同时沿轴向往复运动（pulsation），周期性地对出口上方粉体施加轴向冲击力。论文的实验数据明确支持这一设计的有效性：LNCT（搅拌+脉动）在 5 g 目标量下对所有可加粉粉末均优于 LNLW（仅搅拌），Tris 的加粉时间从 78.7 s 降至 26.7 s（减少 66%），KH₂PO₄ 从完全失败变为可加粉。'));
C.push(b('速度差异化的搅拌策略——初始慢速搅拌建立均匀粉体结构，待流动稳定后逐步提速。这避免了传统"开机即全速"导致的粉末飞溅与不均匀出粉。'));

C.push(sp());
C.push(h2('2.2 出口开关（Shutter/Valve）机构'));
C.push(p('在漏斗出口下方增设物理挡片或阀芯，由电磁铁或舵机驱动，实现以下控制模式：'));

C.push(b('可变开度——出口有效面积连续可调。粗加段全开，精加段缩小至最小可控开度，关断段完全封闭。这一机制使流速调节不再仅依赖振动参数，而是通过改变出口几何约束实现大范围速率控制。'));
C.push(b('物理关断——加粉完成时，先关闭挡片切断粉末路径，再停止振动。此顺序操作确保了关断时刻出口上方已无可通过的粉末，从根本上消除残留滴粉问题。Mettler Toledo 专利将此作为核心创新点：闭合部嵌入出口孔形成面密封，停粉后零残留。'));
C.push(b('快速响应——挡片的开关动作应在 <100 ms 内完成，以匹配软件控制的实时性要求。'));

C.push(sp());
C.push(h2('2.3 粉末下降缓冲与主动输送'));
C.push(p('现有系统中，粉末从漏斗出口到目标容器的路径是完全自由的——粉末在重力作用下做自由落体或沿斜壁滑落，落点、速度、散布范围均不可控。这导致三个问题：'));

C.push(b('落点分散——粉末可能溅出目标容器（尤其是低质量粉末在静电作用下飘散），造成物料损失和交叉污染。'));
C.push(b('冲击速度不可控——粉末以不可预测的速度落入容器，天平读数产生动态冲击误差，增加稳定等待时间。'));
C.push(b('出粉是被动的——整个下落过程依赖重力，粉末行为不受机械约束。'));

C.push(sp());
C.push(p('改进方向：在漏斗出口与目标容器之间引入缓冲导流通道，实现粉末的受控降落。具体方案：'));

C.push(b('螺旋导流槽——出口下方加装螺旋形或 S 形导流槽，粉末沿槽滑落而非自由落体。降低下落终点速度，减小对天平称盘的冲击。'));
C.push(b('静电耗散——导流槽采用导电材料（如碳填充 PLA 或金属涂层 3D 打印件），将粉末摩擦产生的静电荷导出，减少粉末飞散。'));
C.push(b('落点约束——导流槽出口尽可能接近目标容器底部，减小最后一程的自由落体距离。XPR 系统的 ErgoClip 适配器即采用此原理。'));
C.push(b('主动推送——在导流通道中集成微型螺旋输送器（auger/screw feeder），将粉末从出口"推"向目标容器，而非依赖重力下落。这使粉末的出口速度由螺旋的转速和螺距精确决定，实现主动定量出粉。'));

C.push(sp());
C.push(h2('2.4 加粉节奏重构：从"快-慢-停"到"慢-定-快-停"'));
C.push(p('传统加粉策略（XPR 为代表）采用"粗加（快）→ 精加（慢）→ 关断"的三段式节奏，其前提是系统具有精密的可变出口和主动输送机构，粗加段的大流量不会失控。对于本系统，因缺少精密出口控制，建议采用反向节奏：'));

C.push(b('慢启动段（Slow-Start Phase）——以低频低占空比启动，建立稳定的粉末流动。此段的目的是：① 确认粉末在当前条件下可正常出粉；② 测量实际出粉速率，为后续定速段提供参数依据；③ 避免"开机即全速"导致的初始冲击和不可控出粉。'));
C.push(b('定速加粉段（Constant-Rate Phase）——根据慢启动段测得的实际速率，选择合适的频率和占空比维持均匀出粉。此段占据目标量的 60–80%，要求速率稳定可控，便于预测剩余时间（利用论文验证的线性时间规律）。'));
C.push(b('快收尾段（Fast-Finish Phase）——在接近目标时，利用已稳定的粉末流动状态，以短脉冲快速追加剩余微量，减少精加时间。与传统"精加慢速"不同，此策略假设粉末流动已进入稳态，短时加速不会导致失控。'));
C.push(b('关断段（Shutoff Phase）——先关挡片再停振动，消除残留。'));

C.push(sp());
C.push(p('该"慢-定-快"节奏的理论基础是：在粉末流动进入稳态后，其出粉行为是可预测的（论文已证明可加粉粉末满足线性时间规律），因此加速段的风险是可控的。反之，传统的"快-慢"节奏假设初始大流量阶段即可控，对本系统而言风险更高。'));

// ── 3. 软件改造 ──
C.push(new Paragraph({ children: [] }));
C.push(h1('三、软件控制策略的对应改造'));

C.push(p('硬件结构的改变（搅拌器、出口挡片、导流通道）要求软件在以下四个层面进行响应性重构。'));

C.push(sp());
C.push(h2('3.1 驱动层改造'));
C.push(tbl(['现状', '改造后', '技术要点'],
  [['单一 Modbus 控制指令：\nwrite_register(frequency, duty)\n→ LA10 振动', '多轴协同控制：\n搅拌器转速（步进电机 PWM）\n挡片位置（舵机角度/电磁铁通断）\n振动参数（频率/占空比）\n螺旋输送器转速', '抽象统一的 Actuator 接口\n每轴独立的状态机\n轴间同步与互锁逻辑\n（如挡片未开时禁止螺旋运转）'],
   ['在线改参数已支持\nupdate_vibration_parameters()\nupdate_vibration_frequency()', '多参数原子更新：\n单次指令同时设定多轴目标\n（避免逐轴更新期间的\n时间差导致状态不一致）', '事务性参数更新\n回滚机制（任一轴失败\n→ 全部回退到安全状态）']],
  [2400, 3400, 3400]));

C.push(sp());
C.push(h2('3.2 定速控制逻辑改造'));
C.push(p('现有 constant-rate-controller 采用 duty-first 策略（优先调整占空比以维持目标速率，频率锁定于预设值，含振荡检测）。该逻辑建立在"振动参数是唯一控制量"的假设上。加入搅拌器和挡片后，出粉速率变为多变量函数：'));

C.push(p('  R = f(ω_stirrer, θ_shutter, f_vib, d_vib)', { noIndent: true }));
C.push(p('  其中 ω = 搅拌转速，θ = 挡片开度，f = 振动频率，d = 振动占空比', { noIndent: true }));

C.push(sp());
C.push(p('新的定速控制需要：'));
C.push(b('主控量变更——挡片开度 θ 成为流速粗调的主控量（对应 XPR 的可变出口），振动参数退居微调角色。搅拌转速维持粉末流动性的辅助角色。'));
C.push(b('解耦控制——四个变量之间存在非线性耦合（如挡片开度影响振动传递效率、搅拌转速影响粉末进入出口的速率），需通过实测建立耦合矩阵并设计解耦控制器。'));
C.push(b('分段控制策略——慢启动段以搅拌为主（建立流动），振动为辅；定速段以挡片开度为主（调节流速）；收尾段挡片收窄 + 振动脉冲配合。'));

C.push(sp());
C.push(h2('3.3 动态调整方法改造'));
C.push(p('现有动态调整基于"实际重量偏离预期曲线 → 调整频率/占空比"的单变量闭环。新系统需要多维动态调整：'));

C.push(tbl(['调整场景', '当前方法', '新方法', '触发条件'],
  [['出粉速率偏低', '提高频率/占空比', '① 优先增大挡片开度\n② 若已全开则提高搅拌转速\n③ 最后调整振动参数', '实际速率 < 目标速率 × 0.8\n持续 > 2 个稳定周期'],
   ['出粉速率偏高', '降低频率/占空比', '① 优先缩小挡片开度\n② 若已接近最小则降低\n   搅拌转速\n③ 最后降低振动参数', '实际速率 > 目标速率 × 1.2\n持续 > 2 个稳定周期'],
   ['疑似架桥', '无主动应对\n只能报警', '① 挡片全关 → 全开（脉冲式\n   开关 3 次冲击出口）\n② 搅拌器执行轴向脉动\n③ 仍无效则报警', '连续 N 秒重量无增长\n（N = 3 × 天平稳定时间）'],
   ['接近目标\n（>90%）', '降低占空比\n进入精加模式', '① 挡片收窄至 20% 开度\n② 等待 1 个稳定周期\n③ 若差额 > 阈值则点动脉冲\n   （快收尾模式）', '实际重量 > 目标 × 0.9']],
  [1800, 2200, 3200, 2200]));

C.push(sp());
C.push(h2('3.4 状态机重构'));
C.push(p('从原有的"启动振动 → 在线调速 → 停止振动"的简单序列，重构为多阶段协同状态机：'));

C.push(b('INIT → 检查各轴状态，挡片置于关闭位，搅拌器归零'));
C.push(b('SLOW_START → 搅拌器启动（低速），挡片开至 50%，振动低频低占空比。实时测量出粉速率，持续至速率稳定（方差 < 阈值）或累计时间超时'));
C.push(b('CONSTANT_RATE → 根据实测速率设定挡片开度和振动参数，维持均匀出粉。持续监控速率偏差，按 3.3 节策略动态调整。至重量 ≥ 目标 × 0.9 时退出'));
C.push(b('FAST_FINISH → 挡片收窄至 20%，以短脉冲振动追加剩余差额。每次脉冲后等待天平稳定，判定是否达标'));
C.push(b('SHUTOFF → 挡片完全关闭，延迟 50 ms 后停止振动和搅拌。等待最终重量稳定 → 记录结果'));
C.push(b('ERROR → 任一阶段出现不可恢复异常（超时/过冲/粉末耗尽）→ 挡片关闭 → 所有轴停止 → 报警'));

C.push(sp());
C.push(h2('3.5 粉末流动状态估计'));
C.push(p('引入基于重量-时间序列的在线状态估计器：'));
C.push(b('稳态检测——滑动窗口内速率方差 σ² < 阈值 → 判定流动进入稳态，允许切换到定速段'));
C.push(b('退化检测——速率趋势性下降（线性回归斜率为负持续超过 3 个窗口）→ 判定粉末流道可能出现架桥或壁面附着加重'));
C.push(b('突变检测——单周期内重量增量超过历史均值的 3σ → 判定可能发生粉体坍塌或团块掉落，触发挡片紧急缩窄'));

// ── 4. 总结 ──
C.push(new Paragraph({ children: [] }));
C.push(h1('四、实施优先级'));

C.push(tbl(['优先级', '改造项', '依赖关系', '说明'],
  [['P0', '出口挡片机构', '无', '最小可行改进：单电磁铁+挡片即可实现\n物理关断，消除残留滴粉。可与现有\n振动底座并联使用'],
   ['P0', '导流缓冲通道', '无', '3D 打印螺旋导流槽，降低粉末冲击速度\n减少飞散，天平读数更稳定'],
   ['P1', '搅拌器', 'P0', '旋转刮板+垂直脉动，解决被动出粉和\n结拱问题。需要步进电机驱动和结构件'],
   ['P1', '软件驱动层重构', 'P0, 搅拌器硬件到位', '多轴 Actuator 抽象、原子参数更新、\n状态机重构'],
   ['P2', '慢-定-快加粉策略', 'P1', '新状态机下的加粉节奏实现，包含\n稳态检测和动态调整'],
   ['P2', '螺旋输送器（可选）', 'P0, P1', '进一步升级为主动推送出粉，使粉末\n出口速度由机械精确决定']],
  [1000, 2200, 2400, 4400]));

C.push(sp());
C.push(p('核心原则：先解决关断（P0），再解决输送（P1），最后优化节奏（P2）。每一步均可独立验证效果，渐进式降低风险。'));

C.push(sp());
C.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 160 },
  children: [new TextRun({ text: '— 完 —', font: F, size: 16, color: 'AAAAAA', italics: true })] }));

// ── build ──
const doc = new Document({
  styles: { default: { document: { run: { font: F, size: 18 }, paragraph: { spacing: { line: 260 } } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1000, bottom: 900, left: 1000, right: 1000 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [new TextRun({ text: '粉末加粉头改进方案', font: F, size: 14, color: 'BBBBBB', italics: true })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: '第 ', font: F, size: 14, color: '999999' }),
        new TextRun({ children: [PageNumber.CURRENT], font: F, size: 14, color: '999999' }),
        new TextRun({ text: ' 页', font: F, size: 14, color: '999999' })] })] }) },
    children: C
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('c:/Users/22371/Downloads/出粉/powder_sampling_control/powder_sampling_control/docs/粉末加粉头改进方案.docx', buf);
  console.log('OK');
});
