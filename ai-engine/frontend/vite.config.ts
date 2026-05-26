import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// During development, the frontend runs at :5173 and the backend at :8000.
// We proxy /api and /ws so the dashboard code can use relative URLs and
// production deployments (where both are served from the same origin) just
// work without any URL juggling.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const wsProxyTarget = env.VITE_WS_PROXY_TARGET || 'ws://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': apiProxyTarget,
        '/ws': {
          target: wsProxyTarget,
          ws: true,
        },
      },
    },
  }
})
