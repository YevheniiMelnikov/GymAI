import { build } from 'esbuild';

await build({
  entryPoints: ['frontend/src/index.ts'],
  bundle: true,
  format: 'iife',
  target: 'es2017',
  minify: true,
  sourcemap: true,
  outfile: 'static/js/index.js',
});
