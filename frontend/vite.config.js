import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// FastAPI mounts the built app at /console, so the base path must match
// (otherwise built asset URLs resolve against / instead of /console/).
//
// Backend port: use 8090, not FastAPI's usual 8000. On this machine the
// backend runs inside WSL2 while this dev server runs on Windows, and
// Windows reserves TCP 7978-8077 (Hyper-V/WinNAT excludedportrange) which
// silently breaks WSL2 localhost-forwarding for any port in that range —
// 8000 falls right in it. Start the backend with:
//   uvicorn web_server:app --host 0.0.0.0 --port 8090
const BACKEND = 'http://localhost:8090'

export default defineConfig({
  plugins: [vue()],
  base: '/console/',
  server: {
    proxy: {
      '/api': BACKEND,
      '/events': BACKEND,
    },
  },
})
