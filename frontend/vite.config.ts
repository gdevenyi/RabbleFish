import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development Vite serves the UI and forwards the API and the WebSocket to the backend.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': backend,
      '/ws': { target: backend, ws: true },
    },
  },
})
