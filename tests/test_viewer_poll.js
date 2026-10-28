const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../web/trace-viewer/app.js'), 'utf8');
const start = source.indexOf('  function dataFingerprint(');
const end = source.indexOf('  /* ---------- initialization ---------- */', start);
assert(start >= 0 && end > start);
let renders = 0;
let call = 0;
const old = {id:'case', lifecycleOverride:'running'};
const data = {cases:[{id:'case'}]};
const state = {data, index:0, manifest:[old], datasetMeta:old, datasetId:'case', dataUrl:'data.json', dataFingerprint:'unchanged',dataLastModified:'date'};
const mainScroll = {scrollTop:42};
const dom = {logBody:{},taskList:{scrollTop:11}};
const context = {
 state, dom, document:{hidden:false}, console, Set,
 activeCase:()=>state.data.cases[state.index],
 $:()=>mainScroll, $$:()=>[],
 setupWorkspaceSwitcher:()=>{}, renderSidebarSummary:()=>{}, renderRunChrome:()=>{},
 renderTaskList:()=>{renders++},renderAllContent:()=>{},hydrateRow:()=>{},
 manifestPath:()=>'/manifest',
 fetch:async (url)=>{
   call++;
   if(url==='/manifest') return {ok:true,json:async()=>({datasets:[{id:'case',lifecycleOverride:'stopped'}]})};
   return {status:304,ok:false};
 },
};
vm.runInNewContext(source.slice(start,end)+'\nthis.pollWorkspace=pollWorkspace;', context);
(async()=>{
 await context.pollWorkspace();
 assert.equal(state.datasetMeta.lifecycleOverride,'stopped');
 assert.equal(renders,1);assert.equal(mainScroll.scrollTop,42);assert.equal(dom.taskList.scrollTop,11);
 await context.pollWorkspace();assert.equal(renders,1);assert.equal(call,4);
 console.log('viewer poll: metadata change refreshes; 304 retains data and scroll');
})().catch(error=>{console.error(error);process.exit(1)});
