import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Card,
  Table,
  Input,
  Select,
  Space,
  Button,
  Tag,
  Typography,
  Tooltip,
  Empty,
  Row,
  Col,
  Statistic,
  Tabs,
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  ProjectOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  CalendarOutlined,
  FireOutlined,
  ArrowRightOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  listMsiaPlansApi,
  listPendingReviewsApi,
} from '@/api/msiaPlan';
import type {
  MsiaPlanItem,
  MsiaPlanPageResponse,
  PendingReviewItem,
} from '@/api/msiaPlan';
import { getPhaseResult, type PhaseResult } from '@/api/reviews';
import { formatDate } from '@/utils/format';
import { scoreColor as _sc, scoreTextColor as _stc } from '@/utils/scoreColor';
import { NUM_FONT } from '@/utils/fonts';
import { useAuthStore } from '@/store/auth';

const { Text } = Typography;

// 默认分页大小
const DEFAULT_PAGE_SIZE = 20;

// MSIA 阶段元数据 (与 PhaseReview 保持一致)
const MSIA_PHASES = [
  { code: 'MSIA1', color: '#8c8c8c', label: 'M1' },
  { code: 'MSIA2', color: '#2E5CE6', label: 'M2' },
  { code: 'MSIA3', color: '#0FB5BA', label: 'M3' },
  { code: 'MSIA4', color: '#F97316', label: 'M4' },
  { code: 'MSIA5', color: '#10B981', label: 'M5' },
];

// 阶段状态: 未开始 / 进行中 / 已完成 (用于顶部统计卡)
type PhaseStatus = 'pending' | 'in_progress' | 'done';

function getPhaseStatus(planDate: string | null, actualDate: string | null): PhaseStatus {
  if (actualDate) return 'done';
  if (planDate) return 'in_progress';
  return 'pending';
}

// 项目管理列表页 (基于 MSIA 计划实际数据)
export default function Projects() {
  const navigate = useNavigate();
  // 当前用户 (判断是否显示评分补录入口, 仅管理员可见)
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.Role === 'admin';

  // 列表查询状态
  const [keyword, setKeyword] = useState('');
  const [plantFilter, setPlantFilter] = useState<string | undefined>(undefined);
  const [committed, setCommitted] = useState<{ keyword: string }>({ keyword: '' });
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
  // MSIA 各阶段平均分 (全局)
  const [phaseResults, setPhaseResults] = useState<Record<string, PhaseResult | null>>({});
  // 待评审项目 (本月+下月)
  const [pendingReviews, setPendingReviews] = useState<PendingReviewItem[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  // 待评审范围切换: 1=本月+下月, 2=本月+下2月
  const [pendingMonths, setPendingMonths] = useState(1);
  // 当前激活的 Tab: projects=项目管理, pending=待评审项目
  const [activeTab, setActiveTab] = useState('projects');

  // 拉取列表数据
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMsiaPlansApi({
        keyword: committed.keyword.trim() || undefined,
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

  // 拉取 MSIA 各阶段平均分 (全局, 不按项目过滤)
  const fetchPhaseResults = useCallback(async () => {
    try {
      const entries = await Promise.all(
        MSIA_PHASES.map(async (p) => {
          try {
            const res = await getPhaseResult(p.code);
            return [p.code, res] as const;
          } catch {
            return [p.code, null] as const;
          }
        })
      );
      setPhaseResults(Object.fromEntries(entries));
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    fetchPhaseResults();
  }, [fetchPhaseResults]);

  // 拉取待评审项目 (本月+下月)
  const fetchPendingReviews = useCallback(async () => {
    setPendingLoading(true);
    try {
      const res = await listPendingReviewsApi(pendingMonths);
      setPendingReviews(res || []);
    } catch {
      setPendingReviews([]);
    } finally {
      setPendingLoading(false);
    }
  }, [pendingMonths]);

  useEffect(() => {
    fetchPendingReviews();
  }, [fetchPendingReviews]);

  // 跳转到阶段评审页面 (直接进入待评审阶段)
  const goToPhaseReview = (planId: number, phaseNum: number) => {
    navigate(`/projects/${planId}/phases/${phaseNum}`);
  };

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

  // 统计数据
  const stats = useMemo(() => {
    const items = filteredItems;
    const total = items.length;
    let done3 = 0, inProgress3 = 0;
    let done4 = 0, inProgress4 = 0;
    let done5 = 0, inProgress5 = 0;
    let overdueCount = 0;

    items.forEach((it) => {
      const s3 = getPhaseStatus(it.msia3PlanDate, it.msia3ActualDate);
      const s4 = getPhaseStatus(it.msia4PlanDate, it.msia4ActualDate);
      const s5 = getPhaseStatus(it.msia5PlanDate, it.msia5ActualDate);
      if (s3 === 'done') done3 += 1; else if (s3 === 'in_progress') inProgress3 += 1;
      if (s4 === 'done') done4 += 1; else if (s4 === 'in_progress') inProgress4 += 1;
      if (s5 === 'done') done5 += 1; else if (s5 === 'in_progress') inProgress5 += 1;

      const today = dayjs();
      [3, 4, 5].forEach((p) => {
        const plan = it[`msia${p}PlanDate` as keyof MsiaPlanItem] as string | null;
        const actual = it[`msia${p}ActualDate` as keyof MsiaPlanItem] as string | null;
        if (plan && !actual && dayjs(plan).isBefore(today, 'day')) overdueCount += 1;
      });
    });

    return { total, done3, inProgress3, done4, inProgress4, done5, inProgress5, overdueCount };
  }, [filteredItems]);

  // 表格列定义
  const columns: ColumnsType<MsiaPlanItem> = [
    {
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>
          NO.
        </span>
      ),
      dataIndex: 'seq',
      key: 'seq',
      width: 56,
      fixed: 'left',
      render: (v: number) => (
        <Text
          strong
          style={{
            fontFamily: NUM_FONT,
            fontSize: 11,
            color: '#2E5CE6',
          }}
        >
          {v}
        </Text>
      ),
    },
    {
      title: '项目',
      key: 'project',
      width: 200,
      fixed: 'left',
      render: (_, record) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {record.projectName ? (
            <Text strong style={{ fontSize: 12, lineHeight: 1.35 }}>
              {record.projectName}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
          )}
          {record.order_description && (
            <Text type="secondary" style={{ fontSize: 10 }} ellipsis>
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
      width: 90,
      render: (v: string | null) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {v ? (
            <Tag color="blue" style={{ fontSize: 10, margin: 0, width: 'fit-content', padding: '0 4px', lineHeight: '14px' }}>
              {v}
            </Tag>
          ) : (
            <Text type="secondary" style={{ fontSize: 10 }}>-</Text>
          )}
        </div>
      ),
    },
    {
      title: '负责人',
      key: 'owner',
      width: 90,
      render: (_, record) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {record.ownerName ? (
            <Text strong style={{ fontSize: 11, color: '#2E5CE6' }}>
              {record.ownerName}
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 10 }}>-</Text>
          )}
          {record.leadUser && (
            <Text type="secondary" style={{ fontSize: 10 }}>
              Lead: {record.leadUser}
            </Text>
          )}
        </div>
      ),
    },
    // MSIA1~5 各阶段综合评分列 (替代原 MSIA3/4/5 完成进度列)
    // 未评审阶段显示为空 (无占位填充); 评分口径与"我的面板-项目库"一致
    // 配色规则 (用户指定): <75% 红 / =75% 黄 / >75% 绿, 实心填充整个格子, 黑色字体
    // 填充方式: 绝对定位铺满单元格 (覆盖 td padding), 纵向相邻格子颜色边界直接对接无留白
    ...MSIA_PHASES.map((p) => ({
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700, fontSize: 11, color: p.color }}>
          {p.code}
        </span>
      ),
      key: p.code,
      width: 86,
      align: 'center' as const,
      onCell: () => ({
        // 评分格铺满色块后, 去掉单元格自身 padding/hover 背景/边框, 保证色块与相邻行对接
        className: 'msia-score-cell',
      }),
      render: (_: unknown, record: MsiaPlanItem) => {
        const s = record.phase_scores?.[p.code];
        // 未评审: 显示为空 (保持单元格高度稳定)
        if (!s) return <span style={{ display: 'inline-block', minWidth: 44 }} />;
        // 三档实心填充: <75% 红 / =75% 黄 / >75% 绿 (含浮点容差)
        const v = s.avg_score;
        const fill =
          v >= 0.7495 && v <= 0.7505
            ? '#FFFF00' // =75% 黄
            : v > 0.7505
              ? '#00CC00' // >75% 绿
              : '#FF6600'; // <75% 红
        return (
          <Tooltip
            title={`综合评分 ${s.avg_percent}% | 已评分 ${s.item_count} 项${s.source === 'historic' ? ' (补录)' : ''}`}
          >
            <div
              className="msia-score-fill"
              style={{ backgroundColor: fill }}
            >
              <span
                style={{
                  color: '#000000',
                  fontFamily: NUM_FONT,
                  fontWeight: 700,
                  fontSize: 12,
                  lineHeight: '18px',
                  position: 'relative',
                }}
              >
                {s.avg_percent}%
              </span>
            </div>
          </Tooltip>
        );
      },
    })),
    {
      title: '',
      key: 'action',
      width: 50,
      fixed: 'right',
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => navigate(`/projects/${record.planId}`)}
          style={{ padding: '0 4px' }}
        />
      ),
    },
  ];

  // 点击查询
  const handleSearch = () => {
    setCommitted({ keyword: keyword.trim() });
    setPage(1);
  };

  // 重置筛选
  const handleReset = () => {
    setKeyword('');
    setPlantFilter(undefined);
    setCommitted({ keyword: '' });
    setPage(1);
  };

  return (
    <div>
      <style>{`
        .msia-projects-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, #fafbfc 0%, #f0f2f5 100%) !important;
          border-bottom: 2px solid #2E5CE6 !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-projects-table .ant-table-tbody > tr:hover > td {
          background: #f0f7ff !important;
        }
        .msia-projects-table .ant-table-tbody > tr > td {
          padding: 8px 8px !important;
        }
        /* 评分单元格: 色块铺满整个格子, 纵向相邻行颜色边界直接对接 */
        .msia-projects-table td.msia-score-cell {
          padding: 0 !important;
          position: relative;
        }
        .msia-projects-table td.msia-score-cell .msia-score-fill {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 34px;
        }
        /* 固定列模式下的单元格背景由色块自身呈现, 避免 hover 底色盖住色块 */
        .msia-projects-table .ant-table-tbody > tr:hover > td.msia-score-cell {
          background: transparent !important;
        }
        /* 邻格水平边界: 色块自身即边界, 去掉单元格竖向边框造成的白线 */
        .msia-projects-table td.msia-score-cell + td.msia-score-cell {
          border-left: none !important;
        }
      `}</style>

      {/* ============ 顶部统计仪表盘 ============ */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #2E5CE6' }}>
            <Statistic
              title="项目总数"
              value={stats.total}
              prefix={<ProjectOutlined />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #0FB5BA' }}>
            <Statistic
              title="MSIA3 已完成"
              value={stats.done3}
              suffix={stats.inProgress3 > 0 ? `/ 进行中 ${stats.inProgress3}` : ''}
              valueStyle={{ color: '#0FB5BA', fontFamily: NUM_FONT, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #F97316' }}>
            <Statistic
              title="MSIA4 已完成"
              value={stats.done4}
              suffix={stats.inProgress4 > 0 ? `/ 进行中 ${stats.inProgress4}` : ''}
              valueStyle={{ color: '#F97316', fontFamily: NUM_FONT, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #10B981' }}>
            <Statistic
              title="MSIA5 已完成"
              value={stats.done5}
              suffix={stats.inProgress5 > 0 ? `/ 进行中 ${stats.inProgress5}` : ''}
              valueStyle={{ color: '#10B981', fontFamily: NUM_FONT, fontWeight: 700 }}
            />
          </Card>
        </Col>
      </Row>

      {/* ============ MSIA Result 指标卡 (各阶段平均分) ============ */}
      <Card
        size="small"
        style={{ marginBottom: 16, borderTop: '3px solid #2E5CE6' }}
        title={
          <Space>
            <DashboardOutlined style={{ color: '#2E5CE6' }} />
            <Text strong style={{ fontSize: 13 }}>MSIA Result</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>所有项目各阶段评审平均分</Text>
          </Space>
        }
      >
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {MSIA_PHASES.map((p) => {
            const result = phaseResults[p.code];
            const hasScore = result?.avg_score != null;
            const percent = hasScore ? (result!.avg_score! * 100) : null;
            return (
              <Tooltip
                key={p.code}
                title={hasScore ? `已评分: ${result!.count} 项` : '暂无评分数据'}
              >
                <div
                  style={{
                    flex: '1 1 120px',
                    minWidth: 120,
                    padding: '8px 12px',
                    backgroundColor: hasScore ? `${_sc(result!.avg_score)}0a` : '#fafafa',
                    border: `1px solid ${hasScore ? _sc(result!.avg_score) : '#e8e8e8'}`,
                    borderRadius: 4,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 2,
                  }}
                >
                  <Tag
                    style={{
                      backgroundColor: p.color,
                      color: '#fff',
                      fontWeight: 700,
                      fontFamily: NUM_FONT,
                      fontSize: 10,
                      margin: 0,
                      padding: '0 8px',
                      lineHeight: '18px',
                    }}
                  >
                    {p.code}
                  </Tag>
                  {hasScore ? (
                    <Text
                      strong
                      style={{
                        fontSize: 20,
                        fontFamily: NUM_FONT,
                        color: _stc(result!.avg_score),
                        lineHeight: 1.3,
                      }}
                    >
                      {percent!.toFixed(1)}
                      <span style={{ fontSize: 11 }}>%</span>
                    </Text>
                  ) : (
                    <Text
                      strong
                      style={{
                        fontSize: 20,
                        fontFamily: NUM_FONT,
                        color: '#bfbfbf',
                        lineHeight: 1.3,
                      }}
                    >
                      —
                    </Text>
                  )}
                  <Text type="secondary" style={{ fontSize: 9 }}>
                    {hasScore ? `${result!.count} items` : 'no data'}
                  </Text>
                </div>
              </Tooltip>
            );
          })}
        </div>
      </Card>

      {/* ============ Tabs: 项目管理 / 待评审项目 ============ */}
      <Card
        size="small"
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'projects',
              label: (
                <Space size={4}>
                  <ProjectOutlined />
                  <span>项目管理</span>
                  <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>{data.total}</Tag>
                </Space>
              ),
              children: (
                <>
                  {/* 顶部搜索区 + 管理员补录入口 (靠右) */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 16 }}>
                    <Input
                      placeholder="搜索关键字 (项目名/工单描述/负责人/SME/产线类型)"
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
                    <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
                      刷新
                    </Button>
                    {/* 评分补录入口: 仅管理员可见, 跳转历史评分录入页 */}
                    {isAdmin && (
                      <Tooltip title="针对需要补录分数的项目进行评分信息补录 (仅管理员)">
                        <Button
                          type="primary"
                          ghost
                          icon={<EditOutlined />}
                          onClick={() => navigate('/historic-score')}
                          style={{ marginLeft: 'auto', borderColor: '#2E5CE6' }}
                        >
                          补录入口
                        </Button>
                      </Tooltip>
                    )}
                  </div>

                  {/* 表格 */}
                  <div className="msia-projects-table">
                    <Table<MsiaPlanItem>
                      columns={columns}
                      dataSource={filteredItems}
                      rowKey={(record) => record.planId}
                      loading={loading}
                      scroll={{ x: 1150 }}
                      size="middle"
                      bordered
                      locale={{ emptyText: <Empty description="暂无项目数据" /> }}
                      onRow={(record) => ({
                        onClick: () => navigate(`/projects/${record.planId}`),
                        style: { cursor: 'pointer' },
                      })}
                      pagination={{
                        current: page,
                        pageSize,
                        total: data.total,
                        showSizeChanger: true,
                        showQuickJumper: true,
                        showTotal: (t) => `共 ${t} 条`,
                        pageSizeOptions: ['10', '20', '50', '100'],
                        onChange: (p, ps) => {
                          setPage(p);
                          setPageSize(ps);
                        },
                      }}
                    />
                  </div>
                </>
              ),
            },
            {
              key: 'pending',
              label: (
                <Space size={4}>
                  <FireOutlined style={{ color: '#F97316' }} />
                  <span>待评审项目</span>
                  {pendingReviews.length > 0 && (
                    <Tag color="orange" style={{ margin: 0, fontSize: 10 }}>{pendingReviews.length}</Tag>
                  )}
                </Space>
              ),
              children: (
                <>
                  {/* 顶部工具区 */}
                  <Space style={{ marginBottom: 16 }} wrap>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {pendingMonths === 1 ? '本月 + 下月' : `本月 + 下 ${pendingMonths} 月`} 计划评审但未完成的项目
                    </Text>
                    <Select
                      size="small"
                      value={pendingMonths}
                      onChange={(v) => setPendingMonths(v)}
                      style={{ width: 120 }}
                      options={[
                        { value: 1, label: '本月+下月' },
                        { value: 2, label: '本月+下2月' },
                        { value: 3, label: '本月+下3月' },
                      ]}
                    />
                    <Button
                      size="small"
                      icon={<ReloadOutlined />}
                      onClick={fetchPendingReviews}
                      loading={pendingLoading}
                    >
                      刷新
                    </Button>
                  </Space>

                  {/* 待评审项目列表 */}
                  {pendingReviews.length === 0 ? (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          暂无待评审项目 (本月及下月)
                        </Text>
                      }
                    />
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {pendingReviews.map((item) => {
                        const overduePhases = item.pending_phases.filter((p) => p.is_overdue);
                        return (
                          <div
                            key={item.planId}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 12,
                              padding: '10px 14px',
                              background: overduePhases.length > 0
                                ? 'linear-gradient(90deg, #fff1f0 0%, #fff7f3 100%)'
                                : '#fafafa',
                              border: `1px solid ${overduePhases.length > 0 ? '#ffccc7' : '#f0f0f0'}`,
                              borderRadius: 6,
                              transition: 'all 0.2s',
                            }}
                          >
                            {/* 项目信息 */}
                            <div style={{ flex: '1 1 200px', minWidth: 200 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Text strong style={{ fontSize: 12 }}>
                                  {item.projectName || item.order_description || `工单 ${item.orderId || '-'}`}
                                </Text>
                                {overduePhases.length > 0 && (
                                  <Tag color="red" icon={<ClockCircleOutlined />} style={{ fontSize: 10, margin: 0 }}>
                                    逾期 {overduePhases.length}
                                  </Tag>
                                )}
                              </div>
                              <Text type="secondary" style={{ fontSize: 10 }}>
                                {item.ownerName && `负责人: ${item.ownerName}`}
                                {item.leadUser && ` · 评审: ${item.leadUser}`}
                                {item.plantName && ` · ${item.plantName}`}
                              </Text>
                            </div>

                            {/* 待评审阶段按钮 */}
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                              {item.pending_phases.map((ph) => {
                                const meta = MSIA_PHASES.find((m) => m.code === ph.phase);
                                const color = meta?.color || '#8c8c8c';
                                return (
                                  <Tooltip
                                    key={ph.phase}
                                    title={
                                      <div style={{ fontSize: 11 }}>
                                        <div>{ph.phase} 评审</div>
                                        <div>计划日期: {formatDate(ph.plan_date)}</div>
                                        <div>
                                          {ph.is_overdue
                                            ? `已逾期 ${Math.abs(ph.days_until)} 天`
                                            : ph.days_until === 0
                                              ? '今天'
                                              : `${ph.days_until} 天后`}
                                        </div>
                                        <div style={{ marginTop: 4, color: '#2E5CE6' }}>
                                          点击直接进入评审 →
                                        </div>
                                      </div>
                                    }
                                  >
                                    <Button
                                      size="small"
                                      type="primary"
                                      ghost
                                      onClick={() => goToPhaseReview(item.planId, ph.phase_num)}
                                      style={{
                                        padding: '0 10px',
                                        height: 28,
                                        borderColor: color,
                                        color: color,
                                        fontWeight: 600,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 4,
                                      }}
                                    >
                                      <span
                                        style={{
                                          backgroundColor: color,
                                          color: '#fff',
                                          padding: '0 4px',
                                          borderRadius: 2,
                                          fontSize: 10,
                                          fontFamily: NUM_FONT,
                                          fontWeight: 700,
                                        }}
                                      >
                                        {ph.phase}
                                      </span>
                                      <span style={{ fontSize: 10 }}>
                                        {ph.is_overdue
                                          ? `逾期${Math.abs(ph.days_until)}d`
                                          : ph.days_until === 0
                                            ? '今天'
                                            : `${ph.days_until}d`}
                                      </span>
                                      <ArrowRightOutlined style={{ fontSize: 10 }} />
                                    </Button>
                                  </Tooltip>
                                );
                              })}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
