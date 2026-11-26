const $ = id => document.getElementById(id);
let sessionId = null, busy = false, currentReport = null;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Please try again.`);
  return data;
}
function jsonPost(path, data) { return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); }
function node(tag, className, text) { const n = document.createElement(tag); n.className = className || ''; if(text !== undefined)n.textContent=text; return n; }
function notice(message, error=false) { $('notice').textContent=message; $('notice').classList.toggle('error',error); $('notice').hidden=false; }
function setBusy(value) {
  busy=value;
  for(const id of ['browse-button','paste-button','confirm-review','nav-new','send-button','explain-report','question-input','language']) $(id).disabled=value;
  document.querySelectorAll('.sample-card button').forEach(button => button.disabled=value);
  $('sample-grid').setAttribute('aria-busy', String(value));
  $('chat-status').textContent=value?'● THINKING':'● READY';
}
function statusClass(status) { return status.startsWith('Below')?'low':status.startsWith('Above')?'high':status.startsWith('Within')?'normal':'missing'; }
function resultCard(row) {
  const card=node('div','result-card'), top=node('div','result-card-top');
  top.append(node('span','result-name',row.marker), node('span',`result-status ${statusClass(row.status)}`,row.status.replace(' report range',' range')));
  const value=node('div','result-value',`${row.value} `); value.append(node('small','',row.unit));
  card.append(top,value,node('div','result-range',`Report interval: ${row.range}`));
  if(row.low!==null && row.high>row.low) {
    const track=node('div','range-track');
    const point=node('span',`range-point ${statusClass(row.status)}`);
    const percent=Math.max(3,Math.min(97,20+60*(row.value-row.low)/(row.high-row.low)));
    point.style.left=`${percent}%`; track.append(point); track.setAttribute('aria-hidden','true'); card.append(track);
  }
  const details=node('details','row-source'); details.append(node('summary','','View extracted row'),node('p','',row.raw_line)); card.append(details);
  return card;
}
function showReport(data) {
  if(sessionId && sessionId!==data.session_id) api(`/api/report/${sessionId}`,{method:'DELETE'}).catch(()=>{});
  sessionId=data.session_id; currentReport=data;
  $('active-report').textContent=data.sample ? `${data.sample.name} · synthetic case` : 'Your file';
  const casePrompt=document.querySelector('#suggestions button');
  casePrompt.dataset.question=data.sample?.question || "Which results are outside my report's range?";
  casePrompt.textContent=data.sample ? 'Ask about this case' : 'What stands out?';
  document.body.classList.add('has-report'); $('notice').hidden=true;
  $('results-section').hidden=false; $('chat-section').hidden=!data.reviewed;
  $('review-panel').hidden=data.reviewed; $('report-actions').hidden=!data.reviewed;
  $('review-text').value=data.text;
  $('review-status').textContent=data.reviewed?'✓ Values confirmed':'Review the extracted values';
  $('review-status').classList.toggle('confirmed',data.reviewed);
  $('extraction-label').textContent=`${data.extraction}${data.extraction_ms ? ` · ${(data.extraction_ms/1000).toFixed(1)}s to read` : ''}`;
  const outside=data.results.filter(row=>['low','high'].includes(statusClass(row.status))).length;
  $('result-summary').textContent=data.row_count ? `${data.row_count} CBC markers read · ${outside} outside their printed intervals. A flag is a starting point for discussion, not a diagnosis.` : 'No supported rows found. Check the extracted text below. Conflicting duplicate rows are omitted.';
  $('result-grid').replaceChildren(...data.results.map(resultCard));
  $('download-brief').classList.toggle('disabled',!data.reviewed); $('download-brief').setAttribute('aria-disabled',String(!data.reviewed));
  if(data.reviewed) $('download-brief').href=`/api/report/${sessionId}/brief`; else $('download-brief').removeAttribute('href');
  $('messages').replaceChildren();
  if(data.reviewed) addMessage('assistant','Your report is ready. We can go through a result together, look at the flagged values, or prepare questions for your clinician. What would you like to understand?');
  $('evidence-list').replaceChildren(node('div','evidence-empty','Ask a question to see the exact report rows and reference notes used.'));
  $('answer-mode').textContent='READY'; $('answer-latency').textContent='—';
  $('tool-activity').textContent='Tool activity will appear after a question.';
  $('results-section').scrollIntoView({behavior:'smooth',block:'start'});
}
function addMessage(role, text) {
  const message=node('div',`message ${role}-message`), body=node('div','message-body');
  if(role==='assistant') { message.append(node('div','message-icon','✳')); body.append(node('div','message-name','Swasthya assistant')); }
  const paragraph=node('p','',text); body.append(paragraph); message.append(body); $('messages').append(message);
  $('messages').scrollTop=$('messages').scrollHeight;
  return {message,body,paragraph};
}
function renderAnswer(container, text, response) {
  container.replaceChildren();
  const parts=text.split(/(\[(?:R\d+|CBC-\d+)\]|\*\*[^*]+\*\*)/g);
  for(const part of parts) {
    if(/^\[(?:R\d+|CBC-\d+)\]$/.test(part)) {
      const citation=node('button','citation',part.slice(1,-1)); citation.type='button';
      citation.addEventListener('click',()=>{showEvidence(response);const source=document.getElementById(`source-${part.slice(1,-1)}`);if(source){source.scrollIntoView({behavior:'smooth',block:'nearest'});source.classList.add('source-highlight');setTimeout(()=>source.classList.remove('source-highlight'),1800);}});
      container.append(citation);
    } else if(part.startsWith('**') && part.endsWith('**')) container.append(node('strong','',part.slice(2,-2)));
    else container.append(document.createTextNode(part));
  }
}
function showEvidence(data) {
  const list=$('evidence-list'); list.replaceChildren();
  if(!data.sources.length)list.append(node('div','evidence-empty','This safety or scope response did not use report evidence.'));
  for(const source of data.sources) {
    const card=node('div','source-card'); card.id=`source-${source.id}`;
    card.append(node('div','source-id',source.id),node('div','source-title',source.title),node('p','source-text',source.text));
    if(source.url) {const link=node('a','source-link','Read medical reference ↗');link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
    list.append(card);
  }
  $('answer-mode').textContent=data.mode.toUpperCase(); $('answer-latency').textContent=`${(data.latency_ms/1000).toFixed(1)}s`;
  const activity=$('tool-activity'); activity.replaceChildren(node('p','',`${data.retrieval} · Retrieval ${data.retrieval_ms} ms · Model ${data.model_ms} ms`));
  for(const tool of data.trace) {
    const detail=node('details','tool-detail'); detail.append(node('summary','',tool.tool.replaceAll('_',' ')),node('pre','',JSON.stringify(tool.output,null,2)));activity.append(detail);
  }
}
function addFeedback(body,data) {
  const row=node('div','response-actions');
  const evidence=node('button','','View evidence'); evidence.onclick=()=>showEvidence(data); row.append(evidence);
  const copy=node('button','','Copy'); copy.onclick=async()=>{try{await navigator.clipboard.writeText(data.content);copy.textContent='Copied';}catch{copy.textContent='Copy unavailable';}};row.append(copy);
  for(const [rating,label] of [['helpful','Helpful'],['not_helpful','Needs improvement']]) {
    const button=node('button','feedback-button',label);
    button.onclick=async()=>{try{await jsonPost('/api/feedback',{query_id:data.query_id,rating});row.querySelectorAll('.feedback-button').forEach(b=>b.disabled=true);button.textContent='Feedback saved';refreshMetrics();}catch(error){notice(error.message,true);}};
    row.append(button);
  }
  body.append(row);
}
async function refreshMetrics() {
  try {const data=await api('/api/metrics');$('metrics-grid').replaceChildren(...[['Questions',data.queries],['Average response',`${(data.mean_latency_ms/1000).toFixed(1)}s`],['Evidence fallbacks',data.fallbacks],['Helpful responses',data.helpful]].map(([label,value])=>{const card=node('div','metric-card');card.append(node('strong','',String(value)),node('small','',label));return card;}));}catch{}
}
async function sendQuestion(question) {
  if(!sessionId || !currentReport.reviewed)return notice('Confirm the extracted report values first.',true);
  if(busy || !question.trim())return;
  setBusy(true); $('notice').hidden=true;
  addMessage('user',question.trim()); const pending=addMessage('assistant','Reading the evidence and preparing your explanation…'); pending.message.classList.add('thinking');
  $('question-input').value=''; $('chat-section').scrollIntoView({behavior:'smooth',block:'start'});
  try {
    const data=await jsonPost('/api/chat',{session_id:sessionId,question:question.trim(),language:$('language').value});
    renderAnswer(pending.paragraph,data.content,data); showEvidence(data);addFeedback(pending.body,data);
    if(data.warning)pending.body.append(node('div','answer-warning',data.warning));
    if(data.booking){const booking=node('div','booking-card');booking.append(node('strong','',data.booking.id),node('span','','Demo request saved · no real appointment booked'));pending.body.append(booking);}
    refreshMetrics();
  }catch(error){pending.paragraph.textContent=error.message;notice(error.message,true);}
  finally{pending.message.classList.remove('thinking');setBusy(false);$('messages').scrollTop=$('messages').scrollHeight;$('question-input').focus({preventScroll:true});}
}
async function uploadFile(file) {
  if(!file || busy)return;
  if(file.size>8*1024*1024)return notice('Please use a file smaller than 8 MB.',true);
  setBusy(true);notice(`Reading ${file.name}. Scanned reports may take a little longer…`);
  try{const form=new FormData();form.append('file',file);showReport(await api('/api/report/upload',{method:'POST',body:form}));}
  catch(error){notice(error.message,true);}finally{setBusy(false);$('file-input').value='';}
}
async function resetReport() {
  if(busy)return;
  if(sessionId)await api(`/api/report/${sessionId}`,{method:'DELETE'}).catch(()=>{});
  sessionId=null;currentReport=null;document.body.classList.remove('has-report');
  for(const id of ['results-section','chat-section','notice'])$(id).hidden=true;
  $('messages').replaceChildren();$('review-text').value='';$('report-text').value='';window.scrollTo({top:0,behavior:'smooth'});
}
function sampleCard(sample,index) {
  const card=node('article',`sample-card accent-${sample.accent}`);
  const top=node('div','sample-card-top');
  top.append(node('span','sample-avatar',sample.name.slice(0,1)),node('span','sample-type',sample.kind));
  const detail=node('div','sample-card-detail');
  detail.append(node('small','sample-overline',`CASE ${String(index+1).padStart(2,'0')} · ${sample.name.toUpperCase()}`),node('h3','',sample.title),node('p','',sample.description));
  const button=node('button','sample-open',sample.id==='scanned-pdf'?'Run OCR demo ↗':'Open report ↗');
  button.type='button';
  if(index===0) button.id='demo-button';
  button.addEventListener('click',()=>loadSample(sample));
  card.append(top,detail,button);
  return card;
}
async function loadSample(sample) {
  if(busy)return;
  setBusy(true);
  notice(sample.id==='scanned-pdf'?'Reading the scanned PDF with pdfmark-ocr. This may take a moment…':`Opening ${sample.name}'s synthetic CBC…`);
  try { showReport(await api(`/api/report/sample/${encodeURIComponent(sample.id)}`,{method:'POST'})); }
  catch(error){ notice(error.message,true); }
  finally { setBusy(false); }
}
async function loadSampleLibrary() {
  try {
    const data=await api('/api/reports/samples');
    $('sample-grid').replaceChildren(...data.reports.map(sampleCard));
  } catch(error) {
    $('sample-grid').replaceChildren(node('div','sample-loading','The report library is unavailable. Reload the page after starting the server.'));
    notice(error.message,true);
  }
}
$('browse-button').onclick=event=>{event.stopPropagation();if(!busy)$('file-input').click();};
$('dropzone').onclick=event=>{if(event.target!==$('file-input') && !busy)$('file-input').click();};
$('dropzone').onkeydown=event=>{if(event.target===$('dropzone') && ['Enter',' '].includes(event.key)){event.preventDefault();if(!busy)$('file-input').click();}};
$('hero-upload').onclick=()=>$('sample-grid').scrollIntoView({behavior:'smooth',block:'center'});
$('file-input').onchange=event=>uploadFile(event.target.files[0]);
for(const type of ['dragenter','dragover'])$('dropzone').addEventListener(type,event=>{event.preventDefault();$('dropzone').classList.add('dragging');});
for(const type of ['dragleave','drop'])$('dropzone').addEventListener(type,event=>{event.preventDefault();$('dropzone').classList.remove('dragging');});
$('dropzone').addEventListener('drop',event=>uploadFile(event.dataTransfer.files[0]));
$('paste-button').onclick=async()=>{if(busy)return;const text=$('report-text').value.trim();if(text.length<4)return notice('Paste the report text first.',true);setBusy(true);try{showReport(await jsonPost('/api/report/text',{text}));}catch(error){notice(error.message,true);}finally{setBusy(false);}};
$('confirm-review').onclick=async()=>{if(busy)return;setBusy(true);try{showReport(await jsonPost(`/api/report/${sessionId}/review`,{text:$('review-text').value}));}catch(error){notice(error.message,true);}finally{setBusy(false);}};
$('edit-extraction').onclick=()=>{$('review-panel').hidden=!$('review-panel').hidden;};
$('review-text').oninput=()=>{if(currentReport){currentReport.reviewed=false;$('chat-section').hidden=true;$('report-actions').hidden=true;$('download-brief').removeAttribute('href');$('download-brief').classList.add('disabled');$('review-status').textContent='Changes need confirmation';}};
$('explain-report').onclick=()=>sendQuestion('Explain my CBC report. Which results are outside their printed intervals, and what should I discuss with my clinician?');
$('chat-form').onsubmit=event=>{event.preventDefault();sendQuestion($('question-input').value);};
$('suggestions').onclick=event=>{if(event.target.dataset.question)sendQuestion(event.target.dataset.question);};
$('nav-new').onclick=resetReport;
$('nav-workspace').onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
const replace=node('button','button button-outline','New report');replace.onclick=resetReport;document.querySelector('.report-toolbar>div').prepend(replace);
api('/api/health').then(data=>{$('model-status').textContent=data.model_enabled?'OpenAI connected · ready':'Local evidence mode';}).catch(()=>{$('model-status').textContent='Server unavailable';notice('The server is unavailable. Start the app and reload.',true);});
loadSampleLibrary();
refreshMetrics();
