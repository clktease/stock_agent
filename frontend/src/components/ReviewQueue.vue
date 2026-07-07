<script setup>
import { ref, computed, onMounted } from 'vue'
import ReviewCard from './ReviewCard.vue'
import { listItems } from '../api'
import { useSSE } from '../composables/useSSE'

const items = ref([])
const filterType = ref('')
const loading = ref(true)
const errorMsg = ref('')

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await listItems({ status: 'pending' })
    items.value = res.items
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  filterType.value ? items.value.filter((i) => i.item_type === filterType.value) : items.value
)

function onUpdated(updatedItem) {
  items.value = items.value.filter((i) => i.id !== updatedItem.id)
}

useSSE((evt) => {
  if (evt.type === 'review_new') {
    if (!items.value.some((i) => i.id === evt.item.id)) items.value.unshift(evt.item)
  } else if (evt.type === 'review_updated') {
    items.value = items.value.filter((i) => i.id !== evt.item.id)
  }
})

onMounted(load)
</script>

<template>
  <section>
    <div class="toolbar">
      <h2>待審佇列<span class="count">{{ filtered.length }}</span></h2>
      <select v-model="filterType">
        <option value="">全部類型</option>
        <option value="influencer_alert">網紅發言警示</option>
        <option value="holdings_anomaly">持股異常變動</option>
      </select>
    </div>

    <p v-if="loading" class="hint">載入中…</p>
    <p v-else-if="errorMsg" class="error">{{ errorMsg }}</p>
    <p v-else-if="!filtered.length" class="hint">目前沒有待審項目。</p>
    <ReviewCard v-for="item in filtered" :key="item.id" :item="item" @updated="onUpdated" />
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
h2 {
  margin: 0;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
h2 .count {
  font-family: var(--font-mono);
  font-style: normal;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--brass-bright);
  background: var(--brass-dim);
  border-radius: 3px;
  padding: 2px 7px;
}
select {
  background: var(--surface-2);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 0.78rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 10px;
}
.hint { color: var(--ink-dim); font-size: 0.9rem; }
.error { color: var(--loss); }
</style>
