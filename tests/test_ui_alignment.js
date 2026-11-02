// Exercise actual UI helpers, not a separate reimplementation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.join(__dirname,'..');
const radio=fs.readFileSync(path.join(root,'lora/remote.html'),'utf8').split('<script>')[1].split('</script>')[0];
new vm.Script(radio);
const ctx={performance:{now:()=>0},count:n=>n==null?'—':String(n)};
vm.runInNewContext(radio.slice(radio.indexOf('function recordedRate'),radio.indexOf('class RecordingTimer'))+'\nglobalThis.rate=recordedRate;globalThis.view=statusPresentation;globalThis.Feedback=CommandFeedback;',ctx);
let lanRate=ctx.rate;
if(fs.existsSync(path.join(root,'index.html'))){
 const lan=fs.readFileSync(path.join(root,'index.html'),'utf8').split('<script>')[1].split('</script>')[0];new vm.Script(lan);
 const local={};vm.runInNewContext(lan.slice(lan.indexOf('function recordedRate'),lan.indexOf('function updateStatusAge'))+'\nglobalThis.rate=recordedRate;',local);lanRate=local.rate;
 const notices={};vm.runInNewContext(lan.slice(lan.indexOf('function recordingWarning'),lan.indexOf('async function refreshRecordings'))+'\nglobalThis.warning=recordingWarning;',notices);
 assert.equal(notices.warning({state:'warning',data_loss:{cache_dropped:17109},message:'Detailed per-topic diagnostics '.repeat(100)}),'Warning: Data loss detected');
 assert.equal(notices.warning({state:'error',data_loss:{unflushed_messages:2},exit_code:1}),'Error: Data loss detected · Recorder exited with code 1');
}
for(const [messages,seconds] of [[1,25],[1,250],[1,2500],[1,2e7],[1000,20],[0,10],[1,0],[null,10]])assert.equal(ctx.rate(messages,seconds),lanRate(messages,seconds));
assert.equal(ctx.rate(1,25),'0.04');assert.notEqual(ctx.rate(1,2e7),'0');
const status={radio_connected:true,synchronized:true,age_seconds:0,status:{state:'idle',can_start:true},pending:null};
assert.equal(ctx.view({...status,status:{state:'idle',can_start:false}}).kind,'blocked');
assert.equal(ctx.view({...status,radio_connected:false}).kind,'offline');
assert.equal(ctx.view({...status,pending:'start'}).title,'Preparing to record');
assert.equal(ctx.view({...status,status:{state:'recording'},pending:'stop'}).kind,'stopping');
assert.equal(ctx.view({...status,status:{state:'recording'}}).title,'Recording in progress');
const f=new ctx.Feedback();f.observe(status,0);f.fail('Invalid split size');
for(const now of [1000,10000,100000]){f.observe(status,now);assert.equal(f.reading(status,now).text,'Invalid split size','Polling must not overwrite validation errors')}
f.dismiss();assert.equal(f.reading(status,100000).text,'Ready for a command');
const unknown={...status,last_command:{id:'11',action:'stop',result:'unknown',message:'Outcome uncertain'}};
f.observe(unknown,100000);assert.equal(f.reading(unknown,500000).kind,'error','Uncertainty cannot expire silently');
f.begin('Sending another request');f.clear();assert.equal(f.reading(unknown,500001).text,'Ready for a command');
const accepted={...status,last_command:{id:'12',action:'stop',result:'accepted',message:'Stop accepted'}};
f.observe(accepted,500001);assert.equal(f.reading(accepted,500002).kind,'success');assert.equal(f.reading(accepted,507000).text,'Ready for a command');
f.observe({...status,topics_loading:true},600000);f.observe({...status,topics_loading:false},601000);assert.equal(f.recentJob('topics',601500),true);assert.equal(f.recentJob('topics',603000),false);
console.log('UI alignment: status, rate precision and persistent-feedback checks passed.');
// LAN and radio previews use the same units and concise one-shot feedback.
const bw={};vm.runInNewContext(radio.slice(radio.indexOf('function bandwidthRate'),radio.indexOf('function renderBandwidth'))+'\nglobalThis.rate=bandwidthRate;',bw);
for(const [value,text] of [[null,'—'],[1024,'1.0 KiB/s'],[2*1024**2,'2.0 MiB/s'],[12,'12 B/s']])assert.equal(bw.rate(value),text);
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:''});return nodes.get(id)};
const preview={chosen:new Set(['/a','/b']),$:node,document:{querySelectorAll:()=>[]},Date};
vm.runInNewContext(radio.slice(radio.indexOf('function bandwidthRate'),radio.indexOf('function metadataReady'))+'\nglobalThis.render=renderBandwidth;',preview);
preview.render({bandwidth_rates:{'/a':1024},bandwidth_loading:true});
assert.match(node('selection-count').textContent,/1.0 KiB\/s \+ 1 unmeasured/);
assert.match(node('bandwidth-note').textContent,/Estimating on robot/);
preview.chosen.clear();preview.render({bandwidth_rates:{},bandwidth_measured_at:123});assert.match(node('selection-count').textContent,/Select topics above/);assert.doesNotMatch(node('selection-count').textContent,/0 selected|—/);assert.match(node('bandwidth-note').textContent,/Refresh topics to check again/);
assert.doesNotMatch(radio,/auto-estimate|heartbeat:true|bandwidthTouchedAt/);
console.log('Bandwidth alignment: units, partial totals and one-shot feedback passed.');
