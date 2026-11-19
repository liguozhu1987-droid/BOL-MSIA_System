// BOL 管理系统使用说明 · PPT 架构模版（含真实系统截图）
const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.author = 'Trae Work';
pres.title = 'BOL 管理系统使用说明';

// ── 尺寸常量 ──
const SLIDE_W = 10, SLIDE_H = 5.625;
const MARGIN = 0.5;
const CONTENT_X = MARGIN, CONTENT_W = SLIDE_W - 2 * MARGIN;

// ── 配色（与系统 UI 蓝色渐变一致） ──
const C = {
  primary: '2E5AAC', dark: '1A3A6E', accent: 'E07A5F',
  success: '27AE60', danger: 'E74C3C',
  ink: '1A1A2E', muted: '6B7280', rule: 'D1D5DB',
  bg2: 'F8FAFC', light: 'EEF2FF', lightAcc: 'FDEEE8',
  warn: 'FFF9EC', warnBd: 'E8C878', warnTx: '92400E',
  white: 'FFFFFF', lightG: 'E8F5EC', lightR: 'FDECEA',
  iceBlue: 'CADCFC'
};
const FT = 'SimSun';
const FB = 'Microsoft YaHei';

// 截图路径
const S = {
  home: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/01_home.png',
  dashboard: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/02_dashboard.png',
  dynamic: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/03_dynamic_bol.png',
  ct: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/04_actual_ct.png',
  comp: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/05_comparison.png',
  reports: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/06_reports.png',
  budget: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/07_budget_bol.png',
  tracking: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/08_tracking.png',
  login: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/09_login.png',
  account: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/10_account.png',
  help: 'c:/WorkFile/D/OPEX/04-Digital_development/2026/IE系统完善开发/BOL管理系统/screenshots/11_budget_help.png'
};

// ══════════ 容器系统 ══════════
function createVirtualNode(type, data, parentX = 0, parentY = 0) {
  const opts = data.opts || {};
  const node = { type, data, absX: parentX + (opts.x || 0), absY: parentY + (opts.y || 0), w: opts.w || 0, h: opts.h || 0, children: [] };
  node.addShape = function (st, opts = {}) { const c = createVirtualNode('shape', { shapeType: st, opts }, node.absX, node.absY); node.children.push(c); return c; };
  node.addText = function (text, opts = {}) { const safeOpts = { fit: 'shrink', ...opts }; const c = createVirtualNode('text', { text, opts: safeOpts }, node.absX, node.absY); node.children.push(c); return c; };
  node.addImage = function (opts = {}) { const c = createVirtualNode('image', { opts }, node.absX, node.absY); node.children.push(c); return c; };
  node.addTable = function (td, opts = {}) { const c = createVirtualNode('table', { tableData: td, opts }, node.absX, node.absY); node.children.push(c); return c; };
  return node;
}
function flattenNode(node, realSlide) {
  const absOpts = { ...node.data.opts, x: node.absX, y: node.absY };
  if (node.type === 'shape') realSlide.addShape(node.data.shapeType, absOpts);
  else if (node.type === 'text') realSlide.addText(node.data.text, absOpts);
  else if (node.type === 'image') realSlide.addImage(absOpts);
  else if (node.type === 'table') realSlide.addTable(node.data.tableData, absOpts);
  node.children.forEach(ch => flattenNode(ch, realSlide));
}
const orig = pres.addSlide.bind(pres);
pres.addSlide = function (opts) {
  const real = orig(opts);
  const vs = { children: [], _real: real,
    set background(v) { real.background = v; },
    addShape: function (st, o = {}) { const n = createVirtualNode('shape', { shapeType: st, opts: o }, 0, 0); this.children.push(n); return n; },
    addText: function (t, o = {}) { const n = createVirtualNode('text', { text: t, opts: { fit: 'shrink', ...o } }, 0, 0); this.children.push(n); return n; },
    addImage: function (o = {}) { const n = createVirtualNode('image', { opts: o }, 0, 0); this.children.push(n); return n; },
    addTable: function (td, o = {}) { const n = createVirtualNode('table', { tableData: td, opts: o }, 0, 0); this.children.push(n); return n; },
    render: function () { this.children.forEach(ch => flattenNode(ch, real)); }
  };
  return vs;
};

// ── 组件 ──
let pn = 0;
function ns(bg) { const s = pres.addSlide(); s.background = { color: bg || C.white }; pn++; return s; }
function header(s, chip, title, sub) {
  s.addShape(pres.shapes.OVAL, { x: CONTENT_X, y: 0.35, w: 0.42, h: 0.42, fill: { color: C.primary }, line: { type: 'none' } });
  s.addText(chip, { x: CONTENT_X, y: 0.35, w: 0.42, h: 0.42, align: 'center', valign: 'middle', fontSize: 12, bold: true, color: C.white, fontFace: FB });
  s.addText(title, { x: CONTENT_X + 0.55, y: 0.27, w: 6.6, h: 0.55, fontSize: 22, bold: true, color: C.dark, fontFace: FT, charSpacing: 1.5 });
  if (sub) s.addText(sub, { x: CONTENT_X + 0.57, y: 0.8, w: 7.6, h: 0.28, fontSize: 10.5, color: C.muted, fontFace: FB });
  s.addText('BOL 管理系统使用说明', { x: 6.3, y: 0.38, w: 3.2, h: 0.24, fontSize: 8.5, color: C.muted, fontFace: FB, align: 'right' });
  if (pn > 1) s.addText(String(pn), { x: 9.42, y: 5.32, w: 0.4, h: 0.24, fontSize: 9, color: C.muted, fontFace: FB, align: 'right' });
}
function card(s, x, y, w, h, fill, line, r) {
  return s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: r === undefined ? 0.05 : r,
    fill: { color: fill || C.white }, line: line === undefined ? { color: C.rule, width: 0.75 } : line });
}
function chip(s, x, y, num, color, d) { const sz = d || 0.34;
  s.addShape(pres.shapes.OVAL, { x, y, w: sz, h: sz, fill: { color: color || C.primary }, line: { type: 'none' } });
  s.addText(String(num), { x, y, w: sz, h: sz, align: 'center', valign: 'middle', fontSize: 11, bold: true, color: C.white, fontFace: FB });
}
function arrowR(s, x, y, w, h, color) { s.addShape(pres.shapes.RIGHT_ARROW, { x, y, w: w || 0.28, h: h || 0.22, fill: { color: color || C.muted }, line: { type: 'none' } }); }
function arrowD(s, x, y, w, h, color) { s.addShape(pres.shapes.DOWN_ARROW, { x, y, w: w || 0.22, h: h || 0.26, fill: { color: color || C.muted }, line: { type: 'none' } }); }
function guide(s, text) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CONTENT_X, y: 5.02, w: CONTENT_W, h: 0.46, rectRadius: 0.04, fill: { color: C.warn }, line: { color: C.warnBd, width: 1, dashType: 'dash' } });
  s.addText([{ text: '✎ 撰写指引  ', options: { bold: true, color: C.warnTx, fontSize: 9 } },
    { text: text, options: { color: C.warnTx, fontSize: 9 } }],
    { x: CONTENT_X + 0.15, y: 5.02, w: CONTENT_W - 0.3, h: 0.46, fontFace: FB, valign: 'middle', fit: 'none' });
}
// 带边框的截图卡片
function screenshotCard(s, x, y, w, h, imgPath, label) {
  const cd = card(s, x, y, w, h, C.white, { color: C.rule, width: 1 }, 0.06);
  // 顶部标题栏
  cd.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0, y: 0, w: w, h: 0.34, rectRadius: 0.06, fill: { color: C.bg2 }, line: { type: 'none' } });
  cd.addText(label, { x: 0.12, y: 0.02, w: w - 0.24, h: 0.3, fontSize: 9, bold: true, color: C.dark, fontFace: FB, valign: 'middle' });
  // 截图（等比缩放，居中）
  cd.addImage({ path: imgPath, x: 0.04, y: 0.4, w: w - 0.08, h: h - 0.44 });
  return cd;
}

// ════════════════════════════════════════════
// P1 封面
// ════════════════════════════════════════════
(() => {
  const s = ns(C.dark);
  // 右侧首页截图（半透明叠加）
  s.addShape(pres.shapes.RECTANGLE, { x: 4.6, y: 0, w: 5.4, h: 5.625, fill: { color: '2A4A8C' }, line: { type: 'none' } });
  s.addImage({ path: S.home, x: 5.0, y: 0.6, w: 4.6, h: 4.4 });
  // 左侧装饰圆
  s.addShape(pres.shapes.OVAL, { x: 0.1, y: 3.8, w: 2.0, h: 2.0, fill: { color: C.primary, transparency: 60 }, line: { type: 'none' } });
  // 内容
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.1, w: 2.1, h: 0.32, rectRadius: 0.16, fill: { color: C.accent }, line: { type: 'none' } });
  s.addText('系统说明文档', { x: 0.6, y: 1.1, w: 2.1, h: 0.32, align: 'center', valign: 'middle', fontSize: 10, bold: true, color: C.white, fontFace: FB });
  s.addText('BOL 管理系统', { x: 0.58, y: 1.62, w: 5.5, h: 0.75, fontSize: 36, bold: true, color: C.white, fontFace: FT, charSpacing: 2.5 });
  s.addText('使用说明 · 架构与操作指南', { x: 0.62, y: 2.52, w: 5, h: 0.42, fontSize: 16, color: C.iceBlue, fontFace: FT, charSpacing: 1.5 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.62, y: 3.15, w: 1.2, h: 0.05, fill: { color: C.accent }, line: { type: 'none' } });
  s.addText('六大功能模块  ·  四类数据源  ·  双周期分析报告', { x: 0.62, y: 3.35, w: 5, h: 0.3, fontSize: 11, color: C.white, fontFace: FB });
  s.addText('适用对象：工厂 IE · 生产管理 · 系统管理员', { x: 0.62, y: 3.78, w: 5, h: 0.26, fontSize: 9.5, color: C.iceBlue, fontFace: FB });
  s.addText('版本 v1.0  ·  2026-10  ·  BOL 管理分析平台 v0.4', { x: 0.62, y: 4.88, w: 5, h: 0.18, fontSize: 8, color: C.iceBlue, fontFace: FB });
  s.render();
})();

// ════════════════════════════════════════════
// P2 目录
// ════════════════════════════════════════════
(() => {
  const s = ns();
  s.addText('目录', { x: CONTENT_X, y: 0.35, w: 2.5, h: 0.6, fontSize: 26, bold: true, color: C.dark, fontFace: FT, charSpacing: 2 });
  s.addText('CONTENTS', { x: CONTENT_X + 1.15, y: 0.52, w: 3, h: 0.35, fontSize: 12, color: C.muted, fontFace: FB, charSpacing: 1.5 });
  const items = [
    ['序', '如何下手 · 写作方法论', '四步下手法 / 组织原则', 'P3-4'],
    ['一', '系统概述', '首页导航 / 模块地图 / 角色权限', 'P5-7'],
    ['二', '核心概念与术语', 'BOL 三类型 / 维度 / KPI / 规则', 'P8-9'],
    ['三', '功能模块操作', '预算 BOL / 动态 BOL / 实测 CT / 跟踪', 'P10-14'],
    ['四', '分析中心与报告', '多维对比 / 报告中心 / 读法', 'P15-16'],
    ['五', '账号与系统管理', '个人设置 / 人员权限 / FAQ', 'P17-18'],
    ['六', '落地与检查清单', '培训计划 / 定稿自查', 'P19']
  ];
  items.forEach((it, i) => {
    const col = i < 4 ? 0 : 1;
    const row = i < 4 ? i : i - 4;
    const x = CONTENT_X + col * (4.5 + 0.2), y = 1.18 + row * 0.86;
    const cd = card(s, x, y, 4.5, 0.76, i === 0 ? C.light : C.white);
    chip(s, x + 0.16, y + 0.21, it[0], i === 0 ? C.accent : C.primary);
    cd.addText(it[1], { x: 0.62, y: 0.06, w: 2.9, h: 0.34, fontSize: 14, bold: true, color: C.dark, fontFace: FB });
    cd.addText(it[2], { x: 0.62, y: 0.4, w: 3.3, h: 0.3, fontSize: 9.5, color: C.muted, fontFace: FB });
    cd.addText(it[3], { x: 3.72, y: 0.22, w: 0.7, h: 0.3, fontSize: 10, bold: true, color: C.primary, fontFace: FB, align: 'right' });
  });
  guide(s, '目录即检索地图——按"用户任务"而非"系统菜单"组织；定稿前与 2-3 位真实用户核对任务清单是否完整。');
  s.render();
})();

// ════════════════════════════════════════════
// P3 序 · 四步下手法
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '序', '如何下手：四步写作法', '从零到一份可交付的系统说明');
  const steps = [
    ['1', '定读者', '工厂 IE / 生产管理 / 管理层 / 管理员', '详略与深度随读者定'],
    ['2', '理场景', '列出各角色高频任务清单', '任务决定章节顺序'],
    ['3', '搭骨架', '目录先行，每页定一个目标', '本架构 19 页即骨架'],
    ['4', '填内容', '步骤 + 截图 + 结果验证', '术语首现即定义']
  ];
  steps.forEach((st, i) => {
    const x = CONTENT_X + i * (2.16 + 0.14), y = 1.28, w = 2.16, h = 2.5;
    const cd = card(s, x, y, w, h, i === 3 ? C.light : C.white, { color: C.primary, width: 1 });
    chip(s, x + 0.14, y + 0.14, st[0], C.primary, 0.4);
    cd.addText(st[1], { x: 0.62, y: 0.18, w: 1.4, h: 0.36, fontSize: 15, bold: true, color: C.dark, fontFace: FB });
    cd.addText('▸ ' + st[2], { x: 0.15, y: 0.78, w: w - 0.3, h: 0.76, fontSize: 10, color: C.ink, fontFace: FB, fit: 'none' });
    cd.addText('▸ ' + st[3], { x: 0.15, y: 1.54, w: w - 0.3, h: 0.76, fontSize: 10, color: C.muted, fontFace: FB, fit: 'none' });
    if (i < 3) arrowR(s, x + w + 0.02, y + 1.16, 0.1, 0.2, C.primary);
  });
  const trap = card(s, CONTENT_X, 4.0, CONTENT_W, 0.62, C.lightR, { color: C.danger, width: 1 });
  trap.addText([{ text: '⚠ 常见陷阱  ', options: { bold: true, color: C.danger } },
  { text: '按系统菜单顺序罗列功能——读者找不到"我要做什么"。先任务后功能，是使用说明与功能手册的本质区别。', options: { color: C.ink } }],
    { x: 0.18, y: 0.08, w: CONTENT_W - 0.36, h: 0.46, fontSize: 10.5, fontFace: FB, valign: 'middle', fit: 'none' });
  guide(s, '四步法用于项目启动会：每步指定产出物与完成时间（建议 1+1+0.5+2 周），写入撰写排期。');
  s.render();
})();

// ════════════════════════════════════════════
// P4 序 · 组织原则
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '序', '内容组织原则：用户旅程优先', '同一套系统信息，两种讲法，效果截然不同');
  const bad = card(s, CONTENT_X, 1.25, 4.0, 2.5, C.white, { color: C.danger, width: 1.25 });
  bad.addText('✕ 避免 · 功能罗列式', { x: 0.2, y: 0.12, w: 3.6, h: 0.36, fontSize: 14, bold: true, color: C.danger, fontFace: FB });
  ['按系统菜单逐个介绍功能', '术语无解释直接使用', '纯文字描述、无界面截图', '读者需自己拼接操作路径'].forEach((t, i) => {
    bad.addText('· ' + t, { x: 0.22, y: 0.56 + i * 0.46, w: 3.6, h: 0.42, fontSize: 10.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  const good = card(s, CONTENT_X + 5.0, 1.25, 4.0, 2.5, C.lightG, { color: C.success, width: 1.25 });
  good.addText('✓ 推荐 · 用户旅程式', { x: 0.2, y: 0.12, w: 3.6, h: 0.36, fontSize: 14, bold: true, color: C.success, fontFace: FB });
  ['按"角色 → 任务 → 步骤 → 结果"组织', '术语首次出现即定义（见第二章）', '每个操作配界面截图 + 标注', 'FAQ 按任务场景检索'].forEach((t, i) => {
    good.addText('· ' + t, { x: 0.22, y: 0.56 + i * 0.46, w: 3.6, h: 0.42, fontSize: 10.5, color: C.ink, fontFace: FB, fit: 'none' });
  });
  arrowR(s, CONTENT_X + 4.1, 2.32, 0.8, 0.36, C.primary);
  const ex = card(s, CONTENT_X, 4.0, CONTENT_W, 0.62, C.light, { color: C.primary, width: 1 });
  ex.addText([{ text: '转化示例  ', options: { bold: true, color: C.primary } },
  { text: '「第三章 审批模块功能介绍」  ➜  「工厂 IE：如何提交一次 BOL 变更，并看到它反映在报告里」', options: { color: C.ink } }],
    { x: 0.18, y: 0.06, w: CONTENT_W - 0.36, h: 0.5, fontSize: 11, fontFace: FB, valign: 'middle', fit: 'none' });
  guide(s, '写作过程中随时自检："这一页在回答谁的什么任务？"答不上来时，该页应删或并入附录。');
  s.render();
})();

// ════════════════════════════════════════════
// P5 一、1.1 系统首页导航（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '一', '系统首页：模块导航地图', '第一章 · 1.1 ｜ 登录后第一屏就是全局入口');
  // 左侧：截图
  screenshotCard(s, CONTENT_X, 1.15, 5.3, 3.65, S.home, '门户首页 · 游客访问视图');
  // 右侧：说明
  const txt = card(s, CONTENT_X + 5.5, 1.15, 3.5, 3.65, C.white, { color: C.rule, width: 0.75 });
  txt.addText('页面结构', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.dark, fontFace: FB });
  const items = [
    ['顶部品牌区', 'BOL 公式 · 当前时间 · 用户信息'],
    ['核心模块', '综合看板 · 高 BOL 跟踪（2 个高频）'],
    ['工具模块', '预算 BOL / BOL 审批 / 实测 CT / 分析中心 / 系统管理'],
    ['底部版本条', 'v0.4 · 双库路由 · 改善闭环'],
    ['权限标识', '游客模式下受限模块显示"需登录"']
  ];
  items.forEach((it, i) => {
    chip(s, CONTENT_X + 5.5 + 0.18, 1.15 + 0.52 + i * 0.6, i + 1, C.primary, 0.24);
    txt.addText(it[0], { x: 0.52, y: 0.48 + i * 0.6, w: 1.6, h: 0.28, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
    txt.addText(it[1], { x: 0.52, y: 0.72 + i * 0.6, w: 2.8, h: 0.32, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  guide(s, '首页截图是用户的第一张系统地图——标注各区域名称与作用；不同角色看到的模块不同（权限）。');
  s.render();
})();

// ════════════════════════════════════════════
// P6 一、1.2 模块架构图
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '一', '系统模块架构：五源 → 双报告 → 三用户', '第一章 · 1.2 ｜ 数据流全景图');
  // 数据源层
  const srcs = ['Budget BOL', '动态 BOL', '实测 CT', 'IE KPI', '高 BOL 跟踪'];
  const srcW = 1.53, srcGap = 0.1, srcX0 = CONTENT_X + 0.95;
  srcs.forEach((t, i) => {
    const x = srcX0 + i * (srcW + srcGap);
    const cd = card(s, x, 1.3, srcW, 0.68, C.light, { color: C.primary, width: 1 });
    cd.addText(t, { x: 0.05, y: 0.02, w: srcW - 0.1, h: 0.64, fontSize: 10, bold: true, color: C.dark, fontFace: FB, align: 'center', valign: 'middle' });
  });
  s.addText('数据源层', { x: CONTENT_X, y: 1.42, w: 0.85, h: 0.44, fontSize: 10, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fill: { color: C.primary } });
  [2.48, 5.38, 8.28].forEach(x => arrowD(s, x, 2.02, 0.28, 0.28, C.muted));
  // 分析层
  const engs = [['季度分析报告', '异常识别导向'], ['年度分析报告', '结构对标导向']];
  engs.forEach((e, i) => {
    const x = CONTENT_X + 0.95 + 1.05 + i * 3.3;
    const cd = card(s, x, 2.4, 2.9, 0.76, C.dark, { color: C.dark, width: 0 });
    cd.addText(e[0], { x: 0.1, y: 0.06, w: 2.7, h: 0.34, fontSize: 12.5, bold: true, color: C.white, fontFace: FB, align: 'center' });
    cd.addText(e[1], { x: 0.1, y: 0.4, w: 2.7, h: 0.28, fontSize: 9, color: C.iceBlue, fontFace: FB, align: 'center' });
  });
  s.addText('分析层', { x: CONTENT_X, y: 2.56, w: 0.85, h: 0.44, fontSize: 10, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fill: { color: C.accent } });
  [2.48, 5.38, 8.28].forEach(x => arrowD(s, x, 3.24, 0.28, 0.28, C.muted));
  // 应用层
  const users = ['工厂 IE', '生产管理', '管理层'];
  users.forEach((u, i) => {
    const x = CONTENT_X + 0.95 + i * 2.78;
    const cd = card(s, x, 3.62, 2.48, 0.7, C.white, { color: C.success, width: 1 });
    cd.addText(u, { x: 0.05, y: 0.02, w: 2.38, h: 0.66, fontSize: 11, bold: true, color: C.dark, fontFace: FB, align: 'center', valign: 'middle' });
  });
  s.addText('应用层', { x: CONTENT_X, y: 3.74, w: 0.85, h: 0.44, fontSize: 10, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fill: { color: C.success } });
  // 底部说明
  const note = card(s, CONTENT_X, 4.6, CONTENT_W, 0.36, C.bg2, { color: C.rule, width: 0.5 });
  note.addText('系统特点：双库路由（HRDB 只读 + CMC 读写）· 多维度分析 · 改善闭环 · 可信度分级', { x: 0.2, y: 0.03, w: 8.6, h: 0.3, fontSize: 10, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });
  guide(s, '架构图模块名与系统首页逐一核对；箭头即真实数据流向，报告生成时点建议标注（季初 / 年初）。');
  s.render();
})();

// ════════════════════════════════════════════
// P7 一、1.3 角色与权限
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '一', '角色权限与使用场景矩阵', '第一章 · 1.3 ｜ 决定第三章各模块的详略与顺序');
  const hdr = { fill: { color: C.primary }, color: C.white, bold: true, align: 'center', valign: 'middle', fontFace: FB, fontSize: 10.5 };
  const cc = (o) => Object.assign({ valign: 'middle', fontFace: FB, fontSize: 9.5, color: C.ink }, o);
  const rows = [
    [{ text: '角色', options: hdr }, { text: '高频任务（TOP3）', options: hdr }, { text: '可访问模块', options: hdr }, { text: '频率', options: hdr }, { text: '说明章节', options: hdr }],
    [{ text: '工厂 IE', options: cc({ bold: true }) }, { text: '提交 BOL 变更 / 录入实测 CT / 月度 KPI', options: cc({ align: 'left' }) }, { text: '全部模块', options: cc() }, { text: '每周', options: cc({ align: 'center', color: C.danger, bold: true }) }, { text: '3.1 / 3.2 / 3.3', options: cc({ align: 'center' }) }],
    [{ text: '生产管理', options: cc({ bold: true }) }, { text: '看板总览 / 跟踪改善 / 报告复盘', options: cc({ align: 'left' }) }, { text: '看板 / 跟踪 / 报告 / 分析中心', options: cc() }, { text: '每月', options: cc({ align: 'center', color: C.accent, bold: true }) }, { text: '3.4 / 4', options: cc({ align: 'center' }) }],
    [{ text: '管理层', options: cc({ bold: true }) }, { text: 'KPI 速览 / 年度洞察 / 行动建议', options: cc({ align: 'left' }) }, { text: '看板 / 报告中心', options: cc() }, { text: '每季/年', options: cc({ align: 'center', color: C.success, bold: true }) }, { text: '4', options: cc({ align: 'center' }) }],
    [{ text: '游客', options: cc({ bold: true }) }, { text: '查看公开数据 / 了解系统', options: cc({ align: 'left' }) }, { text: '看板 / BOL 审批 / 实测 CT / 分析中心 / 报告', options: cc() }, { text: '按需', options: cc({ align: 'center' }) }, { text: '—', options: cc({ align: 'center' }) }],
    [{ text: '系统管理员', options: cc({ bold: true }) }, { text: '用户权限 / 数据口径 / 规则维护', options: cc({ align: 'left' }) }, { text: '全部 + 后台管理', options: cc() }, { text: '按需', options: cc({ align: 'center' }) }, { text: '5', options: cc({ align: 'center' }) }]
  ];
  s.addTable(rows, {
    x: CONTENT_X, y: 1.22, w: CONTENT_W, colW: [1.1, 3.3, 2.3, 0.8, 1.5],
    rowH: [0.42, 0.58, 0.58, 0.58, 0.58, 0.58],
    border: { type: 'solid', pt: 0.5, color: C.rule }, autoPage: false
  });
  s.addText('频率色标：红=每周 · 橙=每月 · 绿=每季/年 —— 频率越高，对应操作章节越详细', { x: CONTENT_X, y: 4.78, w: CONTENT_W, h: 0.26, fontSize: 9.5, color: C.muted, fontFace: FB, italic: true, fit: 'none' });
  guide(s, '访谈各角色代表 15 分钟补全"高频任务"列；矩阵中未出现的高频任务，须在第三章补充对应操作页。');
  s.render();
})();

// ════════════════════════════════════════════
// P8 二、2.1 BOL 三类型 + 公式
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '二', '核心概念：BOL 与三类型', '第二章 · 2.1 ｜ 全系统最基础的概念');
  // 顶部公式
  const fc = card(s, CONTENT_X, 1.18, CONTENT_W, 0.56, C.light, { color: C.primary, width: 1 });
  fc.addText([{ text: '核心公式  ', options: { bold: true, color: C.primary } },
  { text: 'BOL = CT × HC × (1+1/15) / OEE / 60   ', options: { color: C.dark, fontSize: 13, bold: true } },
  { text: '（单位：min / 台）', options: { color: C.muted, fontSize: 9 } }],
    { x: 0.2, y: 0.06, w: CONTENT_W - 0.4, h: 0.44, fontSize: 11, fontFace: FB, valign: 'middle', fit: 'none' });
  // 三类型
  const types = [
    ['Target', '产能规划目标', '来源：产能规划（ame_target）', '用途：产能与 HC 测算基准', '最宽松'],
    ['Achievable', '可达值', '来源：CT / HC 计算', '用途：改善潜力评估核心', '当前工程能力'],
    ['Budget', '年度预算', '来源：年度预算编制', '用途：财务对标与达成判定', '最严格']
  ];
  types.forEach((t, i) => {
    const x = CONTENT_X + i * (2.9 + 0.15), y = 1.92, w = 2.9, h = 2.1;
    const c = card(s, x, y, w, h, C.white, { color: C.primary, width: 1 });
    c.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.15, y: 0.14, w: 1.5, h: 0.4, rectRadius: 0.2, fill: { color: C.primary }, line: { type: 'none' } });
    c.addText(t[0], { x: 0.15, y: 0.14, w: 1.5, h: 0.4, fontSize: 13, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle' });
    c.addText(t[1], { x: 1.72, y: 0.2, w: 1.1, h: 0.32, fontSize: 11, bold: true, color: C.dark, fontFace: FB });
    [t[2], t[3], t[4]].forEach((tt, j) => {
      c.addText('· ' + tt, { x: 0.18, y: 0.66 + j * 0.46, w: w - 0.36, h: 0.42, fontSize: 9.5, color: C.muted, fontFace: FB, fit: 'none' });
    });
  });
  const rule = card(s, CONTENT_X, 4.2, CONTENT_W, 0.5, C.lightR, { color: C.danger, width: 1 });
  rule.addText('关键原则：三类型对比必须在同年份、同一批项目内进行（跨年项目组合不同，均值绝对值不可比）', { x: 0.2, y: 0.06, w: CONTENT_W - 0.4, h: 0.38, fontSize: 11, bold: true, color: C.danger, fontFace: FB, valign: 'middle', fit: 'none' });
  guide(s, '三类型是全系统口径基础，首次出现即定义；示例数值以真实系统为准（FA：Target 33.2 / Achievable 31.8 / Budget 23.0 min）。');
  s.render();
})();

// ════════════════════════════════════════════
// P9 二、2.2 维度 + KPI + 规则速查
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '二', '分析维度 · KPI · 业务规则速查', '第二章 · 2.2 ｜ 报告与分析的"统一语言"');
  // 左：四维度
  const dimCard = card(s, CONTENT_X, 1.18, 4.4, 3.5, C.white, { color: C.rule, width: 0.75 });
  dimCard.addText('四大分析维度', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  const dims = [
    ['工厂', '北京 · 上海 · 长春 · 重庆 · 广州 · 武汉', C.primary],
    ['工艺类型', 'FA（总装）· IHE / IHR（内饰）', C.accent],
    ['产品类型', 'Roof Type：BLTS / Fixed panel / Rollo / TLES multi …', C.success],
    ['时间', '月度 · 季度 · 财年', C.dark]
  ];
  dims.forEach((d, i) => {
    chip(s, CONTENT_X + 0.18, 1.18 + 0.44 + i * 0.62, i + 1, d[2], 0.26);
    dimCard.addText(d[0], { x: 0.56, y: 0.4 + i * 0.62, w: 1.5, h: 0.3, fontSize: 10.5, bold: true, color: C.dark, fontFace: FB });
    dimCard.addText(d[1], { x: 0.56, y: 0.7 + i * 0.62, w: 3.65, h: 0.34, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  dimCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.8, w: 4.4, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });
  dimCard.addText('核心对比规则：跨工厂对比须在「工艺×产品类型」组合内进行', { x: 0.18, y: 2.9, w: 4.04, h: 0.3, fontSize: 9, bold: true, color: C.dark, fontFace: FB, fit: 'none' });

  // 右上：KPI
  const kpiCard = card(s, CONTENT_X + 4.6, 1.18, 4.4, 1.6, C.white, { color: C.rule, width: 0.75 });
  kpiCard.addText('四项 IE KPI', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  const kpis = [
    ['BOL Reduction', '7.0%', C.success],
    ['Updates Rate', '80%', C.primary],
    ['ACT CT Rate', '85%', C.accent],
    ['LB 线平衡', '87%', '8E44AD']
  ];
  kpis.forEach((k, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.18 + col * 2.05, y = 0.46 + row * 0.55;
    kpiCard.addText(k[0], { x: x, y: y, w: 1.3, h: 0.24, fontSize: 9, color: C.muted, fontFace: FB });
    kpiCard.addText(k[1], { x: x, y: y + 0.22, w: 1.3, h: 0.28, fontSize: 13, bold: true, color: k[2], fontFace: FB });
  });

  // 右下：规则速查
  const ruleCard = card(s, CONTENT_X + 4.6, 2.92, 4.4, 1.76, C.white, { color: C.rule, width: 0.75 });
  ruleCard.addText('业务规则速查（3 条）', { x: 0.18, y: 0.08, w: 2.5, h: 0.28, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  const rules = [
    ['可信度分级', 'n≥5 且 ≥2 工厂 = 高可信；n≥3 且 ≥10 = 中可信'],
    ['近 2 倍异常', '比值 ∈ [1.8, 2.2] = 疑似漏/重复提交'],
    ['反公式达成率', 'ΣBudget / ΣAchievable < 100% = 达成（去项目数偏差）']
  ];
  rules.forEach((r, i) => {
    ruleCard.addText('▸ ' + r[0], { x: 0.18, y: 0.42 + i * 0.44, w: 1.4, h: 0.26, fontSize: 9.5, bold: true, color: C.dark, fontFace: FB });
    ruleCard.addText(r[1], { x: 1.62, y: 0.42 + i * 0.44, w: 2.65, h: 0.4, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });

  guide(s, '本章是全文口径的"单一事实源"：正文引用时统一指向第二章；任何规则变更须记录版本与生效日期。');
  s.render();
})();

// ════════════════════════════════════════════
// P10 三、3.1 预算 BOL（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '三', '预算 BOL 管理', '第三章 · 3.1 ｜ 年度预算三类型录入与维护');
  // 左侧：截图
  screenshotCard(s, CONTENT_X, 1.15, 5.3, 3.65, S.budget, '预算 BOL 模块 · 列表视图');
  // 右侧：操作要点
  const txt = card(s, CONTENT_X + 5.5, 1.15, 3.5, 3.65, C.white, { color: C.rule, width: 0.75 });
  txt.addText('核心操作', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.dark, fontFace: FB });
  const items = [
    ['筛选查询', '按工艺 / 工厂 / Roof Type / 财年筛选'],
    ['Excel 导入', '模板批量导入，自动校验字段'],
    ['三类型维护', 'Target / Achievable / Budget 独立编辑'],
    ['变更历史', '每次修改留痕，可追溯'],
    ['帮助中心', '内置字段说明与公式解释']
  ];
  items.forEach((it, i) => {
    chip(s, CONTENT_X + 5.5 + 0.18, 1.15 + 0.52 + i * 0.6, i + 1, C.primary, 0.24);
    txt.addText(it[0], { x: 0.52, y: 0.48 + i * 0.6, w: 1.4, h: 0.28, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
    txt.addText(it[1], { x: 0.52, y: 0.72 + i * 0.6, w: 2.8, h: 0.32, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  guide(s, '截图建议用红框标注 2-3 个关键操作区（筛选栏 / 导入按钮 / 三类型 Tab）；附 Excel 模板字段说明。');
  s.render();
})();

// ════════════════════════════════════════════
// P11 三、3.2 动态 BOL 审批（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '三', '动态 BOL 审批与多维分析', '第三章 · 3.2 ｜ 变更从提交到报告反映的完整链路');
  // 左侧：流程
  const flowCard = card(s, CONTENT_X, 1.15, 3.8, 3.65, C.white, { color: C.rule, width: 0.75 });
  flowCard.addText('审批流程', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  const steps = ['发起变更', '填写明细', '审批流转', '版本更新', '报告反映'];
  steps.forEach((st, i) => {
    const y = 0.42 + i * 0.46;
    flowCard.addShape(pres.shapes.OVAL, { x: 0.2, y: y + 0.04, w: 0.32, h: 0.32, fill: { color: i < 4 ? C.primary : C.success }, line: { type: 'none' } });
    flowCard.addText(String(i + 1), { x: 0.2, y: y + 0.04, w: 0.32, h: 0.32, fontSize: 11, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle' });
    flowCard.addText(st, { x: 0.64, y: y, w: 2.8, h: 0.4, fontSize: 10.5, color: C.dark, fontFace: FB, valign: 'middle' });
    if (i < 4) flowCard.addShape(pres.shapes.RECTANGLE, { x: 0.34, y: y + 0.32, w: 0.04, h: 0.14, fill: { color: C.rule }, line: { type: 'none' } });
  });
  // 流程下：关键特性
  flowCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.72, w: 3.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });
  flowCard.addText('关键特性', { x: 0.18, y: 2.78, w: 2, h: 0.24, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
  ['近 2 倍校验：提交实时提示异常', '多维筛选：工艺/工厂/RoofType/时间', '降幅统计：自动对比上一版本'].forEach((t, i) => {
    flowCard.addText('▸ ' + t, { x: 0.18, y: 3.02 + i * 0.22, w: 3.44, h: 0.2, fontSize: 8, color: C.muted, fontFace: FB, fit: 'none' });
  });

  // 右侧：截图
  screenshotCard(s, CONTENT_X + 4.0, 1.15, 5.0, 3.65, S.dynamic, 'BOL 审批模块 · 多维分析视图');
  guide(s, '截图标注重点：筛选区 / 数据列表 / 图表区；补充"驳回后如何修改重提"的分支场景说明。');
  s.render();
})();

// ════════════════════════════════════════════
// P12 三、3.3 实测 CT（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '三', '实测 CT 工时采集', '第三章 · 3.3 ｜ 瓶颈工时的录入、监控与异常');
  // 左：截图
  screenshotCard(s, CONTENT_X, 1.15, 5.3, 3.65, S.ct, '实测 CT 模块 · 数据视图');
  // 右：要点
  const txt = card(s, CONTENT_X + 5.5, 1.15, 3.5, 3.65, C.white, { color: C.rule, width: 0.75 });
  txt.addText('监控要点', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.dark, fontFace: FB });
  const items = [
    ['数据来源', '传感器采集 cycle time 原始数据'],
    ['瓶颈工位', '自动识别瓶颈工位，计算中位数'],
    ['120s 红线', '超标自动预警，纳入异常清单'],
    ['覆盖率', '有效记录 / 应采集产线，目标 85%'],
    ['趋势分析', '按月 / 季 / 年查看变化趋势']
  ];
  items.forEach((it, i) => {
    chip(s, CONTENT_X + 5.5 + 0.18, 1.15 + 0.52 + i * 0.6, i + 1, C.accent, 0.24);
    txt.addText(it[0], { x: 0.52, y: 0.48 + i * 0.6, w: 1.4, h: 0.28, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
    txt.addText(it[1], { x: 0.52, y: 0.72 + i * 0.6, w: 2.8, h: 0.32, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  guide(s, '补充：数据缺失的处理流程（谁补录 / 时限 / 留痕要求）；红线阈值与第二章 KPI 目标保持一致。');
  s.render();
})();

// ════════════════════════════════════════════
// P13 三、3.4 高 BOL 跟踪（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '三', '高 BOL 跟踪：改善闭环', '第三章 · 3.4 ｜ 问题识别 → 改善 → 验证 → 关闭');
  // 左：闭环流程
  const lc = card(s, CONTENT_X, 1.15, 3.8, 3.65, C.white, { color: C.rule, width: 0.75 });
  lc.addText('改善闭环流程', { x: 0.18, y: 0.1, w: 2.5, h: 0.3, fontSize: 12, bold: true, color: C.success, fontFace: FB });
  const loop = [
    ['问题识别', '超标 CT / 低 LB / 近 2 倍异常'],
    ['任务分配', '指定工厂 / 责任人 / 截止日期'],
    ['改善执行', '改善措施落地，更新 BOL 版本'],
    ['验证关闭', '数据验证后关闭，纳入报告']
  ];
  loop.forEach((it, i) => {
    const y = 0.52 + i * 0.7;
    lc.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.2, y: y, w: 3.4, h: 0.56, rectRadius: 0.28, fill: { color: C.lightG }, line: { type: 'none' } });
    lc.addText(String(i + 1), { x: 0.2, y: y, w: 0.56, h: 0.56, fontSize: 12, bold: true, color: C.success, fontFace: FB, align: 'center', valign: 'middle' });
    lc.addText(it[0], { x: 0.8, y: y + 0.02, w: 2.5, h: 0.26, fontSize: 10.5, bold: true, color: C.dark, fontFace: FB });
    lc.addText(it[1], { x: 0.8, y: y + 0.28, w: 2.8, h: 0.26, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
    if (i < 3) arrowD(s, CONTENT_X + 1.8, 1.15 + y + 0.56, 0.2, 0.14, C.success);
  });

  // 右：截图
  screenshotCard(s, CONTENT_X + 4.0, 1.15, 5.0, 3.65, S.tracking, '高 BOL 跟踪模块 · 改善项目列表');
  guide(s, '闭环是高 BOL 跟踪的核心价值——强调"不只是清单，是从发现到关闭的全流程管理"。');
  s.render();
})();

// ════════════════════════════════════════════
// P14 三、3.5 综合看板（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '三', '综合看板：跨数据源一览', '第三章 · 3.5 ｜ 首页第一个"核心模块"');
  // 上：截图（更大）
  screenshotCard(s, CONTENT_X, 1.15, 6.0, 3.65, S.dashboard, '综合看板 · 跨数据源汇总视图');
  // 右：要点
  const txt = card(s, CONTENT_X + 6.2, 1.15, 2.8, 3.65, C.white, { color: C.rule, width: 0.75 });
  txt.addText('看板内容', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 11.5, bold: true, color: C.dark, fontFace: FB });
  const items = [
    'BOL 分布概览（按工艺）',
    '跟踪状态统计',
    'KPI 达成速览',
    'Top 异常项目',
    '月度趋势图表'
  ];
  items.forEach((t, i) => {
    txt.addText('▸ ' + t, { x: 0.18, y: 0.46 + i * 0.52, w: 2.44, h: 0.46, fontSize: 9.5, color: C.ink, fontFace: FB, fit: 'none' });
  });
  txt.addShape(pres.shapes.RECTANGLE, { x: 0, y: 3.1, w: 2.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });
  txt.addText('适合角色：管理层速览 / 生产管理日常巡检', { x: 0.18, y: 3.2, w: 2.44, h: 0.35, fontSize: 8.5, color: C.muted, fontFace: FB, italic: true, fit: 'none' });
  guide(s, '看板是最高频访问的页面——重点标注 KPI 红绿灯、Top 异常入口、跟踪状态汇总三个核心区。');
  s.render();
})();

// ════════════════════════════════════════════
// P15 四、4.1 分析中心（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '四', '分析中心：多维对比分析', '第四章 · 4.1 ｜ 按维度组合深度钻取 BOL 差异');
  // 左：截图
  screenshotCard(s, CONTENT_X, 1.15, 5.5, 3.65, S.comp, '分析中心 · 多维对比分析视图');
  // 右：功能说明
  const txt = card(s, CONTENT_X + 5.7, 1.15, 3.3, 3.65, C.white, { color: C.rule, width: 0.75 });
  txt.addText('分析能力', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.dark, fontFace: FB });
  const items = [
    ['维度组合', '工艺 × Roof Type × 工厂 × 财年'],
    ['可视化', '柱状对比 + 箱线分布 + 趋势线'],
    ['可信度', '自动标记高/中/低可信等级'],
    ['数据导出', '分析结果可导出 Excel'],
    ['钻取', '点击柱图可下钻到项目明细']
  ];
  items.forEach((it, i) => {
    chip(s, CONTENT_X + 5.7 + 0.18, 1.15 + 0.52 + i * 0.6, i + 1, '8E44AD', 0.24);
    txt.addText(it[0], { x: 0.52, y: 0.48 + i * 0.6, w: 1.2, h: 0.28, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
    txt.addText(it[1], { x: 0.52, y: 0.72 + i * 0.6, w: 2.6, h: 0.32, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });
  guide(s, '分析中心是"数据探索"工具——说明常见分析场景（如 FA+BLTS 跨厂对比），降低使用门槛。');
  s.render();
})();

// ════════════════════════════════════════════
// P16 四、4.2 报告中心（真实截图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '四', '报告中心：季度 / 年度分析报告', '第四章 · 4.2 ｜ 系统自动生成的结构化分析报告');
  // 左：报告类型说明
  const lc = card(s, CONTENT_X, 1.15, 3.8, 3.65, C.white, { color: C.rule, width: 0.75 });
  lc.addText('两类报告', { x: 0.18, y: 0.1, w: 2, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });

  const qc = lc.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.18, y: 0.5, w: 3.44, h: 1.1, rectRadius: 0.08, fill: { color: C.light }, line: { color: C.primary, width: 1 } });
  qc.addText('季度分析报告', { x: 0.15, y: 0.08, w: 2, h: 0.3, fontSize: 11, bold: true, color: C.primary, fontFace: FB });
  qc.addText('导向：异常识别', { x: 0.15, y: 0.36, w: 3, h: 0.24, fontSize: 9, color: C.dark, fontFace: FB });
  qc.addText('内容：KPI 速览 / 异常清单 / 改善跟踪 / 行动建议', { x: 0.15, y: 0.58, w: 3.14, h: 0.44, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });

  const yc = lc.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.18, y: 1.72, w: 3.44, h: 1.1, rectRadius: 0.08, fill: { color: C.lightAcc }, line: { color: C.accent, width: 1 } });
  yc.addText('年度分析报告', { x: 0.15, y: 0.08, w: 2, h: 0.3, fontSize: 11, bold: true, color: C.accent, fontFace: FB });
  yc.addText('导向：结构对标', { x: 0.15, y: 0.36, w: 3, h: 0.24, fontSize: 9, color: C.dark, fontFace: FB });
  yc.addText('内容：多维现状 / 跨源洞察 / 标杆对比 / 综合建议', { x: 0.15, y: 0.58, w: 3.14, h: 0.44, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });

  lc.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.96, w: 3.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });
  lc.addText('三步阅读法', { x: 0.18, y: 3.02, w: 2, h: 0.22, fontSize: 10, bold: true, color: C.dark, fontFace: FB });
  ['① 先看管理层摘要 / 概览', '② 按工厂查异常清单', '③ 带走行动项与责任人'].forEach((t, i) => {
    lc.addText(t, { x: 0.18, y: 3.24 + i * 0.22, w: 3.44, h: 0.22, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
  });

  // 右：截图
  screenshotCard(s, CONTENT_X + 4.0, 1.15, 5.0, 3.65, S.reports, '报告中心 · 报告列表与下载');
  guide(s, '报告是系统分析能力的最终产出物——说明报告生成时机（季初 / 年初）、发布方式、历史版本查询。');
  s.render();
})();

// ════════════════════════════════════════════
// P17 五、5.1 账号与个人设置
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '五', '账号设置与系统登录', '第五章 · 5.1 ｜ 登录、个人信息、密码修改');
  // 左：登录页截图
  screenshotCard(s, CONTENT_X, 1.15, 4.6, 3.45, S.login, '登录页');
  // 右：账号设置截图
  screenshotCard(s, CONTENT_X + 4.8, 1.15, 4.2, 3.45, S.account, '账号设置页');

  // 底部要点
  const pts = card(s, CONTENT_X, 4.75, CONTENT_W, 0.22, C.bg2, { color: C.rule, width: 0.5 });
  pts.addText('登录：账号密码 / 游客访问（只读）/ 邮件找回  |  设置：基本信息 / 密码修改 / 所属工厂', { x: 0.2, y: 0.01, w: 8.6, h: 0.2, fontSize: 8.5, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });
  guide(s, '补充：首次登录强制修改密码、密码强度要求、账号锁定策略等安全规则（如有）。');
  s.render();
})();

// ════════════════════════════════════════════
// P18 五、5.2 FAQ 与数据规范
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '五', 'FAQ 与数据规范', '第五章 · 5.2 ｜ 高频问题 + 录入规范');
  const faq = card(s, CONTENT_X, 1.15, 4.6, 3.42, C.white, { color: C.primary, width: 1 });
  faq.addText('高频问题 TOP6', { x: 0.2, y: 0.12, w: 3, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  [
    '为什么我的项目没出现在跨工厂对比里？',
    '预算达成率为什么用"反公式"？',
    '提交时弹出"近 2 倍"提示是什么意思？',
    '报告里的 n 代表什么？为何有的组合不展示？',
    'CT 数据缺失的月份怎么处理？',
    'LB 为什么上限是 91%？'
  ].forEach((q, i) => {
    faq.addText('Q' + (i + 1) + '  ' + q, { x: 0.2, y: 0.5 + i * 0.47, w: 4.2, h: 0.42, fontSize: 9.5, color: C.ink, fontFace: FB, fit: 'none' });
  });

  const spec = card(s, CONTENT_X + 4.8, 1.15, 4.2, 3.42, C.white, { color: C.accent, width: 1 });
  spec.addText('数据录入规范', { x: 0.2, y: 0.12, w: 3, h: 0.3, fontSize: 12, bold: true, color: C.accent, fontFace: FB });
  [
    ['必填字段', 'project_code · line_nr · location · process_type'],
    ['提交时限', '变更发生后 5 个工作日内提报'],
    ['修正流程', '管理员通道修正 + 全程留痕'],
    ['口径一致性', '与第二章规则表联动，单一事实源'],
    ['Excel 导入', '模板必填字段校验，错误行提示']
  ].forEach((r, i) => {
    spec.addText(r[0], { x: 0.2, y: 0.56 + i * 0.58, w: 1.3, h: 0.54, fontSize: 10, bold: true, color: C.dark, fontFace: FB, fit: 'none' });
    spec.addText(r[1], { x: 1.55, y: 0.56 + i * 0.58, w: 2.5, h: 0.54, fontSize: 9, color: C.muted, fontFace: FB, fit: 'none' });
  });
  guide(s, 'FAQ 从用户工单 / 答疑记录提炼并每季更新；规范条目与 2.2 规则表联动，避免两处口径不一致。');
  s.render();
})();

// ════════════════════════════════════════════
// P19 六、落地计划与检查清单
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '六', '落地计划与定稿检查清单', '第六章 ｜ 从文档到用户真正会用');
  // 左：3 周落地计划
  const plan = card(s, CONTENT_X, 1.15, 4.6, 3.42, C.white, { color: C.primary, width: 1 });
  plan.addText('3 周落地计划', { x: 0.2, y: 0.12, w: 3, h: 0.3, fontSize: 12, bold: true, color: C.primary, fontFace: FB });
  const weeks = [
    ['第 1 周', '收集 5 位真实用户高频问题，充实 FAQ 与角色矩阵', '访谈 + 工单分析'],
    ['第 2 周', '截取各模块关键界面，补充标注与操作步骤', '截图 + 标注'],
    ['第 3 周', '试讲 2 场（工厂 IE + 管理层），按反馈迭代定稿', '试讲 + 迭代']
  ];
  weeks.forEach((w, i) => {
    const y = 0.56 + i * 0.9;
    plan.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.2, y: y, w: 0.8, h: 0.76, rectRadius: 0.06, fill: { color: C.primary }, line: { type: 'none' } });
    plan.addText(w[0], { x: 0.2, y: y + 0.18, w: 0.8, h: 0.4, fontSize: 11, bold: true, color: C.white, fontFace: FB, align: 'center' });
    plan.addText(w[1], { x: 1.1, y: y + 0.04, w: 3.3, h: 0.48, fontSize: 10, color: C.dark, fontFace: FB, fit: 'none' });
    plan.addText(w[2], { x: 1.1, y: y + 0.48, w: 3.3, h: 0.24, fontSize: 8.5, color: C.muted, fontFace: FB, italic: true, fit: 'none' });
  });

  // 右：检查清单
  const chk = card(s, CONTENT_X + 4.8, 1.15, 4.2, 3.42, C.lightG, { color: C.success, width: 1 });
  chk.addText('定稿自查清单', { x: 0.2, y: 0.12, w: 3, h: 0.3, fontSize: 12, bold: true, color: C.success, fontFace: FB });
  [
    '每个高频任务都有"步骤 + 截图"',
    '术语首次出现处有定义',
    '口径规则统一指向 2.2 速查',
    'FAQ 覆盖工单 TOP 问题',
    '报告导读与实际报告一致',
    '版本号 · 联系人 · 更新日期完整'
  ].forEach((t, i) => {
    chk.addShape(pres.shapes.OVAL, { x: 0.2, y: 0.56 + i * 0.46, w: 0.24, h: 0.24, fill: { color: C.white }, line: { color: C.success, width: 1.5 } });
    chk.addText(t, { x: 0.56, y: 0.54 + i * 0.46, w: 3.44, h: 0.3, fontSize: 9.5, color: C.ink, fontFace: FB, fit: 'none' });
  });

  // 底部
  const end = card(s, CONTENT_X, 4.7, CONTENT_W, 0.3, C.dark, { color: C.dark, width: 0 });
  end.addText('目标：让每一位用户在 3 页之内，找到属于自己任务的答案。', { x: 0.3, y: 0.02, w: 8.4, h: 0.26, fontSize: 10.5, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });
  guide(s, '清单用于定稿评审会逐项打勾；时间线的负责人与时间点写入项目计划并每周跟进。');
  s.render();
})();

// ════════════════════════════════════════════
// P20 四、4.3 年度报告架构（12 章逻辑图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '四', '年度报告架构：12 章分析逻辑', '第四章 · 4.3 ｜ 从覆盖范围到改善建议的完整链路');

  // 左列卡片背景
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CONTENT_X, y: 1.15, w: 4.3, h: 3.35, rectRadius: 0.06, fill: { color: C.white }, line: { color: C.rule, width: 0.75 } });
  s.addText('前半 · 覆盖与现状', { x: CONTENT_X + 0.2, y: 1.23, w: 3, h: 0.26, fontSize: 11, bold: true, color: C.primary, fontFace: FB });

  const front = [
    ['一', '分析范围与数据口径', '覆盖范围 / 数据源 / 可信度规则'],
    ['二', '年度概览', '审批 / WON / 改善目标 / 同比 / 工厂数'],
    ['三', '预算 BOL 三类型结构', 'Target / Achievable / Budget 对比'],
    ['四', '工艺×产品类型 BOL 总览', '均值 / Min-Max / 可信度'],
    ['五', '跨工厂 BOL 总览', 'FA / IHE / IHR 按工艺'],
    ['六', '跨工厂可比组合深度对比', '同产品类型内对比 + 高可信汇总']
  ];
  front.forEach((it, i) => {
    const yBase = 1.56 + i * 0.48;
    s.addShape(pres.shapes.OVAL, { x: CONTENT_X + 0.2, y: yBase + 0.02, w: 0.26, h: 0.26, fill: { color: C.primary }, line: { type: 'none' } });
    s.addText(it[0], { x: CONTENT_X + 0.2, y: yBase + 0.02, w: 0.26, h: 0.26, fontSize: 10, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle' });
    s.addText(it[1], { x: CONTENT_X + 0.54, y: yBase, w: 3.5, h: 0.24, fontSize: 9.5, bold: true, color: C.dark, fontFace: FB, fit: 'none' });
    s.addText(it[2], { x: CONTENT_X + 0.54, y: yBase + 0.22, w: 3.5, h: 0.22, fontSize: 8, color: C.muted, fontFace: FB, fit: 'none' });
  });

  // 右列卡片背景
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CONTENT_X + 4.5, y: 1.15, w: 4.5, h: 3.35, rectRadius: 0.06, fill: { color: C.white }, line: { color: C.rule, width: 0.75 } });
  s.addText('后半 · 趋势与改善', { x: CONTENT_X + 4.7, y: 1.23, w: 3, h: 0.26, fontSize: 11, bold: true, color: C.accent, fontFace: FB });

  const back = [
    ['七', '实际 vs 预算：年度改善目标达成', '达成分布 / 偏差 / 落后 Top10'],
    ['八', 'FY2025→FY2026 同项目变化', '改善 / 持平 / 恶化'],
    ['九', 'QWS 报价 vs 实际 BOL 覆盖', '覆盖比 / 口径待核实'],
    ['十', '实测 CT 年度稳定性', '月度瓶颈 CT 中位数趋势'],
    ['十一', 'IE KPI 达成速览', 'Reduction / Updates / ACT / LB'],
    ['十二', '综合洞察与改进建议', '核心洞察 / 标杆 / FY2027 行动']
  ];
  back.forEach((it, i) => {
    const yBase = 1.56 + i * 0.48;
    s.addShape(pres.shapes.OVAL, { x: CONTENT_X + 4.7, y: yBase + 0.02, w: 0.26, h: 0.26, fill: { color: C.accent }, line: { type: 'none' } });
    s.addText(it[0], { x: CONTENT_X + 4.7, y: yBase + 0.02, w: 0.26, h: 0.26, fontSize: 8.5, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle' });
    s.addText(it[1], { x: CONTENT_X + 5.04, y: yBase, w: 3.8, h: 0.24, fontSize: 9.5, bold: true, color: C.dark, fontFace: FB, fit: 'none' });
    s.addText(it[2], { x: CONTENT_X + 5.04, y: yBase + 0.22, w: 3.8, h: 0.22, fontSize: 8, color: C.muted, fontFace: FB, fit: 'none' });
  });

  // 中间箭头
  arrowR(s, CONTENT_X + 4.32, 2.7, 0.16, 0.3, C.primary);

  // 底部特点
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CONTENT_X, y: 4.68, w: CONTENT_W, h: 0.26, rectRadius: 0.04, fill: { color: C.bg2 }, line: { color: C.rule, width: 0.5 } });
  s.addText('年度报告特点：结构对标导向 · 跨年可比项目对比 · 高可信度优先（≥80% 规则） · 产出 FY 下一财年行动建议', { x: CONTENT_X + 0.2, y: 4.69, w: 8.6, h: 0.24, fontSize: 8.5, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });

  guide(s, '年度报告每章对应一个分析维度；建议在说明中配报告截图，标注各章在报告中的位置，方便用户快速定位。');
  s.render();
})();

// ════════════════════════════════════════════
// P21 四、4.4 季度报告架构（6 章逻辑图）
// ════════════════════════════════════════════
(() => {
  const s = ns();
  header(s, '四', '季度报告架构：6 章分析逻辑', '第四章 · 4.4 ｜ 聚焦当期执行跟踪与异常识别');

  // 6 章按 3×2 网格排列（全部绝对定位，不用嵌套容器）
  const chapters = [
    ['一', 'BOL KPI 总览', ['1.1 年度更新率', '1.2 各工厂达成率', '1.3 ACT CT 抓取率', '1.4 改善目标汇总'], C.primary],
    ['二', 'BOL 变更动态', ['2.1 月度审批趋势', '2.2 各工厂审批分布', '2.3 版本变化明细'], C.accent],
    ['三', '实测 CT 异常识别', ['3.1 各工厂瓶颈 CT', '3.2 超标产线 Top10'], C.success],
    ['四', '线平衡率异常识别', ['4.1 各工厂线平衡率', '4.2 低 LB 项目 Top10'], '8E44AD'],
    ['五', '可信度跨工厂对比', ['5.{n} 工厂间对比', '（仅 ≥80% 可信度组合）'], C.dark],
    ['六', '综合洞察与建议', ['6.1 核心洞察', '6.2 标杆与收敛空间', '6.3 下季度行动'], C.danger]
  ];
  const cw = 2.84, chh = 1.5, gapX = 0.14, gapY = 0.12;
  chapters.forEach((ch, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = CONTENT_X + col * (cw + gapX), y = 1.2 + row * (chh + gapY);
    // 卡片背景
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x, y: y, w: cw, h: chh, rectRadius: 0.06, fill: { color: C.white }, line: { color: ch[3], width: 1 } });
    // 章节圆标
    s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: y + 0.1, w: 0.38, h: 0.38, fill: { color: ch[3] }, line: { type: 'none' } });
    s.addText(ch[0], { x: x + 0.12, y: y + 0.1, w: 0.38, h: 0.38, fontSize: 13, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle' });
    // 章节标题
    s.addText(ch[1], { x: x + 0.58, y: y + 0.12, w: cw - 0.7, h: 0.34, fontSize: 11, bold: true, color: C.dark, fontFace: FB, valign: 'middle', fit: 'none' });
    // 子项
    ch[2].forEach((sub, j) => {
      s.addText('· ' + sub, { x: x + 0.15, y: y + 0.58 + j * 0.2, w: cw - 0.3, h: 0.18, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });
    });
  });

  // 底部特点
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CONTENT_X, y: 4.68, w: CONTENT_W, h: 0.26, rectRadius: 0.04, fill: { color: C.bg2 }, line: { color: C.rule, width: 0.5 } });
  s.addText('季度报告特点：异常识别导向 · 当期执行跟踪 · 月度/环比趋势 · 产出下季度改善行动项', { x: CONTENT_X + 0.2, y: 4.69, w: 8.6, h: 0.24, fontSize: 8.5, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });

  guide(s, '季度报告 6 章对应"KPI→变更→CT→LB→跨厂对比→建议"闭环；与年度报告共享建议模板，但聚焦当季可执行项。');
  s.render();
})();

// ════════════════════════════════════════════
// 输出
// ════════════════════════════════════════════
const OUT = String.raw`c:\WorkFile\D\OPEX\04-Digital_development\2026\IE系统完善开发\BOL管理系统\BOL管理系统使用说明_含真实界面.pptx`;
pres.writeFile({ fileName: OUT }).then(() => console.log('written:', OUT));

