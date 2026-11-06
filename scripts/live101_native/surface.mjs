import { setTimeout as delay } from 'node:timers/promises';
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

export class NativeSurface {
  constructor(page, budgetMs = 900000, captureDir = null) {
    this.page = page;
    this.deadline = Date.now() + budgetMs;
    this.captureDir = captureDir;
    this.shots = [];
  }

  async install() {
    await this.wait("document.readyState === 'complete' && typeof window.__hwpx === 'object'", 
      'sealed product page', { timeoutMs: 20000 });
    await this.value(`window.__cap = {
      alerts: [],
      takeAlert() { return this.alerts.length ? this.alerts.shift() : null; },
      btn(scope, text) {
        const parent = scope ? document.querySelector(scope) : document;
        return parent && [...parent.querySelectorAll('button')]
          .find(button => button.textContent.trim() === text && !button.disabled) || null;
      },
      clickBtn(scope, text) {
        const button = this.btn(scope, text);
        if (!button) return false;
        button.click();
        return true;
      },
      setValue(selector, value) {
        const element = document.querySelector(selector);
        if (!element) return false;
        let setter;
        for (let proto = Object.getPrototypeOf(element); proto; proto = Object.getPrototypeOf(proto)) {
          const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
          if (typeof descriptor?.set === 'function') { setter = descriptor.set; break; }
        }
        element.focus();
        if (setter) setter.call(element, value); else element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      },
      commitValue(selector) {
        const element = document.querySelector(selector);
        if (!element) return false;
        let left = false;
        const mark = () => { left = true; };
        element.addEventListener('focusout', mark);
        element.focus();
        if (element.tagName === 'SELECT') element.dispatchEvent(new Event('change', { bubbles: true }));
        element.blur();
        element.removeEventListener('focusout', mark);
        if (!left && element.tagName !== 'SELECT') {
          element.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
        }
        return true;
      },
    };
    window.alert = message => { window.__cap.alerts.push(String(message)); };
    true`);
  }

  async value(expression) {
    const remaining = this.deadline - Date.now();
    if (remaining <= 0) throw new Error('live101 journey budget ended before product evaluation');
    return this.page.evaluate(expression, Math.min(30000, remaining));
  }

  async snapshot(screen) {
    const result = await this.value(`window.pywebview.api.initial(${JSON.stringify(screen)})`);
    if (!result || typeof result !== 'object' || Array.isArray(result)) {
      throw new Error(`${screen} projection is not an object`);
    }
    return result;
  }

  async dispatch(screen, action, payload) {
    return this.value(`window.pywebview.api.dispatch(${JSON.stringify(screen)},
      ${JSON.stringify(action)}, ${JSON.stringify(payload)})`);
  }

  async installDispatchProbe() {
    const installed = await this.value(`(()=>{
      const api=window.pywebview?.api;
      if(typeof api?.dispatch!=='function')return false;
      if(api.dispatch===window.__cap.dispatchWrapper)return true;
      const originalApi=api;
      const original=(...args)=>originalApi.dispatch(...args);
      window.__cap.dispatchTrace??=[];
      window.__cap.dispatchGate=null;
      const wrapper=async(screen,action,payload)=>{
        const trace={screen,action,payload};window.__cap.dispatchTrace.push(trace);
        const gate=window.__cap.dispatchGate;
        if(gate?.action===action && gate.mode==='before'){
          gate.reached=true;await gate.promise;
        }
        try{
          const response=await original(screen,action,payload);
          trace.response=response;
          if(gate?.action===action && gate.mode==='after'){
            gate.reached=true;await gate.promise;
          }
          return response;
        }catch(error){trace.error=String(error?.message||error);throw error;}
      };
      window.pywebview.api=new Proxy(originalApi, {
        get(target,method){return method==='dispatch'?wrapper:Reflect.get(target,method);}
      });
      window.__cap.dispatchWrapper=wrapper;
      window.__cap.dispatchInstalled=true;return true;
    })()`);
    if (!installed) throw new Error('native dispatch probe could not attach');
  }

  async takeDispatchTrace() {
    return this.value(`window.__cap.dispatchTrace.splice(0)`);
  }

  async gateDispatch(action, mode) {
    if (!['before', 'after'].includes(mode)) throw new Error('invalid dispatch gate mode');
    const installed = await this.value(`(()=>{
      if(window.__cap.dispatchGate)return false;
      let release;const promise=new Promise(resolve=>{release=resolve});
      window.__cap.dispatchGate={action:${JSON.stringify(action)},
        mode:${JSON.stringify(mode)},reached:false,promise,release};return true;
    })()`);
    if (!installed) throw new Error(`native dispatch gate already occupied: ${action}`);
  }

  async waitDispatchGate(label) {
    await this.wait(`!!window.__cap.dispatchGate?.reached`, label);
  }

  async releaseDispatch() {
    const released = await this.value(`(()=>{
      const gate=window.__cap.dispatchGate;if(!gate)return false;
      window.__cap.dispatchGate=null;gate.release();return true;
    })()`);
    if (!released) throw new Error('native dispatch gate is absent');
  }

  async wait(expression, label, { timeoutMs = 20000, requires = [] } = {}) {
    const remaining = this.deadline - Date.now();
    if (remaining <= 0) throw new Error(`live101 journey budget ended before ${label}`);
    const until = Date.now() + Math.min(timeoutMs, remaining);
    while (Date.now() < until) {
      const result = await this.page.evaluate(`(()=>{
        const before = window.__cap?.takeAlert() ?? null;
        if (before !== null) return { ready:false, alert:before };
        const ready = Boolean(${expression});
        const after = window.__cap?.takeAlert() ?? null;
        return { ready:after === null && ready, alert:after };
      })()`, Math.min(3000, Math.max(1, until - Date.now())));
      if (result.alert !== null) {
        throw new Error(`native alert during ${label}: ${result.alert}`);
      }
      if (result.ready) return;
      await delay(150);
    }
    if (Date.now() >= this.deadline) throw new Error(`live101 journey budget ended at ${label}`);
    for (const selector of requires) {
      if (!await this.value(`document.querySelector(${JSON.stringify(selector)}) !== null`)) {
        throw new Error(`missing native surface ${selector} at ${label}`);
      }
    }
    throw new Error(`native step timed out: ${label}: ${expression}`);
  }

  async click(selector, label = selector) {
    const clicked = await this.value(`(()=>{
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      element.click(); return true;
    })()`);
    if (!clicked) throw new Error(`missing native surface ${selector} at ${label}`);
  }

  async clickText(scope, text) {
    const clicked = await this.value(`(()=>{
      const button = window.__cap.btn(${JSON.stringify(scope)}, ${JSON.stringify(text)});
      if (!button) return false;
      button.click(); return true;
    })()`);
    if (!clicked) throw new Error(`missing native button ${text} in ${scope ?? 'document'}`);
  }

  async setValue(selector, value) {
    if (!await this.value(`window.__cap.setValue(${JSON.stringify(selector)}, ${JSON.stringify(value)})`)) {
      throw new Error(`missing native input ${selector}`);
    }
    if (!await this.value(`window.__cap.commitValue(${JSON.stringify(selector)})`)) {
      throw new Error(`native input did not commit ${selector}`);
    }
  }

  async scrollTo(selector) {
    const moved = await this.value(`(()=>{
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      element.scrollIntoView({ block:'center', behavior:'instant' });
      return true;
    })()`);
    if (!moved) throw new Error(`missing native scroll target ${selector}`);
  }

  async shoot(name) {
    if (this.shots.includes(name)) throw new Error(`duplicate live101 shutter ${name}`);
    if (this.captureDir) {
      await mkdir(this.captureDir, { recursive: true });
      const { bytes } = await this.stablePng(name);
      const file = path.join(this.captureDir,
        `${String(this.shots.length + 1).padStart(2, '0')}-${name}.png`);
      await writeFile(file, bytes, { flag: 'wx' });
    }
    this.shots.push(name);
  }

  async stablePng(name) {
    const deadline = Math.min(this.deadline, Date.now() + 3000);
    let previous = null;
    while (Date.now() < deadline) {
      const response = await this.page.command('Page.captureScreenshot',
        { format: 'png', captureBeyondViewport: false, fromSurface: true },
        Math.max(1, deadline - Date.now()));
      const bytes = Buffer.from(response.data ?? '', 'base64');
      if (bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
        throw new Error(`native ${name} audit did not return PNG`);
      }
      const digest = createHash('sha256').update(bytes).digest('hex');
      if (previous?.digest === digest) {
        return { bytes, size: bytes.length, sha256: digest, unstable: false,
          width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
      }
      previous = { digest };
      await delay(200);
    }
    throw new Error(`native ${name} pixel audit did not settle`);
  }

  async auditShot(name, directory) {
    await mkdir(directory, { recursive: true });
    const { bytes, ...evidence } = await this.stablePng(name);
    await writeFile(path.join(directory, `${name}.png`), bytes, { flag: 'wx' });
    return evidence;
  }
}
