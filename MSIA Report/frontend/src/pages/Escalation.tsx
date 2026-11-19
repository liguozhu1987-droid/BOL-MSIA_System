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
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Row,
  Col,
  Statistic,
  Tabs,
  Badge,
  Popconfirm,
  Alert,
  Descriptions,
  Timeline,
} from 'antd';
import type { InputNumberProps } from 'antd';
import {
  ThunderboltOutlined,
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  MailOutlined,
  ClockCircleOutlined,
  ArrowUpOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  SafetyCertificateOutlined,
  ApartmentOutlined,
  ExperimentOutlined,
  CopyOutlined,
  CrownOutlined,
  LockOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';

import {
  listEscalationConfigsApi,
  createEscalationConfigApi,
  updateEscalationConfigApi,
  deleteEscalationConfigApi,
  toggleEscalationConfigApi,
  listEscalationLogsApi,
  getEscalationLogStatsApi,
  getEscalationLogFiltersApi,
  triggerEscalationScanApi,
  sendTestEmailApi,
  listUserOptionsApi,
  PLANT_OPTIONS,
  getPlantDisplayName,
  type EscalationConfig,
  type EscalationConfigCreatePayload,
  type EscalationLog,
  type EscalationLogStats,
  type EscalationLogFilters,
  type TestEmailResponse,
  type UserOption,
} from '@/api/escalation';
import type { PageResponse } from '@/api/issues';
import { useAuthStore } from '@/store/auth';
import { formatDateTime } from '@/utils/format';
import { BRAND, techCardStyle, industrialBgStyle, CornerMarker } from '@/styles/shared';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// 小时数输入框 (Space.Compact + 后缀 "h", 替代已弃用的 InputNumber addonAfter)
function HoursInputNumber({ max }: { max?: InputNumberProps['max'] }) {
  return (
    <Space.Compact style={{ width: '100%' }}>
      <InputNumber min={1} max={max} style={{ width: '100%' }} />
      <Button style={{ pointerEvents: 'none', minWidth: 36 }} disabled>
        h
      </Button>
    </Space.Compact>
  );
}

// 严重等级元数据
const SEVERITY_META: Record<string, { color: string; text: string; desc: string }> = {
  H: { color: 'red', text: 'H 高', desc: 'High 严重问题, 须快速响应' },
  M: { color: 'orange', text: 'M 中', desc: 'Medium 中等问题' },
  L: { color: 'blue', text: 'L 低', desc: 'Low 一般问题' },
};

// 升级级别元数据
const LEVEL_META: Record<number, { color: string; text: string; icon: React.ReactNode; desc: string }> = {
  1: { color: BRAND.primary, text: 'Lv1 责任人', icon: <MailOutlined />, desc: '逾期达到阈值首次提醒责任人, 之后按该间隔重复' },
  2: { color: BRAND.orange, text: 'Lv2 部门经理', icon: <ApartmentOutlined />, desc: '逾期达到阈值首次升级部门经理, 之后按该间隔重复' },
  3: { color: BRAND.danger, text: 'Lv3 AME Director', icon: <CrownOutlined />, desc: '逾期达到阈值首次升级 AME Director, 之后按该间隔重复' },
};

export default function Escalation() {
  const { message } = App.useApp();
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.Role === 'admin';

  // 配置列表状态
  const [configs, setConfigs] = useState<EscalationConfig[]>([]);
  const [configsTotal, setConfigsTotal] = useState(0);
  const [configsLoading, setConfigsLoading] = useState(false);
  const [configPage, setConfigPage] = useState(1);
  const [configPlantFilter, setConfigPlantFilter] = useState<string | undefined>();
  const [configSeverityFilter, setConfigSeverityFilter] = useState<string | undefined>();
  const [configEnabledFilter, setConfigEnabledFilter] = useState<boolean | undefined>();

  // 日志列表状态
  const [logs, setLogs] = useState<EscalationLog[]>([]);
  const [logsTotal, setLogsTotal] = useState(0);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logPage, setLogPage] = useState(1);
  const [logLevelFilter, setLogLevelFilter] = useState<number | undefined>();
  const [logPlantFilter, setLogPlantFilter] = useState<string | undefined>();
  const [logOwnerFilter, setLogOwnerFilter] = useState<string | undefined>();
  const [logProjectFilter, setLogProjectFilter] = useState<string | undefined>();
  // 日志筛选选项 (责任人/项目, 来自有升级日志的问题)
  const [logFilters, setLogFilters] = useState<EscalationLogFilters>({ owners: [], projects: [] });

  // 统计
  const [stats, setStats] = useState<EscalationLogStats | null>(null);

  // 用户选项（下拉选择收件人）
  const [userOptions, setUserOptions] = useState<UserOption[]>([]);
  const [userOptionsLoading, setUserOptionsLoading] = useState(false);

  // 弹窗
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<EscalationConfig | null>(null);
  // 弹窗模式: create 新增 / copy 复制新增 / edit 编辑
  const [formMode, setFormMode] = useState<'create' | 'copy' | 'edit'>('create');
  const [editForm] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const [scanLoading, setScanLoading] = useState(false);

  // 测试邮件弹窗
  const [testEmailModalOpen, setTestEmailModalOpen] = useState(false);
  const [testEmailRecipient, setTestEmailRecipient] = useState('');
  const [testEmailLoading, setTestEmailLoading] = useState(false);
  const [testEmailResult, setTestEmailResult] = useState<TestEmailResponse | null>(null);

  // 非管理员提示
  const readOnly = !isAdmin;

  // ============ 数据加载 ============
  const fetchConfigs = useCallback(async () => {
    setConfigsLoading(true);
    try {
      const res = (await listEscalationConfigsApi({
        page: configPage,
        page_size: 20,
        plant: configPlantFilter,
        severity: configSeverityFilter,
        enabled: configEnabledFilter,
      })) as PageResponse<EscalationConfig>;
      setConfigs(res.items || []);
      setConfigsTotal(res.total || 0);
    } catch {
      setConfigs([]);
      setConfigsTotal(0);
    } finally {
      setConfigsLoading(false);
    }
  }, [configPage, configPlantFilter, configSeverityFilter, configEnabledFilter]);

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const res = (await listEscalationLogsApi({
        page: logPage,
        page_size: 20,
        level: logLevelFilter,
        plant: logPlantFilter,
        owner_name: logOwnerFilter,
        project_name: logProjectFilter,
      })) as PageResponse<EscalationLog>;
      setLogs(res.items || []);
      setLogsTotal(res.total || 0);
    } catch {
      setLogs([]);
      setLogsTotal(0);
    } finally {
      setLogsLoading(false);
    }
  }, [logPage, logLevelFilter, logPlantFilter, logOwnerFilter, logProjectFilter]);

  const fetchLogFilters = useCallback(async () => {
    try {
      const res = (await getEscalationLogFiltersApi()) as EscalationLogFilters;
      setLogFilters({ owners: res.owners || [], projects: res.projects || [] });
    } catch {
      setLogFilters({ owners: [], projects: [] });
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const s = (await getEscalationLogStatsApi()) as EscalationLogStats;
      setStats(s);
    } catch {
      // 跳过
    }
  }, []);

  const fetchUserOptions = useCallback(async () => {
    setUserOptionsLoading(true);
    try {
      const list = (await listUserOptionsApi()) as UserOption[];
      setUserOptions(list || []);
    } catch {
      setUserOptions([]);
    } finally {
      setUserOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    fetchLogFilters();
  }, [fetchLogFilters]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    fetchUserOptions();
  }, [fetchUserOptions]);

  // 辅助: 邮箱分号字符串 → 数组 (去除空值)
  const recipientsStrToArray = (str: string | null | undefined): string[] => {
    if (!str) return [];
    return str
      .split(/[;；]/g)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  };

  // 辅助: 邮箱数组 → 分号字符串
  const recipientsArrayToStr = (arr: unknown[] | null | undefined): string | null => {
    if (!Array.isArray(arr) || arr.length === 0) return null;
    return arr
      .map((v) => String(v ?? '').trim())
      .filter((v) => v.length > 0)
      .join(';');
  };

  // 生成用户下拉选项: label 显示 中文姓名 (用户名) - 部门, value 为邮箱
  const recipientSelectOptions = useMemo(() => {
    const out: Array<{ label: string; value: string }> = [];
    const seen = new Set<string>();
    for (const u of userOptions) {
      const email = (u.Email || '').trim();
      if (!email) continue;
      if (seen.has(email.toLowerCase())) continue;
      seen.add(email.toLowerCase());
      const namePart = u.DisplayName || u.Username;
      const deptPart = u.Department ? ` - ${u.Department}` : '';
      out.push({
        label: `${namePart} (${u.Username})${deptPart}`,
        value: email,
      });
    }
    return out;
  }, [userOptions]);

  // ============ 操作 ============
  const applyConfigToForm = (cfg: EscalationConfig) => {
    editForm.setFieldsValue({
      Plant: cfg.Plant,
      Severity: cfg.Severity,
      Level1Hours: cfg.Level1Hours,
      Level2Hours: cfg.Level2Hours,
      Level3Hours: cfg.Level3Hours,
      // Lv1 仍使用普通字符串输入 (责任人邮箱留空即可)
      Level1Recipients: cfg.Level1Recipients || '',
      // Lv2 / Lv3 使用多选下拉 (数组形式)
      Level2Recipients: recipientsStrToArray(cfg.Level2Recipients),
      Level3Recipients: recipientsStrToArray(cfg.Level3Recipients),
      IsEnabled: cfg.IsEnabled,
      Remarks: cfg.Remarks || '',
    });
  };

  const handleEdit = (cfg: EscalationConfig | null) => {
    setEditingConfig(cfg);
    setFormMode(cfg ? 'edit' : 'create');
    if (cfg) {
      applyConfigToForm(cfg);
    } else {
      editForm.resetFields();
      editForm.setFieldsValue({
        Level1Hours: 48,
        Level2Hours: 168,
        Level3Hours: 336,
        Level2Recipients: [],
        Level3Recipients: [],
        IsEnabled: true,
      });
    }
    setEditModalOpen(true);
  };

  // 复制已有配置: 预填其全部字段, 走"新增"保存路径, 用户可改成其他工厂/等级
  const handleCopy = (cfg: EscalationConfig) => {
    setEditingConfig(null);
    setFormMode('copy');
    editForm.resetFields();
    applyConfigToForm(cfg);
    editForm.setFieldsValue({ Remarks: cfg.Remarks ? `复制自 ${cfg.Plant}-${cfg.Severity}: ${cfg.Remarks}` : `复制自 ${cfg.Plant}-${cfg.Severity}` });
    setEditModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await editForm.validateFields();
      setSubmitting(true);
      const payload: EscalationConfigCreatePayload = {
        Plant: values.Plant,
        Severity: values.Severity,
        Level1Hours: values.Level1Hours,
        Level2Hours: values.Level2Hours,
        Level3Hours: values.Level3Hours,
        Level1Recipients: (values.Level1Recipients as string)?.trim() || null,
        Level2Recipients: recipientsArrayToStr(values.Level2Recipients),
        Level3Recipients: recipientsArrayToStr(values.Level3Recipients),
        IsEnabled: values.IsEnabled,
        Remarks: (values.Remarks as string)?.trim() || null,
      };
      if (editingConfig) {
        await updateEscalationConfigApi(editingConfig.Id, payload);
        message.success('配置已更新');
      } else {
        await createEscalationConfigApi(payload);
        message.success(formMode === 'copy' ? '配置已复制创建' : '配置已创建');
      }
      setEditModalOpen(false);
      fetchConfigs();
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteEscalationConfigApi(id);
      message.success('配置已删除');
      fetchConfigs();
    } catch {
      // 错误已提示
    }
  };

  const handleToggle = async (id: number) => {
    try {
      await toggleEscalationConfigApi(id);
      message.success('状态已切换');
      fetchConfigs();
    } catch {
      // 错误已提示
    }
  };

  const handleScan = async () => {
    setScanLoading(true);
    try {
      const res = (await triggerEscalationScanApi()) as {
        ok: boolean;
        result: { scanned: number; sent: number; skipped: number };
      };
      message.success(
        `扫描完成: 扫描 ${res.result.scanned} 条, 发送 ${res.result.sent} 条, 跳过 ${res.result.skipped} 条`
      );
      fetchLogs();
      fetchLogFilters();
      fetchStats();
    } catch {
      // 错误已提示
    } finally {
      setScanLoading(false);
    }
  };

  const handleSendTestEmail = async () => {
    const email = testEmailRecipient.trim();
    if (!email) {
      message.warning('请输入测试收件人邮箱');
      return;
    }
    setTestEmailLoading(true);
    setTestEmailResult(null);
    try {
      const res = (await sendTestEmailApi(email)) as TestEmailResponse;
      setTestEmailResult(res);
      if (res.ok) {
        message.success('测试邮件已发送, 请查收');
      } else {
        message.error('测试邮件发送失败, 请查看详情');
      }
    } catch {
      // 错误已提示
    } finally {
      setTestEmailLoading(false);
    }
  };

  const openTestEmailModal = () => {
    setTestEmailResult(null);
    setTestEmailRecipient('');
    setTestEmailModalOpen(true);
  };

  // ============ 配置表格列 ============
  const configColumns: ColumnsType<EscalationConfig> = [
    {
      title: '工厂',
      dataIndex: 'Plant',
      key: 'Plant',
      width: 140,
      render: (text: string) => (
        <Space>
          <ApartmentOutlined style={{ color: BRAND.primary }} />
          <Tag color={text === '*' ? 'default' : 'blue'} style={{ fontFamily: NUM_FONT, fontSize: 11 }}>
            {getPlantDisplayName(text)}
          </Tag>
        </Space>
      ),
    },
    {
      title: '等级',
      dataIndex: 'Severity',
      key: 'Severity',
      width: 80,
      render: (s: string) => {
        const meta = SEVERITY_META[s];
        return meta ? (
          <Tooltip title={meta.desc}>
            <Tag color={meta.color} style={{ fontSize: 11, fontWeight: 700 }}>{s}</Tag>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        );
      },
    },
    {
      title: '逾期阈值/提醒间隔',
      key: 'hours',
      width: 200,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title={LEVEL_META[1].desc}>
            <Tag color={LEVEL_META[1].color} style={{ fontSize: 10 }}>
              {LEVEL_META[1].icon} {record.Level1Hours}h
            </Tag>
          </Tooltip>
          <ArrowUpOutlined style={{ fontSize: 10, color: '#d9d9d9' }} />
          <Tooltip title={LEVEL_META[2].desc}>
            <Tag color={LEVEL_META[2].color} style={{ fontSize: 10 }}>
              {LEVEL_META[2].icon} {record.Level2Hours}h
            </Tag>
          </Tooltip>
          <ArrowUpOutlined style={{ fontSize: 10, color: '#d9d9d9' }} />
          <Tooltip title={LEVEL_META[3].desc}>
            <Tag color={LEVEL_META[3].color} style={{ fontSize: 10 }}>
              {LEVEL_META[3].icon} {record.Level3Hours}h
            </Tag>
          </Tooltip>
        </Space>
      ),
    },
    {
      title: 'Lv1 收件人',
      dataIndex: 'Level1Recipients',
      key: 'Level1Recipients',
      width: 160,
      ellipsis: true,
      render: (text: string | null) =>
        text ? (
          <Tooltip title={text}>
            <Text style={{ fontSize: 11 }}>{text}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 10 }}>责任人邮箱</Text>
        ),
    },
    {
      title: 'Lv2 部门经理',
      dataIndex: 'Level2Recipients',
      key: 'Level2Recipients',
      width: 180,
      ellipsis: true,
      render: (text: string | null) =>
        text ? (
          <Tooltip title={text}>
            <Text style={{ fontSize: 11 }}>{text}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 10 }}>未配置</Text>
        ),
    },
    {
      title: 'Lv3 AME Director',
      dataIndex: 'Level3Recipients',
      key: 'Level3Recipients',
      width: 180,
      ellipsis: true,
      render: (text: string | null) =>
        text ? (
          <Tooltip title={text}>
            <Text style={{ fontSize: 11 }}>{text}</Text>
          </Tooltip>
        ) : (
          <Text type="secondary" style={{ fontSize: 10 }}>未配置</Text>
        ),
    },
    {
      title: '状态',
      dataIndex: 'IsEnabled',
      key: 'IsEnabled',
      width: 90,
      render: (enabled: boolean, record) =>
        readOnly ? (
          <Tag color={enabled ? 'success' : 'default'} style={{ fontSize: 10 }}>
            {enabled ? '启用' : '禁用'}
          </Tag>
        ) : (
          <Switch
            checked={enabled}
            size="small"
            onChange={() => handleToggle(record.Id)}
          />
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      fixed: 'right' as const,
      render: (_, record) =>
        readOnly ? (
          <Button
            size="small"
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            查看
          </Button>
        ) : (
          <Space size="small">
            <Button
              size="small"
              type="link"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            >
              编辑
            </Button>
            <Tooltip title="复制此配置为新配置 (可修改工厂/等级)">
              <Button
                size="small"
                type="link"
                icon={<CopyOutlined />}
                onClick={() => handleCopy(record)}
              >
                复制
              </Button>
            </Tooltip>
            <Popconfirm
              title="确认删除此配置?"
              onConfirm={() => handleDelete(record.Id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
    },
  ];

  // ============ 日志表格列 ============
  const logColumns: ColumnsType<EscalationLog> = [
    {
      title: '问题编号',
      dataIndex: 'IssueNo',
      key: 'IssueNo',
      width: 140,
      render: (text: string | null) => (
        <Text style={{ fontFamily: NUM_FONT, fontSize: 11 }}>{text || '—'}</Text>
      ),
    },
    {
      title: '项目名称',
      dataIndex: 'ProjectName',
      key: 'ProjectName',
      width: 150,
      ellipsis: true,
      render: (text: string | null) => (
        <Tooltip title={text}>
          <Text style={{ fontSize: 11 }}>{text || '—'}</Text>
        </Tooltip>
      ),
    },
    {
      title: '责任人',
      dataIndex: 'OwnerName',
      key: 'OwnerName',
      width: 90,
      render: (text: string | null) => (
        <Text style={{ fontSize: 11 }}>{text || '—'}</Text>
      ),
    },
    {
      title: '问题标题',
      dataIndex: 'IssueTitle',
      key: 'IssueTitle',
      width: 200,
      ellipsis: true,
      render: (text: string | null) => <Text style={{ fontSize: 11 }}>{text || '—'}</Text>,
    },
    {
      title: '工厂',
      dataIndex: 'Plant',
      key: 'Plant',
      width: 100,
      render: (text: string | null) =>
        text ? <Tag color="blue" style={{ fontSize: 10 }}>{getPlantDisplayName(text)}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: '等级',
      dataIndex: 'Severity',
      key: 'Severity',
      width: 60,
      render: (s: string | null) => {
        const meta = s ? SEVERITY_META[s] : null;
        return meta ? (
          <Tag color={meta.color} style={{ fontSize: 10, fontWeight: 700 }}>{s}</Tag>
        ) : (
          <Text type="secondary">—</Text>
        );
      },
    },
    {
      title: '升级级别',
      dataIndex: 'Level',
      key: 'Level',
      width: 140,
      render: (lvl: number, record) => {
        const meta = LEVEL_META[lvl];
        const remind = record.RemindCount || 1;
        return meta ? (
          <Tooltip title={meta.desc}>
            <Tag color={meta.color} icon={meta.icon} style={{ fontSize: 10, fontWeight: 600 }}>
              {meta.text}
            </Tag>
            {remind > 1 && (
              <Tag color="default" style={{ fontSize: 10, marginInlineEnd: 0 }}>第 {remind} 次</Tag>
            )}
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        );
      },
    },
    {
      title: '收件人',
      dataIndex: 'Recipients',
      key: 'Recipients',
      width: 240,
      render: (text: string, record) => {
        // 测试模式下 Recipients 为重定向后的测试邮箱, OriginalRecipients 保留原始收件人
        const original = record.OriginalRecipients?.trim();
        const redirected = !!original && original !== text;
        return (
          <Tooltip
            title={
              redirected
                ? `实际发送: ${text}\n原收件人: ${original}`
                : text
            }
          >
            <div>
              <Text style={{ fontSize: 11 }}>{text}</Text>
              {redirected && (
                <div style={{ marginTop: 2 }}>
                  <Tag color="orange" style={{ fontSize: 10, marginInlineEnd: 4, lineHeight: '16px', padding: '0 4px' }}>测试</Tag>
                  <Text type="secondary" style={{ fontSize: 10 }}>原收件人: {original}</Text>
                </div>
              )}
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '发送时间',
      dataIndex: 'SentAt',
      key: 'SentAt',
      width: 150,
      render: (date: string) => (
        <Text style={{ fontSize: 10 }}>{formatDateTime(date)}</Text>
      ),
    },
  ];

  return (
    <div style={industrialBgStyle}>
      {/* 顶部统计卡 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={5}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.purple}` }}>
            <CornerMarker color={BRAND.purple} />
            <Statistic
              title="升级总数"
              value={stats?.total || 0}
              prefix={<ThunderboltOutlined style={{ color: BRAND.purple }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.primary}` }}>
            <CornerMarker color={BRAND.primary} />
            <Statistic
              title="Lv1 责任人"
              value={stats?.level1_count || 0}
              prefix={<MailOutlined style={{ color: BRAND.primary }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.orange}` }}>
            <CornerMarker color={BRAND.orange} />
            <Statistic
              title="Lv2 部门经理"
              value={stats?.level2_count || 0}
              prefix={<ApartmentOutlined style={{ color: BRAND.orange }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.danger}` }}>
            <CornerMarker color={BRAND.danger} />
            <Statistic
              title="Lv3 AME Director"
              value={stats?.level3_count || 0}
              prefix={<CrownOutlined style={{ color: BRAND.danger }} />}
              valueStyle={{ fontSize: 22, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.cyan}` }}>
            <CornerMarker color={BRAND.cyan} />
            <Statistic
              title="近24h"
              value={stats?.last_24h_count || 0}
              prefix={<ClockCircleOutlined style={{ color: BRAND.cyan }} />}
              valueStyle={{
                fontSize: 22,
                fontFamily: NUM_FONT,
                color: (stats?.last_24h_count || 0) > 0 ? BRAND.cyan : undefined,
              }}
            />
          </Card>
        </Col>
      </Row>

      {/* 升级流程说明 */}
      <Alert
        type="info"
        showIcon
        icon={<ThunderboltOutlined />}
        style={{ marginBottom: 12 }}
        message={
          <span>
            <Text strong>问题升级流程:</Text>
            <Text style={{ marginLeft: 8 }}>
              问题逾期后按阈值触发多级邮件升级, 并按各级阈值间隔持续重复提醒 (逾期未处理期间不停) —
            </Text>
            <Tag color={BRAND.primary} style={{ marginLeft: 8, fontSize: 10 }}>Lv1 责任人 (每48h)</Tag>
            <ArrowUpOutlined style={{ fontSize: 10, color: '#999' }} />
            <Tag color={BRAND.orange} style={{ marginLeft: 4, fontSize: 10 }}>Lv2 部门经理 (每168h)</Tag>
            <ArrowUpOutlined style={{ fontSize: 10, color: '#999' }} />
            <Tag color={BRAND.danger} style={{ marginLeft: 4, fontSize: 10 }}>Lv3 AME Director (每336h)</Tag>
            <Text type="secondary" style={{ marginLeft: 12, fontSize: 11 }}>
              频次由配置阈值决定 (如 48=每2天); 调度器每小时 00 分扫描; Plant="*" 为全局兜底; 已关闭/待审批关闭不升级
            </Text>
          </span>
        }
      />

      {/* 主体内容 */}
      <Card size="small" style={techCardStyle}>
        <Tabs
          defaultActiveKey="configs"
          items={[
            // ===== 升级配置 =====
            {
              key: 'configs',
              label: (
                <Space size={4}>
                  <ThunderboltOutlined style={{ color: BRAND.purple }} />
                  <span>升级配置</span>
                  <Tag color="purple" style={{ margin: 0, fontSize: 10 }}>{configsTotal}</Tag>
                </Space>
              ),
              children: (
                <>
                  {readOnly && (
                    <Alert
                      type="warning"
                      showIcon
                      icon={<LockOutlined />}
                      style={{ marginBottom: 12 }}
                      message="只读模式: 您当前为查看权限, 仅管理员可新增/编辑/删除升级配置与发送测试邮件"
                    />
                  )}
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="按工厂筛选"
                      value={configPlantFilter}
                      onChange={(v) => { setConfigPlantFilter(v); setConfigPage(1); }}
                      allowClear
                      style={{ width: 180 }}
                      options={[
                        { value: '*', label: '全局 (兜底)' },
                        ...PLANT_OPTIONS.map((p) => ({ value: p.code, label: p.fullName })),
                      ]}
                    />
                    <Select
                      placeholder="按等级筛选"
                      value={configSeverityFilter}
                      onChange={(v) => { setConfigSeverityFilter(v); setConfigPage(1); }}
                      allowClear
                      style={{ width: 120 }}
                      options={[
                        { value: 'H', label: 'H 高' },
                        { value: 'M', label: 'M 中' },
                        { value: 'L', label: 'L 低' },
                      ]}
                    />
                    <Select
                      placeholder="按状态筛选"
                      value={configEnabledFilter}
                      onChange={(v) => { setConfigEnabledFilter(v); setConfigPage(1); }}
                      allowClear
                      style={{ width: 120 }}
                      options={[
                        { value: true, label: '启用' },
                        { value: false, label: '禁用' },
                      ]}
                    />
                    <Button icon={<ReloadOutlined />} onClick={fetchConfigs} loading={configsLoading}>
                      刷新
                    </Button>
                    {isAdmin && (
                      <>
                        <Button
                          type="primary"
                          icon={<PlusOutlined />}
                          onClick={() => handleEdit(null)}
                        >
                          新增配置
                        </Button>
                        <Popconfirm
                          title="手动触发升级扫描?"
                          description="将立即扫描所有未关闭问题并发送升级邮件"
                          onConfirm={handleScan}
                          okText="确认"
                          cancelText="取消"
                        >
                          <Button
                            icon={<PlayCircleOutlined />}
                            loading={scanLoading}
                            style={{ borderColor: BRAND.purple, color: BRAND.purple }}
                          >
                            手动扫描
                          </Button>
                        </Popconfirm>
                        <Button
                          icon={<ExperimentOutlined />}
                          onClick={openTestEmailModal}
                          style={{ borderColor: BRAND.cyan, color: BRAND.cyan }}
                        >
                          测试邮件
                        </Button>
                      </>
                    )}
                  </Space>
                  <Table<EscalationConfig>
                    columns={configColumns}
                    dataSource={configs}
                    rowKey={(r) => r.Id}
                    loading={configsLoading}
                    scroll={{ x: 1300 }}
                    size="small"
                    bordered
                    locale={{ emptyText: <Empty description="暂无升级配置, 请新增" /> }}
                    pagination={{
                      current: configPage,
                      total: configsTotal,
                      pageSize: 20,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 条`,
                      onChange: (p) => setConfigPage(p),
                    }}
                  />
                </>
              ),
            },

            // ===== 升级日志 =====
            {
              key: 'logs',
              label: (
                <Space size={4}>
                  <MailOutlined style={{ color: BRAND.primary }} />
                  <span>升级日志</span>
                  {logsTotal > 0 && <Badge count={logsTotal} size="small" />}
                </Space>
              ),
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="按升级级别筛选"
                      value={logLevelFilter}
                      onChange={(v) => { setLogLevelFilter(v); setLogPage(1); }}
                      allowClear
                      style={{ width: 160 }}
                      options={[
                        { value: 1, label: 'Lv1 责任人' },
                        { value: 2, label: 'Lv2 部门经理' },
                        { value: 3, label: 'Lv3 AME Director' },
                      ]}
                    />
                    <Select
                      placeholder="按责任人筛选"
                      value={logOwnerFilter}
                      onChange={(v) => { setLogOwnerFilter(v); setLogPage(1); }}
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      style={{ width: 160 }}
                      options={logFilters.owners}
                    />
                    <Select
                      placeholder="按项目筛选"
                      value={logProjectFilter}
                      onChange={(v) => { setLogProjectFilter(v); setLogPage(1); }}
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      style={{ width: 200 }}
                      options={logFilters.projects}
                    />
                    <Input
                      placeholder="按工厂筛选"
                      value={logPlantFilter}
                      onChange={(e) => setLogPlantFilter(e.target.value || undefined)}
                      allowClear
                      style={{ width: 140 }}
                    />
                    <Button icon={<ReloadOutlined />} onClick={() => { fetchLogs(); fetchLogFilters(); }} loading={logsLoading}>
                      刷新
                    </Button>
                  </Space>
                  <Table<EscalationLog>
                    columns={logColumns}
                    dataSource={logs}
                    rowKey={(r) => r.Id}
                    loading={logsLoading}
                    scroll={{ x: 1400 }}
                    size="small"
                    bordered
                    locale={{ emptyText: <Empty description="暂无升级日志" /> }}
                    pagination={{
                      current: logPage,
                      total: logsTotal,
                      pageSize: 20,
                      showSizeChanger: true,
                      showTotal: (t) => `共 ${t} 条`,
                      onChange: (p) => setLogPage(p),
                    }}
                  />
                </>
              ),
            },
          ]}
        />
      </Card>

      {/* ===== 编辑/新增弹窗 ===== */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: BRAND.purple }} />
            <span>
              {readOnly
                ? '查看升级配置'
                : formMode === 'edit'
                  ? '编辑升级配置'
                  : formMode === 'copy'
                    ? '复制新增升级配置'
                    : '新增升级配置'}
            </span>
            {readOnly && <Tag color="default" icon={<LockOutlined />} style={{ fontSize: 10 }}>只读</Tag>}
          </Space>
        }
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={readOnly ? undefined : handleSubmit}
        confirmLoading={submitting}
        okText={readOnly ? undefined : '保存'}
        cancelText={readOnly ? '关闭' : '取消'}
        width={680}
        forceRender
      >
        <Form form={editForm} layout="vertical" style={{ marginTop: 16 }} disabled={readOnly}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="工厂"
                name="Plant"
                tooltip='工厂代码, 与 HRDB location 字段对应; 选择 "*" 表示全局兜底配置'
                rules={[{ required: true, message: '请选择工厂' }]}
              >
                <Select
                  placeholder="请选择工厂"
                  showSearch
                  optionFilterProp="label"
                  options={[
                    { value: '*', label: '全局 (兜底)' },
                    ...PLANT_OPTIONS.map((p) => ({
                      value: p.code,
                      label: `${p.code} - ${p.fullName}`,
                    })),
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="严重等级"
                name="Severity"
                rules={[{ required: true, message: '请选择等级' }]}
              >
                <Select
                  options={[
                    { value: 'H', label: 'H 高 (快速响应)' },
                    { value: 'M', label: 'M 中' },
                    { value: 'L', label: 'L 低' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>

          <Alert
            type="info"
            showIcon
            icon={<ClockCircleOutlined />}
            style={{ marginBottom: 16 }}
            message={
              <Text style={{ fontSize: 11 }}>
                {'逾期阈值 = 首次触发时间 + 重复提醒间隔 (问题逾期后, 各级按自身阈值间隔重复提醒; 须满足 Lv1 < Lv2 < Lv3)'}
              </Text>
            }
          />

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label={<Space><Tag color={BRAND.primary} style={{ fontSize: 9 }}>Lv1</Tag>责任人 (逾期阈值/间隔)</Space>}
                name="Level1Hours"
                tooltip="逾期达到该小时数后首次提醒责任人, 之后每隔该小时数重复提醒 (如 48 = 每 2 天一次)"
                rules={[{ required: true }]}
              >
                <HoursInputNumber max={720} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label={<Space><Tag color={BRAND.orange} style={{ fontSize: 9 }}>Lv2</Tag>部门经理 (逾期阈值/间隔)</Space>}
                name="Level2Hours"
                tooltip="逾期达到该小时数后首次升级部门经理, 之后每隔该小时数重复提醒 (如 168 = 每 7 天一次)"
                rules={[{ required: true }]}
              >
                <HoursInputNumber max={720} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label={<Space><Tag color={BRAND.danger} style={{ fontSize: 9 }}>Lv3</Tag>AME Director (逾期阈值/间隔)</Space>}
                name="Level3Hours"
                tooltip="逾期达到该小时数后首次升级 AME Director, 之后每隔该小时数重复提醒 (如 336 = 每 14 天一次)"
                rules={[{ required: true }]}
              >
                <HoursInputNumber max={1440} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="Lv1 收件人 (责任人)"
            name="Level1Recipients"
            tooltip="留空则使用问题责任人邮箱 (推荐留空)"
          >
            <Input placeholder="留空使用责任人邮箱; 多个用分号分隔" />
          </Form.Item>

          <Form.Item
            label="Lv2 收件人 (部门经理)"
            name="Level2Recipients"
            tooltip="可从用户管理中多选; 也可直接输入邮箱后按回车新增自定义收件人"
          >
            <Select
              mode="tags"
              allowClear
              showSearch
              loading={userOptionsLoading}
              placeholder="选择部门经理或输入邮箱 (回车确认)"
              options={recipientSelectOptions}
              optionFilterProp="label"
              tokenSeparators={[';', '；', ',', '，', '\n']}
              maxTagCount="responsive"
              filterOption={(input, option) => {
                const label = String(option?.label || '').toLowerCase();
                const value = String(option?.value || '').toLowerCase();
                const key = input.toLowerCase();
                return label.includes(key) || value.includes(key);
              }}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item
            label="Lv3 收件人 (AME Director)"
            name="Level3Recipients"
            tooltip="可从用户管理中多选; 也可直接输入邮箱后按回车新增自定义收件人"
          >
            <Select
              mode="tags"
              allowClear
              showSearch
              loading={userOptionsLoading}
              placeholder="选择 AME Director 或输入邮箱 (回车确认)"
              options={recipientSelectOptions}
              optionFilterProp="label"
              tokenSeparators={[';', '；', ',', '，', '\n']}
              maxTagCount="responsive"
              filterOption={(input, option) => {
                const label = String(option?.label || '').toLowerCase();
                const value = String(option?.value || '').toLowerCase();
                const key = input.toLowerCase();
                return label.includes(key) || value.includes(key);
              }}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item label="启用" name="IsEnabled" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item label="备注" name="Remarks">
            <TextArea rows={2} placeholder="可选" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* ===== 测试邮件弹窗 ===== */}
      <Modal
        title={
          <Space>
            <ExperimentOutlined style={{ color: BRAND.cyan }} />
            <span>邮件服务连通性测试</span>
          </Space>
        }
        open={testEmailModalOpen}
        onCancel={() => setTestEmailModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setTestEmailModalOpen(false)}>
            关闭
          </Button>,
          <Button
            key="send"
            type="primary"
            icon={<MailOutlined />}
            loading={testEmailLoading}
            onClick={handleSendTestEmail}
          >
            发送测试邮件
          </Button>,
        ]}
        width={560}
      >
        <Alert
          type="info"
          showIcon
          icon={<MailOutlined />}
          style={{ marginBottom: 16 }}
          message="此功能用于验证系统 SMTP 邮箱服务是否连通, 不依赖升级配置, 直接向指定邮箱发送一封测试邮件"
        />
        <Form layout="vertical">
          <Form.Item
            label="测试收件人邮箱"
            required
            tooltip="输入需测试的邮箱地址, 系统将向该地址发送一封测试邮件"
          >
            <Input
              placeholder="例如 your.name@inalfa.local"
              value={testEmailRecipient}
              onChange={(e) => setTestEmailRecipient(e.target.value)}
              onPressEnter={handleSendTestEmail}
              prefix={<MailOutlined style={{ color: '#bfbfbf' }} />}
            />
          </Form.Item>
        </Form>

        {testEmailResult && (
          <Alert
            type={testEmailResult.ok ? 'success' : 'error'}
            showIcon
            icon={testEmailResult.ok ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}
            style={{ marginTop: 8 }}
            message={testEmailResult.message}
            description={
              <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
                <Descriptions.Item label="SMTP 主机">
                  {testEmailResult.smtp_host}:{testEmailResult.smtp_port}
                </Descriptions.Item>
                <Descriptions.Item label="发件人">
                  {testEmailResult.from_address}
                </Descriptions.Item>
                {testEmailResult.log_id && (
                  <Descriptions.Item label="日志ID">
                    #{testEmailResult.log_id}
                  </Descriptions.Item>
                )}
                {testEmailResult.error && (
                  <Descriptions.Item label="错误信息">
                    <Text type="danger" style={{ fontSize: 11, wordBreak: 'break-all' }}>
                      {testEmailResult.error}
                    </Text>
                  </Descriptions.Item>
                )}
              </Descriptions>
            }
          />
        )}
      </Modal>
    </div>
  );
}
