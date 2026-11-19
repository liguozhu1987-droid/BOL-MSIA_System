/**
 * MSIA 共享样式常量 — Soft-Tech Business 设计系统
 *
 * 统一各页面重复定义的样式常量 (此前 techCardStyle / industrialBgStyle /
 * CornerMarker 在 5+ 个文件各自定义且色值漂移)。
 * 色值与 src/index.css CSS 变量、src/theme.ts token 保持同步。
 */
import type React from 'react';

/** 品牌色 */
export const BRAND = {
  primary: '#2E5CE6',
  primaryDeep: '#1E46C0',
  primaryLight: '#6B93F0',
  cyan: '#0FB5BA',
  teal: '#14B8A6',
  success: '#10B981',
  warning: '#F59E0B',
  danger: '#EF4444',
  orange: '#F97316',
  purple: '#8B5CF6',
  gray: '#94A3B8',
} as const;

/** 页面背景: 柔和蓝白渐变 */
export const industrialBgStyle: React.CSSProperties = {
  background:
    'radial-gradient(ellipse 50% 30% at 90% 0%, rgba(15, 181, 186, 0.045) 0%, transparent 65%),' +
    'radial-gradient(ellipse 45% 28% at 5% 5%, rgba(46, 92, 230, 0.05) 0%, transparent 65%),' +
    '#F4F7FC',
  minHeight: '100%',
};

/** 标准卡片: 柔和大圆角 + 多层柔和阴影 */
export const techCardStyle: React.CSSProperties = {
  border: '1px solid rgba(46, 92, 230, 0.10)',
  borderRadius: 14,
  boxShadow: '0 1px 3px rgba(27, 46, 116, 0.04), 0 4px 16px rgba(27, 46, 116, 0.05)',
  overflow: 'hidden',
  position: 'relative',
};

/** 卡片顶部柔光渐变条 (替代锐利角标) */
export const topGlowStyle: React.CSSProperties = {
  position: 'absolute',
  top: 0,
  left: 0,
  right: 0,
  height: 3,
  background: 'linear-gradient(90deg, rgba(46, 92, 230, 0.35) 0%, rgba(15, 181, 186, 0.35) 100%)',
  borderRadius: '14px 14px 0 0',
};

/** 角标装饰: 柔和渐变圆点 (保持旧接口 { color } 兼容) */
export const CornerMarker = ({ color = BRAND.primary }: { color?: string }) => (
  <div
    style={{
      position: 'absolute',
      top: 10,
      right: 10,
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: color,
      opacity: 0.4,
      filter: 'blur(0.5px)',
    }}
  />
);

/** 区块标题: 左侧柔和渐变胶囊条 */
export const sectionTitleStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  fontWeight: 600,
  fontSize: 15,
  color: '#1B2540',
};

/** 标题装饰条 (配合 sectionTitleStyle 使用) */
export const sectionBarStyle: React.CSSProperties = {
  width: 4,
  height: 16,
  borderRadius: 2,
  background: 'linear-gradient(180deg, #2E5CE6 0%, #0FB5BA 100%)',
};
