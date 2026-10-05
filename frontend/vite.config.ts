import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: loadEnv('production', '.', 'VITE_').VITE_BASE_PATH || '/',
  plugins: [react()],
  build: { chunkSizeWarningLimit: 600 },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
