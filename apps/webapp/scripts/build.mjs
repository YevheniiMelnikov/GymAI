import { build } from 'esbuild';

await build({
  entryPoints: ['frontend/src/index.ts'],
  bundle: true,
  format: 'esm',
  minify: true,
  sourcemap: true,
  outfile: 'static/js/index.js',
});
