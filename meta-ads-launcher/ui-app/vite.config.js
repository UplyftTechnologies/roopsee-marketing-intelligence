import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into ../ui/dist (served by FastAPI). In dev: UI on :5174, API proxied to :8765.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../ui/dist', emptyOutDir: true },
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8765', '/creatives': 'http://127.0.0.1:8765' } },
})
