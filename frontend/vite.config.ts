import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Builds straight into the Django app's static dir as one js + one css file.
// The names carry a content hash and manifest.json lists them; the Django
// view reads it, so a browser can never keep serving an old build from cache.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/chat/",
  build: {
    outDir: "../deep_agent_app/static/chat",
    emptyOutDir: true,
    manifest: "manifest.json",
    sourcemap: false,
    // recharts + the AI SDK make one ~950 kB bundle; one file is the point here.
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      input: "src/main.tsx",
      output: {
        entryFileNames: "index-[hash].js",
        assetFileNames: "index-[hash].[ext]",
        codeSplitting: false,
      },
    },
  },
});
