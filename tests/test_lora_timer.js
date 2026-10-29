// Run with Node.js. Exercises the actual browser timer without a radio or DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../lora/remote.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
new vm.Script(script); // Check the entire page script, including event handlers.
const context = {performance: {now: () => 0}};
vm.runInNewContext(script.slice(script.indexOf('class RecordingTimer'), script.indexOf('const recordingTimer='))
  + '\nglobalThis.Timer = RecordingTimer;', context);
const timer = new context.Timer();
const sample = (state, elapsed, extra = {}) => ({
  status: {state, elapsed_seconds: elapsed, name: 'recording-one'},
  age_seconds: 0, radio_connected: true, synchronized: true, fresh_seconds: 15,
  pending: null, ...extra,
});

timer.update(sample('starting', 0), 0);
assert.equal(timer.reading(4000).seconds, 0, 'Do not start before confirmed recording');
timer.update(sample('recording', 10, {age_seconds: 2}), 4000);
assert.equal(timer.reading(4500).seconds, 12.5, 'Advance between browser/radio updates');
assert.equal(timer.reading(4500).estimated, true);
timer.update(sample('recording', 10, {age_seconds: 3}), 5000);
assert.equal(timer.reading(5500).seconds, 13.5, 'Cached replies must not restart the timer');
timer.pause(5500);
assert.equal(timer.reading(7500).seconds, 13.5, 'Stop click or local controller failure freezes the estimate');
timer.update(sample('recording', 12, {pending: 'stop'}), 7500);
assert.equal(timer.reading(9500).seconds, 13.5, 'Keep frozen while Stop awaits acknowledgment');
timer.update(sample('stopping', 14), 9500);
assert.equal(timer.reading(12000).seconds, 14, 'Use confirmed elapsed time while finalizing');
assert.equal(timer.reading(12000).estimated, false);
timer.update(sample('idle', null), 12000);
assert.equal(timer.reading(15000).seconds, null, 'Idle clears the timer');

timer.update(sample('recording', 20), 16000);
assert.equal(timer.reading(40000).seconds, 35, 'Stop extrapolation at the freshness limit');
timer.update(sample('recording', 20, {radio_connected: false, age_seconds: 24}), 40000);
assert.equal(timer.reading(50000).seconds, 35, 'Stale status stays frozen');
timer.update(sample('recording', 50, {age_seconds: 1}), 51000);
assert.equal(timer.reading(52000).seconds, 52, 'Fresh Pi data reanchors the estimate');
timer.update(sample('recording', 50, {synchronized: false}), 52000);
assert.equal(timer.reading(54000).seconds, 52, 'Unsynchronized status cannot advance');
timer.update({...sample('recording', 1, {radio_connected: false}),
  status: {state: 'recording', elapsed_seconds: 1, name: 'recording-two'}}, 54000);
assert.equal(timer.reading(56000).seconds, 1, 'Never carry the previous recording timer into a different bag');
timer.update(sample('recording', null), 57000);
assert.equal(timer.reading(59000).seconds, null, 'Unknown elapsed time must stay unknown');
console.log('LoRa browser timer: all behavior checks passed.');
