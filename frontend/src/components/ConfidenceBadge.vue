<script setup>
defineProps({ confidence: { type: String, required: true } })
</script>

<template>
  <span class="badge" :class="confidence">{{ confidence }}</span>
</template>

<style scoped>
/* stamp-style badge — matches the routing-slip ticket stamps in the chat console */
.badge {
  display: inline-block;
  font-family: var(--font-mono);
  padding: 1px 7px;
  border-radius: 2px;
  border: 1px solid currentColor;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
  transform: rotate(-2deg);
}
.badge.high {
  background: color-mix(in srgb, var(--loss) 16%, transparent);
  color: var(--loss);
}
.badge.medium {
  background: var(--brass-dim);
  color: var(--brass-bright);
}
.badge.low {
  background: color-mix(in srgb, var(--ink-dim) 16%, transparent);
  color: var(--ink-dim);
}
</style>
