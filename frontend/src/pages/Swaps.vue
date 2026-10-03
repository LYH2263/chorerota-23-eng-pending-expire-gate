<template>
  <div>
    <h1 class="brand">对调</h1>
    <p class="muted">先生成周表，再填写两格对调（day + task_id）。过期以库内状态标记为准，前后端同一口径。</p>
    <div class="week-card" style="margin-bottom:12px">
      <label>A day <input type="number" v-model.number="form.a_day" /></label>
      <label>A task_id <input type="number" v-model.number="form.a_task" /></label>
      <label>B day <input type="number" v-model.number="form.b_day" /></label>
      <label>B task_id <input type="number" v-model.number="form.b_task" /></label>
      <button @click="request">申请对调</button>
    </div>
    <p v-if="err" class="err">{{ err }}</p>
    <ul class="list">
      <li v-for="s in rows" :key="s.id">
        #{{ s.id }} D{{ s.a_day }}/T{{ s.a_task }} ↔ D{{ s.b_day }}/T{{ s.b_task }}
        <span class="chip" :class="chipClass(s.status)">{{ s.status }}</span>
        <template v-if="s.status==='pending'">
          <button style="margin-left:8px" @click="confirm(s.id)">确认改表</button>
          <button class="ghost" style="margin-left:4px" @click="expire(s.id)">标记过期</button>
        </template>
        <span v-else-if="s.status==='expired'" class="muted" style="margin-left:8px">已过期，不可确认</span>
      </li>
    </ul>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
// 与后端 main.py 的 SWAP_* 常量同一组字面值；前端不自造过期判定（不看本地时钟）。
const STATUS = { PENDING: 'pending', CONFIRMED: 'confirmed', EXPIRED: 'expired' }
const rows = ref([])
const err = ref('')
const form = ref({ a_day: 0, a_task: 1, b_day: 1, b_task: 1 })
function chipClass(status) {
  if (status === STATUS.PENDING) return 'coral'
  if (status === STATUS.EXPIRED) return 'expired'
  return ''
}
async function load() { rows.value = await api('/swaps') }
async function callAndReload(fn) {
  err.value = ''
  try { await fn(); await load() } catch (e) { err.value = e.message }
}
function request() { callAndReload(() => api('/weeks/1/swaps', { method: 'POST', body: JSON.stringify(form.value) })) }
function confirm(id) { callAndReload(() => api('/swaps/' + id + '/confirm', { method: 'POST', body: '{}' })) }
function expire(id) { callAndReload(() => api('/swaps/' + id + '/expire', { method: 'POST', body: '{}' })) }
onMounted(load)
</script>
