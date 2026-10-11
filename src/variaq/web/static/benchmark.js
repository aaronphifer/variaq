/* Presentation only. Scientific evaluation, pairing and statistics come from Python. */
"use strict";
(function () {
const {apiGet, apiPost, esc, fmtNum, shortId, boolText, setStatus} = window.VARIAQ;
const $ = id => document.getElementById(id);
const palette = ['#89ccff', '#85e0b4', '#ffd18a', '#d0adff', '#ff9baf', '#98dbec'];
const charts = new Map();
const label = r => `${r.solver} · ${r.backend.name} · ${r.precision || 'precision unreported'} · ${r.warmup_mode} · seed ${r.seed} · ${shortId(r.run_id)}`;
const json = value => `<pre class="json-block">${esc(JSON.stringify(value, null, 2))}</pre>`;
function table(headers, rows) {
  return `<div class="table-wrap"><table class="data-table"><thead><tr>${headers.map(x=>`<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map(row=>`<tr>${row.map((x,i)=>`<td class="wrap-anywhere" data-label="${esc(headers[i])}">${x}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${headers.length}">No observations in this selection.</td></tr>`}</tbody></table></div>`;
}
const metric = (v, unit='') => v == null ? 'Unavailable' : `${new Intl.NumberFormat('en', {maximumSignificantDigits:4}).format(v)}${unit}`;
const solverName = (solver, backend) => ({'exact/python-enumeration':'Exact · CPU','heuristic/seeded-multistart-local-search':'Heuristic · CPU','qaoa/qiskit.quantum_info.Statevector':'QAOA · Qiskit','cudaq-cpu/qpp-cpu':'CUDA-Q · CPU','cudaq-gpu/nvidia':'CUDA-Q · GPU'}[`${solver}/${backend}`] || `${solver} · ${backend}`);
const modeName = mode => ({explicit_warmup:'warmup',unwarmed:'unwarmed',not_applicable:'classical',unknown:'warmup unknown'}[mode] || mode);
const zeroMarkers = {id:'measuredZero',afterDatasetsDraw(chart) {
  chart.data.datasets.forEach((dataset,index)=>{
    const meta=chart.getDatasetMeta(index);
    if(!meta.visible) return;
    dataset.data.forEach((value,i)=>{
      if(value !== 0) return;
      const bar=meta.data[i]; if(!bar) return;
      const ctx=chart.ctx; ctx.save();ctx.fillStyle=dataset.borderColor;
      ctx.beginPath();ctx.arc(bar.x,bar.y,4,0,Math.PI*2);ctx.fill();
      if(chart.canvas.id==='compare-chart-gap') {ctx.font='12px system-ui';ctx.fillStyle='#e9f0fc';ctx.fillText('0%',bar.x+9,bar.y+4);}
      ctx.restore();
    });
  });
}};
function draw(id, labels, datasets, note, scatter=false, context=[]) {
  charts.get(id)?.destroy(); charts.delete(id);
  const canvas = $('compare-chart-'+id);
  const available=datasets.length && datasets.some(d=>d.data.some(v=>scatter ? v.y != null : v != null));
  canvas.parentElement.hidden=!available;
  if(!scatter) canvas.parentElement.style.height=Math.max(180,labels.length*(id==='timing'?62:48)+50)+'px';
  $('compare-chart-'+id+'-note').textContent = note + (available ? '' : ' No measured values in this selection.');
  const legendId='compare-chart-'+id+'-legend';
  let legend=$(legendId);
  if(!legend){legend=document.createElement('ul');legend.id=legendId;legend.className='chart-legend';legend.setAttribute('aria-label',id+' chart series');canvas.parentElement.insertAdjacentElement('afterend',legend);}
  legend.hidden=!available || (!scatter && datasets.length===1);
  legend.innerHTML=datasets.map((d,i)=>`<li><span aria-hidden="true" style="color:${palette[i%palette.length]}">${scatter?['●','▲','■','+','✳','◆'][i%6]:'■'}</span> ${esc(d.label)}</li>`).join('');
  const rows = datasets.flatMap(d => d.data.map((v,i) => [esc(d.label), esc(scatter ? `${v.instance} · ${JSON.stringify(v.parameters)}` : context[i] || labels[i].join(' · ')), metric(scatter ? v.y : v, id==='gap'?'%':''), scatter ? v.count ?? '—' : d.counts?.[i] ?? '—']));
  $('compare-chart-'+id+'-data').innerHTML = `<caption>${esc(note)}</caption><thead><tr><th scope="col">Metric</th><th scope="col">Solver / source</th><th scope="col">Value</th><th scope="col">n</th></tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody>`;
  if (typeof Chart === 'undefined' || !available) return;
  const valuesAxis={beginAtZero:true,ticks:{color:'#a8b8cf'},grid:{color:'#23364b'}};
  // A visible marker represents a measured zero; nulls remain absent.
  if(id==='gap') valuesAxis.suggestedMax=1;
  const chart = new Chart(canvas, {type: scatter ? 'scatter' : 'bar',plugins:scatter?[]:[zeroMarkers],data:{labels,datasets: datasets.map((d,i)=>({...d,backgroundColor:palette[i%palette.length],borderColor:palette[i%palette.length],pointStyle:['circle','triangle','rect','cross','star','rectRot'][i%6],pointRadius:5,showLine:false,maxBarThickness:18}))},options:{indexAxis:scatter?'x':'y',responsive:true,maintainAspectRatio:false,scales:scatter?{x:{ticks:{color:'#a8b8cf',maxRotation:0},title:{display:true,text:'Logical variables',color:'#a8b8cf'},grid:{color:'#23364b'}},y:valuesAxis}:{x:valuesAxis,y:{ticks:{color:'#e9f0fc',autoSkip:false,font:{size:11}},grid:{display:false}}},plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>scatter ? items[0].raw.instance : context[items[0].dataIndex] || labels[items[0].dataIndex].join(' · ')}}}}});
  charts.set(id,chart);
}
async function comparison() {
  let selection = null, loaded = null, busy = false;
  let instanceId = null;
  function fill(id, values, all) {
    const node=$(id), previous=node.value;
    node.innerHTML = (all ? `<option value="">${all}</option>` : '') + [...new Set(values)].map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
    if ([...node.options].some(o=>o.value===previous)) node.value=previous;
  }
  function render() {
    const analysis=loaded.analysis;
    const instances=analysis.instances || [];
    let instance=instances.find(i=>i.problem_id===instanceId) || instances[0];
    if (instance) { instanceId=instance.problem_id; $('compare-instance').value=instanceId; }
    const runs=instance?.runs || [];
    const pairs=(analysis.comparisons.find(c=>c.comparison_type==='paired_solvers')?.pairs || []).filter(p=>p.problem_id===instanceId);
    const complete=pairs.filter(p=>p.left_run_id && p.right_run_id);
    const view=loaded.instance_summaries.find(i=>i.problem_id===instanceId);
    const groups=view?.groups || [];
    const achievement=view?.optimum_achievement_rate == null ? 'Unavailable' : `${metric(view.optimum_achievement_rate*100)}%`;
    $('comparison-summary').innerHTML = [
      ['Reference optimum',metric(instance?.reference_optimum),instance ? instance.sense+' · selected exact runs' : 'No instance selected'],
      ['Valid quality runs',view?.valid_run_count ?? 0,`${view?.excluded_run_count ?? 0} excluded · this instance`],
      ['Optimum achievement',achievement,`${view?.optimum_achieved_count ?? 0} / ${view?.reference_comparable_count ?? 0} reference-comparable runs`],
      ['Mean gap',metric(view?.gap_percent.mean,'%'),`n = ${view?.gap_percent.count ?? 0} measurable gaps`]
    ].map(([k,v,detail])=>`<div class="stat"><span class="stat-value">${esc(v)}</span><span class="stat-label">${esc(k)}</span><small class="stat-detail">${esc(detail)}</small></div>`).join('');
    $('comparison-window').textContent=`${loaded.selected_count} selected runs · ${instances.length} instances · window ${loaded.window_count ? loaded.offset+1 : 0}–${loaded.offset+loaded.window_count} of ${loaded.total}.`;
    $('compare-prev').disabled=loaded.offset===0; $('compare-next').disabled=loaded.offset+loaded.limit>=loaded.total;
    $('comparison-title').textContent=instance ? `${instance.problem.family || instance.problem.problem_type} · ${shortId(instance.problem_id)} · ${instance.sense}` : 'No instance measurements';
    $('comparison-reference').textContent=instance ? (instance.reference_optimum == null ? `Exact reference unavailable: ${instance.reference_reason}.` : `Reference ${metric(instance.reference_optimum)} · ${instance.reference_run_ids.length} selected exact run(s).`) : 'No runs in this selection. Adjust the filters or choose another window.';
    $('comparison-scope').textContent=`This instance only · ${complete.length} recorded pairs · descriptive means by configuration, not paired speedups.`;
    const chartGroups=groups.slice(0,12);
    $('comparison-chart-limit').hidden=groups.length<=12;
    $('comparison-chart-limit').textContent=`Quality, gap and timing charts show the first 12 of ${groups.length} configurations. Summary metrics and solver tables include all configurations; filter the evidence for a focused chart.`;
    const labels=chartGroups.map(g=>[solverName(g.solver,g.backend.name),`${g.precision?.toUpperCase() || ''} ${modeName(g.warmup_mode)} · ${g.group_id.replace('config-','C')}`.trim()]);
    const contexts=chartGroups.map(g=>`${g.solver} · ${g.backend.name} · ${g.group_id} · ${g.valid_run_count} valid runs; source IDs in solver summary`);
    draw('quality',labels,[{label:'Objective',data:chartGroups.map(g=>g.objective.mean),counts:chartGroups.map(g=>g.objective.count)}],'Mean feasible objective · same instance.',false,contexts);
    draw('gap',labels,[{label:'Gap (%)',data:chartGroups.map(g=>g.gap_percent.mean),counts:chartGroups.map(g=>g.gap_percent.count)}],'Mean gap · lower is better. Dots labelled 0% are measured zeros.',false,contexts);
    const counts=view?.gap_counts || {zero:0,nonzero:0,unavailable:0};
    const state=$('comparison-gap-state');
    state.dataset.state=view?.gap_state || 'unavailable';
    state.textContent=counts.zero || counts.nonzero ? `Run gaps in this instance: ${counts.zero} zero · ${counts.nonzero} nonzero · ${counts.unavailable} unavailable run gaps${view.gap_state==='all_zero'?' — all measurable gaps are 0%.':''}` : `Gap unavailable for ${counts.unavailable} runs${instance?.reference_reason ? ': '+instance.reference_reason : '. No defined relative gap in this selection.'}`;
    draw('timing',labels,[['wall_time_seconds','Wall'],['solver_time_seconds','Compute'],['warmup_seconds','Warmup']].map(([key,name])=>({label:name,data:chartGroups.map(g=>g.timing[key].mean),counts:chartGroups.map(g=>g.timing[key].count)})), 'Mean seconds · scopes retained per configuration; layers overlap.',false,contexts);
    $('comparison-groups').innerHTML=table(['Solver / configuration','Valid runs','Mean objective','Mean gap','Optimum achieved'],groups.map(g=>[
      `<strong>${esc(solverName(g.solver,g.backend.name))}</strong><small class="group-context">${esc(g.precision?.toUpperCase() || 'Precision unreported')} · ${esc(modeName(g.warmup_mode))} · ${esc(g.group_id.replace('config-','C'))}</small><details><summary>Controls & source runs</summary>${json(g)}</details>`,
      `${g.valid_run_count} valid / ${g.run_ids.length} selected`,metric(g.objective.mean),`${metric(g.gap_percent.mean,'%')}<small class="group-context">n = ${g.gap_percent.count} · ${g.gap_counts.unavailable} unavailable</small>`,g.optimum_achievement_rate==null?'Unavailable':`${metric(g.optimum_achievement_rate*100)}% · ${g.optimum_achieved_count}/${g.reference_comparable_count}`
    ]));
    const series = new Map();
    for(const p of loaded.repeat_scaling || []) {
      if(p.wall.mean == null) continue;
      const key=`${p.solver} / ${p.backend} / ${p.warmup_mode} / ${JSON.stringify(p.parameters)}`;
      if(!series.has(key))series.set(key,[]);
      series.get(key).push({x:p.size,y:p.wall.mean,count:p.wall.count,instance:p.problem_id,parameters:p.parameters});
    }
    draw('scaling',[],[...series].map(([name, data],i)=>({label:solverName(name.split(' / ')[0],name.split(' / ')[1])+` · ${modeName(name.split(' / ')[2])} · S${i+1}`,data})), 'Mean wall seconds by size · separate points for each instance and configuration.',true);
    $('comparison-repeats').innerHTML=table(['Solver / backend / warmup','Status counts','Objective n / mean / median / sample SD / range','Wall s: n / mean / median / sample SD / range'],(instance?.repeats || []).map(r=>[`${esc(r.solver)} / ${esc(r.backend)} / ${esc(r.warmup_mode)}<details><summary>Configuration & source runs</summary>${json({parameters:r.parameters,run_ids:r.run_ids})}</details>`,esc(JSON.stringify(r.status_counts)), summary(r.objective), summary(r.timing.wall_time_seconds)]));
    $('comparison-pairs').innerHTML=table(['Repeat / benchmark','Solvers & status','Pairing','Expectation delta / reason'],pairs.map(p=>[`${esc(p.repeat_key)}<br>${esc(shortId(p.benchmark_id))}`,`${esc(p.left_solver)} (${esc(p.left?.status || 'missing')}) / ${esc(p.right_solver)} (${esc(p.right?.status || 'missing')})`,p.left_run_id && p.right_run_id ? 'Recorded pair' : `Incomplete / ambiguous: ${esc(JSON.stringify(p.missing_pairs))}`,`${fmtNum(p.numerical_correctness.max_expectation_delta)}<br>${esc(p.numerical_correctness.reason || 'Matched candidate expectations')}<details><summary>Pair provenance</summary>${json(p)}</details>`]));
    if(pairs.length) $('comparison-pairs').innerHTML = `<details><summary>Explore ${pairs.length} paired / incomplete observations</summary>${$('comparison-pairs').innerHTML}</details>`;
    if (!pairs.length) $('comparison-pairs').insertAdjacentHTML('afterbegin',runs.length ? '<p class="notice warn">Unpaired evidence: no recorded repeat pairs in this instance. Individual measurements remain available.</p>' : '<p class="empty-state">No recorded experiments match this selection. Adjust the filters or choose another campaign.</p>');
    $('comparison-runs').innerHTML=table(['Experiment / backend','Status / feasibility','Objective / gap %','Wall / compute / warmup (s)','Unavailable reasons & provenance'],runs.map(r=>[`<a href="/runs/${encodeURIComponent(r.run_id)}">${esc(shortId(r.run_id))}</a><br>${esc(label(r))}`,`${esc(r.status)} / ${boolText(r.feasible)}`,`${metric(r.objective)} / ${metric(r.optimality_gap_percent)}`,`${metric(r.timing.wall_time_seconds)} / ${metric(r.timing.solver_time_seconds)} / ${metric(r.timing.warmup_seconds)}`,`<details><summary>${Object.keys(r.missing_measurements).length} unavailable measurements</summary>${json(r.missing_measurements)}</details><details><summary>Full provenance & scopes</summary>${json(r)}</details>`]));
    setStatus('comparison-status', `${loaded.selected_count} runs analyzed. ${analysis.warnings.length ? analysis.warnings.length+' scientific warnings; see provenance.' : ''}`);
    if (analysis.warnings.length) $('comparison-runs').insertAdjacentHTML('afterbegin',`<div class="notice warn">${analysis.warnings.map(esc).join('<br>')}</div>`);
    $('comparison-export').disabled=loaded.selected_count===0;
  }
  function summary(s) { return `${s.count} / ${fmtNum(s.mean,5)} / ${fmtNum(s.median,5)} / ${s.std==null?'Unavailable (fewer than 2 observations)':fmtNum(s.std,5)} / ${fmtNum(s.minimum,5)}–${fmtNum(s.maximum,5)}`; }
  async function load(next, reset=true) {
    if(busy) return; busy=true; $('comparison-export').disabled=true;
    setStatus('comparison-status','Analyzing selected evidence…'); $('comparison-workspace').hidden=true;
    try {
      loaded=await apiPost('/comparison',next); selection=next;
      const instances=loaded.analysis.instances || [], runs=instances.flatMap(i=>i.runs);
      fill('compare-instance', instances.map(i=>i.problem_id));
      if(reset) { fill('compare-problem',instances.map(i=>i.problem_id),'All instances'); fill('compare-solver',runs.map(r=>r.solver),'All solvers'); fill('compare-backend',runs.map(r=>r.backend.name),'All backends'); fill('compare-size',loaded.analysis.scaling_points.map(p=>p.x_value),'All sizes'); }
      render(); $('comparison-workspace').hidden=false;
    } catch(e) { setStatus('comparison-status',e.message,true); }
    finally { busy=false; }
  }
  $('comparison-form').addEventListener('submit',e=>{e.preventDefault(); const ids=$('compare-ids').value.trim(); const campaign=$('compare-campaign').value; if(!ids&&!campaign){setStatus('comparison-status','Choose a campaign or enter run IDs.',true);return;} instanceId=null; for(const id of ['compare-problem','compare-solver','compare-backend','compare-size','compare-warmup']) $(id).value=''; load(ids?{run_ids:ids.split(',').map(s=>s.trim()).filter(Boolean),limit:500,offset:0}:{campaign_id:campaign,limit:500,offset:0});});
  $('compare-instance').addEventListener('change',()=>{instanceId=$('compare-instance').value;render();});
  $('comparison-filters').addEventListener('submit',e=>{e.preventDefault();if(!selection)return;const next={...selection,offset:0}; for(const [key,id] of [['problem_id','compare-problem'],['solver','compare-solver'],['backend','compare-backend'],['warmup','compare-warmup'],['size','compare-size']]) {delete next[key];if($(id).value)next[key]=key==='size'?Number($(id).value):$(id).value;}load(next,false);});
  for(const [id,dir] of [['compare-prev',-1],['compare-next',1]]) $(id).addEventListener('click',()=>load({...selection,offset:Math.max(0,selection.offset+dir*selection.limit)},false));
  $('comparison-export').addEventListener('click',async()=>{if(!selection||busy)return; $('comparison-export').disabled=true;setStatus('comparison-export-status','Generating exports…');try{const result=await apiPost('/comparison/reports',selection);$('comparison-export-status').innerHTML=`<a href="/reports/${encodeURIComponent(result.report_id)}">Open report and download JSON, CSV, Markdown →</a>`;}catch(e){setStatus('comparison-export-status',e.message,true);}finally{$('comparison-export').disabled=false;}});
  try { const data=await apiGet('/campaigns?limit=100'); $('compare-campaign').innerHTML='<option value="">Choose a campaign…</option>'+data.campaigns.map(c=>`<option value="${esc(c.campaign_id)}">${esc(c.name)} · ${c.completed_runs} recorded runs</option>`).join(''); const cid=new URLSearchParams(location.search).get('campaign');if(cid){if(!data.campaigns.some(c=>c.campaign_id===cid))$('compare-campaign').insertAdjacentHTML('beforeend',`<option value="${esc(cid)}">${esc(cid)}</option>`);$('compare-campaign').value=cid;await load({campaign_id:cid,limit:500,offset:0});}else setStatus('comparison-status',data.campaigns.length?'Choose a campaign to begin.':'No campaigns yet. Create an experiment or select existing run IDs.'); }catch(e){setStatus('comparison-status',e.message,true);}
}
if(window.VARIAQ_PAGE==='comparison') document.addEventListener('DOMContentLoaded',comparison);
// Dark, readable defaults also apply to historical campaign charts.
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-help]').forEach((node,i)=>{
    node.className='tip'; const id='scientific-help-'+i;
    node.innerHTML=`<button type="button" aria-label="Explain scientific term" aria-describedby="${id}">?</button><span id="${id}" role="tooltip">${esc(node.dataset.help)}</span>`;
    function show(){node.classList.remove('dismissed');const tip=node.querySelector('[role=tooltip]');tip.style.left='0';const box=tip.getBoundingClientRect();if(box.right>innerWidth-12)tip.style.left=(innerWidth-12-box.right)+'px';}
    node.addEventListener('mouseenter',show);node.querySelector('button').addEventListener('focus',show);
    node.addEventListener('keydown',e=>{if(e.key==='Escape')node.classList.add('dismissed');});
  });
  let pending = false;
  function accessibleScrollRegions() {
    if(pending) return; pending=true;
    requestAnimationFrame(()=>{
      pending=false;
      document.querySelectorAll('.table-wrap, .json-block').forEach(node=>{
        const scrollable=node.clientWidth>0 && (node.scrollWidth>node.clientWidth+1 || node.scrollHeight>node.clientHeight+1);
        if(scrollable) {node.tabIndex=0;node.setAttribute('role','group');node.setAttribute('aria-label','Scrollable data. Use arrow keys to scroll.');}
        else {node.removeAttribute('tabindex');node.removeAttribute('role');node.removeAttribute('aria-label');}
      });
    });
  }
  new MutationObserver(accessibleScrollRegions).observe(document.body,{childList:true,subtree:true});
  window.addEventListener('resize',accessibleScrollRegions);
  document.addEventListener('toggle',accessibleScrollRegions,true);
  accessibleScrollRegions();
  if(typeof Chart!=='undefined'){Chart.defaults.color='#a8b8cf';Chart.defaults.borderColor='#2a3b51';}});
})();
