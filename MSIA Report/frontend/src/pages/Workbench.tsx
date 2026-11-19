import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App,
  Card,
  Table,
  Tag,
  Space,
  Button,
  Typography,
  Tooltip,
  Empty,
  Skeleton,
  Modal,
  Form,
  Input,
  DatePicker,
  Select,
  Row,
  Col,
  Statistic,
  Tabs,
  Drawer,
  Timeline,
  Popconfirm,
  Progress,
  Badge,
  Image as AntImage,
  Upload,
} from 'antd';
import {
  ProjectOutlined,
  BugOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  EyeOutlined,
  EditOutlined,
  SendOutlined,
  CheckOutlined,
  CloseOutlined,
  AuditOutlined,
  DashboardOutlined,
  WarningOutlined,
  SafetyCertificateOutlined,
  ArrowRightOutlined,
  FileSearchOutlined,
  ExclamationCircleOutlined,
  PaperClipOutlined,
  UploadOutlined,
  DeleteOutlined,
  LockOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  getMyProjectsApi,
  getMyIssuesApi,
  getMyIssueFiltersApi,
  getPendingClosuresApi,
  workbenchUpdateIssueApi,
  requestClosureApi,
  approveClosureApi,
  type MyProjectItem,
  type MyIssueFilters,
  type PhaseSummary,
  type WorkbenchUpdatePayload,
} from '@/api/workbench';
import type { Issue, IssueStatus, IssuePriority, IssueAttachment } from '@/api/issues';
import {
  listIssueEvidence,
  listIssueClosureEvidence,
  fetchAttachmentBlobUrl,
  uploadIssueEvidence,
  uploadIssueClosureEvidence,
  deleteIssueClosureEvidence,
  deleteAttachment,
} from '@/api/issues';
import { useAuthStore } from '@/store/auth';
import { formatDateTime, formatDate } from '@/utils/format';
import { BRAND, techCardStyle, industrialBgStyle, CornerMarker } from '@/styles/shared';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

// 阶段元数据
const PHASE_META: Record<string, { label: string; color: string; desc: string }> = {
  MSIA1: { label: '立项启动', color: BRAND.gray, desc: 'Project Kick-off' },
  MSIA2: { label: '需求分析', color: BRAND.primary, desc: 'Planning & Design' },
  MSIA3: { label: '设计冻结', color: BRAND.cyan, desc: 'Design Freeze' },
  MSIA4: { label: '预验收', color: BRAND.orange, desc: 'Pre-Acceptance' },
  MSIA5: { label: '终验收', color: BRAND.success, desc: 'Final Acceptance' },
};

// 状态映射
const statusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  open: { color: 'default', text: '待处理', icon: <ClockCircleOutlined /> },
  in_progress: { color: 'processing', text: '处理中', icon: <EditOutlined /> },
  pending_verification: { color: 'warning', text: '待审批', icon: <AuditOutlined /> },
  closed: { color: 'success', text: '已关闭', icon: <CheckCircleOutlined /> },
};

// 优先级映射
const priorityMap: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高' },
  medium: { color: 'orange', text: '中' },
  low: { color: 'blue', text: '低' },
};

// 严重等级映射
const severityMap: Record<string, { color: string }> = {
  H: { color: 'red' },
  M: { color: 'orange' },
  L: { color: 'blue' },
};

export default function Workbench() {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdminOrLead = user?.Role === 'admin' || user?.Role === 'lead_reviewer';
  const isReviewee = user?.Role === 'reviewee';

  // 数据状态
  const [projects, setProjects] = useState<MyProjectItem[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issuesTotal, setIssuesTotal] = useState(0);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [pendingClosures, setPendingClosures] = useState<Issue[]>([]);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [pendingLoading, setPendingLoading] = useState(false);

  // 筛选
  const [projectKeyword, setProjectKeyword] = useState('');
  const [issuePlanFilter, setIssuePlanFilter] = useState<string | undefined>();
  const [issuePhaseFilter, setIssuePhaseFilter] = useState<string | undefined>();
  const [issueStatusFilter, setIssueStatusFilter] = useState<string | undefined>();
  const [issueKeyword, setIssueKeyword] = useState('');
  const [issueProjectFilters, setIssueProjectFilters] = useState<MyIssueFilters>({ projects: [] });
  const [issuePage, setIssuePage] = useState(1);
  const [pendingPhaseFilter, setPendingPhaseFilter] = useState<string | undefined>();
  const [pendingPage, setPendingPage] = useState(1);

  // 编辑/详情抽屉
  const [editDrawerOpen, setEditDrawerOpen] = useState(false);
  const [editIssue, setEditIssue] = useState<Issue | null>(null);
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [detailIssue, setDetailIssue] = useState<Issue | null>(null);
  const [editForm] = Form.useForm();

  // 审批弹窗
  const [approvalModalOpen, setApprovalModalOpen] = useState(false);
  const [approvalIssue, setApprovalIssue] = useState<Issue | null>(null);
  const [approvalForm] = Form.useForm();
  // 审批动作 (true=批准关闭, false=驳回申请), 用状态而非渲染期读表单值, 避免 useForm 未连接警告
  const [approvalAction, setApprovalAction] = useState(true);
  // 提交中状态 (防止重复点击导致多次发送邮件)
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [closureRequesting, setClosureRequesting] = useState(false);

  // 审核证据相关状态 (用于详情/编辑抽屉展示)
  const [detailEvidence, setDetailEvidence] = useState<IssueAttachment[]>([]);
  const [editEvidence, setEditEvidence] = useState<IssueAttachment[]>([]);
  const [evidenceUrls, setEvidenceUrls] = useState<Record<number, string>>({});
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string>('');
  const [uploadingEvidence, setUploadingEvidence] = useState(false);

  // 关闭证据相关状态 (被审核员申请关闭时上传, 独立于审核证据)
  const [closureEvidence, setClosureEvidence] = useState<IssueAttachment[]>([]);
  const [closureEvidenceUrls, setClosureEvidenceUrls] = useState<Record<number, string>>({});
  const [uploadingClosure, setUploadingClosure] = useState(false);
  // 详情抽屉用的关闭证据 (审批人查看)
  const [detailClosureEvidence, setDetailClosureEvidence] = useState<IssueAttachment[]>([]);

  // 指标卡点击交互: 控制 Tab + 逾期问题弹窗
  const [activeTab, setActiveTab] = useState<string>(isAdminOrLead ? 'pending' : 'projects');
  const [overdueModalOpen, setOverdueModalOpen] = useState(false);
  const [overdueIssues, setOverdueIssues] = useState<Issue[]>([]);

  // 指标卡点击: 切换 Tab + 自动筛选
  const handleCardClick = (type: 'projects' | 'issues' | 'pending_issues' | 'overdue' | 'pending_closure') => {
    if (type === 'overdue') {
      // 逾期: 弹窗展示所有逾期问题 (Deadline 硬边界: 次日零点起且未关闭/未待审批)
      const overdue = issues.filter(
        (i) => i.Deadline
          && dayjs().isAfter(dayjs(i.Deadline), 'day')
          && i.Status !== 'closed'
          && i.Status !== 'pending_verification'
      );
      setOverdueIssues(overdue);
      setOverdueModalOpen(true);
      return;
    }
    if (type === 'issues') {
      // 我的问题: 清除状态筛选, 显示全部
      setIssueStatusFilter(undefined);
      setActiveTab('issues');
    } else if (type === 'pending_issues') {
      // 待处理: 切到问题列表 + 筛选 open 状态
      setIssueStatusFilter('open');
      setActiveTab('issues');
    } else if (type === 'pending_closure') {
      // 待审批关闭: 切到待关闭审批 Tab
      setActiveTab('pending');
    } else {
      setActiveTab(type);
    }
  };

  // ============ 数据加载 ============
  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true);
    try {
      const res = await getMyProjectsApi();
      setProjects(res || []);
    } catch {
      setProjects([]);
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  const fetchIssues = useCallback(async () => {
    setIssuesLoading(true);
    try {
      const res = await getMyIssuesApi({
        plan_id: issuePlanFilter,
        phase_code: issuePhaseFilter,
        status: issueStatusFilter,
        keyword: issueKeyword || undefined,
        page: issuePage,
        page_size: 20,
      });
      setIssues(res.items || []);
      setIssuesTotal(res.total || 0);
    } catch {
      setIssues([]);
      setIssuesTotal(0);
    } finally {
      setIssuesLoading(false);
    }
  }, [issuePlanFilter, issuePhaseFilter, issueStatusFilter, issueKeyword, issuePage]);

  // 项目筛选选项 (有问题的项目列表, HRDB)
  const fetchIssueFilters = useCallback(async () => {
    try {
      const res = await getMyIssueFiltersApi();
      setIssueProjectFilters({ projects: res.projects || [] });
    } catch {
      setIssueProjectFilters({ projects: [] });
    }
  }, []);

  const fetchPendingClosures = useCallback(async () => {
    setPendingLoading(true);
    try {
      const res = await getPendingClosuresApi({
        phase_code: pendingPhaseFilter,
        page: pendingPage,
        page_size: 20,
      });
      setPendingClosures(res.items || []);
      setPendingTotal(res.total || 0);
    } catch {
      setPendingClosures([]);
      setPendingTotal(0);
    } finally {
      setPendingLoading(false);
    }
  }, [pendingPhaseFilter, pendingPage]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // 编辑抽屉打开时预填表单 (Form 包裹在 {editIssue && ...} 内, 需等其挂载后再填充, 避免 useForm 未连接警告)
  useEffect(() => {
    if (editIssue && editDrawerOpen) {
      editForm.setFieldsValue({
        RootCause: editIssue.RootCause || '',
        CorrectiveAction: editIssue.CorrectiveAction || '',
        PlannedCloseDate: editIssue.PlannedCloseDate ? dayjs(editIssue.PlannedCloseDate) : null,
        OwnerName: editIssue.OwnerName || '',
      });
    }
  }, [editIssue, editDrawerOpen, editForm]);

  useEffect(() => {
    if (isReviewee || isAdminOrLead) {
      fetchIssues();
    }
  }, [fetchIssues, isReviewee, isAdminOrLead]);

  // 项目筛选选项随问题列表可见范围加载
  useEffect(() => {
    if (isReviewee || isAdminOrLead) {
      fetchIssueFilters();
    }
  }, [fetchIssueFilters, isReviewee, isAdminOrLead]);

  useEffect(() => {
    if (isAdminOrLead) {
      fetchPendingClosures();
    }
  }, [fetchPendingClosures, isAdminOrLead]);

  // 切到待关闭审批 Tab 时主动刷新一次 (避免新提交的关闭申请未及时同步)
  useEffect(() => {
    if (isAdminOrLead && activeTab === 'pending') {
      fetchPendingClosures();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, isAdminOrLead]);

  // ============ 操作处理 ============

  // 判断附件是否为图片
  const isImageAttachment = (att: IssueAttachment): boolean => {
    return !!att.MimeType?.startsWith('image/') ||
      /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '');
  };

  // 加载审核证据 (优先使用 Issue 已嵌入的 Evidence, 否则单独查询)
  const loadIssueEvidence = useCallback(async (issue: Issue): Promise<IssueAttachment[]> => {
    let atts = issue.Evidence;
    if (!atts || atts.length === 0) {
      try {
        atts = await listIssueEvidence(issue.Id);
      } catch {
        atts = [];
      }
    }
    // 为每个图片附件生成 Blob URL (避免重复生成)
    for (const att of atts || []) {
      if (isImageAttachment(att) && !evidenceUrls[att.Id]) {
        try {
          const url = await fetchAttachmentBlobUrl(att.Id);
          setEvidenceUrls((prev) => ({ ...prev, [att.Id]: url }));
        } catch {
          // 跳过
        }
      }
    }
    return atts || [];
  }, [evidenceUrls]);

  // 权限判断: 是否可管理证据 (admin 或责任人)
  // 责任人匹配: OwnerUserId (本地用户Id) 或 OwnerUserName (HRDB userName_in_charge) 等于当前用户 Username
  const canManageEvidence = (issue: Issue | null): boolean => {
    if (!issue || !user) return false;
    if (user.Role === 'admin') return true;
    if (issue.OwnerUserId === user.Id) return true;
    return !!(issue.OwnerUserName && issue.OwnerUserName === user.Username);
  };

  // 上传审核证据 (被审核员补充整改证据)
  const handleUploadEvidence = async (issueId: number, file: File) => {
    setUploadingEvidence(true);
    try {
      await uploadIssueEvidence(issueId, file);
      message.success(`已上传: ${file.name}`);
      // 刷新证据列表 + 生成 Blob URL
      const atts = await listIssueEvidence(issueId);
      setEditEvidence(atts);
      // 同步到详情抽屉 (若打开)
      if (detailIssue && detailIssue.Id === issueId) {
        setDetailEvidence(atts);
      }
      const newUrls: Record<number, string> = {};
      for (const att of atts) {
        if (isImageAttachment(att)) {
          try {
            const url = await fetchAttachmentBlobUrl(att.Id);
            newUrls[att.Id] = url;
          } catch {
            // 跳过
          }
        }
      }
      if (Object.keys(newUrls).length > 0) {
        setEvidenceUrls((prev) => ({ ...prev, ...newUrls }));
      }
    } catch {
      // 错误已由拦截器提示
    } finally {
      setUploadingEvidence(false);
    }
  };

  // 删除证据
  const handleDeleteEvidence = async (issueId: number, attachmentId: number) => {
    try {
      await deleteAttachment(attachmentId);
      message.success('已删除');
      // 释放 Blob URL
      const oldUrl = evidenceUrls[attachmentId];
      if (oldUrl) {
        URL.revokeObjectURL(oldUrl);
        setEvidenceUrls((prev) => {
          const next = { ...prev };
          delete next[attachmentId];
          return next;
        });
      }
      // 刷新证据列表
      const atts = await listIssueEvidence(issueId);
      setEditEvidence(atts);
      if (detailIssue && detailIssue.Id === issueId) {
        setDetailEvidence(atts);
      }
    } catch {
      // 错误已由拦截器提示
    }
  };

  // ============ 关闭证据 (被审核员申请关闭时上传, 独立于审核证据) ============

  // 加载关闭证据并生成 Blob URL
  const loadClosureEvidence = useCallback(async (issue: Issue): Promise<IssueAttachment[]> => {
    try {
      const atts = await listIssueClosureEvidence(issue.Id);
      // 为图片附件生成 Blob URL
      for (const att of atts || []) {
        if (isImageAttachment(att) && !closureEvidenceUrls[att.Id]) {
          try {
            const url = await fetchAttachmentBlobUrl(att.Id);
            setClosureEvidenceUrls((prev) => ({ ...prev, [att.Id]: url }));
          } catch {
            // 跳过
          }
        }
      }
      return atts || [];
    } catch {
      return [];
    }
  }, [closureEvidenceUrls]);

  // 上传关闭证据 (被审核员提交问题关闭申请时上传)
  const handleUploadClosureEvidence = async (issueId: number, file: File) => {
    setUploadingClosure(true);
    try {
      await uploadIssueClosureEvidence(issueId, file);
      message.success(`已上传关闭证据: ${file.name}`);
      // 刷新关闭证据列表 + 生成 Blob URL
      const atts = await listIssueClosureEvidence(issueId);
      setClosureEvidence(atts);
      const newUrls: Record<number, string> = {};
      for (const att of atts) {
        if (isImageAttachment(att)) {
          try {
            const url = await fetchAttachmentBlobUrl(att.Id);
            newUrls[att.Id] = url;
          } catch {
            // 跳过
          }
        }
      }
      if (Object.keys(newUrls).length > 0) {
        setClosureEvidenceUrls((prev) => ({ ...prev, ...newUrls }));
      }
    } catch {
      // 错误已由拦截器提示
    } finally {
      setUploadingClosure(false);
    }
  };

  // 删除关闭证据 (责任人本人或管理员)
  const handleDeleteClosureEvidence = async (issueId: number, attachmentId: number) => {
    try {
      await deleteIssueClosureEvidence(issueId, attachmentId);
      message.success('关闭证据已删除');
      // 释放 Blob URL
      const oldUrl = closureEvidenceUrls[attachmentId];
      if (oldUrl) {
        URL.revokeObjectURL(oldUrl);
        setClosureEvidenceUrls((prev) => {
          const next = { ...prev };
          delete next[attachmentId];
          return next;
        });
      }
      // 刷新关闭证据列表
      const atts = await listIssueClosureEvidence(issueId);
      setClosureEvidence(atts);
    } catch {
      // 错误已由拦截器提示
    }
  };

  // 打开编辑抽屉
  const handleEditIssue = async (issue: Issue) => {
    setEditIssue(issue);
    setEditDrawerOpen(true);
    // 并行加载审核证据 (只读) + 关闭证据 (可上传)
    try {
      const [evi, closure] = await Promise.all([
        loadIssueEvidence(issue),
        loadClosureEvidence(issue),
      ]);
      setEditEvidence(evi);
      setClosureEvidence(closure);
    } catch {
      setEditEvidence([]);
      setClosureEvidence([]);
    }
  };

  // 提交编辑
  const handleEditSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      if (!editIssue) return;
      const payload: WorkbenchUpdatePayload = {
        RootCause: values.RootCause || null,
        CorrectiveAction: values.CorrectiveAction || null,
        PlannedCloseDate: values.PlannedCloseDate
          ? values.PlannedCloseDate.format('YYYY-MM-DDTHH:mm:ss')
          : null,
        OwnerName: values.OwnerName || null,
      };
      await workbenchUpdateIssueApi(editIssue.Id, payload);
      message.success('问题更新成功');
      setEditDrawerOpen(false);
      fetchIssues();
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    }
  };

  // 申请关闭
  const handleRequestClosure = async (issue: Issue) => {
    if (closureRequesting) return;  // 防重复点击
    setClosureRequesting(true);
    const hide = message.loading('正在提交关闭申请...', 0);
    try {
      await requestClosureApi(issue.Id);
      hide();
      message.success('关闭申请已提交, 等待审核员审批');
      fetchIssues();
    } catch (err) {
      hide();
      message.error('提交失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setClosureRequesting(false);
    }
  };

  // 打开审批弹窗
  const handleOpenApproval = (issue: Issue, approved: boolean) => {
    setApprovalIssue(issue);
    setApprovalAction(approved);
    approvalForm.setFieldsValue({ Approved: approved, VerificationComments: '' });
    setApprovalModalOpen(true);
  };

  // 提交审批
  const handleApprovalSubmit = async () => {
    if (approvalSubmitting) return;  // 防重复点击
    try {
      const values = await approvalForm.validateFields();
      if (!approvalIssue) return;
      setApprovalSubmitting(true);
      const hide = message.loading('正在提交审批...', 0);
      await approveClosureApi(approvalIssue.Id, {
        Approved: values.Approved,
        VerificationComments: values.VerificationComments || null,
      });
      hide();
      message.success(values.Approved ? '问题已关闭' : '关闭申请已驳回');
      setApprovalModalOpen(false);
      fetchPendingClosures();
      fetchIssues();
      // 批准关闭后: 若问题关联了 MSIA 审核条款, 提示管理员/审核员前往更新评分
      if (values.Approved && approvalIssue.PlanId && approvalIssue.PhaseCode && approvalIssue.PhaseReviewItemId) {
        const before = approvalIssue.ScoreAtClosure;
        const needUpdate = approvalIssue.ScoreAfterUpdate == null;
        modal.confirm({
          title: '是否更新该审核条款的评分?',
          content: (
            <div style={{ fontSize: 13 }}>
              <p>问题已关闭，该问题关联的审核条款评分可能需要更新。</p>
              <p>
                <strong>项目:</strong> {approvalIssue.ProjectName || approvalIssue.PlanId}<br/>
                <strong>MSIA 阶段:</strong> {approvalIssue.PhaseCode}<br/>
                <strong>审核条款:</strong> {approvalIssue.ItemName || `#${approvalIssue.PhaseReviewItemId}`}<br/>
                <strong>整改前评分:</strong> {before != null ? `${(Number(before) * 100).toFixed(0)}%` : '未评分'}
                {!needUpdate && <><br/><strong>整改后评分:</strong> {(Number(approvalIssue.ScoreAfterUpdate) * 100).toFixed(0)}%</>}
              </p>
              <p style={{ color: '#2E5CE6' }}>
                {needUpdate ? '点击"前往更新"将跳转到该项目/阶段的评审页面并定位到此检查项，您可以重新评分。'
                  : '该条款评分已更新，如需调整仍可前往评审页面。'}
              </p>
            </div>
          ),
          okText: '前往更新',
          cancelText: '稍后',
          onOk: () => {
            navigate(
              `/projects/${approvalIssue.PlanId}/phases/${approvalIssue.PhaseCode}?itemId=${approvalIssue.PhaseReviewItemId}`
            );
          },
        });
      }
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setApprovalSubmitting(false);
    }
  };

  // ============ 我的项目库表格列 ============
  const projectColumns: ColumnsType<MyProjectItem> = [
    {
      title: '项目',
      key: 'project',
      width: 220,
      render: (_, record) => (
        <div>
          <Text strong style={{ fontSize: 12 }}>
            {record.projectName || record.order_description || `工单 ${record.orderId || '-'}`}
          </Text>
          {record.lineType && (
            <div>
              <Tag style={{ fontSize: 10 }}>{record.lineType}</Tag>
            </div>
          )}
        </div>
      ),
    },
    {
      title: '负责人',
      key: 'owner',
      width: 120,
      render: (_, record) => (
        <div>
          <Text style={{ fontSize: 11 }}>{record.ownerName || '—'}</Text>
          {record.leadUser && (
            <div><Text type="secondary" style={{ fontSize: 10 }}>评审: {record.leadUser}</Text></div>
          )}
        </div>
      ),
    },
    {
      title: '工厂/产线',
      key: 'plant',
      width: 100,
      render: (_, record) => (
        <Text style={{ fontSize: 11 }}>
          {[record.plantName, record.lineName].filter(Boolean).join(' / ') || '—'}
        </Text>
      ),
    },
    // MSIA1-5 各阶段评分
    ...[1, 2, 3, 4, 5].map((i) => {
      const code = `MSIA${i}`;
      const meta = PHASE_META[code];
      return {
        title: (
          <Tooltip title={meta.desc}>
            <Tag color={meta.color} style={{ margin: 0, fontSize: 10 }}>{code}</Tag>
          </Tooltip>
        ),
        key: code,
        width: 80,
        render: (_: unknown, record: MyProjectItem) => {
          const phase = record.phases.find((p) => p.phase_num === i);
          if (!phase || phase.avg_score === null) {
            return <Text type="secondary" style={{ fontSize: 10 }}>—</Text>;
          }
          const percent = phase.avg_percent || 0;
          const color = percent >= 75 ? BRAND.success : percent >= 50 ? BRAND.warning : BRAND.danger;
          return (
            <Tooltip title={`${phase.item_count} 项已评`}>
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  fontSize: 13,
                  fontWeight: 700,
                  fontFamily: NUM_FONT,
                  color,
                }}>
                  {percent.toFixed(1)}%
                </div>
                <Progress
                  percent={percent}
                  size="small"
                  strokeColor={color}
                  showInfo={false}
                  style={{ margin: 0, transform: 'scale(0.8)' }}
                />
              </div>
            </Tooltip>
          );
        },
      };
    }),
    {
      title: '总体',
      key: 'overall',
      width: 80,
      render: (_, record) => {
        if (record.overall_avg_percent === null) {
          return <Text type="secondary">—</Text>;
        }
        const percent = record.overall_avg_percent;
        const color = percent >= 75 ? BRAND.success : percent >= 50 ? BRAND.warning : BRAND.danger;
        return (
          <div style={{ textAlign: 'center' }}>
            <Statistic
              value={percent}
              precision={1}
              suffix="%"
              valueStyle={{ fontSize: 16, color, fontFamily: NUM_FONT }}
            />
          </div>
        );
      },
    },
    {
      title: '问题',
      key: 'issues',
      width: 60,
      render: (_, record) => (
        <Badge count={record.issue_count} showZero color={BRAND.orange} />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right' as const,
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/projects/${record.planId}`)}
          >
            详情
          </Button>
        </Space>
      ),
    },
  ];

  // ============ 问题列表表格列 ============
  const issueColumns: ColumnsType<Issue> = [
    {
      title: '问题编号',
      dataIndex: 'IssueNo',
      key: 'IssueNo',
      width: 140,
      render: (text: string) => (
        <Text style={{ fontFamily: NUM_FONT, fontSize: 11 }}>{text}</Text>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'ProjectName',
      key: 'ProjectName',
      width: 160,
      ellipsis: true,
      render: (v: string | null | undefined, record) => {
        const name = v || '';
        if (!name && !record.PlanId) return <Text type="secondary">—</Text>;
        return <Text style={{ fontSize: 12 }}>{name || `PlanID: ${record.PlanId}`}</Text>;
      },
    },
    {
      title: '标题',
      dataIndex: 'Title',
      key: 'Title',
      width: 200,
      ellipsis: true,
      render: (text: string) => <Text style={{ fontSize: 12 }}>{text}</Text>,
    },
    {
      title: '阶段',
      dataIndex: 'PhaseCode',
      key: 'PhaseCode',
      width: 80,
      render: (code: string) => {
        const meta = PHASE_META[code];
        return meta ? (
          <Tag color={meta.color} style={{ fontSize: 10 }}>{code}</Tag>
        ) : <Text type="secondary">—</Text>;
      },
    },
    {
      title: '优先级',
      dataIndex: 'Priority',
      key: 'Priority',
      width: 70,
      render: (p: IssuePriority) => {
        const meta = priorityMap[p] || priorityMap.medium;
        return <Tag color={meta.color} style={{ fontSize: 10 }}>{meta.text}</Tag>;
      },
    },
    {
      title: '严重度',
      dataIndex: 'Severity',
      key: 'Severity',
      width: 60,
      render: (s: string) => {
        const meta = severityMap[s] || severityMap.M;
        return <Tag color={meta.color} style={{ fontSize: 10 }}>{s}</Tag>;
      },
    },
    {
      title: '状态',
      dataIndex: 'Status',
      key: 'Status',
      width: 90,
      render: (s: IssueStatus) => {
        const meta = statusMap[s] || statusMap.open;
        return <Tag color={meta.color} icon={meta.icon} style={{ fontSize: 10 }}>{meta.text}</Tag>;
      },
    },
    {
      title: '整改完成日期',
      dataIndex: 'Deadline',
      key: 'Deadline',
      width: 115,
      render: (date: string | null, record: Issue) => {
        if (!date) {
          return (
            <Tooltip title="阶段评审未完成, 暂不参与逾期判定">
              <Text type="secondary" style={{ fontSize: 10 }}>—</Text>
            </Tooltip>
          );
        }
        const d = dayjs(date);
        const isOverdue = dayjs().isAfter(d, 'day')
          && record.Status !== 'closed'
          && record.Status !== 'pending_verification';
        return (
          <Text style={{ fontSize: 10, color: isOverdue ? BRAND.danger : undefined }}>
            {d.format('YYYY-MM-DD')}
            {isOverdue && <Tag color="red" style={{ fontSize: 9, marginLeft: 4 }}>逾期</Tag>}
          </Text>
        );
      },
    },
    {
      title: '计划关闭',
      dataIndex: 'PlannedCloseDate',
      key: 'PlannedCloseDate',
      width: 100,
      render: (date: string | null) => {
        if (!date) return <Text type="secondary" style={{ fontSize: 10 }}>—</Text>;
        return <Text style={{ fontSize: 10 }}>{dayjs(date).format('YYYY-MM-DD')}</Text>;
      },
    },
    {
      title: '原因/措施',
      key: 'hasContent',
      width: 80,
      render: (_, record: Issue) => (
        <Space size={4}>
          {record.RootCause ? (
            <Tooltip title="已填写原因"><CheckCircleOutlined style={{ color: BRAND.success }} /></Tooltip>
          ) : (
            <Tooltip title="未填写原因"><ExclamationCircleOutlined style={{ color: '#d9d9d9' }} /></Tooltip>
          )}
          {record.CorrectiveAction ? (
            <Tooltip title="已填写措施"><CheckCircleOutlined style={{ color: BRAND.success }} /></Tooltip>
          ) : (
            <Tooltip title="未填写措施"><ExclamationCircleOutlined style={{ color: '#d9d9d9' }} /></Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      fixed: 'right' as const,
      render: (_, record: Issue) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<EyeOutlined />}
            onClick={async () => {
              setDetailIssue(record);
              setDetailDrawerOpen(true);
              try {
                const [evi, closure] = await Promise.all([
                  loadIssueEvidence(record),
                  loadClosureEvidence(record),
                ]);
                setDetailEvidence(evi);
                setDetailClosureEvidence(closure);
              } catch {
                setDetailEvidence([]);
                setDetailClosureEvidence([]);
              }
            }}
          >
            查看
          </Button>
          <Button
            size="small"
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEditIssue(record)}
            disabled={record.Status === 'closed'}
          >
            维护
          </Button>
          {record.Status !== 'closed' && record.Status !== 'pending_verification' && (
            <Popconfirm
              title="确认申请关闭此问题?"
              description="提交后将等待审核员审批"
              onConfirm={() => handleRequestClosure(record)}
              okText="确认"
              cancelText="取消"
              disabled={closureRequesting}
            >
              <Button
                size="small"
                type="link"
                icon={<SendOutlined />}
                style={{ color: '#F97316' }}
                loading={closureRequesting}
              >
                申请关闭
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ============ 待审批列表表格列 ============
  const pendingColumns: ColumnsType<Issue> = [
    ...issueColumns.slice(0, 7), // 前7列 (问题编号/项目/标题/阶段/优先级/严重度/状态)
    {
      title: '关闭申请时间',
      dataIndex: 'ClosureRequestedAt',
      key: 'ClosureRequestedAt',
      width: 120,
      render: (date: string | null) => (
        date ? <Text style={{ fontSize: 10 }}>{formatDateTime(date)}</Text> : <Text type="secondary">—</Text>
      ),
    },
    {
      title: '原因/措施',
      key: 'hasContent',
      width: 80,
      render: (_, record: Issue) => (
        <Space size={4} direction="vertical">
          {record.RootCause && (
            <Tooltip title={record.RootCause}>
              <Tag color="blue" style={{ fontSize: 9 }}>有原因</Tag>
            </Tooltip>
          )}
          {record.CorrectiveAction && (
            <Tooltip title={record.CorrectiveAction}>
              <Tag color="green" style={{ fontSize: 9 }}>有措施</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      fixed: 'right' as const,
      render: (_, record: Issue) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<EyeOutlined />}
            onClick={async () => {
              setDetailIssue(record);
              setDetailDrawerOpen(true);
              // 加载审核证据 + 关闭证据
              try {
                const [evi, closure] = await Promise.all([
                  loadIssueEvidence(record),
                  loadClosureEvidence(record),
                ]);
                setDetailEvidence(evi);
                setDetailClosureEvidence(closure);
              } catch {
                setDetailEvidence([]);
                setDetailClosureEvidence([]);
              }
            }}
          >
            查看
          </Button>
          <Button
            size="small"
            type="link"
            icon={<CheckOutlined />}
            style={{ color: BRAND.success }}
            onClick={() => handleOpenApproval(record, true)}
          >
            批准
          </Button>
          <Button
            size="small"
            type="link"
            icon={<CloseOutlined />}
            style={{ color: BRAND.danger }}
            onClick={() => handleOpenApproval(record, false)}
          >
            驳回
          </Button>
        </Space>
      ),
    },
  ];

  // ============ 统计数据 ============
  const stats = useMemo(() => {
    const totalProjects = projects.length;
    const totalIssues = issuesTotal;
    const pendingCount = issues.filter(
      (i) => i.Status === 'open' || i.Status === 'in_progress'
    ).length;
    const pendingClosureCount = pendingTotal;
    const overdueIssues = issues.filter(
      (i) => i.Deadline
        && dayjs().isAfter(dayjs(i.Deadline), 'day')
        && i.Status !== 'closed'
        && i.Status !== 'pending_verification'
    ).length;
    return { totalProjects, totalIssues, pendingCount, pendingClosureCount, overdueIssues };
  }, [projects, issues, issuesTotal, pendingTotal]);

  // ============ 渲染 ============
  return (
    <div style={industrialBgStyle}>
      {/* 顶部统计卡 - 点击快速进入对应内容 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={isAdminOrLead ? 4 : 5}>
          <Card
            size="small"
            hoverable
            onClick={() => handleCardClick('projects')}
            style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.primary}`, cursor: 'pointer' }}
          >
            <CornerMarker color={BRAND.primary} />
            <Statistic
              title="我的项目"
              value={stats.totalProjects}
              prefix={<ProjectOutlined style={{ color: BRAND.primary }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={isAdminOrLead ? 4 : 5}>
          <Card
            size="small"
            hoverable
            onClick={() => handleCardClick('issues')}
            style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.orange}`, cursor: 'pointer' }}
          >
            <CornerMarker color={BRAND.orange} />
            <Statistic
              title="我的问题"
              value={stats.totalIssues}
              prefix={<BugOutlined style={{ color: BRAND.orange }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={isAdminOrLead ? 4 : 5}>
          <Card
            size="small"
            hoverable
            onClick={() => handleCardClick('pending_issues')}
            style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.warning}`, cursor: 'pointer' }}
          >
            <CornerMarker color={BRAND.warning} />
            <Statistic
              title="待处理"
              value={stats.pendingCount}
              prefix={<ClockCircleOutlined style={{ color: BRAND.warning }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={isAdminOrLead ? 4 : 5}>
          <Card
            size="small"
            hoverable
            onClick={() => handleCardClick('overdue')}
            style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.danger}`, cursor: 'pointer' }}
          >
            <CornerMarker color={BRAND.danger} />
            <Statistic
              title="逾期问题"
              value={stats.overdueIssues}
              prefix={<WarningOutlined style={{ color: BRAND.danger }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT, color: stats.overdueIssues > 0 ? BRAND.danger : undefined }}
            />
          </Card>
        </Col>
        {isAdminOrLead && (
          <>
            <Col span={4}>
              <Card
                size="small"
                hoverable
                onClick={() => handleCardClick('pending_closure')}
                style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.purple}`, cursor: 'pointer' }}
              >
                <CornerMarker color={BRAND.purple} />
                <Statistic
                  title="待审批关闭"
                  value={stats.pendingClosureCount}
                  prefix={<SafetyCertificateOutlined style={{ color: BRAND.purple }} />}
                  valueStyle={{ fontSize: 22, fontFamily: NUM_FONT, color: stats.pendingClosureCount > 0 ? BRAND.purple : undefined }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.cyan}` }}>
                <CornerMarker color={BRAND.cyan} />
                <Statistic
                  title="用户角色"
                  value={user?.Role === 'admin' ? '管理员' : '主审核员'}
                  prefix={<DashboardOutlined style={{ color: BRAND.cyan }} />}
                  valueStyle={{ fontSize: 16 }}
                />
              </Card>
            </Col>
          </>
        )}
        {!isAdminOrLead && (
          <Col span={5}>
            <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.cyan}` }}>
              <CornerMarker color={BRAND.cyan} />
              <Statistic
                title="用户角色"
                value={user?.Role === 'reviewee' ? '被审核人 (ME)' : user?.Role || '—'}
                prefix={<DashboardOutlined style={{ color: BRAND.cyan }} />}
                valueStyle={{ fontSize: 16 }}
              />
            </Card>
          </Col>
        )}
      </Row>

      {/* 主体内容 - Tab 切换 */}
      <Card size="small" style={{ ...techCardStyle }}>
        <Tabs
          defaultActiveKey={isAdminOrLead ? 'pending' : 'projects'}
          items={[
            // ===== 被审核人: 我的项目库 =====
            ...(isReviewee || isAdminOrLead ? [{
              key: 'projects',
              label: (
                <Space size={4}>
                  <ProjectOutlined />
                  <span>我的项目库</span>
                  <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>{stats.totalProjects}</Tag>
                </Space>
              ),
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Input
                      placeholder="搜索项目名"
                      prefix={<FileSearchOutlined />}
                      value={projectKeyword}
                      onChange={(e) => setProjectKeyword(e.target.value)}
                      allowClear
                      style={{ width: 240 }}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchProjects} loading={projectsLoading}>
                      刷新
                    </Button>
                  </Space>
                  <Table<MyProjectItem>
                    columns={projectColumns}
                    dataSource={projects.filter((p) => {
                      if (!projectKeyword) return true;
                      const kw = projectKeyword.toLowerCase();
                      return (p.projectName || '').toLowerCase().includes(kw) ||
                             (p.order_description || '').toLowerCase().includes(kw);
                    })}
                    rowKey={(r) => r.planId}
                    loading={projectsLoading}
                    scroll={{ x: 1200 }}
                    size="small"
                    bordered
                    locale={{ emptyText: <Empty description="暂无负责的项目" /> }}
                    pagination={{
                      pageSize: 10,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 个项目`,
                    }}
                    onRow={(record) => ({
                      onClick: () => navigate(`/projects/${record.planId}`),
                      style: { cursor: 'pointer' },
                    })}
                  />
                </>
              ),
            }] : []),

            // ===== 被审核人: 审核问题列表 =====
            ...(isReviewee || isAdminOrLead ? [{
              key: 'issues',
              label: (
                <Space size={4}>
                  <BugOutlined style={{ color: BRAND.orange }} />
                  <span>审核问题列表</span>
                  <Tag color="orange" style={{ margin: 0, fontSize: 10 }}>{issuesTotal}</Tag>
                </Space>
              ),
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="按项目筛选"
                      value={issuePlanFilter}
                      onChange={(v) => { setIssuePlanFilter(v); setIssuePage(1); }}
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      style={{ width: 220 }}
                      options={issueProjectFilters.projects}
                    />
                    <Select
                      placeholder="按阶段筛选"
                      value={issuePhaseFilter}
                      onChange={(v) => { setIssuePhaseFilter(v); setIssuePage(1); }}
                      allowClear
                      style={{ width: 140 }}
                      options={[
                        { value: 'MSIA1', label: 'MSIA1 立项启动' },
                        { value: 'MSIA2', label: 'MSIA2 需求分析' },
                        { value: 'MSIA3', label: 'MSIA3 设计冻结' },
                        { value: 'MSIA4', label: 'MSIA4 预验收' },
                        { value: 'MSIA5', label: 'MSIA5 终验收' },
                      ]}
                    />
                    <Select
                      placeholder="按状态筛选"
                      value={issueStatusFilter}
                      onChange={(v) => { setIssueStatusFilter(v); setIssuePage(1); }}
                      allowClear
                      style={{ width: 120 }}
                      options={[
                        { value: 'open', label: '待处理' },
                        { value: 'in_progress', label: '处理中' },
                        { value: 'pending_verification', label: '待审批' },
                        { value: 'closed', label: '已关闭' },
                        { value: 'overdue', label: '逾期' },
                      ]}
                    />
                    <Input
                      placeholder="搜索问题名称"
                      value={issueKeyword}
                      onChange={(e) => { setIssueKeyword(e.target.value); setIssuePage(1); }}
                      allowClear
                      prefix={<SearchOutlined style={{ color: BRAND.gray }} />}
                      style={{ width: 200 }}
                    />
                    <Button icon={<ReloadOutlined />} onClick={() => { fetchIssues(); fetchIssueFilters(); }} loading={issuesLoading}>
                      刷新
                    </Button>
                  </Space>
                  <Table<Issue>
                    columns={issueColumns}
                    dataSource={issues}
                    rowKey={(r) => r.Id}
                    loading={issuesLoading}
                    scroll={{ x: 1100 }}
                    size="small"
                    bordered
                    locale={{ emptyText: <Empty description="暂无审核问题" /> }}
                    pagination={{
                      current: issuePage,
                      total: issuesTotal,
                      pageSize: 20,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 条`,
                      onChange: (p) => setIssuePage(p),
                    }}
                  />
                </>
              ),
            }] : []),

            // ===== 管理员/主审核员: 待关闭审批 =====
            ...(isAdminOrLead ? [{
              key: 'pending',
              label: (
                <Space size={4}>
                  <SafetyCertificateOutlined style={{ color: BRAND.purple }} />
                  <span>待关闭审批</span>
                  {pendingTotal > 0 && (
                    <Badge count={pendingTotal} size="small" />
                  )}
                </Space>
              ),
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="按阶段筛选"
                      value={pendingPhaseFilter}
                      onChange={(v) => { setPendingPhaseFilter(v); setPendingPage(1); }}
                      allowClear
                      style={{ width: 140 }}
                      options={[
                        { value: 'MSIA1', label: 'MSIA1 立项启动' },
                        { value: 'MSIA2', label: 'MSIA2 需求分析' },
                        { value: 'MSIA3', label: 'MSIA3 设计冻结' },
                        { value: 'MSIA4', label: 'MSIA4 预验收' },
                        { value: 'MSIA5', label: 'MSIA5 终验收' },
                      ]}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchPendingClosures} loading={pendingLoading}>
                      刷新
                    </Button>
                  </Space>
                  <Table<Issue>
                    columns={pendingColumns}
                    dataSource={pendingClosures}
                    rowKey={(r) => r.Id}
                    loading={pendingLoading}
                    scroll={{ x: 1200 }}
                    size="small"
                    bordered
                    locale={{ emptyText: <Empty description="暂无待审批的关闭申请" /> }}
                    pagination={{
                      current: pendingPage,
                      total: pendingTotal,
                      pageSize: 20,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 条`,
                      onChange: (p) => setPendingPage(p),
                    }}
                  />
                </>
              ),
            }] : []),
          ]}
        />
      </Card>

      {/* ===== 编辑抽屉 ===== */}
      <Drawer
        title={
          <Space>
            <EditOutlined style={{ color: BRAND.primary }} />
            <span>维护问题</span>
            {editIssue && (
              <Tag style={{ fontFamily: NUM_FONT, fontSize: 10 }}>{editIssue.IssueNo}</Tag>
            )}
          </Space>
        }
        width={560}
        open={editDrawerOpen}
        onClose={() => setEditDrawerOpen(false)}
        forceRender
        extra={
          <Space>
            <Button onClick={() => setEditDrawerOpen(false)}>取消</Button>
            <Button type="primary" icon={<CheckOutlined />} onClick={handleEditSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        {editIssue && (
          <div>
            {/* 问题基本信息 */}
            <Card size="small" title="问题基本信息" style={{ marginBottom: 16 }}>
              <Paragraph>
                <Text strong>标题: </Text>
                <Text>{editIssue.Title}</Text>
              </Paragraph>
              {/* 问题来源: MSIA 阶段 + 审核条款项具体内容 (后端注入 ItemName) */}
              <Paragraph>
                <Text strong>问题来源: </Text>
                {editIssue.PhaseCode && (
                  <Tag color={PHASE_META[editIssue.PhaseCode]?.color} style={{ fontSize: 11 }}>
                    {editIssue.PhaseCode}
                  </Tag>
                )}
                <Text type="secondary" style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
                  {editIssue.ItemNo || ''}
                </Text>
                {editIssue.ItemName && (
                  <Text style={{ fontSize: 12 }}>{editIssue.ItemName}</Text>
                )}
                {!editIssue.ItemName && !editIssue.ItemNo && (
                  <Text type="secondary">未关联审核条款</Text>
                )}
              </Paragraph>
              {editIssue.Description && (
                <Paragraph>
                  <Text strong>描述: </Text>
                  <Text>{editIssue.Description}</Text>
                </Paragraph>
              )}
              <Space wrap>
                {editIssue.PhaseCode && <Tag color={PHASE_META[editIssue.PhaseCode]?.color}>{editIssue.PhaseCode}</Tag>}
                <Tag color={priorityMap[editIssue.Priority]?.color}>{priorityMap[editIssue.Priority]?.text}</Tag>
                <Tag color={severityMap[editIssue.Severity]?.color}>严重度: {editIssue.Severity}</Tag>
                <Tag color={statusMap[editIssue.Status]?.color} icon={statusMap[editIssue.Status]?.icon}>
                  {statusMap[editIssue.Status]?.text}
                </Tag>
              </Space>
            </Card>

            {/* 审核证据展示 (被审核人只读查看审核员提交的证据, 不可编辑/删除/补充) */}
            <Card
              size="small"
              title={
                <Space>
                  <PaperClipOutlined style={{ color: BRAND.primary }} />
                  <span>审核证据</span>
                  <Tag color="blue" style={{ fontSize: 10 }}>{editEvidence.length}</Tag>
                  <Tag color="default" icon={<LockOutlined />} style={{ fontSize: 10, marginLeft: 4 }}>
                    只读
                  </Tag>
                </Space>
              }
              style={{ marginBottom: 16, borderTop: `2px solid ${BRAND.primary}` }}
            >
              {editEvidence.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无审核证据"
                  style={{ margin: '8px 0' }}
                />
              ) : (
                <Space size="small" wrap>
                  {editEvidence.map((att) => {
                    const isImg = isImageAttachment(att);
                    const url = evidenceUrls[att.Id];
                    return (
                      <div key={att.Id} style={{ position: 'relative', display: 'inline-block' }}>
                        {isImg && url ? (
                          <AntImage
                            width={88}
                            height={88}
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
                        ) : (
                          <Tooltip title={att.FileName}>
                            <Tag icon={<PaperClipOutlined />} style={{ fontSize: 11 }}>
                              {att.FileName.length > 16 ? `${att.FileName.slice(0, 14)}...` : att.FileName}
                            </Tag>
                          </Tooltip>
                        )}
                      </div>
                    );
                  })}
                </Space>
              )}
              <div style={{ marginTop: 8, fontSize: 11, color: '#999' }}>
                <LockOutlined /> 审核员登记问题时上传的证据, 被审核人仅可查看, 不可编辑
              </div>
            </Card>

            {/* 维护表单 */}
            <Form form={editForm} layout="vertical">
              <Form.Item
                label="原因分析"
                name="RootCause"
                tooltip="分析问题产生的根本原因"
              >
                <TextArea
                  rows={4}
                  placeholder="请输入原因分析..."
                  maxLength={2000}
                  showCount
                />
              </Form.Item>

              <Form.Item
                label="纠正措施"
                name="CorrectiveAction"
                tooltip="针对问题采取的纠正和预防措施"
              >
                <TextArea
                  rows={4}
                  placeholder="请输入纠正措施..."
                  maxLength={2000}
                  showCount
                />
              </Form.Item>

              <Form.Item
                label="计划完成日期"
                name="PlannedCloseDate"
                tooltip="预计完成纠正措施并关闭问题的日期"
              >
                <DatePicker
                  style={{ width: '100%' }}
                  placeholder="选择计划完成日期"
                />
              </Form.Item>

              {/* 整改完成日期 (Deadline): 系统按阶段评审日期+10天计算, 逾期判定硬边界, 仅展示 */}
              <Form.Item label="整改完成日期" tooltip="系统按阶段实际审核日期 + 10 天自动计算, 超过该日期未关闭将视为逾期; 阶段评审未完成时为空">
                {editIssue?.Deadline ? (
                  <Text strong style={{ color: dayjs().isAfter(dayjs(editIssue.Deadline), 'day') ? BRAND.danger : undefined }}>
                    {dayjs(editIssue.Deadline).format('YYYY-MM-DD')}
                    {dayjs().isAfter(dayjs(editIssue.Deadline), 'day') && editIssue.Status !== 'closed' && (
                      <Tag color="red" style={{ marginLeft: 8 }}>已逾期</Tag>
                    )}
                  </Text>
                ) : (
                  <Text type="secondary">阶段评审未完成, 暂未生成</Text>
                )}
              </Form.Item>

              <Form.Item label="责任人" name="OwnerName">
                <Input placeholder="责任人姓名" />
              </Form.Item>
            </Form>

            {/* 关闭证据 (被审核员纠正措施完成后上传, 用于申请关闭问题) */}
            <Card
              size="small"
              style={{ marginTop: 16, borderTop: `2px solid ${BRAND.success}` }}
              title={
                <Space>
                  <CheckCircleOutlined style={{ color: BRAND.success }} />
                  <span>关闭证据</span>
                  <Tag color="green" style={{ fontSize: 10 }}>{closureEvidence.length}</Tag>
                  {canManageEvidence(editIssue) && editIssue.Status !== 'closed' && (
                    <Tag color="blue" style={{ fontSize: 10, marginLeft: 4 }}>可上传</Tag>
                  )}
                  {editIssue.Status === 'closed' && (
                    <Tag color="default" icon={<LockOutlined />} style={{ fontSize: 10, marginLeft: 4 }}>
                      问题已关闭
                    </Tag>
                  )}
                </Space>
              }
            >
              {closureEvidence.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无关闭证据"
                  style={{ margin: '8px 0' }}
                />
              ) : (
                <Space size="small" wrap>
                  {closureEvidence.map((att) => {
                    const isImg = isImageAttachment(att);
                    const url = closureEvidenceUrls[att.Id];
                    return (
                      <div key={att.Id} style={{ position: 'relative', display: 'inline-block' }}>
                        {isImg && url ? (
                          <AntImage
                            width={88}
                            height={88}
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
                        ) : (
                          <Tooltip title={att.FileName}>
                            <Tag icon={<PaperClipOutlined />} style={{ fontSize: 11 }}>
                              {att.FileName.length > 16 ? `${att.FileName.slice(0, 14)}...` : att.FileName}
                            </Tag>
                          </Tooltip>
                        )}
                        {/* 责任人本人或管理员可删除关闭证据 (问题未关闭时) */}
                        {canManageEvidence(editIssue) && editIssue.Status !== 'closed' && (
                          <Popconfirm
                            title="确认删除此关闭证据?"
                            onConfirm={() => handleDeleteClosureEvidence(editIssue!.Id, att.Id)}
                            placement="top"
                          >
                            <Button
                              type="text"
                              size="small"
                              style={{
                                position: 'absolute',
                                top: -8,
                                right: -8,
                                background: '#fff',
                                borderRadius: '50%',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.15)',
                                padding: 0,
                                width: 20,
                                height: 20,
                                minWidth: 20,
                              }}
                              icon={<DeleteOutlined style={{ fontSize: 12, color: BRAND.danger }} />}
                            />
                          </Popconfirm>
                        )}
                      </div>
                    );
                  })}
                </Space>
              )}
              {/* 上传按钮: 责任人/admin 可上传多张图片作为关闭证据 (问题未关闭时) */}
              {canManageEvidence(editIssue) && editIssue.Status !== 'closed' && (
                <div style={{ marginTop: 12 }} onPaste={(e) => {
                  const items = e.clipboardData?.items;
                  if (!items) return;
                  const files: File[] = [];
                  for (let i = 0; i < items.length; i++) {
                    const item = items[i];
                    if (item.kind === 'file' && item.type.startsWith('image/')) {
                      const file = item.getAsFile();
                      if (file) files.push(file);
                    }
                  }
                  if (files.length === 0) return;
                  e.preventDefault();
                  files.forEach((f) => handleUploadClosureEvidence(editIssue!.Id, f));
                }}>
                  <Upload
                    name="file"
                    showUploadList={false}
                    multiple
                    accept="image/*"
                    beforeUpload={(file) => {
                      handleUploadClosureEvidence(editIssue!.Id, file as File);
                      return false;
                    }}
                  >
                    <Button
                      type="dashed"
                      size="small"
                      icon={<UploadOutlined style={{ fontSize: 12 }} />}
                      loading={uploadingClosure}
                      style={{ fontSize: 11, height: 28 }}
                    >
                      上传关闭证据
                    </Button>
                  </Upload>
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                    支持上传多张图片, 可点击添加或直接粘贴 (Ctrl+V), 作为问题关闭申请的证据 (供审核员审批时参考)
                  </div>
                </div>
              )}
              {!canManageEvidence(editIssue) && (
                <div style={{ fontSize: 11, color: '#999', marginTop: 8 }}>
                  <LockOutlined /> 仅问题责任人或管理员可上传关闭证据
                </div>
              )}
            </Card>

            {/* 提示 */}
            <Card size="small" style={{ marginTop: 16, background: '#fffbe6', border: '1px solid #ffe58f' }}>
              <Space>
                <ExclamationCircleOutlined style={{ color: BRAND.warning }} />
                <Text style={{ fontSize: 11 }}>
                  原因分析和纠正措施为选填项, 未填写也可点击"申请关闭"按钮提交关闭申请, 等待审核员审批。
                </Text>
              </Space>
            </Card>
          </div>
        )}
      </Drawer>

      {/* ===== 详情抽屉 (审批查看) ===== */}
      <Drawer
        title={
          <Space>
            <EyeOutlined style={{ color: BRAND.purple }} />
            <span>问题详情</span>
            {detailIssue && (
              <Tag style={{ fontFamily: NUM_FONT, fontSize: 10 }}>{detailIssue.IssueNo}</Tag>
            )}
          </Space>
        }
        width={560}
        open={detailDrawerOpen}
        onClose={() => setDetailDrawerOpen(false)}
      >
        {detailIssue && (
          <div>
            <Card size="small" title="基本信息" style={{ marginBottom: 12 }}>
              <Paragraph><Text strong>标题: </Text><Text>{detailIssue.Title}</Text></Paragraph>
              {/* 问题来源: MSIA 阶段 + 审核条款项具体内容 (后端注入 ItemName) */}
              <Paragraph>
                <Text strong>问题来源: </Text>
                {detailIssue.PhaseCode && (
                  <Tag color={PHASE_META[detailIssue.PhaseCode]?.color} style={{ fontSize: 11 }}>
                    {detailIssue.PhaseCode}
                  </Tag>
                )}
                <Text type="secondary" style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
                  {detailIssue.ItemNo || ''}
                </Text>
                {detailIssue.ItemName && (
                  <Text style={{ fontSize: 12 }}>{detailIssue.ItemName}</Text>
                )}
                {!detailIssue.ItemName && !detailIssue.ItemNo && (
                  <Text type="secondary">未关联审核条款</Text>
                )}
              </Paragraph>
              {detailIssue.Description && (
                <Paragraph><Text strong>描述: </Text><Text>{detailIssue.Description}</Text></Paragraph>
              )}
              <Space wrap>
                {detailIssue.PhaseCode && <Tag color={PHASE_META[detailIssue.PhaseCode]?.color}>{detailIssue.PhaseCode}</Tag>}
                <Tag color={priorityMap[detailIssue.Priority]?.color}>优先级: {priorityMap[detailIssue.Priority]?.text}</Tag>
                <Tag color={severityMap[detailIssue.Severity]?.color}>严重度: {detailIssue.Severity}</Tag>
              </Space>
            </Card>

            {/* 审核证据展示 */}
            <Card
              size="small"
              title={
                <Space>
                  <PaperClipOutlined style={{ color: BRAND.primary }} />
                  <span>审核证据</span>
                  <Tag color="blue" style={{ fontSize: 10 }}>{detailEvidence.length}</Tag>
                </Space>
              }
              style={{ marginBottom: 12, borderTop: `2px solid ${BRAND.primary}` }}
            >
              {detailEvidence.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无审核证据"
                  style={{ margin: '8px 0' }}
                />
              ) : (
                <Space size="small" wrap>
                  {detailEvidence.map((att) => {
                    const isImg = isImageAttachment(att);
                    const url = evidenceUrls[att.Id];
                    return (
                      <div key={att.Id} style={{ position: 'relative', display: 'inline-block' }}>
                        {isImg && url ? (
                          <AntImage
                            width={88}
                            height={88}
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
                        ) : (
                          <Tooltip title={att.FileName}>
                            <Tag icon={<PaperClipOutlined />} style={{ fontSize: 11 }}>
                              {att.FileName.length > 16 ? `${att.FileName.slice(0, 14)}...` : att.FileName}
                            </Tag>
                          </Tooltip>
                        )}
                      </div>
                    );
                  })}
                </Space>
              )}
            </Card>

            <Card size="small" title="原因分析" style={{ marginBottom: 12, borderTop: `2px solid ${BRAND.primary}` }}>
              <Paragraph>
                {detailIssue.RootCause || <Text type="secondary">未填写</Text>}
              </Paragraph>
            </Card>

            <Card size="small" title="纠正措施" style={{ marginBottom: 12, borderTop: `2px solid ${BRAND.success}` }}>
              <Paragraph>
                {detailIssue.CorrectiveAction || <Text type="secondary">未填写</Text>}
              </Paragraph>
            </Card>

            {/* 关闭证据展示 (被审核员上传, 审批人查看) */}
            <Card
              size="small"
              style={{ marginBottom: 12, borderTop: `2px solid ${BRAND.success}` }}
              title={
                <Space>
                  <CheckCircleOutlined style={{ color: BRAND.success }} />
                  <span>关闭证据</span>
                  <Tag color="green" style={{ fontSize: 10 }}>{detailClosureEvidence.length}</Tag>
                </Space>
              }
            >
              {detailClosureEvidence.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无关闭证据"
                  style={{ margin: '8px 0' }}
                />
              ) : (
                <Space size="small" wrap>
                  {detailClosureEvidence.map((att) => {
                    const isImg = isImageAttachment(att);
                    const url = closureEvidenceUrls[att.Id];
                    return (
                      <div key={att.Id} style={{ position: 'relative', display: 'inline-block' }}>
                        {isImg && url ? (
                          <AntImage
                            width={88}
                            height={88}
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
                        ) : (
                          <Tooltip title={att.FileName}>
                            <Tag icon={<PaperClipOutlined />} style={{ fontSize: 11 }}>
                              {att.FileName.length > 16 ? `${att.FileName.slice(0, 14)}...` : att.FileName}
                            </Tag>
                          </Tooltip>
                        )}
                      </div>
                    );
                  })}
                </Space>
              )}
            </Card>

            <Card size="small" title="时间信息" style={{ marginBottom: 12 }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 11 }}>计划关闭日期</Text>
                  <div>{detailIssue.PlannedCloseDate ? formatDate(detailIssue.PlannedCloseDate) : '—'}</div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 11 }}>申请关闭时间</Text>
                  <div>{detailIssue.ClosureRequestedAt ? formatDateTime(detailIssue.ClosureRequestedAt) : '—'}</div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 11 }}>创建时间</Text>
                  <div>{detailIssue.CreatedAt ? formatDateTime(detailIssue.CreatedAt) : '—'}</div>
                </Col>
              </Row>
            </Card>

            {detailIssue.VerificationComments && (
              <Card size="small" title="验证意见" style={{ borderTop: `2px solid ${BRAND.purple}` }}>
                <Paragraph>{detailIssue.VerificationComments}</Paragraph>
              </Card>
            )}
          </div>
        )}
      </Drawer>

      {/* ===== 审批弹窗 ===== */}
      <Modal
        title={
          <Space>
            <SafetyCertificateOutlined style={{ color: BRAND.purple }} />
            <span>{approvalAction ? '批准关闭问题' : '驳回关闭申请'}</span>
          </Space>
        }
        open={approvalModalOpen}
        onCancel={() => setApprovalModalOpen(false)}
        onOk={handleApprovalSubmit}
        confirmLoading={approvalSubmitting}
        forceRender
        okText={approvalSubmitting ? '提交中...' : '确认'}
        cancelText="取消"
        okButtonProps={{
          danger: !approvalAction,
          type: approvalAction ? 'primary' : 'default',
          disabled: approvalSubmitting,
        }}
      >
        {approvalIssue && (
          <div style={{ marginBottom: 16 }}>
            <Text strong>问题: {approvalIssue.Title}</Text>
            <div style={{ marginTop: 8 }}>
              <Tag style={{ fontFamily: NUM_FONT, fontSize: 10 }}>{approvalIssue.IssueNo}</Tag>
              {approvalIssue.PhaseCode && <Tag color={PHASE_META[approvalIssue.PhaseCode]?.color}>{approvalIssue.PhaseCode}</Tag>}
            </div>
          </div>
        )}
        <Form form={approvalForm} layout="vertical">
          <Form.Item name="Approved" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            label="验证意见"
            name="VerificationComments"
            tooltip="审批意见将记录在问题中"
          >
            <TextArea
              rows={3}
              placeholder="请输入验证意见..."
              maxLength={1000}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
