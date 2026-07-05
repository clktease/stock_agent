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
      <h1>人機協作審核主控台</h1>
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
  --bg: #0f1115;
  --surface: #171a21;
  --border: #2a2e37;
  --accent: #6366f1;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f7f7fb;
    --surface: #ffffff;
    --border: #e2e2ea;
    --accent: #4f46e5;
    color-scheme: light;
  }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: #e6e6ea;
}
@media (prefers-color-scheme: light) {
  body { color: #1a1a1f; }
}

.shell { max-width: 880px; margin: 0 auto; padding: 24px 20px 60px; }

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 28px;
}
h1 { font-size: 1.3rem; margin: 0; }
nav { display: flex; align-items: center; gap: 14px; }
nav a {
  color: inherit;
  opacity: 0.65;
  text-decoration: none;
  font-size: 0.92rem;
}
nav a.router-link-exact-active { opacity: 1; font-weight: 600; color: var(--accent); }
.pending-badge {
  background: var(--accent);
  color: #fff;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.78rem;
  font-weight: 600;
}
</style>
