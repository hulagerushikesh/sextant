import path from 'node:path'
// `vitest/config` rather than `vite`: a superset, so one file configures the
// dev server, the build, and the test run. Two files would be two places for
// the `@` alias to drift apart, and a test that resolves `@/lib/health`
// differently from the build is testing something the build never ships.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  // :3000 is this project's dev server (see CLAUDE.md, "Local ports"); the
  // redesign used :3100 while it lived beside the app it was replacing.
  server: { port: 3000, open: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
