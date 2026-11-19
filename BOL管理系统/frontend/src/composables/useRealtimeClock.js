import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

// 实时时钟 composable：每分钟刷新一次当前时间
// —— 统一 PageHeader / HomeView 的时间显示逻辑
//    （此前 PageHeader 为组件创建时的静态快照，页面停留数小时后时间显示错误）
// 用法：const { dateStr, timeStr, dateTimeStr } = useRealtimeClock()
export function useRealtimeClock(updateMs = 60000) {
  const now = ref(new Date())

  const dateStr = computed(() =>
    now.value.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  )
  const timeStr = computed(() =>
    now.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  )
  // 'yyyy/MM/dd HH:mm'
  const dateTimeStr = computed(() => `${dateStr.value} ${timeStr.value}`)

  let timer = null
  onMounted(() => {
    timer = setInterval(() => {
      now.value = new Date()
    }, updateMs)
  })
  onBeforeUnmount(() => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })

  return { now, dateStr, timeStr, dateTimeStr }
}
