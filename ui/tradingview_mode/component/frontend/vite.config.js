import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Streamlit serves the component under /component/<name>/, so asset URLs
// must be relative. An absolute base ("/") makes the iframe load Streamlit's
// own HTML instead of this bundle and the component silently never boots.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
