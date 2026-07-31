import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("./frontend/", import.meta.url));
const webOutDir = fileURLToPath(new URL("./build/web/", import.meta.url));

export default {
  root: frontendRoot,
  base: "./",
  build: {
    outDir: webOutDir,
    emptyOutDir: true,
    manifest: true,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    modulePreload: false,
    minify: false,
    rolldownOptions: {
      treeshake: false,
    },
  },
};
