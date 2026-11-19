<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { baseOption } from '@/utils/echartsTheme'

const props = defineProps({
  // 图表标题
  title: { type: String, default: '' },
  // 图表副标题（可选）
  subtitle: { type: String, default: '' },
  // ECharts option 对象
  option: { type: Object, required: true },
  // 图表高度（px）
  height: { type: [Number, String], default: 280 },
  // 是否在 option 变化时重新渲染
  autoResize: { type: Boolean, default: true }
})

// 图表点击事件：统一通过 @chart-click 监听（不提供 prop 回调，避免双通道重复触发）
const emit = defineEmits(['chart-click'])

const chartRef = ref(null)
let chart = null

function mergeDeep(target, source) {
  const out = { ...target }
  Object.keys(source || {}).forEach((key) => {
    const t = target[key]
    const s = source[key]
    if (
      t && s && typeof t === 'object' && typeof s === 'object'
      && !Array.isArray(t) && !Array.isArray(s)
    ) {
      out[key] = mergeDeep(t, s)
    } else {
      out[key] = s
    }
  })
  return out
}

function renderChart() {
  if (!chartRef.value) return
  // 容器尺寸为 0 时跳过，由 ResizeObserver 在尺寸就绪后触发
  if (chartRef.value.offsetWidth === 0 || chartRef.value.offsetHeight === 0) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
    // dev 调试: 暴露实例便于自动化测试图表事件
    if (import.meta.env.DEV) {
      window.__echartsInstances = window.__echartsInstances || {}
      window.__echartsInstances[props.title || `chart-${Object.keys(window.__echartsInstances).length}`] = chart
    }
  }
  const merged = mergeDeep(baseOption, props.option || {})
  chart.setOption(merged, true)
  chart.off('click')
  // 单通道: 仅 emit Vue 事件（@chart-click）。
  // 注意勿再手动调用 props.onChartClick —— @chart-click 监听器本身会被 Vue
  // 编译为 onChartClick prop，emit 时已自动调用，手动调用会导致 handler 执行两次。
  chart.on('click', (params) => emit('chart-click', params))
}

function handleResize() {
  chart?.resize()
}

let resizeObserver = null
// 卸载标志：防止 document.fonts.ready 回调在组件销毁后触发重渲染
let disposed = false

onMounted(async () => {
  await nextTick()
  // 多次轮询等待容器宽度稳定（最多 600ms）
  for (let i = 0; i < 12; i++) {
    if (chartRef.value && chartRef.value.offsetWidth > 0 && chartRef.value.offsetHeight > 0) break
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  renderChart()
  // 离线字体（@font-face woff2）加载完成后重渲染一次：
  // canvas 文字不会随字体加载自动切换，需主动重绘保证图表使用正确字体
  if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
      if (!disposed) renderChart()
    })
  }
  if (props.autoResize) {
    window.addEventListener('resize', handleResize)
    // 使用 ResizeObserver 监听容器尺寸变化（首次渲染兜底 + 父级布局变化）
    if (typeof ResizeObserver !== 'undefined' && chartRef.value) {
      resizeObserver = new ResizeObserver(() => {
        if (!chart && chartRef.value && chartRef.value.offsetWidth > 0 && chartRef.value.offsetHeight > 0) {
          renderChart()
        } else if (chart) {
          chart.resize()
        }
      })
      resizeObserver.observe(chartRef.value)
    }
  }
})

onBeforeUnmount(() => {
  disposed = true
  if (props.autoResize) {
    window.removeEventListener('resize', handleResize)
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  chart?.dispose()
  chart = null
})

watch(
  () => props.option,
  () => {
    nextTick(renderChart)
  },
  { deep: true }
)
</script>

<template>
  <div class="chart-card">
    <div v-if="title || subtitle" class="chart-header">
      <div class="chart-title" v-if="title">{{ title }}</div>
      <div class="chart-subtitle" v-if="subtitle">{{ subtitle }}</div>
    </div>
    <div ref="chartRef" class="chart-body" :style="{ height: typeof height === 'number' ? height + 'px' : height }"></div>
  </div>
</template>

<style scoped>
.chart-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 14px 16px 8px;
  transition: border-color var(--transition);
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-sm);
}

.chart-card:hover {
  border-color: var(--color-border-bright);
  box-shadow: var(--shadow);
}

.chart-header {
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-border);
}

.chart-title {
  /* 对齐三层标题规范 H3：display 字体 + 渐变竖条 */
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  letter-spacing: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chart-title::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 14px;
  background: var(--gradient-primary);
  border-radius: 2px;
}

.chart-subtitle {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 4px;
  line-height: 1.4;
}

.chart-body {
  width: 100%;
}
</style>
