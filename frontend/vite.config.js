import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// FastAPI mounts the built app at /console, so the base path must match
// (otherwise built asset URLs resolve against / instead of /console/).
export default defineConfig({
  plugins: [vue()],
  base: '/console/',
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/events': 'http://localhost:8000',
    },
  },
})
