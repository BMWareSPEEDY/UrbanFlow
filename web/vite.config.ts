import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Output goes straight into Flask's static tree so `python app.py` remains the
// single command that runs the demo. No Node dependency at demo time (D-17).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/command/',
  build: {
    outDir: '../static/command',
    emptyOutDir: true,
    sourcemap: false,
    target: 'es2020',
  },
  server: {
    proxy: {
      '/api/v1': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:5000',
    },
  },
})
