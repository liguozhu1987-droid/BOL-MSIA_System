import dayjs from 'dayjs';

// 日期格式化：null/undefined/空字符串返回空，绝不使用占位默认值
export function formatDate(
  date: string | Date | null | undefined,
  format = 'YYYY-MM-DD'
): string {
  if (date === null || date === undefined || date === '') {
    return '';
  }
  const d = dayjs(date);
  if (!d.isValid()) {
    return '';
  }
  return d.format(format);
}

// 日期时间格式化
export function formatDateTime(
  date: string | Date | null | undefined,
  format = 'YYYY-MM-DD HH:mm:ss'
): string {
  return formatDate(date, format);
}

// 得分格式化：null/undefined 返回空字符串
export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) {
    return '';
  }
  return String(score);
}

// 通用数字格式化：null/undefined 返回空字符串
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '';
  }
  return String(value);
}

// 安全文本：null/undefined 返回空字符串
export function formatText(value: string | null | undefined): string {
  if (value === null || value === undefined) {
    return '';
  }
  return value;
}
