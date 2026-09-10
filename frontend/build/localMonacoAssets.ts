import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import type { Plugin } from 'vite';
import { resolveMonacoWorkerAssets } from '../src/app/services/monacoWorkerAssets';

const moduleId = 'virtual:local-monaco';
const resolvedId = `\0${moduleId}`;

// Snapshot only the installed distribution. Request paths never reach the
// filesystem; the same byte snapshot is served in development and emitted in
// production. A content-addressed directory prevents mixed-version cache hits.
export function readMonacoDistribution(packageRoot: string) {
  const files = new Map<string, Buffer>();
  function visit(directory: string, prefix = '') {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0)) {
      const relative = `${prefix}${entry.name}`;
      if (entry.isDirectory()) visit(path.join(directory, entry.name), `${relative}/`);
      else if (entry.isFile()) files.set(relative, readFileSync(path.join(directory, entry.name)));
      else throw new Error(`Unsupported Monaco distribution entry: ${relative}`);
    }
  }
  visit(path.join(packageRoot, 'min/vs'));
  files.set('LICENSE.txt', readFileSync(path.join(packageRoot, 'LICENSE')));
  for (const required of ['loader.js', 'editor/editor.main.js', 'editor/editor.main.css']) {
    if (!files.get(required)?.length) throw new Error(`Missing Monaco distribution file: ${required}`);
  }
  const hash = createHash('sha256');
  for (const [name, data] of files) {
    hash.update(JSON.stringify([name, data.length]));
    hash.update(data);
  }
  const directory = `assets/monaco-${hash.digest('hex')}/vs`;
  const workers = resolveMonacoWorkerAssets(Object.fromEntries(
    [...files.keys()].filter(name => name.startsWith('assets/')).map(name => [`/${name}`, name]),
  ));
  return { files, directory, workers };
}

export function localMonacoAssets(): Plugin {
  let distribution: ReturnType<typeof readMonacoDistribution>;
  let base: string;
  return {
    name: 'local-monaco-distribution',
    configResolved(config) {
      base = config.base;
      if (!base.startsWith('/') || base.startsWith('//') || base.includes('\\') || /[?#]/.test(base)) {
        throw new Error('Monaco requires a same-origin absolute application base path');
      }
      distribution = readMonacoDistribution(path.join(config.root, 'node_modules/monaco-editor'));
    },
    resolveId(id) { if (id === moduleId) return resolvedId; },
    load(id) {
      if (id !== resolvedId) return;
      const vs = `${base}${distribution.directory}`;
      return `export default ${JSON.stringify({
        vs,
        workers: Object.fromEntries(Object.entries(distribution.workers).map(([kind, file]) => [kind, `${vs}/${file}`])),
      })};`;
    },
    generateBundle() {
      for (const [name, source] of distribution.files) {
        this.emitFile({ type: 'asset', fileName: `${distribution.directory}/${name}`, source });
      }
    },
    configureServer(server) {
      const prefix = `${base}${distribution.directory}/`;
      const mime: Record<string, string> = {
        '.js': 'text/javascript', '.css': 'text/css', '.ttf': 'font/ttf',
        '.json': 'application/json', '.map': 'application/json', '.svg': 'image/svg+xml',
      };
      server.middlewares.use((request, response, next) => {
        // Do not normalize or decode traversal into another valid asset.
        const url = (request.url ?? '').split('?')[0];
        if (!url.startsWith(prefix)) return next();
        if (request.method !== 'GET' && request.method !== 'HEAD') {
          response.statusCode = 405;
          response.setHeader('Allow', 'GET, HEAD');
          return response.end();
        }
        const name = url.slice(prefix.length);
        const data = distribution.files.get(name);
        response.setHeader('X-Content-Type-Options', 'nosniff');
        if (!data) { response.statusCode = 404; return response.end(); }
        response.setHeader('Content-Type', mime[path.extname(name)] ?? 'text/plain');
        response.setHeader('Content-Length', data.length);
        response.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
        response.end(request.method === 'HEAD' ? undefined : data);
      });
    },
  };
}
