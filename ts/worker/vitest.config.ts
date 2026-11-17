import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// The Worker's logic runs under plain Node here. `cloudflare:workers` exists
// only inside workerd, so the two classes it provides are stubbed; everything
// else is the real code.
export default defineConfig({
  resolve: {
    alias: {
      "cloudflare:workers": fileURLToPath(new URL("./tests/stubs/cloudflare-workers.ts", import.meta.url)),
    },
  },
  test: {
    // The OAuth provider imports `cloudflare:workers` too. Inlined so the alias
    // above reaches it: bearer.test.ts runs the real provider, not a fake.
    server: { deps: { inline: ["@cloudflare/workers-oauth-provider"] } },
  },
});
