import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);
import './style.css';

const root = document.querySelector('#app');
root.innerHTML = `
<aside class="sidebar"><a class="brand" href="/"><span class="brand-icon">◈</span> 观数 <small>INSIGHT</small></a>
<div class="workspace">企业经营分析工作台</div><button id="new-analysis" class="nav active">◉ 新建分析</button>
<div class="nav-heading">最近分析</div><div id="history" class="history"></div>
<div class="sidebar-foot">观数 · 企业经营分析<br>个人项目 · 合成业务数据</div></aside>
<main><header><span>工作空间 <span class="slash">/</span> 经营分析</span><div class="health"><span id="db-status">连接中</span><span id="model-status">模型状态</span></div></header>
<section class="intro"><div class="eyebrow">BUSINESS INTELLIGENCE</div><h1>让数据，回答业务问题。</h1><p>用自然语言探索经营数据，从指标到趋势，让每一个结论都有据可查。</p></section>
<section class="query-card"><div class="card-top"><strong>开始一次分析</strong><span id="data-period">销售 · 订单 · 退款</span></div>
<label for="question" class="sr-only">分析问题</label><textarea id="question" rows="3" placeholder="例如：分析最近三个完整自然月各部门的退款率，找出异常部门并生成趋势图。"></textarea>
<div class="query-bottom"><span>已接入业务口径与表结构</span><button id="ask" class="primary">开始 AI 分析 <span>↗</span></button></div><p id="model-hint" class="model-hint"></p></section>
<div class="demo-header"><strong>探索示例</strong><span>固定 SQL 案例 · 查询真实本地数据库 · 不调用模型</span></div><section id="cases" class="cases"></section>
<div id="notice" class="notice" role="alert" hidden></div>
<section id="run" hidden><div class="section-heading"><div><span class="eyebrow">ANALYSIS</span><h2 id="run-title"></h2></div><span id="run-mode" class="tag"></span></div>
<div id="progress" class="progress" aria-live="polite"></div><div id="clarification" class="clarification" hidden><p id="clarification-text"></p><input id="answer" aria-label="补充信息" placeholder="请输入补充信息"/><button id="resume" class="primary">继续分析</button></div>
<div id="result" hidden><div class="result-toolbar"><span id="result-meta"></span><a id="download" class="download">↓ 导出报告</a></div>
<div id="kpis" class="kpis"></div><div id="insights" class="insights"></div><div id="anomalies"></div><div id="charts" class="charts"></div>
<div class="evidence"><div class="tabs" role="tablist"><button class="selected" data-tab="data">结果明细</button><button data-tab="sql">查询 SQL</button><button data-tab="definitions">指标口径</button></div>
<div id="data-panel" class="panel"></div><pre id="sql-panel" class="panel" hidden></pre><div id="definitions-panel" class="panel definitions" hidden></div></div></div></section>
<footer>统计异常用于发现待核查线索，不代表已证明的业务原因。<span>Python · LangGraph · PostgreSQL · ECharts</span></footer></main>`;

const $ = (id) => document.getElementById(id);
let selectedJob = null, source = null, charts = [], requestPending = false;
function textElement(tag, text, className) { const el = document.createElement(tag); el.textContent = text; if (className) el.className = className; return el; }
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, options) { const res = await fetch(path, options); const data = await res.json(); if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求参数无效'); return data; }
function post(path, data) { return api(path, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) }); }
function disposeCharts() { charts.forEach(chart => chart.dispose()); charts = []; }
async function refreshHistory() { const jobs = await api('/api/queries'); $('history').replaceChildren(...jobs.map(job => {const button = textElement('button', job.question); button.title = job.question; button.onclick = () => selectJob(job.id); return button;})); }
function stage(event) { if (event.type !== 'stage') return; const el = textElement('span', `✓ ${event.label}`); $('progress').append(el); }
async function selectJob(id) {
  source?.close(); selectedJob = id; notice(''); disposeCharts();
  const job = await api(`/api/queries/${id}`); if (id !== selectedJob) return;
  $('run').hidden = false; $('result').hidden = true; $('clarification').hidden = true; $('run-title').textContent = job.question;
  $('run-mode').textContent = job.mode === 'demo' ? '固定案例' : 'AI 问数'; $('progress').replaceChildren();
  if (['queued','running'].includes(job.status)) {
    const stream = new EventSource(`/api/queries/${id}/events`); source = stream;
    stream.onmessage = event => { if(id === selectedJob) stage(JSON.parse(event.data)); };
    stream.addEventListener('finished', () => { stream.close(); if(id === selectedJob) selectJob(id); refreshHistory(); });
    stream.onerror = () => { stream.close(); if(id === selectedJob) notice('进度连接中断；任务仍在后台运行，可点击左侧分析记录查看状态。'); };
  } else {
    job.events.forEach(stage);
    if (job.status === 'complete') renderResult(job);
    else if (job.status === 'needs_input') { $('clarification').hidden = false; $('clarification-text').textContent = typeof job.clarification === 'string' ? job.clarification : job.clarification.text || JSON.stringify(job.clarification); }
    else notice(job.error || '分析未完成');
  }
}
function renderResult(job) {
  const result = job.result; $('result').hidden = false;
  $('result-meta').textContent = `${result.row_count} 行结果 · 数据日期 ${result.as_of}${result.truncated ? ' · 结果已截断' : ''}`;
  $('download').href = `/api/queries/${job.id}/report`;
  $('kpis').replaceChildren(...result.kpis.map(kpi => { const card = textElement('div','', 'kpi'); card.append(textElement('span',kpi.label),textElement('strong',kpi.value)); return card; }));
  $('insights').replaceChildren(textElement('h3','分析摘要'),...result.insights.map(item => textElement('p',item)));
  $('anomalies').replaceChildren(...result.anomalies.map(item => {const el=textElement('div','', 'anomaly'); el.append(textElement('strong',`${item.dimension} · 退款率 ${item.value}% · 待核查`),textElement('p',item.evidence),textElement('small',result.anomaly_note)); return el;}));
  $('charts').replaceChildren(...result.charts.map(item => {const card=textElement('article','', 'chart-card'); const canvas=textElement('div','', 'chart'); card.append(textElement('h3',item.title),canvas); requestAnimationFrame(() => { if(job.id !== selectedJob || !canvas.isConnected) return; const chart=echarts.init(canvas,null,{renderer:'svg'}); chart.setOption(item.option); charts.push(chart); }); return card;}));
  const table=document.createElement('table'), head=document.createElement('thead'), row=document.createElement('tr');
  result.columns.forEach(column => row.append(textElement('th',column))); head.append(row); table.append(head); const body=document.createElement('tbody');
  result.rows.forEach(record => {const tr=document.createElement('tr'); result.columns.forEach(column => tr.append(textElement('td',record[column] ?? '—'))); body.append(tr);}); table.append(body); $('data-panel').replaceChildren(table);
  $('sql-panel').textContent = result.sql;
  $('definitions-panel').replaceChildren(...Object.entries(result.definitions).map(([key,value]) => {const line=document.createElement('p');line.append(textElement('strong',`${key}：`),document.createTextNode(value));return line;}));
}
async function submit(mode, caseId) {
  if (requestPending) return; requestPending = true; notice('');
  try { const job=await post('/api/queries',{question: $('question').value.trim() || '固定案例',mode,case_id:caseId}); await refreshHistory(); await selectJob(job.id); $('run').scrollIntoView({behavior:'smooth',block:'start'}); }
  catch(error){notice(error.message);} finally {requestPending=false;}
}
$('ask').onclick = () => { if (!$('question').value.trim()) return notice('请先输入你想分析的业务问题。'); submit('ai'); };
$('question').onkeydown = event => {if((event.ctrlKey || event.metaKey) && event.key==='Enter') $('ask').click();};
$('resume').onclick = async () => {try{await post(`/api/queries/${selectedJob}/resume`,{answer:$('answer').value});await selectJob(selectedJob);}catch(error){notice(error.message);}};
$('new-analysis').onclick = () => {source?.close();selectedJob=null;disposeCharts();$('run').hidden=true;$('question').value='';notice('');$('question').focus();};
document.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => {document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));['data','sql','definitions'].forEach(name=>$(name+'-panel').hidden=name!==button.dataset.tab);});
window.addEventListener('resize',()=>charts.forEach(chart=>chart.resize()));
async function init() {
  try {const [health,catalog]=await Promise.all([api('/api/health'),api('/api/catalog')]);
    $('db-status').textContent=health.database.connected?'● 数据库已连接':'● 数据库未就绪';
    $('model-status').textContent=health.model_ready?'● AI 已配置':'○ AI 待配置';
    $('model-hint').textContent=health.model_ready?`当前模型：${health.model} · 最多返回 ${health.max_rows} 行`:'AI 自由问数待配置模型；可以先运行下方固定案例查看数据与图表。';
    if(health.database.as_of) $('data-period').textContent=`合成数据 · 基准日期 ${health.database.as_of}`;
    $('cases').replaceChildren(...catalog.cases.map((item,i)=>{const button=textElement('button','', 'case');button.append(textElement('span',`0${i+1}`,'case-number'),textElement('strong',item.question),textElement('span','运行案例 ↗','case-action'));button.onclick=()=>{ $('question').value=item.question;submit('demo',item.id);};return button;}));
    await refreshHistory();
  } catch(error) {notice(`初始化失败：${error.message}`);}
}
init();
