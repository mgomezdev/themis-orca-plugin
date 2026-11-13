const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../src/themis_orca/panel.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// Small DOM/host bridge contract harness. Browser layout is verified separately.
function page() {
  class Element {
    constructor() { this.value = ''; this.textContent = ''; this.children = []; this.handlers = {}; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    replaceChildren() { this.children = []; }
    append(...children) { this.children.push(...children); }
    fire(name) { this.handlers[name]({preventDefault() {}}); }
    set innerHTML(_) { throw Error('Untrusted content must use textContent'); }
    get selectedOptions() { return this.children.filter(child => child.selected); }
  }
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const messages = [], handlers = {};
  let receive, tick, cleared = false;
  vm.runInNewContext(script, {
    document: {getElementById: id => elements[id], createElement: () => new Element()},
    orca: {postMessage: data => messages.push(JSON.parse(JSON.stringify(data))), onMessage: fn => receive = fn},
    window: {addEventListener: (name, fn) => handlers[name] = fn},
    setInterval: (fn, delay) => { assert.equal(delay, 750); tick = fn; return 1; },
    clearInterval: id => { assert.equal(id, 1); cleared = true; },
  });
  const state = overrides => receive({type: 'state', status: 'Ready', url: 'https://themis.test/api/v1', configured: true, key_set: true, plate_index: 0, busy: false, ...overrides});
  return {elements, messages, handlers, state, tick: () => tick(), cleared: () => cleared};
}

test('page registers the listener and asks for state without connecting', () => {
  const p = page();
  assert.deepEqual(p.messages, [{command: 'ready'}]);
  p.tick();
  assert.deepEqual(p.messages.at(-1), {command: 'poll'});
  p.handlers.pagehide();
  assert.equal(p.cleared(), true);
});

test('plate state and busy controls render without overwriting an edited URL', () => {
  const p = page();
  p.state({plate_index: 2});
  assert.equal(p.elements.plate.textContent, 'Current plate: 3');
  p.elements.url.value = 'https://edited.test';
  p.state({busy: true});
  assert.equal(p.elements.url.value, 'https://edited.test');
  for (const id of ['save', 'forget', 'url', 'api-key', 'refresh']) assert.equal(p.elements[id].disabled, true);
  assert.equal(p.elements.cancel.hidden, false);
  p.state({plate_index: null});
  assert.match(p.elements.plate.textContent, /No plate/);
  assert.equal(p.elements.refresh.disabled, false);
});

test('save submits credentials only to the host and clears the field after success', () => {
  const p = page(); p.state();
  p.elements['api-key'].value = 'replacement-key';
  p.elements['settings-form'].fire('submit');
  assert.deepEqual(p.messages.at(-1), {command: 'save', url: 'https://themis.test/api/v1', api_key: 'replacement-key'});
  p.state({settings_saved: true});
  assert.equal(p.elements['api-key'].value, '');
  assert.match(p.elements['api-key'].placeholder, /Leave blank/);
  assert.match(html, /id="api-key" type="password"/);
});

test('status, collection labels and errors render as text, never HTML', () => {
  const p = page();
  const payload = '<img src=x onerror=alert(1)>';
  p.state({status: payload, notice: payload, counts: {[payload]: 2}, errors: {models: payload}});
  assert.equal(p.elements.status.textContent, payload);
  assert.equal(p.elements.notice.textContent, payload);
  assert.equal(p.elements.counts.children[0].textContent, payload);
  assert.equal(p.elements.errors.children[0].textContent, payload);
  assert.equal(p.elements.errors.hidden, false);
  p.state({counts: null, errors: {}});
  assert.equal(p.elements.counts.hidden, true);
  assert.equal(p.elements.errors.hidden, true);
});

test('connect, cancel and forget are explicit commands; forgotten key disables refresh', () => {
  const p = page(); p.state();
  p.elements.refresh.fire('click');
  p.elements.cancel.fire('click');
  p.elements.forget.fire('click');
  assert.deepEqual(p.messages.slice(-3), [{command: 'refresh'}, {command: 'cancel'}, {command: 'forget'}]);
  p.state({key_set: false, configured: false, settings_saved: true});
  assert.equal(p.elements.refresh.disabled, true);
  assert.equal(p.elements.forget.disabled, true);
});

test('all five send destinations expose the correct project and object fields', () => {
  const p = page();
  p.state({choices:{projects:[{id:7,name:'P'}],printers:[{id:5,name:'Printer'}],models:[],processes:['Standard']},
    snapshot:{plate_number:2,objects:[{id:'17',name:'Part',instances:2}]}});
  for (const action of ['job','existing_plate','existing_objects','new_plate','new_objects']) {
    p.elements.action.value = action; p.elements.action.fire('change');
    assert.equal(p.elements['project-row'].hidden, !action.startsWith('existing'));
    assert.equal(p.elements['name-row'].hidden, !action.startsWith('new'));
    assert.equal(p.elements['objects-row'].hidden, !action.endsWith('objects'));
  }
  p.elements['project-name'].value = 'New project';
  p.elements['send-form'].fire('submit');
  assert.equal(p.messages.at(-1).workflow.action, 'new_objects');
  assert.deepEqual(p.messages.at(-1).workflow.object_ids, ['17']);
  assert.deepEqual(p.messages.at(-1).workflow.targets, ['any']);
});

test('project overrides stay selected and explain their import-group scope', () => {
  const p = page(); p.state({choices:{projects:[],printers:[],models:[],processes:[]},snapshot:{plate_number:1,objects:[]}});
  p.elements.action.value = 'new_plate';
  p.elements['use-overrides'].checked = true;
  p.elements.overrides.value = '{"wall_loops":3}';
  p.elements.action.fire('change');
  assert.equal(p.elements.send.disabled, false);
  assert.equal(p.elements.overrides.value, '{"wall_loops":3}');
  assert.match(p.elements['override-note'].textContent, /import group/);
});

test('sliced G-code destinations require a captured export with proven automatic eligibility', () => {
  const p = page();
  const capture = {id:'slice-1',name:'part.gcode',profile:'Printer 0.4 nozzle',model:'Printer',printers:['P'],error:'',attempted:false};
  const state = {choices:{projects:[{id:7,name:'P'}],printers:[],models:[],processes:[]},captures:[capture]};
  p.state(state);
  for (const action of ['existing_gcode','new_gcode']) {
    p.elements.action.value = action; p.elements.action.fire('change');
    assert.equal(p.elements['geometry-source'].hidden, true);
    assert.equal(p.elements['geometry-settings'].hidden, true);
    assert.equal(p.elements['gcode-source'].hidden, false);
    assert.equal(p.elements['project-row'].hidden, !action.startsWith('existing'));
    assert.equal(p.elements['name-row'].hidden, !action.startsWith('new'));
    assert.equal(p.elements.send.disabled, true);
  }
  p.elements['capture-id'].value = 'slice-1'; p.elements['capture-id'].fire('change');
  assert.equal(p.elements.send.disabled, false);
  assert.match(p.elements['gcode-note'].textContent, /Eligible printers: P/);
  p.elements['use-overrides'].checked = true; p.elements.overrides.value = 'invalid json from previous geometry action';
  p.elements['project-name'].value = 'Sliced'; p.elements['send-form'].fire('submit');
  assert.deepEqual(p.messages.at(-1), {command:'send',workflow:{action:'new_gcode',project_id:'',project_name:'Sliced',capture_id:'slice-1',quantity:'1'}});
  p.state(state); assert.equal(p.elements['capture-id'].value, 'slice-1');
  p.state({...state,captures:[{...capture,error:'No unique mapping'}]}); assert.equal(p.elements.send.disabled,true);
  p.state({...state,captures:[{...capture,attempted:true}]}); assert.equal(p.elements.send.disabled,true);
  p.elements['clear-captures'].fire('click'); assert.deepEqual(p.messages.at(-1),{command:'clear_captures'});
});
