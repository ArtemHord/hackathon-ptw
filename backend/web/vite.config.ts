import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const target = 'http://localhost:8000'
const proxied = ['/meetings', '/kb', '/chat', '/tts', '/settings', '/experts', '/integrations', '/debug', '/health']

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    proxy: {
      ...Object.fromEntries(proxied.map((p) => [p, target])),
      '/app/ws': { target, ws: true },
    },
  },
})
