// MSIA 阶段审核报告弹窗 (按 Report MSIA 模板格式渲染)
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Empty,
  Input,
  Modal,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  DownloadOutlined,
  EditOutlined,
  SaveOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useAuthStore } from '@/store/auth';
import { scoreTextColor as _stc } from '@/utils/scoreColor';
import { NUM_FONT } from '@/utils/fonts';
import {
  downloadPhaseAuditReportPdf,
  getPhaseAuditReport,
  getCombinedAuditReport,
  downloadCombinedReportPdf,
  updatePhaseReviewMeta,
  type AuditReportIssue,
  type PhaseAuditReport,
} from '@/api/phaseReports';

const { Text, Paragraph } = Typography;

// 严重度 Tag 颜色
const severityColor = (sev: string): string => {
  const s = (sev || '').toUpperCase();
  if (s === 'H') return 'red';
  if (s === 'M') return 'orange';
  if (s === 'L') return 'blue';
  return 'default';
};

// Milestones 面板的 5 个项目里程碑时间点 (项目级, 审核员手动维护)
const MS_FIELDS = [
  { key: 'inalfa_kickoff', label: '1. Inalfa kick-off' },
  { key: 'supplier_kickoff', label: '2. Supplier kick-off' },
  { key: 'design_freeze', label: '3. Design freeze' },
  { key: 'pvp', label: '4. PVP' },
  { key: 'inalfa_sop', label: '5. Inalfa SOP' },
] as const;

interface MilestoneValues {
  inalfa_kickoff: string;
  supplier_kickoff: string;
  design_freeze: string;
  pvp: string;
  inalfa_sop: string;
}

const EMPTY_MILESTONES: MilestoneValues = {
  inalfa_kickoff: '',
  supplier_kickoff: '',
  design_freeze: '',
  pvp: '',
  inalfa_sop: '',
};

// 问题行文本: [H] 标题 (编号)
function issueLine(iss: AuditReportIssue, withItem = false): string {
  const sev = (iss.severity || iss.priority || '').toUpperCase() || '?';
  return `[${sev}] ${iss.title} (${iss.issue_no})`;
}

interface PhaseReportModalProps {
  open: boolean;
  planId: string;
  phaseCode: string | null;
  onClose: () => void;
  /** 合并模式: 传入多阶段代码 (如 "MSIA1,MSIA2,MSIA3") */
  combinedPhases?: string | null;
}

export default function PhaseReportModal({ open, planId, phaseCode, onClose, combinedPhases }: PhaseReportModalProps) {
  const { message } = App.useApp();
  const user = useAuthStore((s) => s.user);
  const isAuditor = ['admin', 'lead_reviewer', 'reviewer'].includes(user?.Role || '');
  const isCombined = !!combinedPhases;

  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<PhaseAuditReport | null>(null);
  const [placeEditing, setPlaceEditing] = useState(false);
  const [placeValue, setPlaceValue] = useState('');
  const [placeSaving, setPlaceSaving] = useState(false);
  const [cmcEditing, setCmcEditing] = useState(false);
  const [cmcValue, setCmcValue] = useState('');
  const [cmcSaving, setCmcSaving] = useState(false);
  const [msEditing, setMsEditing] = useState(false);
  const [msValues, setMsValues] = useState<MilestoneValues>(EMPTY_MILESTONES);
  const [msSaving, setMsSaving] = useState(false);
  const [exporting, setExporting] = useState(false);

  // 元数据维护目标阶段: 合并模式取第一个阶段 (项目级字段后端会同步所有阶段)
  const metaPhaseCode = isCombined
    ? (combinedPhases || '').split(',')[0]?.trim() || null
    : phaseCode;

  const fetchData = useCallback(async () => {
    if (!planId) return;
    if (!isCombined && !phaseCode) return;
    setLoading(true);
    try {
      const data = isCombined
        ? await getCombinedAuditReport(planId, combinedPhases!)
        : await getPhaseAuditReport(planId, phaseCode!);
      setReport(data);
      setPlaceValue(data.review_place || 'Teams');
      setCmcValue(data.project?.cmc_ame || '');
      setMsValues({
        inalfa_kickoff: data.milestones?.inalfa_kickoff || '',
        supplier_kickoff: data.milestones?.supplier_kickoff || '',
        design_freeze: data.milestones?.design_freeze || '',
        pvp: data.milestones?.pvp || '',
        inalfa_sop: data.milestones?.inalfa_sop || '',
      });
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [planId, phaseCode, isCombined, combinedPhases]);

  useEffect(() => {
    if (open) {
      setPlaceEditing(false);
      setCmcEditing(false);
      setMsEditing(false);
      fetchData();
    } else {
      setReport(null);
    }
  }, [open, fetchData]);

  // 保存 Review place
  const handleSavePlace = async () => {
    if (!planId || !metaPhaseCode || !placeValue.trim()) return;
    setPlaceSaving(true);
    try {
      await updatePhaseReviewMeta(planId, metaPhaseCode, { review_place: placeValue.trim() });
      message.success('评审地点已更新');
      setPlaceEditing(false);
      fetchData();
    } catch {
      // 拦截器已提示
    } finally {
      setPlaceSaving(false);
    }
  };

  // 保存 CMC AME (项目级, 默认为空, 仅显示手动维护值)
  const handleSaveCmc = async () => {
    if (!planId || !metaPhaseCode) return;
    setCmcSaving(true);
    try {
      await updatePhaseReviewMeta(planId, metaPhaseCode, { cmc_ame: cmcValue.trim() });
      message.success('CMC AME 已更新');
      setCmcEditing(false);
      fetchData();
    } catch {
      // 拦截器已提示
    } finally {
      setCmcSaving(false);
    }
  };

  // 保存 5 个里程碑时间点 (项目级, 同步所有阶段报告)
  const handleSaveMilestones = async () => {
    if (!planId || !metaPhaseCode) return;
    setMsSaving(true);
    try {
      await updatePhaseReviewMeta(planId, metaPhaseCode, {
        inalfa_kickoff: msValues.inalfa_kickoff.trim(),
        supplier_kickoff: msValues.supplier_kickoff.trim(),
        design_freeze: msValues.design_freeze.trim(),
        pvp: msValues.pvp.trim(),
        inalfa_sop: msValues.inalfa_sop.trim(),
      });
      message.success('里程碑时间点已更新');
      setMsEditing(false);
      fetchData();
    } catch {
      // 拦截器已提示
    } finally {
      setMsSaving(false);
    }
  };

  // 导出 PDF
  const handleExportPdf = async () => {
    if (!planId) return;
    setExporting(true);
    try {
      if (isCombined) {
        await downloadCombinedReportPdf(planId, combinedPhases!);
      } else {
        await downloadPhaseAuditReportPdf(planId, phaseCode!);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败');
    } finally {
      setExporting(false);
    }
  };

  // 检查项表格列 (Item / Request / Result / Comments)
  const itemColumns: ColumnsType<PhaseAuditReport['items'][number]> = [
    {
      title: 'Item',
      dataIndex: 'item_name',
      key: 'item_name',
      width: '26%',
      render: (_, r) => (
        <Text style={{ fontSize: 12 }}>{r.item_name}</Text>
      ),
    },
    {
      title: 'Request',
      dataIndex: 'request',
      key: 'request',
      width: '34%',
      render: (v: string) =>
        v ? (
          <Text style={{ fontSize: 11, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{v}</Text>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: 'Result',
      dataIndex: 'result',
      key: 'result',
      width: '10%',
      align: 'center',
      render: (v: string, r) => {
        if (!v) return <Text type="secondary">-</Text>;
        const score = r.score ?? 0;
        const color = _stc(score);
        return (
          <Text strong style={{ color, fontFamily: NUM_FONT }}>
            {v}
          </Text>
        );
      },
    },
    {
      title: 'Comments',
      dataIndex: 'issues',
      key: 'issues',
      width: '30%',
      render: (issues: AuditReportIssue[]) =>
        issues && issues.length > 0 ? (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            {issues.map((iss, idx) => (
              <div key={idx} style={{ fontSize: 12, lineHeight: '18px' }}>
                <Tag color={severityColor(iss.severity)} style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}>
                  {iss.severity || iss.priority}
                </Tag>
                <Text>{iss.title}</Text>{' '}
                <Text type="secondary" style={{ fontSize: 11 }}>({iss.issue_no})</Text>
              </div>
            ))}
          </Space>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>-</Text>
        ),
    },
  ];

  const modalTitle = (
    <Space>
      <Text strong>MSIA 审核报告</Text>
      {isCombined ? (
        <Tag color="purple">MSIA1+2+3 汇总</Tag>
      ) : (
        phaseCode && <Tag color="blue">{phaseCode}</Tag>
      )}
    </Space>
  );

  return (
    <Modal
      title={modalTitle}
      open={open}
      onCancel={onClose}
      width={1000}
      footer={
        <Space>
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExportPdf}
          >
            导出 PDF
          </Button>
          <Button onClick={onClose}>关闭</Button>
        </Space>
      }
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 10 }} />
      ) : !report ? (
        <Empty description="无法加载报告数据" />
      ) : (
        <div>
          {/* ======== 标题区 ======== */}
          <div style={{ textAlign: 'center', marginBottom: 12 }}>
            <Text strong style={{ fontSize: 15 }}>
              Manufacturing System Implementation Assessment Report
            </Text>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {report.phase_code} Review Report
              </Text>
            </div>
          </div>

          {/* ======== 头部: 项目关键数据 + 里程碑 + MSIA 结果 ======== */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <div
              style={{
                flex: 3,
                border: '1px solid #8EA9DB',
                borderRadius: 4,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  backgroundColor: '#4472C4',
                  color: '#fff',
                  fontWeight: 600,
                  fontSize: 12,
                  padding: '4px 12px',
                }}
              >
                Project Key Data
              </div>
              <Descriptions
                size="small"
                column={1}
                styles={{ label: { fontSize: 12, width: 110 }, content: { fontSize: 12 } }}
                style={{ padding: '0 12px 4px' }}
              >
                <Descriptions.Item label="Project name">
                  {report.project.name || <Text type="secondary">-</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="Project No.">
                  {report.project.no || <Text type="secondary">-</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="Project type">
                  {report.project.type || <Text type="secondary">-</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="CMC AME">
                  {cmcEditing ? (
                    <Space.Compact style={{ width: '100%' }}>
                      <Input
                        size="small"
                        value={cmcValue}
                        onChange={(e) => setCmcValue(e.target.value)}
                        onPressEnter={handleSaveCmc}
                        maxLength={255}
                        placeholder="请输入 CMC AME"
                      />
                      <Button
                        size="small"
                        type="primary"
                        icon={<SaveOutlined />}
                        loading={cmcSaving}
                        onClick={handleSaveCmc}
                      />
                    </Space.Compact>
                  ) : (
                    <>
                      {report.project.cmc_ame || <Text type="secondary">-</Text>}{' '}
                      {isAuditor && (
                        <Tooltip title="维护 CMC AME (项目级, 各阶段报告共享)">
                          <Button
                            type="text"
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() => setCmcEditing(true)}
                            style={{ padding: '0 2px' }}
                          />
                        </Tooltip>
                      )}
                    </>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="Plant ME">
                  {report.project.plant_me || <Text type="secondary">-</Text>}
                </Descriptions.Item>
              </Descriptions>
            </div>
            <div
              style={{
                flex: 3,
                border: '1px solid #8EA9DB',
                borderRadius: 4,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  backgroundColor: '#4472C4',
                  color: '#fff',
                  fontWeight: 600,
                  fontSize: 12,
                  padding: '4px 12px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span>Milestones</span>
                {isAuditor && !msEditing && (
                  <Tooltip title="维护里程碑时间点 (项目级, 各阶段报告共享)">
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => setMsEditing(true)}
                      style={{ color: '#fff', padding: '0 2px' }}
                    />
                  </Tooltip>
                )}
              </div>
              {msEditing ? (
                <div style={{ padding: '8px 12px 8px' }}>
                  {MS_FIELDS.map(({ key, label }) => (
                    <div
                      key={key}
                      style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}
                    >
                      <Text style={{ fontSize: 12, width: 126, flexShrink: 0 }}>{label}</Text>
                      <Input
                        size="small"
                        value={msValues[key]}
                        onChange={(e) => setMsValues({ ...msValues, [key]: e.target.value })}
                        maxLength={50}
                        placeholder="如 2026-01-15"
                      />
                    </div>
                  ))}
                  <Space size={4} style={{ marginTop: 2 }}>
                    <Button
                      size="small"
                      type="primary"
                      icon={<SaveOutlined />}
                      loading={msSaving}
                      onClick={handleSaveMilestones}
                    >
                      保存
                    </Button>
                    <Button size="small" onClick={() => setMsEditing(false)}>
                      取消
                    </Button>
                  </Space>
                </div>
              ) : (
                <Descriptions
                  size="small"
                  column={1}
                  styles={{ label: { fontSize: 12, width: 130 }, content: { fontSize: 12 } }}
                  style={{ padding: '0 12px 4px' }}
                >
                  {MS_FIELDS.map(({ key, label }) => (
                    <Descriptions.Item key={key} label={label}>
                      {report.milestones[key] ? (
                        <Text style={{ fontFamily: NUM_FONT }}>{report.milestones[key]}</Text>
                      ) : (
                        <Text type="secondary">-</Text>
                      )}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              )}
            </div>
            <div
              style={{
                flex: 1,
                border: '1px solid #8EA9DB',
                borderRadius: 4,
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <div
                style={{
                  backgroundColor: '#4472C4',
                  color: '#fff',
                  fontWeight: 600,
                  fontSize: 12,
                  padding: '4px 12px',
                }}
              >
                MSIA
              </div>
              <div
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 4,
                  padding: 8,
                }}
              >
                <Text type="secondary" style={{ fontSize: 11 }}>
                  MSIA No.
                </Text>
                <Text strong style={{ fontSize: 22, fontFamily: NUM_FONT }}>
                  {report.msia_no}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  MSIA Result
                </Text>
                <Text
                  strong
                  style={{
                    fontSize: 18,
                    fontFamily: NUM_FONT,
                    color: report.msia_result
                      ? (isCombined
                          ? _stc(parseFloat(report.msia_result) / 100)
                          : '#2E5CE6')
                      : '#bfbfbf',
                  }}
                >
                  {report.msia_result || 'None'}
                </Text>
              </div>
            </div>
          </div>

          {/* ======== High-risk comments (reviewer) ======== */}
          <div
            style={{
              border: '1px solid #ffa39e',
              backgroundColor: '#fff1f0',
              borderRadius: 4,
              padding: '8px 12px',
              marginBottom: 12,
              minHeight: 56,
            }}
          >
            <Space size={4} style={{ marginBottom: 4 }}>
              <WarningOutlined style={{ color: '#EF4444' }} />
              <Text strong style={{ fontSize: 12 }}>
                High-risk comments (reviewer):
              </Text>
            </Space>
            {report.high_risk_issues.length > 0 ? (
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                {report.high_risk_issues.map((hr, idx) => (
                  <div key={idx} style={{ fontSize: 12, lineHeight: '18px' }}>
                    <Tag color="red" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}>
                      H
                    </Tag>
                    {isCombined && hr.phase_code && (
                      <Tag color="purple" style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}>
                        {hr.phase_code}
                      </Tag>
                    )}
                    <Text>{hr.title}</Text>{' '}
                    {hr.item_name && (
                      <Text type="secondary" style={{ fontSize: 11 }}>- {hr.item_name} </Text>
                    )}
                    <Text type="secondary" style={{ fontSize: 11 }}>({hr.issue_no})</Text>
                  </div>
                ))}
              </Space>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                无高风险问题
              </Text>
            )}
          </div>

          {/* ======== 检查项表格 ======== */}
          {isCombined && report.sub_reports ? (
            /* 合并模式: 各阶段竖直叠加, 每个阶段独立表头和尾部 */
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {report.sub_reports.map((sr, idx) => (
                <div key={idx}>
                  <div style={{ marginBottom: 6, marginTop: idx > 0 ? 8 : 0 }}>
                    <Tag color="blue" style={{ fontSize: 11, fontWeight: 700 }}>{sr.phase_code}</Tag>
                    {sr.msia_result && (
                      <Text style={{ fontSize: 11, marginLeft: 8, color: _stc(parseFloat(sr.msia_result) / 100) }}>
                        平均分: {sr.msia_result}
                      </Text>
                    )}
                  </div>
                  <Table
                    size="small"
                    bordered
                    columns={itemColumns}
                    dataSource={sr.items}
                    rowKey={(r) => `${sr.phase_code}-${r.phase_review_item_id}`}
                    pagination={false}
                    scroll={{ y: 240 }}
                    locale={{ emptyText: <Empty description="该阶段暂无检查项" /> }}
                  />
                  {/* 各阶段尾部 */}
                  <div style={{ display: 'grid', gridTemplateColumns: '3fr 2.4fr 2.2fr 2fr', gap: 8, marginTop: 8 }}>
                    <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>Reviewers:</Text>
                      <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                        {sr.reviewers?.length > 0 ? sr.reviewers.join(' / ') : <Text type="secondary">-</Text>}
                      </Paragraph>
                    </div>
                    <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>Review place:</Text>
                      <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                        {sr.review_place || <Text type="secondary">-</Text>}
                      </Paragraph>
                    </div>
                    <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>Reviewees:</Text>
                      <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                        {sr.reviewees || <Text type="secondary">-</Text>}
                      </Paragraph>
                    </div>
                    <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>Date:</Text>
                      <Paragraph style={{ fontSize: 12, marginBottom: 0, fontFamily: NUM_FONT }}>
                        {sr.date || <Text type="secondary">-</Text>}
                      </Paragraph>
                    </div>
                  </div>
                </div>
              ))}
            </Space>
          ) : (
            /* 单阶段模式 */
            <>
              <Table
                size="small"
                bordered
                columns={itemColumns}
                dataSource={report.items}
                rowKey={(r) => r.phase_review_item_id}
                pagination={false}
                scroll={{ y: 320 }}
                locale={{ emptyText: <Empty description="该阶段暂无检查项" /> }}
              />

              {/* ======== 尾部: Reviewers / Review place / Reviewees / Date ======== */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '3fr 2.4fr 2.2fr 2fr',
                  gap: 8,
                  marginTop: 12,
                }}
              >
                <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    Reviewers:
                  </Text>
                  <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                    {report.reviewers.length > 0 ? report.reviewers.join(' / ') : <Text type="secondary">-</Text>}
                  </Paragraph>
                </div>
                <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    Review place:
                  </Text>
                  {placeEditing ? (
                    <Space.Compact style={{ width: '100%', marginTop: 2 }}>
                      <Input
                        size="small"
                        value={placeValue}
                        onChange={(e) => setPlaceValue(e.target.value)}
                        onPressEnter={handleSavePlace}
                        maxLength={500}
                      />
                      <Button
                        size="small"
                        type="primary"
                        icon={<SaveOutlined />}
                        loading={placeSaving}
                        onClick={handleSavePlace}
                      />
                    </Space.Compact>
                  ) : (
                    <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                      {report.review_place || <Text type="secondary">-</Text>}{' '}
                      {isAuditor && (
                        <Tooltip title="维护评审地点">
                          <Button
                            type="text"
                            size="small"
                            icon={<EditOutlined />}
                            onClick={() => setPlaceEditing(true)}
                            style={{ padding: '0 2px' }}
                          />
                        </Tooltip>
                      )}
                    </Paragraph>
                  )}
                </div>
                <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    Reviewees:
                  </Text>
                  <Paragraph style={{ fontSize: 12, marginBottom: 0 }}>
                    {report.reviewees || <Text type="secondary">-</Text>}
                  </Paragraph>
                </div>
                <div style={{ border: '1px solid #8EA9DB', borderRadius: 4, padding: '4px 8px' }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    Date:
                  </Text>
                  <Paragraph
                    style={{
                      fontSize: 12,
                      marginBottom: 0,
                      fontFamily: NUM_FONT,
                    }}
                  >
                    {report.date || <Text type="secondary">-</Text>}
                  </Paragraph>
                </div>
              </div>
            </>
          )}

          {/* 说明 */}
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 12 }}
            message={
              <span style={{ fontSize: 12 }}>
                Request 列为该检查项的审核标准要求 (100% 档评分描述); Result 列为检查项最新评分 (未评分为空);
                Comments 列为该检查项下审核员登记的问题;
                Reviewers 为参与评审 (提交问题/评分) 的用户; Date 为最后一次提交问题或评分的时间。
                {isAuditor &&
                  ' Review place、CMC AME 与 Milestones 里程碑时间点可点击编辑维护; CMC AME 与里程碑为项目级数据, 各阶段报告共享, 未维护时显示为空。'}
              </span>
            }
          />
        </div>
      )}
    </Modal>
  );
}
