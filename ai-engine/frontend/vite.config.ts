import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// During development, the frontend runs at :5173 and the backend at :8000.
// We proxy /api and /ws so the dashboard code can use relative URLs and
// production deployments (where both are served from the same origin) just
// work without any URL juggling.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})