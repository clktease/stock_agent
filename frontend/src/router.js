import { createRouter, createWebHistory } from 'vue-router'
import ReviewQueue from './components/ReviewQueue.vue'
import HistoryView from './components/HistoryView.vue'

const routes = [
  { path: '/', name: 'queue', component: ReviewQueue },
  { path: '/history', name: 'history', component: HistoryView },
]

export default createRouter({
  history: createWebHistory('/console/'),
  routes,
})
