import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build straight into Flask's static dir; Flask serves static/dist/index.html.
export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5860",
    },
  },
});
