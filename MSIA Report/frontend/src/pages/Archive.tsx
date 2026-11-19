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
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  EyeOutlined,
  InboxOutlined,
  TrophyOutlined,
  CheckCircleOutlined,
  ApartmentOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  listArchivedProjectsApi,
} from '@/api/archive';
import type { ArchivedProjectItem, ArchivedProjectPageResponse } from '@/api/archive';
import { formatDate } from '@/utils/format';
import { NUM_FONT } from '@/utils/fonts';

const { Text } = Typography;

// 默认分页大小
const DEFAULT_PAGE_SIZE = 20;

// MSIA 阶段元数据 (与 Projects.tsx 保持一致)
const MSIA_PHASES = [
  { code: 'MSIA1', color: '#8c8c8c', label: 'M1' },
  { code: 'MSIA2', color: '#2E5CE6', label: 'M2' },
  { code: 'MSIA3', color: '#0FB5BA', label: 'M3' },
  { code: 'MSIA4', color: '#F97316', label: 'M4' },
  { code: 'MSIA5', color: '#10B981', label: 'M5' },
];

// 评分三档填充色 (与项目管理一致: <75% 红 / =75% 黄 / >75% 绿)
function scoreFill(v: number): string {
  if (v >= 0.7495 && v <= 0.7505) return '#FFFF00';
  return v > 0.7505 ? '#00CC00' : '#FF6600';
}

// 项目存档列表页 (已完成全部阶段审核的项目, 仅查询)
export default function Archive() {
  const navigate = useNavigate();

  // 列表查询状态
  const [keyword, setKeyword] = useState('');
  const [plantFilter, setPlantFilter] = useState<string | undefined>(undefined);
  const [committed, setCommitted] = useState<{ keyword: string }>({ keyword: '' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [data, setData] = useState<ArchivedProjectPageResponse>({
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
    total_pages: 0,
  });
  const [loading, setLoading] = useState(false);

  // 拉取归档列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listArchivedProjectsApi({
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

  // 工厂选项 (当前页数据提取, 去重)
  const plantOptions = useMemo(() => {
    const plants = new Set<string>();
    data.items.forEach((it) => {
      if (it.plantName) plants.add(it.plantName);
    });
    return Array.from(plants).sort();
  }, [data.items]);

  // 前端按工厂过滤
  const filteredItems = useMemo(() => {
    if (!plantFilter) return data.items;
    return data.items.filter((it) => it.plantName === plantFilter);
  }, [data.items, plantFilter]);

  // 顶部统计 (基于当前页过滤后的数据)
  const stats = useMemo(() => {
    const items = filteredItems;
    const total = items.length;
    const overallScores = items
      .map((it) => it.overall)
      .filter((v): v is number => v != null);
    const avgOverall = overallScores.length
      ? (overallScores.reduce((s, v) => s + v, 0) / overallScores.length) * 100
      : null;
    const thisYear = dayjs().year();
    const completedThisYear = items.filter((it) =>
      it.msia5ActualDate && dayjs(it.msia5ActualDate).year() === thisYear,
    ).length;
    const plants = new Set(items.map((it) => it.plantName).filter(Boolean));
    return { total, avgOverall, completedThisYear, plantCount: plants.size };
  }, [filteredItems]);

  // 表格列定义 (与项目管理列表风格一致)
  const columns: ColumnsType<ArchivedProjectItem> = [
    {
      title: <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>NO.</span>,
      dataIndex: 'seq',
      key: 'seq',
      width: 56,
      fixed: 'left',
      render: (v: number) => (
        <Text strong style={{ fontFamily: NUM_FONT, fontSize: 11, color: '#2E5CE6' }}>
          {v}
        </Text>
      ),
    },
    {
      title: '项目',
      key: 'project',
      width: 210,
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
      render: (v: string | null) =>
        v ? (
          <Tag color="blue" style={{ fontSize: 10, margin: 0, width: 'fit-content', padding: '0 4px', lineHeight: '14px' }}>
            {v}
          </Tag>
        ) : (
          <Text type="secondary" style={{ fontSize: 10 }}>-</Text>
        ),
    },
    {
      title: '负责人',
      key: 'owner',
      width: 100,
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
    {
      title: '工厂',
      dataIndex: 'plantName',
      key: 'plantName',
      width: 80,
      render: (v: string | null) => v || <Text type="secondary">-</Text>,
    },
    // MSIA1~5 各阶段综合评分 (实心色块, 与项目管理一致)
    ...MSIA_PHASES.map((p) => ({
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700, fontSize: 11, color: p.color }}>
          {p.code}
        </span>
      ),
      key: p.code,
      width: 82,
      align: 'center' as const,
      onCell: () => ({ className: 'msia-archive-score-cell' }),
      render: (_: unknown, record: ArchivedProjectItem) => {
        const s = record.phase_scores?.[p.code];
        if (!s) return <span style={{ display: 'inline-block', minWidth: 44 }} />;
        return (
          <Tooltip
            title={`综合评分 ${s.avg_percent}% | 已评分 ${s.item_count} 项${s.source === 'historic' ? ' (补录)' : ''}`}
          >
            <div className="msia-archive-score-fill" style={{ backgroundColor: scoreFill(s.avg_score) }}>
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
      title: '综合评分',
      key: 'overall',
      width: 96,
      align: 'center',
      render: (_, record) => {
        const v = record.overall;
        if (v == null) return <Text type="secondary">-</Text>;
        const fill = scoreFill(v);
        return (
          <Tooltip title="MSIA1~5 各阶段综合评分的算术平均">
            <Tag
              style={{
                backgroundColor: fill,
                color: '#000',
                fontWeight: 700,
                fontFamily: NUM_FONT,
                fontSize: 12,
                margin: 0,
                padding: '0 8px',
                lineHeight: '20px',
                borderRadius: 2,
              }}
            >
              {(v * 100).toFixed(1)}%
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '完成日期',
      key: 'completed',
      width: 105,
      render: (_, record) => (
        <Tooltip title="MSIA5 终验收实际日期">
          <Space size={4}>
            <CheckCircleOutlined style={{ color: '#10B981', fontSize: 11 }} />
            <Text style={{ fontSize: 12, fontFamily: NUM_FONT }}>
              {formatDate(record.msia5ActualDate) || '-'}
            </Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '问题',
      key: 'issues',
      width: 90,
      align: 'center',
      render: (_, record) => {
        const st = record.issue_stats;
        if (!st || st.total === 0) return <Text type="secondary" style={{ fontSize: 11 }}>0</Text>;
        return (
          <Tooltip title={`共 ${st.total} 个问题, 未关闭 ${st.unclosed} 个`}>
            <Space size={4}>
              <Text style={{ fontSize: 12, fontFamily: NUM_FONT }}>{st.total}</Text>
              {st.unclosed > 0 ? (
                <Tag color="orange" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '14px' }}>
                  未关闭 {st.unclosed}
                </Tag>
              ) : (
                <Tag color="success" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '14px' }}>
                  已关闭
                </Tag>
              )}
            </Space>
          </Tooltip>
        );
      },
    },
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
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/archive/${record.planId}`);
          }}
          style={{ padding: '0 4px' }}
        />
      ),
    },
  ];

  const handleSearch = () => {
    setCommitted({ keyword: keyword.trim() });
    setPage(1);
  };

  const handleReset = () => {
    setKeyword('');
    setPlantFilter(undefined);
    setCommitted({ keyword: '' });
    setPage(1);
  };

  return (
    <div>
      <style>{`
        .msia-archive-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, #fafbfc 0%, #f0f2f5 100%) !important;
          border-bottom: 2px solid #2E5CE6 !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-archive-table .ant-table-tbody > tr:hover > td {
          background: #f0f7ff !important;
        }
        .msia-archive-table .ant-table-tbody > tr > td {
          padding: 8px 8px !important;
        }
        .msia-archive-table td.msia-archive-score-cell {
          padding: 0 !important;
          position: relative;
        }
        .msia-archive-table td.msia-archive-score-cell .msia-archive-score-fill {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 34px;
        }
        .msia-archive-table .ant-table-tbody > tr:hover > td.msia-archive-score-cell {
          background: transparent !important;
        }
        .msia-archive-table td.msia-archive-score-cell + td.msia-archive-score-cell {
          border-left: none !important;
        }
      `}</style>

      {/* ============ 顶部统计 ============ */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #722ED1' }}>
            <Statistic
              title="存档项目"
              value={stats.total}
              prefix={<InboxOutlined />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#722ED1' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #2E5CE6' }}>
            <Statistic
              title="平均综合评分"
              value={stats.avgOverall ?? '-'}
              suffix={stats.avgOverall != null ? '%' : ''}
              precision={stats.avgOverall != null ? 1 : undefined}
              prefix={<TrophyOutlined />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#2E5CE6' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #10B981' }}>
            <Statistic
              title="本年度完成"
              value={stats.completedThisYear}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#10B981' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" style={{ borderTop: '3px solid #0FB5BA' }}>
            <Statistic
              title="覆盖工厂"
              value={stats.plantCount}
              prefix={<ApartmentOutlined />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#0FB5BA' }}
            />
          </Card>
        </Col>
      </Row>

      {/* ============ 归档项目列表 ============ */}
      <Card
        size="small"
        styles={{ body: { padding: '12px 16px' } }}
        title={
          <Space>
            <InboxOutlined style={{ color: '#722ED1' }} />
            <Text strong style={{ fontSize: 13 }}>已归档项目</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              已完成 MSIA 全部阶段审核的项目 (只读查询)
            </Text>
          </Space>
        }
      >
        {/* 顶部搜索区 */}
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
        </div>

        {/* 表格 */}
        <div className="msia-archive-table">
          <Table<ArchivedProjectItem>
            columns={columns}
            dataSource={filteredItems}
            rowKey={(record) => record.planId}
            loading={loading}
            scroll={{ x: 1350 }}
            size="middle"
            bordered
            locale={{ emptyText: <Empty description="暂无归档项目" /> }}
            onRow={(record) => ({
              onClick: () => navigate(`/archive/${record.planId}`),
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
      </Card>
    </div>
  );
}
