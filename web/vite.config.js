import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Relative asset paths so the built app also works when web/app.py serves
  // dist/ directly, without Vite, on whatever host the venue gives us.
  base: './',
  server: {
    // Reachable from a phone or the projector laptop, not just localhost.
    host: true,
    proxy: {
      '/api': 'http://127.0.0.1:5001',
    },
  },
})
