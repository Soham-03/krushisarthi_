import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During "npm run dev" the API runs on port 8000 (python run.py).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { "/api": "https://krushisarthi-h5fb.onrender.com" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
