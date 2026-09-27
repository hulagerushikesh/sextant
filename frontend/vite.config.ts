import path from 'node:path'
import { defineConfig } from 'vite'
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
})
