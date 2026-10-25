import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Chongqing Family Translator",
        short_name: "Translator",
        lang: "zh-HK",
        display: "standalone",
        background_color: "#ffffff",
        theme_color: "#1a73e8",
        icons: [{ src: "icon.svg", sizes: "any", type: "image/svg+xml" }],
      },
      workbox: {
        // The VAD model and WASM (several MB) load on demand; the app needs the network anyway.
        globIgnores: ["vad/**"],
        navigateFallbackDenylist: [/^\/ws/, /^\/health/],
      },
    }),
  ],
  server: {
    // `npm run dev` on :5173 talks to the backend on :8000.
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/health": "http://localhost:8000",
    },
  },
  test: { environment: "node" },
});
