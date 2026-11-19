import type { ThemeConfig } from 'antd';

/**
 * MSIA 审核管理系统 — Ant Design 主题配置
 * 设计方向: Soft-Tech Business (柔和科技商务风)
 * 主色 #2E5CE6 深湖蓝, 辅助 #0FB5BA 青碧色
 * 设计原则: 大圆角、多层柔和阴影、精致玻璃质感、克制的科技点缀
 *
 * 注意: 色值与 src/index.css 中的 CSS 变量保持同步
 */
export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#2E5CE6',
    colorInfo: '#2E5CE6',
    colorSuccess: '#10B981',
    colorWarning: '#F59E0B',
    colorError: '#EF4444',
    colorLink: '#2E5CE6',
    borderRadius: 10,
    fontSize: 14,
    colorBgLayout: '#F4F7FC',
    colorTextBase: '#1B2540',
    colorBorder: 'rgba(46, 92, 230, 0.14)',
    colorBorderSecondary: 'rgba(46, 92, 230, 0.08)',
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif",
    wireframe: false,
    boxShadow: '0 2px 8px rgba(27, 46, 116, 0.06)',
    boxShadowSecondary: '0 8px 24px rgba(27, 46, 116, 0.10)',
  },
  components: {
    Layout: {
      headerBg: 'rgba(255, 255, 255, 0.82)',
      siderBg: 'transparent',
      bodyBg: '#F4F7FC',
      headerHeight: 60,
      headerPadding: '0 24px',
    },
    Menu: {
      itemSelectedBg: 'rgba(46, 92, 230, 0.08)',
      itemSelectedColor: '#2E5CE6',
      itemActiveBg: 'rgba(15, 181, 186, 0.05)',
      itemHoverBg: 'rgba(46, 92, 230, 0.04)',
      itemHeight: 42,
      iconSize: 16,
      itemMarginInline: 10,
      itemBorderRadius: 10,
    },
    Card: {
      headerBg: 'transparent',
      headerFontSize: 15,
      paddingLG: 22,
      boxShadowTertiary: '0 1px 3px rgba(27, 46, 116, 0.05)',
      borderRadiusLG: 14,
    },
    Table: {
      headerBg: 'rgba(46, 92, 230, 0.03)',
      headerColor: '#5D6B8A',
      rowHoverBg: 'rgba(46, 92, 230, 0.03)',
      borderColor: 'rgba(46, 92, 230, 0.08)',
      cellPaddingBlock: 12,
      cellPaddingInline: 16,
      headerBorderRadius: 10,
    },
    Button: {
      fontWeight: 500,
      primaryShadow: '0 4px 12px rgba(46, 92, 230, 0.24)',
      borderRadius: 10,
      controlHeight: 34,
    },
    Input: {
      activeShadow: '0 0 0 3px rgba(46, 92, 230, 0.08)',
      borderRadius: 10,
    },
    Tag: {
      defaultBg: 'rgba(46, 92, 230, 0.05)',
      borderRadiusSM: 6,
    },
    Modal: {
      titleFontSize: 16,
      borderRadiusLG: 14,
    },
    Statistic: {
      titleFontSize: 13,
      contentFontSize: 28,
    },
    Select: {
      borderRadius: 10,
    },
    DatePicker: {
      borderRadius: 10,
    },
    Tabs: {
      itemActiveColor: '#2E5CE6',
      inkBarColor: '#2E5CE6',
      itemSelectedColor: '#2E5CE6',
      itemHoverColor: '#6B93F0',
    },
    Badge: {
      dotSize: 6,
    },
    Divider: {
      colorSplit: 'rgba(46, 92, 230, 0.10)',
    },
    Tooltip: {
      borderRadius: 8,
    },
    Dropdown: {
      borderRadiusLG: 12,
    },
    Checkbox: {
      borderRadiusSM: 5,
    },
    Progress: {
      defaultColor: '#2E5CE6',
    },
    Alert: {
      borderRadiusLG: 12,
    },
    Message: {
      borderRadiusLG: 12,
    },
  },
};

/** 共享调色板: 图表与状态色 (与 CSS 变量同步) */
export const PALETTE = {
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
