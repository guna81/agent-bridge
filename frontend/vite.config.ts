import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the UI runs on :5173 and talks to the proxy on :8000.
const backend = process.env.VITE_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/v1": backend,
      "/admin": { target: backend, ws: true },
    },
  },
});
