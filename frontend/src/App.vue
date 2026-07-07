<script setup>
import { ref, onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { getStats } from './api'
import { useSSE } from './composables/useSSE'

const pendingCount = ref(0)

async function refreshStats() {
  try {
    const stats = await getStats()
    pendingCount.value = stats.by_status?.pending || 0
  } catch {
    // best-effort — badge just stays stale if this fails
  }
}

useSSE((evt) => {
  if (evt.type === 'review_new' || evt.type === 'review_updated') refreshStats()
})

onMounted(refreshStats)
</script>

<template>
  <div class="shell">
    <header>
      <h1><span class="mark">§</span> 人機協作審核主控台</h1>
      <nav>
        <RouterLink to="/">待審佇列</RouterLink>
        <RouterLink to="/history">歷史</RouterLink>
        <span v-if="pendingCount" class="pending-badge">{{ pendingCount }} 待審</span>
      </nav>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>

<style>
:root {
  /* ledger / order-desk palette — shared with the chat console */
  --bg:           #16140f;
  --surface:      #1e1b14;
  --surface-2:    rgba(233,226,208,0.035);
  --border:       rgba(233,226,208,0.10);
  --ink:          #e9e2d0;
  --ink-dim:      #948c74;
  --brass:        #c6963a;
  --brass-bright: #e0ac49;
  --brass-dim:    rgba(198,150,58,0.16);
  --gain:         #5ca867;
  --loss:         #c1594a;
  --accent:       var(--brass);
  --font-display: 'Fraunces', Georgia, serif;
  --font-body:    'IBM Plex Sans', -apple-system, sans-serif;
  --font-mono:    'IBM Plex Mono', 'Courier New', monospace;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:           #f2ede0;
    --surface:      #fbf8f0;
    --surface-2:    rgba(42,36,22,0.03);
    --border:       #ddd3ba;
    --ink:          #2a2416;
    --ink-dim:      #7a705c;
    --brass:        #9c7530;
    --brass-bright: #7d5d26;
    --brass-dim:    rgba(156,117,48,0.12);
    --gain:         #3f7a49;
    --loss:         #a1452f;
    --accent:       var(--brass);
    color-scheme: light;
  }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--font-body);
  background: var(--bg);
  color: var(--ink);
}

.shell { max-width: 880px; margin: 0 auto; padding: 24px 20px 60px; }

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 28px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
h1 {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.3rem;
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 9px;
}
h1 .mark {
  font-family: var(--font-mono);
  font-style: normal;
  font-weight: 600;
  font-size: 0.65rem;
  color: var(--bg);
  background: var(--brass);
  border-radius: 3px;
  padding: 2px 5px;
}
nav { display: flex; align-items: center; gap: 16px; }
nav a {
  color: var(--ink-dim);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}
nav a.router-link-exact-active { color: var(--brass-bright); font-weight: 600; }
.pending-badge {
  background: var(--brass-dim);
  color: var(--brass-bright);
  border: 1px solid rgba(198,150,58,0.3);
  border-radius: 3px;
  padding: 2px 8px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 600;
}
</style>
