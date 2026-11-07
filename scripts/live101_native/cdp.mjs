import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const PROFILE_PORT = 'webview/profile/EBWebView/DevToolsActivePort';
const PAGE_URL = 'http://tauri.localhost/';

function targetsAt(port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const request = http.get({ hostname: '127.0.0.1', port, path: '/json/list',
      agent: false, signal: AbortSignal.timeout(timeoutMs) }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        body += chunk;
        if (body.length > 1_000_000) request.destroy(new Error('DevTools target list too large'));
      });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
      response.on('error', reject);
    });
    request.on('error', reject);
  });
}

export class NativePage {
  constructor(child, socket, token, devtoolsPort) {
    this.child = child;
    this.socket = socket;
    this.token = token;
    this.devtoolsPort = devtoolsPort;
    this.serial = 0;
    this.pending = new Map();
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
      else pending.resolve(message.result);
    });
    socket.addEventListener('close', () => {
      for (const pending of this.pending.values()) pending.reject(new Error('native page closed'));
      this.pending.clear();
    });
  }

  async command(method, params, timeoutMs = 30000) {
    const id = ++this.serial;
    const answer = new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.socket.send(JSON.stringify({ id, method, params }));
    let result;
    const timer = new AbortController();
    try {
      result = await Promise.race([
        answer,
        delay(timeoutMs, undefined, { signal: timer.signal }).then(() => {
          throw new Error(`native ${method} timed out: ${JSON.stringify(params).slice(0, 180)}`);
        }),
      ]);
    } finally {
      timer.abort();
      this.pending.delete(id);
    }
    return result;
  }

  async evaluate(expression, timeoutMs = 30000) {
    const result = await this.command('Runtime.evaluate',
      { expression, awaitPromise: true, returnByValue: true }, timeoutMs);
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text + ': '
        + (result.exceptionDetails.exception?.description ?? expression.slice(0, 180)));
    }
    return result.result?.value;
  }

  async queueDialog(kind, selected) {
    return this.evaluate(`window.__TAURI__.core.invoke('live101_queue_dialog', {
      token:${JSON.stringify(this.token)}, kind:${JSON.stringify(kind)},
      path:${JSON.stringify(selected)}
    })`);
  }

  async _waitExit(timeoutMs) {
    if (this.child.exitCode === null) {
      await Promise.race([
        new Promise(resolve => this.child.once('exit', resolve)),
        delay(timeoutMs),
      ]);
    }
  }

  async _forceKill() {
    this.child.kill();
    await this._waitExit(2000);
    if (this.child.exitCode === null && process.platform === 'win32') {
      spawnSync('taskkill.exe', ['/PID', String(this.child.pid), '/T', '/F'],
        { windowsHide: true, timeout: 3000 });
    }
  }

  _closeSockets() {
    this.socket.close();
    // Undici's WHATWG WebSocket otherwise waits 30 seconds for the peer.
    // Only the exact loopback connection to this isolated profile is closed.
    for (const handle of process._getActiveHandles()) {
      if (handle.remoteAddress === '127.0.0.1'
          && handle.remotePort === this.devtoolsPort
          && typeof handle.destroy === 'function') handle.destroy();
    }
    this.child.stderr.destroy();
    this.child.unref();
  }

  async abort() {
    await this._forceKill();
    this.socket.close();
    this.child.stderr.destroy();
    this.child.unref();
    return { graceful: false, forced: true, exit_code: this.child.exitCode };
  }

  async close() {
    let requestError = null;
    let forced = false;
    try {
      await this.evaluate("window.pywebview.api.confirm_window_close()", 3000);
    } catch (error) {
      requestError = String(error);
    } finally {
      await this._waitExit(5000);
      if (this.child.exitCode === null) {
        forced = true;
        await this._forceKill();
      }
      this._closeSockets();
    }
    const graceful = !forced && this.child.exitCode === 0;
    return { graceful, forced, exit_code: this.child.exitCode,
      request_error: graceful ? null : requestError };
  }
}

function validateLoopbackTarget(target, port) {
  const address = new URL(target.webSocketDebuggerUrl);
  if (address.protocol !== 'ws:' || Number(address.port) !== port
      || !['127.0.0.1', 'localhost'].includes(address.hostname)) {
    throw new Error('DevTools target leaves the isolated loopback endpoint');
  }
}

async function probeDevToolsTarget(home, deadline) {
  const active = await readFile(path.join(home, PROFILE_PORT), 'utf8');
  const port = Number(active.split(/\r?\n/, 1)[0]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('isolated WebView2 profile has an invalid DevTools port');
  }
  const targets = await targetsAt(port, Math.min(2000, Math.max(1, deadline - Date.now())));
  const target = targets.find(item => item.type === 'page' && item.url === PAGE_URL);
  if (!target) return null;
  validateLoopbackTarget(target, port);
  return { target, devtoolsPort: port };
}

async function waitForDevToolsTarget(child, home, deadline, timeoutMs, stderrRef, spawnErrorRef) {
  while (Date.now() < deadline) {
    if (spawnErrorRef.value) throw new Error(`native GUI did not spawn: ${spawnErrorRef.value.message}`);
    if (child.exitCode !== null) throw new Error(`native GUI exited ${child.exitCode}: ${stderrRef.value}`);
    try {
      const found = await probeDevToolsTarget(home, deadline);
      if (found) return found;
    } catch (error) {
      if (error.message.includes('invalid DevTools port')
          || error.message.includes('leaves the isolated loopback')) throw error;
    }
    await delay(100);
  }
  throw new Error(`native Tauri page did not open in ${timeoutMs} ms: ${stderrRef.value}`);
}

async function awaitSocketOpen(socket, deadline) {
  const openTimer = new AbortController();
  try {
    await Promise.race([
      new Promise((resolve, reject) => {
        socket.addEventListener('open', resolve, { once: true });
        socket.addEventListener('error', reject, { once: true });
      }),
      delay(Math.max(1, deadline - Date.now()), undefined,
        { signal: openTimer.signal }).then(() => {
        throw new Error('native DevTools socket open timed out');
      }),
    ]);
  } finally {
    openTimer.abort();
  }
}

async function waitForPageToken(page, token, deadline) {
  while (Date.now() < deadline) {
    if (await page.evaluate('window.__hwpxLive101',
      Math.min(3000, Math.max(1, deadline - Date.now()))) === token) return page;
    await delay(100);
  }
  throw new Error('DevTools target did not match the newly launched native window');
}

export async function connectNativePage(exe, home, timeoutMs = 30000, devAssets = null) {
  const token = randomBytes(32).toString('hex');
  const child = spawn(exe, ['--live101', ...(devAssets ? ['--dev-assets', ...devAssets] : [])], {
    windowsHide: true,
    stdio: ['ignore', 'ignore', 'pipe'],
    env: {
      ...process.env,
      HWPXFILLER_HOME: home,
      HWPX_LIVE101_DRIVER: '1',
      HWPX_LIVE101_TOKEN: token,
    },
  });
  const stderrRef = { value: '' };
  const spawnErrorRef = { value: null };
  child.on('error', error => { spawnErrorRef.value = error; });
  child.stderr.on('data', bytes => { stderrRef.value += bytes; });
  const deadline = Date.now() + timeoutMs;
  let socket;
  try {
    const { target, devtoolsPort } = await waitForDevToolsTarget(
      child, home, deadline, timeoutMs, stderrRef, spawnErrorRef);
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await awaitSocketOpen(socket, deadline);
    const page = new NativePage(child, socket, token, devtoolsPort);
    return await waitForPageToken(page, token, deadline);
  } catch (error) {
    socket?.close();
    child.kill();
    child.stderr.destroy();
    child.unref();
    throw error;
  }
}
