import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Row,
  Select,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CalendarOutlined,
  CameraOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  ProjectOutlined,
  ReloadOutlined,
  SearchOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { toPng } from 'html-to-image';
import {
  getMsiaPlanDetailApi,
  listMsiaPlansApi,
} from '@/api/msiaPlan';
import type {
  MsiaPlanDetail,
  MsiaPlanItem,
  MsiaPlanPageResponse,
} from '@/api/msiaPlan';
import { formatDate, formatDateTime } from '@/utils/format';

const { Title, Text } = Typography;

// 默认分页大小: 每页 20 条
const DEFAULT_PAGE_SIZE = 20;

// 阶段定义: MSIA3 / MSIA4 / MSIA5
const PHASES = [
  { key: '3', label: '3', fullLabel: 'MSIA3', color: '#0FB5BA', desc: '设计冻结' },
  { key: '4', label: '4', fullLabel: 'MSIA4', color: '#F97316', desc: '预验收' },
  { key: '5', label: '5', fullLabel: 'MSIA5', color: '#10B981', desc: '终验收' },
] as const;

// 阶段状态: 未开始 / 进行中 / 已完成
type PhaseStatus = 'pending' | 'in_progress' | 'done';

// 根据计划/实际日期判断阶段状态
function getPhaseStatus(planDate: string | null, actualDate: string | null): PhaseStatus {
  if (actualDate) return 'done';
  if (planDate) return 'in_progress';
  return 'pending';
}

const phaseStatusMap: Record<PhaseStatus, { color: string; text: string; icon: React.ReactNode }> = {
  pending: { color: 'default', text: '未开始', icon: <ClockCircleOutlined /> },
  in_progress: { color: 'processing', text: '进行中', icon: <SyncOutlined spin /> },
  done: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
};

// 计算工单整体进度 (基于 MSIA3/4/5 实际完成数)
function getOverallProgress(item: MsiaPlanItem): { done: number; total: number; percent: number } {
  const phases = [3, 4, 5];
  let done = 0;
  phases.forEach((p) => {
    const actual = item[`msia${p}ActualDate` as keyof MsiaPlanItem] as string | null;
    if (actual) done += 1;
  });
  return { done, total: 3, percent: Math.round((done / 3) * 100) };
}

// ============ 甘特图时间轴组件 ============
// 12 个月份位置 (基于 2026-01 ~ 2026-12)
const TIMELINE_YEAR = 2026;
const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];

// 根据日期字符串返回月份位置百分比 (0-100)
function getDatePosition(dateStr: string | null): number | null {
  if (!dateStr) return null;
  const d = dayjs(dateStr);
  if (!d.isValid() || d.year() !== TIMELINE_YEAR) return null;
  return ((d.month() + 0.5) / 12) * 100;
}

// 获取当前月份位置百分比 (用于今日竖线)
function getCurrentMonthPosition(): number {
  const now = dayjs();
  if (now.year() !== TIMELINE_YEAR) return -1;
  return ((now.month() + 0.5) / 12) * 100;
}

// 甘特图状态色: 已完成=绿色实心 / 未实施未超期=蓝色空心 / 超期=红色空心
const GANTT_DONE_COLOR = '#52C41A';
const GANTT_PLAN_COLOR = '#1677FF';
const GANTT_OVERDUE_COLOR = '#FF4D4F';

// 单个阶段标记 (甘特图上的圆点)
// - 已完成 (有实际日期): 绿色实心圆
// - 未实施且未超期 (无实际日期, 计划日期 >= 今天): 蓝色空心圆
// - 超期 (无实际日期, 计划日期 < 今天): 红色空心圆
function PhaseMarker({
  phase,
  planDate,
  actualDate,
}: {
  phase: typeof PHASES[number];
  planDate: string | null;
  actualDate: string | null;
}) {
  const today = dayjs();
  const isDone = Boolean(actualDate);
  const isOverdue = !isDone && Boolean(planDate) && dayjs(planDate).isBefore(today, 'day');

  const pos = getDatePosition(actualDate) ?? getDatePosition(planDate);

  if (pos === null) return null;

  const baseStyle: React.CSSProperties = {
    position: 'absolute',
    left: `${pos}%`,
    top: '50%',
    transform: 'translate(-50%, -50%)',
    width: 22,
    height: 22,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 11,
    fontWeight: 700,
    transition: 'all 0.3s',
    cursor: 'pointer',
    zIndex: 2,
  };

  let markerStyle: React.CSSProperties;
  let tooltipText: string;

  if (isDone) {
    // 已完成: 绿色实心圆
    markerStyle = {
      ...baseStyle,
      backgroundColor: GANTT_DONE_COLOR,
      border: `2px solid ${GANTT_DONE_COLOR}`,
      color: '#fff',
    };
    tooltipText = `${phase.fullLabel} · 已完成 | 计划: ${formatDate(planDate) || '-'} | 实际: ${formatDate(actualDate) || '-'}`;
  } else if (isOverdue) {
    // 超期: 红色空心圆
    markerStyle = {
      ...baseStyle,
      backgroundColor: '#fff',
      border: `2px solid ${GANTT_OVERDUE_COLOR}`,
      color: GANTT_OVERDUE_COLOR,
    };
    tooltipText = `${phase.fullLabel} · 已超期 | 计划: ${formatDate(planDate) || '-'} | 实际: -`;
  } else {
    // 未实施且未超期: 蓝色空心圆
    markerStyle = {
      ...baseStyle,
      backgroundColor: '#fff',
      border: `2px solid ${GANTT_PLAN_COLOR}`,
      color: GANTT_PLAN_COLOR,
    };
    tooltipText = `${phase.fullLabel} · 未实施 | 计划: ${formatDate(planDate) || '-'} | 实际: -`;
  }

  return (
    <Tooltip title={tooltipText} placement="top">
      <div style={markerStyle}>{phase.label}</div>
    </Tooltip>
  );
}

// 共享月份头部 (只渲染一次, 作为列 title)
function MonthHeader() {
  const currentMonthPos = getCurrentMonthPosition();
  const currentMonthIdx = dayjs().year() === TIMELINE_YEAR ? dayjs().month() : -1;

  return (
    <div style={{ width: '100%', position: 'relative' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(12, 1fr)',
          fontSize: 10,
          color: '#666',
        }}
      >
        {MONTH_LABELS.map((m, idx) => {
          const isCurrent = idx === currentMonthIdx;
          return (
            <div
              key={m}
              style={{
                textAlign: 'center',
                color: isCurrent ? '#F97316' : '#666',
                fontWeight: isCurrent ? 700 : 500,
                position: 'relative',
              }}
            >
              {m}
              {isCurrent && (
                <div
                  style={{
                    position: 'absolute',
                    bottom: -4,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 0,
                    height: 0,
                    borderLeft: '4px solid transparent',
                    borderRight: '4px solid transparent',
                    borderTop: '4px solid #F97316',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// 每行的时间轴单元格 (无月份头部, 只有标记和背景)
// showCurrentMonthLine: 是否显示当前月份竖线 (详情抽屉中设为 false)
function GanttTimelineRow({
  record,
  showCurrentMonthLine = true,
}: {
  record: MsiaPlanItem;
  showCurrentMonthLine?: boolean;
}) {
  const currentMonthPos = getCurrentMonthPosition();

  return (
    <div style={{ width: '100%', position: 'relative', height: 36 }}>
      {/* 时间轴主体 (12 格背景) */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 2,
          bottom: 2,
          background: `repeating-linear-gradient(90deg, #fafafa 0, #fafafa calc(100%/12 - 1px), #f0f0f0 calc(100%/12 - 1px), #f0f0f0 calc(100%/12))`,
          borderRadius: 4,
          overflow: 'visible',
        }}
      >
        {/* 当前月份竖线 - 橙色细虚线, 仅在数据行间连贯 (不延伸到表头) */}
        {showCurrentMonthLine && currentMonthPos >= 0 && (
          <div
            style={{
              position: 'absolute',
              left: `${currentMonthPos}%`,
              top: -6,
              bottom: -6,
              width: 0,
              borderLeft: '1px dashed #F97316',
              zIndex: 1,
              pointerEvents: 'none',
              opacity: 0.7,
            }}
          />
        )}

        {/* 三个阶段标记 */}
        {PHASES.map((phase) => {
          const plan = record[`msia${phase.key}PlanDate` as keyof MsiaPlanItem] as string | null;
          const actual = record[`msia${phase.key}ActualDate` as keyof MsiaPlanItem] as string | null;
          return (
            <PhaseMarker
              key={phase.key}
              phase={phase}
              planDate={plan}
              actualDate={actual}
            />
          );
        })}
      </div>
    </div>
  );
}

// 渲染动态字段的 Descriptions 区块 (用于详情抽屉)
function renderDynamicBlock(
  title: string,
  record: Record<string, unknown> | null,
  icon?: React.ReactNode
) {
  if (!record || Object.keys(record).length === 0) {
    return <Empty description="无数据" style={{ margin: '8px 0' }} />;
  }
  return (
    <Descriptions
      title={
        <Space>
          {icon}
          <span>{title}</span>
        </Space>
      }
      bordered
      column={2}
      size="small"
      styles={{ label: { width: 140, backgroundColor: '#fafafa' } }}
    >
      {Object.entries(record).map(([k, v]) => {
        const str = String(v ?? '');
        const isDate = /^\d{4}-\d{2}-\d{2}/.test(str);
        return (
          <Descriptions.Item key={k} label={k} span={isDate ? 1 : 2}>
            <Text style={{ wordBreak: 'break-all' }}>
              {isDate ? formatDateTime(str) : str || <Text type="secondary">-</Text>}
            </Text>
          </Descriptions.Item>
        );
      })}
    </Descriptions>
  );
}

// 展开行: 详细阶段信息
function ExpandedRow({ record }: { record: MsiaPlanItem }) {
  const { done, total, percent } = getOverallProgress(record);
  const color = percent === 100 ? '#10B981' : percent >= 67 ? '#0FB5BA' : percent >= 33 ? '#F59E0B' : '#EF4444';

  return (
    <div style={{ padding: '12px 24px', background: '#fafafa' }}>
      <Row gutter={16}>
        <Col span={6}>
          <Card size="small" title="项目负责人">
            <Space direction="vertical" size={2}>
              <Text strong style={{ color: '#2E5CE6', fontSize: 14 }}>
                {record.ownerName || '-'}
              </Text>
              {record.userName_in_charge && (
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {record.userName_in_charge}
                </Text>
              )}
            </Space>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="审核负责人">
            <Space direction="vertical" size={2}>
              {record.leadUser && (
                <Space size={4}>
                  <Tag color="purple" style={{ fontSize: 10, margin: 0 }}>Lead</Tag>
                  <Text style={{ fontSize: 12 }}>{record.leadUser}</Text>
                </Space>
              )}
              {record.sme1 && (
                <Space size={4}>
                  <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>SME1</Tag>
                  <Text style={{ fontSize: 12 }}>{record.sme1}</Text>
                </Space>
              )}
              {record.sme2 && (
                <Space size={4}>
                  <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>SME2</Tag>
                  <Text style={{ fontSize: 12 }}>{record.sme2}</Text>
                </Space>
              )}
              {!record.leadUser && !record.sme1 && !record.sme2 && (
                <Text type="secondary">-</Text>
              )}
            </Space>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="工厂 / 产线">
            <Space direction="vertical" size={2}>
              {record.plantName && (
                <Text style={{ fontSize: 12 }}>
                  <ProjectOutlined style={{ marginRight: 4 }} />
                  {record.plantName}
                </Text>
              )}
              {record.lineName && (
                <Text type="secondary" style={{ fontSize: 11 }}>产线: {record.lineName}</Text>
              )}
              {record.supplerName && (
                <Text type="secondary" style={{ fontSize: 11 }}>供应商: {record.supplerName}</Text>
              )}
            </Space>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title="整体进度">
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text strong style={{ color, fontSize: 18 }}>
                {percent}% <Text type="secondary" style={{ fontSize: 11 }}>({done}/{total})</Text>
              </Text>
              <div style={{ width: '100%', height: 6, backgroundColor: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${percent}%`, height: '100%', backgroundColor: color, transition: 'width 0.3s' }} />
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 阶段明细卡片 */}
      <Row gutter={8} style={{ marginTop: 12 }}>
        {PHASES.map((phase) => {
          const plan = record[`msia${phase.key}PlanDate` as keyof MsiaPlanItem] as string | null;
          const actual = record[`msia${phase.key}ActualDate` as keyof MsiaPlanItem] as string | null;
          const status = getPhaseStatus(plan, actual);
          const statusInfo = phaseStatusMap[status];
          const today = dayjs();
          const isOverdue = plan && !actual && dayjs(plan).isBefore(today, 'day');

          return (
            <Col span={8} key={phase.key}>
              <div
                style={{
                  padding: 10,
                  borderRadius: 8,
                  border: `1px solid ${phase.color}33`,
                  background: `${phase.color}08`,
                }}
              >
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Space>
                    <Tag color={phase.color}>{phase.fullLabel}</Tag>
                    <Text type="secondary" style={{ fontSize: 11 }}>{phase.desc}</Text>
                  </Space>
                  <Tag color={statusInfo.color} icon={statusInfo.icon}>
                    {statusInfo.text}
                    {isOverdue && ' · 逾期'}
                  </Tag>
                  <Text style={{ fontSize: 12 }}>
                    计划: <Text strong>{formatDate(plan) || '-'}</Text>
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    实际: <Text strong style={{ color: status === 'done' ? '#10B981' : undefined }}>
                      {formatDate(actual) || '-'}
                    </Text>
                  </Text>
                </Space>
              </div>
            </Col>
          );
        })}
      </Row>
    </div>
  );
}

// MSIA 计划页 (甘特图风格 - 共享月份头部)
export default function MsiaPlan() {
  const { message } = App.useApp();

  // 列表查询状态
  const [keyword, setKeyword] = useState('');
  const [plantFilter, setPlantFilter] = useState<string | undefined>(undefined);
  const [committed, setCommitted] = useState<{ keyword: string; order_id: string }>({
    keyword: '',
    order_id: '',
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [data, setData] = useState<MsiaPlanPageResponse>({
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
    total_pages: 0,
  });
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  // 详情抽屉状态
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<MsiaPlanDetail | null>(null);
  const [currentRow, setCurrentRow] = useState<MsiaPlanItem | null>(null);

  // 表格容器 ref (用于导出图片)
  const tableWrapperRef = useRef<HTMLDivElement>(null);

  // 拉取列表数据
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMsiaPlansApi({
        keyword: committed.keyword.trim() || undefined,
        order_id: committed.order_id.trim() || undefined,
        page,
        page_size: pageSize,
      });
      setData(res);
    } catch {
      // 错误已由 axios 拦截器统一提示
    } finally {
      setLoading(false);
    }
  }, [committed, page, pageSize]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 工厂选项 (从当前数据中提取, 去重)
  const plantOptions = useMemo(() => {
    const plants = new Set<string>();
    data.items.forEach((it) => {
      if (it.plantName) plants.add(it.plantName);
    });
    return Array.from(plants).sort();
  }, [data.items]);

  // 过滤后的数据 (按工厂前端过滤)
  const filteredItems = useMemo(() => {
    if (!plantFilter) return data.items;
    return data.items.filter((it) => it.plantName === plantFilter);
  }, [data.items, plantFilter]);

  // 点击查询
  const handleSearch = () => {
    setCommitted({ keyword: keyword.trim(), order_id: '' });
    setPage(1);
  };

  // 重置筛选
  const handleReset = () => {
    setKeyword('');
    setPlantFilter(undefined);
    setCommitted({ keyword: '', order_id: '' });
    setPage(1);
  };

  // 导出图片
  const handleExportImage = async () => {
    if (!tableWrapperRef.current) {
      message.warning('无法获取表格内容');
      return;
    }
    setExporting(true);
    try {
      const dataUrl = await toPng(tableWrapperRef.current, {
        backgroundColor: '#ffffff',
        pixelRatio: 2,
        filter: (node) => {
          // 过滤掉分页器等不需要的元素
          if (node instanceof HTMLElement) {
            return !node.classList.contains('msia-no-export');
          }
          return true;
        },
      });
      const link = document.createElement('a');
      link.download = `MSIA计划甘特图_${dayjs().format('YYYYMMDD_HHmmss')}.png`;
      link.href = dataUrl;
      link.click();
      message.success('图片已导出');
    } catch (err) {
      console.error('导出失败:', err);
      message.error('导出失败, 请重试');
    } finally {
      setExporting(false);
    }
  };

  // 打开详情抽屉
  const openDetail = async (record: MsiaPlanItem) => {
    const planId = record.planId;
    if (!planId) {
      message.warning('无法识别该记录的 ID');
      return;
    }
    setCurrentRow(record);
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await getMsiaPlanDetailApi(String(planId));
      setDetail(res);
    } catch {
      // 错误已由拦截器提示
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setDetailOpen(false);
    setDetail(null);
    setCurrentRow(null);
  };

  // 统计数据
  const stats = useMemo(() => {
    const items = filteredItems;
    const total = items.length;
    let msia3Done = 0, msia3InProgress = 0;
    let msia4Done = 0, msia4InProgress = 0;
    let msia5Done = 0, msia5InProgress = 0;
    let overdueCount = 0;

    items.forEach((it) => {
      const s3 = getPhaseStatus(it.msia3PlanDate, it.msia3ActualDate);
      const s4 = getPhaseStatus(it.msia4PlanDate, it.msia4ActualDate);
      const s5 = getPhaseStatus(it.msia5PlanDate, it.msia5ActualDate);
      if (s3 === 'done') msia3Done += 1;
      else if (s3 === 'in_progress') msia3InProgress += 1;
      if (s4 === 'done') msia4Done += 1;
      else if (s4 === 'in_progress') msia4InProgress += 1;
      if (s5 === 'done') msia5Done += 1;
      else if (s5 === 'in_progress') msia5InProgress += 1;

      const today = dayjs();
      [3, 4, 5].forEach((p) => {
        const plan = it[`msia${p}PlanDate` as keyof MsiaPlanItem] as string | null;
        const actual = it[`msia${p}ActualDate` as keyof MsiaPlanItem] as string | null;
        if (plan && !actual && dayjs(plan).isBefore(today, 'day')) overdueCount += 1;
      });
    });

    return {
      total,
      msia3Done, msia3InProgress,
      msia4Done, msia4InProgress,
      msia5Done, msia5InProgress,
      overdueCount,
    };
  }, [filteredItems]);

  // 表格列定义 (静态 - 共享月份头部甘特图)
  const columns: ColumnsType<MsiaPlanItem> = useMemo(() => {
    return [
      {
        title: '序号',
        dataIndex: 'seq',
        key: 'seq',
        width: 50,
        fixed: 'left',
        render: (v: number) => <Text strong style={{ fontSize: 12 }}>{v}</Text>,
      },
      {
        title: '项目',
        key: 'project',
        width: 200,
        fixed: 'left',
        render: (_, record) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {record.projectName ? (
              <Text strong style={{ fontSize: 13 }}>
                {record.projectName}
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: 13 }}>-</Text>
            )}
            {record.order_description && (
              <Text type="secondary" style={{ fontSize: 11 }} ellipsis>
                {record.order_description}
              </Text>
            )}
          </div>
        ),
      },
      {
        title: '产线类型',
        dataIndex: 'lineType',
        key: 'lineType',
        width: 100,
        render: (v: string | null) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {v ? (
              <Tag color="blue" style={{ fontSize: 11, margin: 0, width: 'fit-content' }}>
                {v}
              </Tag>
            ) : (
              <Text type="secondary" style={{ fontSize: 11 }}>-</Text>
            )}
          </div>
        ),
      },
      {
        title: <MonthHeader />,
        key: 'gantt',
        width: 520,
        render: (_, record) => <GanttTimelineRow record={record} />,
        onCell: () => ({
          style: { overflow: 'visible' },
        }),
      },
      {
        title: '操作',
        key: 'action',
        width: 60,
        fixed: 'right',
        render: (_, record) => (
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={(e) => {
              e.stopPropagation();
              openDetail(record);
            }}
            style={{ padding: '0 4px' }}
          />
        ),
      },
    ];
  }, []);

  return (
    <div>
      {/* 全局样式: 表格单元格 overflow visible */}
      <style>{`
        /* 让时间轴列单元格 overflow visible, 使竖线穿透行边界 */
        .msia-gantt-table .ant-table-cell {
          overflow: visible !important;
        }
        .msia-gantt-table .ant-table-cell-fix-right,
        .msia-gantt-table .ant-table-cell-fix-left {
          overflow: hidden !important;
        }
      `}</style>

      {/* ============ 顶部统计卡片 ============ */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #2E5CE6' }}>
            <Statistic
              title="本页计划数"
              value={stats.total}
              prefix={<ProjectOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #0FB5BA' }}>
            <Statistic
              title="MSIA3 已完成"
              value={stats.msia3Done}
              suffix={stats.msia3InProgress > 0 ? `/ 进行中 ${stats.msia3InProgress}` : ''}
              valueStyle={{ color: '#0FB5BA' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #F97316' }}>
            <Statistic
              title="MSIA4 已完成"
              value={stats.msia4Done}
              suffix={stats.msia4InProgress > 0 ? `/ 进行中 ${stats.msia4InProgress}` : ''}
              valueStyle={{ color: '#F97316' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #10B981' }}>
            <Statistic
              title="MSIA5 已完成"
              value={stats.msia5Done}
              suffix={stats.msia5InProgress > 0 ? `/ 进行中 ${stats.msia5InProgress}` : ''}
              valueStyle={{ color: '#10B981' }}
            />
          </Card>
        </Col>
      </Row>

      {/* ============ 主表格卡片 ============ */}
      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>MSIA 计划表 · 甘特图视图</Title>
            <Tag color="blue">共 {data.total} 条</Tag>
            {stats.overdueCount > 0 && (
              <Tag color="red" icon={<ClockCircleOutlined />}>
                逾期 {stats.overdueCount} 项
              </Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              时间轴年份: {TIMELINE_YEAR}
            </Text>
            <Button
              type="primary"
              icon={<CameraOutlined />}
              loading={exporting}
              onClick={handleExportImage}
            >
              导出图片
            </Button>
          </Space>
        }
      >
        {/* 顶部搜索区 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="关键字 (项目名/工单描述/负责人/SME/产线类型)"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            allowClear
            style={{ width: 360 }}
          />
          <Select
            placeholder="按工厂筛选"
            value={plantFilter}
            onChange={(v) => setPlantFilter(v)}
            allowClear
            style={{ width: 180 }}
            options={plantOptions.map((p) => ({ label: p, value: p }))}
            showSearch
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            查询
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleReset}>
            重置
          </Button>
        </Space>

        {/* 图例说明 */}
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#fafafa', borderRadius: 4, display: 'flex', gap: 16, alignItems: 'center', fontSize: 11 }}>
          <Text type="secondary" strong style={{ fontSize: 11 }}>图例:</Text>
          <Space size={4}>
            <div style={{ width: 14, height: 14, borderRadius: '50%', backgroundColor: GANTT_DONE_COLOR, border: `2px solid ${GANTT_DONE_COLOR}` }} />
            <Text type="secondary">已完成 (绿色实心)</Text>
          </Space>
          <Space size={4}>
            <div style={{ width: 14, height: 14, borderRadius: '50%', backgroundColor: '#fff', border: `2px solid ${GANTT_PLAN_COLOR}` }} />
            <Text type="secondary">未实施 (蓝色空心)</Text>
          </Space>
          <Space size={4}>
            <div style={{ width: 14, height: 14, borderRadius: '50%', backgroundColor: '#fff', border: `2px solid ${GANTT_OVERDUE_COLOR}` }} />
            <Text type="secondary">超期 (红色空心)</Text>
          </Space>
          <Space size={4}>
            <div style={{ width: 2, height: 14, backgroundColor: '#F97316' }} />
            <Text type="secondary">当前月份</Text>
          </Space>
          <Text type="secondary" style={{ marginLeft: 'auto' }}>
            提示: 点击行首 ▸ 展开详细信息
          </Text>
        </div>

        {/* 表格容器 (ref 用于导出图片) */}
        <div ref={tableWrapperRef} className="msia-gantt-table">
          <Table<MsiaPlanItem>
            columns={columns}
            dataSource={filteredItems}
            rowKey={(record) => record.planId}
            loading={loading}
            scroll={{ x: 1000 }}
            size="middle"
            bordered
            locale={{ emptyText: <Empty description="暂无计划数据" /> }}
            expandable={{
              expandedRowRender: (record) => <ExpandedRow record={record} />,
              rowExpandable: () => true,
            }}
            pagination={{
              current: page,
              pageSize,
              total: data.total,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (t) => `共 ${t} 条`,
              pageSizeOptions: ['20', '30', '50'],
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        </div>
      </Card>

      {/* ============ 详情抽屉 ============ */}
      <Drawer
        title={
          currentRow ? (
            <Space>
              <Text strong>计划详情</Text>
              <Tag color="blue">seq #{currentRow.seq}</Tag>
              {currentRow.projectName && (
                <Tag color="purple">{currentRow.projectName}</Tag>
              )}
            </Space>
          ) : (
            '计划详情'
          )
        }
        placement="right"
        width={820}
        open={detailOpen}
        onClose={closeDetail}
        destroyOnHidden
      >
        {detailLoading ? (
          <Skeleton active paragraph={{ rows: 12 }} />
        ) : (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            {/* 顶部阶段进度概览 */}
            {currentRow && (
              <Card size="small" style={{ background: '#fafafa' }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Statistic
                      title="项目名称"
                      value={currentRow.projectName || '-'}
                      valueStyle={{ fontSize: 14 }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="项目负责人"
                      value={currentRow.ownerName || '-'}
                      valueStyle={{ fontSize: 14, color: '#2E5CE6' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="审核负责人"
                      value={currentRow.leadUser || '-'}
                      valueStyle={{ fontSize: 14 }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="整体进度"
                      value={getOverallProgress(currentRow).percent}
                      suffix="%"
                      valueStyle={{
                        color:
                          getOverallProgress(currentRow).percent === 100
                            ? '#10B981'
                            : '#2E5CE6',
                      }}
                    />
                  </Col>
                </Row>
              </Card>
            )}

            {/* 阶段进度时间轴 (详情版 - 含月份头部, 不显示当前月份竖线) */}
            {currentRow && (
              <Card size="small" title="阶段时间轴 (2026)">
                <div style={{ width: '100%', position: 'relative' }}>
                  <MonthHeader />
                  <div style={{ marginTop: 6 }}>
                    <GanttTimelineRow record={currentRow} showCurrentMonthLine={false} />
                  </div>
                </div>
              </Card>
            )}

            {/* 计划信息 (动态字段, 含 MSIA1-5 完整日期) */}
            {renderDynamicBlock('计划信息 (含 MSIA1-5 完整日期)', detail?.plan ?? null)}

            {/* TODO: 后续规划 - 在此处展示 MSIA3 / MSIA4 / MSIA5 各阶段的评审报告概述
                - 评审得分 / 关键检查项结果 / 主要问题与建议
                - 当前暂不显示, 待评审模块数据接入后补充 */}
          </Space>
        )}
      </Drawer>
    </div>
  );
}
