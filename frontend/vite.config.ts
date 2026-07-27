import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-проксі веде на backend (uvicorn). Порт бекенду береться з env
// BACKEND_PORT (дефолт 8000) — щоб не редагувати цей файл щоразу, коли
// порт зайнятий іншим локальним проєктом:
//   BACKEND_PORT=8010 npm run dev -- --port 5180
const backendPort = process.env.BACKEND_PORT ?? "8000";
const backendHttp = `http://localhost:${backendPort}`;
const backendWs = `ws://localhost:${backendPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: backendWs, ws: true },
      "/health": { target: backendHttp },
      "/api": { target: backendHttp },
    },
  },
});
