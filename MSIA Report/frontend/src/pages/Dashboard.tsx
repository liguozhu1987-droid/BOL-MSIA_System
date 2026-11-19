import { useState, useEffect, useMemo, useCallback } from 'react';
import { Card, Col, Row, Typography, Spin, Tag, Empty, Drawer, Table, Statistic, Segmented, App, Button, Space, Tooltip, Collapse, Modal } from 'antd';
import {
  ProjectOutlined,
  BugOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  TrophyOutlined,
  ReloadOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  FilterOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import { http } from '@/api/client';
import { scoreTextColorByPercent } from '@/utils/scoreColor';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text } = Typography;

// ============ 类型定义 ============
interface FactoryScoreItem {
  plant: string;
  avg_score: number;
  project_count: number;
  review_count: number;
}
interface ProjectScoreItem {
  project_id: number;
  plan_id?: string;
  project_name: string;
  plant: string;
  owner_name: string;
  avg_score: number;
  review_count: number;
}
interface IssueStatItem {
  plant: string;
  total: number;
  h_count: number;
  m_count: number;
  l_count: number;
  closed: number;
  close_rate: number;
}
interface OverdueItem {
  dimension: string;
  dimension_type: string;
  plant: string;
  overdue_count: number;
  total_open: number;
}
interface DashboardSummary {
  total_projects: number;
  total_issues: number;
  total_closed: number;
  total_overdue: number;
  avg_score: number | null;
}
interface DashboardAnalytics {
  summary: DashboardSummary;
  factory_scores: FactoryScoreItem[];
  project_scores: ProjectScoreItem[];
  issue_stats: IssueStatItem[];
  overdue_by_plant: OverdueItem[];
  overdue_by_owner: OverdueItem[];
}
interface DrilldownData {
  project: { id: number; name: string; plant: string };
  phase_scores: { phase_code: string; avg_score: number; count: number }[];
  item_scores: {
    item_no: string; phase_code: string; score: number;
    result_text: string; status: string; comments: string;
  }[];
  issue_summary: { total: number; closed: number; overdue: number };
}
interface FactoryProject {
  project_id: number;
  plan_id?: string;
  project_name: string;
  plant: string;
  owner_name: string;
  avg_score: number;
  review_count: number;
}
interface PlantIssue {
  id: number;
  issue_no: string;
  title: string;
  owner_name: string;
  owner_company: string | null;
  severity: string;
  status: string;
  due_date: string | null;
  phase_code: string | null;
  project_id: number | null;
  project_name: string;
  is_overdue: boolean;
}

// ============ 颜色常量 (与 styles/shared BRAND 保持同步) ============
const COLORS = {
  primary: '#2E5CE6',
  success: '#10B981',
  danger: '#EF4444',
  gray: '#94A3B8',
};

// 柱形图渐变端点色 (参照用户提供的柱形图色调: 上浅下深)
const GRADIENT_RED = { top: '#FFB8B3', bottom: '#EE5A4A' };    // 警示色: 红色渐变 (高警示)
const GRADIENT_RED_LIGHT = { top: '#FFD5D0', bottom: '#F58573' }; // 警示色: 浅红渐变 (中警示)
const GRADIENT_BLUE = { top: '#E2F2FE', bottom: '#4BAAF7' };   // 正常色: 浅蓝色渐变
const LINK_BLUE = '#3393DB';                                   // 折线/文字用深蓝 (取自参考图)

// 垂直渐变 (柱顶浅 -> 柱底深)
const barGradientV = (top: string, bottom: string) => ({
  type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1,
  colorStops: [
    { offset: 0, color: top },
    { offset: 1, color: bottom },
  ],
});

// 水平渐变 (左浅 -> 右深)
const barGradientH = (left: string, right: string) => ({
  type: 'linear' as const, x: 0, y: 0, x2: 1, y2: 0,
  colorStops: [
    { offset: 0, color: left },
    { offset: 1, color: right },
  ],
});

// 评分柱形颜色 (百分比 0~100): >=75% 正常浅蓝渐变, <75% 警示红渐变
const scoreBarGradient = (percent: number | null | undefined) =>
  percent != null && percent >= 75
    ? barGradientV(GRADIENT_BLUE.top, GRADIENT_BLUE.bottom)
    : barGradientV(GRADIENT_RED.top, GRADIENT_RED.bottom);

// 评分统一格式化: 百分比保留 1 位小数 (如 62.3%)
const fmtScore = (v: number | null | undefined): string => {
  if (v == null || Number.isNaN(Number(v))) return '--';
  return `${Number(v).toFixed(1)}%`;
};

// 评分改进分析项
interface ScoreImprovementItem {
  plan_id: string;
  project_name: string;
  plant: string;
  phase_code: string;
  item_id: number;
  item_name: string;
  item_no: string;
  first_score: number;
  latest_score: number;
  improvement: number;
  review_count: number;
}

// 评分改进分析 - 评审历史明细记录
interface ScoreHistoryRecord {
  seq: number;
  review_id: number;
  score: number | null;
  result_text: string;
  comments: string;
  status: string;
  reviewer_name: string;
  submitted_at: string | null;
  created_at: string | null;
}
interface ScoreImprovementHistory {
  plan_id: string;
  project_name: string;
  plant: string;
  phase_code: string;
  item_id: number;
  item_name: string;
  item_no: string;
  records: ScoreHistoryRecord[];
  first_score: number | null;
  latest_score: number | null;
  improvement: number | null;
}

// ============ 主页面 ============
export default function Dashboard() {
  const { message } = App.useApp();
  const [data, setData] = useState<DashboardAnalytics | null>(null);
  const [loading, setLoading] = useState(false);
  const [overdueView, setOverdueView] = useState<string>('plant');

  // 下钻状态
  const [factoryDrillPlant, setFactoryDrillPlant] = useState<string | null>(null);
  const [factoryProjects, setFactoryProjects] = useState<FactoryProject[]>([]);
  const [factoryDrillLoading, setFactoryDrillLoading] = useState(false);

  const [issueDrillPlant, setIssueDrillPlant] = useState<string | null>(null);
  const [plantIssues, setPlantIssues] = useState<PlantIssue[]>([]);
  const [issueDrillLoading, setIssueDrillLoading] = useState(false);
  const [issueFilter, setIssueFilter] = useState<string>('all');
  const [issueGroupBy, setIssueGroupBy] = useState<string>('none');

  const [projectDrilldown, setProjectDrilldown] = useState<DrilldownData | null>(null);
  const [projectDrillOpen, setProjectDrillOpen] = useState(false);
  const [projectDrillLoading, setProjectDrillLoading] = useState(false);

  // 评分改进分析
  const [scoreImprovement, setScoreImprovement] = useState<ScoreImprovementItem[]>([]);
  const [scoreImprovementLoading, setScoreImprovementLoading] = useState(false);

  // 评分改进分析 - 评审历史明细弹窗
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyDetail, setHistoryDetail] = useState<ScoreImprovementHistory | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await http.get<DashboardAnalytics>('/dashboard/analytics');
      setData(res);
      // 并行加载评分改进分析
      setScoreImprovementLoading(true);
      http.get<{ items: ScoreImprovementItem[]; total: number }>('/dashboard/score-improvement')
        .then((r) => setScoreImprovement(r.items || []))
        .catch(() => {})
        .finally(() => setScoreImprovementLoading(false));
    } catch {
      message.error('看板数据加载失败');
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // 工厂下钻
  const handleFactoryClick = async (plant: string) => {
    setFactoryDrillPlant(plant);
    setFactoryDrillLoading(true);
    try {
      const res = await http.get<{ plant: string; projects: FactoryProject[] }>(
        `/dashboard/factory/${encodeURIComponent(plant)}/projects`
      );
      setFactoryProjects(res.projects || []);
    } catch {
      message.error('工厂数据加载失败');
      setFactoryProjects([]);
    } finally {
      setFactoryDrillLoading(false);
    }
  };

  // 问题清单下钻
  const handleIssueChartClick = async (plant: string) => {
    setIssueDrillPlant(plant);
    setIssueFilter('all');
    setIssueDrillLoading(true);
    try {
      const res = await http.get<{ plant: string; total: number; issues: PlantIssue[] }>(
        `/dashboard/plant/${encodeURIComponent(plant)}/issues?status=all`
      );
      setPlantIssues(res.issues || []);
    } catch {
      message.error('问题清单加载失败');
      setPlantIssues([]);
    } finally {
      setIssueDrillLoading(false);
    }
  };

  // 问题筛选
  const handleIssueFilterChange = async (filter: string) => {
    setIssueFilter(filter);
    if (!issueDrillPlant) return;
    setIssueDrillLoading(true);
    try {
      const res = await http.get<{ plant: string; total: number; issues: PlantIssue[] }>(
        `/dashboard/plant/${encodeURIComponent(issueDrillPlant)}/issues?status=${filter}`
      );
      setPlantIssues(res.issues || []);
    } catch {
      setPlantIssues([]);
    } finally {
      setIssueDrillLoading(false);
    }
  };

  // 项目下钻 (出错时显示空数据而非报错)
  // 支持两种查询方式: project_id > 0 (本地 Project.Id) 或 project_id=0 + plan_id (HRDB 关联)
  const handleProjectDrilldown = async (projectId: number, planId?: string) => {
    setProjectDrillOpen(true);
    setProjectDrillLoading(true);
    try {
      const url = planId
        ? `/dashboard/project/${projectId}/drilldown?plan_id=${encodeURIComponent(planId)}`
        : `/dashboard/project/${projectId}/drilldown`;
      const res = await http.get<DrilldownData>(url);
      setProjectDrilldown(res);
    } catch {
      // 不弹错误提示, 显示空结构 (符合"没数据也不报错"要求)
      setProjectDrilldown({
        project: { id: projectId, name: '', plant: '' },
        phase_scores: [],
        item_scores: [],
        issue_summary: { total: 0, closed: 0, overdue: 0 },
      });
    } finally {
      setProjectDrillLoading(false);
    }
  };

  // 评分改进分析 - 点击行查看该检查项的评审历史明细 (整改前后数据来源)
  const handleImprovementRowClick = async (record: ScoreImprovementItem) => {
    setHistoryOpen(true);
    setHistoryLoading(true);
    setHistoryDetail(null);
    try {
      const res = await http.get<ScoreImprovementHistory>(
        `/dashboard/score-improvement/history?plan_id=${encodeURIComponent(record.plan_id)}&item_id=${record.item_id}`
      );
      setHistoryDetail(res);
    } catch {
      message.error('评审历史明细加载失败');
      setHistoryOpen(false);
    } finally {
      setHistoryLoading(false);
    }
  };

  // ---- 图表 1: 工厂综合 MSIA 评分 (水平柱形图, Y轴=工厂代号, 评分以百分比展示) ----
  const factoryScoreOption: EChartsOption = useMemo(() => {
    const scores = (data?.factory_scores || []).slice().reverse();
    // avg_score 为 0~1 小数, 转为 0~100 百分比 (保留 1 位小数, 柱长与 x 轴 max=100 匹配)
    const toPct = (v: number) => Number(((Number(v) || 0) * 100).toFixed(1));
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(46,92,230,0.12)',
        textStyle: { color: '#0F172A', fontSize: 12 },
        formatter: (params: any) => {
          const item = scores[params[0]?.dataIndex];
          if (!item) return '';
          return `<b>${item.plant}</b><br/>平均分: <b style="color:#2E5CE6">${fmtScore(toPct(item.avg_score))}</b><br/>项目数: ${item.project_count}<br/>评审记录: ${item.review_count}<br/><i style="color:#3393DB">点击查看项目明细</i>`;
        },
      },
      grid: { left: 48, right: 56, top: 20, bottom: 24 },
      xAxis: {
        type: 'value',
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(46,92,230,0.04)', type: 'dashed' } },
        axisLabel: {
          color: '#94A3B8',
          fontSize: 11,
          fontFamily: NUM_FONT,
          formatter: '{value}%',
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: scores.map((s) => s.plant),
        axisLine: { lineStyle: { color: 'rgba(46,92,230,0.1)' } },
        axisLabel: { color: '#475569', fontSize: 13, fontWeight: 600 },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: scores.map((s) => ({
            value: toPct(s.avg_score),
            itemStyle: {
              borderRadius: [0, 6, 6, 0],
              // 正常色: 浅蓝色渐变 (左浅 -> 右深)
              color: barGradientH(GRADIENT_BLUE.top, GRADIENT_BLUE.bottom),
            },
          })),
          barWidth: 22,
          label: {
            show: true,
            position: 'right',
            color: '#4BAAF7',
            fontSize: 13,
            fontWeight: 600,
            fontFamily: NUM_FONT,
            formatter: (p: any) => fmtScore(p.value),
          },
          emphasis: {
            itemStyle: { shadowBlur: 12, shadowColor: 'rgba(46,92,230,0.3)' },
          },
        },
      ],
    };
  }, [data]);

  // ---- 图表 2: 问题数量与关闭率 (美化组合图) ----
  const issueComboOption: EChartsOption = useMemo(() => {
    const stats = data?.issue_stats || [];
    // L-低 使用正常色浅蓝渐变
    const L_COLOR_BOTTOM = GRADIENT_BLUE.bottom;
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', crossStyle: { color: 'rgba(46,92,230,0.2)' } },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(46,92,230,0.12)',
        textStyle: { color: '#0F172A', fontSize: 12 },
        formatter: (params: any) => {
          const item = stats[params[0]?.dataIndex];
          if (!item) return '';
          let html = `<b>${item.plant}</b><br/>`;
          html += `总数: <b>${item.total}</b><br/>`;
          html += `<span style="color:${GRADIENT_RED.bottom}">H</span>: ${item.h_count} | <span style="color:${GRADIENT_RED_LIGHT.bottom}">M</span>: ${item.m_count} | <span style="color:${L_COLOR_BOTTOM}">L</span>: ${item.l_count}<br/>`;
          html += `已关闭: <b>${item.closed}</b><br/>`;
          html += `关闭率: <b style="color:${LINK_BLUE}">${(Number(item.close_rate || 0) * 100).toFixed(1)}%</b><br/>`;
          html += `<i style="color:${LINK_BLUE}">点击查看问题清单</i>`;
          return html;
        },
      },
      legend: {
        data: [
          { name: 'H 严重', icon: 'circle' },
          { name: 'M 中等', icon: 'circle' },
          { name: 'L 低', icon: 'circle' },
          { name: '关闭率', icon: 'circle' },
        ],
        // 图例居中置顶, 避免与右上角"关闭率"轴名称及折线标签重叠
        top: 0, left: 'center',
        textStyle: { color: '#64748B', fontSize: 11 },
        itemWidth: 8, itemHeight: 8, itemGap: 14,
      },
      grid: { left: 44, right: 52, top: 48, bottom: 28 },
      xAxis: {
        type: 'category',
        data: stats.map((s) => s.plant),
        axisLine: { lineStyle: { color: 'rgba(46,92,230,0.1)' } },
        axisLabel: { color: '#475569', fontSize: 12, fontWeight: 500 },
        axisTick: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '问题数',
          nameTextStyle: { color: '#94A3B8', fontSize: 10, padding: [0, 0, 0, 30] },
          splitLine: { lineStyle: { color: 'rgba(46,92,230,0.04)', type: 'dashed' } },
          axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: NUM_FONT },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: 'value',
          name: '关闭率',
          max: 100,
          nameTextStyle: { color: '#94A3B8', fontSize: 10, padding: [0, 30, 0, 0] },
          splitLine: { show: false },
          axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: NUM_FONT, formatter: '{value}%' },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      series: [
        {
          name: 'H 严重',
          type: 'bar',
          stack: 'issue',
          data: stats.map((s) => s.h_count),
          itemStyle: {
            // 警示色: 红色渐变
            color: barGradientV(GRADIENT_RED.top, GRADIENT_RED.bottom),
          },
          barWidth: 28,
        },
        {
          name: 'M 中等',
          type: 'bar',
          stack: 'issue',
          data: stats.map((s) => s.m_count),
          itemStyle: {
            // 警示色: 浅红渐变 (中警示, 区别于 H 的深红)
            color: barGradientV(GRADIENT_RED_LIGHT.top, GRADIENT_RED_LIGHT.bottom),
          },
          barWidth: 28,
        },
        {
          name: 'L 低',
          type: 'bar',
          stack: 'issue',
          data: stats.map((s) => s.l_count),
          itemStyle: {
            // 正常色: 浅蓝色渐变
            color: barGradientV(GRADIENT_BLUE.top, GRADIENT_BLUE.bottom),
            borderRadius: [5, 5, 0, 0],
          },
          barWidth: 28,
        },
        {
          name: '关闭率',
          type: 'line',
          yAxisIndex: 1,
          data: stats.map((s) => Number(((Number(s.close_rate) || 0) * 100).toFixed(1))),
          itemStyle: { color: LINK_BLUE, borderColor: '#fff', borderWidth: 2 },
          lineStyle: { color: LINK_BLUE, width: 3, shadowColor: 'rgba(51,147,219,0.4)', shadowBlur: 10 },
          symbol: 'circle',
          symbolSize: 9,
          label: {
            show: true,
            position: 'top',
            color: LINK_BLUE,
            fontSize: 11,
            fontWeight: 600,
            fontFamily: NUM_FONT,
            formatter: (p: any) => fmtScore(p.value),
            distance: 6,
          },
          z: 10,
        },
      ],
    };
  }, [data]);

  // ---- 图表 3: 项目 MSIA 分值 ----
  const projectScoreOption: EChartsOption = useMemo(() => {
    const projects = (data?.project_scores || []).slice(0, 20);
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(46,92,230,0.12)',
        textStyle: { color: '#0F172A', fontSize: 12 },
        formatter: (params: any) => {
          const item = projects[params[0]?.dataIndex];
          if (!item) return '';
          return `<b>${item.project_name}</b><br/>工厂: ${item.plant}<br/>责任人: ${item.owner_name}<br/>平均分: <b>${fmtScore(item.avg_score)}</b><br/>评审数: ${item.review_count}<br/><i style="color:#3393DB">点击查看评审明细</i>`;
        },
      },
      grid: { left: 40, right: 24, top: 20, bottom: 70 },
      xAxis: {
        type: 'category',
        data: projects.map((p) => p.project_name.length > 10 ? p.project_name.substring(0, 10) + '...' : p.project_name),
        axisLine: { lineStyle: { color: 'rgba(46,92,230,0.1)' } },
        axisLabel: { color: '#64748B', fontSize: 10, rotate: 35, interval: 0 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(46,92,230,0.04)', type: 'dashed' } },
        axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: NUM_FONT },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: projects.map((p) => ({
            value: p.avg_score,
            itemStyle: {
              borderRadius: [4, 4, 0, 0],
              // 评分柱: >=75% 浅蓝渐变 (正常), <75% 红渐变 (警示)
              color: scoreBarGradient(p.avg_score),
            },
          })),
          barWidth: 28,
          label: {
            show: true,
            position: 'top',
            fontSize: 11,
            fontFamily: NUM_FONT,
            color: '#475569',
            formatter: (p: any) => fmtScore(p.value),
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(46,92,230,0.3)' },
          },
        },
      ],
    };
  }, [data]);

  // ---- 图表 4: 问题超期分析 ----
  const overdueOption: EChartsOption = useMemo(() => {
    const items = overdueView === 'plant' ? (data?.overdue_by_plant || []) : (data?.overdue_by_owner || []);
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(46,92,230,0.12)',
        textStyle: { color: '#0F172A', fontSize: 12 },
        formatter: (params: any) => {
          const item = items[params[0]?.dataIndex];
          if (!item) return '';
          const rate = item.total_open > 0 ? Math.round(item.overdue_count / item.total_open * 100) : 0;
          return `<b>${item.dimension}</b><br/>${overdueView === 'owner' ? '工厂: ' + item.plant + '<br/>' : ''}超期数: <b style="color:#EF4444">${item.overdue_count}</b><br/>未关闭总数: ${item.total_open}<br/>超期率: ${rate}%`;
        },
      },
      grid: { left: 40, right: 24, top: 20, bottom: 50 },
      xAxis: {
        type: 'category',
        data: items.map((s) => s.dimension.length > 8 ? s.dimension.substring(0, 8) + '...' : s.dimension),
        axisLine: { lineStyle: { color: 'rgba(46,92,230,0.1)' } },
        axisLabel: { color: '#475569', fontSize: 11, rotate: items.length > 6 ? 30 : 0, interval: 0 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(46,92,230,0.04)', type: 'dashed' } },
        axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: NUM_FONT },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: items.map((s) => ({
            value: s.overdue_count,
            itemStyle: {
              borderRadius: [4, 4, 0, 0],
              // 超期>5 深红渐变 (高警示) | 1~5 浅红渐变 (中警示) | 0 正常浅蓝渐变
              color: s.overdue_count > 5
                ? barGradientV(GRADIENT_RED.top, GRADIENT_RED.bottom)
                : s.overdue_count > 0
                  ? barGradientV(GRADIENT_RED_LIGHT.top, GRADIENT_RED_LIGHT.bottom)
                  : barGradientV(GRADIENT_BLUE.top, GRADIENT_BLUE.bottom),
            },
          })),
          barWidth: 30,
          label: {
            show: true,
            position: 'top',
            color: '#EF4444',
            fontSize: 12,
            fontWeight: 600,
            fontFamily: NUM_FONT,
          },
        },
      ],
    };
  }, [data, overdueView]);

  // 工厂下钻图表
  const factoryProjectOption: EChartsOption = useMemo(() => {
    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(255,255,255,0.96)',
        borderColor: 'rgba(46,92,230,0.12)',
        textStyle: { color: '#0F172A', fontSize: 12 },
        formatter: (params: any) => {
          const item = factoryProjects[params[0]?.dataIndex];
          if (!item) return '';
          return `<b>${item.project_name}</b><br/>责任人: ${item.owner_name}<br/>平均分: <b>${fmtScore(item.avg_score)}</b><br/>评审数: ${item.review_count}<br/><i style="color:#3393DB">点击查看评审明细</i>`;
        },
      },
      grid: { left: 40, right: 24, top: 20, bottom: 70 },
      xAxis: {
        type: 'category',
        data: factoryProjects.map((p) => p.project_name.length > 10 ? p.project_name.substring(0, 10) + '...' : p.project_name),
        axisLine: { lineStyle: { color: 'rgba(46,92,230,0.1)' } },
        axisLabel: { color: '#64748B', fontSize: 10, rotate: 35, interval: 0 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value', max: 100,
        splitLine: { lineStyle: { color: 'rgba(46,92,230,0.04)', type: 'dashed' } },
        axisLabel: { color: '#94A3B8', fontSize: 11, fontFamily: NUM_FONT },
        axisLine: { show: false }, axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: factoryProjects.map((p) => ({
          value: p.avg_score,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            // 评分柱: >=75% 浅蓝渐变 (正常), <75% 红渐变 (警示)
            color: scoreBarGradient(p.avg_score),
          },
        })),
        barWidth: 28,
        label: { show: true, position: 'top', fontSize: 11, fontFamily: NUM_FONT, color: '#475569', formatter: (p: any) => fmtScore(p.value) },
      }],
    };
  }, [factoryProjects]);

  // 统计卡片
  const summary = data?.summary;
  const statCards = [
    { title: '项目总数', value: summary?.total_projects ?? 0, icon: <ProjectOutlined />, color: COLORS.primary, bg: 'rgba(46,92,230,0.06)', border: 'rgba(46,92,230,0.12)' },
    { title: '问题总数', value: summary?.total_issues ?? 0, icon: <BugOutlined />, color: COLORS.danger, bg: 'rgba(238,90,74,0.06)', border: 'rgba(238,90,74,0.15)' },
    { title: '已关闭', value: summary?.total_closed ?? 0, icon: <CheckCircleOutlined />, color: COLORS.success, bg: 'rgba(16,185,129,0.06)', border: 'rgba(16,185,129,0.15)', suffix: summary && summary.total_issues > 0 ? ` (${Math.round(summary.total_closed / summary.total_issues * 100)}%)` : '' },
    { title: '超期问题', value: summary?.total_overdue ?? 0, icon: <WarningOutlined />, color: COLORS.danger, bg: 'rgba(238,90,74,0.06)', border: 'rgba(238,90,74,0.15)' },
    { title: '平均评分', value: summary?.avg_score != null ? Number(summary.avg_score).toFixed(1) : '--', icon: <TrophyOutlined />, color: '#3393DB', bg: 'rgba(51,147,219,0.06)', border: 'rgba(51,147,219,0.15)', suffix: summary?.avg_score != null ? '%' : '' },
  ];

  // 问题清单表格列
  const issueColumns = [
    { title: '问题编号', dataIndex: 'issue_no', key: 'issue_no', width: 150 },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    { title: '所属项目', dataIndex: 'project_name', key: 'project_name', width: 140, ellipsis: true },
    {
      title: '严重度', dataIndex: 'severity', key: 'severity', width: 70,
      render: (v: string) => {
        // 与"问题数量与关闭率"图表色调一致: H 深红 / M 浅红 / L 浅蓝
        const styleMap: Record<string, React.CSSProperties> = {
          H: { color: '#EE5A4A', borderColor: '#EE5A4A', background: 'rgba(238,90,74,0.08)' },
          M: { color: '#F58573', borderColor: '#F58573', background: 'rgba(245,133,115,0.08)' },
          L: { color: '#4BAAF7', borderColor: '#4BAAF7', background: 'rgba(75,170,247,0.08)' },
        };
        return <Tag style={styleMap[v]}>{v}</Tag>;
      },
    },
    { title: '责任人', dataIndex: 'owner_name', key: 'owner_name', width: 100 },
    { title: '阶段', dataIndex: 'phase_code', key: 'phase_code', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string, record: PlantIssue) => {
        if (record.is_overdue) return <Tag color="red">超期</Tag>;
        const colors: Record<string, string> = { open: 'default', in_progress: 'processing', pending_verification: 'warning', closed: 'success' };
        return <Tag color={colors[v] || 'default'}>{v}</Tag>;
      },
    },
    { title: '截止日期', dataIndex: 'due_date', key: 'due_date', width: 110 },
  ];

  // 下钻明细表格列
  const drilldownColumns = [
    { title: '阶段', dataIndex: 'phase_code', key: 'phase_code', width: 80 },
    { title: '编号', dataIndex: 'item_no', key: 'item_no', width: 80 },
    {
      title: '评分', dataIndex: 'score', key: 'score', width: 70,
      render: (v: number) => (
        <Text strong style={{ color: scoreTextColorByPercent(v), fontFamily: NUM_FONT }}>{fmtScore(v)}</Text>
      ),
    },
    { title: '结果', dataIndex: 'result_text', key: 'result_text', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        const colors: Record<string, string> = { draft: 'default', submitted: 'processing', confirmed: 'success' };
        return <Tag color={colors[v] || 'default'}>{v}</Tag>;
      },
    },
    { title: '评审意见', dataIndex: 'comments', key: 'comments', ellipsis: true },
  ];

  return (
    <Spin spinning={loading}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 3, height: 20, background: `linear-gradient(180deg, ${COLORS.primary} 0%, ${LINK_BLUE} 100%)`, borderRadius: 1 }} />
          <Title level={4} style={{ margin: 0 }}>MSIA 综合看板</Title>
          <div className="tech-badge">
            <div style={{ width: 4, height: 4, borderRadius: '50%', background: LINK_BLUE, boxShadow: `0 0 4px ${LINK_BLUE}` }} />
            LIVE
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新数据</Button>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {statCards.map((card, index) => (
          <Col xs={12} sm={8} lg={4} xl={4} key={index}>
            <Card className="tech-card-hover" style={{ borderRadius: 6, border: `1px solid ${card.border}`, overflow: 'hidden', position: 'relative', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', animation: `tech-fade-up 0.5s ease-out ${index * 0.06}s both` }} styles={{ body: { padding: 16 } }}>
              <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: card.color, boxShadow: `2px 0 8px ${card.color}33` }} />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 11, color: '#64748B', marginBottom: 4, letterSpacing: 0.5, fontFamily: NUM_FONT, textTransform: 'uppercase' }}>{card.title}</div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: '#0F172A', fontVariantNumeric: 'tabular-nums', fontFamily: NUM_FONT }}>{card.value}<span style={{ fontSize: 12, fontWeight: 400, color: '#94A3B8', marginLeft: 2 }}>{card.suffix || ''}</span></div>
                </div>
                <div style={{ width: 40, height: 40, borderRadius: 6, background: card.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: card.color, fontSize: 18 }}>{card.icon}</div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 图表 1 + 图表 2 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card className="tech-scanline" style={{ borderRadius: 6, border: '1px solid rgba(46,92,230,0.08)', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', height: '100%' }}
            title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 3, height: 14, background: COLORS.primary }} /><Text strong style={{ fontSize: 13 }}>各工厂综合 MSIA 评分</Text></div>}
            extra={<Tooltip title="点击柱形图可下钻到项目明细"><Tag style={{ fontFamily: NUM_FONT, fontSize: 10, cursor: 'pointer' }}>可下钻</Tag></Tooltip>}
          >
            {data && data.factory_scores.length > 0 ? (
              <ReactECharts option={factoryScoreOption} style={{ height: 300 }}
                onEvents={{ click: (params: any) => {
                  const scores = (data?.factory_scores || []).slice().reverse();
                  const item = scores[params.dataIndex];
                  if (item) handleFactoryClick(item.plant);
                }}}
              />
            ) : <Empty description="暂无评分数据" style={{ marginTop: 80 }} />}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card className="tech-scanline" style={{ borderRadius: 6, border: '1px solid rgba(46,92,230,0.08)', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', height: '100%' }}
            title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 3, height: 14, background: LINK_BLUE }} /><Text strong style={{ fontSize: 13 }}>问题数量与关闭率 (按工厂 x HML)</Text></div>}
            extra={<Tooltip title="点击柱形图可查看问题清单"><Tag style={{ fontFamily: NUM_FONT, fontSize: 10, cursor: 'pointer' }}>可下钻</Tag></Tooltip>}
          >
            {data && data.issue_stats.length > 0 ? (
              <ReactECharts option={issueComboOption} style={{ height: 300 }}
                onEvents={{ click: (params: any) => {
                  const item = data.issue_stats[params.dataIndex];
                  if (item) handleIssueChartClick(item.plant);
                }}}
              />
            ) : <Empty description="暂无问题数据" style={{ marginTop: 80 }} />}
          </Card>
        </Col>
      </Row>

      {/* 图表 3: 项目 MSIA 分值 */}
      <Card className="tech-scanline" style={{ borderRadius: 6, border: '1px solid rgba(46,92,230,0.08)', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', marginTop: 16 }}
        title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 3, height: 14, background: GRADIENT_BLUE.bottom }} /><Text strong style={{ fontSize: 13 }}>各项目 MSIA 分值 (点击可下钻查看评审明细)</Text></div>}
        extra={<Tag style={{ fontFamily: NUM_FONT, fontSize: 10 }}>Top 20</Tag>}
      >
        {data && data.project_scores.length > 0 ? (
          <ReactECharts option={projectScoreOption} style={{ height: 340 }}
            onEvents={{ click: (params: any) => {
              const projects = (data?.project_scores || []).slice(0, 20);
              const item = projects[params.dataIndex];
              if (item) handleProjectDrilldown(item.project_id, item.plan_id);
            }}}
          />
        ) : <Empty description="暂无项目评分数据" style={{ marginTop: 80 }} />}
      </Card>

      {/* 图表 4: 问题超期分析 */}
      <Card className="tech-scanline" style={{ borderRadius: 6, border: '1px solid rgba(46,92,230,0.08)', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', marginTop: 16 }}
        title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 3, height: 14, background: COLORS.danger }} /><Text strong style={{ fontSize: 13 }}>问题超期分析</Text></div>}
        extra={<Segmented size="small" value={overdueView} onChange={(v) => setOverdueView(v as string)} options={[{ value: 'plant', label: '按工厂' }, { value: 'owner', label: '按责任人' }]} />}
      >
        {data && ((overdueView === 'plant' && data.overdue_by_plant.length > 0) || (overdueView === 'owner' && data.overdue_by_owner.length > 0)) ? (
          <ReactECharts option={overdueOption} style={{ height: 300 }} />
        ) : <Empty description="暂无超期数据" style={{ marginTop: 80 }} />}
      </Card>

      {/* 图表 5: 评分改进分析 (整改前后评分差异) */}
      <Card className="tech-scanline" style={{ borderRadius: 6, border: '1px solid rgba(46,92,230,0.08)', background: 'rgba(255,255,255,0.8)', backdropFilter: 'blur(8px)', marginTop: 16 }}
        title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 3, height: 14, background: COLORS.primary }} /><Text strong style={{ fontSize: 13 }}>评分改进分析 (整改前后评分差异)</Text></div>}
        extra={<Tooltip title="首次评分 = 该检查项第一次已提交评审; 整改后评分 = 最新一次评审。点击行可查看每次评分的明细记录"><Tag style={{ fontFamily: NUM_FONT, fontSize: 10, cursor: 'pointer' }}>点击行查看明细</Tag></Tooltip>}
      >
        {scoreImprovementLoading ? (
          <div style={{ textAlign: 'center', paddingTop: 40 }}><Spin size="large" /></div>
        ) : scoreImprovement.length > 0 ? (
          <Table<ScoreImprovementItem>
            rowKey={(r) => `${r.plan_id}-${r.item_id}`}
            dataSource={scoreImprovement}
            size="small"
            pagination={{ pageSize: 10, showSizeChanger: false }}
            scroll={{ x: 900 }}
            onRow={(r) => ({ onClick: () => handleImprovementRowClick(r), style: { cursor: 'pointer' } })}
            columns={[
              {
                title: '项目', dataIndex: 'project_name', key: 'project_name', width: 180,
                render: (v, r) => <div><Text strong style={{ fontSize: 12 }}>{v}</Text><div><Tag style={{ fontSize: 10 }}>{r.plant}</Tag></div></div>,
              },
              { title: '阶段', dataIndex: 'phase_code', key: 'phase_code', width: 80, render: (v) => <Tag color="blue" style={{ fontSize: 10 }}>{v}</Tag> },
              { title: '检查项', dataIndex: 'item_name', key: 'item_name', width: 200, render: (v, r) => <Text style={{ fontSize: 11 }}>{v}<br/><Text type="secondary" style={{ fontSize: 10 }}>{r.item_no}</Text></Text> },
              {
                title: '首次评分', dataIndex: 'first_score', key: 'first_score', width: 90, align: 'center' as const,
                render: (v: number) => <Text style={{ color: scoreTextColorByPercent(v), fontWeight: 700, fontFamily: NUM_FONT }}>{fmtScore(v)}</Text>,
              },
              {
                title: '整改后评分', dataIndex: 'latest_score', key: 'latest_score', width: 90, align: 'center' as const,
                render: (v: number) => <Text style={{ color: scoreTextColorByPercent(v), fontWeight: 700, fontFamily: NUM_FONT }}>{fmtScore(v)}</Text>,
              },
              {
                title: '提升', dataIndex: 'improvement', key: 'improvement', width: 80, align: 'center' as const,
                render: (v: number) => <Tag color={v > 0 ? 'success' : v < 0 ? 'error' : 'default'} style={{ fontWeight: 700 }}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</Tag>,
              },
              { title: '评分次数', dataIndex: 'review_count', key: 'review_count', width: 70, align: 'center' as const, render: (v: number) => <Text type="secondary">{v}</Text> },
            ]}
          />
        ) : <Empty description="暂无评分改进数据 (需对同一检查项重新评分后显示)" style={{ marginTop: 40 }} />}
      </Card>

      {/* ===== 工厂下钻 Drawer ===== */}
      <Drawer
        title={factoryDrillPlant ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setFactoryDrillPlant(null)} />
            <Text strong>{factoryDrillPlant} 工厂 - 项目评分明细</Text>
          </div>
        ) : '工厂数据'}
        placement="right" open={!!factoryDrillPlant} onClose={() => setFactoryDrillPlant(null)} width={800}
      >
        {factoryDrillLoading ? <div style={{ textAlign: 'center', paddingTop: 100 }}><Spin size="large" /></div> : (
          factoryProjects.length > 0 ? (
            <>
              <Row gutter={12} style={{ marginBottom: 16 }}>
                <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${COLORS.primary}` }}><Statistic title="项目数" value={factoryProjects.length} valueStyle={{ fontFamily: NUM_FONT }} /></Card></Col>
                <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${COLORS.success}` }}><Statistic title="最高分" value={Math.max(...factoryProjects.map(p => p.avg_score)).toFixed(1)} suffix="%" valueStyle={{ color: COLORS.success, fontFamily: NUM_FONT }} /></Card></Col>
                <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${GRADIENT_RED.bottom}` }}><Statistic title="最低分" value={Math.min(...factoryProjects.map(p => p.avg_score)).toFixed(1)} suffix="%" valueStyle={{ color: GRADIENT_RED.bottom, fontFamily: NUM_FONT }} /></Card></Col>
              </Row>
              <ReactECharts option={factoryProjectOption} style={{ height: 280 }}
                onEvents={{ click: (params: any) => {
                  const item = factoryProjects[params.dataIndex];
                  if (item) { setFactoryDrillPlant(null); handleProjectDrilldown(item.project_id, item.plan_id); }
                }}}
              />
              <Card size="small" title="项目列表" style={{ marginTop: 16 }}>
                <Table rowKey={(r) => r.plan_id || String(r.project_id)} columns={[
                  { title: '项目名称', dataIndex: 'project_name', key: 'project_name', ellipsis: true },
                  { title: '责任人', dataIndex: 'owner_name', key: 'owner_name', width: 100 },
                  { title: '评审数', dataIndex: 'review_count', key: 'review_count', width: 70 },
                  { title: '评分', dataIndex: 'avg_score', key: 'avg_score', width: 70, render: (v: number) => <Text strong style={{ color: scoreTextColorByPercent(v), fontFamily: NUM_FONT }}>{v}</Text> },
                ]} dataSource={factoryProjects} pagination={false} size="small" />
              </Card>
            </>
          ) : <Empty description="该工厂暂无项目评分数据" style={{ marginTop: 80 }} />
        )}
      </Drawer>

      {/* ===== 问题清单下钻 Drawer ===== */}
      <Drawer
        title={issueDrillPlant ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setIssueDrillPlant(null)} />
            <Text strong>{issueDrillPlant} 工厂 - 问题清单</Text>
            <Tag color="blue">{plantIssues.length} 条</Tag>
          </div>
        ) : '问题清单'}
        placement="right" open={!!issueDrillPlant} onClose={() => setIssueDrillPlant(null)} width={950}
      >
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <Space>
            <FilterOutlined style={{ color: COLORS.primary }} />
            <Segmented value={issueFilter} onChange={(v) => handleIssueFilterChange(v as string)} options={[
              { value: 'all', label: '全部' },
              { value: 'open', label: '未关闭' },
              { value: 'closed', label: '已关闭' },
              { value: 'overdue', label: '超期' },
            ]} />
          </Space>
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>分组:</Text>
            <Segmented size="small" value={issueGroupBy} onChange={(v) => setIssueGroupBy(v as string)} options={[
              { value: 'none', label: '无' },
              { value: 'project', label: '按项目' },
              { value: 'phase', label: '按阶段' },
              { value: 'owner', label: '按责任人' },
            ]} />
          </Space>
        </div>
        {issueDrillLoading ? <div style={{ textAlign: 'center', paddingTop: 100 }}><Spin size="large" /></div> : (
          plantIssues.length > 0 ? (
            issueGroupBy === 'none' ? (
              <Table rowKey="id" columns={issueColumns} dataSource={plantIssues}
                pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
                size="small" scroll={{ x: 800 }}
              />
            ) : (() => {
              // 按选定维度分组
              const groupKey = (item: PlantIssue) => {
                if (issueGroupBy === 'project') return item.project_name || '未关联项目';
                if (issueGroupBy === 'phase') return item.phase_code || '未指定阶段';
                if (issueGroupBy === 'owner') return item.owner_name || '未分配';
                return '其他';
              };
              const groups: Record<string, PlantIssue[]> = {};
              plantIssues.forEach((item) => {
                const key = groupKey(item);
                if (!groups[key]) groups[key] = [];
                groups[key].push(item);
              });
              return (
                <Collapse
                  defaultActiveKey={Object.keys(groups)}
                  items={Object.entries(groups)
                    .sort((a, b) => b[1].length - a[1].length)
                    .map(([key, items]) => ({
                      key,
                      label: (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Text strong>{key}</Text>
                          <Tag color="blue">{items.length} 条</Tag>
                          <Tag color={items.some((i) => i.is_overdue) ? 'red' : 'default'}>
                            {items.filter((i) => i.is_overdue).length} 超期
                          </Tag>
                          <Tag color="success">{items.filter((i) => i.status === 'closed').length} 已关闭</Tag>
                        </div>
                      ),
                      children: (
                        <Table rowKey="id" columns={issueColumns} dataSource={items}
                          pagination={false} size="small" scroll={{ x: 800 }}
                        />
                      ),
                    }))}
                />
              );
            })()
          ) : <Empty description="暂无符合条件的问题" style={{ marginTop: 80 }} />
        )}
      </Drawer>

      {/* ===== 项目下钻 Drawer ===== */}
      <Drawer
        title={projectDrilldown ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => setProjectDrillOpen(false)} />
            <Text strong>{projectDrilldown.project.name || '项目明细'}</Text>
            {projectDrilldown.project.plant && <Tag color="blue">{projectDrilldown.project.plant}</Tag>}
          </div>
        ) : '项目明细'}
        placement="right" open={projectDrillOpen} onClose={() => setProjectDrillOpen(false)} width={900}
      >
        {projectDrillLoading ? <div style={{ textAlign: 'center', paddingTop: 100 }}><Spin size="large" /></div> : projectDrilldown ? (
          <div>
            <Row gutter={12} style={{ marginBottom: 16 }}>
              <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${COLORS.danger}` }}><Statistic title="问题总数" value={projectDrilldown.issue_summary.total} valueStyle={{ fontFamily: NUM_FONT }} /></Card></Col>
              <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${COLORS.success}` }}><Statistic title="已关闭" value={projectDrilldown.issue_summary.closed} valueStyle={{ color: COLORS.success, fontFamily: NUM_FONT }} /></Card></Col>
              <Col span={8}><Card size="small" style={{ borderTop: `3px solid ${COLORS.danger}` }}><Statistic title="超期" value={projectDrilldown.issue_summary.overdue} valueStyle={{ color: COLORS.danger, fontFamily: NUM_FONT }} /></Card></Col>
            </Row>
            {projectDrilldown.phase_scores.length > 0 && (
              <Card size="small" title="各阶段评分" style={{ marginBottom: 16 }}>
                <ReactECharts option={{
                  tooltip: { trigger: 'axis' },
                  grid: { left: 40, right: 20, top: 20, bottom: 30 },
                  xAxis: { type: 'category', data: projectDrilldown.phase_scores.map(p => p.phase_code) },
                  yAxis: { type: 'value', max: 100 },
                  series: [{ type: 'bar', data: projectDrilldown.phase_scores.map(p => ({
                    value: p.avg_score,
                    itemStyle: { borderRadius: [4, 4, 0, 0], color: scoreBarGradient(p.avg_score) },
                  })), barWidth: 30,
                    label: { show: true, position: 'top', fontFamily: NUM_FONT, color: '#475569', formatter: (p: any) => fmtScore(p.value) },
                  }],
                }} style={{ height: 200 }} />
              </Card>
            )}
            <Card size="small" title={`检查项评分明细 (${projectDrilldown.item_scores.length} 条)`}>
              {projectDrilldown.item_scores.length > 0 ? (
                <Table rowKey={(r) => r.key} columns={drilldownColumns} dataSource={projectDrilldown.item_scores.map((r, i) => ({ ...r, key: `${r.phase_code}-${r.item_no}-${i}` }))}
                  pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }} size="small" scroll={{ x: 600 }}
                />
              ) : <Empty description="暂无评审明细数据" style={{ marginTop: 40 }} />}
            </Card>
          </div>
        ) : <Empty description="暂无数据" style={{ marginTop: 80 }} />}
      </Drawer>

      {/* ===== 评分改进分析 - 评审历史明细弹窗 ===== */}
      <Modal
        open={historyOpen}
        onCancel={() => setHistoryOpen(false)}
        footer={null}
        width={880}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 3, height: 14, background: COLORS.primary }} />
            <Text strong>评审历史明细 (整改前后数据来源)</Text>
          </div>
        }
      >
        <Spin spinning={historyLoading}>
          {historyDetail && (
            <div>
              {/* 检查项基本信息 */}
              <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(46,92,230,0.04)', borderRadius: 4, border: '1px solid rgba(46,92,230,0.08)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Text strong style={{ fontSize: 13 }}>{historyDetail.project_name}</Text>
                  <Tag style={{ fontSize: 10 }}>{historyDetail.plant}</Tag>
                  <Tag color="blue" style={{ fontSize: 10 }}>{historyDetail.phase_code}</Tag>
                  {historyDetail.item_no && <Tag style={{ fontSize: 10, fontFamily: NUM_FONT }}>{historyDetail.item_no}</Tag>}
                </div>
                <Text type="secondary" style={{ fontSize: 12 }}>{historyDetail.item_name}</Text>
              </div>

              {/* 整改前后摘要 */}
              <Row gutter={12} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Card size="small" style={{ borderTop: `3px solid ${COLORS.gray}`, textAlign: 'center' }}>
                    <Statistic title="首次评分 (整改前)" value={fmtScore(historyDetail.first_score)}
                      valueStyle={{ color: scoreTextColorByPercent(historyDetail.first_score ?? 0), fontFamily: NUM_FONT, fontSize: 22 }} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" style={{ borderTop: `3px solid ${COLORS.primary}`, textAlign: 'center' }}>
                    <Statistic title="整改后评分 (最新一次)" value={fmtScore(historyDetail.latest_score)}
                      valueStyle={{ color: scoreTextColorByPercent(historyDetail.latest_score ?? 0), fontFamily: NUM_FONT, fontSize: 22 }} />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" style={{ borderTop: `3px solid ${historyDetail.improvement != null && historyDetail.improvement >= 0 ? COLORS.success : COLORS.danger}`, textAlign: 'center' }}>
                    <Statistic title="提升" value={historyDetail.improvement != null ? `${historyDetail.improvement > 0 ? '+' : ''}${historyDetail.improvement.toFixed(1)}%` : '--'}
                      valueStyle={{ color: historyDetail.improvement != null && historyDetail.improvement > 0 ? COLORS.success : historyDetail.improvement != null && historyDetail.improvement < 0 ? COLORS.danger : COLORS.gray, fontFamily: NUM_FONT, fontSize: 22 }} />
                  </Card>
                </Col>
              </Row>

              {/* 数据来源说明 */}
              <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
                首次评分 = 该检查项最早一次已提交的评审分值; 整改后评分 = 最新一次已提交的评审分值。下表按时间正序列出全部评审记录 (含未提交草稿), 可追溯每次评分的评分人、分值与评审意见。
              </Text>

              {/* 全部评审记录 */}
              <Table<ScoreHistoryRecord>
                rowKey="review_id"
                dataSource={historyDetail.records}
                size="small"
                pagination={false}
                scroll={{ y: 320 }}
                rowClassName={(r) => {
                  const submitted = historyDetail.records.filter((x) => x.score != null);
                  const isFirst = submitted.length > 0 && r.review_id === submitted[0].review_id;
                  const isLatest = submitted.length > 0 && r.review_id === submitted[submitted.length - 1].review_id;
                  return isFirst || isLatest ? 'history-highlight-row' : '';
                }}
                columns={[
                  { title: '#', dataIndex: 'seq', key: 'seq', width: 44, align: 'center' as const,
                    render: (v: number, r) => {
                      const submitted = historyDetail.records.filter((x) => x.score != null);
                      const isFirst = submitted.length > 0 && r.review_id === submitted[0].review_id;
                      const isLatest = submitted.length > 0 && r.review_id === submitted[submitted.length - 1].review_id && submitted.length > 1;
                      return <span style={{ fontFamily: NUM_FONT }}>
                        {v}{isFirst && <Tag color="geekblue" style={{ fontSize: 9, marginLeft: 4, lineHeight: '14px', padding: '0 4px' }}>首次</Tag>}
                        {isLatest && <Tag color="gold" style={{ fontSize: 9, marginLeft: 4, lineHeight: '14px', padding: '0 4px' }}>整改后</Tag>}
                      </span>;
                    },
                  },
                  { title: '评分', dataIndex: 'score', key: 'score', width: 80, align: 'center' as const,
                    render: (v: number | null) => v == null
                      ? <Text type="secondary" style={{ fontSize: 11 }}>未评分</Text>
                      : <Text strong style={{ color: scoreTextColorByPercent(v), fontFamily: NUM_FONT }}>{fmtScore(v)}</Text>,
                  },
                  { title: '评分人', dataIndex: 'reviewer_name', key: 'reviewer_name', width: 100, ellipsis: true },
                  { title: '结果', dataIndex: 'result_text', key: 'result_text', width: 130, ellipsis: true,
                    render: (v: string) => v ? <Text style={{ fontSize: 11 }}>{v}</Text> : <Text type="secondary" style={{ fontSize: 11 }}>-</Text>,
                  },
                  { title: '评审意见', dataIndex: 'comments', key: 'comments', ellipsis: true,
                    render: (v: string) => v ? <Text style={{ fontSize: 11 }}>{v}</Text> : <Text type="secondary" style={{ fontSize: 11 }}>-</Text>,
                  },
                  { title: '状态', dataIndex: 'status', key: 'status', width: 76, align: 'center' as const,
                    render: (v: string) => v === 'confirmed' ? <Tag color="success" style={{ fontSize: 10 }}>已确认</Tag>
                      : v === 'submitted' ? <Tag color="processing" style={{ fontSize: 10 }}>已提交</Tag>
                      : <Tag style={{ fontSize: 10 }}>草稿</Tag>,
                  },
                  { title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 130,
                    render: (v: string | null, r) => <Text style={{ fontSize: 11, fontFamily: NUM_FONT }}>{v || r.created_at || '-'}</Text>,
                  },
                ]}
              />
            </div>
          )}
        </Spin>
      </Modal>
    </Spin>
  );
}
