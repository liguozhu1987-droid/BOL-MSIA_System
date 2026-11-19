import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Image as AntImage,
  Modal,
  Row,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  Result,
} from 'antd';
import {
  ApartmentOutlined,
  InboxOutlined,
  ArrowLeftOutlined,
  BugOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  PaperClipOutlined,
  ProjectOutlined,
  ReloadOutlined,
  TrophyOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import { getMsiaPlanDetailApi } from '@/api/msiaPlan';
import type { MsiaPlanDetail } from '@/api/msiaPlan';
import {
  getArchivedPhaseReviewsApi,
  listArchivedProjectsApi,
} from '@/api/archive';
import type {
  ArchivedPhaseReviews,
  ArchivedProjectItem,
  ArchivedReviewItem,
} from '@/api/archive';
import {
  getIssues,
  getIssue,
  listIssueEvidence,
  listIssueClosureEvidence,
  fetchAttachmentBlobUrl,
} from '@/api/issues';
import type { Issue, IssueAttachment } from '@/api/issues';
import PhaseReportModal from '@/components/PhaseReportModal';
import { formatDate, formatDateTime } from '@/utils/format';
import { NUM_FONT } from '@/utils/fonts';

const { Text, Paragraph } = Typography;

// ============ 问题状态/优先级/严重等级映射 (与问题管理模块对齐) ============
const issueStatusMap: Record<string, { color: string; text: string; icon?: React.ReactNode }> = {
  open: { color: 'default', text: '待处理', icon: <ClockCircleOutlined /> },
  in_progress: { color: 'processing', text: '处理中', icon: <BugOutlined /> },
  pending_verification: { color: 'warning', text: '待验证' },
  closed: { color: 'success', text: '已关闭', icon: <CheckCircleOutlined /> },
};

const issuePriorityMap: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高' },
  medium: { color: 'blue', text: '中' },
  low: { color: 'default', text: '低' },
};

const issueSeverityMap: Record<string, { color: string; text: string }> = {
  H: { color: 'red', text: 'H 高' },
  M: { color: 'orange', text: 'M 中' },
  L: { color: 'default', text: 'L 低' },
};

const phaseBadgeColor: Record<string, string> = {
  MSIA1: 'blue',
  MSIA2: 'cyan',
  MSIA3: 'geekblue',
  MSIA4: 'purple',
  MSIA5: 'magenta',
};

// 判断附件是否为图片
function isImageAttachment(att: IssueAttachment): boolean {
  return !!att.MimeType?.startsWith('image/') ||
    /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '');
}

// 判断附件是否为 PDF
function isPdfAttachment(att: IssueAttachment): boolean {
  return !!att.MimeType?.includes('pdf') || /\.pdf$/i.test(att.FileName || '');
}

// 安全显示文本
function showText(v: string | null | undefined): React.ReactNode {
  if (v === null || v === undefined || v === '') return <Text type="secondary">-</Text>;
  return v;
}

// 阶段定义: MSIA1 - MSIA5 (与 ProjectDetail 保持一致)
const ALL_PHASES = [
  { key: '1', label: 'MSIA1', color: '#8c8c8c', desc: '立项启动', timing: 'Project Kick-off' },
  { key: '2', label: 'MSIA2', color: '#2E5CE6', desc: '需求分析', timing: 'Planning & Design' },
  { key: '3', label: 'MSIA3', color: '#0FB5BA', desc: '设计冻结', timing: 'Design Freeze' },
  { key: '4', label: 'MSIA4', color: '#F97316', desc: '预验收', timing: 'Pre-Acceptance' },
  { key: '5', label: 'MSIA5', color: '#10B981', desc: '终验收', timing: 'Final Acceptance' },
] as const;

// 评分三档填充色 (与项目管理一致: <75% 红 / =75% 黄 / >75% 绿)
function scoreFill(v: number): string {
  if (v >= 0.7495 && v <= 0.7505) return '#FFFF00';
  return v > 0.7505 ? '#00CC00' : '#FF6600';
}

// 从 plan 详情中提取阶段日期 (动态字段)
function getPhaseDates(plan: Record<string, unknown> | null) {
  if (!plan) return {};
  const result: Record<string, { plan: string | null; actual: string | null }> = {};
  for (let i = 1; i <= 5; i++) {
    const planDate = plan[`msia${i}PlanDate`] as string | null;
    const actualDate = plan[`msia${i}ActualDate`] as string | null;
    result[i] = { plan: planDate || null, actual: actualDate || null };
  }
  return result;
}

// 归档项目详情页 (只读查询: 阶段日期 + 各阶段评分 + 审核记录明细)
export default function ArchiveDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MsiaPlanDetail | null>(null);
  // 归档列表项 (含 phase_scores / overall / issue_stats 注入字段)
  const [archivedItem, setArchivedItem] = useState<ArchivedProjectItem | null>(null);

  // 阶段审核记录弹窗
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewPhase, setReviewPhase] = useState<string | null>(null);
  const [reviewData, setReviewData] = useState<ArchivedPhaseReviews | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);

  // 阶段审核报告弹窗 (复用项目管理模块的 Report MSIA 模板报告)
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [reportPhaseCode, setReportPhaseCode] = useState<string | null>(null);
  // 合并报告模式: 传入 "MSIA1,MSIA2,MSIA3" 时启用, 否则为 null (单阶段模式)
  const [combinedReportPhases, setCombinedReportPhases] = useState<string | null>(null);

  // 项目问题清单 (只读)
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issuesTotal, setIssuesTotal] = useState(0);

  // 问题详情抽屉 (只读)
  const [issueDrawerOpen, setIssueDrawerOpen] = useState(false);
  const [currentIssue, setCurrentIssue] = useState<Issue | null>(null);
  const [evidence, setEvidence] = useState<IssueAttachment[]>([]);
  const [closureEvidence, setClosureEvidence] = useState<IssueAttachment[]>([]);
  const [attachmentUrls, setAttachmentUrls] = useState<Record<number, string>>({});
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string>('');

  // 拉取详情数据
  const fetchDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const detailRes = await getMsiaPlanDetailApi(id);
      setDetail(detailRes);

      // 通过 orderId 反查归档列表项, 获取注入的阶段评分/综合评分/问题统计
      const planData = detailRes.plan as Record<string, unknown> | null;
      const orderId = planData?.orderId as string | undefined;
      if (orderId) {
        try {
          const listRes = await listArchivedProjectsApi({ order_id: orderId, page: 1, page_size: 20 });
          const matched = listRes.items.find((it) => String(it.planId) === String(id));
          if (matched) setArchivedItem(matched);
        } catch {
          // 归档列表查询失败不阻塞详情展示
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchDetail();
  }, [fetchDetail]);

  // 打开阶段审核记录弹窗 (只读)
  const openPhaseReviews = async (phaseCode: string) => {
    if (!id) return;
    setReviewPhase(phaseCode);
    setReviewModalOpen(true);
    setReviewLoading(true);
    setReviewData(null);
    try {
      const res = await getArchivedPhaseReviewsApi(id, phaseCode);
      setReviewData(res);
    } catch {
      // 错误已由 axios 拦截器统一提示
      setReviewModalOpen(false);
    } finally {
      setReviewLoading(false);
    }
  };

  // 拉取本项目问题清单 (只读, 全量不分页: 归档项目问题数量有限)
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      setIssuesLoading(true);
      try {
        const res = await getIssues({ plan_id: id, page: 1, page_size: 200 });
        if (!cancelled) {
          setIssues(res.items || []);
          setIssuesTotal(res.total || 0);
        }
      } catch {
        if (!cancelled) {
          setIssues([]);
          setIssuesTotal(0);
        }
      } finally {
        if (!cancelled) setIssuesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // 打开问题详情抽屉 (只读): 拉取详情 + 证据附件 Blob URL
  const openIssueDetail = async (issue: Issue) => {
    setIssueDrawerOpen(true);
    setCurrentIssue(issue);
    setEvidence([]);
    setClosureEvidence([]);
    setAttachmentUrls({});
    let fresh: Issue | null = null;
    try {
      fresh = await getIssue(issue.Id);
      setCurrentIssue(fresh);
    } catch {
      fresh = issue; // 详情失败时退回列表数据
    }
    // 审核证据 + 关闭证据 (只读展示)
    let evAtts: IssueAttachment[] = [];
    let clAtts: IssueAttachment[] = [];
    try {
      evAtts = fresh.Evidence && fresh.Evidence.length > 0
        ? fresh.Evidence
        : await listIssueEvidence(issue.Id);
    } catch {
      evAtts = [];
    }
    try {
      clAtts = fresh.ClosureEvidence && fresh.ClosureEvidence.length > 0
        ? fresh.ClosureEvidence
        : await listIssueClosureEvidence(issue.Id);
    } catch {
      clAtts = [];
    }
    setEvidence(evAtts);
    setClosureEvidence(clAtts);
    const entries = await Promise.all(
      [...evAtts, ...clAtts].map(async (att) => {
        try {
          const url = await fetchAttachmentBlobUrl(att.Id);
          return [att.Id, url] as const;
        } catch {
          return [att.Id, ''] as const;
        }
      }),
    );
    const urls: Record<number, string> = {};
    for (const [attId, url] of entries) {
      if (url) urls[attId] = url;
    }
    setAttachmentUrls(urls);
  };

  // 渲染附件卡片 (只读: 图片点击预览, PDF 新窗口查看, 其他下载)
  const renderAttachmentCards = (atts: IssueAttachment[]) => {
    if (atts.length === 0) {
      return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无附件" style={{ margin: '12px 0' }} />;
    }
    const cardStyle: React.CSSProperties = {
      width: 120,
      height: 120,
      border: '1px solid #d9d9d9',
      borderRadius: 2,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      gap: 4,
      background: '#fafafa',
      padding: 4,
    };
    return (
      <Space size="small" wrap>
        {atts.map((att) => {
          const isImg = isImageAttachment(att);
          const isPdf = isPdfAttachment(att);
          const url = attachmentUrls[att.Id];
          if (isImg && url) {
            return (
              <div key={att.Id} style={{ display: 'inline-block', textAlign: 'center' }}>
                <AntImage
                  width={120}
                  height={120}
                  src={url}
                  alt={att.FileName}
                  style={{ cursor: 'pointer', border: '1px solid #d9d9d9', borderRadius: 2, objectFit: 'cover' }}
                  onClick={() => {
                    setPreviewSrc(url);
                    setPreviewOpen(true);
                  }}
                  preview={{
                    visible: previewOpen && previewSrc === url,
                    onVisibleChange: (v) => {
                      if (!v) {
                        setPreviewOpen(false);
                        setPreviewSrc('');
                      }
                    },
                  }}
                />
                <div style={{ fontSize: 10, color: '#888', maxWidth: 120, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {att.FileName}
                </div>
              </div>
            );
          }
          if (url) {
            return (
              <Tooltip key={att.Id} title={isPdf ? '点击查看 PDF' : '点击下载文件'}>
                <div
                  style={cardStyle}
                  onClick={() => {
                    if (isPdf) {
                      window.open(url, '_blank');
                    } else {
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = att.FileName;
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);
                    }
                  }}
                >
                  {isPdf ? (
                    <FilePdfOutlined style={{ fontSize: 36, color: '#EF4444' }} />
                  ) : (
                    <PaperClipOutlined style={{ fontSize: 36, color: '#722ED1' }} />
                  )}
                  <Text style={{ fontSize: 10, textAlign: 'center' }} ellipsis>{att.FileName}</Text>
                  <EyeOutlined style={{ fontSize: 10, color: '#722ED1' }} />
                </div>
              </Tooltip>
            );
          }
          return (
            <Tooltip key={att.Id} title={att.FileName}>
              <div style={{ ...cardStyle, cursor: 'default' }}>
                <PaperClipOutlined style={{ fontSize: 36, color: '#bfbfbf' }} />
                <Text type="secondary" style={{ fontSize: 10, textAlign: 'center' }} ellipsis>{att.FileName}</Text>
              </div>
            </Tooltip>
          );
        })}
      </Space>
    );
  };

  // 阶段日期
  const phaseDates = getPhaseDates(detail?.plan ?? null);
  const plan = (detail?.plan ?? null) as Record<string, unknown> | null;

  // 综合评分 (五阶段算术平均, 后端注入)
  const overall = archivedItem?.overall ?? null;

  // 审核记录表格列
  const reviewColumns: ColumnsType<ArchivedReviewItem> = [
    {
      title: <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>NO.</span>,
      dataIndex: 'seq',
      key: 'seq',
      width: 56,
      render: (v: number) => (
        <Text strong style={{ fontFamily: NUM_FONT, fontSize: 11, color: '#2E5CE6' }}>{v}</Text>
      ),
    },
    {
      title: '检查项',
      key: 'item',
      width: 220,
      render: (_, record) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Text strong style={{ fontSize: 12 }}>{record.item_name}</Text>
          {record.item_type && (
            <Tag style={{ fontSize: 10, margin: 0, width: 'fit-content', padding: '0 4px', lineHeight: '14px' }}>
              {record.item_type}
            </Tag>
          )}
        </div>
      ),
    },
    {
      title: '要求',
      dataIndex: 'request',
      key: 'request',
      width: 260,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="secondary" style={{ fontSize: 11 }} ellipsis>{v}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '评分',
      key: 'score',
      width: 84,
      align: 'center',
      onCell: () => ({ className: 'msia-archive-review-score-cell' }),
      render: (_, record) => {
        if (record.score == null) {
          return (
            <Text type="secondary" style={{ fontSize: 11 }}>-</Text>
          );
        }
        return (
          <div className="msia-archive-review-score-fill" style={{ backgroundColor: scoreFill(record.score) }}>
            <span style={{ color: '#000', fontFamily: NUM_FONT, fontWeight: 700, fontSize: 12, lineHeight: '18px' }}>
              {record.score_percent}%
            </span>
          </div>
        );
      },
    },
    {
      title: '结果',
      dataIndex: 'result_text',
      key: 'result_text',
      width: 110,
      render: (v: string | null) =>
        v ? <Tag style={{ fontSize: 10, margin: 0 }}>{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '评审意见',
      dataIndex: 'comments',
      key: 'comments',
      width: 260,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text style={{ fontSize: 11 }} ellipsis>{v}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '评审人',
      dataIndex: 'reviewer_name',
      key: 'reviewer_name',
      width: 90,
      render: (v: string | null) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      key: 'submitted_at',
      width: 120,
      render: (v: string | null) =>
        v ? <Text style={{ fontSize: 11, fontFamily: NUM_FONT }}>{v}</Text> : <Text type="secondary">-</Text>,
    },
  ];

  // 项目问题清单表格列 (只读, 参照问题管理模块精简)
  const issueColumns: ColumnsType<Issue> = [
    {
      title: <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>Issue No</span>,
      dataIndex: 'IssueNo',
      key: 'IssueNo',
      width: 150,
      fixed: 'left',
      render: (v: string) => <Text code style={{ fontSize: 12, color: '#722ED1' }}>{v}</Text>,
    },
    {
      title: 'MSIA阶段',
      dataIndex: 'PhaseCode',
      key: 'PhaseCode',
      width: 96,
      render: (v: string | null) => v ? (
        <Tag color={phaseBadgeColor[v] || 'default'} style={{ fontSize: 11 }}>{v}</Tag>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: '问题标题',
      dataIndex: 'Title',
      key: 'Title',
      width: 240,
      ellipsis: { showTitle: false },
      render: (v: string, record) => (
        <Tooltip title={v} placement="topLeft">
          <Space size={4} style={{ minWidth: 0 }}>
            <Text style={{ fontSize: 12 }}>{v}</Text>
            {record.ItemName && (
              <Tag style={{ fontSize: 10, margin: 0 }}>{record.ItemName}</Tag>
            )}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '严重',
      dataIndex: 'Severity',
      key: 'Severity',
      width: 76,
      align: 'center',
      render: (v: string | null) => v ? (
        <Tag color={issueSeverityMap[v]?.color || 'default'} style={{ fontSize: 11, margin: 0 }}>
          {issueSeverityMap[v]?.text || v}
        </Tag>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: '状态',
      dataIndex: 'Status',
      key: 'Status',
      width: 100,
      render: (v: string) => {
        const info = issueStatusMap[v];
        return (
          <Tag color={info?.color || 'default'} icon={info?.icon} style={{ fontSize: 11, margin: 0 }}>
            {info?.text || v}
          </Tag>
        );
      },
    },
    {
      title: '责任人',
      dataIndex: 'OwnerName',
      key: 'OwnerName',
      width: 100,
      render: (v: string | null) => v || <Text type="secondary">-</Text>,
    },
    {
      title: '整改完成日期',
      dataIndex: 'Deadline',
      key: 'Deadline',
      width: 110,
      render: (v: string | null) =>
        v ? <Text style={{ fontSize: 11, fontFamily: NUM_FONT }}>{formatDate(v)}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '关闭时间',
      dataIndex: 'ClosedAt',
      key: 'ClosedAt',
      width: 110,
      render: (v: string | null) =>
        v ? (
          <Text style={{ fontSize: 11, fontFamily: NUM_FONT, color: '#10B981' }}>{formatDateTime(v)}</Text>
        ) : <Text type="secondary">未关闭</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 70,
      fixed: 'right',
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => openIssueDetail(record)}
          style={{ padding: '0 4px' }}
        />
      ),
    },
  ];

  if (loading) {
    return (
      <Card>
        <Skeleton active paragraph={{ rows: 12 }} />
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <Result
          status="error"
          title="加载失败"
          subTitle={error}
          extra={
            <Button type="primary" icon={<ReloadOutlined />} onClick={fetchDetail}>
              重试
            </Button>
          }
        />
      </Card>
    );
  }

  return (
    <div>
      <style>{`
        .msia-archive-review-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, #fafbfc 0%, #f0f2f5 100%) !important;
          border-bottom: 2px solid #722ED1 !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-archive-review-table .ant-table-tbody > tr > td {
          padding: 8px 8px !important;
        }
        .msia-archive-review-table td.msia-archive-review-score-cell {
          padding: 0 !important;
          position: relative;
        }
        .msia-archive-review-table td.msia-archive-review-score-cell .msia-archive-review-score-fill {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          min-height: 34px;
        }
        /* 问题清单表格 (与审核记录表格同风格) */
        .msia-archive-issue-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, #fafbfc 0%, #f0f2f5 100%) !important;
          border-bottom: 2px solid #722ED1 !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-archive-issue-table .ant-table-tbody > tr > td {
          padding: 8px 8px !important;
        }
        .msia-archive-issue-table .ant-table-tbody > tr:hover > td {
          background: #faf5ff !important;
        }
      `}</style>

      {/* 返回按钮 */}
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/archive')}
        style={{ marginBottom: 12, paddingLeft: 0 }}
      >
        返回存档列表
      </Button>

      {/* ============ 顶部基本信息卡 ============ */}
      <Card
        size="small"
        style={{ marginBottom: 16, borderTop: '3px solid #722ED1' }}
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>PROJECT</Text>}
              value={(plan?.projectName as string) || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600 }}
              prefix={<ProjectOutlined style={{ color: '#722ED1' }} />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>OWNER</Text>}
              value={archivedItem?.ownerName || (plan?.name_in_charge as string) || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600, color: '#2E5CE6' }}
              prefix={<UserOutlined style={{ color: '#2E5CE6' }} />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>LEAD REVIEWER</Text>}
              value={archivedItem?.leadUser || (plan?.leadUser as string) || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600 }}
              prefix={<UserOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>COMPLETED</Text>}
              value={formatDate((plan?.msia5ActualDate as string) || null) || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600, color: '#10B981', fontFamily: NUM_FONT }}
              prefix={<CheckCircleOutlined style={{ color: '#10B981' }} />}
            />
          </Col>
        </Row>
      </Card>

      {/* ============ 关键信息卡 (工厂/产线/供应商/综合评分) ============ */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <Space>
            <ApartmentOutlined />
            <Text strong>工厂 / 产线信息</Text>
          </Space>
        }
        extra={
          overall != null ? (
            <Tooltip title="MSIA1~5 各阶段综合评分的算术平均">
              <Space size={4}>
                <TrophyOutlined style={{ color: '#722ED1' }} />
                <Text strong style={{ fontFamily: NUM_FONT, fontSize: 14, color: '#722ED1' }}>
                  综合评分 {(overall * 100).toFixed(1)}%
                </Text>
              </Space>
            </Tooltip>
          ) : null
        }
      >
        <Row gutter={16}>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="工厂">
                {archivedItem?.plantName ? <Tag color="blue">{archivedItem.plantName}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="产线">
                {archivedItem?.lineName || <Text type="secondary">-</Text>}
              </Descriptions.Item>
            </Descriptions>
          </Col>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="产线类型">
                {archivedItem?.lineType ? <Tag color="geekblue">{archivedItem.lineType}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="项目类型">
                {archivedItem?.projectType ? <Tag color="geekblue">{archivedItem.projectType}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
            </Descriptions>
          </Col>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="供应商">
                {archivedItem?.supplerName || <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="SME">
                <Space size={4} wrap>
                  {archivedItem?.sme1 && <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>{archivedItem.sme1}</Tag>}
                  {archivedItem?.sme2 && <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>{archivedItem.sme2}</Tag>}
                  {!archivedItem?.sme1 && !archivedItem?.sme2 && <Text type="secondary">-</Text>}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>

      {/* ============ 阶段总览 (MSIA1 - MSIA5, 只读, 各阶段审核记录/审核报告均可查看) ============ */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {ALL_PHASES.map((phase) => {
          const dates = phaseDates[phase.key];
          const planDate = dates?.plan || null;
          const actualDate = dates?.actual || null;
          const score = archivedItem?.phase_scores?.[phase.label] ?? null;

          const phaseCard = (
            <Col xs={24} sm={12} lg={8} xl={4} key={phase.key}>
              <Card
                size="small"
                style={{
                  borderTop: `3px solid ${phase.color}`,
                  height: '100%',
                }}
                styles={{ body: { minHeight: 140, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' } }}
                title={
                  <Space>
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 38,
                        height: 20,
                        backgroundColor: phase.color,
                        color: '#fff',
                        fontSize: 10,
                        fontWeight: 700,
                        fontFamily: NUM_FONT,
                        borderRadius: 2,
                      }}
                    >
                      {phase.label}
                    </div>
                    <Text strong style={{ fontSize: 12 }}>{phase.desc}</Text>
                  </Space>
                }
                actions={[
                  <Tooltip title="查看阶段审核记录" key="reviews">
                    <Button
                      type="link"
                      size="small"
                      icon={<FileSearchOutlined />}
                      onClick={() => openPhaseReviews(phase.label)}
                    >
                      审核记录
                    </Button>
                  </Tooltip>,
                  <Tooltip title="查看阶段审核报告 (Report MSIA 模板)" key="report">
                    <Button
                      type="link"
                      size="small"
                      icon={<FileTextOutlined />}
                      onClick={() => {
                        setReportPhaseCode(phase.label);
                        setCombinedReportPhases(null);
                        setReportModalOpen(true);
                      }}
                    >
                      报告
                    </Button>
                  </Tooltip>,
                ]}
              >
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  {actualDate ? (
                    <Tag color="success" icon={<CheckCircleOutlined />}>已完成</Tag>
                  ) : (
                    <Tag color="default" icon={<ClockCircleOutlined />}>未维护日期</Tag>
                  )}
                  <Text style={{ fontSize: 12 }}>
                    计划: <Text strong>{formatDate(planDate) || '-'}</Text>
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    实际: <Text strong style={{ color: actualDate ? '#10B981' : undefined }}>
                      {formatDate(actualDate) || '-'}
                    </Text>
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    评分:{' '}
                    {score ? (
                      <Text strong style={{ fontFamily: NUM_FONT, color: '#000' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '0 6px',
                            backgroundColor: scoreFill(score.avg_score),
                            borderRadius: 2,
                            lineHeight: '18px',
                          }}
                        >
                          {score.avg_percent}%
                        </span>
                      </Text>
                    ) : (
                      <Text type="secondary">-</Text>
                    )}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 10, fontStyle: 'italic' }}>
                    {phase.timing}
                  </Text>
                </Space>
              </Card>
            </Col>
          );

          // 在 MSIA3 与 MSIA4 之间插入 MSIA1&2&3 汇总报告卡 (与项目管理对齐)
          if (phase.key === '4') {
            return [
              <Col xs={24} sm={12} lg={8} xl={4} key="msia-archive-combined">
                <Card
                  size="small"
                  style={{
                    borderTop: '3px solid #722ED1',
                    background: 'linear-gradient(180deg, #faf5ff 0%, #fff 60%)',
                    height: '100%',
                  }}
                  styles={{ body: { minHeight: 140, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' } }}
                  title={
                    <Space>
                      <div
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          padding: '0 6px',
                          height: 20,
                          backgroundColor: '#722ED1',
                          color: '#fff',
                          fontSize: 10,
                          fontWeight: 700,
                          fontFamily: NUM_FONT,
                          borderRadius: 2,
                        }}
                      >
                        M1+2+3
                      </div>
                      <Text strong style={{ fontSize: 12 }}>阶段汇总</Text>
                    </Space>
                  }
                  actions={[
                    <Tooltip title="查看 MSIA1+2+3 汇总报告" key="report">
                      <Button
                        type="link"
                        size="small"
                        icon={<FileTextOutlined />}
                        onClick={() => {
                          setReportPhaseCode(null);
                          setCombinedReportPhases('MSIA1,MSIA2,MSIA3');
                          setReportModalOpen(true);
                        }}
                      >
                        报告
                      </Button>
                    </Tooltip>,
                  ]}
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Tag color="purple">汇总报告</Tag>
                    <Text style={{ fontSize: 12 }}>
                      覆盖: <Text strong>MSIA1 / MSIA2 / MSIA3</Text>
                    </Text>
                    <Text type="secondary" style={{ fontSize: 10, fontStyle: 'italic' }}>
                      Combined Phase Summary
                    </Text>
                  </Space>
                </Card>
              </Col>,
              phaseCard,
            ];
          }

          return [phaseCard];
        })}
      </Row>

      {/* ============ 关键日期 + 问题统计 ============ */}
      <Card
        size="small"
        title={
          <Space>
            <ClockCircleOutlined />
            <Text strong>关键日期与问题统计</Text>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col span={5}>
            <Statistic
              title="工单下发日期"
              value={formatDate((plan?.issueDate as string) || null) || '-'}
              valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
            />
          </Col>
          <Col span={5}>
            <Statistic
              title="工单结束日期"
              value={formatDate((plan?.endDate as string) || null) || '-'}
              valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
            />
          </Col>
          <Col span={5}>
            <Statistic
              title="计划更新时间"
              value={formatDateTime((plan?.updateDate as string) || null) || '-'}
              valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="问题总数"
              value={archivedItem?.issue_stats?.total ?? 0}
              valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
            />
          </Col>
          <Col span={5}>
            <Statistic
              title="未关闭问题"
              value={archivedItem?.issue_stats?.unclosed ?? 0}
              valueStyle={{
                fontSize: 13,
                fontFamily: NUM_FONT,
                color: (archivedItem?.issue_stats?.unclosed ?? 0) > 0 ? '#F97316' : '#10B981',
              }}
            />
          </Col>
        </Row>
      </Card>

      {/* ============ 阶段审核记录弹窗 (只读) ============ */}
      <Modal
        open={reviewModalOpen}
        onCancel={() => setReviewModalOpen(false)}
        footer={null}
        width={1100}
        title={
          <Space>
            <InboxOutlined style={{ color: '#722ED1' }} />
            <span>{reviewPhase} 审核记录</span>
            {reviewData?.summary?.avg_percent != null && (
              <Tag
                style={{
                  backgroundColor: scoreFill(reviewData.summary.avg_score!),
                  color: '#000',
                  fontWeight: 700,
                  fontFamily: NUM_FONT,
                  margin: 0,
                }}
              >
                综合 {reviewData.summary.avg_percent}%
              </Tag>
            )}
          </Space>
        }
      >
        {reviewLoading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : reviewData ? (
          <>
            {/* 历史补录评分提示 (无逐项评审记录时回退展示) */}
            {reviewData.summary.scored_count === 0 && reviewData.historic_score != null && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message={`该阶段无逐项评审记录, 展示历史补录评分: ${(reviewData.historic_score * 100).toFixed(1)}%`}
              />
            )}
            {reviewData.summary.scored_count === 0 && reviewData.historic_score == null && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="该阶段无评审记录"
              />
            )}
            <div className="msia-archive-review-table">
              <Table<ArchivedReviewItem>
                columns={reviewColumns}
                dataSource={reviewData.items}
                rowKey="item_id"
                size="small"
                bordered
                scroll={{ x: 1150, y: 480 }}
                pagination={false}
                locale={{ emptyText: <Empty description="暂无检查项" /> }}
              />
            </div>
            <div style={{ marginTop: 8, textAlign: 'right' }}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                共 {reviewData.summary.item_count} 个检查项, 已评分 {reviewData.summary.scored_count} 项
              </Text>
            </div>
          </>
        ) : (
          <Empty description="暂无数据" />
        )}
      </Modal>

      {/* ============ 问题闭环情况 (只读, 本项目全部问题) ============ */}
      <Card
        size="small"
        style={{ marginTop: 16, borderTop: '3px solid #722ED1' }}
        title={
          <Space>
            <BugOutlined style={{ color: '#722ED1' }} />
            <Text strong>问题闭环情况</Text>
            <Tag style={{ fontSize: 11, margin: 0 }}>共 {issuesTotal} 项</Tag>
          </Space>
        }
        extra={
          <Tooltip title="点击行或操作列图标查看问题详情 (含关闭证据)">
            <Text type="secondary" style={{ fontSize: 11 }}>只读 · 点击行查看详情</Text>
          </Tooltip>
        }
      >
        <div className="msia-archive-issue-table">
          <Table<Issue>
            columns={issueColumns}
            dataSource={issues}
            rowKey="Id"
            size="small"
            loading={issuesLoading}
            scroll={{ x: 1150 }}
            pagination={issues.length > 10 ? { pageSize: 10, showSizeChanger: false, showTotal: (t) => `共 ${t} 项` } : false}
            locale={{ emptyText: <Empty description="本项目无问题记录" /> }}
            onRow={(record) => ({
              onClick: () => openIssueDetail(record),
              style: { cursor: 'pointer' },
            })}
          />
        </div>
      </Card>

      {/* ============ 问题详情抽屉 (只读) ============ */}
      <Drawer
        open={issueDrawerOpen}
        onClose={() => setIssueDrawerOpen(false)}
        width={760}
        title={
          <Space>
            <BugOutlined style={{ color: '#722ED1' }} />
            <span>问题详情 (只读)</span>
            {currentIssue?.IssueNo && (
              <Text code style={{ color: '#722ED1' }}>{currentIssue.IssueNo}</Text>
            )}
          </Space>
        }
      >
        {currentIssue ? (
          <>
            {/* 基本信息 */}
            <div style={{ fontSize: 13, fontWeight: 600, color: '#722ED1', margin: '4px 0 8px', paddingBottom: 6, borderBottom: '2px solid rgba(114, 46, 209, 0.15)' }}>
              <BugOutlined /> 问题基本信息
            </div>
            <Descriptions column={2} bordered size="small" styles={{ label: { width: 100, background: '#fafafa' } }}>
              <Descriptions.Item label="问题标题" span={2}>
                <Text strong>{currentIssue.Title}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={issueStatusMap[currentIssue.Status as string]?.color || 'default'} icon={issueStatusMap[currentIssue.Status as string]?.icon}>
                  {issueStatusMap[currentIssue.Status as string]?.text || currentIssue.Status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="MSIA 阶段">
                {currentIssue.PhaseCode ? (
                  <Tag color={phaseBadgeColor[currentIssue.PhaseCode] || 'default'}>{currentIssue.PhaseCode}</Tag>
                ) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="严重等级">
                <Tag color={issueSeverityMap[currentIssue.Severity as string]?.color || 'default'}>
                  {issueSeverityMap[currentIssue.Severity as string]?.text || currentIssue.Severity}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="优先级">
                <Tag color={issuePriorityMap[currentIssue.Priority as string]?.color || 'default'}>
                  {issuePriorityMap[currentIssue.Priority as string]?.text || currentIssue.Priority}
                </Tag>
              </Descriptions.Item>
              {currentIssue.ItemName && (
                <Descriptions.Item label="关联检查项" span={2}>
                  <Text style={{ fontSize: 12 }}>{currentIssue.ItemName}</Text>
                  {currentIssue.ItemNo && <Tag style={{ fontSize: 10, marginLeft: 6 }}>#{currentIssue.ItemNo}</Tag>}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="问题描述" span={2}>
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {currentIssue.Description || <Text type="secondary">无</Text>}
                </Paragraph>
              </Descriptions.Item>
              <Descriptions.Item label="责任人">{showText(currentIssue.OwnerName)}</Descriptions.Item>
              <Descriptions.Item label="所属公司">{showText(currentIssue.OwnerCompany)}</Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {currentIssue.CreatedAt ? (
                  <Text style={{ fontSize: 12, fontFamily: NUM_FONT }}>{formatDateTime(currentIssue.CreatedAt)}</Text>
                ) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="关闭时间">
                {currentIssue.ClosedAt ? (
                  <Text style={{ fontSize: 12, fontFamily: NUM_FONT, color: '#10B981' }}>{formatDateTime(currentIssue.ClosedAt)}</Text>
                ) : <Text type="secondary">未关闭</Text>}
              </Descriptions.Item>
            </Descriptions>

            {/* 闭环整改情况 */}
            <div style={{ fontSize: 13, fontWeight: 600, color: '#722ED1', margin: '16px 0 8px', paddingBottom: 6, borderBottom: '2px solid rgba(114, 46, 209, 0.15)' }}>
              <CheckCircleOutlined /> 闭环整改情况
            </div>
            <Descriptions column={2} bordered size="small" styles={{ label: { width: 100, background: '#fafafa' } }}>
              <Descriptions.Item label="整改完成日期">
                {currentIssue.Deadline ? formatDate(currentIssue.Deadline) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="计划关闭日期">
                {currentIssue.PlannedCloseDate ? formatDate(currentIssue.PlannedCloseDate) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="关闭申请时间">
                {currentIssue.ClosureRequestedAt ? formatDateTime(currentIssue.ClosureRequestedAt) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="验证时间">
                {currentIssue.VerifiedAt ? formatDateTime(currentIssue.VerifiedAt) : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="根本原因" span={2}>
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {currentIssue.RootCause || <Text type="secondary" italic>尚未填写</Text>}
                </Paragraph>
              </Descriptions.Item>
              <Descriptions.Item label="纠正措施" span={2}>
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {currentIssue.CorrectiveAction || <Text type="secondary" italic>尚未填写</Text>}
                </Paragraph>
              </Descriptions.Item>
              <Descriptions.Item label="验证意见" span={2}>
                <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {currentIssue.VerificationComments || <Text type="secondary">-</Text>}
                </Paragraph>
              </Descriptions.Item>
            </Descriptions>

            {/* 审核证据 (只读) */}
            <div style={{ fontSize: 13, fontWeight: 600, color: '#722ED1', margin: '16px 0 8px', paddingBottom: 6, borderBottom: '2px solid rgba(114, 46, 209, 0.15)' }}>
              <PaperClipOutlined /> 审核证据 ({evidence.length})
            </div>
            {renderAttachmentCards(evidence)}

            {/* 关闭证据 (只读) */}
            <div style={{ fontSize: 13, fontWeight: 600, color: '#722ED1', margin: '16px 0 8px', paddingBottom: 6, borderBottom: '2px solid rgba(114, 46, 209, 0.15)' }}>
              <CheckCircleOutlined /> 关闭证据 ({closureEvidence.length})
            </div>
            {renderAttachmentCards(closureEvidence)}
          </>
        ) : (
          <Skeleton active paragraph={{ rows: 8 }} />
        )}
      </Drawer>

      {/* ============ 阶段审核报告弹窗 (复用项目管理 Report MSIA 模板, 含导出 PDF) ============ */}
      <PhaseReportModal
        open={reportModalOpen}
        planId={id || ''}
        phaseCode={reportPhaseCode}
        combinedPhases={combinedReportPhases}
        onClose={() => setReportModalOpen(false)}
      />
    </div>
  );
}
