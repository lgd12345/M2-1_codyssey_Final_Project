import { defineConfig } from 'vite'

// Preserve the browser-facing Host so FastAPI can compare it with Origin.
// Vite's string shorthand enables changeOrigin and breaks that comparison.
const proxy = {
  '/api': {
    target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
    changeOrigin: false,
  },
}

export default defineConfig({
  server: {
    host: '0.0.0.0',
    proxy,
  },
  preview: { proxy },
})
