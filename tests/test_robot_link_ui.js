const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
for(const name of ['index.html','lora/remote.html']){
 const file=path.join(__dirname,'..',name);if(!fs.existsSync(file))continue;
 const source=fs.readFileSync(file,'utf8').split('<script>')[1].split('</script>')[0];new vm.Script(source);
 const scope={};vm.runInNewContext(source.slice(source.indexOf('function robotLinkWarning'),source.indexOf('function recordedRate'))+'\nglobalThis.warning=robotLinkWarning;',scope);
 const warning=scope.warning;
 assert.equal(warning({state:'idle',robot_link:'unknown'}),'');
 assert.equal(warning({state:'recording',robot_link:'connected',robot_link_interruptions:0}),'');
 assert.equal(warning({state:'idle',robot_link:'lost'}),'Robot link unavailable');
 assert.equal(warning({state:'recording',robot_link:'lost'}),'Robot link unavailable · recording continues');
 assert.equal(warning({state:'stopping',robot_link:'lost'}),'Robot link unavailable');
 assert.equal(warning({state:'recording',robot_link:'connected',robot_link_interruptions:1}),'Robot link interrupted during recording');
 assert.equal(warning({state:'recording',robot_link:'connected',robot_link_interrupted:true}),'Robot link interrupted during recording');
 assert.equal(warning({state:'idle',robot_link:'connected',robot_link_interruptions:1}),'');
}
console.log('LAN/LoRa link warning text and unknown/recovery behavior passed.');
