import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SaveOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useAuthStore } from '@/store/auth';
import {
  deleteHistoricScoreApi,
  listHistoricScoreProjectsApi,
  saveHistoricScoresApi,
} from '@/api/historicScores';
import type { HistoricScoreProjectItem } from '@/api/historicScores';
import { techCardStyle } from '@/styles/shared';

const { Title, Text } = Typography;

// MSIA 阶段定义
const PHASES = ['MSIA1', 'MSIA2', 'MSIA3', 'MSIA4', 'MSIA5'] as const;

// 阶段配色
const phaseColors: Record<string, string> = {
  MSIA1: 'blue',
  MSIA2: 'cyan',
  MSIA3: 'geekblue',
  MSIA4: 'orange',
  MSIA5: 'green',
};

interface PhaseDraft {
  score: number | null;
  remark: string;
}

export default function HistoricScore() {
  const { message } = App.useApp();
  const user = useAuthStore((s) => s.user);
  const isAdminOrLead = user?.Role === 'admin' || user?.Role === 'lead_reviewer';

  // 列表
  const [data, setData] = useState<HistoricScoreProjectItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState('');
  const [searchText, setSearchText] = useState('');

  // 录入抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<HistoricScoreProjectItem | null>(null);
  const [drafts, setDrafts] = useState<Record<string, PhaseDraft>>({});
  const [saving, setSaving] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listHistoricScoreProjectsApi({
        keyword: searchText || undefined,
        page,
        page_size: pageSize,
      });
      setData(res.items || []);
      setTotal(res.total || 0);
    } catch {
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [searchText, page, pageSize]);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  // 打开录入抽屉
  const openEditor = (item: HistoricScoreProjectItem) => {
    setEditing(item);
    // 用已录入评分初始化草稿
    const initial: Record<string, PhaseDraft> = {};
    PHASES.forEach((p) => {
      const entered = item.entered_phases_map?.[p];
      initial[p] = {
        score: entered ? entered.score_percent : null,
        remark: entered?.remark || '',
      };
    });
    setDrafts(initial);
    setDrawerOpen(true);
  };

  const setDraft = (phase: string, patch: Partial<PhaseDraft>) => {
    setDrafts((prev) => ({
      ...prev,
      [phase]: { ...prev[phase], ...patch },
    }));
  };

  // 保存
  const handleSave = async () => {
    if (!editing) return;
    const scores = PHASES.filter((p) => drafts[p]?.score != null).map((p) => ({
      phase_code: p,
      score: drafts[p].score as number,
      remark: drafts[p].remark || null,
    }));
    if (scores.length === 0) {
      message.warning('请至少录入一个阶段的评分');
      return;
    }
    setSaving(true);
    try {
      await saveHistoricScoresApi(String(editing.planId), {
        order_id: editing.orderId,
        project_name: editing.projectName,
        scores,
      });
      message.success(`已保存 ${scores.length} 个阶段评分`);
      setDrawerOpen(false);
      fetchList();
    } catch {
      // 错误已由拦截器提示
    } finally {
      setSaving(false);
    }
  };

  // 删除某阶段评分
  const handleDelete = async (phase: string) => {
    if (!editing) return;
    try {
      await deleteHistoricScoreApi(String(editing.planId), phase);
      message.success(`已删除 ${phase} 历史评分`);
      setDraft(phase, { score: null, remark: '' });
      fetchList();
    } catch {
      // 忽略
    }
  };

  const columns: ColumnsType<HistoricScoreProjectItem> = [
    {
      title: '项目名称',
      key: 'projectName',
      width: 240,
      render: (_, r) => (
        <div>
          <div style={{ fontWeight: 600 }}>{r.projectName || '-'}</div>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.orderId || ''}</Text>
        </div>
      ),
    },
    {
      title: '工单描述',
      dataIndex: 'order_description',
      key: 'order_description',
      ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '负责人',
      dataIndex: 'ownerName',
      key: 'ownerName',
      width: 110,
      render: (v: string | null) => v || '-',
    },
    {
      title: '工厂/产线',
      key: 'plant',
      width: 150,
      render: (_, r) => (
        <Text>
          {r.plantName || '-'}
          {r.lineName ? ` / ${r.lineName}` : ''}
        </Text>
      ),
    },
    {
      title: '已录入阶段',
      key: 'entered',
      width: 260,
      render: (_, r) =>
        r.entered_phase_count > 0 ? (
          <Space size={[4, 4]} wrap>
            {PHASES.map((p) => {
              const s = r.entered_phases_map?.[p];
              return s ? (
                <Tag key={p} color={phaseColors[p]}>
                  {p} {s.score_percent}%
                </Tag>
              ) : null;
            })}
          </Space>
        ) : (
          <Text type="secondary">未录入</Text>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_, r) => (
        <Button
          type="primary"
          ghost
          size="small"
          icon={<EditOutlined />}
          onClick={() => openEditor(r)}
        >
          {r.entered_phase_count > 0 ? '修改' : '录入'}
        </Button>
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Card style={techCardStyle} styles={{ body: { padding: 16 } }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <Title level={4} style={{ margin: 0 }}>
              <HistoryOutlined /> 历史评分录入
            </Title>
            <Text type="secondary">
              适用于系统上线前已审核完成的项目：直接录入各阶段评分（如 MSIA1 78%），无需逐条评价检查项。
            </Text>
          </div>
          <Space>
            <Input
              placeholder="搜索项目名称 / 工单号"
              allowClear
              prefix={<SearchOutlined />}
              style={{ width: 260 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={() => {
                setPage(1);
                setSearchText(keyword);
              }}
            />
            <Button
              type="primary"
              icon={<SearchOutlined />}
              onClick={() => {
                setPage(1);
                setSearchText(keyword);
              }}
            >
              搜索
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchList} />
          </Space>
        </div>

        {!isAdminOrLead && (
          <Alert
            type="warning"
            showIcon
            message="当前账号无历史评分录入权限，仅 Lead 审核员 / 管理员可录入。"
            style={{ marginBottom: 12 }}
          />
        )}

        <Table
          rowKey="planId"
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 个项目`,
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
          locale={{ emptyText: <Empty description="暂无项目" /> }}
          scroll={{ x: 1000 }}
        />
      </Card>

      {/* 录入抽屉 */}
      <Drawer
        title={editing ? `历史评分录入 - ${editing.projectName || editing.orderId}` : '历史评分录入'}
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={
          <div style={{ textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setDrawerOpen(false)}>取消</Button>
              <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
                保存评分
              </Button>
            </Space>
          </div>
        }
      >
        {editing && (
          <>
            <Card size="small" style={{ marginBottom: 16 }}>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="项目名称">{editing.projectName || '-'}</Descriptions.Item>
                <Descriptions.Item label="工单号">{editing.orderId || '-'}</Descriptions.Item>
                <Descriptions.Item label="负责人">{editing.ownerName || '-'}</Descriptions.Item>
                <Descriptions.Item label="工厂/产线">
                  {editing.plantName || '-'}
                  {editing.lineName ? ` / ${editing.lineName}` : ''}
                </Descriptions.Item>
              </Descriptions>
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                showIcon
                message="正常流程需逐条评价检查项后取平均分；此处适用于项目在系统上线前已完成审核，直接录入阶段总分（百分比 0-100）。"
              />
            </Card>

            {PHASES.map((phase) => {
              const draft = drafts[phase] || { score: null, remark: '' };
              const hasEntered = draft.score != null;
              return (
                <Card
                  key={phase}
                  size="small"
                  style={{
                    marginBottom: 12,
                    borderColor: hasEntered ? '#6EE7B7' : '#C9D9F0',
                  }}
                  title={
                    <Space>
                      <Badge color={phaseColors[phase]} text={<Text strong>{phase}</Text>} />
                      {hasEntered ? (
                        <Tag color="success" icon={<CheckCircleOutlined />}>
                          已录入
                        </Tag>
                      ) : (
                        <Tag>未录入</Tag>
                      )}
                    </Space>
                  }
                >
                  <Space align="start" style={{ width: '100%' }} wrap>
                    <div style={{ width: 150 }}>
                      <div style={{ marginBottom: 4 }}>
                        <Text type="secondary">阶段评分 (%)</Text>
                      </div>
                      <InputNumber
                        min={0}
                        max={100}
                        precision={2}
                        value={draft.score}
                        onChange={(v) => setDraft(phase, { score: v })}
                        placeholder="如 78"
                        style={{ width: '100%' }}
                        suffix="%"
                      />
                    </div>
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <div style={{ marginBottom: 4 }}>
                        <Text type="secondary">备注（可选）</Text>
                      </div>
                      <Input
                        value={draft.remark}
                        onChange={(e) => setDraft(phase, { remark: e.target.value })}
                        placeholder="录入说明"
                        maxLength={200}
                      />
                    </div>
                    <div>
                      <div style={{ marginBottom: 4 }}>&nbsp;</div>
                      <Popconfirm
                        title={`确认删除 ${phase} 的历史评分？`}
                        onConfirm={() => handleDelete(phase)}
                        disabled={!hasEntered}
                      >
                        <Button danger icon={<DeleteOutlined />} disabled={!hasEntered}>
                          删除
                        </Button>
                      </Popconfirm>
                    </div>
                  </Space>
                </Card>
              );
            })}
          </>
        )}
      </Drawer>
    </div>
  );
}
