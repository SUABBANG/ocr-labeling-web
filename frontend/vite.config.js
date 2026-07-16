import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev 서버는 백엔드(8000)로 /api 프록시. build 시 backend가 dist/를 서빙.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
