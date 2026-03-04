import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// For local dev, set VITE_API_URL to the API Gateway URL (from CDK output "ApiUrl").
// In production the SPA is served via CloudFront which proxies /api/* to API Gateway.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: process.env.VITE_API_URL
      ? {
          '/api': {
            target: process.env.VITE_API_URL,
            changeOrigin: true,
          },
        }
      : undefined,
  },
});
