/** Deterministic loopback proxy for the packaged external-network control. */
import http from 'node:http';
import { mkdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const TARGET = 'http://example.com/__n03_network_control__';

function writeJsonAtomic(filename, value) {
  mkdirSync(path.dirname(filename), { recursive: true });
  const temporary = path.join(path.dirname(filename), `.${path.basename(filename)}.${randomUUID()}.tmp`);
  try {
    writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    renameSync(temporary, filename);
  } finally {
    try { unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}

export function startProxy(readyFile, hitFile) {
  const server = http.createServer((request, response) => {
    const valid = request.method === 'GET' && request.url === TARGET && request.headers.host === 'example.com';
    if (!valid) {
      response.writeHead(502, { 'Content-Length': '0' }).end();
      return;
    }
    try {
      writeJsonAtomic(hitFile, { method: request.method, target: request.url, host: request.headers.host });
      response.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
        'Content-Length': '0',
      }).end();
    } catch (error) {
      console.error(error);
      response.writeHead(500, { 'Content-Length': '0' }).end();
    }
  });
  // Node exposes CONNECT separately from ordinary request handlers.
  server.on('connect', (_request, socket) => {
    socket.end('HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n');
  });
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      try {
        const address = server.address();
        writeJsonAtomic(readyFile, { host: address.address, port: address.port });
        resolve({ server, port: address.port });
      } catch (error) {
        server.close();
        reject(error);
      }
    });
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 4 || args[0] !== '--ready-file' || args[2] !== '--hit-file' || !args[1] || !args[3]) {
      throw new Error('Usage: node scripts/selftest_http_proxy.mjs --ready-file PATH --hit-file PATH');
    }
    await startProxy(path.resolve(args[1]), path.resolve(args[3]));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}
