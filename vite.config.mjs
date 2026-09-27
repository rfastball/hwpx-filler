import { fileURLToPath } from "node:url";
import { cpSync, existsSync } from "node:fs";
import { join } from "node:path";

const frontendRoot = fileURLToPath(new URL("./frontend/", import.meta.url));
const webOutDir = fileURLToPath(new URL("./build/web/", import.meta.url));
const studioRoot = fileURLToPath(new URL("./build/rhwp/studio/", import.meta.url));
const studioManifest = fileURLToPath(new URL("./vendor/rhwp/studio-runtime.json", import.meta.url));

export default {
  root: frontendRoot,
  base: "./",
  plugins: [{
    name: "local-rhwp-studio",
    closeBundle() {
      if (!existsSync(join(studioRoot, "index.html"))) {
        throw new Error("rhwp Studio build is missing; run scripts/build_rhwp.ps1");
      }
      cpSync(studioRoot, join(webOutDir, "rhwp", "studio"), { recursive: true });
      cpSync(studioManifest, join(webOutDir, "rhwp", "studio-runtime.json"));
    },
  }],
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
