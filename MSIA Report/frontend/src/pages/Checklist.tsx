import { useEffect, useState, useMemo, useCallback, type CSSProperties } from 'react';
import {
  Card,
  Table,
  Tag,
  Space,
  Button,
  Input,
  Typography,
  Drawer,
  Empty,
  Tooltip,
  Statistic,
  Row,
  Col,
  Segmented,
  Divider,
  Modal,
  Form,
  Select,
  Switch,
  InputNumber,
  App,
  Popconfirm,
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  KeyOutlined,
  FileTextOutlined,
  AuditOutlined,
  SafetyCertificateOutlined,
  EyeOutlined,
  ClusterOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckItem,
  ScoreOption,
  CheckItemPayload,
  getCheckItems,
  createCheckItem,
  updateCheckItem,
  deleteCheckItem,
  toggleCheckItemActive,
  parseScoreOptions,
} from '@/api/checkItems';
import { useAuthStore } from '@/store/auth';
import { formatDate } from '@/utils/format';
import {
  MATURITY_LEVELS as _ML,
  scoreColor as _sc,
  scoreBg as _sb,
  scoreTagTextColor as _sttc,
  SCORE_LABEL_MAP as _SLM,
  scoreTextColor as _stc,
} from '@/utils/scoreColor';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// ============ 阶段定义 ============
interface PhaseMeta {
  code: string;
  label: string;
  short: string;
  color: string;
  bg: string;
  border: string;
  desc: string;
}

const PHASES: PhaseMeta[] = [
  { code: 'MSIA1', label: '启动阶段', short: 'M1', color: '#8c8c8c', bg: '#f5f5f5', border: '#d9d9d9', desc: 'Project Kick-off' },
  { code: 'MSIA2', label: '规划与设计', short: 'M2', color: '#2E5CE6', bg: '#e6f7ff', border: '#91d5ff', desc: 'Planning & Design' },
  { code: 'MSIA3', label: '设计冻结', short: 'M3', color: '#0FB5BA', bg: '#e6fffb', border: '#87e8de', desc: 'Design Freeze' },
  { code: 'MSIA4', label: '预验收', short: 'M4', color: '#F97316', bg: '#fff7e6', border: '#ffd591', desc: 'Pre-Acceptance' },
  { code: 'MSIA5', label: '终验收', short: 'M5', color: '#10B981', bg: '#f6ffed', border: '#b7eb8f', desc: 'Final Acceptance' },
];

const phaseMap: Record<string, PhaseMeta> = Object.fromEntries(
  PHASES.map((p) => [p.code, p])
);

// ============ 7 档 Maturity 评分定义 (使用全局统一色调) ============
const MATURITY_LEVELS = _ML;

// 默认 7 档评分选项 (新建时使用)
const DEFAULT_SCORE_OPTIONS: ScoreOption[] = MATURITY_LEVELS.map((l) => ({
  score: l.score,
  label: l.label,
  desc: '',
}));

// 评审角色选项
const REVIEWER_ROLE_OPTIONS = [
  { label: '首席评审', value: 'lead_reviewer' },
  { label: '评审', value: 'reviewer' },
  { label: '被评审', value: 'reviewee' },
];

// 评审角色紧凑展示标签 (未映射的角色原样展示, 如 CoE / IE)
const ROLE_LABELS: Record<string, string> = {
  lead_reviewer: '首席评审',
  reviewer: '评审',
  reviewee: '被评审',
};

const scoreColor = _sc;
const scoreBg = _sb;
const scoreTagTextColor = _sttc;
const SCORE_LABEL_MAP = _SLM;
const scoreTextColor = _stc;

// Maturity 矩阵单列宽度 (横向 7 档)
const MATURITY_COL_W = 172;

function extractEvidence(remarks?: string | null): { remarks: string; evidence: string } {
  if (!remarks) return { remarks: '', evidence: '' };
  const idx = remarks.indexOf('Evidence:');
  if (idx === -1) return { remarks, evidence: '' };
  return {
    remarks: remarks.substring(0, idx).trim(),
    evidence: remarks.substring(idx + 'Evidence:'.length).trim(),
  };
}

// 阶段徽章
function PhaseBadge({ code, size = 'default' }: { code: string; size?: 'default' | 'small' }) {
  const meta = phaseMap[code];
  if (!meta) return <Tag>{code}</Tag>;
  const s = size === 'small' ? { w: 28, h: 20, fs: 10 } : { w: 36, h: 24, fs: 11 };
  return (
    <Tooltip title={`${code} · ${meta.label} (${meta.desc})`}>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: s.w,
          height: s.h,
          backgroundColor: meta.color,
          color: '#fff',
          fontSize: s.fs,
          fontWeight: 700,
          fontFamily: NUM_FONT,
          letterSpacing: 0.5,
          borderRadius: 2,
          boxShadow: `0 1px 2px ${meta.color}55`,
        }}
      >
        {meta.short}
      </div>
    </Tooltip>
  );
}

// ============ Maturity 横向矩阵工具 ============
// hex 转 rgba (用于档位浅色渐变)
function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// 档位浅色底 (纯黄 #FFFF00 视觉偏浅, 同等透明度不明显, 需加倍)
function levelTint(color: string, alpha: number): string {
  const a = color.toUpperCase() === '#FFFF00' ? Math.min(alpha * 2, 0.3) : alpha;
  return hexToRgba(color, a);
}

// 矩阵单元格: 完整换行展示评分标准 (Excel 式); 无描述档位画斜线阴影置灰 (N/A)
function MatrixCell({ desc, focused, color }: { desc?: string; focused: boolean; color: string }) {
  if (!desc) {
    return (
      <>
        <div className="msia-na-spacer" />
        <div
          className="msia-na-cell"
          title="不适用 (N/A)"
          style={focused ? { backgroundColor: levelTint(color, 0.08) } : undefined}
        />
      </>
    );
  }
  return (
    <div
      className={focused ? 'msia-matrix-cell msia-matrix-cell-focused' : 'msia-matrix-cell'}
      style={focused ? { backgroundColor: levelTint(color, 0.08), boxShadow: `inset 3px 0 0 0 ${color}` } : undefined}
    >
      {desc}
    </div>
  );
}

// ============ 7 档评分标准编辑器 ============
function ScoreOptionsEditor({ value, onChange }: { value: ScoreOption[]; onChange: (v: ScoreOption[]) => void }) {
  const updateDesc = (score: number, desc: string) => {
    const next = MATURITY_LEVELS.map((level) => {
      const isTarget = level.score === score;
      const existing = value.find((o) => o.score === level.score);
      return {
        score: level.score,
        label: level.label,
        desc: isTarget ? desc : (existing?.desc || ''),
      };
    });
    onChange(next);
  };

  // 确保至少有 7 档
  const options = useMemo(() => {
    return MATURITY_LEVELS.map((level) => {
      const existing = value.find((o) => o.score === level.score);
      return {
        score: level.score,
        label: level.label,
        desc: existing?.desc || '',
      };
    });
  }, [value]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {options.map((opt) => {
        const c = scoreColor(opt.score);
        const bg = scoreBg(opt.score);
        return (
          <div
            key={opt.score}
            style={{
              display: 'flex',
              alignItems: 'stretch',
              borderRadius: 4,
              overflow: 'hidden',
              border: `1px solid ${c}33`,
              backgroundColor: bg,
            }}
          >
            {/* 分数徽章 */}
            <div
              style={{
                minWidth: 80,
                padding: '8px 10px',
                backgroundColor: c,
                color: scoreTagTextColor(opt.score),
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                flexShrink: 0,
              }}
            >
              <Text
                strong
                style={{
                  color: scoreTagTextColor(opt.score),
                  fontSize: 15,
                  fontFamily: NUM_FONT,
                  lineHeight: 1,
                }}
              >
                {opt.label}
              </Text>
              <Text style={{ color: scoreTagTextColor(opt.score) === '#fff' ? '#ffffffaa' : '#1F2937aa', fontSize: 8, letterSpacing: 0.5 }}>
                MATURITY
              </Text>
            </div>
            {/* 描述输入 */}
            <div style={{ flex: 1, padding: '4px 8px', display: 'flex', alignItems: 'center' }}>
              <TextArea
                value={opt.desc}
                onChange={(e) => updateDesc(opt.score, e.target.value)}
                placeholder="输入该档位的评分标准描述..."
                autoSize={{ minRows: 1, maxRows: 3 }}
                style={{
                  fontSize: 12,
                  border: 'none',
                  backgroundColor: 'transparent',
                  boxShadow: 'none',
                  padding: '2px 0',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ============ 主页面 ============
export default function Checklist() {
  const { message } = App.useApp();
  const user = useAuthStore((state) => state.user);
  const isAdmin = user?.Role === 'admin';

  const [data, setData] = useState<CheckItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [phaseFilter, setPhaseFilter] = useState<string>('all');
  const [keyword, setKeyword] = useState('');
  const [keyOnly, setKeyOnly] = useState(false);
  // 对照档位: 选中后矩阵中该档位列轻微高亮, 便于评审时横向对照 (纯展示, 不打分)
  const [focusLevel, setFocusLevel] = useState<number | null>(null);

  // 详情抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [current, setCurrent] = useState<CheckItem | null>(null);

  // 编辑弹窗
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<CheckItem | null>(null);
  const [editForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [scoreOptions, setScoreOptions] = useState<ScoreOption[]>(DEFAULT_SCORE_OPTIONS);

  // 加载检查项
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getCheckItems();
      setData(list || []);
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 过滤数据
  const filteredData = useMemo(() => {
    let list = data;
    if (phaseFilter !== 'all') {
      list = list.filter((it) => it.PhaseCode === phaseFilter);
    }
    if (keyOnly) {
      list = list.filter((it) => it.IsKeyItem);
    }
    if (keyword.trim()) {
      const kw = keyword.toLowerCase();
      list = list.filter(
        (it) =>
          it.Name.toLowerCase().includes(kw) ||
          it.ItemNo.toLowerCase().includes(kw) ||
          (it.ScoreOptions || '').toLowerCase().includes(kw)
      );
    }
    return list;
  }, [data, phaseFilter, keyOnly, keyword]);

  // 预解析各检查项的评分选项 (避免矩阵 7 列单元格重复 JSON.parse)
  const optionsMap = useMemo(() => {
    const m = new Map<number, ScoreOption[]>();
    data.forEach((d) => m.set(d.Id, parseScoreOptions(d.ScoreOptions)));
    return m;
  }, [data]);

  // 统计
  const stats = useMemo(() => {
    const total = data.length;
    const keyCount = data.filter((it) => it.IsKeyItem).length;
    const byPhase: Record<string, number> = {};
    data.forEach((it) => {
      byPhase[it.PhaseCode] = (byPhase[it.PhaseCode] || 0) + 1;
    });
    return { total, keyCount, byPhase };
  }, [data]);

  // 打开详情抽屉
  const openDetail = (item: CheckItem) => {
    setCurrent(item);
    setDrawerOpen(true);
  };

  // 打开编辑弹窗 (新建或编辑)
  const openEdit = (item: CheckItem | null) => {
    setEditingItem(item);
    if (item) {
      const opts = parseScoreOptions(item.ScoreOptions);
      setScoreOptions(opts.length > 0 ? opts : DEFAULT_SCORE_OPTIONS);
      editForm.setFieldsValue({
        PhaseCode: item.PhaseCode,
        ItemNo: item.ItemNo,
        Name: item.Name,
        Request: item.Request || '',
        RequestDescription: item.RequestDescription || '',
        IsKeyItem: item.IsKeyItem,
        ReviewerRoles: item.ReviewerRoles ? item.ReviewerRoles.split(',').map((r) => r.trim()) : [],
        ReferenceDocuments: item.ReferenceDocuments || '',
        ScoreScaleType: item.ScoreScaleType || '7-step',
        DefaultResultText: item.DefaultResultText || '',
        Remarks: item.Remarks || '',
      });
    } else {
      editForm.resetFields();
      setScoreOptions(DEFAULT_SCORE_OPTIONS);
      editForm.setFieldsValue({
        PhaseCode: phaseFilter !== 'all' ? phaseFilter : 'MSIA1',
        IsKeyItem: false,
        ScoreScaleType: '7-step',
        ReviewerRoles: ['lead_reviewer', 'reviewer'],
      });
    }
    setEditModalOpen(true);
  };

  // 提交新建/编辑
  const handleSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      setSubmitting(true);
      const payload: CheckItemPayload = {
        PhaseCode: values.PhaseCode,
        ItemNo: values.ItemNo,
        Name: values.Name,
        Request: values.Request?.trim() || null,
        RequestDescription: values.RequestDescription?.trim() || null,
        IsKeyItem: values.IsKeyItem,
        ReviewerRoles: Array.isArray(values.ReviewerRoles) && values.ReviewerRoles.length > 0
          ? values.ReviewerRoles.join(',')
          : null,
        ReferenceDocuments: values.ReferenceDocuments?.trim() || null,
        ScoreScaleType: values.ScoreScaleType || '7-step',
        ScoreOptions: scoreOptions,
        DefaultResultText: values.DefaultResultText?.trim() || null,
        Remarks: values.Remarks?.trim() || null,
      };
      if (editingItem) {
        await updateCheckItem(editingItem.Id, payload);
        message.success('检查项已更新');
      } else {
        await createCheckItem(payload);
        message.success('检查项已创建');
      }
      setEditModalOpen(false);
      fetchData();
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  // 删除
  const handleDelete = async (item: CheckItem) => {
    try {
      await deleteCheckItem(item.Id);
      message.success('检查项已删除');
      fetchData();
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    }
  };

  // 启用/停用审核条款 (停用后不进入项目评审打分场景)
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const handleToggleActive = async (item: CheckItem, nextActive: boolean) => {
    setTogglingId(item.Id);
    try {
      await toggleCheckItemActive(item.Id, nextActive);
      // 局部更新, 避免全表刷新抖动
      setData((prev) =>
        prev.map((it) => (it.Id === item.Id ? { ...it, IsActive: nextActive } : it)),
      );
      message.success(nextActive ? '已启用该审核条款' : '已停用该审核条款 (项目评审打分场景将不再显示)');
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setTogglingId(null);
    }
  };

  // Maturity 矩阵列: 0% ~ 100% 横向展开 (行=检查项, 列=档位, 还原 Excel 横向矩阵)
  const matrixColumns: ColumnsType<CheckItem> = useMemo(() => {
    return MATURITY_LEVELS.map((level) => {
      const focused = focusLevel === level.score;
      const meta = SCORE_LABEL_MAP[level.score];
      return {
        key: `mat-${level.score}`,
        title: (
          <div style={{ textAlign: 'center', lineHeight: 1.25 }}>
            <div style={{ fontFamily: NUM_FONT, fontWeight: 700, fontSize: 12, color: scoreTextColor(level.score) }}>
              {level.label}
            </div>
            <div style={{ fontSize: 9, color: '#8c8c8c', marginTop: 1 }}>
              {meta?.title || ''}
            </div>
          </div>
        ),
        width: MATURITY_COL_W,
        onHeaderCell: () => ({
          className: 'msia-mat-head',
          style: {
            '--mat-tint': levelTint(level.color, focused ? 0.12 : 0.05),
            '--mat-accent': focused ? level.color : hexToRgba(level.color, 0.35),
          } as CSSProperties,
        }),
        onCell: () => ({ className: 'msia-mat-td' }),
        render: (_: unknown, record: CheckItem) => {
          const opt = optionsMap.get(record.Id)?.find((o) => o.score === level.score);
          const desc = opt?.desc?.trim();
          return <MatrixCell desc={desc} focused={focused} color={level.color} />;
        },
      };
    });
  }, [focusLevel, optionsMap]);

  // 表格横向总宽 (固定列 + 7 档矩阵 + 右侧紧凑区)
  const tableScrollX = 56 + 54 + 190 + MATURITY_COL_W * 7 + 88 + 72 + (isAdmin ? 100 : 38);

  // 表格列定义
  const columns: ColumnsType<CheckItem> = [
    {
      title: (
        <span style={{ fontFamily: NUM_FONT, fontWeight: 700 }}>
          NO.
        </span>
      ),
      dataIndex: 'ItemNo',
      key: 'ItemNo',
      width: 56,
      fixed: 'left',
      render: (v: string) => (
        <Text
          strong
          style={{
            fontFamily: NUM_FONT,
            fontSize: 11,
            color: '#2E5CE6',
            letterSpacing: 0.3,
          }}
        >
          {v}
        </Text>
      ),
    },
    {
      title: '阶段',
      dataIndex: 'PhaseCode',
      key: 'PhaseCode',
      width: 54,
      fixed: 'left',
      render: (v: string) => <PhaseBadge code={v} size="small" />,
    },
    {
      title: '检查项',
      dataIndex: 'Name',
      key: 'Name',
      width: 190,
      render: (v: string, record) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Text strong style={{ fontSize: 12, lineHeight: 1.35 }}>
            {v}
          </Text>
          {record.IsKeyItem && (
            <Tag
              color="red"
              icon={<KeyOutlined />}
              style={{ fontSize: 9, margin: 0, width: 'fit-content', padding: '0 4px', lineHeight: '14px', height: 14 }}
            >
              KEY
            </Tag>
          )}
        </div>
      ),
    },
    {
      title: (
        <Tooltip title="Maturity 7 档评分标准横向矩阵 (行=检查项, 列=档位), 单元格文本完整换行展示, 斜线阴影=不适用">
          <span style={{ fontFamily: NUM_FONT, fontWeight: 700, fontSize: 11, letterSpacing: 0.5 }}>
            MATURITY 评分标准
          </span>
        </Tooltip>
      ),
      key: 'maturity-matrix',
      children: matrixColumns,
      onHeaderCell: () => ({ className: 'msia-mat-group-head' }),
    },
    {
      title: '评审角色',
      dataIndex: 'ReviewerRoles',
      key: 'ReviewerRoles',
      width: 88,
      render: (v: string) => {
        if (!v) return <Text type="secondary" style={{ fontSize: 11 }}>—</Text>;
        const roles = v.split(',').map((r) => r.trim()).filter(Boolean);
        return (
          <Space size={2} wrap>
            {roles.map((r, i) => (
              <Tag
                key={i}
                style={{
                  fontSize: 9,
                  margin: 0,
                  padding: '0 4px',
                  lineHeight: '14px',
                  height: 14,
                  fontFamily: NUM_FONT,
                  border: '1px solid rgba(46, 92, 230, 0.15)',
                  backgroundColor: 'rgba(46, 92, 230, 0.04)',
                  color: '#2E5CE6',
                }}
              >
                {ROLE_LABELS[r] || r}
              </Tag>
            ))}
          </Space>
        );
      },
    },
    {
      title: (
        <Tooltip title="停用后该条款不进入项目评审打分场景 (审核标准模块中仍保留)">
          <span style={{ fontFamily: NUM_FONT, fontWeight: 700, fontSize: 11 }}>
            启用
          </span>
        </Tooltip>
      ),
      key: 'IsActive',
      width: 72,
      align: 'center',
      render: (_, record) => {
        // 默认视为启用 (老数据 IsActive 为 undefined 时视为 true)
        const active = record.IsActive !== false;
        if (!isAdmin) {
          return (
            <Tag
              color={active ? 'success' : 'default'}
              style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}
            >
              {active ? '启用' : '停用'}
            </Tag>
          );
        }
        return (
          <Tooltip
            title={
              active
                ? '当前: 启用 — 项目评审打分场景会显示该条款'
                : '当前: 停用 — 项目评审打分场景将不再显示该条款, 不进行评审'
            }
          >
            <Switch
              size="small"
              checked={active}
              loading={togglingId === record.Id}
              onChange={(checked, e) => {
                e.stopPropagation();
                handleToggleActive(record, checked);
              }}
              onClick={(_, e) => e.stopPropagation()}
            />
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: isAdmin ? 100 : 38,
      fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={(e) => { e.stopPropagation(); openDetail(record); }}
            style={{ color: '#2E5CE6' }}
          />
          {isAdmin && (
            <>
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={(e) => { e.stopPropagation(); openEdit(record); }}
                style={{ color: '#F59E0B' }}
              />
              <Popconfirm
                title="确认删除"
                description="删除后不可恢复, 确定要删除该检查项吗?"
                onConfirm={(e) => { e?.stopPropagation(); handleDelete(record); }}
                onCancel={(e) => e?.stopPropagation()}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                  style={{ color: '#EF4444' }}
                />
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ];

  // 当前检查项的评分选项
  const currentOptions = useMemo<ScoreOption[]>(() => {
    if (!current) return [];
    return parseScoreOptions(current.ScoreOptions);
  }, [current]);

  const currentEvidence = useMemo(() => {
    return extractEvidence(current?.Remarks);
  }, [current]);

  return (
    <div>
      <style>{`
        .msia-checklist-grid-bg {
          background-image:
            linear-gradient(rgba(46, 92, 230, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(46, 92, 230, 0.04) 1px, transparent 1px);
          background-size: 20px 20px;
        }
        .msia-checklist-table .ant-table-thead > tr > th {
          background: linear-gradient(180deg, rgba(46, 92, 230, 0.02) 0%, rgba(46, 92, 230, 0.04) 100%) !important;
          border-bottom: 2px solid rgba(46, 92, 230, 0.15) !important;
          font-weight: 700 !important;
          padding: 8px 8px !important;
        }
        .msia-checklist-table .ant-table-tbody > tr:hover > td {
          background: rgba(46, 92, 230, 0.02) !important;
        }
        .msia-checklist-table .ant-table-tbody > tr > td {
          border-bottom: 1px solid rgba(46, 92, 230, 0.10) !important;
          padding: 6px 8px !important;
          vertical-align: top !important;
        }
        .msia-checklist-table .ant-table-tbody > tr.ant-table-row {
          height: auto !important;
        }
        .msia-score-step {
          transition: all 0.3s;
        }
        .msia-score-step:hover {
          transform: translateX(4px);
          box-shadow: 0 2px 8px rgba(0,0,0,0.12);
        }
        /* ===== Maturity 横向矩阵 (Excel 式字典) ===== */
        .msia-checklist-table .ant-table-tbody > tr > td.msia-mat-td {
          position: relative;
          padding: 6px 7px !important;
          border-left: 1px solid rgba(46, 92, 230, 0.08) !important;
        }
        .msia-matrix-cell {
          font-size: 12px;
          line-height: 1.6;
          color: #4B5563;
          white-space: normal;
          word-break: break-word;
          overflow-wrap: anywhere;
          min-height: 22px;
          transition: background-color 0.2s, box-shadow 0.2s;
        }
        .msia-matrix-cell-focused {
          margin: -2px -7px;
          padding: 2px 7px;
          border-radius: 3px;
        }
        .msia-na-spacer {
          min-height: 36px;
        }
        .msia-na-cell {
          position: absolute;
          top: 5px;
          left: 5px;
          right: 5px;
          bottom: 5px;
          border-radius: 3px;
          background-color: #fafafa;
          background-image: repeating-linear-gradient(45deg, transparent 0, transparent 5px, rgba(31, 41, 55, 0.06) 5px, rgba(31, 41, 55, 0.06) 10px);
        }
        .msia-checklist-table .ant-table-thead > tr > th.msia-mat-head {
          background: var(--mat-tint, #fafafa) !important;
          border-top: 3px solid var(--mat-accent, transparent) !important;
          border-left: 1px solid rgba(46, 92, 230, 0.12) !important;
          padding-top: 4px !important;
        }
        .msia-checklist-table .ant-table-thead > tr > th.msia-mat-group-head {
          border-left: 1px solid rgba(46, 92, 230, 0.12) !important;
        }
        .msia-na-legend {
          display: inline-block;
          width: 20px;
          height: 11px;
          border-radius: 2px;
          border: 1px solid #e8e8e8;
          background-color: #fafafa;
          background-image: repeating-linear-gradient(45deg, transparent 0, transparent 4px, rgba(31, 41, 55, 0.09) 4px, rgba(31, 41, 55, 0.09) 8px);
        }
      `}</style>

      {/* ============ 顶部统计仪表盘 ============ */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            className="msia-checklist-grid-bg tech-card-hover"
            style={{ borderTop: '3px solid #2E5CE6', position: 'relative', overflow: 'hidden' }}
          >
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>TOTAL ITEMS</Text>}
              value={stats.total}
              prefix={<FileTextOutlined style={{ color: '#2E5CE6' }} />}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            className="msia-checklist-grid-bg tech-card-hover"
            style={{ borderTop: '3px solid #cf1322', position: 'relative', overflow: 'hidden' }}
          >
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>KEY ITEMS</Text>}
              value={stats.keyCount}
              suffix={<Text type="secondary" style={{ fontSize: 11 }}>/ {stats.total}</Text>}
              valueStyle={{ color: '#cf1322', fontFamily: NUM_FONT, fontWeight: 700 }}
              prefix={<KeyOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            className="msia-checklist-grid-bg tech-card-hover"
            style={{ borderTop: '3px solid #0FB5BA', position: 'relative', overflow: 'hidden' }}
          >
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>SCORE SCALE</Text>}
              value="7-step"
              suffix={<Text type="secondary" style={{ fontSize: 10 }}> Maturity</Text>}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#0FB5BA' }}
              prefix={<AuditOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card
            size="small"
            className="msia-checklist-grid-bg tech-card-hover"
            style={{ borderTop: '3px solid #14B8A6', position: 'relative', overflow: 'hidden' }}
          >
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>PHASES</Text>}
              value={Object.keys(stats.byPhase).length}
              suffix={<Text type="secondary" style={{ fontSize: 11 }}> MSIA</Text>}
              valueStyle={{ fontFamily: NUM_FONT, fontWeight: 700, color: '#14B8A6' }}
              prefix={<ClusterOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* ============ 阶段分布卡片 ============ */}
      <Card size="small" style={{ marginBottom: 16 }} styles={{ body: { padding: '12px 16px' } }}>
        <Space size={8} wrap>
          <Text type="secondary" strong style={{ fontSize: 11, letterSpacing: 1, marginRight: 4 }}>
            PHASE DISTRIBUTION:
          </Text>
          {PHASES.map((p) => {
            const count = stats.byPhase[p.code] || 0;
            const active = phaseFilter === p.code;
            return (
              <Tooltip key={p.code} title={`${p.code} · ${p.label} (${p.desc})`}>
                <div
                  onClick={() => setPhaseFilter(active ? 'all' : p.code)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '4px 10px',
                    borderRadius: 4,
                    cursor: 'pointer',
                    border: `1px solid ${active ? p.color : 'rgba(46, 92, 230, 0.08)'}`,
                    backgroundColor: active ? p.bg : 'rgba(255, 255, 255, 0.6)',
                    transition: 'all 0.2s',
                  }}
                >
                  <PhaseBadge code={p.code} size="small" />
                  <Text
                    strong
                    style={{
                      fontSize: 12,
                      fontFamily: NUM_FONT,
                      color: active ? p.color : '#595959',
                    }}
                  >
                    {count}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 10 }}>项</Text>
                </div>
              </Tooltip>
            );
          })}
        </Space>
      </Card>

      {/* ============ 主表格 ============ */}
      <Card
        title={
          <Space>
            <SafetyCertificateOutlined style={{ color: '#2E5CE6', fontSize: 18 }} />
            <Title level={5} style={{ margin: 0 }}>MSIA 审核标准库</Title>
            <Tag
              color="blue"
              style={{
                fontFamily: NUM_FONT,
                fontSize: 11,
              }}
            >
              {filteredData.length} / {stats.total}
            </Tag>
          </Space>
        }
        extra={
          <Space>
            {isAdmin && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => openEdit(null)}
              >
                新建检查项
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="搜索 编号 / 名称 / 评分描述"
            prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
            allowClear
            style={{ width: 320 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Segmented
            value={phaseFilter}
            onChange={(v) => setPhaseFilter(v as string)}
            options={[
              { value: 'all', label: '全部' },
              ...PHASES.map((p) => ({ value: p.code, label: p.short })),
            ]}
          />
          <Segmented
            value={keyOnly ? 'key' : 'all'}
            onChange={(v) => setKeyOnly(v === 'key')}
            options={[
              { value: 'all', label: '全部项' },
              { value: 'key', label: <span><KeyOutlined /> 关键项</span> },
            ]}
          />
          <Tooltip title="选中当前打分档位后, 矩阵中该档位列将轻微高亮, 便于横向对照各检查项在该成熟度阶段的标准 (纯展示, 不打分)">
            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>对照档位:</Text>
              <Segmented
                value={focusLevel == null ? 'none' : String(focusLevel)}
                onChange={(v) => setFocusLevel(v === 'none' ? null : Number(v))}
                options={[
                  { value: 'none', label: '不聚焦' },
                  ...MATURITY_LEVELS.map((l) => ({ value: String(l.score), label: l.label })),
                ]}
              />
            </Space>
          </Tooltip>
          <Text type="secondary" style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span className="msia-na-legend" />
            斜线阴影 = 不适用 (N/A)
          </Text>
        </Space>

        <div className="msia-checklist-table">
          <Table<CheckItem>
            rowKey="Id"
            columns={columns}
            dataSource={filteredData}
            loading={loading}
            scroll={{ x: tableScrollX, y: 600 }}
            onRow={(record) => ({
              onClick: () => openDetail(record),
              style: { cursor: 'pointer' },
            })}
            pagination={{
              pageSize: 25,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              pageSizeOptions: ['10', '25', '50', '100'],
            }}
            size="middle"
          />
        </div>
      </Card>

      {/* ============ 详情抽屉 ============ */}
      <Drawer
        title={
          current ? (
            <Space>
              <PhaseBadge code={current.PhaseCode} />
              <Text
                strong
                style={{
                  fontFamily: NUM_FONT,
                  fontSize: 14,
                  color: '#2E5CE6',
                }}
              >
                {current.ItemNo}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>·</Text>
              <Text strong style={{ fontSize: 14 }}>{current.Name}</Text>
              {current.IsKeyItem && (
                <Tag color="red" icon={<KeyOutlined />} style={{ fontSize: 10, margin: 0 }}>
                  KEY
                </Tag>
              )}
            </Space>
          ) : (
            '审核标准详情'
          )
        }
        placement="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={860}
        extra={
          isAdmin && current ? (
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={() => {
                setDrawerOpen(false);
                openEdit(current);
              }}
            >
              编辑
            </Button>
          ) : null
        }
      >
        {current && (
          <div>
            {/* 顶部信息卡 */}
            <Card
              size="small"
              className="msia-checklist-grid-bg"
              style={{ marginBottom: 16, borderTop: '3px solid #2E5CE6' }}
              styles={{ body: { padding: 12 } }}
            >
              <Row gutter={12}>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>PHASE</Text>
                  <div style={{ marginTop: 4 }}>
                    <PhaseBadge code={current.PhaseCode} />
                    <Text style={{ fontSize: 11, marginLeft: 6, color: '#595959' }}>
                      {phaseMap[current.PhaseCode]?.label || ''}
                    </Text>
                  </div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>SCORE SCALE</Text>
                  <div style={{ marginTop: 4 }}>
                    <Tag
                      style={{
                        fontFamily: NUM_FONT,
                        fontSize: 11,
                        margin: 0,
                        border: '1px solid rgba(46, 92, 230, 0.2)',
                        backgroundColor: 'rgba(46, 92, 230, 0.04)',
                        color: '#2E5CE6',
                      }}
                    >
                      {current.ScoreScaleType}
                    </Tag>
                  </div>
                </Col>
                <Col span={8}>
                  <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>VERSION</Text>
                  <div style={{ marginTop: 4 }}>
                    <Text
                      strong
                      style={{
                        fontFamily: NUM_FONT,
                        fontSize: 13,
                      }}
                    >
                      v{current.Version || 1}
                    </Text>
                  </div>
                </Col>
              </Row>
            </Card>

            {/* Maturity 评分矩阵 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <div style={{ width: 3, height: 16, background: 'linear-gradient(180deg, #2E5CE6 0%, #0FB5BA 100%)' }} />
                <AuditOutlined style={{ color: '#0FB5BA', fontSize: 14 }} />
                <Text strong style={{ fontSize: 13, letterSpacing: 1, color: '#0FB5BA' }}>
                  MATURITY SCORING CRITERIA
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>(7 档: 0% / 25% / 33% / 50% / 67% / 75% / 100%)</Text>
              </div>

              {currentOptions.length === 0 ? (
                <Empty description="无评分档位定义" />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {currentOptions.map((opt, idx) => {
                    const c = scoreColor(opt.score);
                    const bg = scoreBg(opt.score);
                    const hasDesc = !!opt.desc;
                    return (
                      <div
                        key={idx}
                        className="msia-score-step"
                        style={{
                          display: 'flex',
                          alignItems: 'stretch',
                          borderRadius: 6,
                          overflow: 'hidden',
                          border: `1px solid ${c}33`,
                          backgroundColor: bg,
                          opacity: hasDesc ? 1 : 0.6,
                        }}
                      >
                        <div
                          style={{
                            minWidth: 90,
                            padding: '10px 12px',
                            backgroundColor: c,
                            color: scoreTagTextColor(opt.score),
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 2,
                          }}
                        >
                          <Text
                            strong
                            style={{
                              color: scoreTagTextColor(opt.score),
                              fontSize: 16,
                              fontFamily: NUM_FONT,
                              lineHeight: 1,
                            }}
                          >
                            {opt.label}
                          </Text>
                          <Text
                            style={{
                              color: scoreTagTextColor(opt.score) === '#fff' ? '#ffffffaa' : '#1F2937aa',
                              fontSize: 9,
                              letterSpacing: 0.5,
                            }}
                          >
                            MATURITY
                          </Text>
                        </div>
                        <div
                          style={{
                            flex: 1,
                            padding: '10px 14px',
                            display: 'flex',
                            alignItems: 'center',
                          }}
                        >
                          {hasDesc ? (
                            <Text style={{ fontSize: 12, lineHeight: 1.6 }}>
                              {opt.desc}
                            </Text>
                          ) : (
                            <Text type="secondary" italic style={{ fontSize: 12 }}>
                              (未定义 - 空)
                            </Text>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 评审要求 */}
            {current.Request && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#2E5CE6' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#2E5CE6' }}>
                    REQUEST
                  </Text>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: 'rgba(46, 92, 230, 0.03)',
                    borderLeft: '3px solid #2E5CE6',
                    borderRadius: '0 4px 4px 0',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                    {current.Request}
                  </Paragraph>
                </div>
              </div>
            )}

            {/* 评审要求描述 */}
            {current.RequestDescription && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#0FB5BA' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#0FB5BA' }}>
                    REQUEST DESCRIPTION
                  </Text>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: 'rgba(15, 181, 186, 0.03)',
                    borderLeft: '3px solid #0FB5BA',
                    borderRadius: '0 4px 4px 0',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                    {current.RequestDescription}
                  </Paragraph>
                </div>
              </div>
            )}

            {/* 评审角色 */}
            {current.ReviewerRoles && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#F59E0B' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#F59E0B' }}>
                    REVIEWER ROLES
                  </Text>
                </div>
                <Space size={4} wrap>
                  {current.ReviewerRoles.split(',').filter(Boolean).map((r, i) => (
                    <Tag
                      key={i}
                      style={{
                        fontFamily: NUM_FONT,
                        fontSize: 11,
                        margin: 0,
                        padding: '2px 8px',
                        border: '1px solid rgba(250, 173, 20, 0.3)',
                        backgroundColor: 'rgba(250, 173, 20, 0.06)',
                        color: '#d46b08',
                      }}
                    >
                      {r.trim()}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}

            {/* 参考文件 */}
            {current.ReferenceDocuments && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#14B8A6' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#14B8A6' }}>
                    REFERENCE DOCUMENTS
                  </Text>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: 'rgba(54, 207, 201, 0.04)',
                    borderLeft: '3px solid #14B8A6',
                    borderRadius: '0 4px 4px 0',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                    {current.ReferenceDocuments}
                  </Paragraph>
                </div>
              </div>
            )}

            {/* 证据 */}
            {currentEvidence.evidence && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#2E5CE6' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#2E5CE6' }}>
                    EVIDENCES
                  </Text>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: 'rgba(46, 92, 230, 0.03)',
                    borderLeft: '3px solid #2E5CE6',
                    borderRadius: '0 4px 4px 0',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                    {currentEvidence.evidence}
                  </Paragraph>
                </div>
              </div>
            )}

            {/* 备注 */}
            {currentEvidence.remarks && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={{ width: 3, height: 14, backgroundColor: '#8B5CF6' }} />
                  <Text strong style={{ fontSize: 12, letterSpacing: 1, color: '#8B5CF6' }}>
                    REMARKS
                  </Text>
                </div>
                <div
                  style={{
                    padding: '10px 14px',
                    backgroundColor: '#f9f0ff',
                    borderLeft: '3px solid #8B5CF6',
                    borderRadius: '0 4px 4px 0',
                  }}
                >
                  <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 13 }}>
                    {currentEvidence.remarks}
                  </Paragraph>
                </div>
              </div>
            )}

            {/* 底部元信息 */}
            <Divider style={{ margin: '20px 0 12px' }} />
            <Row gutter={16}>
              <Col span={12}>
                <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>
                  CREATED
                </Text>
                <div>
                  <Text style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
                    {formatDate(current.CreatedAt) || '—'}
                  </Text>
                </div>
              </Col>
              <Col span={12}>
                <Text type="secondary" style={{ fontSize: 10, letterSpacing: 1 }}>
                  UPDATED
                </Text>
                <div>
                  <Text style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
                    {formatDate(current.UpdatedAt) || '—'}
                  </Text>
                </div>
              </Col>
            </Row>
          </div>
        )}
      </Drawer>

      {/* ============ 新建/编辑弹窗 ============ */}
      <Modal
        title={
          <Space>
            {editingItem ? <EditOutlined style={{ color: '#2E5CE6' }} /> : <PlusOutlined style={{ color: '#2E5CE6' }} />}
            <span>{editingItem ? '编辑检查项' : '新建检查项'}</span>
            {editingItem && (
              <Tag style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
                ID: {editingItem.Id}
              </Tag>
            )}
          </Space>
        }
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={editingItem ? '保存' : '创建'}
        cancelText="取消"
        width={780}
        forceRender
      >
        <Form
          form={editForm}
          layout="vertical"
          requiredMark="optional"
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label="MSIA 阶段"
                name="PhaseCode"
                rules={[{ required: true, message: '请选择阶段' }]}
              >
                <Select
                  options={PHASES.map((p) => ({
                    label: `${p.code} · ${p.label}`,
                    value: p.code,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="条目编号"
                name="ItemNo"
                rules={[{ required: true, message: '请输入条目编号' }]}
                tooltip="如 MSIA1-01, MSIA2-03 等"
              >
                <Input placeholder="如 MSIA1-01" style={{ fontFamily: NUM_FONT }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="评分类型"
                name="ScoreScaleType"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { label: '7-step Maturity (7档成熟度)', value: '7-step' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="检查项名称"
            name="Name"
            rules={[{ required: true, message: '请输入检查项名称' }]}
          >
            <Input placeholder="如: 项目启动会议是否已完成" />
          </Form.Item>

          <Form.Item label="评审要求" name="Request">
            <TextArea
              placeholder="该检查项的评审要求描述..."
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
          </Form.Item>

          <Form.Item label="评审要求详细说明" name="RequestDescription">
            <TextArea
              placeholder="对评审要求的详细补充说明..."
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="是否关键项" name="IsKeyItem" valuePropName="checked">
                <Switch
                  checkedChildren="是 (KEY)"
                  unCheckedChildren="否"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="评审角色" name="ReviewerRoles">
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="选择可评审该项目的角色"
                  options={REVIEWER_ROLE_OPTIONS}
                />
              </Form.Item>
            </Col>
          </Row>

          {/* ============ 7 档评分标准编辑器 ============ */}
          <Form.Item label="Maturity 评分标准 (7 档)">
            <div style={{
              padding: '12px',
              borderRadius: 6,
              border: '1px solid rgba(46, 92, 230, 0.1)',
              backgroundColor: 'rgba(46, 92, 230, 0.02)',
            }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 10,
              }}>
                <AuditOutlined style={{ color: '#0FB5BA', fontSize: 14 }} />
                <Text strong style={{ fontSize: 12, letterSpacing: 0.5, color: '#0FB5BA' }}>
                  MATURITY SCORING CRITERIA
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  为每个档位填写评分标准描述
                </Text>
              </div>
              <ScoreOptionsEditor value={scoreOptions} onChange={setScoreOptions} />
            </div>
          </Form.Item>

          <Form.Item label="参考文件" name="ReferenceDocuments">
            <TextArea
              placeholder="参考的标准文件、规范等..."
              autoSize={{ minRows: 1, maxRows: 3 }}
            />
          </Form.Item>

          <Form.Item label="默认评审结果文本" name="DefaultResultText">
            <Input placeholder="如: Pass / Fail / N/A" />
          </Form.Item>

          <Form.Item
            label="备注"
            name="Remarks"
            tooltip="可包含 Evidence: 开头的证据说明"
          >
            <TextArea
              placeholder="备注信息..."
              autoSize={{ minRows: 1, maxRows: 3 }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
