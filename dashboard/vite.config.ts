import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Serve the dashboard under /app/ so it co-exists with the FastAPI webhooks on port 8000.
  base: '/app/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    // Proxy API and SSE calls to the FastAPI backend during local dev.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
