import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev the UI runs on :5173 and proxies /api to the FastAPI service on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // React and the chart library are big and rarely change: separate files the browser can cache between releases
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules[\/](react|react-dom|scheduler)[\/]/.test(id)) return 'react'
          if (/node_modules[\/](recharts|d3-[^\/]+|victory-vendor|internmap|recharts-scale|decimal\.js-light|lodash|react-smooth|react-transition-group|fast-equals|clsx|tiny-invariant|prop-types|react-is)[\/]/.test(id)) return 'charts'
          return undefined
        },
      },
    },
  },
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
})
