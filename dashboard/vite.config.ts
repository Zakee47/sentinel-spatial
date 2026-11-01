import { defineConfig } from 'vite';
import { existsSync, cpSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

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
    },
    closeBundle() {
      if (existsSync('../twin/out')) cpSync('../twin/out', 'dist/twin/out', { recursive: true });
      if (existsSync('../replay/demo.jsonl')) cpSync('../replay/demo.jsonl', 'dist/server-demo.jsonl');
    },
  }],
});
