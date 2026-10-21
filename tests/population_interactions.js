// Unit interaction harness: execute the real UI bindings with a small DOM stand-in.
// Safari smoke checks cover the real layout separately.
const assert = require('assert/strict'), fs = require('fs'), vm = require('vm'), path = require('path');
const root = path.join(__dirname, '..', 'electro_gui', 'static');
const C = require(path.join(root, 'core.js'));
const units = [{id: 1, quality: 'sua', area: 'A'}, {id: 2, quality: 'mua', area: 'B'}, {id: 3, quality: 'sua', area: 'A'}];
assert.deepEqual(C.populationUnitList(units, [1, 2, 3, 999], [3, 2, 1, 3, 999], ['sua'], [], true).map(u => u.id), [3, 1]);
assert.deepEqual(C.populationUnitList(units, [3, 1, 999], null, [], [], true).map(u => u.id), [3, 1]);
assert.deepEqual(C.populationUnitList(units, [], [], [], [], true), []);
assert.deepEqual(C.populationUnitList(units, [3], [3], [], ['B'], false).map(u => u.id), [2]);
const fit = {active_unit_ids: [1, 3], times: [0, 1], groups: [{means: [[10, 20], [6, 8]]}, {means: [[4, 24], [8, 4]]}], normalization: {heat_sd: [2, 4], heat_peak: [10, 20]}};
for (const norm of ['z', 'peak']) {
  const ab = C.populationDifference(fit, 0, 1, norm), ba = C.populationDifference(fit, 1, 0, norm);
  assert.equal(ab.limit, ba.limit);
  ab.values.forEach((row, t) => row.forEach((v, u) => assert.equal(v, -ba.values[t][u])));
  assert.equal(ab.values[0][0], norm === 'z' ? 3 : .6);
  const identical = structuredClone(fit); identical.groups[1] = structuredClone(identical.groups[0]);
  assert.equal(C.populationDifference(identical, 0, 1, norm).limit, 1);
}
assert.throws(() => C.populationDifference({...fit, groups: [{means: [[1]]}, fit.groups[1]]}, 0, 1, 'z'), /identical/);
assert.throws(() => C.populationDifference(fit, 0, 0, 'z'), /distinct/);
const elements = new Map(), globalHandlers = new Map();
function el(id) {
  if (elements.has(id)) return elements.get(id);
  const classes = new Set(), handlers = {};
  const value = {id, handlers, hidden: true, isConnected: true, focus: () => { value.focused = true; }, dataset: {}, style: {}, value: '', innerHTML: '',
    classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x), toggle: () => {}},
    addEventListener: (k, f) => { (handlers[k] ||= []).push(f); }, querySelector: q => q === 'svg' ? el('svg') : null,
    querySelectorAll: () => [], getBoundingClientRect: () => ({left: 0, top: 0, width: 100, height: 100}), scrollIntoView: () => {}};
  elements.set(id, value); return value;
}
const context = {window: {EGCore: C}, document: {getElementById: el, querySelector: () => el('any'), querySelectorAll: () => [], documentElement: {dataset: {}}},
  addEventListener: (k, f) => { (globalHandlers.get(k) || globalHandlers.set(k, []).get(k)).push(f); },
  matchMedia: () => ({matches: false, addEventListener() {}}), setTimeout, clearTimeout, clearInterval, performance,
  requestAnimationFrame: () => 0, ResizeObserver: class {observe() {}}, console};
let source = fs.readFileSync(path.join(root, 'explorer.js'), 'utf8');
source = source.replace('  start();', `
  window.qa = {S, D, unitList, stepUnit, bindPopFigure, bindControls, navOrderKey, fillUnitItems, sanitize, fitRequest, closePop, setPopAnchor: a => {popAnchor = a;}};
  changed = () => {}; renderStructure = () => {}; closeSheet = () => {}; applyMode = () => {};
  bindFigure = () => {}; bindBehavior = () => {}; saveState = () => {};`);
vm.runInNewContext(source, context);
const {S, D, unitList, stepUnit, navOrderKey} = context.window.qa;
D.units = units; D.unitMap = new Map(units.map(u => [u.id, u]));
Object.assign(S, {session: 'synthetic', roster: [1, 2, 3, 999], unitStep: 'roster', unitQ: ['sua'], unitArea: [], unit: 2});
D.navOrder = {key: navOrderKey(), ids: [3, 2, 1]};
assert.equal(JSON.stringify(unitList().map(u => u.id)), '[3,1]');
stepUnit(1); assert.equal(S.unit, 3); stepUnit(1); assert.equal(S.unit, 1); stepUnit(1); assert.equal(S.unit, 3);
S.unit = 2; stepUnit(-1); assert.equal(S.unit, 1);
context.window.qa.fillUnitItems('');
assert.ok(el('unitItems').innerHTML.indexOf('data-unit="3"') < el('unitItems').innerHTML.indexOf('data-unit="1"'));
S.win = [-1, 2]; assert.equal(JSON.stringify(unitList().map(u => u.id)), '[1,3]'); // stale order falls back
S.roster = []; stepUnit(1); assert.equal(S.unit, 1); // empty list is safe
S.roster = [1, 2, 3]; S.mode = 'population';
const fig = el('figure');
D.popFit = {active_unit_ids: [1, 2, 3]};
D.popLayout = {width: 100, height: 100, heat: {box: {y: 0}, rowH: 20, order: [2, 0, 1]}, load: {box: {y: 0}, rowH: 20, order: [2, 0, 1]}};
context.window.qa.bindPopFigure(fig);
const before = JSON.stringify([S.align, S.win, S.filters, S.color, S.style, S.panel, S.policy, S.cw, S.sort]);
const click = kind => ({target: {closest: () => ({dataset: {kind}})}, clientX: 10, clientY: 30, preventDefault() {}});
fig.handlers.dblclick[0](click('heat')); assert.equal(S.unit, 1); assert.equal(S.mode, 'raster');
assert.equal(JSON.stringify([S.align, S.win, S.filters, S.color, S.style, S.panel, S.policy, S.cw, S.sort]), before);
S.mode = 'population'; S.unit = 3; fig.classList.add('stale');
fig.handlers.dblclick[0](click('load')); assert.equal(S.unit, 3); // old fit cannot navigate while updating
fig.classList.remove('stale'); fig.handlers.dblclick[0](click('load')); assert.equal(S.unit, 1); assert.equal(S.mode, 'raster');
S.mode = 'population';
fig.handlers.dblclick[0]({...click('heat'), clientY: 50}); assert.equal(S.unit, 2); assert.equal(S.mode, 'raster'); // direct navigation preserves quality filters
assert.equal(JSON.stringify(S.unitQ), '["sua"]');
S.mode = 'population'; D.popFit.active_unit_ids[1] = 999;
fig.handlers.dblclick[0]({...click('heat'), clientY: 50}); assert.equal(S.unit, 2); assert.equal(S.mode, 'population'); // unavailable unit leaves the view intact
D.popFit.active_unit_ids[1] = 2; S.mode = 'raster';
context.window.qa.setPopAnchor(el('unitBtn')); context.window.qa.closePop(); assert.equal(el('unitBtn').focused, true);
context.window.qa.bindControls(); el('popover').hidden = true;
S.roster = [1, 2, 3]; D.navOrder = {key: navOrderKey(), ids: [3, 2, 1]}; S.unit = 3;
el('nextUnit').handlers.click[0](); assert.equal(S.unit, 1);
globalHandlers.get('keydown').find(f => f.toString().includes('ArrowRight'))({key: 'ArrowRight', target: {tagName: 'DIV'}, preventDefault() {}});
assert.equal(S.unit, 3);
// Persisted state rejects invalid policies and retains explicit selections.
const restored = context.window.qa.sanitize({...S, fitSplit: 'random', fitGroups: ['x', 'x'], unitStep: 'unknown'});
assert.equal(restored.fitSplit, 'all'); assert.equal(restored.unitStep, 'all'); assert.equal(JSON.stringify(restored.fitGroups), '["x"]');
console.log('Population numerical display and interaction checks passed');
