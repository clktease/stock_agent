<script setup>
import { ref, onMounted } from 'vue'
import ConfidenceBadge from './ConfidenceBadge.vue'
import { listItems, getItem } from '../api'

const STATUS_LABELS = { approved: '已核准', rejected: '已退回', edited: '已修改核准' }

const groups = ref({ approved: [], rejected: [], edited: [] })
const expanded = ref({})
const loading = ref(true)

async function load() {
  loading.value = true
  const statuses = Object.keys(groups.value)
  const results = await Promise.all(statuses.map((s) => listItems({ status: s })))
  statuses.forEach((s, idx) => { groups.value[s] = results[idx].items })
  loading.value = false
}

async function toggle(id) {
  if (expanded.value[id]) {
    delete expanded.value[id]
    return
  }
  expanded.value[id] = await getItem(id)
}

onMounted(load)
</script>

<template>
  <section>
    <h2><span class="mark">§</span> 審核歷史</h2>
    <p v-if="loading" class="hint">載入中…</p>
    <template v-else>
      <div v-for="(list, status) in groups" :key="status" class="group">
        <h3>{{ STATUS_LABELS[status] }}（{{ list.length }}）</h3>
        <p v-if="!list.length" class="hint">尚無項目。</p>
        <div v-for="item in list" :key="item.id" class="row">
          <div class="row-header" @click="toggle(item.id)">
            <span>{{ item.title }}</span>
            <ConfidenceBadge :confidence="item.confidence" />
          </div>
          <div v-if="expanded[item.id]" class="detail">
            <p class="text">{{ expanded[item.id].edited_text || expanded[item.id].ai_summary }}</p>
            <p v-if="expanded[item.id].reviewer_note" class="note">備註：{{ expanded[item.id].reviewer_note }}</p>
            <ul class="timeline">
              <li v-for="log in expanded[item.id].logs" :key="log.id">
                <time>{{ log.created_at }}</time> — {{ log.action }}
                <span v-if="log.note">（{{ log.note }}）</span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
h2 {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
  display: flex;
  align-items: baseline;
  gap: 9px;
  margin-bottom: 20px;
}
h2 .mark {
  font-family: var(--font-mono);
  font-style: normal;
  font-weight: 600;
  font-size: 0.65rem;
  color: var(--bg);
  background: var(--brass);
  border-radius: 3px;
  padding: 2px 5px;
}
.group { margin-bottom: 24px; }
h3 {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.hint { color: var(--ink-dim); font-size: 0.9rem; }
.row {
  border: 1px solid var(--border);
  border-radius: 4px;
  margin-bottom: 8px;
  overflow: hidden;
}
.row-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  background: var(--surface-2);
}
.row-header:hover { background: var(--brass-dim); }
.detail {
  padding: 10px 14px;
  border-top: 1px solid var(--border);
}
.text { white-space: pre-wrap; line-height: 1.5; }
.note { color: var(--ink-dim); font-size: 0.85rem; }
.timeline {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  font-family: var(--font-mono);
  font-size: 0.76rem;
  color: var(--ink-dim);
}
</style>
