import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { startProxy } from '../../scripts/selftest_http_proxy.mjs';

const TARGET = 'http://example.com/__n03_network_control__';

function request(port, method, target, host) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, method, path: target, headers: { Host: host } }, response => {
      response.resume();
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers }));
    });
    req.on('connect', (response, socket) => {
      socket.destroy();
      resolve({ status: response.statusCode, headers: response.headers });
    });
    req.on('error', reject);
    req.end();
  });
}

test('packaged network control proxy observes only the exact external GET', async () => {
  const base = path.resolve('.cache');
  mkdirSync(base, { recursive: true });
  const root = mkdtempSync(path.join(base, 'network-control-'));
  const ready = path.join(root, 'ready.json');
  const hit = path.join(root, 'hit.json');
  let server;
  try {
    const started = await startProxy(ready, hit);
    server = started.server;
    assert.deepEqual(JSON.parse(readFileSync(ready, 'utf8')), { host: '127.0.0.1', port: started.port });
    for (const [method, target, host] of [
      ['GET', 'http://example.com/wrong', 'example.com'],
      ['GET', TARGET, 'wrong.example'],
      ['HEAD', TARGET, 'example.com'],
      ['CONNECT', 'example.com:443', 'example.com'],
    ]) {
      assert.equal((await request(started.port, method, target, host)).status, 502);
      assert.equal(existsSync(hit), false);
    }
    const accepted = await request(started.port, 'GET', TARGET, 'example.com');
    assert.equal(accepted.status, 204);
    assert.equal(accepted.headers['access-control-allow-origin'], '*');
    assert.deepEqual(JSON.parse(readFileSync(hit, 'utf8')), {
      method: 'GET', target: TARGET, host: 'example.com',
    });
  } finally {
    if (server) {
      server.closeAllConnections();
      await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
    if (!root.startsWith(`${base}${path.sep}`)) throw new Error('test cleanup escaped workspace cache');
    rmSync(root, { recursive: true, force: true });
  }
});
