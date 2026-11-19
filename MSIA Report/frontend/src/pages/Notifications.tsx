import { useState, useCallback, useEffect } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  App,
  Tooltip,
  Segmented,
  Empty,
  Row,
  Col,
  Statistic,
  Badge,
} from 'antd';
import {
  CheckOutlined,
  BellOutlined,
  ReloadOutlined,
  ReadOutlined,
  MailOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  NotificationOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { http } from '@/api/client';
import { formatDateTime } from '@/utils/format';
import { BRAND, techCardStyle, CornerMarker } from '@/styles/shared';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text } = Typography;

interface NotificationItem {
  Id: number;
  Title: string;
  Content: string | null;
  Type: string | null;
  Status: string;
  Link: string | null;
  CreatedAt: string | null;
  ReadAt: string | null;
}

interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 通知类型标签映射 (扩展更多业务类型)
const typeLabels: Record<string, { color: string; text: string; icon?: React.ReactNode }> = {
  issue_assigned: { color: 'blue', text: '问题分派', icon: <NotificationOutlined /> },
  issue_overdue: { color: 'red', text: '问题逾期', icon: <WarningOutlined /> },
  issue_verified: { color: 'green', text: '问题验证', icon: <CheckCircleOutlined /> },
  review_submitted: { color: 'cyan', text: '审核提交', icon: <MailOutlined /> },
  review_confirmed: { color: 'green', text: '审核确认', icon: <CheckCircleOutlined /> },
  user_sync_failed: { color: 'orange', text: '同步失败', icon: <ExclamationCircleOutlined /> },
  issue_closure_requested: { color: 'purple', text: '关闭申请', icon: <NotificationOutlined /> },
  issue_closure_approved: { color: 'green', text: '关闭批准', icon: <CheckCircleOutlined /> },
  issue_closure_rejected: { color: 'red', text: '关闭驳回', icon: <ExclamationCircleOutlined /> },
};

export default function Notifications() {
  const { message } = App.useApp();
  const [data, setData] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  // 状态筛选: all / unread / read
  const [statusFilter, setStatusFilter] = useState<'all' | 'unread' | 'read'>('all');

  const fetchData = useCallback(async (p: number, ps: number, status: 'all' | 'unread' | 'read') => {
    setLoading(true);
    try {
      const params: { page: number; page_size: number; status?: string } = { page: p, page_size: ps };
      if (status !== 'all') params.status = status;
      const res = await http.get<PageResponse<NotificationItem>>('/notifications', { params });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch {
      // 拦截器统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    fetchData(1, 20, statusFilter);
  }, [fetchData, statusFilter]);

  const handleMarkRead = async (id: number) => {
    try {
      await http.patch(`/notifications/${id}`);
      message.success('已标记为已读');
      fetchData(page, pageSize, statusFilter);
    } catch {
      // 拦截器统一提示
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await http.post('/notifications/mark-read');
      message.success('已全部标记为已读');
      fetchData(page, pageSize, statusFilter);
    } catch {
      // 拦截器统一提示
    }
  };

  // 统计指标
  const unreadCount = data.filter((n) => n.Status === 'unread').length;
  const readCount = data.filter((n) => n.Status === 'read').length;

  const columns: ColumnsType<NotificationItem> = [
    {
      title: '状态',
      dataIndex: 'Status',
      key: 'Status',
      width: 70,
      fixed: 'left',
      render: (val: string) =>
        val === 'unread' ? (
          <Tooltip title="未读">
            <Badge status="error" text={<Text type="danger" style={{ fontSize: 11 }}>未读</Text>} />
          </Tooltip>
        ) : (
          <Tooltip title="已读">
            <Badge status="default" text={<Text type="secondary" style={{ fontSize: 11 }}>已读</Text>} />
          </Tooltip>
        ),
    },
    {
      title: '类型',
      dataIndex: 'Type',
      key: 'Type',
      width: 110,
      render: (val: string | null) => {
        if (!val) return <Text type="secondary">-</Text>;
        const info = typeLabels[val] || { color: 'default', text: val };
        return (
          <Tag color={info.color} style={{ fontSize: 11, margin: 0 }}>
            {info.text}
          </Tag>
        );
      },
    },
    {
      title: '标题',
      dataIndex: 'Title',
      key: 'Title',
      width: 280,
      ellipsis: { showTitle: false },
      render: (val: string, record) => (
        <Tooltip title={val} placement="topLeft">
          <Space size={4} style={{ minWidth: 0, maxWidth: '100%' }}>
            {record.Status === 'unread' && <BellOutlined style={{ color: '#2E5CE6', fontSize: 12 }} />}
            <Text
              style={{
                fontWeight: record.Status === 'unread' ? 600 : 400,
                fontSize: 13,
              }}
              ellipsis
            >
              {val}
            </Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '内容',
      dataIndex: 'Content',
      key: 'Content',
      width: 420,
      ellipsis: { showTitle: false },
      render: (val: string | null) => {
        if (!val) return <Text type="secondary">-</Text>;
        return (
          <Tooltip title={<span style={{ whiteSpace: 'pre-wrap' }}>{val}</span>} placement="topLeft">
            <Text
              type="secondary"
              style={{ fontSize: 12, color: '#595959' }}
              ellipsis
            >
              {val}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: '时间',
      dataIndex: 'CreatedAt',
      key: 'CreatedAt',
      width: 160,
      render: (val: string | null) => {
        if (!val) return <Text type="secondary">-</Text>;
        const d = dayjs(val);
        const now = dayjs();
        const isToday = d.isSame(now, 'day');
        return (
          <Tooltip title={formatDateTime(val)}>
            <Text
              style={{
                fontSize: 11,
                color: isToday ? '#2E5CE6' : '#8c8c8c',
                fontFamily: NUM_FONT,
              }}
            >
              {d.format('MM-DD HH:mm:ss')}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      fixed: 'right',
      render: (_, record) =>
        record.Status === 'unread' ? (
          <Button
            type="link"
            size="small"
            icon={<CheckOutlined />}
            onClick={() => handleMarkRead(record.Id)}
          >
            标已读
          </Button>
        ) : (
          <Text type="secondary" style={{ fontSize: 11 }}>
            —
          </Text>
        ),
    },
  ];

  return (
    <div>
      {/* ============ 顶部统计卡 ============ */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.primary}` }}>
            <CornerMarker color={BRAND.primary} />
            <Statistic
              title={<span style={{ fontSize: 12 }}>通知总数</span>}
              value={total}
              prefix={<NotificationOutlined style={{ color: BRAND.primary }} />}
              valueStyle={{ fontSize: 22, color: BRAND.primary, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.danger}` }}>
            <CornerMarker color={BRAND.danger} />
            <Statistic
              title={<span style={{ fontSize: 12 }}>未读通知</span>}
              value={statusFilter === 'read' ? 0 : unreadCount}
              prefix={<BellOutlined style={{ color: BRAND.danger }} />}
              valueStyle={{
                fontSize: 22,
                color: unreadCount > 0 ? BRAND.danger : BRAND.gray,
                fontFamily: NUM_FONT,
              }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" style={{ ...techCardStyle, borderTop: `3px solid ${BRAND.success}` }}>
            <CornerMarker color={BRAND.success} />
            <Statistic
              title={<span style={{ fontSize: 12 }}>已读通知</span>}
              value={statusFilter === 'unread' ? 0 : readCount}
              prefix={<ReadOutlined style={{ color: BRAND.success }} />}
              valueStyle={{ fontSize: 22, color: BRAND.success, fontFamily: NUM_FONT }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>通知中心</Title>
            <Tag color="blue">{total}</Tag>
            {unreadCount > 0 && <Tag color="red">{unreadCount} 未读</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Segmented
              value={statusFilter}
              onChange={(v) => {
                setStatusFilter(v as 'all' | 'unread' | 'read');
                setPage(1);
              }}
              options={[
                { label: '全部', value: 'all' },
                { label: '未读', value: 'unread' },
                { label: '已读', value: 'read' },
              ]}
              size="small"
            />
            <Button icon={<ReloadOutlined />} onClick={() => fetchData(page, pageSize, statusFilter)}>
              刷新
            </Button>
            <Button type="primary" icon={<CheckOutlined />} onClick={handleMarkAllRead}>
              全部标已读
            </Button>
          </Space>
        }
      >
        <Table<NotificationItem>
          columns={columns}
          dataSource={data}
          rowKey="Id"
          loading={loading}
          size="small"
          scroll={{ x: 1130 }}
          bordered
          locale={{
            emptyText: <Empty description="暂无通知" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
          rowClassName={(record) => (record.Status === 'unread' ? 'notification-unread-row' : '')}
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
              fetchData(p, ps, statusFilter);
            },
          }}
        />
      </Card>

      <style>{`
        .notification-unread-row > td {
          background-color: rgba(22, 119, 255, 0.04) !important;
        }
        .notification-unread-row:hover > td {
          background-color: rgba(22, 119, 255, 0.08) !important;
        }
      `}</style>
    </div>
  );
}
