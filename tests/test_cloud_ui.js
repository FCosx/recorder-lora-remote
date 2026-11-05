const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');

function environment() {
  const nodes = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      classList: {toggle() {}},
      attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; }
    });
    return nodes.get(id);
  };
  const badge = {};
  const upload = {dataset: {uploadName: 'recording-test'}, closest: () => ({querySelector: () => badge})};
  const calls = [];
  const context = {
    $: node, el: node,
    state: 'idle', lastCloud: null, cloudActionPending: null,
    localAction: null, sending: false, lastStatus: null,
    feedbackButtons: new WeakSet(),
    document: {querySelectorAll: () => [upload]},
    metadataReady: d => !context.sending && d.radio_connected && !d.pending && !d.topics_loading && !d.metadata_loading,
    confirm: () => false,
    message: text => { throw Error(text); },
    api: async (endpoint, options) => {
      calls.push([endpoint, JSON.parse(options.body)]);
      return {...sample.cloud, mode: 'automatic'};
    },
    command: (action, body) => calls.push([action, body])
  };
  return {node, upload, calls, context};
}
const sample = {radio_connected: true, synchronized: true, cloud: {
  configured: true, mode: 'manual', reachable: 'reachable', state: 'verifying', progress: 72, queued: 1
}};

(async () => {
  for (const filename of ['index.html', 'lora/remote.html']) {
    if (!fs.existsSync(path.join(root, filename))) continue;
    const html = fs.readFileSync(path.join(root, filename), 'utf8');
    const script = html.split('<script>')[1].split('</script>')[0];
    new vm.Script(script);
    assert.doesNotMatch(html, /<h2>Cloud upload<\/h2>/);
    const recordings = html.split('<h2>Recordings on the Pi</h2>')[1];
    assert.match(recordings, /id="cloud-mode"/);
    assert.match(recordings, /id="refresh-recordings"/);
    assert.match(recordings, /id="cloud-status"/);
    assert.match(recordings, /<span id="cloud-status" class="badge" role="status">/);
    const radioHtml = fs.readFileSync(path.join(root, 'lora/remote.html'), 'utf8');
    for (const selector of ['badge', 'badge.good', 'badge.bad']) {
      const rule = new RegExp('\\.' + selector.replaceAll('.', '\\.') + '\\{[^}]+\\}');
      assert.equal(html.match(rule)[0], radioHtml.match(rule)[0], 'Cloud badges must match the radio badge');
    }
    assert.match(recordings, /aria-checked="false"/);
    const env = environment();
    const {node, calls, context} = env;
    const remote = filename.startsWith('lora');
    const end = remote ? 'function render(d)' : '    async function refreshRecordings';
    vm.createContext(context);
    vm.runInContext(script.slice(script.indexOf('function uploadLabel'), script.indexOf(end)) +
      '\nglobalThis.draw=renderCloud; globalThis.change=changeCloudMode;', context);
    const draw = cloud => context.draw(remote ? {...sample, cloud} : cloud);
    draw(sample.cloud);
    assert.equal(node('cloud-mode').disabled, false);
    assert.equal(node('cloud-mode').attributes['aria-checked'], 'false');
    assert.equal(node('cloud-mode-label').textContent, 'Manual upload');
    assert.match(node('cloud-mode-help').textContent, /Choose recordings/);
    assert.match(node('cloud-status').textContent, /Verifying 72%/);
    assert.equal(node('cloud-status').className, 'badge good');
    assert.equal(node('stop-cloud').disabled, false);
    for (const reachable of ['unreachable', 'unknown', 'not_configured']) {
      draw({...sample.cloud, reachable});
      assert.equal(node('cloud-status').className, reachable === 'unreachable' ? 'badge bad' : 'badge');
      assert.equal(node('cloud-mode').disabled, true);
      assert.equal(node('stop-cloud').disabled, false, 'Stopping work must remain available offline');
      if (!remote) assert.equal(env.upload.disabled, true);
    }
    draw(null);
    assert.equal(node('cloud-mode').disabled, true);
    assert.equal(node('stop-cloud').disabled, true);
    assert.notEqual(node('cloud-status').className, 'badge good');
    draw({...sample.cloud, state:'stopped', queued:0});
    assert.equal(node('stop-cloud').disabled, true);
    if (remote) context.lastStatus = sample;
    else context.lastCloud = sample.cloud;
    await context.change();
    assert.equal(calls.length, 0, 'Canceling confirmation must not send a mode command');
    context.confirm = () => true;
    await context.change();
    assert.equal(calls.length, 1);
    assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1])), {mode:'automatic'});
    draw({...sample.cloud, mode:'automatic'});
    assert.equal(node('cloud-mode').attributes['aria-checked'], 'true');
    assert.match(node('cloud-mode-help').textContent, /Pi is idle/);
    if (remote) {
      context.draw({...sample, radio_connected:false});
      assert.equal(node('cloud-status').className, 'badge bad');
      assert.equal(node('cloud-status').textContent, 'Cloud status outdated');
      context.draw({...sample, synchronized:false});
      assert.equal(node('cloud-status').className, 'badge bad');
      context.draw({...sample, pending:'cloud'});
      assert.equal(node('cloud-mode').disabled, true);
      assert.equal(node('cloud-mode-label').textContent, 'Applying…');
      context.draw({...sample, topics_loading:true});
      assert.equal(node('cloud-mode').disabled, true);
      context.draw({...sample, pending:'cloud-stop'});
      assert.equal(node('stop-cloud').textContent, 'Stopping…');
    } else {
      context.state='offline';draw(sample.cloud);
      assert.equal(node('cloud-status').className, 'badge bad');
      assert.match(node('cloud-status').textContent, /status unavailable/);
      context.state='idle';
      draw({...sample.cloud, state:'stopped', uploads:{'recording-test':{state:'stopped'}}});
      assert.equal(env.upload.disabled, false);
      assert.equal(env.upload.textContent, 'Resume upload');
    }
  }
  console.log('Cloud controls passed: recordings header, offline gates, confirmation, stop and resume.');
})().catch(error => {console.error(error); process.exitCode = 1;});
