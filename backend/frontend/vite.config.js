import { resolve } from "node:path";
import { defineConfig } from "vite";

const root = resolve(import.meta.dirname);

export default defineConfig({
  root,
  build: {
    outDir: resolve(root, "dist"),
    emptyOutDir: true,
    sourcemap: false,
    minify: false,
    lib: {
      entry: resolve(root, "src/app.js"),
      name: "HermesDealsUI",
      formats: ["iife"],
      fileName: () => "app.js",
    },
    rolldownOptions: {
      output: {
        codeSplitting: false,
        entryFileNames: "app.js",
      },
    },
  },
});
