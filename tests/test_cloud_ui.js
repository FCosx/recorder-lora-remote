const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'lora/remote.html'),'utf8');const script=html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{classList:{toggle:()=>{}}});return nodes.get(id)};
const ctx={$:node,document:{activeElement:null},metadataReady:d=>!d.pending&&!d.topics_loading&&!d.metadata_loading};
vm.runInNewContext(script.slice(script.indexOf('function uploadLabel'),script.indexOf('function render(d)'))+'\nglobalThis.draw=renderCloud;',ctx);
ctx.draw({cloud:null,radio_connected:false});assert.equal(node('apply-cloud').disabled,true);assert.match(node('cloud-status').textContent,/outdated/);
const sample={radio_connected:true,cloud:{configured:true,mode:'manual',reachable:'reachable',state:'verifying',progress:72}};
ctx.draw(sample);assert.equal(node('apply-cloud').disabled,false);assert.match(node('cloud-status').textContent,/Verifying 72%/);
ctx.draw({...sample,pending:'cloud'});assert.equal(node('apply-cloud').disabled,true);
ctx.draw({...sample,topics_loading:true});assert.equal(node('apply-cloud').disabled,true);
ctx.draw({...sample,metadata_loading:true});assert.equal(node('cloud-mode').disabled,true);
ctx.draw({...sample,cloud:{...sample.cloud,configured:false,reachable:'not_configured'}});assert.equal(node('apply-cloud').disabled,true);assert.match(node('cloud-status').textContent,/not configured/);
assert.match(html,/renderCloud\(d\)/);assert.match(html,/snapshot=await fetch\('\/api\/status'/);
if(fs.existsSync(path.join(root,'index.html'))){const lan=fs.readFileSync(path.join(root,'index.html'),'utf8');new vm.Script(lan.split('<script>')[1].split('</script>')[0]);assert.match(lan,/actions.append\(details, download, upload, remove\)/);assert.match(lan,/upload-badge\[hidden\]/)}
console.log('Cloud UI: freshness/busy gates, progress, mode, archive-free controls and hidden badges passed.');
