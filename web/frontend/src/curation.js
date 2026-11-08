import { escapeHTML as esc, escapeAttr } from './shared/format';
import './styles.css';
import './curation.css';

const root=document.querySelector('#curationApp');
const state={cases:[],rubric:[],active:null,answers:{},dirty:false,submitting:false};
const labels={yes:'是',no:'否',unknown:'无法判断',agree:'一致',disagree:'不同',uncomparable:'未作比较'};
const verdict={pass_review:'人工建议通过',review:'暂缓复核',reject:'人工建议不通过'};
const $=s=>root.querySelector(s);
async function api(path,options={}){
  const r=await fetch('/api/curation'+path,{cache:'no-store',...options});
  const data=await r.json();if(!r.ok)throw new Error(data.detail||data.error?.message||'请求失败');return data;
}
root.innerHTML=`<header class="audit-top"><a class="audit-brand" href="/trace-viewer-zh/"><b>G</b> GLASSEEK <span>/ 人工抽检</span></a><nav><a href="/trace-viewer-zh/">轨迹查看器 ↗</a><a href="/api/curation/export">导出审核记录</a></nav></header>
<div class="audit-status"><span class="audit-dot"></span><b>先独立判断，再核对程序</b><span id="globalStats">正在连接审核批次…</span></div>
<div id="auditError" class="audit-error" role="alert" hidden></div>
<div class="audit-layout"><aside class="audit-queue"><div class="queue-head"><h2>抽检队列 <span id="caseCount"></span></h2><input id="caseSearch" type="search" aria-label="搜索轨迹" placeholder="搜索题目、来源或轨迹 ID…"><select id="sourceFilter" aria-label="按数据集筛选"><option value="">全部数据集</option></select></div><p id="searchStatus" role="status"></p><div id="caseList"></div><p class="queue-note">定向风险样本 + 对照样本。<br>抽检一致率不代表全量质量。</p></aside>
<main class="audit-trace"><section id="caseHeader" class="audit-question"><small>TRAJECTORY REVIEW</small><h1>选择一道题开始审核</h1></section><div class="trace-toolbar"><label>添加证据到 <select id="evidenceTarget" aria-label="证据对应的检查项"></select></label><button id="collapseAll">收起消息</button></div><div class="trace-search" role="search" aria-label="单条轨迹搜索"><input id="traceSearch" type="search" maxlength="256" placeholder="搜索当前轨迹完整消息…" aria-label="搜索当前轨迹"><div class="trace-search-nav"><span id="traceSearchStatus" role="status" aria-live="polite">全文搜索 · 忽略大小写</span><button id="traceSearchPrev" type="button" aria-label="上一处命中" disabled>↑</button><button id="traceSearchNext" type="button" aria-label="下一处命中" disabled>↓</button><button id="traceSearchClear" type="button">清除</button></div></div><div id="messages"></div></main>
<aside class="audit-form-pane"><div class="form-heading"><span class="section-index">01 / 独立审核</span><h2>逐项确认，不凭总体印象</h2><p>以轨迹内证据为准。无法确认时选“无法判断”。邮箱和手机号不纳入安全判断。</p></div><label class="reviewer-label">审核人标识（自填）<input id="reviewer" maxlength="64" placeholder="你的姓名或固定标识" autocomplete="off"></label><form id="auditForm"><div id="checks"></div><label class="audit-note">补充说明<textarea id="reviewNote" maxlength="4000" placeholder="记录分歧、缺失证据或需要复核的地方；不要粘贴密钥原值。"></textarea></label><label class="complete-check"><input id="confirmed" type="checkbox">我已查看作出判断所需的完整上下文</label><div class="submit-row"><span id="answeredCount">0 / 12 项</span><button id="submitReview" type="submit" disabled>提交并核对程序 →</button></div></form><section id="comparison" aria-live="polite" hidden></section></aside></div><dialog id="sourceDialog" aria-labelledby="sourceTitle"><header><h2 id="sourceTitle">原始轨迹信息</h2><button id="closeSource" type="button">关闭 ×</button></header><p class="source-notice">这里展示来源记录，可能包含参考答案。密钥已脱敏；下载仅包含当前轨迹，不会下载整个数据集文件。</p><div id="sourceTabs"></div><div class="source-view-switch" role="group" aria-label="原始记录展示方式"><button id="sourceViewMessages" type="button" aria-pressed="true">消息阅读</button><button id="sourceViewJson" type="button" aria-pressed="false">原始 JSON</button></div><div id="sourceFileMeta"></div><a id="downloadSource">下载当前记录 JSON ↓</a><div id="sourceSearchBar" class="source-search" role="search" aria-label="原始记录全文搜索"><input id="sourceSearch" type="search" maxlength="256" placeholder="搜索当前原始记录全文…" aria-label="搜索原始记录全文"><div class="source-search-nav"><span id="sourceSearchStatus" role="status" aria-live="polite">全文搜索 · 包含尚未加载的内容</span><button id="sourceSearchPrev" type="button" aria-label="原始记录上一处命中" disabled>↑</button><button id="sourceSearchNext" type="button" aria-label="原始记录下一处命中" disabled>↓</button><button id="sourceSearchClear" type="button">清除</button></div></div><div id="sourceMessages"></div><pre id="sourceContent" hidden></pre><button id="sourceMore" type="button" hidden>继续加载</button></dialog>`;

function error(message){$('#auditError').textContent=message;$('#auditError').hidden=!message;}
function renderQueue(){
  const source=$('#sourceFilter').value;
  const words=$('#caseSearch').value.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  const filtered=state.cases.filter(c=>(!source||c.source===source)&&words.every(w=>[c.question,c.source,c.id,c.original_id].join(' ').normalize('NFKC').toLocaleLowerCase().includes(w)));
  $('#searchStatus').textContent=`显示 ${filtered.length} / ${state.cases.length} 条`;
  $('#caseList').innerHTML=filtered.map(c=>`<button class="case-button ${state.active?.id===c.id?'active':''}" data-case="${escapeAttr(c.id)}"><span>${esc(c.source)} <i>${c.reviewed?'已审核':'待审核'}</i></span><strong>${esc(c.question||'未命名任务')}</strong><small>${c.messages} 条消息 · ${c.reviewed} 次审核<br><span class="case-id">${esc(c.id)}</span></small></button>`).join('')||'<p class="empty-search">未找到匹配轨迹，请调整关键词或数据集。</p>';
  $('#caseCount').textContent=state.cases.length;
  $('#caseList').querySelectorAll('[data-case]').forEach(b=>b.addEventListener('click',()=>loadCase(b.dataset.case)));
}
function renderChecks(){
  let group='';$('#checks').innerHTML=state.rubric.map((r,i)=>{
    const heading=r.group!==group?`<h3 class="check-group">${esc(r.group)}</h3>`:'';group=r.group;
    return `${heading}<fieldset class="audit-check" id="check-${r.id}"><legend><span>${String(i+1).padStart(2,'0')}</span>${esc(r.text)}</legend><p>${esc(r.help)}</p><div class="answer-options">${['yes','no','unknown'].map(v=>`<label><input type="radio" name="${r.id}" value="${v}"><span>${labels[v]}</span></label>`).join('')}</div><label class="evidence-input">证据消息<input data-evidence="${r.id}" placeholder="例如 M3, M8" aria-label="${escapeAttr(r.text)} 证据消息"></label></fieldset>`;
  }).join('');
  $('#checks').querySelectorAll('input[type=radio]').forEach(input=>input.addEventListener('change',()=>{
    state.answers[input.name]=input.value;state.dirty=true;$('#evidenceTarget').value=input.name;syncDependencies();updateReady();
  }));
  $('#checks').querySelectorAll('[data-evidence]').forEach(input=>input.addEventListener('input',()=>{state.dirty=true;}));
}
function syncDependencies(){
  for(const r of state.rubric.filter(r=>r.parent)){
    const no=state.answers[r.parent]==='no';const field=$(`#check-${r.id}`);
    if(no){state.answers[r.id]='no';field.dataset.auto='1';field.querySelector('input[value=no]').checked=true;}
    else if(field.dataset.auto==='1'){delete state.answers[r.id];field.querySelectorAll('input[type=radio]').forEach(x=>x.checked=false);delete field.dataset.auto;}
    field.querySelectorAll('input[type=radio]').forEach(x=>x.disabled=no);field.classList.toggle('auto-answer',no);
  }
}
function updateReady(){
  const n=Object.keys(state.answers).length;$('#answeredCount').textContent=`${n} / ${state.rubric.length} 项`;
  $('#submitReview').disabled=state.submitting||!state.active||n!==state.rubric.length||!$('#reviewer').value.trim()||!$('#confirmed').checked;
}
const traceFind={token:0,timer:null,hits:[],current:-1,total:0,messageCount:0,limited:false};
function paintMessage(details){
  const loader=details._loader;if(!loader)return;
  const index=Number(details.dataset.message),text=loader.text;
  const fragment=document.createDocumentFragment();let end=0;
  traceFind.hits.forEach((hit,i)=>{
    if(hit.message_index!==index||hit.end>text.length)return;
    fragment.append(document.createTextNode(text.slice(end,hit.start)));
    const mark=document.createElement('mark');mark.textContent=text.slice(hit.start,hit.end);mark.dataset.hit=String(i);
    if(i===traceFind.current)mark.classList.add('current-hit');
    fragment.append(mark);end=hit.end;
  });
  fragment.append(document.createTextNode(text.slice(end)));details.querySelector('pre').replaceChildren(fragment);
}
function resetTraceSearch(){
  traceFind.token++;clearTimeout(traceFind.timer);traceFind.hits=[];traceFind.current=-1;traceFind.total=0;
  $('#traceSearch').value='';$('#traceSearchStatus').textContent='全文搜索 · 忽略大小写';
  $('#traceSearchPrev').disabled=$('#traceSearchNext').disabled=true;
  $('#messages').querySelectorAll('details').forEach(paintMessage);
}
async function hydrate(details,until=0){
  if(!details._loader){
    const loader=details._loader={text:'',offset:0,pending:null};
    const c=state.active.id,index=Number(details.dataset.message),more=details.querySelector('.more-message');
    loader.load=async()=>{
      if(loader.pending)return loader.pending;
      if(loader.offset===null)return;
      more.disabled=true;more.textContent='正在加载…';
      loader.pending=(async()=>{
        const data=await api(`/cases/${c}/messages/${index}?offset=${loader.offset}`);
        loader.text+=data.content;loader.offset=data.next_offset;paintMessage(details);
        more.hidden=loader.offset===null;more.textContent=`继续加载（已显示 ${Math.min(loader.offset??data.total,data.total).toLocaleString()} / ${data.total.toLocaleString()} 字）`;
      })();
      try{await loader.pending;}catch(e){more.textContent='重试加载';throw e;}
      finally{loader.pending=null;more.disabled=false;}
    };
    more.addEventListener('click',()=>loader.load().catch(e=>error(e.message)));
  }
  const loader=details._loader;
  if(loader.pending)await loader.pending;
  if(loader.offset===0)await loader.load();
  while(loader.offset!==null&&loader.text.length<until)await loader.load();
}
async function jumpTraceHit(delta=0){
  if(!traceFind.hits.length)return;
  const token=traceFind.token;
  traceFind.current=(traceFind.current+delta+traceFind.hits.length)%traceFind.hits.length;
  const current=traceFind.current,hit=traceFind.hits[current];
  $('#traceSearchStatus').textContent=`${current+1} / ${traceFind.total} 处 · ${traceFind.messageCount} 条消息${traceFind.limited?'（前 2000 处可跳转）':''}`;
  const details=$(`#messages [data-message="${hit.message_index}"]`);details.open=true;
  try{
    await hydrate(details,hit.end);
    if(token!==traceFind.token||current!==traceFind.current)return;
    $('#messages').querySelectorAll('details').forEach(paintMessage);
    const mark=details.querySelector(`mark[data-hit="${current}"]`);
    if(mark){
      const pane=$('.audit-trace');
      const target=pane.getBoundingClientRect().top+$('.trace-search').offsetHeight+35;
      pane.scrollBy({top:mark.getBoundingClientRect().top-target,behavior:'instant'});
    }
  }catch(e){if(token===traceFind.token)error(e.message);}
}
async function searchTrace(query,token){
  try{
    const result=await api(`/cases/${state.active.id}/search`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});
    if(token!==traceFind.token)return;
    Object.assign(traceFind,{hits:result.hits,total:result.total,messageCount:result.message_count,limited:result.limited,current:0});
    $('#traceSearchPrev').disabled=$('#traceSearchNext').disabled=!result.hits.length;
    $('#traceSearchStatus').textContent=result.total?'':'未找到匹配内容（已搜索完整消息）';
    $('#messages').querySelectorAll('details').forEach(paintMessage);
    if(result.hits.length)await jumpTraceHit();
  }catch(e){if(token===traceFind.token)$('#traceSearchStatus').textContent='搜索失败：'+e.message;}
}
$('#traceSearch').addEventListener('input',()=>{
  const query=$('#traceSearch').value;resetTraceSearch();$('#traceSearch').value=query;
  if(!query||!state.active)return;
  $('#traceSearchStatus').textContent='正在搜索完整轨迹…';const token=traceFind.token;
  traceFind.timer=setTimeout(()=>searchTrace(query,token),250);
});
$('#traceSearch').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();jumpTraceHit(e.shiftKey?-1:1);}
  if(e.key==='Escape'){resetTraceSearch();}
});
$('#traceSearchPrev').addEventListener('click',()=>jumpTraceHit(-1));
$('#traceSearchNext').addEventListener('click',()=>jumpTraceHit(1));
$('#traceSearchClear').addEventListener('click',()=>{resetTraceSearch();$('#traceSearch').focus();});
async function loadCase(id){
  if(state.submitting)return;
  if(state.dirty&&!confirm('当前题有未提交的判断，确定切换吗？'))return;
  error('');
  try{
    const c=await api('/cases/'+id);resetTraceSearch();state.active=c;state.answers={};state.dirty=false;
    $('#auditForm').reset();$('#comparison').hidden=true;renderChecks();renderQueue();
    $('#caseHeader').innerHTML=`<small>${esc(c.source)} · ${c.agent_role==='child'?'子代理':'主代理'} · ${c.messages.length} 条消息</small><h1>${esc(c.question)}</h1><details class="source-details"><summary>来源与工具协议</summary><p>${esc(c.source_location.source_artifact||'')} · 记录索引（从 0 起）${c.source_location.source_line_zero_based??'未知'}</p><p>审核 ID ${esc(c.id)}<br>原始轨迹 ID ${esc(c.source_location.original_id||'未知')}</p><p>内容哈希 ${esc(c.content_hash.slice(0,16))} · 冻结协议 ${esc(c.contract_sha256.slice(0,16))}</p><pre>${esc(JSON.stringify(c.tools,null,2))}</pre></details><button id="viewSource" type="button" class="view-source">查看原始轨迹信息 / 文件 ↗</button>`;
    $('#viewSource').addEventListener('click',openSource);
    $('#messages').innerHTML=c.messages.map(m=>`<details class="audit-message ${m.origin==='tool_response'?'external':m.role}" data-message="${m.index}"><summary><span class="message-number">M${m.index+1}</span><b>${m.origin==='tool_response'?'工具返回':({assistant:'助手',user:'用户',system:'系统',developer:'开发者'}[m.role]||m.role)}</b><span class="message-preview">${esc(m.content.slice(0,120))}</span><small>${m.characters.toLocaleString()} 字</small></summary><div class="message-detail"><div class="message-meta"><span>存储角色 ${esc(m.role)} · 源位置 ${esc(String(m.source_message_index))}${m.response_to?' · response_to '+esc(m.response_to):''}</span><button type="button" data-pin="${m.index}">引用 M${m.index+1}</button></div><pre>${esc(m.content)}</pre><button class="more-message" type="button">加载完整消息</button></div></details>`).join('');
    $('#messages').querySelectorAll('details').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)hydrate(d).catch(e=>error(e.message));}));
    $('#messages').querySelectorAll('[data-pin]').forEach(b=>b.addEventListener('click',()=>{
      const input=$(`[data-evidence="${$('#evidenceTarget').value}"]`);const value=`M${Number(b.dataset.pin)+1}`;
      const values=input.value.split(/[,，\s]+/).filter(Boolean);if(!values.includes(value))values.push(value);input.value=values.join(', ');state.dirty=true;
      b.textContent='已添加 ✓';setTimeout(()=>b.textContent='引用 '+value,1200);
    }));
    history.replaceState(null,'','#'+id);updateReady();$('.audit-trace').scrollTop=0;
  }catch(e){error(e.message);}
}
function showComparison(event){
  const r=event.result,c=event.comparison;const score=r.score===null?`${r.score_min}–${r.score_max}`:r.score;
  const title=c.disagree?`${c.disagree} 项判断不同`:c.agree?'可比项目一致':'尚无可比较项目';
  $('#comparison').innerHTML=`<div class="comparison-head"><span class="section-index">02 / 提交后核对</span><h2>${esc(title)}</h2><div class="score-display"><b>${score}<small> / 100</small></b><span class="verdict ${r.state}">${verdict[r.state]}</span></div><p>${c.agree} 项一致 · ${c.disagree} 项不同 · ${c.uncomparable} 项无法比较${c.agreement_rate===null?'':` · 可比项一致率 ${Math.round(c.agreement_rate*100)}%`}</p>${r.uncertain_weight?'<p>存在无法判断项，分数显示可能范围；不能据上界判定通过。</p>':''}<p>关键项不通过不能被其他得分抵消。此提交不是训练放行，也尚未成为仲裁后的黄金标签。</p></div>
    <table class="comparison-table"><thead><tr><th>检查项</th><th>人工</th><th>程序</th><th>结果</th></tr></thead><tbody>${c.rows.map(row=>`<tr class="${row.status}"><td title="${escapeAttr(row.program_basis)}">${esc(state.rubric.find(x=>x.id===row.id).text)}</td><td>${labels[row.human]}</td><td>${labels[row.program]}</td><td>${labels[row.status]}</td></tr>`).join('')}</tbody></table>
    <details class="program-findings"><summary>程序命中依据（${event.automatic.findings.length} 项）</summary>${event.automatic.findings.map(f=>`<p><b>${esc(f.rule_id)}</b> · ${f.message_index>=0?'M'+(f.message_index+1):'结构/元数据'} · ${esc(f.origin||'')}<br><small>${esc(f.pointer||'')}</small></p>`).join('')||'<p>规则未命中不等于已证明不存在风险。</p>'}</details><p class="comparison-note">${esc(c.note)}</p><button id="nextCase" class="next-case">保存完成，审核下一题 →</button>`;
  $('#comparison').hidden=false;$('#comparison').scrollIntoView({behavior:'smooth',block:'start'});
  $('#nextCase').addEventListener('click',()=>{const i=state.cases.findIndex(x=>x.id===state.active.id);const next=[...state.cases.slice(i+1),...state.cases.slice(0,i)].find(x=>!x.reviewed);if(next)loadCase(next.id);else error('本批次已全部有审核记录，可在左侧选择题目进行复核。');});
}
$('#auditForm').addEventListener('submit',async event=>{
  event.preventDefault();if(state.submitting)return;error('');state.submitting=true;updateReady();
  try{
    const evidence={};for(const r of state.rubric){const text=$(`[data-evidence="${r.id}"]`).value.trim();const parts=text?text.split(/[,，\s]+/):[];if(parts.some(p=>!/^M?\d+$/i.test(p)))throw new Error('证据编号请填写 M3, M8 这样的格式');evidence[r.id]=[...new Set(parts.map(p=>Number(p.replace(/^M/i,''))-1))];}
    const c=state.active;const result=await api('/reviews',{method:'POST',headers:{'Content-Type':'application/json','X-Curation-Review':'1'},body:JSON.stringify({case_id:c.id,reviewer:$('#reviewer').value,submission_id:crypto.randomUUID().replaceAll('-',''),content_hash:c.content_hash,policy_hash:c.policy_hash,rubric_hash:c.rubric_hash,answers:state.answers,evidence,note:$('#reviewNote').value,confirmed_complete:$('#confirmed').checked})});
    state.dirty=false;state.cases.find(x=>x.id===c.id).reviewed++;renderQueue();showComparison(result);await refreshStats();
  }catch(e){error(e.message);}finally{state.submitting=false;updateReady();}
});
$('#reviewer').value=localStorage.getItem('glasseek-reviewer')||'';
$('#reviewer').addEventListener('input',()=>{localStorage.setItem('glasseek-reviewer',$('#reviewer').value);updateReady();});
$('#confirmed').addEventListener('change',updateReady);$('#reviewNote').addEventListener('input',()=>state.dirty=true);
$('#sourceFilter').addEventListener('change',renderQueue);$('#caseSearch').addEventListener('input',renderQueue);$('#collapseAll').addEventListener('click',()=>$('#messages').querySelectorAll('details').forEach(d=>d.open=false));
let sourceRequest=0,sourceLoader=null,sourceView='messages';
const sourceFind={token:0,timer:null,hits:[],current:-1,total:0,limited:false};
function sourceFragment(text,blockIndex=null){
  const fragment=document.createDocumentFragment();let end=0;
  sourceFind.hits.forEach((hit,i)=>{
    if(hit.end>text.length||(blockIndex!==null&&hit.block_index!==blockIndex))return;
    fragment.append(document.createTextNode(text.slice(end,hit.start)));
    const mark=document.createElement('mark');mark.textContent=text.slice(hit.start,hit.end);mark.dataset.sourceHit=String(i);
    if(i===sourceFind.current)mark.classList.add('current-hit');
    fragment.append(mark);end=hit.end;
  });
  fragment.append(document.createTextNode(text.slice(end)));return fragment;
}
function paintSource(){
  if(!sourceLoader)return;
  if(sourceLoader.view==='messages'){
    $('#sourceMessages').querySelectorAll('[data-source-block]').forEach(el=>{
      const index=Number(el.dataset.sourceBlock),block=sourceLoader.blocks?.[index];
      if(block?.loaded)el.querySelector('pre').replaceChildren(sourceFragment(block.text,index));
    });
  }else $('#sourceContent').replaceChildren(sourceFragment(sourceLoader.text));
}
function renderSourceBlocks(loader){
  const roles={assistant:'助手',user:'用户',system:'系统',developer:'开发者',tool:'工具返回',function:'工具返回',human:'用户',gpt:'助手',metadata:'元数据',unknown:'未知角色'};
  $('#sourceMessages').innerHTML=loader.blocks.map(b=>{
    const tool=b.role==='user'&&b.content.trimStart().startsWith('<tool_response>');
    const label=tool?'用户 · 工具返回':(roles[b.role]||b.role);
    return `<details class="source-message" data-source-block="${b.index}" ${b.index<2?'open':''}><summary><b>${esc(label)}</b><span>${esc(b.title)}</span><small>${b.characters.toLocaleString()} 字</small></summary><p class="source-message-path">${esc(b.path)} · 原始角色 ${esc(b.role)}</p><pre>${esc(b.content)}</pre><button class="source-block-more" type="button">加载完整消息</button></details>`;
  }).join('');
  $('#sourceMessages').querySelectorAll('[data-source-block]').forEach(el=>{
    const index=Number(el.dataset.sourceBlock);
    el.addEventListener('toggle',()=>{if(el.open)ensureSourceBlock(loader,index).catch(e=>{$('#sourceSearchStatus').textContent='加载失败：'+e.message;});});
    el.querySelector('button').onclick=()=>ensureSourceBlock(loader,index,Infinity,true).catch(e=>{$('#sourceSearchStatus').textContent='加载失败：'+e.message;});
  });
}
async function ensureSourceBlock(loader,index,until=0,oneChunk=false){
  const block=loader.blocks[index],el=$(`#sourceMessages [data-source-block="${index}"]`);
  if(!block.load){
    Object.assign(block,{text:'',offset:0,pending:null,loaded:false});
    block.load=async()=>{
      if(block.pending)return block.pending;
      if(block.offset===null||loader!==sourceLoader)return;
      const more=el.querySelector('button');more.disabled=true;
      block.pending=(async()=>{
        const data=await api(`/cases/${loader.caseId}/files/${loader.kind}/readable/${index}?offset=${block.offset}`);
        if(loader!==sourceLoader)return;
        block.text+=data.content;block.offset=data.next_offset;block.loaded=true;paintSource();
        more.hidden=block.offset===null;more.textContent=`继续加载（${block.offset??data.total} / ${data.total} 字）`;
      })();
      try{await block.pending;}finally{block.pending=null;more.disabled=false;}
    };
  }
  if(block.pending)await block.pending;
  if(oneChunk){await block.load();return;}
  if(block.offset===0)await block.load();
  while(loader===sourceLoader&&block.offset!==null&&block.text.length<until)await block.load();
}
function resetSourceSearch(keepQuery=false){
  sourceFind.token++;clearTimeout(sourceFind.timer);sourceFind.hits=[];sourceFind.current=-1;sourceFind.total=0;
  if(!keepQuery)$('#sourceSearch').value='';
  $('#sourceSearchStatus').textContent='全文搜索 · 包含尚未加载的内容';
  $('#sourceSearchPrev').disabled=$('#sourceSearchNext').disabled=true;paintSource();
}
async function openSource(){
  const c=state.active;
  $('#sourceDialog').showModal();
  $('#sourceTabs').innerHTML=(c.files||[]).map(f=>`<button type="button" data-source-kind="${escapeAttr(f.kind)}">${f.kind==='dataset'?'数据集原始记录':'筛选后完整记录'}</button>`).join('');
  $('#sourceTabs').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>loadSource(c,b.dataset.sourceKind)));
  if(c.files?.length)await loadSource(c,c.files.some(f=>f.kind==='dataset')?'dataset':c.files[0].kind);
  else {sourceLoader=null;resetSourceSearch();$('#sourceSearch').disabled=true;$('#sourceContent').textContent='此记录尚未准备来源文件。';$('#sourceFileMeta').textContent='';$('#downloadSource').hidden=true;$('#sourceMore').hidden=true;}
}
async function loadSource(c,kind){
  const token=++sourceRequest;
  resetSourceSearch(true);
  const loader=sourceLoader={caseId:c.id,kind,view:sourceView,text:'',offset:0,pending:null};
  $('#sourceMessages').hidden=sourceView!=='messages';$('#sourceContent').hidden=sourceView!=='json';$('#sourceMessages').textContent='正在加载消息…';
  $('#sourceViewMessages').setAttribute('aria-pressed',String(sourceView==='messages'));$('#sourceViewJson').setAttribute('aria-pressed',String(sourceView==='json'));
  $('#sourceSearch').disabled=false;$('#sourceContent').textContent='正在加载…';$('#downloadSource').hidden=true;$('#sourceMore').hidden=true;
  $('#sourceTabs').querySelectorAll('button').forEach(b=>b.classList.toggle('selected',b.dataset.sourceKind===kind));
  loader.load=async()=>{
    if(loader.pending)return loader.pending;
    if(loader.offset===null||token!==sourceRequest)return;
    $('#sourceMore').disabled=true;
    loader.pending=(async()=>{
      const d=await api(`/cases/${c.id}/files/${kind}?offset=${loader.offset}`);
      if(token!==sourceRequest)return;
      if(loader.view==='json'){loader.text+=d.content;loader.offset=d.next_offset;paintSource();}
      else{
        const projected=await api(`/cases/${c.id}/files/${kind}/readable`);
        if(token!==sourceRequest)return;
        loader.blocks=projected.blocks;loader.offset=null;renderSourceBlocks(loader);
      }
      const m=d.metadata;
      $('#sourceFileMeta').textContent=`来源文件：${m.path}\n记录位置：${m.line_number}（从 1 起；索引 ${m.row_index}）\n原记录内容哈希：${m.original_sha256}\n展示文件 SHA256：${m.displayed_sha256}\n适配器来源哈希核对：${m.provenance_hash_matches===true?'一致':m.provenance_hash_matches===false?'不一致：仅按来源坐标定位，需复核适配器是否记录了中间结构哈希':'不适用'}\n敏感信息脱敏：${m.redacted?'是':'未检测到需脱敏内容'}`;
      $('#downloadSource').href=`/api/curation/cases/${c.id}/files/${kind}?download=true`;$('#downloadSource').hidden=false;
      $('#sourceMore').hidden=loader.offset===null;
      $('#sourceMore').textContent=`继续加载（${loader.offset??d.total} / ${d.total} 字）`;
    })();
    try{await loader.pending;}
    catch(e){if(token===sourceRequest){$('#sourceMore').hidden=false;$('#sourceMore').textContent='重试加载';}throw e;}
    finally{loader.pending=null;if(token===sourceRequest)$('#sourceMore').disabled=false;}
  };
  $('#sourceMore').onclick=()=>loader.load().catch(e=>{$('#sourceSearchStatus').textContent='加载失败：'+e.message;});
  const query=$('#sourceSearch').value,searchToken=sourceFind.token;
  try{await loader.load();if(query&&token===sourceRequest&&searchToken===sourceFind.token)await searchSource(query,searchToken);}
  catch(e){if(token===sourceRequest)$('#sourceSearchStatus').textContent='加载失败：'+e.message;}
}
async function jumpSourceHit(delta=0){
  if(!sourceFind.hits.length||!sourceLoader)return;
  const token=sourceFind.token,loader=sourceLoader;
  sourceFind.current=(sourceFind.current+delta+sourceFind.hits.length)%sourceFind.hits.length;
  const current=sourceFind.current,hit=sourceFind.hits[current];
  $('#sourceSearchStatus').textContent=`${current+1} / ${sourceFind.total} 处${sourceFind.limited?'（前 2000 处可跳转）':''}`;
  try{
    if(loader.pending)await loader.pending;
    if(loader.view==='messages'){
      const el=$(`#sourceMessages [data-source-block="${hit.block_index}"]`);el.open=true;await ensureSourceBlock(loader,hit.block_index,hit.end);
    }else while(loader===sourceLoader&&token===sourceFind.token&&loader.offset!==null&&loader.text.length<hit.end)await loader.load();
    if(loader!==sourceLoader||token!==sourceFind.token||current!==sourceFind.current)return;
    paintSource();
    const mark=$(`#sourceDialog mark[data-source-hit="${current}"]`);
    if(mark){const dialog=$('#sourceDialog'),target=dialog.getBoundingClientRect().top+$('#sourceSearchBar').offsetHeight+25;dialog.scrollBy({top:mark.getBoundingClientRect().top-target,behavior:'instant'});}
  }catch(e){if(token===sourceFind.token)$('#sourceSearchStatus').textContent='定位失败：'+e.message;}
}
async function searchSource(query,token){
  const loader=sourceLoader;if(!loader)return;
  $('#sourceSearchStatus').textContent='正在搜索完整记录…';
  try{
    const data=await api(`/cases/${loader.caseId}/files/${loader.kind}/search`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,view:loader.view})});
    if(token!==sourceFind.token||loader!==sourceLoader)return;
    Object.assign(sourceFind,{hits:data.hits,total:data.total,limited:data.limited,current:0});
    $('#sourceSearchPrev').disabled=$('#sourceSearchNext').disabled=!data.hits.length;
    $('#sourceSearchStatus').textContent=data.total?'':'未找到匹配内容（已搜索完整记录）';paintSource();
    if(data.hits.length)await jumpSourceHit();
  }catch(e){if(token===sourceFind.token)$('#sourceSearchStatus').textContent='搜索失败：'+e.message;}
}
$('#sourceSearch').addEventListener('input',()=>{
  resetSourceSearch(true);const query=$('#sourceSearch').value,token=sourceFind.token;
  if(query&&sourceLoader){$('#sourceSearchStatus').textContent='正在搜索完整记录…';sourceFind.timer=setTimeout(()=>searchSource(query,token),250);}
});
$('#sourceSearch').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();jumpSourceHit(e.shiftKey?-1:1);}
  if(e.key==='Escape'){e.preventDefault();e.stopPropagation();resetSourceSearch();}
});
$('#sourceSearchPrev').addEventListener('click',()=>jumpSourceHit(-1));
$('#sourceSearchNext').addEventListener('click',()=>jumpSourceHit(1));
$('#sourceSearchClear').addEventListener('click',()=>{resetSourceSearch();$('#sourceSearch').focus();});
function switchSourceView(view){
  if(sourceView===view)return;
  sourceView=view;
  if(sourceLoader)loadSource({id:sourceLoader.caseId},sourceLoader.kind);
}
$('#sourceViewMessages').addEventListener('click',()=>switchSourceView('messages'));
$('#sourceViewJson').addEventListener('click',()=>switchSourceView('json'));
function closeSource(){sourceRequest++;resetSourceSearch();sourceLoader=null;}
$('#closeSource').addEventListener('click',()=>{$('#sourceDialog').close();closeSource();});
$('#sourceDialog').addEventListener('cancel',closeSource);
async function refreshStats(){const s=await api('/summary');$('#globalStats').textContent=`${s.reviewed_cases} / ${s.cases} 题已审核 · ${s.submissions} 次提交 · ${s.disagree} 项待复核分歧`;}
async function init(){try{const data=await api('/cases');state.cases=data.cases;state.rubric=data.rubric;$('#sourceFilter').innerHTML+=[...new Set(state.cases.map(c=>c.source))].map(s=>`<option>${esc(s)}</option>`).join('');$('#evidenceTarget').innerHTML=state.rubric.map((r,i)=>`<option value="${r.id}">${String(i+1).padStart(2,'0')} · ${esc(r.group)}</option>`).join('');renderChecks();renderQueue();await refreshStats();const hash=location.hash.slice(1);const first=state.cases.find(x=>x.id===hash)||state.cases.find(x=>!x.reviewed)||state.cases[0];if(first)await loadCase(first.id);}catch(e){error(e.message);}}
init();
