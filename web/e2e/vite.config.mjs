import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../', import.meta.url)),
  plugins: [react()],
  resolve: { alias: { 'livekit-client': fileURLToPath(new URL('./transport.js', import.meta.url)) } },
  build: { outDir: fileURLToPath(new URL('../../.review-checks/mobile-site', import.meta.url)), emptyOutDir: true },
});
