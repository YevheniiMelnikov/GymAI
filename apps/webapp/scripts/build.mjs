import { build, context } from 'esbuild';

const watch = process.argv.includes('--watch');

if (watch) {
  const ctx = await context({
    entryPoints: ['frontend/src/index.ts'],
    bundle: true,
    format: 'iife',
    target: 'es2017',
    platform: 'browser',
    sourcemap: true,
    minify: true,
    legalComments: 'none',
    outfile: 'static/js/index.js',
    logLevel: 'info',
    color: true
  });
  await ctx.watch();
  console.log('Watching for changes...');
} else {
  await build({
    entryPoints: ['frontend/src/index.ts'],
    bundle: true,
    format: 'iife',
    target: 'es2017',
    platform: 'browser',
    sourcemap: true,
    minify: true,
    legalComments: 'none',
    outfile: 'static/js/index.js',
    logLevel: 'info',
    color: true
  });
}
