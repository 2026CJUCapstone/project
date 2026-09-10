import path from "path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";
import { localMonacoAssets } from './build/localMonacoAssets';

export default defineConfig({
  plugins: [react(), tailwindcss(), localMonacoAssets()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
