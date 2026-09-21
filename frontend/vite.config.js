import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Keep the browser's Host header (changeOrigin: false) so Django's CSRF origin
// check sees localhost:5173 on both the Origin and the Host.
const backend = { target: 'http://127.0.0.1:8000', changeOrigin: false };

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // The production build is served by Django as static files under /static/.
  base: command === 'build' ? '/static/' : '/',
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/admin': backend,
      '/print': backend,
      '/reports': backend,
      '/static': backend,
    },
  },
}));
