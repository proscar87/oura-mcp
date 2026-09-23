import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// The Worker's logic runs under plain Node here. `cloudflare:workers` exists
// only inside workerd, so the one class it provides is stubbed; everything
// else is the real code.
export default defineConfig({
  resolve: {
    alias: {
      "cloudflare:workers": fileURLToPath(new URL("./tests/stubs/cloudflare-workers.ts", import.meta.url)),
    },
  },
});
