import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  App,
  Card,
  Tabs,
  Form,
  Input,
  InputNumber,
  Button,
  Radio,
  Switch,
  Space,
  Typography,
  Alert,
  Tag,
  Tooltip,
  Spin,
  Divider,
  Table,
  Empty,
} from 'antd';
import {
  SettingOutlined,
  MailOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  ThunderboltOutlined,
  ClockCircleOutlined,
  BellOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { FormInstance } from 'antd';
import dayjs from 'dayjs';

import {
  getNotificationMode,
  updateNotificationMode,
  listSettingsGrouped,
  batchUpdateSettings,
  initSystemSettings,
  type NotificationMode,
  type SettingGroup,
  type SystemSettingItem,
  type BatchUpdateItem,
} from '@/api/systemSettings';
import { NUM_FONT } from '@/utils/fonts';

const { Text, Paragraph } = Typography;

// 模块图标映射
const MODULE_ICONS: Record<string, React.ReactNode> = {
  notification: <BellOutlined />,
  smtp: <MailOutlined />,
  issue_closure: <ClockCircleOutlined />,
  maintenance_scan: <ThunderboltOutlined />,
  escalation: <ThunderboltOutlined />,
  monthly_reminder: <BellOutlined />,
  system: <GlobalOutlined />,
};

// 模块顺序 (用于 Tab 排序, 未列出的模块追加到末尾)
const MODULE_ORDER = [
  'notification',
  'smtp',
  'issue_closure',
  'maintenance_scan',
  'escalation',
  'monthly_reminder',
  'system',
];

export default function SystemSettings() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<NotificationMode | null>(null);
  const [notifForm] = Form.useForm();
  const [groups, setGroups] = useState<SettingGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  // 各模块表单实例 (按 module 缓存)
  const [moduleForms, setModuleForms] = useState<Record<string, FormInstance> | null>(null);

  // 加载通知模式
  const fetchMode = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getNotificationMode();
      setMode(res);
      notifForm.setFieldsValue({
        mode: res.mode,
        test_recipients: res.test_recipients,
      });
    } catch {
      // 错误已由拦截器提示
    } finally {
      setLoading(false);
    }
  }, [notifForm]);

  // 加载按模块分组的设置
  // 注意: 各模块表单的初始值由 ModuleConfigForm 自身的 useEffect 根据 group prop 设置,
  //       这里只需更新 groups state, 避免 moduleForms 循环依赖。
  const fetchGroups = useCallback(async () => {
    setGroupsLoading(true);
    try {
      const res = await listSettingsGrouped();
      setGroups(res || []);
    } catch {
      setGroups([]);
    } finally {
      setGroupsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMode();
    fetchGroups();
  }, [fetchMode, fetchGroups]);

  // 保存通知模式
  const handleSaveMode = async () => {
    try {
      const values = await notifForm.validateFields();
      setSaving(true);
      const res = await updateNotificationMode({
        mode: values.mode,
        test_recipients: values.test_recipients || '',
      });
      setMode(res);
      message.success('通知模式已更新');
    } catch {
      // 校验错误或 API 错误, 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  // 保存单个模块的配置 (批量更新)
  const handleSaveModule = async (moduleName: string) => {
    const form = moduleForms?.[moduleName];
    if (!form) return;
    try {
      const values = await form.validateFields();
      setSaving(true);
      // 收集所有变更项 (对比 groups 中的原始值)
      const group = groups.find((g) => g.module === moduleName);
      if (!group) return;
      const items: BatchUpdateItem[] = [];
      group.settings.forEach((s) => {
        const newVal = values[s.key];
        const oldVal = parseValue(s.value, s.value_type);
        // 转为字符串比较, bool 需要 "true"/"false"
        const newStr = stringifyValue(newVal, s.value_type);
        const oldStr = stringifyValue(oldVal, s.value_type);
        if (newStr !== oldStr) {
          items.push({ key: s.key, value: newStr });
        }
      });
      if (items.length === 0) {
        message.info('未检测到变更, 无需保存');
        return;
      }
      const res = await batchUpdateSettings({ items });
      message.success(`已更新 ${res.updated} 项配置${res.skipped > 0 ? `, 跳过 ${res.skipped} 项` : ''}`);
      // 刷新分组数据
      await fetchGroups();
    } catch {
      // 校验错误或 API 错误, 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  // 初始化默认配置
  const handleInit = async () => {
    try {
      setSaving(true);
      const res = await initSystemSettings();
      message.success(res.message || `初始化完成, 新增 ${res.inserted} 项`);
      await fetchGroups();
    } catch {
      // 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  // 全部设置表格列 (只读视图)
  const allColumns: ColumnsType<SystemSettingItem> = [
    {
      title: '模块',
      dataIndex: 'module',
      key: 'module',
      width: 120,
      render: (v: string | null) => v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">other</Text>,
    },
    {
      title: '设置项',
      dataIndex: 'key',
      key: 'key',
      width: 240,
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <Text code style={{ fontSize: 12 }}>{v}</Text>
          {r.display_name && <Text strong>{r.display_name}</Text>}
        </Space>
      ),
    },
    {
      title: '当前值',
      dataIndex: 'value',
      key: 'value',
      render: (v: string | null) => v ? (
        <Tag color="geekblue" style={{ fontFamily: NUM_FONT }}>{v}</Tag>
      ) : (
        <Text type="secondary">未设置</Text>
      ),
    },
    {
      title: '类型',
      dataIndex: 'value_type',
      key: 'value_type',
      width: 80,
      render: (v: string | null) => v ? <Tag>{v}</Tag> : '—',
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: string | null) => v ? <Text type="secondary">{v}</Text> : '—',
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—',
    },
  ];

  // 全部设置 (平铺)
  const allSettings = useMemo(() => {
    return groups.flatMap((g) => g.settings);
  }, [groups]);

  // 模块排序后的分组 (排除 notification, 它由独立 Tab 处理)
  const editableGroups = useMemo(() => {
    const filtered = groups.filter((g) => g.module !== 'notification');
    return filtered.sort((a, b) => {
      const ai = MODULE_ORDER.indexOf(a.module);
      const bi = MODULE_ORDER.indexOf(b.module);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  }, [groups]);

  // 构造 Tab 项
  const tabItems = [
    // Tab 1: 通知模式 (特殊处理: radio + 测试邮箱)
    {
      key: 'notification',
      label: (
        <Space>
          <BellOutlined />
          <span>通知模式</span>
        </Space>
      ),
      children: (
        <Spin spinning={loading}>
          {mode && (
            <Alert
              type={mode.is_test_mode ? 'warning' : 'success'}
              showIcon
              icon={mode.is_test_mode ? <ExperimentOutlined /> : <CheckCircleOutlined />}
              style={{ marginBottom: 16 }}
              message={
                <Space>
                  <Text strong>
                    当前模式: {mode.is_test_mode ? '测试模式' : '生产模式'}
                  </Text>
                  <Tag color={mode.is_test_mode ? 'orange' : 'green'}>
                    {mode.mode}
                  </Tag>
                </Space>
              }
              description={mode.description}
            />
          )}

          {mode?.is_test_mode && (
            <Alert
              type="info"
              showIcon
              icon={<ExclamationCircleOutlined />}
              style={{ marginBottom: 16 }}
              message="测试模式已启用"
              description={
                <span>
                  所有通知邮件将发送到测试邮箱: <Text code>{mode.test_recipients || '(未配置)'}</Text>
                  <br />
                  站内通知 (铃铛) 仍会正常发送给业务相关用户, 不受影响。
                </span>
              }
            />
          )}

          <Form form={notifForm} layout="vertical" style={{ maxWidth: 720 }}>
            <Form.Item
              label="通知模式"
              name="mode"
              tooltip="测试模式: 所有邮件发送到测试邮箱; 生产模式: 发送给真实责任人/升级经理"
              rules={[{ required: true, message: '请选择通知模式' }]}
            >
              <Radio.Group>
                <Space direction="vertical">
                  <Radio value="test">
                    <Space>
                      <ExperimentOutlined style={{ color: '#F59E0B' }} />
                      <Text strong>测试模式</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        (验证阶段使用, 邮件发送到测试邮箱)
                      </Text>
                    </Space>
                  </Radio>
                  <Radio value="production">
                    <Space>
                      <CheckCircleOutlined style={{ color: '#10B981' }} />
                      <Text strong>生产模式</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        (正式部署使用, 邮件发送给真实责任人)
                      </Text>
                    </Space>
                  </Radio>
                </Space>
              </Radio.Group>
            </Form.Item>

            <Form.Item
              noStyle
              shouldUpdate={(prev, curr) => prev.mode !== curr.mode}
            >
              {({ getFieldValue }) => (
                <Form.Item
                  label="测试模式邮件接收地址"
                  name="test_recipients"
                  tooltip="测试模式下, 所有通知邮件将发送到此地址 (多个用英文逗号分隔)"
                  rules={
                    getFieldValue('mode') === 'test'
                      ? [{ required: true, message: '测试模式下必须配置邮件接收地址' }]
                      : []
                  }
                >
                  <Input
                    placeholder="例如: admin@inalfa.local, tester@inalfa.local"
                    disabled={getFieldValue('mode') !== 'test'}
                  />
                </Form.Item>
              )}
            </Form.Item>

            <Divider />

            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={handleSaveMode}
                >
                  保存设置
                </Button>
                <Button onClick={() => fetchMode()}>重置</Button>
              </Space>
            </Form.Item>
          </Form>

          <Card size="small" type="inner" title="说明" style={{ marginTop: 16 }}>
            <Paragraph style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>
              <ExclamationCircleOutlined style={{ color: '#F59E0B' }} />{' '}
              <Text strong>测试模式</Text>: 邮件主题加 <Text code>[TEST]</Text> 前缀,
              正文末尾追加原收件人信息, 便于验证时识别。
            </Paragraph>
            <Paragraph style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>
              <CheckCircleOutlined style={{ color: '#10B981' }} />{' '}
              <Text strong>生产模式</Text>: 邮件正常发送给真实责任人 / 升级经理邮箱。
            </Paragraph>
            <Paragraph style={{ fontSize: 12, color: '#999', marginBottom: 0 }}>
              站内通知 (页面右上角铃铛) 始终发送给业务相关用户, 不受模式影响。
              修改后立即生效, 无需重启服务。
            </Paragraph>
          </Card>
        </Spin>
      ),
    },
    // 其他模块: 表单编辑
    ...editableGroups.map((g) => ({
      key: g.module,
      label: (
        <Space>
          {MODULE_ICONS[g.module] || <SettingOutlined />}
          <span>{g.module_name}</span>
        </Space>
      ),
      children: (
        <ModuleConfigForm
          group={g}
          onRegisterForm={(form) => {
            setModuleForms((prev) => {
              if (prev && prev[g.module] === form) return prev;
              return { ...(prev || {}), [g.module]: form };
            });
          }}
          saving={saving}
          onSave={() => handleSaveModule(g.module)}
        />
      ),
    })),
    // 最后一个 Tab: 全部设置 (只读表格)
    {
      key: 'all',
      label: (
        <Space>
          <SettingOutlined />
          <span>全部设置</span>
        </Space>
      ),
      children: (
        <>
          <Space style={{ marginBottom: 12 }}>
            <Button
              icon={<ReloadOutlined />}
              onClick={fetchGroups}
              loading={groupsLoading}
              size="small"
            >
              刷新
            </Button>
            <Tooltip title="将所有已定义的配置项写入数据库 (已存在的跳过), 用于首次部署或升级后补全配置">
              <Button
                icon={<ThunderboltOutlined />}
                onClick={handleInit}
                loading={saving}
                size="small"
              >
                初始化默认配置
              </Button>
            </Tooltip>
          </Space>
          <Paragraph type="secondary" style={{ fontSize: 12 }}>
            以下为系统全部运行时设置 (持久化到数据库, 修改后立即生效)。
            可在上方各功能模块 Tab 中编辑对应配置。
          </Paragraph>
          <Table<SystemSettingItem>
            columns={allColumns}
            dataSource={allSettings}
            rowKey={(r) => r.key}
            loading={groupsLoading}
            size="small"
            bordered
            pagination={false}
            locale={{ emptyText: <Empty description="暂无系统设置" /> }}
          />
        </>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <SettingOutlined style={{ color: '#2E5CE6' }} />
            <span>系统设置</span>
          </Space>
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => { fetchMode(); fetchGroups(); }}
          >
            刷新
          </Button>
        }
      >
        <Tabs
          defaultActiveKey="notification"
          items={tabItems}
          tabPosition="left"
        />
      </Card>
    </div>
  );
}

// ============ 模块配置表单子组件 ============

interface ModuleConfigFormProps {
  group: SettingGroup;
  onRegisterForm: (form: FormInstance) => void;
  saving: boolean;
  onSave: () => void;
}

function ModuleConfigForm({ group, onRegisterForm, saving, onSave }: ModuleConfigFormProps) {
  const [form] = Form.useForm();

  // 注册表单到父组件
  useEffect(() => {
    onRegisterForm(form);
  }, [form, onRegisterForm]);

  // 设置初始值
  useEffect(() => {
    const values: Record<string, unknown> = {};
    group.settings.forEach((s) => {
      values[s.key] = parseValue(s.value, s.value_type);
    });
    form.setFieldsValue(values);
  }, [group, form]);

  return (
    <Spin spinning={false}>
      <Alert
        type="info"
        showIcon
        icon={MODULE_ICONS[group.module] || <SettingOutlined />}
        style={{ marginBottom: 16 }}
        message={<Text strong>{group.module_name}</Text>}
        description={
          <span style={{ fontSize: 12, color: '#64748B' }}>
            修改后点击"保存设置"立即生效, 无需重启服务。
          </span>
        }
      />
      <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
        {group.settings.map((s) => (
          <Form.Item
            key={s.key}
            label={
              <Space size={4}>
                <Text strong>{s.display_name || s.key}</Text>
                {s.value_type && <Tag style={{ fontSize: 11 }}>{s.value_type}</Tag>}
              </Space>
            }
            name={s.key}
            tooltip={s.description || undefined}
            extra={s.description ? <Text type="secondary" style={{ fontSize: 12 }}>{s.description}</Text> : undefined}
          >
            {renderFormControl(s.value_type)}
          </Form.Item>
        ))}
        <Divider />
        <Form.Item>
          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={onSave}
            >
              保存设置
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Spin>
  );
}

// ============ 辅助函数 ============

// 根据 value_type 渲染对应的表单控件
function renderFormControl(valueType: string | null) {
  switch (valueType) {
    case 'int':
      return <InputNumber style={{ width: '100%' }} placeholder="请输入整数" />;
    case 'float':
      return <InputNumber style={{ width: '100%' }} step={0.1} placeholder="请输入数值" />;
    case 'bool':
      return (
        <Switch
          checkedChildren="启用"
          unCheckedChildren="关闭"
        />
      );
    default:
      return <Input placeholder="请输入" />;
  }
}

// 将字符串值解析为表单控件所需的类型
function parseValue(value: string | null, valueType: string | null): unknown {
  if (value === null || value === undefined || value === '') {
    return valueType === 'bool' ? false : '';
  }
  const v = String(value).trim();
  switch (valueType) {
    case 'int':
      const n = parseInt(v, 10);
      return isNaN(n) ? '' : n;
    case 'float':
      const f = parseFloat(v);
      return isNaN(f) ? '' : f;
    case 'bool':
      return v.toLowerCase() === 'true' || v === '1' || v.toLowerCase() === 'yes';
    default:
      return v;
  }
}

// 将表单值转为字符串 (用于提交批量更新)
function stringifyValue(value: unknown, valueType: string | null): string {
  if (value === null || value === undefined) return '';
  switch (valueType) {
    case 'bool':
      return value ? 'true' : 'false';
    case 'int':
    case 'float':
      return String(value);
    default:
      return String(value);
  }
}
