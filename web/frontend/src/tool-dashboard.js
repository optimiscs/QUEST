import { getJSON, loadRun, runURL } from './api/client';
import { eventKey, summarize, historicalSeries, filterEvents } from './features/tool-health';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = value => value == null ? '—' : `${value.toFixed(1)}%`;
const statuses = {success:'成功',failed:'失败',pending:'待返回',unknown:'状态未知',excluded:'未执行'};
const colors = ['#2462cd','#12a58a','#b98626','#9b62c7','#d75d56','#4c8ea7','#69813c'];
const storeKey = 'quest-tool-health-selection-v1';
const selection = new Map();
try { for (const item of JSON.parse(localStorage.getItem(storeKey) || '[]')) if (item?.run && item?.id) selection.set(eventKey(item.run,item.id),item); } catch { /* storage optional */ }
const cache = new Map();
let runs = [], browse = [], browseVersion = 0, busy = false, rerun = false, timer, page = 0, reason = '', history = [], rows = [], details = [], lastLoaded = 0;
function persist() { try { localStorage.setItem(storeKey, JSON.stringify([...selection.values()])); } catch { /* storage optional */ } }
function label(run) { return runs.find(x => x.id === run)?.label || run; }
function visible() { const q = $('search').value.trim().toLowerCase(); return browse.filter(x => `${x.id} ${x.topicZh || ''} ${x.topic || ''}`.toLowerCase().includes(q)); }
function drawSelection() {
  $('selection-count').textContent = selection.size;
  const groups = new Map();
  for (const item of selection.values()) groups.set(item.run, (groups.get(item.run) || 0) + 1);
  $('selected').innerHTML = [...groups].map(([run,n]) => `<button data-remove-run="${esc(run)}" title="移除此数据集的选择">${esc(label(run))} · ${n} ×</button>`).join('');
  $('trace-list').innerHTML = visible().map(t => `<label class="trace-choice"><input type="checkbox" data-id="${esc(t.id)}" ${selection.has(eventKey($('dataset').value,t.id)) ? 'checked' : ''}><span>${esc(t.id)}<small>${esc(t.topicZh || t.topic || '')}${t.inProgress ? ' · 运行中' : ''}</small></span></label>`).join('') || '<p class="empty">没有匹配轨迹</p>';
}
async function loadBrowse() {
  const version = ++browseVersion, run = $('dataset').value;
  $('trace-list').textContent = '加载轨迹列表…';
  try { const result = await loadRun(run); if (version !== browseVersion) return; browse = result.cases; drawSelection(); }
  catch (e) { if (version === browseVersion) $('trace-list').textContent = e.message; }
}
function changed() { history = []; page = 0; reason = ''; persist(); drawSelection(); render(); refresh(); }
function allEvents() {
  const events = [];
  for (const [key, item] of selection) {
    for (const e of cache.get(key)?.data?.events || []) events.push({...e, run:item.run, trace:item.id});
  }
  return events;
}
function currentEvents() { const tool = $('tool').value; return allEvents().filter(e => !tool || e.tool === tool); }
function render() {
  const all = allEvents(), selectedTool = $('tool').value;
  const names = [...new Set(all.map(e => e.tool))].sort();
  $('tool').innerHTML = '<option value="">全部工具</option>' + names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
  if (names.includes(selectedTool)) $('tool').value = selectedTool;
  rows = currentEvents();
  const stats = summarize(rows);
  const loaded = [...selection.keys()].filter(k => cache.get(k)?.data).length;
  $('scope').textContent = `${selection.size} 条已选 · ${loaded} 条已加载 · ${[...selection.keys()].filter(k => cache.get(k)?.data?.inProgress).length} 条运行中 · ${rows.length.toLocaleString()} 次调用`;
  $('rate').textContent = pct(stats.rate);
  $('outcomes').textContent = `${stats.success.toLocaleString()} / ${stats.failed.toLocaleString()}`;
  $('partial').textContent = `失败中有 ${stats.partial} 次部分失败`;
  $('zero').textContent = stats.zero;
  $('unresolved').textContent = `${stats.pending} / ${stats.unknown} / ${stats.excluded}`;
  const counts = new Map();
  for (const e of rows.filter(e => e.status === 'failed')) for (const r of e.reasons) counts.set(r,(counts.get(r)||0)+1);
  $('reasons').innerHTML = [...counts].sort((a,b)=>b[1]-a[1]).map(([r,n]) => `<button class="reason ${reason===r?'active':''}" data-reason="${esc(r)}" style="--share:${stats.failed ? n/stats.failed*100 : 0}%"><span>${esc(r)}</span><span>${n} · ${pct(n/stats.failed*100)}</span></button>`).join('') || '<p class="empty">当前选择没有已识别的失败调用</p>';
  $('tool-table').innerHTML = names.filter(n => !$('tool').value || $('tool').value===n).map(n => { const s=summarize(rows.filter(e=>e.tool===n)); return `<tr><td>${esc(n)}</td><td>${s.success}</td><td>${s.failed}</td><td>${pct(s.rate)}</td></tr>`; }).join('');
  drawChart(); drawDetails();
}
function drawDetails() {
  details = filterEvents(rows, $('status-filter').value, reason);
  const pages = Math.max(1,Math.ceil(details.length/40)); page=Math.min(page,pages-1);
  $('detail-count').textContent = `${details.length.toLocaleString()} 次${reason ? ' · '+reason : ''}`;
  $('reset-reason').hidden = !reason;
  $('details').innerHTML = details.slice(page*40,page*40+40).map(e => `<tr><td><a href="/?dataset=${encodeURIComponent(e.run)}#${encodeURIComponent(e.trace)}" target="_blank" rel="noopener">${esc(e.trace)} ↗</a><small>${esc(label(e.run))}</small><small>步骤 ${esc(e.step)}${e.elapsedSeconds != null ? ' · '+(e.elapsedSeconds/60).toFixed(1)+' 分钟' : ' · 耗时未记录'}</small></td><td>${esc(e.tool)}</td><td><span class="badge ${esc(e.status)}">${e.partial ? '部分失败' : e.zeroResults ? '成功 · 零结果' : statuses[e.status]}</span><small>${esc(e.reasons.join(' / '))}</small></td><td>${esc((e.queries || []).join('\n'))}${e.error ? `<details><summary>${esc(e.error.slice(0,180))}</summary>${esc(e.error)}</details>` : ''}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">没有符合条件的调用</td></tr>';
  $('page').textContent=`${page+1} / ${pages}`; $('prev').disabled=page===0; $('next').disabled=page===pages-1;
}
function drawChart() {
  const live = $('chart-mode').value === 'live';
  let series;
  const names = [...new Set(rows.map(e=>e.tool))].sort().slice(0,6);
  if (live) {
    series = [{name:'全部所选',points:history.map(p=>({x:p.at,y:p.rate,n:p.n}))},...names.map(n=>({name:n,points:history.map(p=>({x:p.at,y:p.tools[n]?.rate ?? null,n:p.tools[n]?.n || 0}))}))];
    $('chart-note').textContent='每次刷新采样累计成功率；变更选择或工具筛选后重新计时，曲线不跨筛选条件拼接。';
  } else {
    series = [{name:'全部所选',points:historicalSeries(rows)},...names.map(n=>({name:n,points:historicalSeries(rows.filter(e=>e.tool===n))}))];
    const missing=rows.filter(e=>['success','failed'].includes(e.status)&&e.elapsedSeconds==null).length;
    $('chart-note').textContent=`按每条轨迹的运行时间对齐，以 1 分钟为桶展示累计成功率；${missing} 次已完成调用缺少时间，未入图。`;
  }
  $('legend').innerHTML=series.map((s,i)=>`<span><i style="background:${colors[i]}"></i>${esc(s.name)}</span>`).join('');
  const points=series.flatMap(s=>s.points).filter(p=>p.y!=null);
  if (!points.length) { $('chart').innerHTML='<p class="empty">'+(live?'等待一次完整刷新采样':'选择有工具耗时记录的轨迹后展示历史曲线')+'</p>';return; }
  const width=980,height=280,left=50,right=20,top=15,bottom=40;
  const xmin=live?Math.min(...points.map(p=>p.x)):0, xmax=Math.max(xmin+(live?10000:60),...points.map(p=>p.x));
  const x=v=>left+(v-xmin)/(xmax-xmin)*(width-left-right),y=v=>top+(100-v)/100*(height-top-bottom);
  const time=v=>live?new Date(v).toLocaleTimeString([], {hour12:false}):`${(v/60).toFixed(0)}m`;
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="所选轨迹工具成功率折线图"><title>工具成功率，纵轴 0 至 100%</title>`;
  for (const v of [0,25,50,75,100]) svg+=`<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" stroke="#e7edf4"/><text x="${left-9}" y="${y(v)+4}" text-anchor="end" fill="#7a899d" font-size="11">${v}%</text>`;
  for(let i=0;i<=4;i++){const v=xmin+(xmax-xmin)*i/4;svg+=`<text x="${x(v)}" y="${height-12}" text-anchor="middle" fill="#7a899d" font-size="11">${time(v)}</text>`;}
  series.forEach((s,i)=>{let path='',connected=false;for(const p of s.points){if(p.y==null){connected=false;continue;}path+=`${connected?'L':'M'}${x(p.x).toFixed(2)},${y(p.y).toFixed(2)} `;connected=true;}svg+=`<path d="${path}" fill="none" stroke="${colors[i]}" stroke-width="${i?1.7:3}"/>`;for(const p of s.points.filter(p=>p.y!=null))svg+=`<circle cx="${x(p.x)}" cy="${y(p.y)}" r="3" fill="${colors[i]}"><title>${esc(s.name)} · ${time(p.x)} · ${pct(p.y)} · ${p.n} 次已完成调用</title></circle>`;});
  $('chart').innerHTML=svg+'</svg>';
}
function schedule() { clearTimeout(timer); if ($('live').checked) timer=setTimeout(refresh,Number($('interval').value)); }
async function refresh() {
  if (busy) { rerun=true;return; }
  busy=true;clearTimeout(timer);$('refresh').disabled=true;
  const selected=[...selection.entries()], errors=[];
  $('sync').textContent=`正在同步 ${selected.length} 条轨迹…`;
  let cursor=0,done=0;
  await Promise.all(Array.from({length:Math.min(4,selected.length)},async()=>{
    while(cursor<selected.length){const [key,item]=selected[cursor++];
      try{const previous=cache.get(key);const response=await getJSON(`${runURL(item.run)}/traces/${encodeURIComponent(item.id)}/tool-events`,AbortSignal.timeout(20000),previous?.etag);
        if(response.data)cache.set(key,response);
      }catch(e){errors.push(`${item.id}：${e.message}`);}
      done++;$('sync').textContent=`正在同步 ${done}/${selected.length} 条轨迹…`;
    }
  }));
  render();
  if(!rerun && !errors.length && selection.size){
    const stats=summarize(rows), tools={};
    for(const name of new Set(rows.map(e=>e.tool))){const s=summarize(rows.filter(e=>e.tool===name));tools[name]={rate:s.rate,n:s.success+s.failed};}
    history.push({at:Date.now(),rate:stats.rate,n:stats.success+stats.failed,tools});history=history.slice(-360);drawChart();
  }
  $('error').hidden=!errors.length;$('error').textContent=errors.length?`${errors.length} 条同步失败，保留其上次数据，本次不追加实时采样。${errors.slice(0,3).join('；')}`:'';
  lastLoaded=Date.now();$('sync').textContent=`${new Date(lastLoaded).toLocaleTimeString()} · ${errors.length?'部分同步失败':'同步完成'} · ${$('live').checked?'自动刷新中':'刷新已暂停'}`;
  busy=false;$('refresh').disabled=false;
  if(rerun){rerun=false;refresh();}else schedule();
}
$('dataset').addEventListener('change',loadBrowse);$('search').addEventListener('input',drawSelection);
$('trace-list').addEventListener('change',e=>{const id=e.target.dataset.id;if(!id)return;const run=$('dataset').value,key=eventKey(run,id);if(e.target.checked)selection.set(key,{run,id});else selection.delete(key);changed();});
$('selected').addEventListener('click',e=>{const run=e.target.closest('[data-remove-run]')?.dataset.removeRun;if(!run)return;for(const [key,item] of selection)if(item.run===run)selection.delete(key);changed();});
$('select-all').onclick=()=>{for(const t of visible()){const run=$('dataset').value;selection.set(eventKey(run,t.id),{run,id:t.id});}changed();};
$('clear').onclick=()=>{selection.clear();changed();};$('refresh').onclick=refresh;
$('live').onchange=()=>{$('sync').textContent=$('live').checked?'自动刷新已开启':'自动刷新已暂停';if($('live').checked)refresh();else clearTimeout(timer);};$('interval').onchange=schedule;
$('tool').onchange=()=>{history=[];page=0;reason='';render();refresh();};$('chart-mode').onchange=drawChart;
$('reasons').onclick=e=>{const button=e.target.closest('[data-reason]');if(!button)return;reason=reason===button.dataset.reason?'':button.dataset.reason;$('status-filter').value='failed';page=0;render();};
$('status-filter').onchange=()=>{page=0;reason='';render();};$('reset-reason').onclick=()=>{reason='';page=0;render();};
$('prev').onclick=()=>{page--;drawDetails();};$('next').onclick=()=>{page++;drawDetails();};
$('download').onclick=()=>{const csvCell=x=>'"'+String(x??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';const data=[['数据集','轨迹','步骤','工具','状态','零结果','原因','查询','错误'],...details.map(e=>[e.run,e.trace,e.step,e.tool,statuses[e.status],e.zeroResults,e.reasons.join(' / '),(e.queries||[]).join('\n'),e.error])].map(row=>row.map(csvCell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob(['\ufeff'+data],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='tool-health.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
async function init(){try{runs=(await getJSON('/api/v1/runs')).data.datasets;$('dataset').innerHTML=runs.map(r=>`<option value="${esc(r.id)}">${esc(r.label||r.id)}</option>`).join('');const params=new URLSearchParams(location.search);const preferred=params.get('dataset')||'fair120-20261106-step39';if(runs.some(r=>r.id===preferred))$('dataset').value=preferred;await loadBrowse();if(params.get('trace')){const run=$('dataset').value,id=params.get('trace');selection.set(eventKey(run,id),{run,id});persist();}drawSelection();render();await refresh();}catch(e){$('error').hidden=false;$('error').textContent=e.message;}}
init();
