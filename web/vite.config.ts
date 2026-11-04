import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Vite dev server proxies /api to the FastAPI web service.
// `npm run build` outputs web/dist (served by FastAPI).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8710',
    },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'jsdom',
    globals: false,
  },
});
