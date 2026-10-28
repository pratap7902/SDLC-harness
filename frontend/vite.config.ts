import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served by FastAPI at the page paths (app/web/spa.py); the API is the same origin. In dev,
// Vite on :5173 proxies /api to the backend on :8791 (`make dev`).
export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8791', '/health': 'http://localhost:8791' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
