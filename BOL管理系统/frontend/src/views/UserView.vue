<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter, useRoute } from 'vue-router'
import { userApi } from '@/api'
import { formatDateTime } from '@/utils/format'
import { useAuth } from '@/composables/useAuth'
import PageHeader from '@/components/PageHeader.vue'

const router = useRouter()
const route = useRoute()
const { isAdmin } = useAuth()

// --- 子模块导航（系统管理 · Tab） ---
const sysTabs = [
  { key: 'reports', label: '报告中心', icon: 'Document', route: '/reports' },
  { key: 'users', label: '人员管理', icon: 'User', route: '/users', adminOnly: true },
  { key: 'account', label: '账号设置', icon: 'UserFilled', route: '/account' }
]
const activeTab = ref('users')
watch(() => route.path, (p) => {
  if (p.startsWith('/reports')) activeTab.value = 'reports'
  else if (p.startsWith('/users')) activeTab.value = 'users'
  else if (p.startsWith('/account')) activeTab.value = 'account'
}, { immediate: true })

function switchTab(tab) {
  if (tab.adminOnly && !isAdmin.value) {
    ElMessage.warning('该子模块仅管理员可访问')
    return
  }
  router.push(tab.route)
}

// 筛选条件
const filters = reactive({
  department: '',
  role: '',
  status: ''
})

const roleOptions = [
  { label: '全部', value: '' },
  { label: '系统管理员', value: 'ADMIN' },
  { label: 'IE 工程师', value: 'IE' },
  { label: '部门经理', value: 'MGR' },
  { label: '工程师', value: 'ENGINEER' },
  { label: '只读用户', value: 'VIEWER' }
]

const statusOptions = [
  { label: '全部', value: '' },
  { label: '在职', value: 'ACTIVE' },
  { label: '停用', value: 'INACTIVE' }
]

// 表格数据
const tableData = ref([])
const loading = ref(false)
const pagination = reactive({
  page: 1,
  pageSize: 15,
  total: 0
})

const pagedData = computed(() => {
  const start = (pagination.page - 1) * pagination.pageSize
  return tableData.value.slice(start, start + pagination.pageSize)
})

// 对话框
const dialogVisible = ref(false)
const dialogMode = ref('create')
const submitting = ref(false)
const editingId = ref(null)

const defaultForm = () => ({
  name: '',
  username: '',
  email: '',
  phone: '',
  department: '',
  title: '',
  role: 'ENGINEER',
  status: 'ACTIVE',
  remark: '',
  initial_password: ''
})
const form = reactive(defaultForm())

async function loadList() {
  loading.value = true
  try {
    const params = {}
    if (filters.department) params.department = filters.department
    if (filters.role) params.role = filters.role
    if (filters.status) params.status = filters.status
    const res = await userApi.list(params)
    const list = Array.isArray(res) ? res : (res.results || [])
    tableData.value = list
    pagination.total = list.length
    pagination.page = 1
  } catch (e) {
    // ignore
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  loadList()
}

function handleReset() {
  filters.department = ''
  filters.role = ''
  filters.status = ''
  loadList()
}

function openCreate() {
  dialogMode.value = 'create'
  editingId.value = null
  Object.assign(form, defaultForm())
  dialogVisible.value = true
}

function openEdit(row) {
  dialogMode.value = 'edit'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name || '',
    username: row.username || '',
    email: row.email || '',
    phone: row.phone || '',
    department: row.department || '',
    title: row.title || '',
    role: row.role || 'ENGINEER',
    status: row.status || 'ACTIVE',
    remark: row.remark || '',
    initial_password: ''
  })
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (!form.username) {
    ElMessage.warning('请填写用户名')
    return
  }
  if (
    (dialogMode.value === 'create' && !form.initial_password)
    || (form.initial_password && form.initial_password.length < 8)
  ) {
    ElMessage.warning('初始密码至少 8 位')
    return
  }
  submitting.value = true
  try {
    const payload = { ...form }
    if (dialogMode.value === 'create') {
      await userApi.create(payload)
      ElMessage.success('创建成功')
    } else {
      const resettingPassword = !!payload.initial_password
      if (!resettingPassword) delete payload.initial_password
      await userApi.update(editingId.value, payload)
      ElMessage.success(resettingPassword
        ? '信息已更新，用户下次登录需修改新密码'
        : '更新成功')
    }
    dialogVisible.value = false
    loadList()
  } catch (e) {
    // ignore
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除员工 ${row.username} ${row.name} 吗？`,
      '删除确认',
      { type: 'warning' }
    )
    await userApi.remove(row.id)
    ElMessage.success('删除成功')
    loadList()
  } catch (e) {
    // 用户取消
  }
}

async function handleToggleStatus(row) {
  const action = row.status === 'ACTIVE' ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(
      `确认${action}员工 ${row.username} ${row.name} 吗？`,
      `${action}确认`,
      { type: 'warning' }
    )
    if (row.status === 'ACTIVE') {
      await userApi.deactivate(row.id)
    } else {
      await userApi.activate(row.id)
    }
    ElMessage.success(`${action}成功`)
    loadList()
  } catch (e) {
    // 用户取消
  }
}

function roleLabel(role) {
  const map = {
    ADMIN: '系统管理员',
    IE: 'IE 工程师',
    MGR: '部门经理',
    ENGINEER: '工程师',
    VIEWER: '只读用户'
  }
  return map[String(role || '').toUpperCase()] || role || '-'
}

function roleTagType(role) {
  const map = {
    ADMIN: 'danger',
    IE: '',
    MGR: 'warning',
    ENGINEER: 'success',
    VIEWER: 'info'
  }
  return map[String(role || '').toUpperCase()] || 'info'
}

function statusLabel(status) {
  return status === 'ACTIVE' ? '在职' : '停用'
}

function statusTagType(status) {
  return status === 'ACTIVE' ? 'success' : 'info'
}

function handlePageChange(page) {
  pagination.page = page
}

function handleSizeChange(size) {
  pagination.pageSize = size
  pagination.page = 1
}

// 统计卡片
const stats = computed(() => {
  const total = tableData.value.length
  const active = tableData.value.filter((r) => r.status === 'ACTIVE').length
  const departments = new Set(tableData.value.map((r) => r.department).filter(Boolean)).size
  const admins = tableData.value.filter((r) => r.role === 'ADMIN').length
  return { total, active, departments, admins }
})

onMounted(() => {
  loadList()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="系统管理"
      icon="Setting"
      subtitle="系统模块：人员名册与权限管理、季度/年度 BOL 分析报告中心（自动生成与查阅）。"
      :breadcrumbs="[{ label: '系统管理' }, { label: '人员管理' }]"
    />
    <div class="page-container">
      <!-- 子模块导航 Tab -->
      <div class="sys-tabs">
        <button
          v-for="tab in sysTabs"
          :key="tab.key"
          class="sys-tab"
          :class="{
            'is-active': activeTab === tab.key,
            'is-locked': tab.adminOnly && !isAdmin
          }"
          @click="switchTab(tab)"
        >
          <el-icon class="tab-icon"><component :is="tab.icon" /></el-icon>
          <span>{{ tab.label }}</span>
          <el-icon v-if="tab.adminOnly && !isAdmin" class="lock-icon"><Lock /></el-icon>
        </button>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">员工总数</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">在职员工</div>
          <div class="stat-value text-success">{{ stats.active }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">部门数量</div>
          <div class="stat-value">{{ stats.departments }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">系统管理员</div>
          <div class="stat-value text-warning">{{ stats.admins }}</div>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <el-input v-model="filters.department" placeholder="部门" clearable style="width: 160px" @keyup.enter="handleSearch" />
        <el-select v-model="filters.role" placeholder="角色" clearable style="width: 150px">
          <el-option v-for="opt in roleOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 120px">
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-button type="primary" @click="handleSearch">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
        <el-button @click="handleReset">
          <el-icon><Refresh /></el-icon>
          <span>重置</span>
        </el-button>
        <el-button type="success" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>新增员工</span>
        </el-button>
      </div>

      <!-- 表格 -->
      <div class="table-container">
        <el-table :data="pagedData" stripe border size="small" style="width: 100%">
          <el-table-column prop="username" label="用户名" width="120" />
          <el-table-column prop="name" label="姓名" width="100" />
          <el-table-column prop="department" label="部门" min-width="120" show-overflow-tooltip />
          <el-table-column prop="title" label="职位" min-width="120" show-overflow-tooltip />
          <el-table-column label="角色" width="120">
            <template #default="{ row }">
              <el-tag :type="roleTagType(row.role)" size="small">{{ roleLabel(row.role) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
          <el-table-column prop="phone" label="电话" width="130" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="openEdit(row)">编辑</el-button>
              <el-button
                :type="row.status === 'ACTIVE' ? 'warning' : 'success'"
                link
                size="small"
                @click="handleToggleStatus(row)"
              >
                {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
              </el-button>
              <el-button type="danger" link size="small" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            v-model:current-page="pagination.page"
            v-model:page-size="pagination.pageSize"
            :page-sizes="[10, 15, 20, 50]"
            :total="pagination.total"
            layout="total, sizes, prev, pager, next, jumper"
            background
            @current-change="handlePageChange"
            @size-change="handleSizeChange"
          />
        </div>
      </div>

      <!-- 新增/编辑对话框 -->
      <el-dialog
        v-model="dialogVisible"
        :title="dialogMode === 'create' ? '新增员工' : '编辑员工'"
        width="640px"
        :close-on-click-modal="false"
      >
        <el-form :model="form" label-width="90px" size="default">
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="用户名" required>
                <el-input v-model="form.username" placeholder="登录用户名" :disabled="dialogMode === 'edit'" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="姓名" required>
                <el-input v-model="form.name" placeholder="姓名" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item
            :label="dialogMode === 'create' ? '初始密码' : '重置初始密码'"
            :required="dialogMode === 'create'"
          >
            <el-input
              v-model="form.initial_password"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="dialogMode === 'create'
                ? '至少 8 位；用户首次登录后需修改'
                : '留空则不修改；设置后用户下次登录需修改'"
            />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="部门">
                <el-input v-model="form.department" placeholder="部门" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="职位">
                <el-input v-model="form.title" placeholder="职位" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="角色">
                <el-select v-model="form.role" style="width: 100%">
                  <el-option
                    v-for="opt in roleOptions.filter((o) => o.value)"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="状态">
                <el-select v-model="form.status" style="width: 100%">
                  <el-option label="在职" value="ACTIVE" />
                  <el-option label="停用" value="INACTIVE" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="邮箱">
                <el-input v-model="form.email" placeholder="邮箱" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="电话">
                <el-input v-model="form.phone" placeholder="电话" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="备注">
            <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注" />
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<style scoped>
/* 子模块导航 Tab */
.sys-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  padding: 4px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.sys-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: var(--font-body);
}

.sys-tab:hover {
  background: var(--color-primary-glow);
  color: var(--color-primary);
}

.sys-tab.is-active {
  background: var(--color-primary);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 3px 8px rgba(14, 165, 233, 0.3);
}

.sys-tab.is-locked {
  opacity: 0.5;
  cursor: not-allowed;
}

.sys-tab.is-locked:hover {
  background: transparent;
  color: var(--color-text-secondary);
}

.tab-icon {
  font-size: 15px;
}

.lock-icon {
  font-size: 12px;
  opacity: 0.8;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

/* stat-card / stat-label / stat-value 统一由 main.css 全局规范接管 */

.text-success {
  color: var(--color-success);
}

.text-warning {
  color: var(--color-warning);
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .sys-tabs {
    overflow-x: auto;
  }
  .sys-tab {
    white-space: nowrap;
  }
}
</style>
