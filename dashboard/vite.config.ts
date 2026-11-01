import { defineConfig } from 'vite';
import { existsSync, cpSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { syncAssets } from './scripts/sync-assets.mjs';

syncAssets();

export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/ws': { target: 'ws://127.0.0.1:8000', ws: true } } },
  plugins: [{
    name: 'sentinel-twin-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const name = req.url?.split('?')[0].match(/(?:^|\/)twin\/out\/(scene\.glb|twin_points\.bin|twin\.json)$/)?.[1];
        const file = name && resolve('../twin/out', name);
        if (!file || !existsSync(file)) return next();
        res.setHeader('Content-Type', name === 'twin.json' ? 'application/json' : 'application/octet-stream');
        res.end(readFileSync(file));
      });
      server.middlewares.use((req, res, next) => {
        if (!req.url?.split('?')[0].endsWith('/depth/out/depth_points.bin')) return next();
        const file = resolve('../depth/out/depth_points.bin');
        if (!existsSync(file)) return next();
        res.setHeader('Content-Type', 'application/octet-stream');
        res.end(readFileSync(file));
      });
    },
    closeBundle() {
      if (existsSync('../twin/out')) cpSync('../twin/out', 'dist/twin/out', { recursive: true });
      if (existsSync('../depth/out/depth_points.bin')) {
        cpSync('../depth/out', 'dist/depth/out', { recursive: true });
      }
    },
  }],
});
