/**
 * 全局字体常量 — 单一事实来源
 *
 * 字体体系 (Soft-Tech Business):
 * - UI 文本/标签/按钮: 统一无衬线系统栈 (theme.ts fontFamily / index.css --tech-font-sans)
 * - 数据数字 (评分/统计值/编号/日期): 统一等宽栈 NUM_FONT, 数字对齐、科技感
 *
 * 注意: ECharts canvas 渲染无法解析 CSS 变量, 因此内联样式与图表共用此字面量常量;
 * 与 index.css 中 --tech-font-mono 的定义保持一致。
 */
export const NUM_FONT =
  "'Cascadia Code', 'Fira Code', 'SF Mono', Consolas, 'Courier New', monospace";
