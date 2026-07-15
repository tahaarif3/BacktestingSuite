import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the built assets load under Electron's file:// protocol.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
