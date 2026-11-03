import { defineConfig } from 'vite';
export default defineConfig({ base: '/crm/', build: { outDir: 'dist' }, server: { proxy: { '/crm/api': { target: 'http://localhost:8787' } } } });
