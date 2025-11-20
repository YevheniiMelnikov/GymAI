import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
    plugins: [react()],
    root: 'frontend',
    base: '/static/', // Django static url
    build: {
        outDir: '../static/js',
        emptyOutDir: true,
        manifest: true, // Generate manifest.json for Django to use if needed, or just for good measure
        rollupOptions: {
            input: path.resolve(__dirname, 'frontend/src/main.tsx'),
            output: {
                entryFileNames: 'index.js', // Keep it simple for now to match previous output if possible, though hashing is better.
                // If we want to match the exact previous behavior of a single file named index.js:
                assetFileNames: 'assets/[name].[ext]',
                chunkFileNames: 'chunks/[name].js',
            }
        }
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './frontend/src'),
        },
    },
});
