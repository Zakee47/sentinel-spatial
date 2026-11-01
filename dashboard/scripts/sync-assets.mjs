import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = fileURLToPath(new URL('../../', import.meta.url));
const target = resolve(root, 'dashboard/public');
function readAsset(path, branch) {
  const local = resolve(root, path);
  if (existsSync(local)) return readFileSync(local);
  try { return execFileSync('git', ['show', `${branch}:${path}`], { cwd: root, stdio: ['ignore', 'pipe', 'ignore'] }); }
  catch { return null; }
}

export function syncAssets() {
  const names = ['demo.jsonl', 'site.json', 'products.json'];
  const replay = names.map(name => readAsset(`replay/${name}`, 'origin/devin/1793549929-server'));
  if (replay.every(Boolean)) {
    names.forEach((name, i) => writeFileSync(resolve(target, name), replay[i]));
    console.log('Sentinel assets: W1 replay/site/products synced.');
  } else console.log('Sentinel assets: complete W1 replay not available; keeping bundled replay.');
  const findings = readAsset('docs/rea/findings.json', 'origin/devin/1793550562-rea-drone');
  if (findings) {
    mkdirSync(resolve(target, 'rea'), { recursive: true });
    writeFileSync(resolve(target, 'rea/findings.json'), findings);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) syncAssets();
