const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'cookie-consent.js'), 'utf8');
const key = 'mid-grator-cookie-consent';
const record = (analytics, version = 2, decidedAt = new Date().toISOString()) =>
  JSON.stringify({ version, analytics, decidedAt });

function page(initial, measurementId = '') {
  const nodes = {};
  const scripts = [];
  const storage = new Map(initial === undefined ? [] : [[key, initial]]);
  const listeners = {};
  for (const name of ['banner', 'preferences', 'analytics', 'error', 'manage', 'save', 'open', 'accept', 'reject']) {
    nodes[name] = {
      hidden: false,
      checked: false,
      addEventListener(event, callback) { this[event] = callback; }
    };
  }
  const location = {
    hostname: 'example.com', origin: 'https://example.com', pathname: '/',
    reloads: 0, reload() { this.reloads++; },
    replace(url) { this.replaced = url; }
  };
  const document = {
    currentScript: { dataset: {
      googleAnalyticsId: measurementId, googleTagManagerId: 'GTM-TM6GLFG2', language: 'en'
    } },
    querySelector(selector) { return nodes[selector.slice(13, -1)]; },
    createElement() { return { addEventListener() {} }; },
    head: { appendChild(tag) { scripts.push(tag); } },
    cookie: '_ga=abc; _gid=def'
  };
  const localStorage = {
    getItem(name) { return storage.get(name) || null; },
    setItem(name, value) { storage.set(name, value); },
    removeItem(name) { storage.delete(name); }
  };
  const window = { addEventListener(event, callback) { listeners[event] = callback; } };
  const errors = [];
  const console = { error(...args) { errors.push(args); }, warn() {} };
  vm.runInNewContext(source, { window, document, localStorage, location, console, Date });
  return { nodes, scripts, storage, listeners, location, window, localStorage, errors };
}

test('no Google script loads without current consent, including old and expired decisions', () => {
  for (const [value, hidden] of [
    [undefined, false], [record(false), true], [record(true, 1), false],
    [record(true, 2, '2020-01-01T00:00:00Z'), false]
  ]) {
    const state = page(value);
    assert.equal(state.scripts.length, 0);
    assert.equal(state.nodes.banner.hidden, hidden);
  }
});

test('accepting analytics loads GTM once after consent defaults and persists the choice', () => {
  const state = page();
  state.nodes.accept.click();
  assert.equal(state.scripts.length, 1);
  assert.equal(state.scripts[0].src, 'https://www.googletagmanager.com/gtm.js?id=GTM-TM6GLFG2');
  assert.equal(JSON.parse(state.storage.get(key)).analytics, true);
  assert.equal(state.window.dataLayer[0][0], 'consent');
  assert.equal(state.window.dataLayer[0][1], 'default');
  assert.equal(state.window.dataLayer[0][2].analytics_storage, 'denied');
  assert.equal(state.window.dataLayer[1][2].analytics_storage, 'granted');
  assert.equal(state.window.dataLayer[1][2].ad_storage, 'denied');
  assert.equal(state.window.dataLayer[3].event, 'gtm.js');
  state.nodes.open.click();
  state.nodes.save.click();
  assert.equal(state.scripts.length, 1);
});

test('a saved acceptance loads GTM, and rejection disables it and reloads without consent', () => {
  const state = page(record(true), 'G-TEST123');
  assert.equal(state.scripts.length, 2);
  state.nodes.reject.click();
  assert.equal(JSON.parse(state.storage.get(key)).analytics, false);
  assert.equal(state.window['ga-disable-G-TEST123'], true);
  const last = state.window.dataLayer.at(-1);
  assert.equal(last[1], 'update');
  assert.equal(last[2].analytics_storage, 'denied');
  assert.equal(state.location.reloads, 1);
  assert.equal(page(state.storage.get(key)).scripts.length, 0);
});

test('rejecting before acceptance never loads GTM; an unchecked custom choice also rejects', () => {
  for (const action of ['reject', 'save']) {
    const state = page();
    if (action === 'save') state.nodes.manage.click();
    state.nodes[action].click();
    assert.equal(state.scripts.length, 0);
    assert.equal(JSON.parse(state.storage.get(key)).analytics, false);
    assert.equal(state.location.reloads, 0);
  }
});

test('consent changes in another tab stop the container and reload the page', () => {
  const state = page(record(true));
  state.storage.set(key, record(false));
  state.listeners.storage({ key });
  assert.equal(state.location.reloads, 1);
  assert.equal(state.window.dataLayer.at(-1)[2].analytics_storage, 'denied');
});

test('a failed save cannot activate analytics', () => {
  const state = page();
  state.localStorage.setItem = () => { throw new Error('storage unavailable'); };
  state.nodes.accept.click();
  assert.equal(state.scripts.length, 0);
  assert.equal(state.nodes.error.hidden, false);
  assert.equal(state.errors.length, 1);
});

test('a failed withdrawal removes old consent and reloads, or leaves the page if removal also fails', () => {
  for (const failRemoval of [false, true]) {
    const state = page(record(true));
    state.localStorage.setItem = () => { throw new Error('storage unavailable'); };
    if (failRemoval) state.localStorage.removeItem = () => { throw new Error('storage unavailable'); };
    state.nodes.reject.click();
    assert.equal(state.window.dataLayer.at(-1)[2].analytics_storage, 'denied');
    if (failRemoval) {
      assert.equal(state.location.replaced, 'about:blank');
      assert.equal(state.errors.length, 2);
    } else {
      assert.equal(state.storage.has(key), false);
      assert.equal(state.location.reloads, 1);
      assert.equal(state.errors.length, 1);
    }
  }
});
