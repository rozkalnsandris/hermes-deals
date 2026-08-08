import { resolve } from "node:path";
import { defineConfig } from "vite";

const root = resolve(import.meta.dirname);

export default defineConfig({
  root,
  base: "/ui/",
  build: {
    outDir: resolve(root, "dist-w4"),
    emptyOutDir: true,
    sourcemap: false,
    minify: false,
    manifest: true,
    assetsInlineLimit: 0,
    cssCodeSplit: true,
    rolldownOptions: {
      input: resolve(root, "src/w4-entry.js"),
      output: {
        entryFileNames: "assets/[name].[hash].js",
        chunkFileNames: "assets/[name].[hash].js",
        assetFileNames: "assets/[name].[hash][extname]",
      },
    },
  },
});
