<template>
  <div class="actual-ct-page">
    <PageHeader title="实测CT" icon="Monitor" subtitle="SCT vs ACT 对比、线平衡分析、箱线图" />

    <div class="page-container">
      <!-- Tab 块 -->
      <el-tabs v-model="activeTab" type="border-card" class="analysis-tabs" @tab-change="onTabChange">
        <!-- ===== SCT Vs ACT ===== -->
        <el-tab-pane label="SCT Vs ACT" name="SCT_VS_ACT">
          <div class="sct-filter-bar">
            <el-select v-model="sctCompanyFilter" placeholder="工厂（空=全部）" clearable size="default" style="width: 160px" @change="onSctCompanyChange">
              <el-option v-for="c in filterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="sctProcessFilter" placeholder="工艺" clearable size="default" style="width: 120px; margin-left: 8px">
              <el-option v-for="p in sctProcessOptions" :key="p" :label="p === '-' ? '无SCT' : p" :value="p" />
            </el-select>
            <span class="sct-filter-count">共 {{ filteredSctItems.length }} 条</span>
          </div>

          <div v-if="sctLoading" class="loading-hint">加载中...</div>
          <template v-else>
            <!-- SCT vs ACT 柱形对比图 -->
            <ChartCard v-if="filteredSctItems.length" title="SCT vs ACT 对比" :subtitle="(sctCompanyFilter || '全部工厂') + ' · 共 ' + filteredSctItems.length + ' 条'" :option="sctChartOption" :height="400" />

            <el-table :data="sortedSctItems" stripe border size="small" max-height="450" style="width: 100%; margin-top: 16px" :row-class-name="sctRowClass">
            <el-table-column prop="company" label="工厂" width="70" />
            <el-table-column prop="line_nr" label="产线" width="90" />
            <el-table-column prop="project_code" label="项目代码" width="100" />
            <el-table-column prop="project_name" label="项目名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="process" label="工艺" width="60" />
            <el-table-column label="SCT" width="85" align="right">
              <template #default="{ row }">
                <span class="num-cell">{{ row.sct !== null ? row.sct + ' s' : '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="ACT" width="85" align="right">
              <template #default="{ row }">
                <span class="num-cell">{{ row.act }} s</span>
              </template>
            </el-table-column>
            <el-table-column label="Gap" width="95" align="right">
              <template #default="{ row }">
                <span class="num-cell" :style="{ color: row.gap > 0 ? 'var(--color-success)' : (row.gap < 0 ? 'var(--color-danger)' : 'var(--color-text-muted)') }">
                  {{ row.gap !== null ? (row.gap > 0 ? '+' : '') + row.gap + ' s' : '-' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="比例" width="95" align="right">
              <template #default="{ row }">
                <span class="num-cell" :style="{ color: Math.abs(row.gap_pct) > 20 ? 'var(--color-danger)' : (row.gap_pct > 0 ? 'var(--color-success)' : (row.gap_pct < 0 ? 'var(--color-warning)' : 'var(--color-text-muted)')), fontWeight: Math.abs(row.gap_pct) > 20 ? 700 : 400 }">
                  {{ row.gap_pct !== null ? (row.gap_pct > 0 ? '+' : '') + row.gap_pct + '%' : '-' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="bol_nr" label="BOL编号" width="160" show-overflow-tooltip />
          </el-table>
          </template>
        </el-tab-pane>

        <!-- ===== ACT CT 趋势 TOP10 ===== -->
        <el-tab-pane label="ACT CT 趋势 TOP10" name="TREND_TOP">
          <div class="sct-filter-bar">
            <el-select v-model="trendCompany" placeholder="工厂（空=全部）" clearable size="default" style="width: 160px" @change="loadTrendTop">
              <el-option v-for="c in filterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <el-radio-group v-model="trendMode" size="default" style="margin-left: 8px">
              <el-radio-button label="mom">环比（vs 前3个月）</el-radio-button>
              <el-radio-button label="yoy">同比（vs 去年同期）</el-radio-button>
            </el-radio-group>
            <span v-if="trendData" class="sct-filter-count">{{ trendPeriodText }}</span>
          </div>

          <div v-if="trendLoading" class="loading-hint">加载中...</div>
          <template v-else-if="trendData">
            <el-row :gutter="16">
              <el-col :span="12">
                <ChartCard title="下降 TOP10（ACT CT 改善）" :subtitle="trendChartSubtitle" :option="trendDropOption" :height="420" />
              </el-col>
              <el-col :span="12">
                <ChartCard title="上升 TOP10（ACT CT 恶化）" :subtitle="trendChartSubtitle" :option="trendRiseOption" :height="420" />
              </el-col>
            </el-row>
          </template>
          <div v-else class="loading-hint">暂无数据</div>
        </el-tab-pane>

        <!-- ===== ACT vs Std 超差清单 ===== -->
        <el-tab-pane label="ACT vs Std 超差清单" name="ACT_STD_DEV">
          <div class="sct-filter-bar">
            <el-select v-model="devCompany" placeholder="工厂（空=全部）" clearable size="default" style="width: 160px" @change="loadDeviation">
              <el-option v-for="c in filterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <span style="margin-left: 8px">偏差阈值 |ACT−Std|/Std &gt;</span>
            <el-input-number v-model="devThreshold" :min="1" :max="100" :step="5" size="default" style="width: 110px; margin-left: 8px" @change="loadDeviation" />
            <span style="margin-left: 2px">%</span>
            <span v-if="devData" class="sct-filter-count">
              匹配 {{ devData.stats.matched }} 对 · 超差 <b style="color: var(--color-danger)">{{ devData.stats.over_count }}</b>
              （偏高 {{ devData.stats.above_count }} / 偏低 {{ devData.stats.below_count }}）
            </span>
          </div>

          <div v-if="devLoading" class="loading-hint">加载中...</div>
          <template v-else-if="devData">
            <ChartCard v-if="devData.items.length" title="ACT vs Std 哑铃图 TOP20（按 |偏差%| 降序）" subtitle="纵轴 = 差值（ACT − Std，秒）· 浅蓝点 = Std 基准（0）· 深蓝点 = ACT 差值 · 连线红 = 偏高（慢于标准）/ 绿 = 偏低（快于标准）" :option="devChartOption" :height="500" />
            <el-table :data="devData.items" stripe border size="small" max-height="450" style="width: 100%; margin-top: 16px">
              <el-table-column prop="company" label="工厂" width="70" />
              <el-table-column prop="line_nr" label="产线" width="90" />
              <el-table-column prop="project_code" label="项目代码" width="100" />
              <el-table-column prop="project_name" label="项目名称" min-width="160" show-overflow-tooltip />
              <el-table-column prop="process" label="工艺" width="60" />
              <el-table-column label="Std" width="85" align="right">
                <template #default="{ row }">
                  <span class="num-cell">{{ row.std }} s</span>
                </template>
              </el-table-column>
              <el-table-column label="ACT" width="85" align="right">
                <template #default="{ row }">
                  <span class="num-cell">{{ row.act }} s</span>
                </template>
              </el-table-column>
              <el-table-column label="偏差" width="95" align="right">
                <template #default="{ row }">
                  <span class="num-cell">{{ (row.deviation > 0 ? '+' : '') + row.deviation + ' s' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="偏差%" width="95" align="right">
                <template #default="{ row }">
                  <span class="num-cell" :style="{ color: row.deviation_pct > 0 ? 'var(--color-danger)' : 'var(--color-success)', fontWeight: 700 }">
                    {{ (row.deviation_pct > 0 ? '+' : '') + row.deviation_pct + '%' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="bol_nr" label="BOL编号" width="160" show-overflow-tooltip />
              <el-table-column label="Std提交日期" width="110" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ (row.submit_date || '').split('T')[0] || '-' }}
                </template>
              </el-table-column>
            </el-table>
          </template>
          <div v-else class="loading-hint">暂无数据</div>
        </el-tab-pane>

        <!-- ===== Real Line Balance ===== -->
        <el-tab-pane label="Real Line Balance" name="LINE_BALANCE">
          <!-- 级联筛选器（仅对 LB 和箱线图生效） -->
          <div class="cascade-filter-bar">
            <el-select v-model="filters.company" placeholder="工厂名称" clearable size="default" style="width: 150px" @change="onCompanyChange">
              <el-option v-for="c in filterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="filters.line_nr" placeholder="产线名称" clearable size="default" style="width: 140px; margin-left: 10px" :disabled="!filters.company" @change="onLineChange">
              <el-option v-for="l in filterOptions.lines" :key="l" :label="l" :value="l" />
            </el-select>
            <el-select v-model="filters.project_code" placeholder="项目编号" clearable filterable size="default" style="width: 160px; margin-left: 10px" :disabled="!filters.company || !filters.line_nr" @change="onProjectChange">
              <el-option v-for="p in filterOptions.projects" :key="p.code" :label="p.code" :value="p.code" />
            </el-select>
            <el-input v-model="projectName" placeholder="项目名称" readonly size="default" style="width: 240px; margin-left: 10px" />
            <el-button type="primary" size="default" style="margin-left: 12px" :disabled="!canQuery" @click="queryLbBp">查询</el-button>
          </div>

          <div v-if="lbLoading" class="loading-hint">加载中...</div>
          <template v-else-if="lbData">
            <div class="lb-summary">
              <div class="lb-summary-item">
                <div class="lb-summary-label">线平衡率</div>
                <div class="lb-summary-value" :style="{ color: lbData.line_balance_rate >= 85 ? 'var(--color-success)' : (lbData.line_balance_rate >= 70 ? 'var(--color-warning)' : 'var(--color-danger)') }">{{ lbData.line_balance_rate }}%</div>
              </div>
              <div class="lb-summary-item">
                <div class="lb-summary-label">工位数</div>
                <div class="lb-summary-value">{{ lbData.station_count }}</div>
              </div>
              <div class="lb-summary-item">
                <div class="lb-summary-label">瓶颈工位</div>
                <div class="lb-summary-value">{{ lbData.bottleneck_station }}</div>
              </div>
              <div class="lb-summary-item">
                <div class="lb-summary-label">瓶颈CT</div>
                <div class="lb-summary-value">{{ lbData.bottleneck_ct }} s</div>
              </div>
            </div>
            <ChartCard
              title="线平衡图"
              :subtitle="`${lbData.company} · ${lbData.line_nr} · ${lbData.project_code}`"
              :option="lbChartOption"
              :height="380"
              @chart-click="handleStationBarClick"
            />

            <el-dialog v-model="stationDetailDialogVisible" :title="stationDetailTitle" width="900px" top="6vh">
              <div v-loading="stationDetailLoading" element-loading-text="正在分析工位工时...">
                <div class="station-detail-summary">
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">项目</div>
                    <div class="station-detail-metric-value">{{ stationDetail.project_name || stationDetail.project_code }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">工厂</div>
                    <div class="station-detail-metric-value">{{ stationDetail.company }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">产线</div>
                    <div class="station-detail-metric-value">{{ stationDetail.line_nr }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">工位</div>
                    <div class="station-detail-metric-value">{{ stationDetail.station_nr }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">样本数</div>
                    <div class="station-detail-metric-value">{{ stationDetail.sample_count }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">代表CT</div>
                    <div class="station-detail-metric-value" style="color: var(--color-primary, #0ea5e9); font-weight: 600;">{{ stationDetail.represent_ct != null ? stationDetail.represent_ct + ' s' : '-' }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">异常点</div>
                    <div class="station-detail-metric-value" :class="{ 'is-anomaly': stationDetail.anomaly_count > 0 }">{{ stationDetail.anomaly_count }}</div>
                  </div>
                  <div class="station-detail-metric">
                    <div class="station-detail-metric-label">过程状态</div>
                    <div class="station-detail-metric-value" :style="{ color: stationDetail.xbar_r_chart?.is_in_control ? 'var(--color-success, #10b981)' : 'var(--color-danger, #ef4444)', fontWeight: 600 }">
                      {{ stationDetail.xbar_r_chart?.is_in_control ? '受控' : '失控' }}
                    </div>
                  </div>
                </div>

                <!-- 时间范围选择器 -->
                <div class="station-date-range-bar">
                  <span class="range-label">数据时间范围：</span>
                  <el-select v-model="stationDateRange" size="small" style="width: 130px" @change="onDateRangeChange">
                    <el-option label="近 3 个月" value="3m" />
                    <el-option label="近 6 个月" value="6m" />
                    <el-option label="近 1 年" value="1y" />
                    <el-option label="近 2 年" value="2y" />
                    <el-option label="全部历史" value="all" />
                  </el-select>
                  <span class="range-info" v-if="stationDetail.period">
                    当前：{{ stationDetail.period.start_date }} 至 {{ stationDetail.period.end_date }} · 样本 {{ stationDetail.period.sample_count || 0 }} 条
                  </span>
                </div>

                <el-tabs v-model="stationDetailActiveTab" type="border-card" class="station-detail-tabs">
                  <el-tab-pane label="工位节拍直方图" name="histogram">
                    <div class="histogram-toolbar">
                      <span class="histogram-toolbar-label">分组宽度：</span>
                      <el-select v-model="histogramBinSize" size="small" style="width: 110px" @change="onHistogramBinSizeChange">
                        <el-option label="自动" value="auto" />
                        <el-option label="2 秒" :value="2" />
                        <el-option label="5 秒" :value="5" />
                        <el-option label="10 秒" :value="10" />
                        <el-option label="20 秒" :value="20" />
                        <el-option label="30 秒" :value="30" />
                      </el-select>
                      <span v-if="stationDetail.histogram?.filtered_out > 0" class="histogram-filter-info">
                        已剔除异常 {{ stationDetail.histogram.filtered_out }} 条（IQR 范围: {{ stationDetail.histogram.iqr_lower }}~{{ stationDetail.histogram.iqr_upper }}s）
                      </span>
                      <span v-else-if="stationDetail.histogram?.total > 0" class="histogram-filter-info">
                        样本 {{ stationDetail.histogram.total }} 条，无异常剔除
                      </span>
                    </div>
                    <ChartCard title="工位节拍直方图" :subtitle="`${stationDetail.period?.start_date} 至 ${stationDetail.period?.end_date}`" :option="stationHistogramOption" :height="320" />
                  </el-tab-pane>
                  <el-tab-pane label="工位节拍工时均值极差图" name="daily">
                    <ChartCard title="工位节拍工时均值极差图" :subtitle="`最近 ${stationDetail.period?.months || 3} 个月的日均值与极差`" :option="stationDailyOption" :height="300" />
                  </el-tab-pane>
                  <el-tab-pane label="休哈特控制图 (Xbar-R)" name="xbar_r">
                    <div class="xbar-r-info">
                      <span class="xbar-r-status" :class="{ 'is-in-control': stationDetail.xbar_r_chart?.is_in_control, 'is-out-of-control': !stationDetail.xbar_r_chart?.is_in_control }">
                        {{ stationDetail.xbar_r_chart?.message || '无数据' }}
                      </span>
                      <span v-if="stationDetail.xbar_r_chart?.rules_violated?.length" class="xbar-r-rules">
                        违反规则：{{ stationDetail.xbar_r_chart.rules_violated.join('、') }}
                      </span>
                    </div>
                    <ChartCard title="Xbar 均值控制图" :subtitle="`CL=${stationDetail.xbar_r_chart?.xbar_chart?.cl} · UCL=${stationDetail.xbar_r_chart?.xbar_chart?.ucl} · LCL=${stationDetail.xbar_r_chart?.xbar_chart?.lcl}`" :option="xbarChartOption" :height="280" />
                    <ChartCard title="R 极差控制图" :subtitle="`CL=${stationDetail.xbar_r_chart?.r_chart?.cl} · UCL=${stationDetail.xbar_r_chart?.r_chart?.ucl} · LCL=${stationDetail.xbar_r_chart?.r_chart?.lcl}`" :option="rChartOption" :height="280" />
                  </el-tab-pane>
                </el-tabs>

                <div v-if="stationDetail.diagnosis?.summary" class="station-detail-diagnosis">
                  <div class="station-detail-notice">
                    <strong>诊断结论：</strong> {{ stationDetail.diagnosis.summary }}
                  </div>
                  <div class="diagnosis-card-group">
                    <div class="diagnosis-card">
                      <div class="diagnosis-title">异常原因建议</div>
                      <ul>
                        <li v-for="(item, index) in stationDetail.diagnosis.likely_causes || []" :key="index">{{ item }}</li>
                      </ul>
                    </div>
                    <div class="diagnosis-card">
                      <div class="diagnosis-title">改善机会推荐</div>
                      <ul>
                        <li v-for="(item, index) in stationDetail.diagnosis.improvement_opportunities || []" :key="index">{{ item }}</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </el-dialog>
          </template>
          <el-empty v-else :description="lbError || '请选择筛选条件后点击查询'" />
        </el-tab-pane>

        <!-- ===== 箱线图 ===== -->
        <el-tab-pane label="箱线图" name="BOX_PLOT">
          <!-- 级联筛选器（复用 LB 的） -->
          <div class="cascade-filter-bar">
            <el-select v-model="filters.company" placeholder="工厂名称" clearable size="default" style="width: 150px" @change="onCompanyChange">
              <el-option v-for="c in filterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select v-model="filters.line_nr" placeholder="产线名称" clearable size="default" style="width: 140px; margin-left: 10px" :disabled="!filters.company" @change="onLineChange">
              <el-option v-for="l in filterOptions.lines" :key="l" :label="l" :value="l" />
            </el-select>
            <el-select v-model="filters.project_code" placeholder="项目编号" clearable filterable size="default" style="width: 160px; margin-left: 10px" :disabled="!filters.company || !filters.line_nr" @change="onProjectChange">
              <el-option v-for="p in filterOptions.projects" :key="p.code" :label="p.code" :value="p.code" />
            </el-select>
            <el-input v-model="projectName" placeholder="项目名称" readonly size="default" style="width: 240px; margin-left: 10px" />
            <el-button type="primary" size="default" style="margin-left: 12px" :disabled="!canQuery" @click="queryLbBp">查询</el-button>
          </div>

          <div v-if="bpLoading" class="loading-hint">加载中...</div>
          <template v-else-if="bpData">
            <ChartCard title="工位CT分布（箱线图）" :subtitle="`${bpData.company} · ${bpData.line_nr} · ${bpData.project_code}`" :option="boxPlotOption" :height="420" />
          </template>
          <el-empty v-else description="请选择筛选条件后点击查询" />
        </el-tab-pane>

        <!-- ===== Actual CT 检索 ===== -->
        <el-tab-pane label="Actual CT 检索" name="SEARCH">
          <div class="search-filter-bar" v-loading="searchFilterLoading" element-loading-text="加载级联选项...">
            <el-select
              v-model="searchFilters.company"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="工厂（选后自动过滤产线）"
              size="default"
              style="width: 180px"
              @change="onSearchCompanyChange"
            >
              <el-option v-for="c in searchFilterOptions.companies" :key="c" :label="c" :value="c" />
            </el-select>
            <el-select
              v-model="searchFilters.line_nr"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="产线（选后自动过滤项目）"
              size="default"
              style="width: 180px; margin-left: 8px"
              @change="onSearchLineChange"
            >
              <el-option v-for="l in searchFilterOptions.lines" :key="l" :label="l" :value="l" />
            </el-select>
            <el-select
              v-model="searchFilters.project_code"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="项目编号（选后自动过滤名称）"
              size="default"
              style="width: 190px; margin-left: 8px"
              @change="onSearchProjectCodeChange"
            >
              <el-option v-for="p in searchFilterOptions.project_codes" :key="p" :label="p" :value="p" />
            </el-select>
            <el-select
              v-model="searchFilters.project_name"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="项目名称（选后自动过滤工位）"
              size="default"
              style="width: 220px; margin-left: 8px"
              @change="onSearchProjectNameChange"
            >
              <el-option v-for="n in searchFilterOptions.project_names" :key="n" :label="n" :value="n" />
            </el-select>
            <el-select
              v-model="searchFilters.station_nr"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="工位名称"
              size="default"
              style="width: 170px; margin-left: 8px"
            >
              <el-option v-for="s in searchFilterOptions.station_nrs" :key="s" :label="s" :value="s" />
            </el-select>
            <el-button type="primary" size="default" style="margin-left: 12px" :loading="searchLoading" @click="doSearch">检索</el-button>
            <el-button size="default" style="margin-left: 8px" @click="resetSearch">重置</el-button>
            <span class="search-count">共 {{ searchTotal }} 条</span>
          </div>

          <div v-if="searchLoading" class="loading-hint">加载中...</div>
          <template v-else>
            <!-- CT 分布直方图 -->
            <ChartCard
              v-if="searchHistogram && searchHistogram.counts && searchHistogram.counts.length"
              title="CT 分布直方图"
              :subtitle="`共 ${searchTotal} 条 · CT 范围 ${searchHistogram.min_value}s - ${searchHistogram.max_value}s`"
              :option="searchHistChartOption"
              :height="320"
            />
            <!-- 数据列表 -->
            <el-table :data="searchResults" stripe border size="small" max-height="500" style="width: 100%; margin-top: 16px">
              <el-table-column prop="company" label="工厂" width="70" />
              <el-table-column prop="line_nr" label="产线" width="90" />
              <el-table-column prop="project_code" label="项目编号" width="100" />
              <el-table-column prop="project_name" label="项目名称" min-width="160" show-overflow-tooltip />
              <el-table-column prop="station_nr" label="工位" width="90" />
              <el-table-column label="CT(s)" width="90" align="right">
                <template #default="{ row }">
                  <span class="num-cell">{{ row.cycle_time }}</span>
                </template>
              </el-table-column>
              <el-table-column label="采集时间" width="110">
                <template #default="{ row }">
                  <span class="num-cell">{{ row.start_time ? row.start_time.slice(0, 10) : '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" width="160">
                <template #default="{ row }">
                  <span class="num-cell">{{ row.update_time ? row.update_time.replace('T', ' ').slice(0, 19) : '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </template>
          <div v-if="searchTotal > searchFilters.page_size" class="search-pagination">
            <el-pagination
              v-model:current-page="searchFilters.page"
              v-model:page-size="searchFilters.page_size"
              :total="searchTotal"
              :page-sizes="[20, 50, 100, 200]"
              layout="total, sizes, prev, pager, next"
              @size-change="doSearch"
              @current-change="doSearch"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { actualCtApi } from '@/api'
import PageHeader from '@/components/PageHeader.vue'
import ChartCard from '@/components/ChartCard.vue'
import { PALETTE, AXIS, YOY_CHANGE, CHART_SPEC, IMPROVE_HOURS, withAlpha, buildValueLabelConfig, adaptiveBarLayout } from '@/utils/echartsTheme'
import { nearDoubleAnomaly, nearDoubleAnomalyText } from '@/utils/format'

// Tab
const activeTab = ref('SCT_VS_ACT')

// 级联筛选器（LB + 箱线图）
const filters = reactive({
  company: 'BJ',
  line_nr: 'BJFA1',
  project_code: 'T6763',
})
const projectName = ref('')

const filterOptions = reactive({
  companies: [],
  lines: [],
  projects: [],
})

// 级联筛选器缓存：key = `${company}|${line_nr}` → { lines, projects }
// 避免每次切换工厂/产线都发起后端请求
const filterCache = new Map()
const allCompaniesLoaded = ref(false)

const canQuery = computed(() => filters.company && filters.line_nr && filters.project_code)

function dedupeProjectOptions(items) {
  const seen = new Set()
  return (items || []).filter((item) => {
    const code = String(item?.code || '').trim()
    if (!code || seen.has(code)) return false
    seen.add(code)
    return true
  })
}

// 缓存 key
function cacheKey(company, lineNr) {
  return `${company || ''}|${lineNr || ''}`
}

// 筛选器级联（带缓存优化）
async function loadFilterOptions() {
  try {
    // 工厂列表只需加载一次
    if (!allCompaniesLoaded.value) {
      const allRes = await actualCtApi.cascadeFilters({})
      filterOptions.companies = [...new Set((allRes.companies || []).map((item) => String(item || '').trim()).filter(Boolean))]
      allCompaniesLoaded.value = true
    }

    // 检查缓存：同一 (company, line_nr) 组合的级联结果缓存
    const key = cacheKey(filters.company, filters.line_nr)
    let cached = filterCache.get(key)
    if (!cached) {
      const res = await actualCtApi.cascadeFilters({ company: filters.company, line_nr: filters.line_nr })
      cached = {
        lines: [...new Set((res.lines || []).map((item) => String(item || '').trim()).filter(Boolean))],
        projects: dedupeProjectOptions(res.projects || []),
      }
      filterCache.set(key, cached)
    }
    filterOptions.lines = cached.lines
    filterOptions.projects = cached.projects
  } catch (e) {
    console.error('加载筛选器失败', e)
  }
}

function onCompanyChange() {
  filters.line_nr = ''
  filters.project_code = ''
  projectName.value = ''
  loadFilterOptions()
}

function onLineChange() {
  filters.project_code = ''
  projectName.value = ''
  loadFilterOptions()
}

function onProjectChange() {
  const proj = filterOptions.projects.find((p) => p.code === filters.project_code)
  projectName.value = proj ? proj.name : ''
}

// ===== SCT Vs ACT =====
const sctCompanyFilter = ref('BJ')
const sctProcessFilter = ref('FA')
const sctItems = ref([])
const sctLoading = ref(false)

const sctProcessOptions = computed(() => {
  const processes = [...new Set(sctItems.value.map((x) => x.process))]
  return processes.sort()
})

const filteredSctItems = computed(() => {
  if (!sctProcessFilter.value) return sctItems.value
  return sctItems.value.filter((x) => x.process === sctProcessFilter.value)
})

// 按 |gap_pct| 降序排列（Gap最大的项目最需要重点关注）
const sortedSctItems = computed(() => {
  return [...filteredSctItems.value].sort((a, b) => {
    const absA = Math.abs(a.gap_pct ?? 0)
    const absB = Math.abs(b.gap_pct ?? 0)
    return absB - absA
  })
})

// GAP超过20%的行使用警戒色标识
function sctRowClass({ row }) {
  if (row.gap_pct !== null && Math.abs(row.gap_pct) > 20) {
    return 'warning-row'
  }
  return ''
}

async function loadSctData() {
  sctLoading.value = true
  try {
    const params = {}
    if (sctCompanyFilter.value) params.company = sctCompanyFilter.value
    const res = await actualCtApi.sctVsAct(params)
    sctItems.value = res.items || []
  } catch (e) {
    console.error('SCT加载失败', e)
  } finally {
    sctLoading.value = false
  }
}

// ===== ACT CT 趋势 TOP10（近3个月 同比/环比） =====
const trendLoading = ref(false)
const trendData = ref(null)
const trendCompany = ref('')
const trendMode = ref('mom') // mom=环比 yoy=同比

const trendList = computed(() => trendData.value?.[trendMode.value] || { rise: [], drop: [] })

const trendPeriodText = computed(() => {
  const p = trendData.value?.periods
  if (!p) return ''
  const fmt = (arr) => `${arr[0]} ~ ${arr[arr.length - 1]}`
  const isMom = trendMode.value === 'mom'
  return `近3月 ${fmt(p.recent)} · ${isMom ? '环比基期' : '同比基期'} ${fmt(isMom ? p.prev : p.yoy)}`
})

const trendChartSubtitle = computed(() => `${trendCompany.value || '全部工厂'} · ${trendPeriodText.value} · 月度瓶颈CT中位数 · 3月均值对比 · ⚠ = 疑似数据异常（接近 2 倍关系）`)

function trendBarOption(rows, color) {
  // 水平条形图：rank1 顶部（ECharts category 轴自下而上，需反转数组）
  const list = [...rows].reverse()
  if (!list.length) return {}
  const isDrop = list[0].change_pct < 0
  const baseLabel = trendMode.value === 'mom' ? '前3月均值' : '去年同期均值'
  // 接近 2 倍关系（偏差≈±50%）→ 疑似记录缺失/重复，标记 ⚠
  const anomalyFlags = list.map((r) => !!nearDoubleAnomaly(r.recent_avg, r.base_avg))
  return {
    grid: { left: 8, right: 64, top: 10, bottom: 10, containLabel: true },
    tooltip: {
      confine: true,
      formatter: (p) => {
        const d = list[p.dataIndex]
        if (!d) return ''
        // 异常提示块：琥珀左边线 + 浅底，说明倍数关系并建议核实
        const warn = anomalyFlags[p.dataIndex]
          ? `<div style="margin-top:4px;padding:3px 6px;border-left:3px solid ${PALETTE[1]};background:${withAlpha(PALETTE[1], 0.1)};color:${PALETTE[1]};font-size:11px">⚠ 数据异常提示：${nearDoubleAnomalyText(d.recent_avg, d.base_avg)}</div>`
          : ''
        return `<b>${d.project_code} / ${d.line_nr}</b>（${d.company}）<br/>` +
          `${d.project_name || ''}<br/>` +
          `近3月均值: <b>${d.recent_avg} s</b>（${d.recent_months}月）<br/>` +
          `${baseLabel}: <b>${d.base_avg} s</b>（${d.base_months}月）<br/>` +
          `变化: <b style="color:${color}">${d.change_pct > 0 ? '+' : ''}${d.change_pct}%</b>` + warn
      },
    },
    xAxis: {
      type: 'value',
      axisLabel: { formatter: '{value}%', fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } },
    },
    yAxis: {
      type: 'category',
      // 异常行的类目标签追加 ⚠
      data: list.map((r, i) => `${r.project_code}/${r.line_nr}${anomalyFlags[i] ? ' ⚠' : ''}`),
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.text },
      axisLine: { lineStyle: { color: AXIS.line } },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: CHART_SPEC.barMaxWidth,
      itemStyle: { color, borderRadius: isDrop ? [3, 0, 0, 3] : [0, 3, 3, 0] },
      label: buildValueLabelConfig('bar', list.length, {
        position: isDrop ? 'left' : 'right',
        formatter: (p) => (p.value > 0 ? '+' : '') + p.value + '%' + (anomalyFlags[p.dataIndex] ? ' ⚠' : ''),
        color: AXIS.text,
        fontSize: CHART_SPEC.labelAxis,
      }),
      data: list.map((r) => r.change_pct),
    }],
  }
}

const trendDropOption = computed(() => trendBarOption(trendList.value.drop, YOY_CHANGE.down))
const trendRiseOption = computed(() => trendBarOption(trendList.value.rise, YOY_CHANGE.up))

async function loadTrendTop() {
  trendLoading.value = true
  try {
    const params = { top: 10 }
    if (trendCompany.value) params.company = trendCompany.value
    trendData.value = await actualCtApi.ctTrendTop(params)
  } catch (e) {
    console.error('趋势TOP加载失败', e)
  } finally {
    trendLoading.value = false
  }
}

// ===== ACT vs Std 超差清单 =====
const devLoading = ref(false)
const devData = ref(null)
const devCompany = ref('')
const devThreshold = ref(10)

const devChartOption = computed(() => {
  const items = (devData.value?.items || []).slice(0, 20)
  if (!items.length) return {}
  // 哑铃图：X 轴项目/产线（|偏差%| rank1 在左），Y 轴差值（ACT − Std，秒）
  // Std 点落在 0 基准线，ACT 点落在差值处，两点连线红/绿表示偏离方向
  const labels = items.map((r) => `${r.project_code}/${r.line_nr}`)

  // 连线段：value=[X索引, 0（Std基准）, 差值]，颜色在 renderItem 按偏差方向判断
  const segments = items.map((r, idx) => ({ value: [idx, 0, r.deviation], item: r }))

  // Y 轴自适应范围（含 0 基准线，留 15% 余量）
  const vals = items.map((r) => r.deviation)
  const vMin = Math.min(0, ...vals)
  const vMax = Math.max(0, ...vals)
  const pad = (vMax - vMin) * 0.15 || Math.max(1, vMax * 0.05)

  const tooltipHead = (d) =>
    `<b>${d.project_code} / ${d.line_nr}</b>（${d.company} · ${d.process}）<br/>` +
    `${d.project_name || ''}<br/>` +
    `Std: <b>${d.std} s</b> · ACT: <b>${d.act} s</b><br/>` +
    `偏差: <b style="color:${d.deviation_pct > 0 ? YOY_CHANGE.up : YOY_CHANGE.down}">` +
    `${d.deviation > 0 ? '+' : ''}${d.deviation} s（${d.deviation_pct > 0 ? '+' : ''}${d.deviation_pct}%）</b> ` +
    `${d.deviation_pct > 0 ? '偏高（慢于标准）' : '偏低（快于标准）'}`

  return {
    grid: { left: 60, right: 30, top: 50, bottom: 80, containLabel: true },
    legend: {
      top: 0,
      data: ['Std（基准 0）', 'ACT（差值）'],
      textStyle: { color: AXIS.text, fontSize: CHART_SPEC.labelAxis },
    },
    tooltip: {
      confine: true,
      trigger: 'item',
      formatter: (p) => {
        const d = p.data.item
        return d ? tooltipHead(d) : ''
      },
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim, rotate: 40, interval: 0 },
      axisLine: { lineStyle: { color: AXIS.line } },
      axisTick: { lineStyle: { color: AXIS.line } },
    },
    yAxis: {
      type: 'value',
      name: '差值 ACT − Std（秒）',
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      min: Math.floor(vMin - pad),
      max: Math.ceil(vMax + pad),
      axisLabel: { fontSize: CHART_SPEC.labelAxis, color: AXIS.textDim },
      splitLine: { lineStyle: { color: AXIS.line } },
    },
    series: [
      // 基准0→差值连线：红 = ACT 偏高（慢于标准）/ 绿 = 偏低（快于标准）
      {
        name: '偏差连线',
        type: 'custom',
        z: 3,
        renderItem: (params, api) => {
          const x = api.value(0)
          const p1 = api.coord([x, api.value(1)])
          const p2 = api.coord([x, api.value(2)])
          const over = api.value(2) > 0
          return {
            type: 'line',
            shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] },
            style: {
              stroke: over ? YOY_CHANGE.up : YOY_CHANGE.down,
              lineWidth: 2.5,
              lineCap: 'round',
            },
          }
        },
        data: segments,
      },
      {
        name: 'Std（基准 0）',
        type: 'scatter',
        z: 5,
        symbolSize: 10,
        itemStyle: { color: IMPROVE_HOURS.budget, borderColor: '#ffffff', borderWidth: 1 },
        data: items.map((r, idx) => ({ value: [idx, 0], item: r })),
      },
      {
        name: 'ACT（差值）',
        type: 'scatter',
        z: 5,
        symbolSize: 10,
        itemStyle: { color: IMPROVE_HOURS.achievable, borderColor: '#ffffff', borderWidth: 1 },
        data: items.map((r, idx) => ({ value: [idx, r.deviation], item: r })),
      },
    ],
  }
})

async function loadDeviation() {
  devLoading.value = true
  try {
    const params = { threshold: devThreshold.value }
    if (devCompany.value) params.company = devCompany.value
    devData.value = await actualCtApi.actStdDeviation(params)
  } catch (e) {
    console.error('超差清单加载失败', e)
  } finally {
    devLoading.value = false
  }
}

function onSctCompanyChange() {
  sctProcessFilter.value = ''
  loadSctData()
}

const sctChartOption = computed(() => {
  if (!filteredSctItems.value.length) return {}
  const items = sortedSctItems.value
  const labels = items.map((x) => `${x.company} ${x.line_nr} ${x.project_code} ${x.process}`)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const idx = params[0].dataIndex
        const it = items[idx]
        const gapWarn = Math.abs(it.gap_pct) > 20 ? ' ⚠️' : ''
        const nameLine = it.project_name ? `<span style="color:#6b7280">${it.project_name}</span><br/>` : ''
        return `<b>${it.project_code}/${it.process}</b><br/>` +
               nameLine +
               `<span style="color:#6b7280">${it.company} · 产线 ${it.line_nr}</span><br/>` +
               `SCT: ${it.sct ?? '-'} s<br/>` +
               `ACT: ${it.act ?? '-'} s<br/>` +
               `Gap: ${it.gap > 0 ? '+' : ''}${it.gap} s (${it.gap_pct}%)${gapWarn}`
      }
    },
    legend: { data: ['SCT', 'ACT'], bottom: 0 },
    grid: { left: 60, right: 30, top: 30, bottom: 50, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: {
        fontSize: 10,
        rotate: labels.length > 6 ? 35 : 0,
        // 类别过多（如选择 SH 工厂）时按步长抽稀轴标签，防止旋转标签横向重叠；tooltip 仍可查看完整信息
        interval: labels.length > 14 ? Math.ceil(labels.length / 14) - 1 : 0,
        color: (value, index) => Math.abs(items[index].gap_pct) > 20 ? PALETTE[4] : AXIS.textDim,
        fontWeight: (value, index) => Math.abs(items[index].gap_pct) > 20 ? 'bold' : 'normal',
      }
    },
    yAxis: {
      type: 'value',
      name: 'CT (s)',
      nameLocation: 'middle',
      nameGap: 50,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [
      {
        name: 'SCT',
        type: 'bar',
        data: items.map((x) => x.sct ?? 0),
        itemStyle: { color: PALETTE[0] },
        // 柔性柱宽：随类别数自动伸缩（此前两系列固定 60% 合计 120%，SH 项目多时柱体相互遮挡）
        ...adaptiveBarLayout(),
        label: buildValueLabelConfig('barCompact', items.length, {
          position: 'top',
          formatter: '{c}'
        })
      },
      {
        name: 'ACT',
        type: 'bar',
        data: items.map((x) => x.act || 0),
        itemStyle: {
          color: (params) => Math.abs(items[params.dataIndex].gap_pct) > 20 ? PALETTE[4] : PALETTE[1]
        },
        ...adaptiveBarLayout(),
        label: buildValueLabelConfig('barCompact', items.length, {
          position: 'top',
          formatter: '{c}'
        })
      }
    ]
  }
})

// ===== Line Balance =====
const lbData = ref(null)
const lbLoading = ref(false)
const lbError = ref('')

const lbChartOption = computed(() => {
  if (!lbData.value) return {}
  const stations = lbData.value.stations || []
  const bottleneck = lbData.value.bottleneck_ct || 0
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        return `<b>${p.name}</b><br/>平均CT: ${p.value} s<br/>瓶颈CT: ${bottleneck} s`
      }
    },
    grid: { left: 55, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: stations.map((x) => x.station_nr),
      axisLabel: { fontSize: 11, rotate: stations.length > 8 ? 30 : 0, interval: 0 }
    },
    yAxis: {
      type: 'value',
      name: 'CT (s)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [{
      name: '平均CT',
      type: 'bar',
      data: stations.map((x) => ({
        value: x.avg_ct,
        itemStyle: { color: x.avg_ct >= bottleneck ? PALETTE[4] : PALETTE[0] },
        station_nr: x.station_nr,
        station_avg_ct: x.avg_ct,
        sample_count: x.sample_count,
      })),
      ...adaptiveBarLayout(),
      label: buildValueLabelConfig('barCompact', stations.length, {
        position: 'top',
        formatter: '{c}'
      }),
      markLine: {
        silent: true,
        data: [{ yAxis: bottleneck, label: { formatter: `瓶颈 ${bottleneck}`, fontSize: 11 }, lineStyle: { color: PALETTE[4], type: 'dashed' } }]
      }
    }]
  }
})

const stationDetailDialogVisible = ref(false)
const stationDetailLoading = ref(false)
const stationDetailActiveTab = ref('histogram')
// 直方图分组宽度：'auto' 或 数字（2/5/10/20/30 秒）
const histogramBinSize = ref('auto')
// 工位详情时间范围：3m/6m/1y/2y/all
const stationDateRange = ref('3m')
// 最近一次查询工位详情的入参，用于切换分组宽度时重新加载
const lastStationQuery = reactive({ company: '', line_nr: '', project_code: '', station_nr: '' })
const stationDetail = reactive({
  company: '',
  line_nr: '',
  project_code: '',
  station_nr: '',
  project_name: '',
  sample_count: 0,
  anomaly_count: 0,
  represent_ct: null,
  period: {},
  histogram: null,
  daily_series: [],
  anomaly_thresholds: {},
  xbar_r_chart: null,
  diagnosis: { summary: '', likely_causes: [], improvement_opportunities: [] },
})

const stationDetailTitle = computed(() => {
  return `${stationDetail.station_nr || '工位'} 工时分析`
})

const stationHistogramOption = computed(() => {
  const h = stationDetail.histogram
  if (!h || !h.counts || !h.counts.length) return {}
  // 计算峰值 bin，用于高亮最常见的节拍区间
  const maxCount = Math.max(...h.counts)
  const colorByHeight = h.counts.map((c) => c === maxCount ? PALETTE[2] : PALETTE[0])
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        const pct = h.total > 0 ? ((p.value / h.total) * 100).toFixed(1) : '0.0'
        return `${p.name}<br/>数量: ${p.value} 条（${pct}%）`
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: h.categories,
      name: 'CT (s)',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: { fontSize: 10, rotate: h.categories.length > 10 ? 35 : 0, interval: 0 }
    },
    yAxis: { type: 'value', name: '数量', nameLocation: 'middle', nameGap: 30, axisLabel: { fontSize: 11 } },
    series: [{
      name: '分布',
      type: 'bar',
      data: h.counts.map((c, i) => ({ value: c, itemStyle: { color: colorByHeight[i] } })),
      // 直方图柱体紧凑贴合（categoryGap 调小），宽度随分箱数自适应
      ...adaptiveBarLayout({ categoryGap: '20%' }),
      label: buildValueLabelConfig('barCompact', h.categories.length, {
        position: 'top',
        color: '#6b7280',
        formatter: '{c}'
      })
    }]
  }
})

const stationDailyOption = computed(() => {
  const series = stationDetail.daily_series || []
  if (!series.length) return {}
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const q = params[1]
        return `${p.name}<br/>均值: ${p.value} s<br/>极差: ${q.value} s`
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: series.map((x) => x.date),
      axisLabel: { fontSize: 10, rotate: series.length > 8 ? 35 : 0, interval: 0 }
    },
    yAxis: [
      { type: 'value', name: '均值 CT (s)', axisLabel: { fontSize: 11 } },
      { type: 'value', name: '极差 (s)', axisLabel: { fontSize: 11 } }
    ],
    series: [
      { name: '均值 CT', type: 'line', data: series.map((x) => x.mean_ct), yAxisIndex: 0, smooth: true, itemStyle: { color: PALETTE[1] } },
      { name: '极差', type: 'bar', data: series.map((x) => x.range_ct), yAxisIndex: 1, itemStyle: { color: PALETTE[4] } }
    ]
  }
})

// 休哈特 Xbar 均值控制图：日均值 + CL/UCL/LCL 控制限 + 越界点高亮
const xbarChartOption = computed(() => {
  const chart = stationDetail.xbar_r_chart
  const series = stationDetail.daily_series || []
  if (!chart || !series.length) return {}
  const xbar = chart.xbar_chart || {}
  const oocDates = new Set((xbar.out_of_control_points || []).map((p) => p.date))
  const oocMap = new Map((xbar.out_of_control_points || []).map((p) => [p.date, p.rule]))
  const cl = xbar.cl
  const ucl = xbar.ucl
  const lcl = xbar.lcl
  // 每个点根据是否越界分别着色
  const pointColors = series.map((x) => (oocDates.has(x.date) ? PALETTE[4] : PALETTE[0]))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const date = p.name
        const rule = oocMap.get(date)
        const lines = [`${date}`, `日均值: ${p.value} s`]
        if (rule) lines.push(`<span style="color:${PALETTE[4]}">越界（${rule}）</span>`)
        if (cl != null) lines.push(`CL: ${cl}`)
        if (ucl != null) lines.push(`UCL: ${ucl}`)
        if (lcl != null) lines.push(`LCL: ${lcl}`)
        return lines.join('<br/>')
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: series.map((x) => x.date),
      name: '日期',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: { fontSize: 10, rotate: series.length > 8 ? 35 : 0, interval: 0, color: AXIS.textDim }
    },
    yAxis: {
      type: 'value',
      name: '日均值 CT (s)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim },
      splitLine: { show: true, lineStyle: { color: AXIS.line, type: 'dashed' } }
    },
    series: [
      {
        name: '日均值 CT',
        type: 'line',
        data: series.map((x) => x.mean_ct),
        smooth: false,
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { color: PALETTE[0], width: 2 },
        itemStyle: {
          color: (params) => pointColors[params.dataIndex],
          borderColor: '#fff',
          borderWidth: 1
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { type: 'dashed' },
          label: { fontSize: 10, position: 'insideEndTop' },
          data: [
            cl != null ? { name: 'CL', yAxis: cl, lineStyle: { color: PALETTE[1] }, label: { formatter: `CL=${cl}`, color: PALETTE[1] } } : null,
            ucl != null ? { name: 'UCL', yAxis: ucl, lineStyle: { color: PALETTE[4] }, label: { formatter: `UCL=${ucl}`, color: PALETTE[4] } } : null,
            lcl != null ? { name: 'LCL', yAxis: lcl, lineStyle: { color: PALETTE[4] }, label: { formatter: `LCL=${lcl}`, color: PALETTE[4] } } : null
          ].filter(Boolean)
        }
      }
    ]
  }
})

// 休哈特 R 极差控制图：日极差 + CL/UCL/LCL 控制限 + 越界点高亮
const rChartOption = computed(() => {
  const chart = stationDetail.xbar_r_chart
  const series = stationDetail.daily_series || []
  if (!chart || !series.length) return {}
  const rChart = chart.r_chart || {}
  const oocDates = new Set((rChart.out_of_control_points || []).map((p) => p.date))
  const oocMap = new Map((rChart.out_of_control_points || []).map((p) => [p.date, p.rule]))
  const cl = rChart.cl
  const ucl = rChart.ucl
  const lcl = rChart.lcl
  const pointColors = series.map((x) => (oocDates.has(x.date) ? PALETTE[4] : PALETTE[6]))
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const date = p.name
        const rule = oocMap.get(date)
        const lines = [`${date}`, `日极差: ${p.value} s`]
        if (rule) lines.push(`<span style="color:${PALETTE[4]}">越界（${rule}）</span>`)
        if (cl != null) lines.push(`CL: ${cl}`)
        if (ucl != null) lines.push(`UCL: ${ucl}`)
        if (lcl != null) lines.push(`LCL: ${lcl}`)
        return lines.join('<br/>')
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: series.map((x) => x.date),
      name: '日期',
      nameLocation: 'middle',
      nameGap: 40,
      axisLabel: { fontSize: 10, rotate: series.length > 8 ? 35 : 0, interval: 0, color: AXIS.textDim }
    },
    yAxis: {
      type: 'value',
      name: '日极差 (s)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim },
      splitLine: { show: true, lineStyle: { color: AXIS.line, type: 'dashed' } }
    },
    series: [
      {
        name: '日极差',
        type: 'line',
        data: series.map((x) => x.range_ct),
        smooth: false,
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: { color: PALETTE[6], width: 2 },
        itemStyle: {
          color: (params) => pointColors[params.dataIndex],
          borderColor: '#fff',
          borderWidth: 1
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { type: 'dashed' },
          label: { fontSize: 10, position: 'insideEndTop' },
          data: [
            cl != null ? { name: 'CL', yAxis: cl, lineStyle: { color: PALETTE[1] }, label: { formatter: `CL=${cl}`, color: PALETTE[1] } } : null,
            ucl != null ? { name: 'UCL', yAxis: ucl, lineStyle: { color: PALETTE[4] }, label: { formatter: `UCL=${ucl}`, color: PALETTE[4] } } : null,
            lcl != null && lcl > 0 ? { name: 'LCL', yAxis: lcl, lineStyle: { color: PALETTE[4] }, label: { formatter: `LCL=${lcl}`, color: PALETTE[4] } } : null
          ].filter(Boolean)
        }
      }
    ]
  }
})

async function handleStationBarClick(params) {
  const data = params.data
  if (!data || !data.station_nr) return
  const stationNr = data.station_nr
  stationDetailLoading.value = true
  stationDetailDialogVisible.value = true
  stationDetailActiveTab.value = 'histogram'
  histogramBinSize.value = 'auto' // 重置为默认
  stationDateRange.value = '3m' // 重置为默认近3月
  Object.assign(stationDetail, {
    company: lbData.value?.company || '',
    line_nr: lbData.value?.line_nr || '',
    project_code: lbData.value?.project_code || '',
    station_nr: stationNr,
    project_name: lbData.value?.project_name || '',
    sample_count: 0,
    anomaly_count: 0,
    represent_ct: null,
    period: {},
    histogram: null,
    daily_series: [],
    anomaly_thresholds: {},
    xbar_r_chart: null,
    diagnosis: { summary: '', likely_causes: [], improvement_opportunities: [] },
  })
  // 保存入参，便于切换分组宽度时复用
  Object.assign(lastStationQuery, {
    company: lbData.value?.company || '',
    line_nr: lbData.value?.line_nr || '',
    project_code: lbData.value?.project_code || '',
    station_nr: stationNr,
  })
  await loadStationDetail()
}

async function loadStationDetail() {
  if (!lastStationQuery.station_nr) return
  stationDetailLoading.value = true
  try {
    const params = {
      company: lastStationQuery.company,
      line_nr: lastStationQuery.line_nr,
      project_code: lastStationQuery.project_code,
      station_nr: lastStationQuery.station_nr,
      date_range: stationDateRange.value,
    }
    // 传递分组宽度（auto 时不传，后端按 bin_count=10 均分）
    if (histogramBinSize.value !== 'auto') {
      params.bin_size = histogramBinSize.value
    }
    const res = await actualCtApi.stationDetail(params)
    Object.assign(stationDetail, {
      company: res.company || lastStationQuery.company || '',
      line_nr: res.line_nr || lastStationQuery.line_nr || '',
      project_code: res.project_code || lastStationQuery.project_code || '',
      station_nr: res.station_nr || lastStationQuery.station_nr || '',
      project_name: res.project_name || stationDetail.project_name || '',
      sample_count: res.sample_count || 0,
      anomaly_count: res.anomaly_count || 0,
      represent_ct: res.represent_ct ?? null,
      period: res.period || {},
      histogram: res.histogram || null,
      daily_series: res.daily_series || [],
      anomaly_thresholds: res.anomaly_thresholds || {},
      xbar_r_chart: res.xbar_r_chart || null,
      diagnosis: res.diagnosis || { summary: '', likely_causes: [], improvement_opportunities: [] },
    })
  } catch (e) {
    console.error('加载工位分析失败', e)
  } finally {
    stationDetailLoading.value = false
  }
}

// 切换直方图分组宽度时重新加载（仅直方图部分）
async function onHistogramBinSizeChange() {
  await loadStationDetail()
}

// 切换时间范围后重新加载工位详情
async function onDateRangeChange() {
  await loadStationDetail()
}

// ===== Box Plot =====
const bpData = ref(null)
const bpLoading = ref(false)

const boxPlotOption = computed(() => {
  if (!bpData.value) return {}
  const boxData = bpData.value.box_data || []
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        if (!p.data) return ''
        return `<b>${p.name}</b><br/>最大值: ${p.data[5]}<br/>Q3: ${p.data[4]}<br/>中位数: ${p.data[3]}<br/>Q1: ${p.data[2]}<br/>最小值: ${p.data[1]}<br/>均值: ${p.data[6]}<br/>样本: ${p.data[7]}`
      }
    },
    grid: { left: 55, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: boxData.map((x) => x.station_nr),
      axisLabel: { fontSize: 11, rotate: boxData.length > 8 ? 30 : 0, interval: 0 }
    },
    yAxis: {
      type: 'value',
      name: 'CT (s)',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [{
      name: '箱线图',
      type: 'boxplot',
      data: boxData.map((x) => [x.min, x.q1, x.median, x.q3, x.max]),
      itemStyle: { color: PALETTE[0], borderColor: PALETTE[0] }
    }]
  }
})

// 查询 LB + 箱线图
async function queryLbBp() {
  if (!canQuery.value) return
  const params = {
    company: filters.company,
    line_nr: filters.line_nr,
    project_code: filters.project_code,
  }
  lbLoading.value = true
  bpLoading.value = true
  // 先清空旧数据，避免无数据时仍展示上次的项目数据
  lbData.value = null
  bpData.value = null
  lbError.value = ''
  try {
    const [lbRes, bpRes] = await Promise.all([
      actualCtApi.lineBalance(params),
      actualCtApi.boxPlot(params),
    ])
    lbData.value = lbRes
    bpData.value = bpRes
  } catch (e) {
    console.error('查询失败', e)
    // 后端返回 404 表示该项目无实测CT数据；清空数据让模板显示"无数据"占位
    lbData.value = null
    bpData.value = null
    lbError.value = (e && e.response && e.response.data && e.response.data.error) || '该筛选条件下暂无实测 CT 数据'
  } finally {
    lbLoading.value = false
    bpLoading.value = false
  }
}

function onTabChange(tab) {
  if (tab === 'SCT_VS_ACT' && sctItems.value.length === 0) {
    loadSctData()
  }
  if (tab === 'TREND_TOP' && !trendData.value) {
    loadTrendTop()
  }
  if (tab === 'ACT_STD_DEV' && !devData.value) {
    loadDeviation()
  }
  if (tab === 'SEARCH' && searchFilterOptions.companies.length === 0) {
    loadSearchFilters()
  }
}

// ===== Actual CT 检索 =====
const searchFilters = reactive({
  company: [],
  line_nr: [],
  project_code: [],
  project_name: [],
  station_nr: [],
  page: 1,
  page_size: 50,
})
const searchFilterOptions = reactive({
  companies: [],
  lines: [],
  project_codes: [],
  project_names: [],
  station_nrs: [],
})
const searchResults = ref([])
const searchTotal = ref(0)
const searchLoading = ref(false)
const searchHistogram = ref(null)

// 直方图 ECharts 配置
const searchHistChartOption = computed(() => {
  if (!searchHistogram.value || !searchHistogram.value.counts || !searchHistogram.value.counts.length) return {}
  const h = searchHistogram.value
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const p = params[0]
        return `${p.name}<br/>数量: ${p.value} 条`
      }
    },
    grid: { left: 60, right: 30, top: 30, bottom: 60, containLabel: true },
    xAxis: {
      type: 'category',
      data: h.categories,
      name: 'CT (秒)',
      nameLocation: 'middle',
      nameGap: 38,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 10, rotate: h.categories.length > 10 ? 35 : 0, interval: 0, color: AXIS.textDim }
    },
    yAxis: {
      type: 'value',
      name: '数量',
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { fontSize: 12, color: AXIS.textDim },
      axisLabel: { fontSize: 11, color: AXIS.textDim }
    },
    series: [{
      name: 'CT分布',
      type: 'bar',
      data: h.counts,
      // 直方图柱体紧凑贴合（categoryGap 调小），宽度随分箱数自适应
      ...adaptiveBarLayout({ categoryGap: '10%' }),
      itemStyle: { color: PALETTE[0] },
      label: buildValueLabelConfig('barCompact', h.counts.length, {
        position: 'top',
        color: AXIS.text,
        formatter: '{c}'
      })
    }]
  }
})

// 级联筛选器加载锁：避免快速切换导致的竞态条件（后发请求先返回时覆盖新数据）
let searchFilterRequestId = 0
const searchFilterLoading = ref(false)

async function loadSearchFilters() {
  const requestId = ++searchFilterRequestId
  searchFilterLoading.value = true
  try {
    const params = {}
    if (searchFilters.company.length) params.company = searchFilters.company.join(',')
    if (searchFilters.line_nr.length) params.line_nr = searchFilters.line_nr.join(',')
    if (searchFilters.project_code.length) params.project_code = searchFilters.project_code.join(',')
    if (searchFilters.project_name.length) params.project_name = searchFilters.project_name.join(',')
    const res = await actualCtApi.cascadeFilters(params)
    // 忽略过期响应（用户在此期间又改了筛选条件）
    if (requestId !== searchFilterRequestId) return
    // 前端再次去重，避免后端遗漏或网络缓存导致重复项影响 el-option 的 :key
    searchFilterOptions.companies = [...new Set(res.companies || [])]
    searchFilterOptions.lines = [...new Set(res.lines || [])]
    searchFilterOptions.project_codes = [...new Set(res.project_codes || [])]
    searchFilterOptions.project_names = [...new Set(res.project_names || [])]
    searchFilterOptions.station_nrs = [...new Set(res.station_nrs || [])]
  } catch (e) {
    console.error('加载检索筛选器失败', e)
  } finally {
    if (requestId === searchFilterRequestId) {
      searchFilterLoading.value = false
    }
  }
}

// 级联：工厂变化 → 清空下游选项并重载
function onSearchCompanyChange() {
  searchFilters.line_nr = []
  searchFilters.project_code = []
  searchFilters.project_name = []
  searchFilters.station_nr = []
  loadSearchFilters()
}

// 级联：产线变化 → 清空下游选项并重载
function onSearchLineChange() {
  searchFilters.project_code = []
  searchFilters.project_name = []
  searchFilters.station_nr = []
  loadSearchFilters()
}

// 级联：项目编号变化 → 清空下游选项并重载
function onSearchProjectCodeChange() {
  searchFilters.project_name = []
  searchFilters.station_nr = []
  loadSearchFilters()
}

// 级联：项目名称变化 → 清空工位并重载
function onSearchProjectNameChange() {
  searchFilters.station_nr = []
  loadSearchFilters()
}

async function doSearch() {
  searchLoading.value = true
  try {
    const params = { page: searchFilters.page, page_size: searchFilters.page_size }
    if (searchFilters.company.length) params.company = searchFilters.company.join(',')
    if (searchFilters.line_nr.length) params.line_nr = searchFilters.line_nr.join(',')
    if (searchFilters.project_code.length) params.project_code = searchFilters.project_code.join(',')
    if (searchFilters.project_name.length) params.project_name = searchFilters.project_name.join(',')
    if (searchFilters.station_nr.length) params.station_nr = searchFilters.station_nr.join(',')
    const res = await actualCtApi.search(params)
    searchResults.value = res.results || []
    searchTotal.value = res.total || 0
    searchHistogram.value = res.histogram || null
  } catch (e) {
    console.error('检索失败', e)
  } finally {
    searchLoading.value = false
  }
}

function resetSearch() {
  searchFilters.company = []
  searchFilters.line_nr = []
  searchFilters.project_code = []
  searchFilters.project_name = []
  searchFilters.station_nr = []
  searchFilters.page = 1
  searchHistogram.value = null
  loadSearchFilters()
  doSearch()
}

onMounted(async () => {
  await loadFilterOptions()
  await loadSctData()
  if (canQuery.value) {
    await queryLbBp()
  }
})
</script>

<style scoped>
.actual-ct-page { min-height: 100%; }
.page-container { padding: 0 16px; }

.cascade-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-md);
  padding: 12px 16px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  flex-wrap: wrap;
  gap: var(--space-sm);
  box-shadow: var(--shadow-sm);
}

.analysis-tabs {
  background: var(--color-surface);
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
}
.loading-hint {
  text-align: center;
  padding: 40px;
  color: var(--color-text-dim);
  font-size: 13px;
}

/* SCT filter */
.sct-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--color-surface-hover);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.sct-filter-count {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-text-muted);
  font-weight: 500;
}

.num-cell {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}

/* GAP超过20%警戒行 */
:deep(.el-table .warning-row) {
  background: rgba(239, 68, 68, 0.06) !important;
}
:deep(.el-table .warning-row:hover > td) {
  background: rgba(239, 68, 68, 0.12) !important;
}

/* Line Balance */
.lb-summary {
  display: flex;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}
.lb-summary-item {
  flex: 1;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 14px;
  text-align: center;
  box-shadow: var(--shadow-sm);
  position: relative;
  overflow: hidden;
}
.lb-summary-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-primary);
  opacity: 0.8;
}
.lb-summary-label {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  font-weight: 500;
}
.lb-summary-value {
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-display);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}

/* 工位级分析弹窗 - 水平指标卡 */
.station-detail-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}
.station-detail-metric {
  position: relative;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 10px 12px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.station-detail-metric::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--gradient-primary);
  opacity: 0.8;
}
.station-detail-metric-label {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  font-weight: 500;
}
.station-detail-metric-value {
  font-size: 16px;
  font-weight: 700;
  font-family: var(--font-display);
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  word-break: break-all;
  line-height: 1.2;
}
.station-detail-metric-value.is-anomaly {
  color: var(--color-danger);
}
@media (max-width: 1280px) {
  .station-detail-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

/* 直方图工具栏 */
.histogram-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 8px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 13px;
}
.histogram-toolbar-label {
  color: var(--color-text-muted);
  white-space: nowrap;
}
.station-date-range-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin: 12px 0;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  font-size: 13px;
}
.station-date-range-bar .range-label {
  color: var(--color-text-muted);
  white-space: nowrap;
  font-weight: 500;
}
.station-date-range-bar .range-info {
  color: var(--color-text-muted);
  font-size: 12px;
  margin-left: 8px;
}
.histogram-filter-info {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 12px;
}

/* Actual CT 检索 */
.search-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: var(--space-md);
  padding: 12px 16px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  flex-wrap: wrap;
  gap: var(--space-sm);
  box-shadow: var(--shadow-sm);
}
.search-count {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-text-muted);
  font-weight: 500;
}
.search-pagination {
  display: flex;
  justify-content: center;
  margin-top: var(--space-md);
}
</style>