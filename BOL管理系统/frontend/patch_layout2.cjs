const fs = require('fs');
let src = fs.readFileSync('gen_bol_manual_v2.cjs', 'utf8');

// P1: 装饰圆再缩小并上移
src = src.replace(
  "s.addShape(pres.shapes.OVAL, { x: 0.2, y: 3.9, w: 2.0, h: 2.0, fill: { color: C.primary, transparency: 60 }, line: { type: 'none' } });",
  "s.addShape(pres.shapes.OVAL, { x: 0.3, y: 3.7, w: 1.6, h: 1.6, fill: { color: C.primary, transparency: 60 }, line: { type: 'none' } });"
);
// P1: 底部版本号再上移
src = src.replace(
  "s.addText('版本 v1.0  ·  2026-10  ·  BOL 管理分析平台 v0.4', { x: 0.62, y: 4.92, w: 5, h: 0.2, fontSize: 8.5, color: C.iceBlue, fontFace: FB });",
  "s.addText('版本 v1.0  ·  2026-10  ·  BOL 管理分析平台 v0.4', { x: 0.62, y: 4.88, w: 5, h: 0.18, fontSize: 8, color: C.iceBlue, fontFace: FB });"
);

// P11: 关键特性最后一条再缩小
src = src.replace(
  "['近 2 倍校验：提交实时提示异常', '多维筛选：工艺/工厂/RoofType/时间', '降幅统计：自动对比上一版本'].forEach((t, i) => {\n    flowCard.addText('▸ ' + t, { x: 0.18, y: 3.04 + i * 0.24, w: 3.44, h: 0.22, fontSize: 8.5, color: C.muted, fontFace: FB, fit: 'none' });",
  "['近 2 倍校验：提交实时提示异常', '多维筛选：工艺/工厂/RoofType/时间', '降幅统计：自动对比上一版本'].forEach((t, i) => {\n    flowCard.addText('▸ ' + t, { x: 0.18, y: 3.02 + i * 0.22, w: 3.44, h: 0.2, fontSize: 8, color: C.muted, fontFace: FB, fit: 'none' });"
);

fs.writeFileSync('gen_bol_manual_v2.cjs', src);
console.log('patched v2 OK');
