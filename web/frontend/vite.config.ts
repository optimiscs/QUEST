import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  base: '/',
  server: { proxy: { '/api': 'http://127.0.0.1:6081' } },
  build: { sourcemap: true, rollupOptions: { input: { main: resolve(__dirname, 'index.html'), vllm: resolve(__dirname, 'vllm-dashboard.html') } } },
});
