// @vitest-environment node
import http from 'node:http';
import path from 'node:path';
import { build, createServer } from 'vite';
import { describe, expect, it } from 'vitest';
import { localMonacoAssets, readMonacoDistribution } from './localMonacoAssets';

const root = path.resolve(import.meta.dirname, '..');

function request(port: number, pathname: string, method = 'GET') {
  return new Promise<{ status: number; headers: http.IncomingHttpHeaders; body: Buffer }>((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: pathname, method }, response => {
      const chunks: Buffer[] = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode!, headers: response.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
    req.end();
  });
}

describe('local Monaco build and development transport', () => {
  it.each(['/', '/webcompiler/'])('serves only the frozen distribution under %s', async base => {
    const expected = readMonacoDistribution(path.join(root, 'node_modules/monaco-editor'));
    const server = await createServer({
      root, base, configFile: false, plugins: [localMonacoAssets()],
      server: { host: '127.0.0.1', port: 0, watch: null },
      optimizeDeps: { noDiscovery: true, include: [] }, logLevel: 'error',
    });
    try {
      await server.listen();
      const address = server.httpServer!.address();
      if (!address || typeof address === 'string') throw new Error('Expected TCP listener');
      const prefix = `${base}${expected.directory}/`;
      for (const name of ['loader.js', 'editor/editor.main.css', expected.workers.ts, 'LICENSE.txt']) {
        const response = await request(address.port, `${prefix}${name}?v=1`);
        expect(response.status).toBe(200);
        expect(response.body.equals(expected.files.get(name)!)).toBe(true);
        expect(response.headers['x-content-type-options']).toBe('nosniff');
        expect(response.headers['cache-control']).toContain('immutable');
      }
      const head = await request(address.port, `${prefix}loader.js`, 'HEAD');
      expect(head.status).toBe(200);
      expect(head.body.length).toBe(0);
      expect(Number(head.headers['content-length'])).toBe(expected.files.get('loader.js')!.length);
      for (const suffix of ['../package.json', '%2e%2e/package.json', 'assets/../loader.js', '%6coader.js', 'absent.js']) {
        expect((await request(address.port, `${prefix}${suffix}`)).status).toBe(404);
      }
      expect((await request(address.port, `${prefix}loader.js`, 'POST')).status).toBe(405);
      const module = await server.transformRequest('virtual:local-monaco');
      expect(module!.code).toContain(`${base}${expected.directory}`);
      expect(module!.code).not.toContain('cdn.jsdelivr.net');
    } finally { await server.close(); }
  });

  it('emits every installed byte without parsing editor or worker modules', async () => {
    const expected = readMonacoDistribution(path.join(root, 'node_modules/monaco-editor'));
    const transformed: string[] = [];
    const result = await build({
      root, base: '/webcompiler/', configFile: false, logLevel: 'error',
      plugins: [localMonacoAssets(), { name: 'observe-module-graph', transform(_source, id) { transformed.push(id); } }],
      build: { write: false, minify: false, rollupOptions: {
        input: 'virtual:local-monaco', preserveEntrySignatures: 'strict',
      } },
    });
    if (Array.isArray(result) || !('output' in result)) throw new Error('Expected one build');
    const assets = result.output.filter(item => item.type === 'asset');
    expect(assets.length).toBe(expected.files.size);
    for (const asset of assets) {
      const name = asset.fileName.slice(`${expected.directory}/`.length);
      expect(asset.fileName.startsWith(`${expected.directory}/`)).toBe(true);
      expect(Buffer.from(asset.source).equals(expected.files.get(name)!)).toBe(true);
    }
    expect(transformed).toEqual(['\0virtual:local-monaco']);
    const entry = result.output.find(item => item.type === 'chunk');
    expect(entry?.type === 'chunk' && entry.code).toContain(`/webcompiler/${expected.directory}`);
    expect(assets.filter(item => /\.worker-[^/]+\.js$/.test(item.fileName))).toHaveLength(5);
  });
});
