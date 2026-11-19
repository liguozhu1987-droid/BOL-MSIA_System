<script setup>
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { useAuth } from '@/composables/useAuth'

const route = useRoute()
const { fetchMe } = useAuth()

// 是否是主页（主页不需要PageHeader）
const isHome = computed(() => route.path === '/' || route.path === '/home')

onMounted(() => {
  fetchMe()
})
</script>

<template>
  <div class="app-layout">
    <router-view v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </router-view>
  </div>
</template>

<style scoped>
.app-layout {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
}

/* 路由切换淡入淡出 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 220ms ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
