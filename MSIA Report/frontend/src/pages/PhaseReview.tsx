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
  Input,
  Modal,
  Form,
  Select,
  List,
  Popconfirm,
  Divider,
  Popover,
  Upload,
  Image as AntImage,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  AuditOutlined,
  SearchOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  InfoCircleOutlined,
  DashboardOutlined,
  PaperClipOutlined,
  UploadOutlined,
  FileImageOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';

import {
  PhaseReviewItem,
  getPhaseReviewItems,
} from '@/api/phaseReviewItems';
import { listMsiaPlansApi } from '@/api/msiaPlan';
import type { MsiaPlanItem } from '@/api/msiaPlan';
import {
  Issue,
  IssueSeverity,
  IssueAttachment,
  getIssues,
  createIssue,
  updateIssue,
  deleteIssue,
  listIssueEvidence,
  uploadIssueEvidence,
  deleteAttachment,
  fetchAttachmentBlobUrl,
} from '@/api/issues';
import {
  ReviewRecord,
  getItemReviews,
  createReview,
  getPhaseResult,
  getPhaseItemsLatest,
  type PhaseResult,
  type ItemLatestReview,
} from '@/api/reviews';
import { useAuthStore } from '@/store/auth';
import { formatDateTime } from '@/utils/format';
import { NUM_FONT } from '@/utils/fonts';
import {
  SCORE_LABEL_MAP as _SLM,
  scoreTagTextColor as _sttc,
  scoreCardStyle as _scs,
  SCORE_COLOR_RED as _SCR,
  SCORE_COLOR_YELLOW as _SCY,
  SCORE_COLOR_GREEN as _SCG,
} from '@/utils/scoreColor';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// 阶段元数据
const PHASE_META: Record<string, { label: string; color: string; desc: string; timing: string }> = {
  MSIA1: { label: '立项启动', color: '#8c8c8c', desc: 'Project Kick-off', timing: 'Project Kick-off' },
  MSIA2: { label: '需求分析', color: '#2E5CE6', desc: 'Planning & Design', timing: 'Planning & Design' },
  MSIA3: { label: '设计冻结', color: '#0FB5BA', desc: 'Design Freeze', timing: 'Design Freeze' },
  MSIA4: { label: '预验收', color: '#F97316', desc: 'Pre-Acceptance', timing: 'Pre-Acceptance' },
  MSIA5: { label: '终验收', color: '#10B981', desc: 'Final Acceptance', timing: 'Final Acceptance' },
};

// 7 档 Maturity 评分标准 (含详细说明, 供审核员参考) — 使用全局统一三档色调
const MATURITY_CRITERIA = [
  { value: 0, label: '0%', title: 'No Plan (无计划)', color: _SCR, desc: '完全未开始, 未制定任何计划或方案, 无相关文档和活动' },
  { value: 0.25, label: '25%', title: 'Initial (初始)', color: _SCR, desc: '已有初步想法或非正式讨论, 但未形成结构化文档, 执行不可控' },
  { value: 0.33, label: '33%', title: 'Drafting (起草中)', color: _SCR, desc: '正在起草文档或方案, 部分内容已成型但尚未评审, 存在较多缺口' },
  { value: 0.5, label: '50%', title: 'Partially Met (部分满足)', color: _SCR, desc: '已形成文档并部分执行, 但覆盖不完整或存在明显偏差, 需补充完善' },
  { value: 0.67, label: '67%', title: 'Mostly Met (大部分满足)', color: _SCR, desc: '方案完整且大部分已执行落实, 仅有少量待完善项或个别遗漏' },
  { value: 0.75, label: '75%', title: 'Substantially Met (基本满足)', color: _SCY, desc: '已基本满足所有要求, 仅有细微偏差或待最终确认, 不影响交付' },
  { value: 1.0, label: '100%', title: 'Fully Met (完全满足)', color: _SCG, desc: '完全满足所有要求, 已验证并归档, 无任何缺口或偏差' },
];

// 评分选项 (0~1.0, 7 档 Maturity) - 通用默认选项 (无专属标准时使用)
const SCORE_OPTIONS = MATURITY_CRITERIA.map((m) => ({
  value: m.value,
  label: `${m.label} - ${m.title}`,
}));

// 评分档位标签映射 (score -> {label, title, color}) — 使用全局统一色调
const SCORE_LABEL_MAP = _SLM;

// 评分选项条目类型 (统一格式, 兼容通用和专属标准)
interface ScoreCriteriaItem {
  score: number;
  desc: string;
}

// 根据检查项的 ScoreOptions 生成有效的评分选项 (过滤描述为空的档位)
function getItemScoreOptions(item: PhaseReviewItem | null): {
  options: { value: number; label: string }[];
  criteria: ScoreCriteriaItem[];
  isCustom: boolean;
} {
  if (!item || !item.ScoreOptions || item.ScoreOptions.length === 0) {
    // 无专属标准, 返回全部 7 档 (通用)
    const criteria: ScoreCriteriaItem[] = MATURITY_CRITERIA.map((m) => ({ score: m.value, desc: m.desc }));
    return { options: SCORE_OPTIONS, criteria, isCustom: false };
  }
  // 有专属标准: 只保留 desc 非空的档位
  const validOptions = item.ScoreOptions.filter(
    (opt) => opt.desc && opt.desc.trim().length > 0
  );
  const criteria: ScoreCriteriaItem[] = validOptions.map((opt) => ({ score: opt.score, desc: opt.desc }));
  const options = validOptions.map((opt) => {
    const meta = SCORE_LABEL_MAP[opt.score] || { label: `${opt.score * 100}%`, title: '', color: '#8c8c8c' };
    return { value: opt.score, label: `${meta.label} - ${meta.title}` };
  });
  return { options, criteria, isCustom: true };
}

// 严重等级映射
const severityMap: Record<string, { color: string; bg: string; label: string }> = {
  H: { color: '#EF4444', bg: '#fff1f0', label: 'High' },
  M: { color: '#F97316', bg: '#fff7e6', label: 'Middle' },
  L: { color: '#10B981', bg: '#f6ffed', label: 'Low' },
};

// 阶段评审页 - 基于 Excel Report MSIA1~5 sheet 的实际检查项清单
export default function PhaseReview() {
  const { message } = App.useApp();
  const { id, phaseId } = useParams<{ id: string; phaseId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const focusItemId = searchParams.get('itemId'); // 从问题关闭审批跳转而来, 定位到具体检查项
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.Role === 'admin';
  // 权限: 仅审核员 (admin/lead_reviewer/reviewer) 可评分, 被审核员 (reviewee) 只读
  const canReview = user?.Role === 'admin' || user?.Role === 'lead_reviewer' || user?.Role === 'reviewer';

  const [items, setItems] = useState<PhaseReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [projectInfo, setProjectInfo] = useState<MsiaPlanItem | null>(null);
  // 阶段平均分 (MSIA Result)
  const [phaseResult, setPhaseResult] = useState<PhaseResult | null>(null);
  // 阶段各检查项最新评审记录 (用于 RESULT 列)
  const [latestReviews, setLatestReviews] = useState<ItemLatestReview[]>([]);
  // 各检查项已登记问题数量 (用于"问题"按钮登记提示色)
  const [itemIssueCount, setItemIssueCount] = useState<Record<number, number>>({});

  // 评审弹窗
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewItem, setReviewItem] = useState<PhaseReviewItem | null>(null);
  const [reviewRecords, setReviewRecords] = useState<ReviewRecord[]>([]);
  const [reviewForm] = Form.useForm();
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [editingReviewId, setEditingReviewId] = useState<number | null>(null);

  // 问题弹窗
  const [issueModalOpen, setIssueModalOpen] = useState(false);
  const [issueItem, setIssueItem] = useState<PhaseReviewItem | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issueForm] = Form.useForm();
  const [issueSubmitting, setIssueSubmitting] = useState(false);
  const [editingIssueId, setEditingIssueId] = useState<number | null>(null);
  // 审核证据相关状态
  const [evidenceMap, setEvidenceMap] = useState<Record<number, IssueAttachment[]>>({});
  const [evidenceUrls, setEvidenceUrls] = useState<Record<number, string>>({});
  const [uploadingEvidence, setUploadingEvidence] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string>('');
  // 问题登记表单中待上传的证据文件列表 (创建问题时一并上传)
  // 使用 {id, file} 结构: 唯一 id 解决同名/同尺寸图片重复粘贴导致 React key 冲突与删除失效问题
  const [pendingFiles, setPendingFiles] = useState<{ id: string; file: File }[]>([]);

  // 兼容路由 phaseId 为数字 (如 "1") 或完整 PhaseCode (如 "MSIA1") 两种形式
  const phaseCode = phaseId ? (phaseId.startsWith('MSIA') ? phaseId : `MSIA${phaseId}`) : '';
  const meta = PHASE_META[phaseCode];

  // 拉取检查项
  const fetchItems = useCallback(async () => {
    if (!phaseCode) return;
    setLoading(true);
    try {
      const list = await getPhaseReviewItems(phaseCode);
      setItems(list || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [phaseCode]);

  // 拉取项目信息
  const fetchProjectInfo = useCallback(async () => {
    if (!id) return;
    try {
      const res = await listMsiaPlansApi({ page: 1, page_size: 200 });
      const found = res.items.find((it) => String(it.planId) === String(id));
      if (found) setProjectInfo(found);
    } catch {
      // 静默失败
    }
  }, [id]);

  // 拉取阶段平均分 (MSIA Result)
  const fetchPhaseResult = useCallback(async () => {
    if (!phaseCode) return;
    try {
      const res = await getPhaseResult(phaseCode, id);
      setPhaseResult(res);
    } catch {
      setPhaseResult(null);
    }
  }, [phaseCode, id]);

  // 拉取阶段各检查项最新评审记录 (用于 RESULT 列)
  const fetchLatestReviews = useCallback(async () => {
    if (!phaseCode) return;
    try {
      const res = await getPhaseItemsLatest(phaseCode, id);
      setLatestReviews(res || []);
    } catch {
      setLatestReviews([]);
    }
  }, [phaseCode, id]);

  // 拉取本项目本阶段所有问题, 统计各检查项已登记问题数量 (用于"问题"按钮登记提示色)
  // 注: 后端 page_size 上限为 200, 超过时分页拉取
  const fetchItemIssueCounts = useCallback(async () => {
    if (!id || !phaseCode) return;
    try {
      const pageSize = 200;
      const counts: Record<number, number> = {};
      let page = 1;
      let fetched = 0;
      let total = Infinity;
      while (fetched < total) {
        const res = await getIssues({
          plan_id: id,
          phase_code: phaseCode,
          page,
          page_size: pageSize,
        });
        const items = res.items || [];
        total = res.total ?? items.length;
        for (const iss of items) {
          if (iss.PhaseReviewItemId) {
            counts[iss.PhaseReviewItemId] = (counts[iss.PhaseReviewItemId] || 0) + 1;
          }
        }
        fetched += items.length;
        if (items.length < pageSize) break;
        page += 1;
      }
      setItemIssueCount(counts);
    } catch {
      setItemIssueCount({});
    }
  }, [id, phaseCode]);

  useEffect(() => {
    fetchItems();
    fetchProjectInfo();
    fetchPhaseResult();
    fetchLatestReviews();
    fetchItemIssueCounts();
  }, [fetchItems, fetchProjectInfo, fetchPhaseResult, fetchLatestReviews, fetchItemIssueCounts]);

  // 过滤
  const filteredItems = useMemo(() => {
    if (!keyword.trim()) return items;
    const kw = keyword.toLowerCase();
    return items.filter(
      (it) =>
        it.ItemName.toLowerCase().includes(kw) ||
        (it.Request || '').toLowerCase().includes(kw) ||
        (it.ItemType || '').toLowerCase().includes(kw)
    );
  }, [items, keyword]);

  // 从问题关闭审批跳转而来: 自动滚动并高亮目标检查项, 并展开该检查项的问题清单
  useEffect(() => {
    if (!focusItemId || loading || filteredItems.length === 0) return;
    const target = filteredItems.find((it) => String(it.Id) === focusItemId);
    if (!target) return;
    const timer = setTimeout(() => {
      const el = document.querySelector(`tr[data-item-id="${focusItemId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      // 自动打开该检查项的问题弹窗, 展示该检查项下所有问题及状态, 便于判断评分是否可更新
      openIssueModal(target);
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusItemId, filteredItems, loading]);

  // 统计
  const stats = useMemo(() => {
    const total = items.length;
    const docCount = items.filter((it) => it.ItemType === 'Doc.').length;
    const actionCount = items.filter((it) => it.ItemType === 'Action').length;
    const hasRequestCount = items.filter((it) => it.Request).length;
    return { total, docCount, actionCount, hasRequestCount };
  }, [items]);

  // ============ 评审弹窗 ============
  const openReviewModal = async (item: PhaseReviewItem) => {
    setReviewItem(item);
    setReviewModalOpen(true);
    setEditingReviewId(null);
    reviewForm.resetFields();
    reviewForm.setFieldsValue({ Score: undefined, Comments: '' });

    // 拉取该检查项的评审记录 (用于历史展示)
    try {
      const records = await getItemReviews(item.Id);
      setReviewRecords(records || []);
      // 多次评审以最新一次为准: 预填最新一条记录的数据 (无论是否本人), 便于参考
      // 不再进入"编辑模式", 提交时始终创建新记录, 确保最新 Id 反映最新评审
      if (records && records.length > 0) {
        const latestRecord = records[0]; // records 按 Id desc 排序, 第一条为最新
        reviewForm.setFieldsValue({
          Score: latestRecord.Score ?? undefined,
          Comments: latestRecord.Comments || '',
        });
      }
    } catch {
      setReviewRecords([]);
    }
  };

  const handleReviewSubmit = async () => {
    if (!reviewItem || !user) return;
    try {
      const values = await reviewForm.validateFields();
      setReviewSubmitting(true);

      const payload = {
        ProjectId: 1, // 默认项目 ID (兼容旧表结构)
        PhaseId: 1,   // 默认阶段 ID
        ItemId: 1,    // 默认 CheckItem ID
        PhaseReviewItemId: reviewItem.Id,
        PhaseCode: phaseCode,
        ItemNo: `${phaseCode}-${reviewItem.Seq}`,
        PlanId: id,   // MSIA 计划 ID, 区分不同项目
        Score: values.Score ?? null,
        Comments: values.Comments || '',
        Status: 'submitted' as const,
      };

      // 始终创建新评审记录 (多次评审以最新一次为准, max(Id) 即最新)
      // 若之前有本人的评审记录, 后端会保留历史, 但 RESULT 列展示最新 Id 的数据
      await createReview(payload);
      message.success('评审记录已提交');

      // 刷新评审记录
      const records = await getItemReviews(reviewItem.Id);
      setReviewRecords(records || []);
      setEditingReviewId(null);
      reviewForm.resetFields();
      // 刷新阶段平均分
      fetchPhaseResult();
      // 刷新 RESULT 列数据 (展示最新评分)
      fetchLatestReviews();
      // 关闭评审弹窗 (用户要求: 提交后退出评审界面)
      setReviewModalOpen(false);
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setReviewSubmitting(false);
    }
  };

  // ============ 问题弹窗 ============
  const openIssueModal = async (item: PhaseReviewItem) => {
    setIssueItem(item);
    setIssueModalOpen(true);
    setEditingIssueId(null);
    setPendingFiles([]);
    issueForm.resetFields();
    issueForm.setFieldsValue({
      Severity: 'M' as IssueSeverity,
      OwnerName: projectInfo?.ownerName || '',
    });

    // 拉取该检查项下的问题
    try {
      const res = await getIssues({
        phase_review_item_id: item.Id,
        plan_id: id,
        page: 1,
        page_size: 100,
      });
      const issueList = res.items || [];
      setIssues(issueList);
      // 为每个问题加载审核证据 (优先使用 Issue 已嵌入的 Evidence, 否则单独查询)
      const nextMap: Record<number, IssueAttachment[]> = {};
      const nextUrls: Record<number, string> = {};
      await Promise.all(
        issueList.map(async (iss) => {
          let atts = iss.Evidence;
          if (!atts || atts.length === 0) {
            try {
              atts = await listIssueEvidence(iss.Id);
            } catch {
              atts = [];
            }
          }
          nextMap[iss.Id] = atts || [];
          // 为每个图片附件生成 Blob URL
          for (const att of atts || []) {
            if (att.MimeType?.startsWith('image/') || /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '')) {
              try {
                const url = await fetchAttachmentBlobUrl(att.Id);
                nextUrls[att.Id] = url;
              } catch {
                // 跳过
              }
            }
          }
        }),
      );
      setEvidenceMap(nextMap);
      setEvidenceUrls(nextUrls);
    } catch {
      setIssues([]);
      setEvidenceMap({});
      setEvidenceUrls({});
    }
  };

  // 上传审核证据
  // 粘贴上传: 从剪贴板提取图片文件
  const handlePasteEvidence = (issueId: number | null, e: React.ClipboardEvent) => {
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
    e.preventDefault(); // 阻止默认粘贴行为
    if (issueId) {
      // 已创建问题: 直接上传
      files.forEach((f) => handleUploadEvidence(issueId, f));
    } else {
      // 创建中问题: 加入 pendingFiles, 为每张图片分配唯一 id
      // (同名/同尺寸图片重复粘贴时, 唯一 id 可保证 React key 不冲突, 删除时也能精确匹配)
      const withIds = files.map((f) => ({
        id: `paste-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
        file: f,
      }));
      setPendingFiles((prev) => [...prev, ...withIds]);
      message.success(`已从剪贴板添加 ${files.length} 张图片`);
    }
  };

  const handleUploadEvidence = async (issueId: number, file: File) => {
    setUploadingEvidence(true);
    try {
      await uploadIssueEvidence(issueId, file);
      message.success(`已上传: ${file.name}`);
      // 刷新该问题的证据列表
      const atts = await listIssueEvidence(issueId);
      setEvidenceMap((prev) => ({ ...prev, [issueId]: atts }));
      // 为所有图片附件生成 Blob URL (避免闭包旧值导致跳过)
      const newUrls: Record<number, string> = {};
      for (const att of atts) {
        if (att.MimeType?.startsWith('image/') || /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '')) {
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

  // 删除审核证据
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
      // 刷新该问题的证据列表
      const atts = await listIssueEvidence(issueId);
      setEvidenceMap((prev) => ({ ...prev, [issueId]: atts }));
    } catch {
      // 错误已由拦截器提示
    }
  };

  // 判断附件是否为图片
  const isImageAttachment = (att: IssueAttachment): boolean => {
    return !!att.MimeType?.startsWith('image/') ||
      /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '');
  };

  const handleIssueSubmit = async () => {
    if (!issueItem || !user) return;
    try {
      const values = await issueForm.validateFields();
      setIssueSubmitting(true);

      // 根据 Severity 自动推导 Priority
      const severityToPriority: Record<string, 'high' | 'medium' | 'low'> = { H: 'high', M: 'medium', L: 'low' };
      const autoPriority = severityToPriority[values.Severity as string] || 'medium';

      const payload = {
        PhaseReviewItemId: issueItem.Id,
        PlanId: id,
        PhaseCode: phaseCode,
        ItemNo: `${phaseCode}-${issueItem.Seq}`,
        Title: values.Title,
        Description: values.Description || '',
        OwnerName: values.OwnerName || projectInfo?.ownerName || '',
        Severity: values.Severity,
        Priority: autoPriority,
        Status: 'open' as const,
      };

      if (editingIssueId) {
        await updateIssue(editingIssueId, {
          Title: values.Title,
          Description: values.Description,
          OwnerName: values.OwnerName,
          Severity: values.Severity,
          Priority: autoPriority,
        });
        message.success('问题已更新');
      } else {
        const created = await createIssue(payload);
        message.success('问题已登记');
        // 创建问题后, 上传待上传的证据文件
        if (pendingFiles.length > 0) {
          let successCount = 0;
          let failedCount = 0;
          const failedFiles: { id: string; file: File }[] = [];
          for (const item of pendingFiles) {
            try {
              await uploadIssueEvidence(created.Id, item.file);
              successCount++;
            } catch {
              failedCount++;
              failedFiles.push(item); // 保留失败的文件, 以便用户重试
            }
          }
          if (failedCount === 0) {
            message.success(`${successCount} 个证据已上传`);
            setPendingFiles([]);
          } else if (successCount > 0) {
            message.warning(`已上传 ${successCount} 个, 失败 ${failedCount} 个, 请重新粘贴或点击重试失败的图片`);
            setPendingFiles(failedFiles);
          } else {
            message.error(`${failedCount} 个证据上传失败, 请检查后重试 (文件仍保留在上传区)`);
            setPendingFiles(failedFiles);
          }
        }
      }

      // 刷新问题列表 + 证据列表
      const res = await getIssues({
        phase_review_item_id: issueItem.Id,
        plan_id: id,
        page: 1,
        page_size: 100,
      });
      const issueList = res.items || [];
      setIssues(issueList);
      // 同步刷新 evidenceMap (新创建的问题无证据, 仅保留已有问题的证据)
      const nextMap: Record<number, IssueAttachment[]> = {};
      const nextUrls: Record<number, string> = {};
      await Promise.all(
        issueList.map(async (iss) => {
          let atts = iss.Evidence;
          if (!atts || atts.length === 0) {
            try {
              atts = await listIssueEvidence(iss.Id);
            } catch {
              atts = [];
            }
          }
          nextMap[iss.Id] = atts || [];
          for (const att of atts || []) {
            if (att.MimeType?.startsWith('image/') || /\.(jpg|jpeg|png|gif|bmp|webp|svg)$/i.test(att.FileName || '')) {
              try {
                const url = await fetchAttachmentBlobUrl(att.Id);
                nextUrls[att.Id] = url;
              } catch {
                // 跳过
              }
            }
          }
        }),
      );
      setEvidenceMap(nextMap);
      setEvidenceUrls(nextUrls);
      // 同步刷新各检查项问题计数 (问题按钮提示色)
      fetchItemIssueCounts();
      setEditingIssueId(null);
      issueForm.resetFields();
      issueForm.setFieldsValue({
        Severity: 'M' as IssueSeverity,
        OwnerName: projectInfo?.ownerName || '',
      });
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setIssueSubmitting(false);
    }
  };

  const handleEditIssue = (issue: Issue) => {
    setEditingIssueId(issue.Id);
    issueForm.setFieldsValue({
      Title: issue.Title,
      Description: issue.Description,
      OwnerName: issue.OwnerName,
      Severity: issue.Severity as IssueSeverity,
    });
  };

  const handleDeleteIssue = async (issueId: number) => {
    try {
      await deleteIssue(issueId);
      message.success('问题已删除');
      if (issueItem) {
        const res = await getIssues({
          phase_review_item_id: issueItem.Id,
          plan_id: id,
          page: 1,
          page_size: 100,
        });
        setIssues(res.items || []);
      }
      // 同步刷新各检查项问题计数 (问题按钮提示色)
      fetchItemIssueCounts();
    } catch (err) {
      message.error('删除失败');
    }
  };

  // 权限判断: 是否可编辑/删除问题
  const canManageIssue = (issue: Issue) => {
    if (!user) return false;
    if (user.Role === 'admin') return true;
    return issue.CreatedBy === user.Id;
  };

  // 表格列定义 (工业科技风)
  const columns: ColumnsType<PhaseReviewItem> = [
    {
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>
          SEQ
        </span>
      ),
      dataIndex: 'Seq',
      key: 'Seq',
      width: 56,
      fixed: 'left',
      render: (v: number) => (
        <Text
          strong
          style={{
            fontFamily: NUM_FONT,
            fontSize: 12,
            color: '#2E5CE6',
          }}
        >
          {v}
        </Text>
      ),
    },
    {
      title: '检查项 (Item)',
      dataIndex: 'ItemName',
      key: 'ItemName',
      width: 240,
      render: (v: string) => (
        <Text strong style={{ fontSize: 13, lineHeight: 1.4 }}>
          {v}
        </Text>
      ),
    },
    {
      title: 'REQUEST',
      dataIndex: 'Maturity100Desc',
      key: 'Maturity100Desc',
      width: 320,
      render: (desc: string | null, record) => {
        // 优先显示 100% 评分标准描述; 若无则回退到原 Request 标签
        if (desc && desc.trim()) {
          return (
            <Tooltip
              title={
                <div style={{ maxWidth: 420, whiteSpace: 'pre-wrap' }}>
                  <Text style={{ color: '#fff', fontSize: 12, lineHeight: 1.6 }}>
                    {desc}
                  </Text>
                </div>
              }
              placement="topLeft"
            >
              <div
                style={{
                  padding: '6px 10px',
                  backgroundColor: '#f6f8fa',
                  border: '1px solid #e1e4e8',
                  borderLeft: '3px solid #2E5CE6',
                  borderRadius: 3,
                  fontSize: 11,
                  lineHeight: 1.55,
                  color: '#4a5568',
                  display: '-webkit-box',
                  WebkitLineClamp: 4,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                  cursor: 'help',
                }}
              >
                {desc}
              </div>
            </Tooltip>
          );
        }
        // 回退: 显示原 Request 标签 (Reviewed/Countersigned/Aligned)
        const v = record.Request;
        if (!v) {
          return (
            <Tag
              style={{
                fontSize: 10, margin: 0, padding: '0 6px', lineHeight: '16px', height: 16,
                fontFamily: NUM_FONT,
                border: '1px dashed #d9d9d9', backgroundColor: 'transparent', color: '#bfbfbf',
              }}
            >
              —
            </Tag>
          );
        }
        const styleMap: Record<string, { color: string; bg: string; border: string }> = {
          Reviewed: { color: '#0958d9', bg: '#e6f7ff', border: '#91d5ff' },
          Countersigned: { color: '#d46b08', bg: '#fff7e6', border: '#ffd591' },
          Aligned: { color: '#531dab', bg: '#f9f0ff', border: '#d3adf7' },
        };
        const s = styleMap[v] || { color: '#595959', bg: '#fafafa', border: '#d9d9d9' };
        return (
          <Tag
            style={{
              fontSize: 10, margin: 0, padding: '0 8px', lineHeight: '16px', height: 16,
              fontFamily: NUM_FONT,
              border: `1px solid ${s.border}`, backgroundColor: s.bg, color: s.color, fontWeight: 600,
            }}
          >
            {v}
          </Tag>
        );
      },
    },
    {
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>
          RESULT
        </span>
      ),
      key: 'latestScore',
      width: 110,
      render: (_, record) => {
        // 关联 latestReviews 取本检查项最新评审记录 (多次评审以最新一次为准)
        const latest = latestReviews.find((r) => r.phase_review_item_id === record.Id);
        if (!latest) {
          // 未评审: 显示空 (避免重复评审)
          return (
            <Text type="secondary" style={{ fontSize: 11, color: '#bfbfbf' }}>
              —
            </Text>
          );
        }
        // 已评审: 显示评分档位
        const score = latest.score;
        const meta = score != null
          ? SCORE_LABEL_MAP[score] || { label: `${(score * 100).toFixed(0)}%`, title: '', color: '#8c8c8c' }
          : null;
        if (!meta) {
          // 有评审记录但无评分
          return (
            <Tooltip title={`已评审, 状态: ${latest.status} · ${formatDateTime(latest.updated_at || '')}`}>
              <Tag
                style={{
                  fontSize: 10, margin: 0, padding: '0 6px', lineHeight: '16px', height: 16,
                  fontFamily: NUM_FONT,
                  border: '1px solid #d9d9d9', backgroundColor: '#fafafa', color: '#595959',
                }}
              >
                已评审
              </Tag>
            </Tooltip>
          );
        }
        return (
          <Tooltip
            title={
              <div style={{ fontSize: 11 }}>
                <div>评分: {meta.label} ({meta.title})</div>
                <div>状态: {latest.status}</div>
                <div>时间: {formatDateTime(latest.updated_at || '')}</div>
              </div>
            }
          >
            <Tag
              style={{
                backgroundColor: meta.color,
                color: _sttc(score),
                fontWeight: 700,
                fontFamily: NUM_FONT,
                fontSize: 11,
                margin: 0,
                padding: '0 8px',
                lineHeight: '18px',
                height: 18,
                minWidth: 48,
                textAlign: 'center',
              }}
            >
              {meta.label}
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, record) => {
        // 该检查项已登记的问题数量: >0 时按钮显示浅蓝色提示 (比行浮动色稍深)
        const issueCount = itemIssueCount[record.Id] || 0;
        return (
          <Space size="small">
            <Button
              type="primary"
              size="small"
              icon={<AuditOutlined />}
              onClick={() => openReviewModal(record)}
            >
              评审
            </Button>
            {canReview && (
              <Tooltip title={issueCount > 0 ? `该检查项已登记 ${issueCount} 个问题` : '登记问题'}>
                <Button
                  size="small"
                  icon={<ExclamationCircleOutlined />}
                  style={
                    issueCount > 0
                      ? {
                          backgroundColor: '#D6E8FF',
                          borderColor: '#9BC2F7',
                          color: '#1D4ED8',
                          fontWeight: 600,
                        }
                      : undefined
                  }
                  onClick={() => openIssueModal(record)}
                >
                  问题{issueCount > 0 ? ` (${issueCount})` : ''}
                </Button>
              </Tooltip>
            )}
          </Space>
        );
      },
    },
  ];

  if (!phaseCode || !meta) {
    return (
      <Card>
        <Empty description="阶段参数无效" />
      </Card>
    );
  }

  return (
    <div>
      <style>{`
        .msia-phase-review-grid-bg {
          background-image:
            linear-gradient(rgba(46, 92, 230, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(46, 92, 230, 0.04) 1px, transparent 1px);
          background-size: 20px 20px;
        }
        .msia-phase-review-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, #fafbfc 0%, #f0f2f5 100%) !important;
          border-bottom: 2px solid ${meta.color} !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-phase-review-table .ant-table-tbody > tr:hover > td {
          background: #f0f7ff !important;
        }
        .msia-phase-review-table .ant-table-tbody > tr > td {
          padding: 8px 8px !important;
        }
        .msia-phase-review-table .ant-table-tbody > tr.phase-review-focus-row > td {
          background: rgba(46, 92, 230, 0.10) !important;
          box-shadow: inset 3px 0 0 #2E5CE6;
          animation: phase-review-flash 1.6s ease-in-out 2;
        }
        @keyframes phase-review-flash {
          0%, 100% { background: rgba(46, 92, 230, 0.10) !important; }
          50% { background: rgba(46, 92, 230, 0.22) !important; }
        }
      `}</style>

      {/* 返回按钮 */}
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/projects/${id}`)}
        style={{ marginBottom: 12, paddingLeft: 0 }}
      >
        返回项目详情
      </Button>

      {/* ============ 阶段信息头部 ============ */}
      <Card
        size="small"
        className="msia-phase-review-grid-bg"
        style={{ marginBottom: 16, borderTop: `3px solid ${meta.color}` }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                padding: '6px 12px', backgroundColor: meta.color, color: '#fff',
                fontSize: 14, fontWeight: 700,
                fontFamily: NUM_FONT,
                letterSpacing: 0.5, borderRadius: 3,
                boxShadow: `0 2px 4px ${meta.color}55`,
              }}
            >
              {phaseCode}
            </div>
            <div>
              <Title level={5} style={{ margin: 0, fontSize: 16 }}>{meta.label}</Title>
              <Text type="secondary" style={{ fontSize: 11, fontStyle: 'italic' }}>
                {meta.timing}
              </Text>
            </div>
          </div>
          <div style={{ textAlign: 'right', display: 'flex', alignItems: 'center', gap: 24 }}>
            {/* MSIA Result 指标卡 (三档实心交通灯: 黄档黄底黑字, 红绿底白字) */}
            <Tooltip title={`已评分检查项: ${phaseResult?.count ?? 0} 项 (0% 也计算在内, 未评分不参与)}`}>
              <div
                style={{
                  display: 'inline-flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  padding: '4px 16px',
                  backgroundColor: phaseResult?.avg_score != null
                    ? _scs(phaseResult.avg_score).bg
                    : '#fafafa',
                  border: `1px solid ${phaseResult?.avg_score != null ? _scs(phaseResult.avg_score).border : '#d9d9d9'}`,
                  borderRadius: 4,
                  minWidth: 120,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <DashboardOutlined
                    style={{
                      color: phaseResult?.avg_score != null ? _scs(phaseResult.avg_score).text : meta.color,
                      fontSize: 12,
                    }}
                  />
                  <Text
                    style={{
                      fontSize: 10,
                      letterSpacing: 1,
                      color: phaseResult?.avg_score != null ? _scs(phaseResult.avg_score).text : undefined,
                      opacity: phaseResult?.avg_score != null ? 0.72 : undefined,
                    }}
                    type={phaseResult?.avg_score != null ? undefined : 'secondary'}
                  >
                    MSIA RESULT
                  </Text>
                </div>
                {phaseResult?.avg_score != null ? (
                  <Text
                    strong
                    style={{
                      fontSize: 22,
                      fontFamily: NUM_FONT,
                      color: _scs(phaseResult.avg_score).text,
                      lineHeight: 1.2,
                    }}
                  >
                    {(phaseResult.avg_score * 100).toFixed(1)}
                    <span style={{ fontSize: 12 }}>%</span>
                  </Text>
                ) : (
                  <Text
                    strong
                    style={{
                      fontSize: 22,
                      fontFamily: NUM_FONT,
                      color: '#bfbfbf',
                      lineHeight: 1.2,
                    }}
                  >
                    —
                  </Text>
                )}
                <Text
                  style={{
                    fontSize: 9,
                    color: phaseResult?.avg_score != null ? _scs(phaseResult.avg_score).text : undefined,
                    opacity: phaseResult?.avg_score != null ? 0.72 : undefined,
                  }}
                  type={phaseResult?.avg_score != null ? undefined : 'secondary'}
                >
                  ({phaseResult?.count ?? 0} items scored)
                </Text>
              </div>
            </Tooltip>

            {/* 项目信息 */}
            <div>
              <div>
                <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>PROJECT</Text>
              </div>
              <Text strong style={{ fontSize: 13 }}>
                {projectInfo?.projectName || id}
              </Text>
              {projectInfo?.ownerName && (
                <div>
                  <Text type="secondary" style={{ fontSize: 10 }}>
                    负责人: {projectInfo.ownerName}
                  </Text>
                </div>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* ============ 统计卡片 ============ */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Card size="small" style={{ borderTop: `3px solid ${meta.color}`, minWidth: 120 }}>
          <div><Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>TOTAL ITEMS</Text></div>
          <Text strong style={{ fontSize: 20, fontFamily: NUM_FONT, color: meta.color }}>
            {stats.total}
          </Text>
        </Card>
        <Card size="small" style={{ borderTop: '3px solid #2E5CE6', minWidth: 120 }}>
          <div><Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>DOCUMENTS</Text></div>
          <Text strong style={{ fontSize: 20, fontFamily: NUM_FONT, color: '#2E5CE6' }}>
            {stats.docCount}
          </Text>
        </Card>
        <Card size="small" style={{ borderTop: '3px solid #F97316', minWidth: 120 }}>
          <div><Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>ACTIONS</Text></div>
          <Text strong style={{ fontSize: 20, fontFamily: NUM_FONT, color: '#F97316' }}>
            {stats.actionCount}
          </Text>
        </Card>
        <Card size="small" style={{ borderTop: '3px solid #10B981', minWidth: 140 }}>
          <div><Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>HAS REQUEST</Text></div>
          <Text strong style={{ fontSize: 20, fontFamily: NUM_FONT, color: '#10B981' }}>
            {stats.hasRequestCount}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}> / {stats.total}</Text>
        </Card>
      </div>

      {/* ============ 主表格 ============ */}
      <Card
        title={
          <Space>
            <AuditOutlined style={{ color: meta.color, fontSize: 18 }} />
            <Title level={5} style={{ margin: 0 }}>评审检查项清单</Title>
            <Tag color="blue" style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
              {filteredItems.length} / {stats.total}
            </Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>
              (数据源: Excel Report {phaseCode} sheet)
            </Text>
          </Space>
        }
        extra={
          <Space>
            <Input
              placeholder="搜索检查项"
              prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
              allowClear
              style={{ width: 200 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
            <Button icon={<ReloadOutlined />} onClick={fetchItems} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 8 }} />
        ) : (
          <div className="msia-phase-review-table">
            <Table<PhaseReviewItem>
              rowKey="Id"
              columns={columns}
              dataSource={filteredItems}
              scroll={{ x: 1010 }}
              pagination={false}
              size="middle"
              bordered
              locale={{ emptyText: <Empty description="无检查项数据" /> }}
              rowClassName={(record) =>
                focusItemId && String(record.Id) === focusItemId ? 'phase-review-focus-row' : ''
              }
              onRow={(record) => ({
                'data-item-id': String(record.Id),
              } as any)}
            />
          </div>
        )}
      </Card>

      {/* ============ 评审弹窗 ============ */}
      <Modal
        title={
          <Space>
            <AuditOutlined style={{ color: meta.color }} />
            <span>评审检查项</span>
            {reviewItem && (
              <Tag style={{ fontFamily: NUM_FONT }}>
                {phaseCode}-{reviewItem.Seq}
              </Tag>
            )}
          </Space>
        }
        open={reviewModalOpen}
        onCancel={() => setReviewModalOpen(false)}
        footer={null}
        width={720}
        forceRender
      >
        {reviewItem && (
          <>
            {/* 检查项信息 */}
            <Card size="small" style={{ marginBottom: 16, backgroundColor: '#fafafa' }}>
              <Paragraph style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>检查项: </Text>
                <Text strong>{reviewItem.ItemName}</Text>
              </Paragraph>
              <Space size="small">
                {reviewItem.ItemType && (
                  <Tag color={reviewItem.ItemType === 'Doc.' ? 'blue' : 'orange'}>
                    {reviewItem.ItemType}
                  </Tag>
                )}
                {reviewItem.Request && (
                  <Tag color="purple">{reviewItem.Request}</Tag>
                )}
              </Space>
            </Card>

            {/* 历史评审记录 */}
            {reviewRecords.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ fontSize: 13 }}>
                  <CheckCircleOutlined style={{ color: '#10B981', marginRight: 4 }} />
                  已有评审记录 ({reviewRecords.length})
                </Text>
                <List
                  size="small"
                  dataSource={reviewRecords}
                  renderItem={(record) => (
                    <List.Item style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                      <div style={{ width: '100%' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <Space>
                            <Tag color="blue" style={{ fontFamily: NUM_FONT }}>
                              Score: {record.Score ?? '-'}
                            </Tag>
                            <Tag>{record.Status}</Tag>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {formatDateTime(record.UpdatedAt || record.CreatedAt)}
                          </Text>
                        </div>
                        {record.Comments && (
                          <Text style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
                            {record.Comments}
                          </Text>
                        )}
                      </div>
                    </List.Item>
                  )}
                  style={{ marginTop: 8 }}
                />
              </div>
            )}

            <Divider style={{ margin: '12px 0' }} />

            {/* 评审表单 */}
            {!canReview && (
              <div style={{ marginBottom: 12, padding: '8px 12px', backgroundColor: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 4 }}>
                <Text style={{ fontSize: 12, color: '#ad6800' }}>
                  <InfoCircleOutlined style={{ marginRight: 4 }} />
                  您是被审核人员, 仅可查看评审记录, 不可评分或修改
                </Text>
              </div>
            )}
            <Form form={reviewForm} layout="vertical">
              {(() => {
                const { options: itemScoreOptions, criteria: itemCriteria, isCustom } = getItemScoreOptions(reviewItem);
                return (
                  <Form.Item
                    label={
                      <Space size={4}>
                        <span>评分 (Maturity)</span>
                        <Popover
                          placement="rightTop"
                          trigger="click"
                          title={
                            <Space>
                              <InfoCircleOutlined style={{ color: '#2E5CE6' }} />
                              <span>{isCustom ? '本检查项专属评分标准' : 'Maturity 通用评分标准参考'}</span>
                            </Space>
                          }
                          content={
                            <div style={{ maxWidth: 520 }}>
                              {isCustom ? (
                                // 本检查项专属评分标准
                                itemCriteria.map((opt: ScoreCriteriaItem) => {
                                  const meta = SCORE_LABEL_MAP[opt.score] || { label: `${opt.score * 100}%`, title: '', color: '#8c8c8c' };
                                  return (
                                    <div
                                      key={opt.score}
                                      style={{
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: 8,
                                        padding: '6px 0',
                                        borderBottom: '1px dashed #f0f0f0',
                                      }}
                                    >
                                      <Tag
                                        style={{
                                          backgroundColor: meta.color,
                                          color: _sttc(opt.score),
                                          fontWeight: 700,
                                          fontFamily: NUM_FONT,
                                          fontSize: 10,
                                          margin: 0,
                                          minWidth: 40,
                                          textAlign: 'center',
                                        }}
                                      >
                                        {meta.label}
                                      </Tag>
                                      <div style={{ flex: 1 }}>
                                        <Text strong style={{ fontSize: 12 }}>{meta.title}</Text>
                                        <br />
                                        <Text type="secondary" style={{ fontSize: 11 }}>{opt.desc}</Text>
                                      </div>
                                    </div>
                                  );
                                })
                              ) : (
                                // 通用评分标准 (无专属标准时)
                                MATURITY_CRITERIA.map((m) => (
                                  <div
                                    key={m.value}
                                    style={{
                                      display: 'flex',
                                      alignItems: 'flex-start',
                                      gap: 8,
                                      padding: '6px 0',
                                      borderBottom: '1px dashed #f0f0f0',
                                    }}
                                  >
                                    <Tag
                                      style={{
                                        backgroundColor: m.color,
                                        color: _sttc(m.value),
                                        fontWeight: 700,
                                        fontFamily: NUM_FONT,
                                        fontSize: 10,
                                        margin: 0,
                                        minWidth: 40,
                                        textAlign: 'center',
                                      }}
                                    >
                                      {m.label}
                                    </Tag>
                                    <div style={{ flex: 1 }}>
                                      <Text strong style={{ fontSize: 12 }}>{m.title}</Text>
                                      <br />
                                      <Text type="secondary" style={{ fontSize: 11 }}>{m.desc}</Text>
                                    </div>
                                  </div>
                                ))
                              )}
                            </div>
                          }
                        >
                          <Button type="link" size="small" icon={<InfoCircleOutlined />} style={{ padding: '0 2px' }}>
                            查看评分标准
                          </Button>
                        </Popover>
                      </Space>
                    }
                    name="Score"
                    rules={[{ required: true, message: '请选择评分' }]}
                  >
                    <Select
                      placeholder="选择评分档位 (0~100%)"
                      options={itemScoreOptions}
                      disabled={!canReview}
                      optionRender={(option) => {
                        const meta = SCORE_LABEL_MAP[option.value as number] || { label: '', title: '', color: '#8c8c8c' };
                        // 直接显示本档位的具体评分标准描述 (而非通用标题)
                        const desc = isCustom
                          ? (itemCriteria.find((c: ScoreCriteriaItem) => c.score === option.value)?.desc || '')
                          : (MATURITY_CRITERIA.find((mc) => mc.value === option.value)?.desc || '');
                        return (
                          <div style={{ display: 'flex', alignItems: 'flex-start', padding: '2px 0', gap: 8 }}>
                            <Tag
                              style={{
                                backgroundColor: meta.color,
                                color: _sttc(option.value as number),
                                fontWeight: 700,
                                fontFamily: NUM_FONT,
                                fontSize: 10,
                                margin: 0,
                                minWidth: 36,
                                textAlign: 'center',
                                lineHeight: '16px',
                                height: 16,
                                flexShrink: 0,
                              }}
                            >
                              {meta.label}
                            </Tag>
                            <span style={{ fontSize: 12, color: '#4a5568', lineHeight: 1.4, flex: 1 }}>
                              {desc || meta.title}
                            </span>
                          </div>
                        );
                      }}
                    />
                  </Form.Item>
                );
              })()}
              <Form.Item
                label="评审意见 (Comments)"
                name="Comments"
              >
                <TextArea
                  rows={4}
                  placeholder="填写评审意见, 说明评分依据..."
                  maxLength={2000}
                  showCount
                  disabled={!canReview}
                />
              </Form.Item>
              <div style={{ textAlign: 'right' }}>
                <Space>
                  <Button onClick={() => setReviewModalOpen(false)}>取消</Button>
                  {canReview && (
                    <Button
                      type="primary"
                      loading={reviewSubmitting}
                      onClick={handleReviewSubmit}
                      icon={<CheckCircleOutlined />}
                    >
                      提交评审
                    </Button>
                  )}
                </Space>
              </div>
            </Form>
          </>
        )}
      </Modal>

      {/* ============ 问题弹窗 ============ */}
      <Modal
        title={
          <Space>
            <ExclamationCircleOutlined style={{ color: '#F97316' }} />
            <span>问题登记</span>
            {issueItem && (
              <Tag style={{ fontFamily: NUM_FONT }}>
                {phaseCode}-{issueItem.Seq}
              </Tag>
            )}
          </Space>
        }
        open={issueModalOpen}
        onCancel={() => {
          setIssueModalOpen(false);
          setEditingIssueId(null);
          issueForm.resetFields();
        }}
        footer={null}
        width={820}
        forceRender
      >
        {issueItem && (
          <>
            {/* 检查项信息 */}
            <Card size="small" style={{ marginBottom: 16, backgroundColor: '#fafafa' }}>
              <Paragraph style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>检查项: </Text>
                <Text strong>{issueItem.ItemName}</Text>
              </Paragraph>
              <Space size="small">
                {issueItem.ItemType && (
                  <Tag color={issueItem.ItemType === 'Doc.' ? 'blue' : 'orange'}>
                    {issueItem.ItemType}
                  </Tag>
                )}
                {issueItem.Request && <Tag color="purple">{issueItem.Request}</Tag>}
              </Space>
            </Card>

            {/* 已登记问题列表 */}
            {issues.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text strong style={{ fontSize: 13 }}>
                  <WarningOutlined style={{ color: '#F97316', marginRight: 4 }} />
                  已登记问题 ({issues.length})
                </Text>
                <List
                  size="small"
                  dataSource={issues}
                  renderItem={(issue) => {
                    const s = severityMap[issue.Severity] || severityMap.M;
                    // 编辑模式下: 当前编辑的问题高亮, 其他问题禁用"添加证据"按钮以避免误传
                    const isEditingThis = editingIssueId === issue.Id;
                    const isEditingOther = editingIssueId != null && !isEditingThis;
                    return (
                      <List.Item
                        style={{
                          padding: '8px 12px', borderBottom: '1px solid #f0f0f0',
                          backgroundColor: isEditingThis ? '#E6F4FF' : s.bg,
                          border: isEditingThis ? '2px solid #1677FF' : '1px solid transparent',
                          borderRadius: 4, marginBottom: 4,
                          opacity: isEditingOther ? 0.55 : 1,
                        }}
                        actions={
                          canManageIssue(issue) ? [
                            <Tooltip title="编辑" key="edit">
                              <Button
                                type="link"
                                size="small"
                                icon={<EditOutlined />}
                                onClick={() => handleEditIssue(issue)}
                              />
                            </Tooltip>,
                            <Popconfirm
                              key="delete"
                              title="确认删除此问题?"
                              onConfirm={() => handleDeleteIssue(issue.Id)}
                            >
                              <Tooltip title="删除">
                                <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                              </Tooltip>
                            </Popconfirm>,
                          ] : [
                            <Tooltip key="readonly" title={`仅 ${isAdmin ? '管理员' : '创建者'} 可编辑`}>
                              <Text type="secondary" style={{ fontSize: 11, cursor: 'not-allowed' }}>
                                <LockIcon /> 只读
                              </Text>
                            </Tooltip>,
                          ]
                        }
                      >
                        <List.Item.Meta
                          title={
                            <Space>
                              <Tag
                                style={{
                                  backgroundColor: s.color, color: '#fff', fontWeight: 700,
                                  fontFamily: NUM_FONT,
                                  fontSize: 10, margin: 0,
                                }}
                              >
                                {issue.Severity}
                              </Tag>
                              <Tag style={{ fontFamily: NUM_FONT, fontSize: 10 }}>{issue.IssueNo}</Tag>
                              <Text strong style={{ fontSize: 12 }}>{issue.Title}</Text>
                              {isEditingThis && (
                                <Tag color="processing" icon={<EditOutlined />} style={{ fontSize: 10, margin: 0 }}>
                                  正在编辑
                                </Tag>
                              )}
                            </Space>
                          }
                          description={
                            <div>
                              {issue.Description && (
                                <Text style={{ fontSize: 11, color: '#595959' }}>
                                  {issue.Description}
                                </Text>
                              )}
                              {/* 审核证据附件展示 */}
                              <div style={{ marginTop: 6 }}>
                                <Text type="secondary" style={{ fontSize: 10, display: 'block', marginBottom: 4 }}>
                                  <PaperClipOutlined style={{ marginRight: 4 }} />
                                  审核证据 ({(evidenceMap[issue.Id] || []).length})
                                </Text>
                                <Space size="small" wrap>
                                  {(evidenceMap[issue.Id] || []).map((att) => {
                                    const isImg = isImageAttachment(att);
                                    const url = evidenceUrls[att.Id];
                                    return (
                                      <div key={att.Id} style={{ position: 'relative', display: 'inline-block' }}>
                                        {isImg && url ? (
                                          <AntImage
                                            width={64}
                                            height={64}
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
                                            <Tag icon={<FileImageOutlined />} style={{ fontSize: 10, margin: 0 }}>
                                              {att.FileName.length > 12 ? `${att.FileName.slice(0, 10)}...` : att.FileName}
                                            </Tag>
                                          </Tooltip>
                                        )}
                                        {/* 删除按钮 (仅可管理人员可见) */}
                                        {canManageIssue(issue) && (
                                          <Popconfirm
                                            title="确认删除此证据?"
                                            onConfirm={() => handleDeleteEvidence(issue.Id, att.Id)}
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
                                                width: 18,
                                                height: 18,
                                                minWidth: 18,
                                              }}
                                              icon={<DeleteOutlined style={{ fontSize: 11, color: '#EF4444' }} />}
                                            />
                                          </Popconfirm>
                                        )}
                                      </div>
                                    );
                                  })}
                                  {/* 上传按钮 (仅可管理人员可见) */}
                                  {canManageIssue(issue) && (
                                    isEditingOther ? (
                                      <Tooltip title={`编辑模式下不可用, 当前正在更新 ${issues.find((it) => it.Id === editingIssueId)?.IssueNo || ''}`}>
                                        <Button
                                          type="dashed"
                                          size="small"
                                          icon={<UploadOutlined style={{ fontSize: 12 }} />}
                                          disabled
                                          style={{ fontSize: 11, height: 28 }}
                                        >
                                          添加证据
                                        </Button>
                                      </Tooltip>
                                    ) : (
                                      <div onPaste={(e) => handlePasteEvidence(issue.Id, e)}>
                                      <Upload
                                        name="file"
                                        showUploadList={false}
                                        beforeUpload={(file) => {
                                          handleUploadEvidence(issue.Id, file as File);
                                          return false; // 阻止默认上传行为
                                        }}
                                      >
                                        <Button
                                          type="dashed"
                                          size="small"
                                          icon={<UploadOutlined style={{ fontSize: 12 }} />}
                                          loading={uploadingEvidence}
                                          style={{ fontSize: 11, height: 28 }}
                                        >
                                          添加证据
                                        </Button>
                                      </Upload>
                                      <div style={{ fontSize: 10, color: '#999', marginTop: 2 }}>
                                        点击添加或直接粘贴图片 (Ctrl+V)
                                      </div>
                                      </div>
                                    )
                                  )}
                                </Space>
                              </div>
                              <div style={{ marginTop: 4 }}>
                                <Text type="secondary" style={{ fontSize: 10 }}>
                                  责任人: {issue.OwnerName || '-'} · 登记时间: {formatDateTime(issue.CreatedAt)}
                                </Text>
                                <div style={{ marginTop: 2, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                                  <Tag color={
                                    issue.Status === 'closed' ? 'success'
                                    : issue.Status === 'pending_verification' ? 'warning'
                                    : 'error'
                                  } style={{ fontSize: 10, margin: 0 }}>
                                    {issue.Status === 'closed' ? '已关闭' : issue.Status === 'pending_verification' ? '待关闭审批' : '待整改'}
                                  </Tag>
                                  {issue.ScoreAtClosure != null && (
                                    <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                                      整改前: {(Number(issue.ScoreAtClosure) * 100).toFixed(0)}%
                                    </Tag>
                                  )}
                                  {issue.ScoreAfterUpdate != null ? (
                                    <Tag color="green" style={{ fontSize: 10, margin: 0 }}>
                                      整改后: {(Number(issue.ScoreAfterUpdate) * 100).toFixed(0)}%
                                    </Tag>
                                  ) : issue.Status === 'closed' ? (
                                    <Tag color="orange" style={{ fontSize: 10, margin: 0 }}>评分待更新</Tag>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          }
                        />
                      </List.Item>
                    );
                  }}
                  style={{ marginTop: 8 }}
                />
              </div>
            )}

            <Divider style={{ margin: '12px 0' }} />

            {/* 问题登记表单 */}
            {editingIssueId && (() => {
              const editingIssue = issues.find((it) => it.Id === editingIssueId);
              return (
                <div style={{
                  marginBottom: 12, padding: '6px 10px', background: '#FFF7E6',
                  border: '1px solid #FFD591', borderRadius: 4,
                  display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                }}>
                  <Tag color="orange" icon={<EditOutlined />} style={{ margin: 0 }}>编辑模式</Tag>
                  {editingIssue && (
                    <Tag color="blue" style={{ margin: 0, fontFamily: NUM_FONT }}>
                      {editingIssue.IssueNo}
                    </Tag>
                  )}
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    正在更新此问题, 上传证据仅限当前问题, 其他问题的"添加证据"按钮已禁用
                  </Text>
                </div>
              );
            })()}
            <Form form={issueForm} layout="vertical">
              <Form.Item
                label="问题标题"
                name="Title"
                rules={[{ required: true, message: '请输入问题标题' }]}
              >
                <Input placeholder="简明描述发现的问题" maxLength={500} />
              </Form.Item>
              <Form.Item label="问题详情" name="Description">
                <TextArea
                  rows={3}
                  placeholder="详细描述问题内容, 影响范围, 建议整改方案等..."
                  maxLength={2000}
                  showCount
                />
              </Form.Item>
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item
                  label="严重等级 (H/M/L)"
                  name="Severity"
                  rules={[{ required: true }]}
                  style={{ flex: 1 }}
                >
                  <Select
                    options={[
                      { value: 'H', label: 'H - High (高, 严重影响项目)' },
                      { value: 'M', label: 'M - Middle (中, 需要关注)' },
                      { value: 'L', label: 'L - Low (低, 轻微问题)' },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  label="责任人"
                  name="OwnerName"
                  style={{ flex: 1 }}
                >
                  <Input placeholder="默认项目负责人" />
                </Form.Item>
              </div>

              {/* 审核证据上传区域 (创建问题时一并上传; 关闭证据由责任人在问题维护界面单独上传) */}
              {!editingIssueId && (
                <Form.Item label="审核发现证据 (可选, 支持图片)">
                  <div onPaste={(e) => handlePasteEvidence(null, e)}>
                  <Upload
                    listType="picture-card"
                    multiple
                    fileList={pendingFiles.map((item) => ({
                      uid: item.id,
                      name: item.file.name,
                      status: 'done' as const,
                      originFileObj: item.file,
                    })) as never}
                    beforeUpload={(file) => {
                      // 通过选择文件按钮添加: 同样分配唯一 id
                      const id = `pick-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
                      setPendingFiles((prev) => [...prev, { id, file }]);
                      return false;
                    }}
                    onRemove={(file) => {
                      // 按 uid (即 pendingFiles 中的 id) 精确删除单张图片
                      setPendingFiles((prev) => prev.filter((item) => item.id !== file.uid));
                    }}
                    accept="image/*"
                  >
                    <div>
                      <UploadOutlined />
                      <div style={{ marginTop: 4, fontSize: 11 }}>添加图片</div>
                    </div>
                  </Upload>
                  {pendingFiles.length === 0 && (
                    <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                      可点击添加或在此区域直接粘贴图片 (Ctrl+V)
                    </div>
                  )}
                  </div>
                  {pendingFiles.length > 0 && (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      已选择 {pendingFiles.length} 个证据文件, 将在问题登记后自动上传
                    </Text>
                  )}
                </Form.Item>
              )}

              {/* 编辑模式下: 允许追加审核证据 (直接上传到当前编辑的问题) */}
              {editingIssueId && (
                <Form.Item label="追加审核证据 (可选, 粘贴或点击直接上传到当前问题)">
                  <div onPaste={(e) => handlePasteEvidence(editingIssueId, e)}>
                  <Upload
                    listType="picture-card"
                    multiple
                    showUploadList={false}
                    beforeUpload={(file) => {
                      handleUploadEvidence(editingIssueId, file as File);
                      return false; // 阻止 antd Upload 默认上传
                    }}
                    accept="image/*"
                  >
                    <div>
                      <UploadOutlined />
                      <div style={{ marginTop: 4, fontSize: 11 }}>添加图片</div>
                    </div>
                  </Upload>
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                    可点击添加或在此区域直接粘贴图片 (Ctrl+V), 上传后立即保存到当前问题
                  </div>
                  </div>
                </Form.Item>
              )}

              <div style={{ textAlign: 'right' }}>
                <Space>
                  <Button onClick={() => {
                    setEditingIssueId(null);
                    issueForm.resetFields();
                    issueForm.setFieldsValue({
                      Severity: 'M' as IssueSeverity,
                      OwnerName: projectInfo?.ownerName || '',
                    });
                  }}>
                    取消编辑
                  </Button>
                  <Button
                    type="primary"
                    loading={issueSubmitting}
                    onClick={handleIssueSubmit}
                    icon={<PlusOutlined />}
                  >
                    {editingIssueId ? '更新问题' : '登记问题'}
                  </Button>
                </Space>
              </div>
            </Form>
          </>
        )}
      </Modal>
    </div>
  );
}

// 锁图标 (内联 SVG, 避免 import 整个图标库)
function LockIcon() {
  return (
    <span style={{ display: 'inline-flex', verticalAlign: 'middle' }}>
      <svg width="11" height="11" viewBox="0 0 1024 1024" fill="currentColor">
        <path d="M832 464h-68V240c0-70.7-57.3-128-128-128H388c-70.7 0-128 57.3-128 128v224h-68c-17.7 0-32 14.3-32 32v384c0 17.7 14.3 32 32 32h640c17.7 0 32-14.3 32-32V496c0-17.7-14.3-32-32-32zM332 240c0-30.9 25.1-56 56-56h248c30.9 0 56 25.1 56 56v224H332V240zm436 608H256V528h512v320z" />
      </svg>
    </span>
  );
}
