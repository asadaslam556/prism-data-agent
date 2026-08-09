import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, /api/* is proxied to the FastAPI backend so the app works
// without CORS friction. In production the same path is proxied by nginx
// (see nginx.conf) or by whatever reverse proxy sits in front.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
