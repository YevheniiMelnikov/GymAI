import { build, context } from 'esbuild';
import { cp } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const watch = process.argv.includes('--watch');
const currentDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(currentDir, '..');
const cssSource = resolve(projectRoot, 'frontend/src/styles/common.css');
const cssTarget = resolve(projectRoot, 'static/css/common.css');

const buildOptions = {
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
};

async function syncStyles() {
  await cp(cssSource, cssTarget);
}

if (watch) {
  const ctx = await context(buildOptions);
  await syncStyles();
  await ctx.watch({
    async onRebuild(error) {
      if (error) {
        console.error('Rebuild failed', error);
        return;
      }
      try {
        await syncStyles();
      } catch (err) {
        console.error('Failed to sync styles', err);
      }
    }
  });
  console.log('Watching for changes...');
} else {
  await build(buildOptions);
  await syncStyles();
}
