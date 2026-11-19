<script setup>
import PageHeader from '@/components/PageHeader.vue'
</script>

<template>
  <div class="help-page">
    <PageHeader title="预算 BOL 导入帮助" subtitle="Excel 模板使用说明与导入流程指南" icon="Document" />

    <div class="page-container">
      <div class="help-content">
        <!-- 快速开始 -->
        <section class="help-section">
          <h2 class="section-title">快速开始</h2>
          <div class="section-body">
            <el-steps :active="3" finish-status="success" align-center>
              <el-step title="下载模板" description="选择 Budget BOL 或 Achievable BOL 模板" />
              <el-step title="填写数据" description="按要求填写必填列" />
              <el-step title="上传导入" description="选择年份和类型，上传 Excel" />
              <el-step title="核对结果" description="检查导入统计与错误提示" />
            </el-steps>
          </div>
        </section>

        <!-- 模板类型说明 -->
        <section class="help-section">
          <h2 class="section-title">模板类型</h2>
          <div class="section-body">
            <div class="template-cards">
              <div class="template-card">
                <div class="template-icon budget">
                  <el-icon :size="24"><Coin /></el-icon>
                </div>
                <h3>Budget BOL 模板</h3>
                <p class="template-desc">直接录入预算 BOL 数值，适合已明确目标值的场景</p>
                <div class="template-columns">
                  <h4>必填列</h4>
                  <ul>
                    <li><strong>Project Code</strong> - 项目代码（如 T6763）</li>
                    <li><strong>Budget BOL</strong> - 预算 BOL 值（分钟）</li>
                  </ul>
                  <h4>可选列</h4>
                  <ul>
                    <li><strong>Process Type</strong> - 工艺类型（FA/IHR/OB/FR 等）</li>
                    <li><strong>Asset</strong> - 产线编号</li>
                    <li><strong>Plant</strong> - 工厂（Beijing/Shanghai 等）</li>
                    <li><strong>AME Target BOL</strong> - AME 目标（参考）</li>
                    <li><strong>Achievable BOL</strong> - 可达 BOL（参考）</li>
                  </ul>
                </div>
              </div>

              <div class="template-card">
                <div class="template-icon achievable">
                  <el-icon :size="24"><Cpu /></el-icon>
                </div>
                <h3>Achievable BOL 模板</h3>
                <p class="template-desc">录入 CT/HC，系统自动计算 BOL，支持最多5组子工艺</p>
                <div class="template-columns">
                  <h4>必填列</h4>
                  <ul>
                    <li><strong>Project Code</strong> - 项目代码</li>
                    <li><strong>Process1_ct_second</strong> - 子工艺1 CT（秒）</li>
                    <li><strong>Process1_HC_per_shift</strong> - 子工艺1 HC（人/班）</li>
                  </ul>
                  <h4>可选列</h4>
                  <ul>
                    <li><strong>Process Type</strong> - 工艺类型</li>
                    <li><strong>Asset</strong> - 产线编号</li>
                    <li><strong>Plant</strong> - 工厂</li>
                    <li><strong>Comment1~5</strong> - 子工艺备注（可作为子工艺名称）</li>
                    <li><strong>Process2~5_ct_second</strong> - 子工艺2~5 CT</li>
                    <li><strong>Process2~5_HC_per_shift</strong> - 子工艺2~5 HC</li>
                    <li><strong>OEE Actual</strong> - OEE 值（0~1，默认 0.85）</li>
                  </ul>
                  <h4>自动计算列（无需填写）</h4>
                  <ul>
                    <li><strong>BOL Base</strong> - BOL 基准</li>
                    <li><strong>Uplift Indirect Hours</strong> - 间接工时系数（默认 0.0667）</li>
                    <li><strong>BOL(mins)</strong> - 计算后的 BOL（分钟）</li>
                  </ul>
                </div>
              </div>

              <div class="template-card">
                <div class="template-icon target">
                  <el-icon :size="24"><Aim /></el-icon>
                </div>
                <h3>Target BOL 模板</h3>
                <p class="template-desc">产能规划目标 BOL，结构与 Achievable 类似但 OEE 列在第22列</p>
                <div class="template-columns">
                  <h4>必填列</h4>
                  <ul>
                    <li><strong>Project\n Code</strong> - 项目代码</li>
                    <li><strong>Tact-time bottle-neck station (in seconds)</strong> - 主工艺 CT</li>
                    <li><strong>Number of Operators per Shift</strong> - 主工艺 HC</li>
                  </ul>
                  <h4>可选列</h4>
                  <ul>
                    <li><strong>Process Type</strong> - 工艺类型（FA/IHR/OB/FR/LiG/bonding 等）</li>
                    <li><strong>Asset</strong> - 产线编号</li>
                    <li><strong>Plant</strong> - 工厂</li>
                    <li><strong>Comment</strong> - 主工艺备注</li>
                    <li><strong>CT #2~#5 / HC #2~#5</strong> - 子工艺2~5 CT/HC</li>
                    <li><strong>OEE</strong> - OEE 值（第22列，默认 0.85）</li>
                  </ul>
                  <h4>自动计算列（无需填写）</h4>
                  <ul>
                    <li><strong>BOL\nBase</strong> - BOL 基准</li>
                    <li><strong>Uplift Indirect Hours</strong> - 间接工时系数</li>
                    <li><strong>BOL\n (minutes)</strong> - 计算后的 BOL（分钟）</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- BOL 计算公式 -->
        <section class="help-section">
          <h2 class="section-title">BOL 计算公式</h2>
          <div class="section-body">
            <div class="formula-box">
              <div class="formula-title">Achievable BOL 计算公式</div>
              <div class="formula-content">
                <code>BOL = CT × HC × (1 + 1/15) / OEE / 60</code>
              </div>
              <div class="formula-params">
                <div class="param">
                  <span class="param-name">CT</span>
                  <span class="param-desc">Cycle Time（循环周期，单位：秒）</span>
                </div>
                <div class="param">
                  <span class="param-name">HC</span>
                  <span class="param-desc">Head Count（直接员工数，人/班）</span>
                </div>
                <div class="param">
                  <span class="param-name">1/15</span>
                  <span class="param-desc">间接人员系数（固定值）</span>
                </div>
                <div class="param">
                  <span class="param-name">OEE</span>
                  <span class="param-desc">设备综合效率（0~1，默认 0.85）</span>
                </div>
                <div class="param">
                  <span class="param-name">60</span>
                  <span class="param-desc">秒转分钟</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 导入规则 -->
        <section class="help-section">
          <h2 class="section-title">导入规则</h2>
          <div class="section-body">
            <el-table :data="importRules" stripe border>
              <el-table-column prop="rule" label="规则" width="200" />
              <el-table-column prop="description" label="说明" />
            </el-table>
          </div>
        </section>

        <!-- 注意事项 -->
        <section class="help-section">
          <h2 class="section-title">注意事项</h2>
          <div class="section-body">
            <div class="notice-list">
              <div class="notice-item warning">
                <el-icon><WarningFilled /></el-icon>
                <div class="notice-content">
                  <strong>年份选择</strong>
                  <p>上传前请确认选择了正确的财年，重复上传同年同类型会覆盖旧数据</p>
                </div>
              </div>
              <div class="notice-item info">
                <el-icon><InfoFilled /></el-icon>
                <div class="notice-content">
                  <strong>项目信息自动同步</strong>
                  <p>客户、SOP/EOP、产品类型、Roof Type 等信息由系统通过 CMC cbco_records 自动同步，无需在 Excel 中填写</p>
                </div>
              </div>
              <div class="notice-item info">
                <el-icon><InfoFilled /></el-icon>
                <div class="notice-content">
                  <strong>子工艺拆分</strong>
                  <p>Achievable 类型的一行 Excel 可能拆分为多条记录（每个子工艺一条），子工艺名称优先取 Comment 列值</p>
                </div>
              </div>
              <div class="notice-item warning">
                <el-icon><WarningFilled /></el-icon>
                <div class="notice-content">
                  <strong>数据验证</strong>
                  <p>导入前请检查 Project Code 是否存在于 cbco_records，CT/HC 是否为有效数值</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 返回按钮 -->
        <div class="action-bar">
          <el-button type="primary" @click="$router.push('/budget-bol')">
            <el-icon><ArrowLeft /></el-icon>
            返回预算 BOL 管理
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'BudgetBolHelpView',
  data() {
    return {
      importRules: [
        { rule: '全量替换', description: '导入前自动清空该财年该类型的所有旧记录，再全量导入新数据，确保数据库与 Excel 完全一致' },
        { rule: '事务安全', description: '清空 + 导入 整个操作在数据库事务中执行，任一环节失败自动回滚，旧数据不会丢失' },
        { rule: 'Budget BOL 回退', description: 'Budget BOL 列为空/0 时，按 Achievable BOL → AME Target BOL 顺序回退' },
        { rule: 'OEE 默认值', description: 'OEE Actual 列为空时默认 0.85' },
        { rule: '子工艺拆分', description: 'Achievable 类型按子工艺拆分，一行 Excel 可能生成多条记录' },
        { rule: '地点映射', description: 'Plant 自动映射为标准地点（如 Beijing → BJ Inalfa）' },
      ]
    }
  }
}
</script>

<style scoped>
.help-page {
  min-height: 100%;
  background: transparent;
}

.help-content {
  max-width: 1200px;
  margin: 0 auto;
}

.help-section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}

.section-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 20px 0;
  padding-bottom: 12px;
  border-bottom: 2px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-title::before {
  content: '';
  width: 4px;
  height: 20px;
  background: var(--gradient-primary);
  border-radius: 2px;
}

.section-body {
  color: var(--color-text-secondary);
  line-height: 1.6;
}

/* 模板卡片 */
.template-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.template-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 20px;
  background: var(--color-bg);
}

.template-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  color: #fff;
}

.template-icon.budget {
  background: var(--gradient-accent);
}

.template-icon.achievable {
  background: var(--gradient-cyan);
}

.template-icon.target {
  background: linear-gradient(135deg, #7C3AED 0%, #A855F7 100%);
}

.template-card h3 {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 8px 0;
}

.template-desc {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: 16px;
}

.template-columns h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin: 16px 0 8px 0;
}

.template-columns h4:first-of-type {
  margin-top: 0;
}

.template-columns ul {
  margin: 0;
  padding-left: 20px;
}

.template-columns li {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}

/* 公式框 */
.formula-box {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 20px;
}

.formula-title {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: 12px;
}

.formula-content {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 16px 20px;
  margin-bottom: 16px;
}

.formula-content code {
  font-family: var(--font-mono);
  font-size: 15px;
  color: var(--color-text);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.formula-params {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.param {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 8px 14px;
  flex: 1;
  min-width: 180px;
}

.param-name {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--color-primary);
  font-size: 13px;
}

.param-desc {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 4px;
}

/* 注意事项 */
.notice-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notice-item {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid;
}

.notice-item.warning {
  background: var(--color-accent-glow);
  border-color: rgba(245, 158, 11, 0.3);
}

.notice-item.warning .el-icon {
  color: var(--color-accent);
}

.notice-item.info {
  background: var(--color-primary-glow);
  border-color: rgba(37, 99, 235, 0.2);
}

.notice-item.info .el-icon {
  color: var(--color-primary);
}

.notice-item .el-icon {
  font-size: 20px;
  flex-shrink: 0;
  margin-top: 2px;
}

.notice-content strong {
  display: block;
  font-size: 13px;
  color: var(--color-text);
  margin-bottom: 4px;
}

.notice-content p {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 操作栏 */
.action-bar {
  text-align: center;
  padding: 20px 0;
}

@media (max-width: 1024px) {
  .template-cards {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 768px) {
  .template-cards {
    grid-template-columns: 1fr;
  }
  
  .formula-params {
    flex-direction: column;
  }
  
  .param {
    min-width: auto;
  }
}
</style>