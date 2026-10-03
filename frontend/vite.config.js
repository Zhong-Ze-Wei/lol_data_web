import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const proxy = Object.fromEntries(
  ["/api", "/player/api", "/match/api", "/team/api", "/hero/api"].map(
    (path) => [path, { target: "http://127.0.0.1:5100", changeOrigin: true }],
  ),
);

export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { port: 5173, proxy },
  build: { outDir: "dist" },
  test: { environment: "jsdom", include: ["tests/**/*.test.js"] },
});
