import { useCallback, useEffect, useState } from 'react';
import {
  Card,
  Table,
  Tag,
  Space,
  Button,
  Input,
  Modal,
  Form,
  Select,
  Drawer,
  Descriptions,
  Typography,
  App,
  Spin,
} from 'antd';
import {
  SyncOutlined,
  KeyOutlined,
  EditOutlined,
  CheckCircleOutlined,
  StopOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listUsersApi,
  getUserDetailApi,
  toggleUserStatusApi,
  updateUserRoleApi,
  resetPasswordApi,
  triggerUserSyncApi,
} from '@/api/system';
import { getAuthConfigApi } from '@/api/auth';
import type { UserExtended } from '@/api/system';
import { formatDateTime } from '@/utils/format';

const { Title, Text } = Typography;

// 角色中文标签映射
const roleLabels: Record<string, string> = {
  admin: '系统管理员',
  lead_reviewer: '首席评审',
  reviewer: '评审',
  reviewee: '被评审',
};

// 角色对应的 Tag 颜色
const roleColors: Record<string, string> = {
  admin: 'red',
  lead_reviewer: 'gold',
  reviewer: 'blue',
  reviewee: 'default',
};

// 角色下拉选项
const roleOptions = Object.entries(roleLabels).map(([value, label]) => ({
  value,
  label,
}));

// 用户管理页
export default function SystemUsers() {
  const { message, modal } = App.useApp();

  // 列表与分页状态
  const [users, setUsers] = useState<UserExtended[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState(''); // 实际查询关键词
  const [keywordInput, setKeywordInput] = useState(''); // 输入框文本

  // 手动同步状态
  const [syncLoading, setSyncLoading] = useState(false);

  // 本地登录开关: local_login_enabled=false 时隐藏管理员"重置密码"入口
  // (本地密码生命周期已归 Keycloak, 重置本地密码无意义; T05-R1 #7)
  const [localLoginEnabled, setLocalLoginEnabled] = useState(true);

  // 用户详情抽屉
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailUser, setDetailUser] = useState<UserExtended | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 重置密码弹窗
  const [resetOpen, setResetOpen] = useState(false);
  const [resetUser, setResetUser] = useState<UserExtended | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetForm] = Form.useForm<{ newPassword: string; confirmPassword: string }>();

  // 修改角色弹窗
  const [roleOpen, setRoleOpen] = useState(false);
  const [roleUser, setRoleUser] = useState<UserExtended | null>(null);
  const [roleValue, setRoleValue] = useState<string>('');
  const [roleLoading, setRoleLoading] = useState(false);

  // 拉取用户列表（后端分页）
  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listUsersApi({ page, page_size: pageSize, keyword });
      setUsers(res.items || []);
      setTotal(res.total || 0);
    } catch {
      // 错误已由响应拦截器统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword]);

  // 分页或关键词变化时自动拉取
  useEffect(() => {
    void fetchUsers();
  }, [fetchUsers]);

  // 拉取登录配置 (公开端点): local_login_enabled=false 时隐藏重置密码操作
  useEffect(() => {
    let cancelled = false;
    getAuthConfigApi()
      .then((cfg) => {
        if (!cancelled) setLocalLoginEnabled(cfg.local_login_enabled !== false);
      })
      .catch(() => {
        // 拉取失败保持默认展示, 不阻塞页面
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 关键词搜索：重置到第一页
  const handleSearch = (value: string) => {
    const v = value.trim();
    setKeyword(v);
    setKeywordInput(v);
    setPage(1);
  };

  // 手动触发 HR 用户同步
  const handleSync = async () => {
    setSyncLoading(true);
    try {
      const res = await triggerUserSyncApi();
      message.success(res.message || '同步完成');
      // 同步完成后刷新列表
      void fetchUsers();
    } catch {
      // 错误已由响应拦截器统一提示
    } finally {
      setSyncLoading(false);
    }
  };

  // 切换用户启用/禁用状态
  const handleToggleStatus = (record: UserExtended) => {
    const nextStatus = record.Status === 1 ? 0 : 1;
    const actionText = nextStatus === 1 ? '启用' : '禁用';
    modal.confirm({
      title: `确认${actionText}用户`,
      content: `确定要${actionText}用户「${record.DisplayName || record.Username}」吗？`,
      okText: '确定',
      cancelText: '取消',
      onOk: async () => {
        await toggleUserStatusApi(record.Id, nextStatus);
        message.success(`${actionText}成功`);
        void fetchUsers();
      },
    });
  };

  // 打开重置密码弹窗
  const openResetModal = (record: UserExtended) => {
    setResetUser(record);
    resetForm.resetFields();
    setResetOpen(true);
  };

  // 提交重置密码
  const handleResetPassword = async () => {
    if (!resetUser) return;
    try {
      const values = await resetForm.validateFields();
      setResetLoading(true);
      await resetPasswordApi(resetUser.Id, values.newPassword);
      message.success('密码重置成功');
      setResetOpen(false);
      resetForm.resetFields();
      void fetchUsers();
    } catch {
      // 校验失败或 API 错误，已由拦截器/表单处理
    } finally {
      setResetLoading(false);
    }
  };

  // 打开修改角色弹窗
  const openRoleModal = (record: UserExtended) => {
    setRoleUser(record);
    setRoleValue(record.Role);
    setRoleOpen(true);
  };

  // 提交修改角色
  const handleUpdateRole = async () => {
    if (!roleUser) return;
    if (roleValue === roleUser.Role) {
      message.info('角色未变更');
      setRoleOpen(false);
      return;
    }
    setRoleLoading(true);
    try {
      await updateUserRoleApi(roleUser.Id, roleValue);
      message.success('角色修改成功');
      setRoleOpen(false);
      void fetchUsers();
    } catch {
      // 错误已由响应拦截器统一提示
    } finally {
      setRoleLoading(false);
    }
  };

  // 打开用户详情抽屉
  const openDetail = async (record: UserExtended) => {
    setDetailUser(record); // 先用行数据即时展示
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const detail = await getUserDetailApi(record.Id);
      setDetailUser(detail);
    } catch {
      // 错误已由响应拦截器统一提示，保留已有行数据
    } finally {
      setDetailLoading(false);
    }
  };

  // 表格列定义
  const columns: ColumnsType<UserExtended> = [
    {
      title: '用户名',
      dataIndex: 'Username',
      key: 'Username',
      width: 140,
      render: (val: string, record) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => openDetail(record)}>
          {val}
        </Button>
      ),
    },
    {
      title: '姓名',
      dataIndex: 'DisplayName',
      key: 'DisplayName',
      width: 120,
      render: (val: string | null) => val || '-',
    },
    {
      title: '邮箱',
      dataIndex: 'Email',
      key: 'Email',
      width: 200,
      render: (val: string | null) => val || '-',
    },
    {
      title: '电话',
      dataIndex: 'Phone',
      key: 'Phone',
      width: 140,
      render: (val: string | null) => val || '-',
    },
    {
      title: '部门',
      dataIndex: 'Department',
      key: 'Department',
      width: 140,
      render: (val: string | null) => val || '-',
    },
    {
      title: '角色',
      dataIndex: 'Role',
      key: 'Role',
      width: 110,
      render: (val: string) => (
        <Tag color={roleColors[val] || 'default'}>{roleLabels[val] || val}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'Status',
      key: 'Status',
      width: 90,
      render: (val: number) =>
        val === 1 ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '密码状态',
      dataIndex: 'HasPassword',
      key: 'HasPassword',
      width: 110,
      render: (val: boolean) =>
        val ? <Tag color="blue">已设置</Tag> : <Tag color="orange">未设置</Tag>,
    },
    {
      title: '同步时间',
      dataIndex: 'HrSyncedAt',
      key: 'HrSyncedAt',
      width: 170,
      render: (val: string | null) => (val ? formatDateTime(val) : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small" wrap>
          {localLoginEnabled && (
            <Button
              type="link"
              size="small"
              icon={<KeyOutlined />}
              onClick={() => openResetModal(record)}
            >
              重置密码
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openRoleModal(record)}
          >
            修改角色
          </Button>
          <Button
            type="link"
            size="small"
            danger={record.Status === 1}
            icon={record.Status === 1 ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={() => handleToggleStatus(record)}
          >
            {record.Status === 1 ? '禁用' : '启用'}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={5} style={{ margin: 0 }}>用户管理</Title>}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchUsers()}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<SyncOutlined />}
            loading={syncLoading}
            onClick={handleSync}
          >
            手动同步
          </Button>
        </Space>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="搜索用户名/姓名/邮箱"
          value={keywordInput}
          onChange={(e) => {
            const v = e.target.value;
            setKeywordInput(v);
            // 清空时立即触发搜索
            if (v === '' && keyword !== '') {
              setKeyword('');
              setPage(1);
            }
          }}
          onSearch={handleSearch}
          allowClear
          enterButton
          style={{ width: 320 }}
        />
      </div>

      <Table<UserExtended>
        rowKey="Id"
        columns={columns}
        dataSource={users}
        loading={loading}
        scroll={{ x: 1500 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      {/* 用户详情抽屉 */}
      <Drawer
        title="用户详情"
        width={520}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        destroyOnHidden
      >
        <Spin spinning={detailLoading}>
          {detailUser && (
            <>
              <Title level={5} style={{ marginTop: 0 }}>基本信息</Title>
              <Descriptions column={1} bordered size="small" styles={{ label: { width: 110 } }}>
                <Descriptions.Item label="用户名">{detailUser.Username}</Descriptions.Item>
                <Descriptions.Item label="姓名">{detailUser.DisplayName || '-'}</Descriptions.Item>
                <Descriptions.Item label="邮箱">{detailUser.Email || '-'}</Descriptions.Item>
                <Descriptions.Item label="电话">{detailUser.Phone || '-'}</Descriptions.Item>
                <Descriptions.Item label="部门">{detailUser.Department || '-'}</Descriptions.Item>
                <Descriptions.Item label="角色">
                  <Tag color={roleColors[detailUser.Role] || 'default'}>
                    {roleLabels[detailUser.Role] || detailUser.Role}
                  </Tag>
                </Descriptions.Item>
              </Descriptions>

              <Title level={5} style={{ marginTop: 24 }}>系统信息</Title>
              <Descriptions column={1} bordered size="small" styles={{ label: { width: 110 } }}>
                <Descriptions.Item label="状态">
                  {detailUser.Status === 1 ? (
                    <Tag color="green">启用</Tag>
                  ) : (
                    <Tag color="default">禁用</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="密码状态">
                  {detailUser.HasPassword ? (
                    <Tag color="blue">已设置</Tag>
                  ) : (
                    <Tag color="orange">未设置</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="密码更新时间">
                  {detailUser.PasswordUpdatedAt ? formatDateTime(detailUser.PasswordUpdatedAt) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="是否删除">
                  {detailUser.IsDeleted ? '是' : '否'}
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {detailUser.CreatedAt ? formatDateTime(detailUser.CreatedAt) : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="更新时间">
                  {detailUser.UpdatedAt ? formatDateTime(detailUser.UpdatedAt) : '-'}
                </Descriptions.Item>
              </Descriptions>

              <Title level={5} style={{ marginTop: 24 }}>同步信息</Title>
              <Descriptions column={1} bordered size="small" styles={{ label: { width: 110 } }}>
                <Descriptions.Item label="HR 同步时间">
                  {detailUser.HrSyncedAt ? formatDateTime(detailUser.HrSyncedAt) : '尚未同步'}
                </Descriptions.Item>
              </Descriptions>
            </>
          )}
        </Spin>
      </Drawer>

      {/* 重置密码弹窗 */}
      <Modal
        title="重置密码"
        open={resetOpen}
        onOk={handleResetPassword}
        onCancel={() => {
          setResetOpen(false);
          resetForm.resetFields();
        }}
        confirmLoading={resetLoading}
        okText="确认重置"
        cancelText="取消"
        forceRender
      >
        {resetUser && (
          <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
            将为用户「{resetUser.DisplayName || resetUser.Username}」设置新密码
          </Text>
        )}
        <Form form={resetForm} layout="vertical" autoComplete="off" preserve={false}>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '密码至少 8 位' },
            ]}
          >
            <Input.Password placeholder="请输入新密码 (至少 8 位)" />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 修改角色弹窗 */}
      <Modal
        title="修改角色"
        open={roleOpen}
        onOk={handleUpdateRole}
        onCancel={() => setRoleOpen(false)}
        confirmLoading={roleLoading}
        okText="确认修改"
        cancelText="取消"
        destroyOnHidden
      >
        {roleUser && (
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">用户：</Text>
            <Text>{roleUser.DisplayName || roleUser.Username}</Text>
          </div>
        )}
        <div style={{ marginBottom: 8 }}>
          <Text type="secondary">角色</Text>
        </div>
        <Select
          value={roleValue}
          onChange={setRoleValue}
          options={roleOptions}
          style={{ width: '100%' }}
          placeholder="请选择角色"
        />
      </Modal>
    </Card>
  );
}
