import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App,
  Card,
  Table,
  Tag,
  Space,
  Button,
  Input,
  Select,
  Typography,
  Drawer,
  Descriptions,
  Timeline,
  Empty,
  Tooltip,
  Statistic,
  Row,
  Col,
  Segmented,
  Image as AntImage,
  Upload,
  Modal,
  Popconfirm,
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  CommentOutlined,
  CheckCircleOutlined,
  BugOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  TeamOutlined,
  AlertOutlined,
  PaperClipOutlined,
  ArrowRightOutlined,
  FilePdfOutlined,
  DownloadOutlined,
  EyeOutlined,
  UploadOutlined,
  DeleteOutlined,
  LockOutlined,
  UnlockOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  Issue,
  IssueComment,
  IssueListParams,
  IssueFilterOptions,
  getIssues,
  getIssue,
  getIssueStats,
  getIssueFilterOptions,
  listIssueComments,
  listIssueEvidence,
  listIssueClosureEvidence,
  uploadIssueClosureEvidence,
  deleteIssueClosureEvidence,
  fetchAttachmentBlobUrl,
  reopenIssue,
  deleteIssue,
  IssueAttachment,
} from '@/api/issues';
import { useAuthStore } from '@/store/auth';
import { BRAND, techCardStyle } from '@/styles/shared';
import { formatDate, formatDateTime } from '@/utils/format';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text, Paragraph } = Typography;

// ============ 状态/优先级/严重等级映射 (与后端对齐) ============
const statusMap: Record<string, { color: string; text: string; icon?: React.ReactNode }> = {
  open: { color: 'default', text: '待处理', icon: <ClockCircleOutlined /> },
  in_progress: { color: 'processing', text: '处理中', icon: <BugOutlined /> },
  pending_verification: { color: 'warning', text: '待验证', icon: <ExclamationCircleOutlined /> },
  closed: { color: 'success', text: '已关闭', icon: <CheckCircleOutlined /> },
};

const priorityMap: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高' },
  medium: { color: 'blue', text: '中' },
  low: { color: 'default', text: '低' },
};

const severityMap: Record<string, { color: string; text: string }> = {
  H: { color: 'red', text: 'H 高' },
  M: { color: 'orange', text: 'M 中' },
  L: { color: 'default', text: 'L 低' },
};

// 评论动作映射
const actionMap: Record<string, { color: string; text: string }> = {
  create: { color: 'blue', text: '创建' },
  comment: { color: 'default', text: '评论' },
  status_change: { color: 'orange', text: '状态变更' },
  verify: { color: 'green', text: '验证' },
  update: { color: 'cyan', text: '更新' },
  assign: { color: 'purple', text: '分配' },
};

// MSIA 阶段选项
const phaseOptions = [
  { value: 'MSIA1', label: 'MSIA1 立项启动' },
  { value: 'MSIA2', label: 'MSIA2 需求分析' },
  { value: 'MSIA3', label: 'MSIA3 设计冻结' },
  { value: 'MSIA4', label: 'MSIA4 预验收' },
  { value: 'MSIA5', label: 'MSIA5 终验收' },
];

const phaseBadgeColor: Record<string, string> = {
  MSIA1: 'blue',
  MSIA2: 'cyan',
  MSIA3: 'geekblue',
  MSIA4: 'purple',
  MSIA5: 'magenta',
};

// 区块标题样式 (柔和科技商务风)
const sectionTitleStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: '#2E5CE6',
  margin: '16px 0 8px',
  paddingBottom: 6,
  borderBottom: '2px solid rgba(46, 92, 230, 0.12)',
  letterSpacing: 0.3,
  display: 'flex',
  alignItems: 'center',
  gap: 6,
};

// 安全获取文本 (null 返回 '-')
function showText(v: string | null | undefined): React.ReactNode {
  if (v === null || v === undefined || v === '') return <Text type="secondary">-</Text>;
  return v;
}

// 判断附件是否为图片
function isImageAttachment(att: IssueAttachment): boolean {
  return !!att.MimeType?.startsWith('image/') ||
    /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '');
}

// 判断附件是否为 PDF
function isPdfAttachment(att: IssueAttachment): boolean {
  return !!att.MimeType?.includes('pdf') ||
    /\.pdf$/i.test(att.FileName || '');
}

// 问题管理页 - 只读看板 (所有用户可查看与筛选)
export default function Issues() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);

  const [data, setData] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>();
  const [severityFilter, setSeverityFilter] = useState<string | undefined>();
  const [phaseFilter, setPhaseFilter] = useState<string | undefined>();
  const [planIdFilter, setPlanIdFilter] = useState<string | undefined>();
  const [ownerNameFilter, setOwnerNameFilter] = useState<string | undefined>();
  // 多选筛选: 项目 (PlanId 列表) + 责任人 (姓名列表) + MSIA 阶段 (代码列表)
  const [planIdFilters, setPlanIdFilters] = useState<string[]>([]);
  const [ownerNameFilters, setOwnerNameFilters] = useState<string[]>([]);
  const [phaseFilters, setPhaseFilters] = useState<string[]>([]);
  const [filterOptions, setFilterOptions] = useState<IssueFilterOptions>({
    projects: [],
    owners: [],
    project_owner_map: {},
  });
  const [stats, setStats] = useState<any>(null);

  // 详情抽屉 (只读)
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [currentIssue, setCurrentIssue] = useState<Issue | null>(null);
  const [comments, setComments] = useState<IssueComment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'info' | 'analysis' | 'history' | 'evidence' | 'closure'>('info');

  // 审核证据 (只读)
  const [evidence, setEvidence] = useState<IssueAttachment[]>([]);
  const [evidenceUrls, setEvidenceUrls] = useState<Record<number, string>>({});
  // 关闭证据 (可上传/删除)
  const [closureEvidence, setClosureEvidence] = useState<IssueAttachment[]>([]);
  const [closureEvidenceUrls, setClosureEvidenceUrls] = useState<Record<number, string>>({});
  const [closureUploading, setClosureUploading] = useState(false);
  // 待上传的关闭证据文件列表 (受控 Upload, 避免缓存残留)
  const [pendingClosureFiles, setPendingClosureFiles] = useState<File[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string>('');

  // 重开已关闭问题 (admin/lead_reviewer): 原因必填
  const [reopenTarget, setReopenTarget] = useState<Issue | null>(null);
  const [reopenReason, setReopenReason] = useState('');
  const [reopenLoading, setReopenLoading] = useState(false);

  // 加载统计
  const fetchStats = useCallback(async () => {
    try {
      const params: {
        plan_id?: string;
        plan_ids?: string;
        phase_code?: string;
        phase_codes?: string;
        owner_name?: string;
        owner_names?: string;
      } = {};
      // 多选优先, 回退到单选兼容
      if (planIdFilters.length > 0) {
        params.plan_ids = planIdFilters.join(",");
      } else if (planIdFilter) {
        params.plan_id = planIdFilter;
      }
      if (phaseFilters.length > 0) {
        params.phase_codes = phaseFilters.join(",");
      } else if (phaseFilter) {
        params.phase_code = phaseFilter;
      }
      if (ownerNameFilters.length > 0) {
        params.owner_names = ownerNameFilters.join(",");
      } else if (ownerNameFilter) {
        params.owner_name = ownerNameFilter;
      }
      const s = await getIssueStats(params);
      setStats(s);
    } catch {
      setStats(null);
    }
  }, [planIdFilter, planIdFilters, phaseFilter, phaseFilters, ownerNameFilter, ownerNameFilters]);

  // 加载问题列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: IssueListParams = { page, page_size: pageSize };
      if (statusFilter) params.status = statusFilter;
      if (priorityFilter) params.priority = priorityFilter;
      if (severityFilter) params.severity = severityFilter;
      // 阶段多选优先, 回退到单选兼容
      if (phaseFilters.length > 0) {
        params.phase_codes = phaseFilters.join(",");
      } else if (phaseFilter) {
        params.phase_code = phaseFilter;
      }
      // 多选优先, 回退到单选兼容
      if (planIdFilters.length > 0) {
        params.plan_ids = planIdFilters.join(",");
      } else if (planIdFilter) {
        params.plan_id = planIdFilter;
      }
      if (ownerNameFilters.length > 0) {
        params.owner_names = ownerNameFilters.join(",");
      } else if (ownerNameFilter) {
        params.owner_name = ownerNameFilter;
      }
      if (keyword) params.keyword = keyword;
      const res = await getIssues(params);
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch {
      // 错误已由拦截器提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, priorityFilter, severityFilter, phaseFilter, phaseFilters, planIdFilter, planIdFilters, ownerNameFilter, ownerNameFilters, keyword]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // 加载筛选选项 (项目 + 责任人 下拉)
  const fetchFilterOptions = useCallback(async () => {
    try {
      const opts = await getIssueFilterOptions();
      setFilterOptions(opts || { projects: [], owners: [] });
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    fetchFilterOptions();
  }, [fetchFilterOptions]);

  // 级联筛选选项 (useMemo 缓存, 避免每次渲染创建新数组导致 Select 抖动):
  // - 选了项目 → 责任人下拉仅显示这些项目下出现过的负责人
  // - 选了责任人 → 项目下拉仅显示与这些责任人关联的项目
  // - 已选值即使不在过滤后的 options 中, antd 仍以 tag 形式保留显示
  const cascadedOwnerOptions = useMemo(() => {
    const all = filterOptions.owners || [];
    const map = filterOptions.project_owner_map || {};
    if (planIdFilters.length === 0) return all;
    const allowed = new Set<string>();
    planIdFilters.forEach((pid) => {
      (map[pid] || []).forEach((o) => allowed.add(o));
    });
    return all.filter((o) => allowed.has(o.value));
  }, [filterOptions, planIdFilters]);

  const cascadedProjectOptions = useMemo(() => {
    const all = filterOptions.projects || [];
    const map = filterOptions.project_owner_map || {};
    if (ownerNameFilters.length === 0) return all;
    return all.filter((p) => {
      const owners = map[p.value] || [];
      return ownerNameFilters.some((o) => owners.includes(o));
    });
  }, [filterOptions, ownerNameFilters]);

  // 加载评论
  const fetchComments = async (issueId: number) => {
    setCommentsLoading(true);
    try {
      const list = await listIssueComments(issueId);
      setComments(list || []);
    } catch {
      setComments([]);
    } finally {
      setCommentsLoading(false);
    }
  };

  // 加载审核证据并为所有附件生成 Blob URL (图片可直接预览, 其他文件可查看/下载)
  const loadEvidence = useCallback(async (issue: Issue) => {
    let atts = issue.Evidence;
    if (!atts || atts.length === 0) {
      try {
        atts = await listIssueEvidence(issue.Id);
      } catch {
        atts = [];
      }
    }
    setEvidence(atts || []);
    // 为所有附件并行生成 Blob URL, 一次性替换 (避免累积导致内存泄漏)
    const entries = await Promise.all(
      (atts || []).map(async (att) => {
        try {
          const url = await fetchAttachmentBlobUrl(att.Id);
          return [att.Id, url] as const;
        } catch {
          return [att.Id, ''] as const;
        }
      }),
    );
    const urls: Record<number, string> = {};
    for (const [id, url] of entries) {
      if (url) urls[id] = url;
    }
    setEvidenceUrls(urls);
  }, []);

  // 加载关闭证据并为所有附件生成 Blob URL
  const loadClosureEvidence = useCallback(async (issue: Issue) => {
    let atts = issue.ClosureEvidence;
    if (!atts || atts.length === 0) {
      try {
        atts = await listIssueClosureEvidence(issue.Id);
      } catch {
        atts = [];
      }
    }
    setClosureEvidence(atts || []);
    const entries = await Promise.all(
      (atts || []).map(async (att) => {
        try {
          const url = await fetchAttachmentBlobUrl(att.Id);
          return [att.Id, url] as const;
        } catch {
          return [att.Id, ''] as const;
        }
      }),
    );
    const urls: Record<number, string> = {};
    for (const [id, url] of entries) {
      if (url) urls[id] = url;
    }
    setClosureEvidenceUrls(urls);
  }, []);

  // 上传关闭证据 (单张图片)
  const handleUploadClosureEvidence = async (file: File) => {
    if (!currentIssue) return;
    setClosureUploading(true);
    try {
      await uploadIssueClosureEvidence(currentIssue.Id, file);
      message.success(`已上传: ${file.name}`);
      // 刷新关闭证据列表
      const fresh = await getIssue(currentIssue.Id);
      setCurrentIssue(fresh);
      await loadClosureEvidence(fresh);
    } catch (e: any) {
      message.error(e?.message || '上传失败');
    } finally {
      setClosureUploading(false);
    }
  };

  const handlePasteClosureEvidence = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const items = event.clipboardData?.items;
    if (!items || !currentIssue || currentIssue.Status === 'closed') return;
    const files: File[] = [];
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length === 0) return;
    event.preventDefault();
    files.forEach((file) => handleUploadClosureEvidence(file));
  };

  // 删除关闭证据
  const handleDeleteClosureEvidence = async (attachmentId: number) => {
    if (!currentIssue) return;
    try {
      await deleteIssueClosureEvidence(currentIssue.Id, attachmentId);
      message.success('已删除');
      const fresh = await getIssue(currentIssue.Id);
      setCurrentIssue(fresh);
      await loadClosureEvidence(fresh);
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  // 打开详情抽屉 (只读)
  const openDetail = async (issue: Issue) => {
    setDrawerOpen(true);
    setCurrentIssue(issue);
    setComments([]);
    setActiveTab('info');
    setEvidence([]);
    setClosureEvidence([]);
    setClosureEvidenceUrls({});
    setPendingClosureFiles([]);
    try {
      const fresh = await getIssue(issue.Id);
      setCurrentIssue(fresh);
      loadEvidence(fresh);
      loadClosureEvidence(fresh);
    } catch {
      // 使用列表数据
      loadEvidence(issue);
      loadClosureEvidence(issue);
    }
    fetchComments(issue.Id);
  };

  // 重开已关闭问题 (清零评分管控字段, 重新走整改闭环)
  const handleReopen = async () => {
    if (!reopenTarget) return;
    if (!reopenReason.trim()) {
      message.warning('请填写重开原因');
      return;
    }
    setReopenLoading(true);
    try {
      const updated = await reopenIssue(reopenTarget.Id, reopenReason.trim());
      message.success(`问题已重开: ${updated.IssueNo}`);
      setReopenTarget(null);
      setReopenReason('');
      fetchData();
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '重开失败');
    } finally {
      setReopenLoading(false);
    }
  };

  // 删除问题 (软删: 管理员可删除任意问题, 其他用户仅能删除自己登记的)
  const handleDeleteIssue = async (record: Issue) => {
    try {
      await deleteIssue(record.Id);
      message.success(`问题已删除: ${record.IssueNo}`);
      fetchData();
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  // 表格列定义 - 只读展示问题闭环关键信息
  const columns: ColumnsType<Issue> = [
    {
      title: 'Issue No',
      dataIndex: 'IssueNo',
      key: 'IssueNo',
      width: 160,
      fixed: 'left',
      render: (v: string) => (
        <Text code style={{ fontSize: 12, color: '#2E5CE6' }}>{v}</Text>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'ProjectName',
      key: 'ProjectName',
      width: 170,
      ellipsis: true,
      render: (v: string | null | undefined, record) => {
        const name = v || '';
        if (!name && !record.PlanId) return <Text type="secondary">-</Text>;
        return (
          <Tooltip title={name || `PlanID: ${record.PlanId}`}>
            <Text style={{ fontSize: 12 }}>{name || `PlanID: ${record.PlanId}`}</Text>
          </Tooltip>
        );
      },
    },
    {
      title: 'MSIA阶段',
      dataIndex: 'PhaseCode',
      key: 'PhaseCode',
      width: 100,
      filters: phaseOptions.map((p) => ({ text: p.label, value: p.value })),
      onFilter: (value, record) => record.PhaseCode === value,
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
            <Text style={{ fontSize: 13 }}>{v}</Text>
            {record.ItemNo && (
              <Tag style={{ fontSize: 10, margin: 0 }}>#{record.ItemNo}</Tag>
            )}
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'Status',
      key: 'Status',
      width: 110,
      filters: Object.entries(statusMap).map(([value, { text }]) => ({ text, value })),
      onFilter: (value, record) => record.Status === value,
      render: (v: string) => (
        <Tag color={statusMap[v]?.color || 'default'} style={{ fontSize: 11 }}>
          {statusMap[v]?.text || v}
        </Tag>
      ),
    },
    {
      title: '严重',
      dataIndex: 'Severity',
      key: 'Severity',
      width: 80,
      filters: Object.entries(severityMap).map(([value, { text }]) => ({ text, value })),
      onFilter: (value, record) => record.Severity === value,
      render: (v: string) => (
        <Tag color={severityMap[v]?.color || 'default'} style={{ fontSize: 11 }}>
          {severityMap[v]?.text || v}
        </Tag>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'Priority',
      key: 'Priority',
      width: 80,
      filters: Object.entries(priorityMap).map(([value, { text }]) => ({ text, value })),
      onFilter: (value, record) => record.Priority === value,
      render: (v: string) => (
        <Tag color={priorityMap[v]?.color || 'default'} style={{ fontSize: 11 }}>
          {priorityMap[v]?.text || v}
        </Tag>
      ),
    },
    {
      title: '责任人',
      dataIndex: 'OwnerName',
      key: 'OwnerName',
      width: 130,
      render: (v: string | null, record: Issue) => {
        if (!v && !record.OwnerUserName) return <Text type="secondary">-</Text>;
        return (
          <Tooltip title={record.OwnerUserName ? `账号: ${record.OwnerUserName}` : undefined}>
            <Space size={4}>
              <TeamOutlined style={{ color: '#2E5CE6', fontSize: 11 }} />
              <div>
                <Text style={{ fontSize: 12 }}>{v || '-'}</Text>
                {record.OwnerUserName && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 10, fontFamily: NUM_FONT }}>
                      {record.OwnerUserName}
                    </Text>
                  </div>
                )}
              </div>
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '所属公司',
      dataIndex: 'OwnerCompany',
      key: 'OwnerCompany',
      width: 130,
      render: (v: string | null) => v ? (
        <Tag style={{ fontSize: 11, background: 'rgba(22, 119, 255, 0.06)' }}>{v}</Tag>
      ) : <Text type="secondary">-</Text>,
    },
    {
      title: '评分管控',
      key: 'ScoreControl',
      width: 180,
      render: (_, record) => {
        // 仅已关闭问题参与评分管控
        if (record.Status !== 'closed') return <Text type="secondary" style={{ fontSize: 11 }}>-</Text>;
        const before = record.ScoreAtClosure;
        const after = record.ScoreAfterUpdate;
        const fmt = (s?: number | null) => (s === null || s === undefined ? '-' : `${Math.round(s * 100)}%`);
        if (after === null || after === undefined) {
          // 已关闭但整改后评分未回写 → 待更新
          return (
            <Tooltip title="问题已关闭, 请评审员对该检查项重新评分以完成整改后评分回写">
              <Space size={4}>
                <Text style={{ fontSize: 12, color: '#EF4444' }}>{fmt(before)}</Text>
                <Text type="secondary" style={{ fontSize: 11 }}>→</Text>
                <Tag color="orange" style={{ fontSize: 10, margin: 0 }}>待更新</Tag>
              </Space>
            </Tooltip>
          );
        }
        const improved = (before ?? 0) < after;
        const same = before === after;
        return (
          <Tooltip title={record.ScoreUpdatedAt ? `评分更新于 ${record.ScoreUpdatedAt.replace('T', ' ').slice(0, 16)}` : undefined}>
            <Space size={4}>
              <Text type="secondary" style={{ fontSize: 12 }}>{fmt(before)}</Text>
              <Text type="secondary" style={{ fontSize: 11 }}>→</Text>
              <Text strong style={{ fontSize: 12, color: same ? '#8c8c8c' : improved ? '#10B981' : '#EF4444' }}>
                {fmt(after)}
              </Text>
            </Space>
          </Tooltip>
        );
      },
    },
    {
      title: '计划关闭',
      dataIndex: 'PlannedCloseDate',
      key: 'PlannedCloseDate',
      width: 120,
      render: (v: string | null, record) => {
        if (!v) return <Text type="secondary">-</Text>;
        return <Text style={{ fontSize: 12 }}>{formatDate(v)}</Text>;
      },
    },
    {
      title: '整改完成日期',
      dataIndex: 'Deadline',
      key: 'Deadline',
      width: 130,
      render: (v: string | null, record) => {
        if (!v) return <Tooltip title="阶段评审未完成, 暂不参与逾期判定"><Text type="secondary">-</Text></Tooltip>;
        const due = dayjs(v);
        const overdue = due.isBefore(dayjs(), 'day')
          && record.Status !== 'closed'
          && record.Status !== 'pending_verification';
        return (
          <Tooltip title={overdue ? '已超过整改完成日期' : record.DeadlineIsManual ? '人工维护' : '阶段评审日期+10天'}>
            <Text type={overdue ? 'danger' : undefined} style={{ fontSize: 12 }}>
              {formatDate(v)}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'CreatedAt',
      key: 'CreatedAt',
      width: 140,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{formatDate(v)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 210,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          <Button type="link" size="small" onClick={() => openDetail(record)}>
            查看
          </Button>
          {/* 已关闭问题 + 管理员/主审核员: 提供重开入口 (清零评分管控字段, 重新走整改闭环) */}
          {record.Status === 'closed' && (user?.Role === 'admin' || user?.Role === 'lead_reviewer') && (
            <Button
              type="link"
              size="small"
              icon={<UnlockOutlined />}
              style={{ color: '#fa8c16' }}
              onClick={() => {
                setReopenTarget(record);
                setReopenReason('');
              }}
            >
              重开
            </Button>
          )}
          {/* 仅当当前用户是责任人时, 提供前往我的面板维护的快捷入口 */}
          {((record.OwnerUserId && record.OwnerUserId === user?.Id) ||
            (record.OwnerUserName && record.OwnerUserName === user?.Username)) && (
            <Button
              type="link"
              size="small"
              icon={<ArrowRightOutlined />}
              onClick={() => navigate('/workbench')}
            >
              去维护
            </Button>
          )}
          {/* 管理员: 删除任意问题 (软删, 含测试数据清理); 普通用户仅能删除自己登记的问题 */}
          {(user?.Role === 'admin' || record.CreatedBy === user?.Id) && (
            <Popconfirm
              title="删除问题"
              description={
                <span style={{ fontSize: 12 }}>
                  确认删除 {record.IssueNo} ?<br />
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    软删除, 问题将从列表移除并停止升级提醒
                  </Text>
                </span>
              }
              okText="删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={() => handleDeleteIssue(record)}
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ============ 渲染统计卡 ============
  const renderStatsCards = () => {
    if (!stats) return null;
    const closedRate = stats.total > 0 ? Math.round((stats.closed_count / stats.total) * 100) : 0;
    return (
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.primary}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>问题总数</span>}
              value={stats.total}
              prefix={<BugOutlined style={{ color: BRAND.primary }} />}
              valueStyle={{ fontSize: 22, color: BRAND.primary }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.gray}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>待处理</span>}
              value={stats.open_count}
              prefix={<ClockCircleOutlined style={{ color: BRAND.gray }} />}
              valueStyle={{ fontSize: 22, color: '#595959' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.primary}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>处理中</span>}
              value={stats.in_progress_count}
              prefix={<BugOutlined style={{ color: BRAND.primary }} />}
              valueStyle={{ fontSize: 22, color: BRAND.primary }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.warning}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>待验证</span>}
              value={stats.pending_verification_count}
              prefix={<ExclamationCircleOutlined style={{ color: BRAND.warning }} />}
              valueStyle={{ fontSize: 22, color: BRAND.warning }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.success}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>已关闭 ({closedRate}%)</span>}
              value={stats.closed_count}
              prefix={<CheckCircleOutlined style={{ color: BRAND.success }} />}
              valueStyle={{ fontSize: 22, color: BRAND.success }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.danger}` }}>
            <Statistic
              title={<span style={{ fontSize: 12 }}>逾期 / 高优</span>}
              value={stats.overdue_count}
              suffix={<span style={{ fontSize: 11, color: BRAND.danger }}>/ {stats.high_priority_count}</span>}
              prefix={<AlertOutlined style={{ color: BRAND.danger }} />}
              valueStyle={{ fontSize: 22, color: BRAND.danger }}
            />
          </Card>
        </Col>
      </Row>
    );
  };

  // ============ 渲染基本信息段 ============
  const renderInfoSection = () => {
    if (!currentIssue) return null;
    return (
      <>
        <div style={sectionTitleStyle}>
          <BugOutlined />
          问题识别 (D2 - Problem Description)
        </div>
        <Descriptions column={2} bordered size="small" styles={{ label: { width: 110, background: '#fafafa' } }}>
          <Descriptions.Item label="Issue No" span={2}>
            <Text code style={{ color: '#2E5CE6' }}>{currentIssue.IssueNo}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="问题标题" span={2}>
            <Text strong>{currentIssue.Title}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusMap[currentIssue.Status as string]?.color || 'default'}>
              {statusMap[currentIssue.Status as string]?.text || currentIssue.Status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="优先级">
            <Tag color={priorityMap[currentIssue.Priority as string]?.color || 'default'}>
              {priorityMap[currentIssue.Priority as string]?.text || currentIssue.Priority}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="严重等级">
            <Tag color={severityMap[currentIssue.Severity as string]?.color || 'default'}>
              {severityMap[currentIssue.Severity as string]?.text || currentIssue.Severity}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="MSIA 阶段">
            {currentIssue.PhaseCode ? (
              <Tag color={phaseBadgeColor[currentIssue.PhaseCode] || 'default'}>
                {currentIssue.PhaseCode}
              </Tag>
            ) : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          {currentIssue.ItemNo && (
            <Descriptions.Item label="检查项编号" span={2}>
              <Text code>{currentIssue.ItemNo}</Text>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="问题描述" span={2}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {currentIssue.Description || <Text type="secondary">无</Text>}
            </Paragraph>
          </Descriptions.Item>
        </Descriptions>

        <div style={sectionTitleStyle}>
          <TeamOutlined />
          责任分配 (D1 - Team & Ownership)
        </div>
        <Descriptions column={2} bordered size="small" styles={{ label: { width: 110, background: '#fafafa' } }}>
          <Descriptions.Item label="责任人">
            {showText(currentIssue.OwnerName)}
          </Descriptions.Item>
          <Descriptions.Item label="责任人账号">
            {currentIssue.OwnerUserName ? (
              <Text code style={{ fontSize: 11 }}>{currentIssue.OwnerUserName}</Text>
            ) : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="所属公司">
            {currentIssue.OwnerCompany ? (
              <Tag color="blue">{currentIssue.OwnerCompany}</Tag>
            ) : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="登记人 ID">
            {currentIssue.CreatedBy ? <Text code>{currentIssue.CreatedBy}</Text> : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatDateTime(currentIssue.CreatedAt) || <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {formatDateTime(currentIssue.UpdatedAt) || <Text type="secondary">-</Text>}
          </Descriptions.Item>
        </Descriptions>

        {/* 若当前用户为责任人, 在基本信息末尾提供前往我的面板维护的快捷入口 */}
        {((currentIssue.OwnerUserId && currentIssue.OwnerUserId === user?.Id) ||
          (currentIssue.OwnerUserName && currentIssue.OwnerUserName === user?.Username)) &&
          currentIssue.Status !== 'closed' && (
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <Button
              type="primary"
              icon={<ArrowRightOutlined />}
              onClick={() => navigate('/workbench')}
            >
              前往我的面板维护此问题
            </Button>
          </div>
        )}
      </>
    );
  };

  // ============ 渲染分析段 (8D D4-D6) - 只读 ============
  const renderAnalysisSection = () => {
    if (!currentIssue) return null;
    return (
      <>
        <div style={sectionTitleStyle}>
          <SearchOutlined />
          根本原因分析 (D4 - Root Cause)
        </div>
        <Card size="small" style={{ background: '#fafafa', marginBottom: 12 }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
            {currentIssue.RootCause ? (
              currentIssue.RootCause
            ) : (
              <Text type="secondary" italic>尚未填写根本原因分析</Text>
            )}
          </Paragraph>
        </Card>

        <div style={sectionTitleStyle}>
          <CheckCircleOutlined />
          纠正措施 (D5-D6 - Corrective Action)
        </div>
        <Card size="small" style={{ background: '#fafafa', marginBottom: 12 }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
            {currentIssue.CorrectiveAction ? (
              currentIssue.CorrectiveAction
            ) : (
              <Text type="secondary" italic>尚未填写纠正措施</Text>
            )}
          </Paragraph>
        </Card>

        <div style={sectionTitleStyle}>
          <ClockCircleOutlined />
          时间节点 & 验证 (D7-D8 - Timeline & Closure)
        </div>
        <Descriptions column={2} bordered size="small" styles={{ label: { width: 110, background: '#fafafa' } }}>
          <Descriptions.Item label="整改完成日期">
            {currentIssue.Deadline
              ? formatDate(currentIssue.Deadline)
              : <Tooltip title="阶段评审未完成, 暂不参与逾期判定"><Text type="secondary">-</Text></Tooltip>}
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
          <Descriptions.Item label="关闭时间">
            {currentIssue.ClosedAt ? formatDateTime(currentIssue.ClosedAt) : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="验证人 ID">
            {currentIssue.VerifiedBy ? <Text code>{currentIssue.VerifiedBy}</Text> : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="闭环状态" span={2}>
            {currentIssue.ClosingStatus ? (
              <Tag color="green">{currentIssue.ClosingStatus}</Tag>
            ) : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="验证意见" span={2}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {currentIssue.VerificationComments || <Text type="secondary">-</Text>}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
              {currentIssue.Remarks || <Text type="secondary">-</Text>}
            </Paragraph>
          </Descriptions.Item>
        </Descriptions>
      </>
    );
  };

  // ============ 渲染审核证据段 ============
  const renderEvidenceSection = () => {
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
      transition: 'border-color 0.2s, box-shadow 0.2s',
      padding: 4,
    };
    return (
      <div>
        <div style={sectionTitleStyle}>
          <PaperClipOutlined />
          审核证据 ({evidence.length})
          <Tooltip title="由审核员登记问题时上传, 不可编辑">
            <Tag color="default" icon={<LockOutlined />} style={{ marginLeft: 8, fontSize: 11 }}>
              只读
            </Tag>
          </Tooltip>
        </div>
        {evidence.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无审核证据"
            style={{ margin: '12px 0' }}
          />
        ) : (
          <Space size="small" wrap>
            {evidence.map((att) => {
              const isImg = isImageAttachment(att);
              const isPdf = isPdfAttachment(att);
              const url = evidenceUrls[att.Id];

              // 图片: 缩略图 + 点击预览
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

              // 非图片但有 URL: PDF 在新窗口查看, 其他文件下载
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
                        <PaperClipOutlined style={{ fontSize: 36, color: '#2E5CE6' }} />
                      )}
                      <Text style={{ fontSize: 10, textAlign: 'center' }} ellipsis>
                        {att.FileName}
                      </Text>
                      <Space size={2}>
                        {isPdf ? (
                          <EyeOutlined style={{ fontSize: 10, color: '#2E5CE6' }} />
                        ) : (
                          <DownloadOutlined style={{ fontSize: 10, color: '#2E5CE6' }} />
                        )}
                        <Text style={{ fontSize: 9, color: '#2E5CE6' }}>
                          {isPdf ? '查看' : '下载'}
                        </Text>
                      </Space>
                    </div>
                  </Tooltip>
                );
              }

              // 无 URL (加载中或失败): 灰色占位卡片
              return (
                <div key={att.Id} style={{ ...cardStyle, cursor: 'default', borderStyle: 'dashed' }}>
                  <PaperClipOutlined style={{ fontSize: 36, color: '#bfbfbf' }} />
                  <Text type="secondary" style={{ fontSize: 10, textAlign: 'center' }} ellipsis>
                    {att.FileName}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 9 }}>加载中...</Text>
                </div>
              );
            })}
          </Space>
        )}
      </div>
    );
  };

  // ============ 渲染关闭证据段 (责任人可上传/删除) ============
  const renderClosureEvidenceSection = () => {
    if (!currentIssue) return null;
    // 权限: admin 或责任人本人可上传关闭证据
    const isOwner =
      (currentIssue.OwnerUserId && currentIssue.OwnerUserId === user?.Id) ||
      (currentIssue.OwnerUserName && currentIssue.OwnerUserName === user?.Username);
    const canUpload = user?.Role === 'admin' || isOwner;
    // 问题已关闭后, 不允许再上传/删除 (避免破坏关闭后状态)
    const isClosed = currentIssue.Status === 'closed';
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
      transition: 'border-color 0.2s, box-shadow 0.2s',
      padding: 4,
      position: 'relative',
    };
    return (
      <div>
        <div style={sectionTitleStyle}>
          <CheckCircleOutlined />
          关闭证据 ({closureEvidence.length})
          {canUpload && !isClosed && (
            <Tooltip title="被审核人申请关闭问题时上传, 支持多张图片">
              <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>可上传</Tag>
            </Tooltip>
          )}
          {isClosed && (
            <Tag color="default" icon={<LockOutlined />} style={{ marginLeft: 8, fontSize: 11 }}>
              问题已关闭
            </Tag>
          )}
        </div>

        {/* 已上传的关闭证据列表 */}
        {closureEvidence.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无关闭证据"
            style={{ margin: '12px 0' }}
          />
        ) : (
          <Space size="small" wrap style={{ marginBottom: 12 }}>
            {closureEvidence.map((att) => {
              const isImg = isImageAttachment(att);
              const isPdf = isPdfAttachment(att);
              const url = closureEvidenceUrls[att.Id];

              // 图片: 缩略图 + 点击预览
              if (isImg && url) {
                return (
                  <div key={att.Id} style={{ display: 'inline-block', textAlign: 'center', position: 'relative' }}>
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
                    {canUpload && !isClosed && (
                      <Tooltip title="删除此关闭证据">
                        <Button
                          type="primary"
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          shape="circle"
                          style={{ position: 'absolute', top: -6, right: -6, width: 20, height: 20, minWidth: 20, padding: 0 }}
                          onClick={() => handleDeleteClosureEvidence(att.Id)}
                        />
                      </Tooltip>
                    )}
                  </div>
                );
              }

              // 非图片但有 URL: PDF 在新窗口查看, 其他文件下载
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
                        <DownloadOutlined style={{ fontSize: 36, color: '#1677ff' }} />
                      )}
                      <div style={{ fontSize: 10, color: '#666', maxWidth: 100, textAlign: 'center', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {att.FileName}
                      </div>
                      {canUpload && !isClosed && (
                        <Button
                          type="primary"
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          shape="circle"
                          style={{ position: 'absolute', top: -6, right: -6, width: 20, height: 20, minWidth: 20, padding: 0 }}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteClosureEvidence(att.Id);
                          }}
                        />
                      )}
                    </div>
                  </Tooltip>
                );
              }

              // 无 URL: 显示加载失败
              return (
                <div key={att.Id} style={cardStyle}>
                  <PaperClipOutlined style={{ fontSize: 36, color: '#999' }} />
                  <div style={{ fontSize: 10, color: '#999' }}>{att.FileName}</div>
                </div>
              );
            })}
          </Space>
        )}

        {/* 上传区域 (仅责任人/admin 且问题未关闭时显示) */}
        {canUpload && !isClosed && (
          <div
            style={{ marginTop: 12 }}
            tabIndex={0}
            onPaste={handlePasteClosureEvidence}
          >
            <Upload
              listType="picture-card"
              multiple
              fileList={pendingClosureFiles.map((f) => ({
                uid: `${f.name}-${f.size}`,
                name: f.name,
                status: 'done' as const,
                originFileObj: f,
              })) as never}
              beforeUpload={(file) => {
                // 直接上传, 不缓存到本地 state
                handleUploadClosureEvidence(file);
                return false;
              }}
              accept="image/*"
              disabled={closureUploading}
            >
              <div>
                <UploadOutlined />
                <div style={{ marginTop: 4, fontSize: 11 }}>
                  {closureUploading ? '上传中...' : '添加关闭证据图片'}
                </div>
              </div>
            </Upload>
            <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
              支持上传多张图片作为问题关闭的证据 (供管理员/Lead 审核员审批关闭申请时参考)
            </div>
          </div>
        )}

        {!canUpload && (
          <div style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
            <LockOutlined /> 仅问题责任人或管理员可上传关闭证据
          </div>
        )}
      </div>
    );
  };

  // ============ 渲染处理历史 - 只读 ============
  const renderHistorySection = () => {
    if (!currentIssue) return null;
    return (
      <div>
        <div style={sectionTitleStyle}>
          <CommentOutlined />
          处理历史 ({comments.length})
        </div>
        {commentsLoading ? (
          <Text type="secondary">加载中...</Text>
        ) : comments.length === 0 ? (
          <Empty description="暂无处理记录" />
        ) : (
          <Timeline
            items={comments.map((c) => ({
              color: actionMap[c.Action]?.color || 'gray',
              children: (
                <div key={c.Id}>
                  <Space>
                    <Text strong>{c.AuthorName || '系统'}</Text>
                    <Tag color={actionMap[c.Action]?.color || 'default'}>
                      {actionMap[c.Action]?.text || c.Action}
                    </Tag>
                    {c.FromStatus && c.ToStatus && (
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {statusMap[c.FromStatus]?.text || c.FromStatus}
                        {' → '}
                        {statusMap[c.ToStatus]?.text || c.ToStatus}
                      </Text>
                    )}
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {formatDateTime(c.CreatedAt)}
                    </Text>
                  </Space>
                  <Paragraph style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>
                    {c.Content}
                  </Paragraph>
                </div>
              ),
            }))}
          />
        )}
      </div>
    );
  };

  return (
    <div>
      {/* ============ 顶部统计卡 ============ */}
      {renderStatsCards()}

      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>问题管理</Title>
            <Tag color="blue">{total}</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              · 只读看板 (所有用户可查看与筛选)
            </Text>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => { fetchData(); fetchStats(); fetchFilterOptions(); }}>
            刷新
          </Button>
        }
      >
        {/* ============ 筛选栏 ============ */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="搜索标题关键字"
            prefix={<SearchOutlined />}
            allowClear
            style={{ width: 220 }}
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value);
              setPage(1);
            }}
          />
          <Select
            placeholder="MSIA 阶段 (可多选)"
            allowClear
            mode="multiple"
            maxTagCount={2}
            value={phaseFilters}
            onChange={(v) => { setPhaseFilters(v); setPage(1); }}
            style={{ width: 200 }}
            options={phaseOptions}
            optionFilterProp="label"
            notFoundContent="暂无阶段"
          />
          <Select
            placeholder="项目 (可多选)"
            allowClear
            showSearch
            mode="multiple"
            maxTagCount={2}
            value={planIdFilters}
            onChange={(v) => { setPlanIdFilters(v); setPage(1); }}
            style={{ width: 260 }}
            options={cascadedProjectOptions}
            optionFilterProp="label"
            notFoundContent="暂无项目"
          />
          <Select
            placeholder="责任人 (可多选)"
            allowClear
            showSearch
            mode="multiple"
            maxTagCount={2}
            value={ownerNameFilters}
            onChange={(v) => { setOwnerNameFilters(v); setPage(1); }}
            style={{ width: 180 }}
            options={cascadedOwnerOptions}
            optionFilterProp="label"
            notFoundContent={planIdFilters.length > 0 ? '该项目暂无责任人' : '暂无责任人'}
          />
          <Select
            placeholder="状态"
            allowClear
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            style={{ width: 120 }}
            options={[
              ...Object.entries(statusMap).map(([value, { text }]) => ({ value, label: text })),
              { value: 'overdue', label: '逾期' },
            ]}
          />
          <Select
            placeholder="优先级"
            allowClear
            value={priorityFilter}
            onChange={(v) => { setPriorityFilter(v); setPage(1); }}
            style={{ width: 100 }}
            options={Object.entries(priorityMap).map(([value, { text }]) => ({ value, label: text }))}
          />
          <Select
            placeholder="严重等级"
            allowClear
            value={severityFilter}
            onChange={(v) => { setSeverityFilter(v); setPage(1); }}
            style={{ width: 110 }}
            options={Object.entries(severityMap).map(([value, { text }]) => ({ value, label: text }))}
          />
        </Space>

        <Table<Issue>
          rowKey="Id"
          columns={columns}
          dataSource={data}
          loading={loading}
          scroll={{ x: 1700 }}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          onRow={(record) => ({
            onClick: () => openDetail(record),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>

      {/* ============ 详情抽屉 (只读视图) ============ */}
      <Drawer
        title={
          currentIssue ? (
            <Space>
              <Text code style={{ color: '#2E5CE6' }}>{currentIssue.IssueNo}</Text>
              <Text strong style={{ fontSize: 14 }}>{currentIssue.Title}</Text>
            </Space>
          ) : '问题详情'
        }
        placement="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={820}
      >
        {currentIssue && (
          <>
            {/* Tab 切换: 基本信息 / 闭环分析 / 审核证据 / 关闭证据 / 处理历史 */}
            <Segmented
              block
              value={activeTab}
              onChange={(v) => setActiveTab(v as 'info' | 'analysis' | 'history' | 'evidence' | 'closure')}
              options={[
                { value: 'info', label: '基本信息' },
                { value: 'analysis', label: '闭环分析 (8D)' },
                { value: 'evidence', label: `审核证据 (${evidence.length})` },
                { value: 'closure', label: `关闭证据 (${closureEvidence.length})` },
                { value: 'history', label: '处理历史' },
              ]}
              style={{ marginBottom: 16 }}
            />

            {activeTab === 'info' && renderInfoSection()}
            {activeTab === 'analysis' && renderAnalysisSection()}
            {activeTab === 'evidence' && renderEvidenceSection()}
            {activeTab === 'closure' && renderClosureEvidenceSection()}
            {activeTab === 'history' && renderHistorySection()}
          </>
        )}
      </Drawer>

      {/* ============ 重开已关闭问题弹窗 (admin/lead_reviewer) ============ */}
      <Modal
        title={
          <Space>
            <UnlockOutlined style={{ color: '#fa8c16' }} />
            <span>重开问题</span>
            {reopenTarget && <Text code style={{ color: '#2E5CE6' }}>{reopenTarget.IssueNo}</Text>}
          </Space>
        }
        open={!!reopenTarget}
        onCancel={() => {
          setReopenTarget(null);
          setReopenReason('');
        }}
        onOk={handleReopen}
        confirmLoading={reopenLoading}
        okText="确认重开"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        destroyOnHidden
        width={520}
      >
        {reopenTarget && (
          <>
            <Paragraph style={{ marginBottom: 8 }}>
              <Text strong>{reopenTarget.Title}</Text>
            </Paragraph>
            <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
              重开后问题将回到「处理中」状态, 整改前评分 / 整改后评分 / 评分更新时间将全部清零,
              需重新走「整改 → 申请关闭 → 审批 → 评分更新」完整闭环。责任人将收到通知。
            </Paragraph>
            <Input.TextArea
              rows={4}
              maxLength={2000}
              showCount
              placeholder="请填写重开原因 (必填, 将记入处理历史并通知责任人)"
              value={reopenReason}
              onChange={(e) => setReopenReason(e.target.value)}
            />
          </>
        )}
      </Modal>
    </div>
  );
}
