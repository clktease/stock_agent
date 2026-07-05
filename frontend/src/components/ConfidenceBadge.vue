<script setup>
defineProps({ confidence: { type: String, required: true } })
</script>

<template>
  <span class="badge" :class="confidence">{{ confidence }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  white-space: nowrap;
}
.badge.high {
  background: color-mix(in srgb, #ef4444 18%, transparent);
  color: #ef4444;
}
.badge.medium {
  background: color-mix(in srgb, #f59e0b 18%, transparent);
  color: #f59e0b;
}
.badge.low {
  background: color-mix(in srgb, #6366f1 18%, transparent);
  color: #818cf8;
}
</style>
