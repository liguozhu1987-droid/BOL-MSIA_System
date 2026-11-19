// 评分统一色调体系 (三档制: 红 / 黄 / 绿)
// 100% → 绿色 RGB(0,204,0)    #00CC00
// 75%  → 黄色 RGB(255,255,0)  #FFFF00
// 其余 → 红色 RGB(255,102,0)  #FF6600
// 全局所有涉及评分的模块均使用此色调, 保证一致性

// 标准色常量
export const SCORE_COLOR_GREEN = '#00CC00'; // 100%
export const SCORE_COLOR_YELLOW = '#FFFF00'; // 75%
export const SCORE_COLOR_RED = '#FF6600'; // 其余

// 7 档 Maturity 评分定义 (文字色 + 背景色)
export const MATURITY_LEVELS = [
  { score: 0.0, label: '0%', color: SCORE_COLOR_RED, bg: '#FFF1E8' },     // 红
  { score: 0.25, label: '25%', color: SCORE_COLOR_RED, bg: '#FFF1E8' },    // 红
  { score: 0.33, label: '33%', color: SCORE_COLOR_RED, bg: '#FFF1E8' },    // 红
  { score: 0.5, label: '50%', color: SCORE_COLOR_RED, bg: '#FFF1E8' },     // 红
  { score: 0.67, label: '67%', color: SCORE_COLOR_RED, bg: '#FFF1E8' },    // 红
  { score: 0.75, label: '75%', color: SCORE_COLOR_YELLOW, bg: '#FFFBE6' }, // 黄
  { score: 1.0, label: '100%', color: SCORE_COLOR_GREEN, bg: '#E9F9E9' },  // 绿
] as const;

// 评分档位标签映射 (score -> {label, title, color})
export const SCORE_LABEL_MAP: Record<number, { label: string; title: string; color: string }> = {
  0: { label: '0%', title: 'No Plan', color: SCORE_COLOR_RED },
  0.25: { label: '25%', title: 'Initial', color: SCORE_COLOR_RED },
  0.33: { label: '33%', title: 'Drafting', color: SCORE_COLOR_RED },
  0.5: { label: '50%', title: 'Partially Met', color: SCORE_COLOR_RED },
  0.67: { label: '67%', title: 'Mostly Met', color: SCORE_COLOR_RED },
  0.75: { label: '75%', title: 'Substantially Met', color: SCORE_COLOR_YELLOW },
  1.0: { label: '100%', title: 'Fully Met', color: SCORE_COLOR_GREEN },
};

// 档位判定 (含浮点容差): >=100% 绿, >=75% 黄, 其余红
const GREEN_EPS = 0.9995;
const YELLOW_EPS = 0.7495;

// 根据评分 (0~1) 返回标准色; 用于实心色块 / 徽章 / 图表柱 / 边框
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#bfbfbf';
  if (score >= GREEN_EPS) return SCORE_COLOR_GREEN; // 100% 绿
  if (score >= YELLOW_EPS) return SCORE_COLOR_YELLOW; // 75% 黄
  return SCORE_COLOR_RED; // 其余红
}

// 实心色块上的文字颜色: 黄色底对比度低用深色文字, 绿/红底用白色
export function scoreTagTextColor(score: number | null | undefined): string {
  if (score == null) return '#fff';
  if (score >= GREEN_EPS) return '#fff';
  if (score >= YELLOW_EPS) return '#1F2937'; // 深色文字保证黄底可读
  return '#fff';
}

// 浅色背景上的文字颜色: 与标准色同色系但加深保证可读性 (纯黄在白底不可见)
export function scoreTextColor(score: number | null | undefined): string {
  if (score == null) return '#bfbfbf';
  if (score >= GREEN_EPS) return '#008A00'; // 深绿
  if (score >= YELLOW_EPS) return '#A89000'; // 深黄
  return '#E85C00'; // 深橙红
}

// 评分强调卡片配色 (交通灯三档实心底, 与评分标签同一套标准色):
// 黄档 → 亮黄底黑字 (#FFFF00, 全局唯一亮黄); 红档 → 红底白字; 绿档 → 绿底白字
// 用于评分数值等需要强视觉提示的场景, 禁止纯黄做文字色 (浅底上不可见)
export function scoreCardStyle(score: number | null | undefined): { bg: string; text: string; border: string } {
  if (score == null) return { bg: '#fafafa', text: '#bfbfbf', border: '#e8e8e8' };
  if (score >= GREEN_EPS) return { bg: SCORE_COLOR_GREEN, text: '#fff', border: SCORE_COLOR_GREEN };
  if (score >= YELLOW_EPS) return { bg: SCORE_COLOR_YELLOW, text: '#1F2937', border: SCORE_COLOR_YELLOW };
  return { bg: SCORE_COLOR_RED, text: '#fff', border: SCORE_COLOR_RED };
}

// 根据评分 (0~1) 返回浅色背景色
export function scoreBg(score: number | null | undefined): string {
  if (score == null) return '#fafafa';
  if (score >= GREEN_EPS) return '#E9F9E9'; // 浅绿
  if (score >= YELLOW_EPS) return '#FFFBE6'; // 浅黄
  return '#FFF1E8'; // 浅红
}

// 根据评分百分比 (0~100) 返回标准色, 适用于图表柱状等实心元素
export function scoreColorByPercent(percent: number | null | undefined): string {
  if (percent == null) return '#bfbfbf';
  return scoreColor(percent / 100);
}

// 根据评分百分比 (0~100) 返回可读文字色, 适用于浅色背景上的文字
export function scoreTextColorByPercent(percent: number | null | undefined): string {
  if (percent == null) return '#bfbfbf';
  return scoreTextColor(percent / 100);
}
