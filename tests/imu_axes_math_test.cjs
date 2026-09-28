// Exercise the actual page's math without a browser or a second implementation.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../tools/imu_axes.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: id === 'axis' ? '2' : '90', disabled: true, textContent: '',
    getContext: () => ({}),
  });
  return elements.get(id);
}
const sandbox = {
  document: {getElementById: element, addEventListener() {}},
  performance: {now: () => 100},
  Math, Number, Date, JSON,
};
vm.createContext(sandbox);
// Omit startup network/render calls; compile and test all original definitions.
vm.runInContext(source.replace('poll();draw();', ''), sandbox);
const run = code => vm.runInContext(code, sandbox);
const close = (a, b) => assert.ok(Math.abs(a-b) < 1e-8, `${a} != ${b}`);
const vector = (actual, expected) => actual.forEach((v, i) => close(v, expected[i]));
run('var s=Math.SQRT1_2;');
vector(run('rotate([0,0,0,1],[1,2,3])'), [1,2,3]);
vector(run('rotate([0,0,s,s],[1,0,0])'), [0,1,0]);
vector(run('rotate([s,0,0,s],[0,1,0])'), [0,0,1]);
vector(run('rotate([0,s,0,s],[0,0,1])'), [1,0,0]);
close(run('angle([0,0,0,1],[0,0,s,s])'), 90);
close(run('angle([0,0,s,s],[0,0,-s,-s])'), 0);
vector(run('euler([0,0,s,s])'), [0,0,90]);
// Expected rotation is about the reference's local axis, not a world axis.
run('ref=[s,0,0,s]');
close(run('angle(expectedQ(),mul(ref,[0,0,s,s]))'), 0);
close(run('angle(expectedQ(),mul(ref,[0,0,0,1]))'), 90);
run('latest={quat:[0,0,0,1],age_ms:1500}; online=true; receivedAt=100');
assert.equal(run('fresh()'), false);
run('latest.age_ms=10');
assert.equal(run('fresh()'), true);
run('online=false');
assert.equal(run('fresh()'), false);
console.log('PASS: XYZ handedness, x/y/z/w, Euler angles, q/-q invariance, reference-axis error, stale-data gating');
