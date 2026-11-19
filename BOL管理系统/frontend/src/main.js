import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/main.css'

// 创建 Vue 应用实例
const app = createApp(App)

// 注册 Element Plus 全部图标为全局组件
for (const [iconName, iconComponent] of Object.entries(ElementPlusIconsVue)) {
  app.component(iconName, iconComponent)
}

// 注册 Element Plus 与路由
app.use(ElementPlus)
app.use(router)

app.mount('#app')
