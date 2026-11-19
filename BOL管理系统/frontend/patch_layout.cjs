// 修复 PPT 布局问题的补丁脚本
const fs = require('fs');
let src = fs.readFileSync('gen_bol_manual_v2.cjs', 'utf8');

// ===== P1 封面：修复装饰圆和底部版本号 =====
src = src.replace(
  "s.addShape(pres.shapes.OVAL, { x: -0.8, y: 3.6, w: 2.4, h: 2.4, fill: { color: C.primary, transparency: 60 }, line: { type: 'none' } });",
  "s.addShape(pres.shapes.OVAL, { x: 0.2, y: 3.9, w: 2.0, h: 2.0, fill: { color: C.primary, transparency: 60 }, line: { type: 'none' } });"
);
src = src.replace(
  "s.addText('版本 v1.0  ·  2026-10  ·  BOL 管理分析平台 v0.4', { x: 0.62, y: 4.98, w: 5, h: 0.24, fontSize: 9, color: C.iceBlue, fontFace: FB });",
  "s.addText('版本 v1.0  ·  2026-10  ·  BOL 管理分析平台 v0.4', { x: 0.62, y: 4.92, w: 5, h: 0.2, fontSize: 8.5, color: C.iceBlue, fontFace: FB });"
);

// ===== P9 维度页：修复底部规则文字溢出 =====
// 原来 dimCard 高 3.5，y=1.18，底部=4.68，guide 在 5.02 开始没问题
// 但核心对比规则文字和维度文字重叠 —— 减少间距
src = src.replace(
  "dims.forEach((d, i) => {\n    chip(s, CONTENT_X + 0.18, 1.18 + 0.56 + i * 0.72, i + 1, d[2], 0.28);\n    dimCard.addText(d[0], { x: 0.56, y: 0.52 + i * 0.72, w: 1.5, h: 0.32, fontSize: 11, bold: true, color: C.dark, fontFace: FB });\n    dimCard.addText(d[1], { x: 0.56, y: 0.82 + i * 0.72, w: 3.65, h: 0.4, fontSize: 9, color: C.muted, fontFace: FB, fit: 'none' });",
  "dims.forEach((d, i) => {\n    chip(s, CONTENT_X + 0.18, 1.18 + 0.44 + i * 0.62, i + 1, d[2], 0.26);\n    dimCard.addText(d[0], { x: 0.56, y: 0.4 + i * 0.62, w: 1.5, h: 0.3, fontSize: 10.5, bold: true, color: C.dark, fontFace: FB });\n    dimCard.addText(d[1], { x: 0.56, y: 0.7 + i * 0.62, w: 3.65, h: 0.34, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });"
);
// 底部规则文字上移
src = src.replace(
  "dimCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.96, w: 4.4, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  dimCard.addText('核心对比规则：跨工厂对比必须在「工艺 × 产品类型」组合内进行，消除产品结构差异', { x: 0.18, y: 3.08, w: 4.04, h: 0.36, fontSize: 9.5, bold: true, color: C.dark, fontFace: FB, fit: 'none' });",
  "dimCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.8, w: 4.4, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  dimCard.addText('核心对比规则：跨工厂对比须在「工艺×产品类型」组合内进行', { x: 0.18, y: 2.9, w: 4.04, h: 0.3, fontSize: 9, bold: true, color: C.dark, fontFace: FB, fit: 'none' });"
);

// ===== P11 动态 BOL：修复流程底部文本溢出 =====
// 减少步骤间距
src = src.replace(
  "const steps = ['发起变更', '填写明细', '审批流转', '版本更新', '报告反映'];\n  steps.forEach((st, i) => {\n    const y = 0.52 + i * 0.58;",
  "const steps = ['发起变更', '填写明细', '审批流转', '版本更新', '报告反映'];\n  steps.forEach((st, i) => {\n    const y = 0.42 + i * 0.46;"
);
src = src.replace(
  "if (i < 4) flowCard.addShape(pres.shapes.RECTANGLE, { x: 0.34, y: y + 0.36, w: 0.04, h: 0.22, fill: { color: C.rule }, line: { type: 'none' } });",
  "if (i < 4) flowCard.addShape(pres.shapes.RECTANGLE, { x: 0.34, y: y + 0.32, w: 0.04, h: 0.14, fill: { color: C.rule }, line: { type: 'none' } });"
);
// 分隔线上移，文字缩小
src = src.replace(
  "flowCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.6, w: 3.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  flowCard.addText('关键特性', { x: 0.18, y: 2.7, w: 2, h: 0.26, fontSize: 10.5, bold: true, color: C.dark, fontFace: FB });\n  ['近 2 倍校验：提交时实时提示异常', '多维筛选：工艺 / 工厂 / Roof Type / 时间', '降幅统计：自动对比上一版本'].forEach((t, i) => {\n    flowCard.addText('▸ ' + t, { x: 0.18, y: 3.0 + i * 0.3, w: 3.44, h: 0.28, fontSize: 9, color: C.muted, fontFace: FB, fit: 'none' });",
  "flowCard.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.72, w: 3.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  flowCard.addText('关键特性', { x: 0.18, y: 2.78, w: 2, h: 0.24, fontSize: 10, bold: true, color: C.dark, fontFace: FB });\n  ['近 2 倍校验：提交实时提示异常', '多维筛选：工艺/工厂/RoofType/时间', '降幅统计：自动对比上一版本'].forEach((t, i) => {\n    flowCard.addText('▸ ' + t, { x: 0.18, y: 3.04 + i * 0.24, w: 3.44, h: 0.22, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });"
);

// ===== P14 看板页：修复右侧文字与分割线重叠 =====
src = src.replace(
  "txt.addShape(pres.shapes.RECTANGLE, { x: 0, y: 3.0, w: 2.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  txt.addText('适合角色：管理层快速查看 / 生产管理日常巡检', { x: 0.18, y: 3.15, w: 2.44, h: 0.44, fontSize: 8.5, color: C.muted, fontFace: FB, italic: true, fit: 'none' });",
  "txt.addShape(pres.shapes.RECTANGLE, { x: 0, y: 3.1, w: 2.8, h: 0.01, fill: { color: C.rule }, line: { type: 'none' } });\n  txt.addText('适合角色：管理层速览 / 生产管理日常巡检', { x: 0.18, y: 3.2, w: 2.44, h: 0.35, fontSize: 8.5, color: C.muted, fontFace: FB, italic: true, fit: 'none' });"
);
// 减少右侧条目间距
src = src.replace(
  "items.forEach((t, i) => {\n    txt.addText('▸ ' + t, { x: 0.18, y: 0.48 + i * 0.56, w: 2.44, h: 0.5, fontSize: 9.5, color: C.ink, fontFace: FB, fit: 'none' });\n  });",
  "items.forEach((t, i) => {\n    txt.addText('▸ ' + t, { x: 0.18, y: 0.46 + i * 0.52, w: 2.44, h: 0.46, fontSize: 9.5, color: C.ink, fontFace: FB, fit: 'none' });\n  });"
);

// ===== P16 报告中心：修复左侧卡片底部溢出 =====
// 减少三步阅读法的间距
src = src.replace(
  "lc.addText('三步阅读法', { x: 0.18, y: 3.08, w: 2, h: 0.24, fontSize: 10.5, bold: true, color: C.dark, fontFace: FB });\n  ['① 先看管理层摘要 / 概览', '② 按工厂查异常清单', '③ 带走行动项与责任人'].forEach((t, i) => {\n    lc.addText(t, { x: 0.18, y: 3.32 + i * 0.26, w: 3.44, h: 0.24, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });",
  "lc.addText('三步阅读法', { x: 0.18, y: 3.02, w: 2, h: 0.22, fontSize: 10, bold: true, color: C.dark, fontFace: FB });\n  ['① 先看管理层摘要 / 概览', '② 按工厂查异常清单', '③ 带走行动项与责任人'].forEach((t, i) => {\n    lc.addText(t, { x: 0.18, y: 3.24 + i * 0.22, w: 3.44, h: 0.22, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });"
);

// ===== P17 账号页：修复底部要点条与截图重叠 =====
src = src.replace(
  "const pts = card(s, CONTENT_X, 4.6, CONTENT_W, 0.3, C.bg2, { color: C.rule, width: 0.5 });\n  pts.addText('登录方式：账号密码 · 游客访问（只读公开模块）· 支持忘记密码邮件找回  |  个人设置：基本信息 / 密码修改 / 所属工厂', { x: 0.2, y: 0.02, w: 8.6, h: 0.26, fontSize: 9, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });",
  "const pts = card(s, CONTENT_X, 4.75, CONTENT_W, 0.22, C.bg2, { color: C.rule, width: 0.5 });\n  pts.addText('登录：账号密码 / 游客访问（只读）/ 邮件找回  |  设置：基本信息 / 密码修改 / 所属工厂', { x: 0.2, y: 0.01, w: 8.6, h: 0.2, fontSize: 8.5, color: C.muted, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });"
);
// 减小截图高度
src = src.replace(
  "screenshotCard(s, CONTENT_X, 1.15, 4.6, 3.65, S.login, '登录页');\n  // 右：账号设置截图\n  screenshotCard(s, CONTENT_X + 4.8, 1.15, 4.2, 3.65, S.account, '账号设置页');",
  "screenshotCard(s, CONTENT_X, 1.15, 4.6, 3.45, S.login, '登录页');\n  // 右：账号设置截图\n  screenshotCard(s, CONTENT_X + 4.8, 1.15, 4.2, 3.45, S.account, '账号设置页');"
);

// ===== P19 落地计划：修复底部重叠 =====
src = src.replace(
  "const end = card(s, CONTENT_X, 4.6, CONTENT_W, 0.44, C.dark, { color: C.dark, width: 0 });\n  end.addText('目标：让每一位用户在 3 页之内，找到属于自己任务的答案。', { x: 0.3, y: 0.04, w: 8.4, h: 0.36, fontSize: 11.5, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });",
  "const end = card(s, CONTENT_X, 4.7, CONTENT_W, 0.3, C.dark, { color: C.dark, width: 0 });\n  end.addText('目标：让每一位用户在 3 页之内，找到属于自己任务的答案。', { x: 0.3, y: 0.02, w: 8.4, h: 0.26, fontSize: 10.5, bold: true, color: C.white, fontFace: FB, align: 'center', valign: 'middle', fit: 'none' });"
);

fs.writeFileSync('gen_bol_manual_v2.cjs', src);
console.log('patched OK');
