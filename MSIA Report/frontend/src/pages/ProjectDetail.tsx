import { useEffect, useState } from 'react';
import {
  App,
  Card,
  Row,
  Col,
  Descriptions,
  Tag,
  Button,
  Space,
  Typography,
  Skeleton,
  Tooltip,
  Statistic,
  Result,
} from 'antd';
// Descriptions 仍用于工厂/产线信息卡
import {
  ArrowRightOutlined,
  ArrowLeftOutlined,
  ReloadOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  ProjectOutlined,
  UserOutlined,
  ApartmentOutlined,
  DashboardOutlined,
  FileTextOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import {
  getMsiaPlanDetailApi,
  listMsiaPlansApi,
} from '@/api/msiaPlan';
import type {
  MsiaPlanDetail,
  MsiaPlanItem,
} from '@/api/msiaPlan';
import { getPhaseResultsBatch, type PhaseResult } from '@/api/reviews';
import { downloadCombinedReportPdf, downloadPhaseAuditReportPdf } from '@/api/phaseReports';
import PhaseReportModal from '@/components/PhaseReportModal';
import { formatDate, formatDateTime } from '@/utils/format';
import { scoreColor as _sc, scoreTextColor as _stc } from '@/utils/scoreColor';
import { NUM_FONT } from '@/utils/fonts';

const { Title, Text } = Typography;

// 阶段定义: MSIA1 - MSIA5
const ALL_PHASES = [
  { key: '1', label: 'MSIA1', color: '#8c8c8c', desc: '立项启动', timing: 'Project Kick-off' },
  { key: '2', label: 'MSIA2', color: '#2E5CE6', desc: '需求分析', timing: 'Planning & Design' },
  { key: '3', label: 'MSIA3', color: '#0FB5BA', desc: '设计冻结', timing: 'Design Freeze' },
  { key: '4', label: 'MSIA4', color: '#F97316', desc: '预验收', timing: 'Pre-Acceptance' },
  { key: '5', label: 'MSIA5', color: '#10B981', desc: '终验收', timing: 'Final Acceptance' },
] as const;

// 阶段定义: 仅 MSIA3/4/5 (用于进度计算)
const PROGRESS_PHASES = ['3', '4', '5'];

type PhaseStatus = 'pending' | 'in_progress' | 'done';

function getPhaseStatus(planDate: string | null, actualDate: string | null): PhaseStatus {
  if (actualDate) return 'done';
  if (planDate) return 'in_progress';
  return 'pending';
}

const phaseStatusMap: Record<PhaseStatus, { color: string; text: string; icon: React.ReactNode }> = {
  pending: { color: 'default', text: '未开始', icon: <ClockCircleOutlined /> },
  in_progress: { color: 'processing', text: '进行中', icon: <SyncOutlined spin /> },
  done: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
};

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

// 计算整体进度
function getOverallProgress(item: MsiaPlanItem | null): { done: number; total: number; percent: number } {
  if (!item) return { done: 0, total: 3, percent: 0 };
  let done = 0;
  PROGRESS_PHASES.forEach((p) => {
    const actual = item[`msia${p}ActualDate` as keyof MsiaPlanItem] as string | null;
    if (actual) done += 1;
  });
  return { done, total: 3, percent: Math.round((done / 3) * 100) };
}

// 渲染动态字段的 Descriptions 区块 (已废弃, 改为重点展示阶段总览)
// 保留函数定义以便未来需要时恢复
// function renderDynamicBlock(...) { ... }

// 项目详情页 (基于 MSIA 计划实际数据)
export default function ProjectDetail() {
  const { message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MsiaPlanDetail | null>(null);
  const [planItem, setPlanItem] = useState<MsiaPlanItem | null>(null);
  // 当前项目 MSIA 各阶段平均分
  const [phaseResults, setPhaseResults] = useState<PhaseResult[]>([]);
  const [reportModalVisible, setReportModalVisible] = useState(false);
  const [reportPhaseCode, setReportPhaseCode] = useState<string | null>(null);
  // 合并报告模式: 传入 "MSIA1,MSIA2,MSIA3" 时启用, 否则为 null (单阶段模式)
  const [combinedPhases, setCombinedPhases] = useState<string | null>(null);

  // 拉取详情数据
  const fetchDetail = async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      // 1. 获取详情 (含动态字段)
      const detailRes = await getMsiaPlanDetailApi(id);
      setDetail(detailRes);

      // 2. 获取列表项 (通过 planId 在当前页查找, 用于结构化字段展示)
      //    由于 listMsiaPlansApi 支持按 order_id 查询, 这里用 plan 详情中的 orderId 反查
      const planData = detailRes.plan as Record<string, unknown> | null;
      const orderId = planData?.orderId as string | undefined;
      if (orderId) {
        try {
          const listRes = await listMsiaPlansApi({ order_id: orderId, page: 1, page_size: 1 });
          if (listRes.items.length > 0) {
            setPlanItem(listRes.items[0]);
          }
        } catch {
          // 列表查询失败不阻塞详情展示
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetail();
  }, [id]);

  // 拉取当前项目的 MSIA 各阶段平均分
  useEffect(() => {
    if (!id) return;
    getPhaseResultsBatch(id)
      .then((res) => setPhaseResults(res || []))
      .catch(() => setPhaseResults([]));
  }, [id]);

  // 打开阶段审核报告弹窗 (模板格式: Result/Comment/Reviewers/...)
  const openPhaseReport = (phaseCode: string) => {
    setReportPhaseCode(phaseCode);
    setCombinedPhases(null);
    setReportModalVisible(true);
  };

  // 打开 MSIA1+2+3 合并报告弹窗
  const openCombinedReport = () => {
    setReportPhaseCode(null);
    setCombinedPhases('MSIA1,MSIA2,MSIA3');
    setReportModalVisible(true);
  };

  // 导出阶段审核报告 PDF (模板格式, 带错误提示)
  const handleDownloadPdf = async (phaseCode: string) => {
    if (!id) return;
    try {
      await downloadPhaseAuditReportPdf(id, phaseCode);
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败');
    }
  };

  // 导出 MSIA1+2+3 合并报告 PDF
  const handleDownloadCombinedPdf = async () => {
    if (!id) return;
    try {
      await downloadCombinedReportPdf(id, 'MSIA1,MSIA2,MSIA3');
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败');
    }
  };

  // 计算 MSIA1+2+3 平均分 (三个阶段平均分的算数平均)
  const combinedAvgScore = (() => {
    const m1 = phaseResults.find((r) => r.phase_code === 'MSIA1');
    const m2 = phaseResults.find((r) => r.phase_code === 'MSIA2');
    const m3 = phaseResults.find((r) => r.phase_code === 'MSIA3');
    const scores = [m1?.avg_score, m2?.avg_score, m3?.avg_score].filter(
      (v): v is number => v != null,
    );
    if (scores.length === 0) return null;
    return scores.reduce((s, v) => s + v, 0) / scores.length;
  })();

  // 计算阶段日期
  const phaseDates = getPhaseDates(detail?.plan ?? null);

  // 整体进度
  const progress = getOverallProgress(planItem);
  const progressColor = progress.percent === 100 ? '#10B981' : progress.percent >= 67 ? '#0FB5BA' : progress.percent >= 33 ? '#F59E0B' : '#EF4444';

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
        .msia-project-detail-grid-bg {
          background-image:
            linear-gradient(rgba(46, 92, 230, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(46, 92, 230, 0.04) 1px, transparent 1px);
          background-size: 20px 20px;
        }
      `}</style>

      {/* 返回按钮 */}
      <Button
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/projects')}
        style={{ marginBottom: 12, paddingLeft: 0 }}
      >
        返回项目列表
      </Button>

      {/* ============ 顶部基本信息卡 (工业科技风) ============ */}
      <Card
        size="small"
        className="msia-project-detail-grid-bg"
        style={{ marginBottom: 16, borderTop: '3px solid #2E5CE6' }}
      >
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>PROJECT</Text>}
              value={planItem?.projectName || (detail?.plan?.projectName as string) || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600 }}
              prefix={<ProjectOutlined style={{ color: '#2E5CE6' }} />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>OWNER</Text>}
              value={planItem?.ownerName || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600, color: '#2E5CE6' }}
              prefix={<UserOutlined style={{ color: '#2E5CE6' }} />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>LEAD REVIEWER</Text>}
              value={planItem?.leadUser || '-'}
              valueStyle={{ fontSize: 14, fontWeight: 600 }}
              prefix={<UserOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 11, letterSpacing: 1 }}>PROGRESS</Text>}
              value={progress.percent}
              suffix="%"
              valueStyle={{
                fontSize: 18,
                fontWeight: 700,
                color: progressColor,
                fontFamily: NUM_FONT,
              }}
              prefix={<CheckCircleOutlined style={{ color: progressColor }} />}
            />
            <div style={{ width: '100%', height: 4, backgroundColor: '#f0f0f0', borderRadius: 2, overflow: 'hidden', marginTop: 4 }}>
              <div style={{ width: `${progress.percent}%`, height: '100%', backgroundColor: progressColor, transition: 'width 0.3s' }} />
            </div>
          </Col>
        </Row>
      </Card>

      {/* ============ 关键信息卡 (工厂/产线/供应商) ============ */}
      <Card size="small" style={{ marginBottom: 16 }} title={<Space><ApartmentOutlined /><Text strong>工厂 / 产线信息</Text></Space>}>
        <Row gutter={16}>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="工厂">
                {planItem?.plantName ? <Tag color="blue">{planItem.plantName}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="产线">
                {planItem?.lineName || <Text type="secondary">-</Text>}
              </Descriptions.Item>
            </Descriptions>
          </Col>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="产线类型">
                {planItem?.lineType ? <Tag color="geekblue">{planItem.lineType}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="项目类型">
                {planItem?.projectType ? <Tag color="geekblue">{planItem.projectType}</Tag> : <Text type="secondary">-</Text>}
              </Descriptions.Item>
            </Descriptions>
          </Col>
          <Col span={8}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="供应商">
                {planItem?.supplerName || <Text type="secondary">-</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="SME">
                <Space size={4} wrap>
                  {planItem?.sme1 && <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>{planItem.sme1}</Tag>}
                  {planItem?.sme2 && <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>{planItem.sme2}</Tag>}
                  {!planItem?.sme1 && !planItem?.sme2 && <Text type="secondary">-</Text>}
                </Space>
              </Descriptions.Item>
            </Descriptions>
          </Col>
        </Row>
      </Card>

      {/* ============ MSIA Result 指标卡 (当前项目各阶段平均分) ============ */}
      <Card
        size="small"
        style={{ marginBottom: 16, borderTop: '3px solid #2E5CE6' }}
        title={
          <Space>
            <DashboardOutlined style={{ color: '#2E5CE6' }} />
            <Text strong style={{ fontSize: 13 }}>MSIA Result</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>当前项目各阶段评审平均分</Text>
          </Space>
        }
      >
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {ALL_PHASES.map((phase) => {
            const result = phaseResults.find((r) => r.phase_code === phase.label);
            const hasScore = result?.avg_score != null;
            const percent = hasScore ? (result!.avg_score! * 100) : null;
            return (
              <Tooltip
                key={phase.key}
                title={hasScore ? `已评分: ${result!.count} 项 (0% 也计算在内, 未评分不参与)` : '暂无评分数据'}
              >
                <div
                  style={{
                    flex: '1 1 120px',
                    minWidth: 120,
                    padding: '8px 12px',
                    backgroundColor: hasScore ? `${_sc(result!.avg_score)}0a` : '#fafafa',
                    border: `1px solid ${hasScore ? _sc(result!.avg_score) : '#e8e8e8'}`,
                    borderRadius: 4,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 2,
                  }}
                >
                  <Tag
                    style={{
                      backgroundColor: phase.color,
                      color: '#fff',
                      fontWeight: 700,
                      fontFamily: NUM_FONT,
                      fontSize: 10,
                      margin: 0,
                      padding: '0 8px',
                      lineHeight: '18px',
                    }}
                  >
                    {phase.label}
                  </Tag>
                  {hasScore ? (
                    <Text
                      strong
                      style={{
                        fontSize: 20,
                        fontFamily: NUM_FONT,
                        color: _stc(result!.avg_score),
                        lineHeight: 1.3,
                      }}
                    >
                      {percent!.toFixed(1)}
                      <span style={{ fontSize: 11 }}>%</span>
                    </Text>
                  ) : (
                    <Text
                      strong
                      style={{
                        fontSize: 20,
                        fontFamily: NUM_FONT,
                        color: '#bfbfbf',
                        lineHeight: 1.3,
                      }}
                    >
                      —
                    </Text>
                  )}
                  <Text type="secondary" style={{ fontSize: 9 }}>
                    {hasScore ? `${result!.count} items` : 'no data'}
                  </Text>
                </div>
              </Tooltip>
            );
          })}
        </div>
      </Card>

      {/* ============ 阶段总览 (MSIA1 - MSIA5) ============ */}
      <Title level={5} style={{ marginBottom: 12 }}>
        <Space>
          <Text>阶段总览</Text>
          <Tag color="blue" style={{ fontSize: 10 }}>MSIA1 - MSIA5</Tag>
        </Space>
      </Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {ALL_PHASES.flatMap((phase) => {
          const dates = phaseDates[phase.key];
          const planDate = dates?.plan || null;
          const actualDate = dates?.actual || null;
          const status = getPhaseStatus(planDate, actualDate);
          const statusInfo = phaseStatusMap[status];
          const today = dayjs();
          const isOverdue = planDate && !actualDate && dayjs(planDate).isBefore(today, 'day');

          const phaseCard = (
            <Col xs={24} sm={12} lg={8} xl={4} key={phase.key}>
              <Card
                size="small"
                style={{
                  borderTop: `3px solid ${phase.color}`,
                  borderColor: status === 'done' ? phase.color : undefined,
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
                        width: 30,
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
                  <Tooltip title="进入阶段评审" key="review">
                    <Button
                      type="link"
                      size="small"
                      icon={<ArrowRightOutlined />}
                      onClick={() => navigate(`/projects/${id}/phases/${phase.key}`)}
                    >
                      评审
                    </Button>
                  </Tooltip>,
                  <Tooltip title="查看阶段报告" key="report">
                    <Button
                      type="link"
                      size="small"
                      icon={<FileTextOutlined />}
                      onClick={() => openPhaseReport(phase.label)}
                    >
                      报告
                    </Button>
                  </Tooltip>,
                  <Tooltip title="导出 PDF" key="pdf">
                    <Button
                      type="link"
                      size="small"
                      icon={<DownloadOutlined />}
                      onClick={() => handleDownloadPdf(phase.label)}
                    />
                  </Tooltip>,
                ]}
              >
                <Space direction="vertical" size={4} style={{ width: '100%' }}>
                  <Tag color={statusInfo.color} icon={statusInfo.icon}>
                    {statusInfo.text}
                    {isOverdue && ' · 逾期'}
                  </Tag>
                  <Text style={{ fontSize: 12 }}>
                    计划: <Text strong>{formatDate(planDate) || '-'}</Text>
                  </Text>
                  <Text style={{ fontSize: 12 }}>
                    实际: <Text strong style={{ color: status === 'done' ? '#10B981' : undefined }}>
                      {formatDate(actualDate) || '-'}
                    </Text>
                  </Text>
                  <Text type="secondary" style={{ fontSize: 10, fontStyle: 'italic' }}>
                    {phase.timing}
                  </Text>
                </Space>
              </Card>
            </Col>
          );

          // 在 MSIA3 与 MSIA4 之间插入 MSIA1&2&3 汇总报告块
          if (phase.key === '4') {
            const combinedHasScore = combinedAvgScore != null;
            const combinedPercent = combinedHasScore ? combinedAvgScore! * 100 : null;
            const combinedColor = combinedHasScore ? _stc(combinedAvgScore!) : '#722ED1';
            return [
              <Col xs={24} sm={12} lg={8} xl={4} key="msia-combined-summary">
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
                        onClick={openCombinedReport}
                      >
                        报告
                      </Button>
                    </Tooltip>,
                    <Tooltip title="导出汇总 PDF" key="pdf">
                      <Button
                        type="link"
                        size="small"
                        icon={<DownloadOutlined />}
                        onClick={handleDownloadCombinedPdf}
                      />
                    </Tooltip>,
                  ]}
                >
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Tag color="purple">汇总报告</Tag>
                    <Text style={{ fontSize: 12 }}>
                      平均分:{' '}
                      {combinedHasScore ? (
                        <Text
                          strong
                          style={{
                            color: combinedColor,
                            fontFamily: NUM_FONT,
                          }}
                        >
                          {combinedPercent!.toFixed(1)}%
                        </Text>
                      ) : (
                        <Text type="secondary">-</Text>
                      )}
                    </Text>
                    <Text style={{ fontSize: 12 }}>
                      覆盖:{' '}
                      <Text strong>
                        MSIA1 / MSIA2 / MSIA3
                      </Text>
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

      {/* ============ 关键日期 (精简) ============ */}
      {planItem && (
        <Card size="small" style={{ marginTop: 16 }} title={<Space><ClockCircleOutlined /><Text strong>关键日期</Text></Space>}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="工单下发日期"
                value={formatDate(planItem.issueDate) || '-'}
                valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="工单结束日期"
                value={formatDate(planItem.endDate) || '-'}
                valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="计划更新时间"
                value={formatDateTime(planItem.updateDate) || '-'}
                valueStyle={{ fontSize: 13, fontFamily: NUM_FONT }}
              />
            </Col>
          </Row>
        </Card>
      )}

      {/* 阶段审核报告弹窗 (Report MSIA 模板格式) */}
      <PhaseReportModal
        open={reportModalVisible}
        planId={id || ''}
        phaseCode={reportPhaseCode}
        combinedPhases={combinedPhases}
        onClose={() => setReportModalVisible(false)}
      />
    </div>
  );
}
