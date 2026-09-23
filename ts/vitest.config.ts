import { defineConfig } from "vitest/config";

// The Worker in ./worker has its own suite, its own dependencies and its own
// config; run from here, its tests would resolve against the wrong ones.
export default defineConfig({
  test: { include: ["tests/**/*.test.ts"] },
});
