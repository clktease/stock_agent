<script setup>
import { ref } from 'vue'
import ConfidenceBadge from './ConfidenceBadge.vue'
import { updateItem } from '../api'

const props = defineProps({ item: { type: Object, required: true } })
const emit = defineEmits(['updated'])

const editing = ref(false)
const editedText = ref(props.item.ai_summary)
const note = ref('')
const busy = ref(false)
const error = ref('')

const typeLabel = {
  influencer_alert: '網紅發言警示',
  holdings_anomaly: '持股異常變動',
}

async function act(action) {
  busy.value = true
  error.value = ''
  try {
    const payload = { action }
    if (note.value) payload.note = note.value
    if (action === 'edit') payload.edited_text = editedText.value
    const updated = await updateItem(props.item.id, payload)
    emit('updated', updated)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <article class="card">
    <header>
      <h3>{{ item.title }}</h3>
      <ConfidenceBadge :confidence="item.confidence" />
    </header>
    <p class="type">{{ typeLabel[item.item_type] || item.item_type }}</p>

    <p class="summary" v-if="!editing">{{ item.ai_summary }}</p>
    <textarea v-else v-model="editedText" rows="4" />

    <ul class="sources" v-if="item.source_urls?.length">
      <li v-for="url in item.source_urls" :key="url">
        <a :href="url" target="_blank" rel="noopener">{{ url }}</a>
      </li>
    </ul>

    <input class="note" v-model="note" placeholder="審核備註（選填）" />

    <div class="actions">
      <button class="approve" :disabled="busy" @click="act('approve')">核准</button>
      <button class="reject" :disabled="busy" @click="act('reject')">退回</button>
      <button v-if="!editing" :disabled="busy" @click="editing = true">修改</button>
      <button v-else class="approve" :disabled="busy" @click="act('edit')">儲存修改並核准</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
  </article>
</template>

<style scoped>
.card {
  border: 1px solid var(--border);
  border-left: 2px solid var(--brass);
  border-radius: 4px;
  padding: 16px 18px;
  margin-bottom: 14px;
  background: var(--surface-2);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
h3 {
  margin: 0;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.05rem;
}
.type {
  margin: 4px 0 10px;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.summary {
  white-space: pre-wrap;
  line-height: 1.55;
  margin: 0 0 10px;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 10px;
  font-family: var(--font-body);
  padding: 8px;
  border-radius: 3px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--ink);
}
.sources {
  list-style: none;
  padding: 0;
  margin: 0 0 10px;
  font-family: var(--font-mono);
  font-size: 0.76rem;
}
.sources a {
  color: var(--brass-bright);
}
.note {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 10px;
  border-radius: 3px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--ink);
  margin-bottom: 10px;
}
.actions {
  display: flex;
  gap: 8px;
}
button {
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 0.85rem;
  padding: 6px 14px;
  border-radius: 3px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
button:hover:not(:disabled) { border-color: var(--brass); background: var(--brass-dim); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.approve { color: var(--gain); border-color: color-mix(in srgb, var(--gain) 40%, transparent); }
button.approve:hover:not(:disabled) { background: color-mix(in srgb, var(--gain) 12%, transparent); border-color: var(--gain); }
button.reject { color: var(--loss); border-color: color-mix(in srgb, var(--loss) 40%, transparent); }
button.reject:hover:not(:disabled) { background: color-mix(in srgb, var(--loss) 12%, transparent); border-color: var(--loss); }
.error { color: var(--loss); font-size: 0.85rem; }
</style>
