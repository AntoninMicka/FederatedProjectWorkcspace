// SPDX-FileCopyrightText: 2026 Antonín Mička
// SPDX-License-Identifier: MPL-2.0
// Behaviour harness for the audience screen script (AUDIT-B4-T1, B-ODD-10).
// Runs the served /presentation-screen.js in a minimal DOM with a scripted fetch.
'use strict';
const vm = require('node:vm');
const fs = require('node:fs');

const source = fs.readFileSync(process.argv[2], 'utf8');
function element() {
  return {hidden: false, style: {}, dataset: {}, children: [], textContent: '', className: '',
    replaceChildren(...children) { this.children = children; }, append(...children) { this.children.push(...children); },
    querySelectorAll() { return []; }, querySelector() { return null; }, setAttribute() {},
    classList: {add() {}, remove() {}, toggle() {}}};
}
const screen = element(), link = element(), body = element();
link.hidden = true;
const warnings = [];
let mode = 'ok';
const document = {hidden: false, body, createElement: element, addEventListener() {},
  querySelector: selector => ({'#screen': screen, '#link-status': link})[selector] || null};
async function fetch() {
  if (mode === 'throw') throw new TypeError('Failed to fetch');
  const ok = mode === 'ok';
  return {ok, status: ok ? 200 : 503, headers: {get() { return null; }}, json: async () => ({visible: false})};
}
const window = {fetch, document, addEventListener() {}};
const context = {window, document, fetch, setTimeout, clearTimeout, setInterval() {}, addEventListener() {},
  innerWidth: 1600, innerHeight: 900, AbortSignal, AbortController, URL,
  console: {warn: name => warnings.push(name), log() {}, error() {}}};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context);

const settle = () => new Promise(resolve => setTimeout(resolve, 20));
const polls = () => warnings.filter(name => name === 'presentation_public_poll_failed').length;
(async () => {
  const steps = [];
  await settle();
  steps.push(['start', link.hidden, body.dataset.link ?? null, polls()]);
  for (const [name, next] of [['throw-1', 'throw'], ['throw-2', 'throw'], ['http-503', 'http'], ['recovered', 'ok']]) {
    mode = next;
    await vm.runInContext('poll()', context);
    await settle();
    steps.push([name, link.hidden, body.dataset.link ?? null, polls()]);
  }
  mode = 'http';
  await vm.runInContext('reportDisplayRatio()', context);
  await vm.runInContext('reportDisplayRatio()', context);
  steps.push(['ratio', warnings.filter(name => name === 'presentation_display_ratio_failed').length]);
  console.log(JSON.stringify({steps}));
})().catch(error => { console.error(error); process.exit(1); });
