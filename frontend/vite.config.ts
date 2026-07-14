import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-проксі веде WS на backend (uvicorn, порт 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/health": { target: "http://localhost:8000" },
    },
  },
});
