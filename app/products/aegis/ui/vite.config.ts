import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Served by the Aegis worker at /aegis/; in development, API calls are proxied to the worker.
export default defineConfig({
  base: '/aegis/',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: { port: 5181, proxy: { '/aegis/api': 'http://127.0.0.1:8102' } },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
