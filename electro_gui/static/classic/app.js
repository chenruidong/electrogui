(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {
    sessions: [], session: null, units: [], fields: new Map(), recipe: null,
    revision: 0, loadSequence: 0, results: {}, jobs: {}, running: {},
    roster: new Set(), view: 'unit', yaw: -.45, pitch: .35,
    workspaces: {
      unit: {revision:0, dirty:true, result:null, previous:null, job:null, preview:null, annotations:[], overlayRevision:0, overlayJob:null},
      population: {revision:0, dirty:true, result:null, previous:null, job:null, preview:null, annotations:[], overlayRevision:0, overlayJob:null}
    },
    recipes: {unit:null, population:null},
    alignments: {unit:[], population:[]}, popView: {dims:'2',x:'0',y:'1',z:'2',loading:'0',time:'0'}
  };
  const clone = v => JSON.parse(JSON.stringify(v));
  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (v, n = 3) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(n) : '—';
  const notice = (message = '', error = false) => {
    $('notice').textContent = message;
    $('notice').hidden = !message;
    $('notice').classList.toggle('error', error);
  };
  const progress = () => { $('progress').hidden = !state.loading && !Object.values(state.running).some(Boolean); };
  async function api(path, options = {}) {
    const response = await fetch(path, {headers: {'Content-Type':'application/json'}, ...options});
    const body = await response.json();
    if (!response.ok) throw Error(body.error || `HTTP ${response.status}`);
    return body;
  }
  async function waitJob(id, current, quiet=false) {
    while (current()) {
      const job = await api(`/api/jobs/${id}`);
      if (!current()) return null;
      if (job.status === 'error') throw Error(job.error);
      if (job.status === 'done') return job.result;
      if(!quiet) notice(job.message);
      await new Promise(resolve => setTimeout(resolve, 700));
    }
    return null;
  }
  function options(el, values, selected) {
    el.replaceChildren(...values.map(item => {
      const [value, label] = Array.isArray(item) ? item : [item, item];
      const option = new Option(String(label), String(value));
      option.selected = String(value) === String(selected);
      return option;
    }));
  }
  function color(key) {
    const styles = getComputedStyle(document.documentElement);
    const semantic = {PP:'--pp', PM:'--pm', MM:'--mm', NA:'--muted', prey:'--pp', predator:'--mm', A:'--accent', B:'--pm', C:'--mm'};
    if (semantic[key]) return styles.getPropertyValue(semantic[key]).trim();
    const palette = ['#225f72','#b15b2b','#397c77','#876ba8','#687829','#c06a8b'];
    let hash = 0;
    for (const char of String(key)) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    return palette[hash % palette.length];
  }
  const groupColor = group => color(group.color_key || group.name);
  const rule = (field, value, op = 'eq') => ({field, op, value});
  const cohort = (id, name, rules) => ({id, name, mode:'all', rules});
  function defaultRecipe() {
    return {enabled:true, shared:{mode:'all',rules:[]}, cohorts:['PP','PM','MM'].map(w => cohort(w,w,[rule('world',w)])),
      facet:'none',group_by:'cohort',split_by:'none',overlap:'exclude',strata:'none',gate:'none'};
  }
  function ws(kind = state.view) { return state.workspaces[kind]; }
  function inputId(kind, name) { return kind === 'unit' ? name : `pop${name[0].toUpperCase()}${name.slice(1)}`; }
  function recipeId(kind, name) { if (kind === 'unit') return ({enabled:'recipeEnabled',facet:'facet',group_by:'groupBy',split_by:'splitBy',overlap:'overlap',strata:'strata',gate:'gate'})[name] || name; return ({enabled:'popRecipeEnabled',facet:'popFacet',group_by:'popGroupBy',split_by:'popSplitBy',overlap:'popOverlap',strata:'popStrata',gate:'popGate'})[name] || `pop${name}`; }
  function invalidate(kind = state.view, reason = 'Settings changed') {
    const w = ws(kind); w.revision++; w.dirty = true;if($('setupSummary'))$('setupSummary').hidden=true;
    state.revision = w.revision;
    if(kind === 'population' && ($('popStability').value !== 'verified_stable' || $('stableRosterSummary').dataset.roster !== [...state.roster].sort((a,b)=>a-b).join(','))) $('stableRosterSummary').hidden = true;
    updateResultState(kind, reason);
    schedulePreview(kind);
    updateSharedSummary();
  }
  function recipeFromUI(kind = state.view) {
    const prefix = kind === 'unit' ? '' : 'pop';
    const r = clone(state.recipes[kind] || defaultRecipe());
    Object.assign(r, {enabled:$(recipeId(kind,'enabled')).checked,facet:$(recipeId(kind,'facet')).value,group_by:$(recipeId(kind,'group_by')).value,
      split_by:$(recipeId(kind,'split_by')).value,overlap:$(recipeId(kind,'overlap')).value,strata:$(recipeId(kind,'strata')).value,gate:$(recipeId(kind,'gate')).value});
    return r;
  }
  function requestBase(kind = state.view) {
    if (!state.session) throw Error('Load an assembled session first.');
    const id = name => inputId(kind,name);
    const numeric = name => {const value = $(id(name)).value.trim(); if (!value || !Number.isFinite(Number(value))) throw Error(`Enter a number for ${id(name)}.`); return Number(value);};
    return {session_id:state.session.session_id, workspace:kind, alignment:$(id('alignment')).value, stability:$(id('stability')).value,
      pre:numeric('pre'), post:numeric('post'), bin:numeric('bin'), sigma:numeric('sigma'),
      count_window:[numeric('countLo'),numeric('countHi')], recipe:recipeFromUI(kind), test:kind==='unit'?$('unitTest').value:'none', annotations:clone(ws(kind).annotations)};
  }
  function updateResultState(kind, reason = 'Settings changed') {
    const w=ws(kind), result=w.result, meta=$(kind==='unit'?'unitMeta':'popMeta');
    const status=result ? (w.dirty ? `Previous result — ${reason || 'settings changed'}` : `Completed result · ${w.job?.slice(0,8)||''}`) : 'No completed result';
    $(kind==='unit'?'jobLabel':'popJobLabel').textContent=status;
    $(kind==='unit'?'resultState':'popResultState').textContent=status;
    meta.dataset.dirty=String(w.dirty);
    if(result) meta.textContent=`${result.settings.alignment} · ${result.settings.stability} · bin ${result.settings.bin*1000} ms · σ ${result.settings.sigma*1000} ms${w.dirty?' · plots and exports use the completed settings':''}`;
    document.querySelectorAll(kind==='unit'?'.export':'.pop-export').forEach(b=>{b.disabled=!w.job;if(w.job)b.dataset.job=w.job;else delete b.dataset.job;});
  }
  function updateCompute(kind) {
    const w=ws(kind), p=w.preview;
    if(kind === 'population') $('stableRoster').disabled = !state.session || state.loading || Boolean(state.running.stableSelection) || Boolean(state.running.population);
    const blocked=Boolean(annotationError(w.annotations)) || !state.session || state.loading || state.running[kind] || (kind==='population' && state.running.stableSelection) || w.previewRevision!==w.revision || !p || p.status==='error' || p.eligibility?.status!=='ready' || !(p.support?.selected_events>0) || (kind==='unit' && p.significance?.status==='blocked');
    for(const id of kind==='unit'?['runUnit','runUnitNear']:['runPopulation','runPopulationNear']) if($(id)) $(id).disabled=Boolean(blocked);
  }

  let previewTimers = {};
  function schedulePreview(kind = state.view) {
    clearTimeout(previewTimers[kind]);
    updateCompute(kind);
    if (!state.session || state.loading) return;
    const el=$(kind==='unit'?'unitPreview':'popPreview'); if(el) el.innerHTML='<strong>Selection preview pending…</strong><span>Checking the current draft; eligibility counts are not final.</span>';
    previewTimers[kind] = setTimeout(() => runPreview(kind), 350);
  }
  async function runPreview(kind) {
    const w = ws(kind), revision = w.revision, sequence=state.loadSequence; if (w.previewInFlight) return; w.previewInFlight=true;
    try {
      const body = {action:'preview', workspace:kind, ...requestBase(kind)};
      if (kind === 'unit') body.unit_id = Number($('unitSelect').value);
      else Object.assign(body,{unit_ids:[...state.roster],method:$('popMethod').value,scaling:$('popScaling').value,components:Number($('popComponents').value)});
      const response = await api('/api/jobs',{method:'POST',body:JSON.stringify(body)});
      const result = await waitJob(response.id, () => sequence===state.loadSequence, true);
      if (result && revision === w.revision && sequence===state.loadSequence) { w.previewRevision=revision; w.preview = result; renderPreview(kind,result); if(kind==='unit') updateTestEligibility(result); }
    } catch (error) {
      if (revision === w.revision && !String(error.message).includes('Action must be')) renderPreviewError(kind,error.message);
    } finally { w.previewInFlight=false; updateCompute(kind); if(w.revision!==revision) schedulePreview(kind); }
  }
  function renderPreview(kind, preview) {
    const el = $(kind === 'unit' ? 'unitPreview' : 'popPreview'); if (!el) return;
    const support = preview.support || {}, errors = preview.errors || [], warnings = preview.warnings || [];
    const groups=(support.cohorts||[]).map(g=>`${escape(g.name||g.id||'group')}: ${g.selected_events??g.events??0} events, ${g.selected_trials??g.trials??0} trials, ${g.blocks??0} blocks`).join(' · ');
    const missing=`${support.missing_rule_events||0} candidate events have a missing rule field`;
    const ledger={exclusions:support.excluded,missing_fields_by_comparison:support.missing_by_cohort,overlap_excluded:support.overlap_excluded||0,temporal_gate_excluded:support.gate_excluded||0,gate_missing_endpoint:support.gate_missing_endpoint||0,strata_excluded:support.strata_excluded||0};
    const excluded=Object.entries(support.excluded||{}).map(([k,v])=>`${k}: ${typeof v==='object'?JSON.stringify(v):v}`).join(' · ');
    const eligibility=preview.eligibility?.status ? `eligibility ${preview.eligibility.status}` : '';
    const tests=preview.significance?.status && preview.significance.status!=='not_requested' ? `${preview.significance.status}: ${preview.significance.reason||''}` : '';
    const reducers=(preview.roster||[]).filter(u=>u.limiting_unit).map(u=>`Unit ${u.id}: removes ${u.marginal_trials_removed} common trials`).join('; ');
    el.innerHTML = `<strong>Selection preview</strong><span>${support.selected_events ?? support.events ?? 0} events · ${support.selected_trials ?? support.eligible_trials ?? 0} trials · ${support.selected_blocks ?? support.blocks ?? 0} blocks</span>${groups?`<span>${groups}</span>`:''}${support.common_eligible_trials != null ? `<span>${support.common_eligible_trials} common eligible trials</span>`:''}${support.overlap_events_before_policy ? `<small>${support.overlap_events_before_policy} overlapping events before policy</small>`:''}${missing?`<small>${escape(missing)}</small>`:''}${excluded?`<small>Excluded: ${escape(excluded)}</small>`:''}${support.valid_zero?'<em class="inline-error">Valid selection with zero support. Review group counts, missing rule fields and exclusions below.</em>':''}${reducers?`<small>Common-trial reducers: ${escape(reducers)}</small>`:''}${eligibility?`<small>${escape(eligibility)}</small>`:''}${tests?`<small>${escape(tests)}</small>`:''}<details><summary>Exclusion and missing-field details</summary><pre>${escape(JSON.stringify(ledger,null,2))}</pre></details>${errors.length ? `<em class="inline-error">${escape(errors.join('; '))}</em>`:''}${warnings.length ? `<small>${escape(warnings.join('; '))}</small>`:''}`;
  }
  function renderPreviewError(kind, message) { const el=$(kind==='unit'?'unitPreview':'popPreview'); if(el) el.innerHTML=`<strong>Selection preview unavailable</strong><span>${escape(message)}</span>`; }
  function updateTestEligibility(preview) { const options=preview.result?.test_options||preview.test_options||{}; const current=$('unitTest').value; state.testBlocked=Boolean(current!=='none' && options[current]?.status==='blocked'); [...$('unitTest').options].forEach(o=>{const info=options[o.value];o.disabled=Boolean(info?.status==='blocked');o.title=info?.reason||'';}); $('testEligibility').textContent=Object.entries(options).map(([key,info])=>`${key==='paired_permutation'?'Within-trial':'Disjoint block'}: ${info.reason}`).join(' ');updateCompute('unit'); if(state.testBlocked) notice(options[current]?.reason||'The selected significance design is not applicable to this selection.',true); }
  function alignmentCategory(value) {
    const key=String(value).toLowerCase();
    if (/reward|token|juice/.test(key)) return 'Reward'; if (/eye|gaze/.test(key)) return 'Eye'; if (/move|joystick|reach/.test(key)) return 'Movement'; if (/object|prey|predator/.test(key)) return 'Object'; if (/sync|clock|diagnostic/.test(key)) return 'Technical'; return 'Trial';
  }
  function fillAlignments(kind, selected) {
    const prefix=kind==='unit'?'':'pop', search=$(kind==='unit'?'alignmentSearch':'popAlignmentSearch'), select=$(inputId(kind,'alignment'));
    const query=(search?.value||'').toLowerCase(); const all=state.alignments[kind] || [];
    const groups=new Map(); all.filter(a=>a===selected||a.toLowerCase().includes(query)).forEach(a=>{const key=['object_outcome','trial_initiation','object_spawn'].includes(a)?'Common':state.session?.alignment_fields?.find(f=>f.key===a)?.category||alignmentCategory(a);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(a);});
    select.replaceChildren(...[...groups].map(([cat,values])=>{const og=document.createElement('optgroup');og.label=cat;values.forEach(v=>{const o=new Option(v,v);o.selected=v===selected || (!selected && v==='object_outcome');og.append(o);});return og;}));
    if (!select.value && all.length) select.value=selected||all[0];
    const help=$(kind==='unit'?'alignmentHelp':'popAlignmentHelp'); if(help) help.textContent=state.session?.alignment_fields?.find(f=>f.key===select.value)?.description||'Recorded event anchor; technical synchronization events are grouped separately.';
  }
  function renderAnnotations(kind='unit') {
    const host=$(kind==='unit'?'annotations':'popAnnotations'); if(!host)return;
    const events=(state.alignments[kind]||[]).filter(e=>e!=='object_outcome'); const eventSelect=(selected,attr)=>`<select data-${attr}><option value="">Choose recorded event…</option>${events.map(v=>`<option value="${escape(v)}" ${selected===v?'selected':''}>${escape(v)}</option>`).join('')}</select>`;
    host.innerHTML=ws(kind).annotations.map((a,i)=>`<div class="annotation-row" data-index="${i}"><label class="check"><input data-visible type="checkbox" ${a.visible!==false?'checked':''}><span>${escape(a.name||a.kind)}</span></label><select data-kind><option value="reference" ${a.kind==='reference'?'selected':''}>Reference line</option><option value="event" ${a.kind==='event'?'selected':''}>Event ticks</option><option value="interval" ${a.kind==='interval'?'selected':''}>Duration band</option></select><input data-name value="${escape(a.name||'Annotation')}" aria-label="Annotation name"><input data-color type="color" value="${a.color||'#225f72'}" aria-label="Annotation color">${a.kind==='reference'?`<label class="inline-field">time <input data-time type="number" step="0.01" value="${a.time??0}"></label>`:`<label class="inline-field">source <select data-source><option value="recorded_events">Recorded events</option></select></label>${a.kind==='event'?`<label class="inline-field">event ${eventSelect(a.event,'event')}</label>`:`<label class="inline-field">onset ${eventSelect(a.onset,'onset')}</label><label class="inline-field">offset ${eventSelect(a.offset,'offset')}</label>`}<label class="inline-field">match <select data-match><option value="same_object" ${a.match==='same_object'?'selected':''}>same object</option><option value="same_trial" ${a.match!=='same_object'?'selected':''}>same trial</option></select></label><label class="inline-field">occurrence <select data-occurrence><option value="first" ${a.occurrence==='first'?'selected':''}>first</option><option value="last" ${a.occurrence==='last'?'selected':''}>last</option><option value="all" ${a.occurrence!=='first'&&a.occurrence!=='last'?'selected':''}>all</option></select></label>`}<button data-remove type="button" class="text-button">Remove</button><small>${a.kind==='reference'?'constant relative time':a.kind==='event'?'per-row event; pairing is explicit':'Recorded-event endpoints, not detected movement bouts. Missing or ambiguous pairs are omitted and reported.'}</small></div>`).join('');
    host.querySelectorAll('.annotation-row').forEach(row=>{const a=ws(kind).annotations[Number(row.dataset.index)], changed=()=>{scheduleAnnotation(kind);};row.querySelector('[data-visible]').onchange=e=>{a.visible=e.target.checked;changed();};row.querySelector('[data-kind]').onchange=e=>{a.kind=e.target.value;renderAnnotations(kind);changed();};row.querySelector('[data-name]').oninput=e=>{a.name=e.target.value;changed();};row.querySelector('[data-color]').oninput=e=>{a.color=e.target.value;changed();};row.querySelector('[data-time]')?.addEventListener('input',e=>{a.time=e.target.value.trim()===''?null:Number(e.target.value);changed();});row.querySelector('[data-source]')?.addEventListener('change',e=>{a.source=e.target.value;changed();});row.querySelector('[data-event]')?.addEventListener('change',e=>{a.event=e.target.value;changed();});row.querySelector('[data-onset]')?.addEventListener('change',e=>{a.onset=e.target.value;changed();});row.querySelector('[data-offset]')?.addEventListener('change',e=>{a.offset=e.target.value;changed();});row.querySelector('[data-match]')?.addEventListener('change',e=>{a.match=e.target.value;changed();});row.querySelector('[data-occurrence]')?.addEventListener('change',e=>{a.occurrence=e.target.value;changed();});row.querySelector('[data-remove]').onclick=()=>{ws(kind).annotations.splice(Number(row.dataset.index),1);renderAnnotations(kind);changed();};});
  }
  function annotationError(layers) {
    for(const a of layers){
      if(a.kind==='reference' && !Number.isFinite(a.time)) return 'Enter a finite reference time.';
      if(a.kind==='event' && !a.event) return 'Choose a recorded event for the tick layer.';
      if(a.kind==='interval' && (!a.onset||!a.offset||a.onset===a.offset)) return 'Choose distinct recorded onset and offset events.';
    }
    return '';
  }
  let annotationTimers={};
  function scheduleAnnotation(kind) {
    const w=ws(kind);clearTimeout(annotationTimers[kind]);w.overlayRevision++;updateCompute(kind);$('setupSummary').hidden=true;
    const error=annotationError(w.annotations);if(error){notice(error,true);return;}
    if(!w.result||!w.job)return;
    $(kind==='unit'?'annotationStatus':'popAnnotationStatus').textContent='Updating display layers; plots and exports retain the last completed overlay until ready.';
    annotationTimers[kind]=setTimeout(()=>annotateResult(kind,w.overlayRevision),300);
  }
  async function annotateResult(kind,revision) {
    const w=ws(kind);if(revision!==w.overlayRevision||w.annotationInFlight||!w.result||!state.session)return;
    w.annotationInFlight=true;
    const sequence=state.loadSequence, baseJob=w.job, sessionId=state.session.session_id;
    const current=()=>sequence===state.loadSequence && state.session?.session_id===sessionId;
    try {
      const job=await api('/api/jobs',{method:'POST',body:JSON.stringify({action:'annotate',workspace:kind,session_id:sessionId,completed_job_id:baseJob,layers:clone(w.annotations)})});
      const result=await waitJob(job.id,current,true);
      if(result&&current()&&revision===w.overlayRevision&&baseJob===w.job){w.result=result;w.job=job.id;state.results[kind]=result;state.jobs[kind]=job.id;kind==='unit'?renderUnit(result):renderPopulation(result);}
    } catch(error){if(current()&&revision===w.overlayRevision)notice(`Annotation update failed: ${error.message}`,true);}
    finally {w.annotationInFlight=false;if(current()&&revision!==w.overlayRevision)scheduleAnnotation(kind);}
  }

  function fieldOptions(selected, special = null, purpose = 'condition', query = '') {
    const q=String(query||'').toLowerCase(); const list = [...state.fields.values()].filter(f=>!q || `${f.key} ${f.label} ${fieldCategory(f)} ${f.description||''}`.toLowerCase().includes(q)).sort((a,b) => `${fieldCategory(a)} ${a.label}`.localeCompare(`${fieldCategory(b)} ${b.label}`));
    if (selected && !list.some(f => f.key === selected) && selected !== special) list.unshift(state.fields.get(selected)||{key:selected,label:selected,availability:'unavailable',reason:'Not present in this session'});
    const groups = new Map();
    for (const f of list) { const key = f.availability === 'unavailable' ? 'Unavailable in this session' : fieldCategory(f); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(f); }
    const rendered = [...groups].map(([category, fields]) => `<optgroup label="${escape(category)}">${fields.map(f =>
      `<option value="${escape(f.key)}" ${selected === f.key ? 'selected' : ''} ${f.availability === 'unavailable' ? 'disabled' : ''}>${escape(f.label || f.key)}${f.availability === 'unavailable' ? ' · unavailable' : ''}${purpose === 'grouping' && f.cardinality != null ? ` · ${f.cardinality} values` : ''}${purpose === 'grouping' && f.type === 'number' && f.grouping_eligible === false ? ' · bins required' : ''}</option>`).join('')}</optgroup>`).join('');
    return (special ? `<option value="${special}">${special === 'cohort' ? 'Comparison group' : 'None'}</option>` : '') + rendered;
  }
  function fieldCategory(field) {
    const key = String(field?.key || '');
    if(['world','intention','bar','role','action','outcome','correct'].includes(key))return 'Common';
    if (/^object|role|action|outcome|bar|image|correct/.test(key)) return 'Object / outcome';
    if (/previous|next|history|error|first|last/.test(key)) return 'History / derived';
    if (field?.timing?.includes('trial') || key === 'world' || key === 'intention') return 'Task / trial';
    if (field?.availability === 'unavailable') return 'Unavailable in this session';
    return 'Advanced recorded fields';
  }
  function fieldError(field, condition) {
    if(!field||field.availability==='unavailable')return field?.reason||'Field unavailable in this session.';
    if(['present','missing'].includes(condition.op))return '';
    const values=Array.isArray(condition.value)?condition.value:[condition.value];
    if(!values.length)return 'Select at least one value.';
    if(field.type==='number' && values.some(v=>typeof v!=='number'||!Number.isFinite(v)))return 'Enter finite numbers.';
    if(condition.op==='between' && (values.length!==2||values[0]>values[1]))return 'Enter an ordered lower and upper bound.';
    if(field.type==='category'&&values.some(v=>!field.values?.map(String).includes(String(v))))return 'Unknown category; choose a valid value. Recorded zero support is shown explicitly.';
    if(field.type==='boolean'&&values.some(v=>typeof v!=='boolean'))return 'Choose Yes or No.';
    return '';
  }
  function validateRuleDisplay(box, condition) {
    const f=state.fields.get(condition.field),help=box.querySelector('.rule-help');if(!help)return;
    const error=fieldError(f,condition);help.textContent=error||`${f.description||f.type} ${f.timing_description||f.timing||''} · ${f.missing_count||0} missing in session rows`;help.classList.toggle('inline-error',Boolean(error));
  }

  function groupAt(index, kind = state.view) { const recipe = state.recipes[kind] || defaultRecipe(); return index === 'shared' ? recipe.shared : recipe.cohorts[Number(index)]; }
  function renderRecipe(kind = state.view) {
    const r = state.recipes[kind] || defaultRecipe(), builder = $(kind==='unit'?'recipeBuilder':'popRecipeBuilder'), fieldQuery=$(kind==='unit'?'conditionSearch':'popConditionSearch')?.value;
    if (!builder) return;
    const renderRules = (group,index) => group.rules.map((condition,i) => {
      const field = state.fields.get(condition.field);
      const unavailable = !field || field.availability === 'unavailable';
      const value = Array.isArray(condition.value) ? condition.value.join(', ') : condition.value ?? '';
      return `<div class="recipe-rule" data-group="${index}" data-index="${i}">
        <select data-field aria-label="Condition field">${fieldOptions(condition.field,null,'condition',fieldQuery)}</select>
        <select data-op aria-label="Condition operator">${operatorsFor(field).map(([op,label]) => `<option value="${op}" ${op === condition.op ? 'selected' : ''}>${label}</option>`).join('')}</select>
        ${valueControl(field, condition, value)}
        <button data-remove-rule type="button" aria-label="Remove condition">×</button>
        <div class="rule-help ${fieldError(field,condition)?'inline-error':''}">${escape(fieldError(field,condition) || (unavailable ? field?.reason || 'Field unavailable for this session' : `${field.description || field.type || ''} ${field.timing_description || field.timing || ''}${field.cardinality != null ? ` · ${field.cardinality} values` : ''}`))}</div>
      </div>`;
    }).join('');
    const renderGroup = (group,index) => `<div class="recipe" data-group-box="${index}"><div class="recipe-headline">
      ${index === 'shared' ? '<strong>Apply to all groups</strong>' : `<input data-name aria-label="Comparison group name" value="${escape(group.name)}">`}
      <select data-mode aria-label="Boolean mode"><option value="all" ${group.mode === 'all' ? 'selected' : ''}>ALL</option><option value="any" ${group.mode === 'any' ? 'selected' : ''}>ANY</option></select>
      ${index === 'shared' ? '' : '<button data-remove-cohort type="button" class="text-button">Remove</button>'}</div>${renderRules(group,index)}
      <button data-add-rule type="button" class="add-rule">+ condition</button></div>`;
    builder.innerHTML = renderGroup(r.shared,'shared') + r.cohorts.map(renderGroup).join('') + '<button data-add-cohort type="button" class="text-button">+ add comparison group</button>';
    builder.querySelectorAll('[data-group-box]').forEach(box => {
      const index = box.dataset.groupBox, group = groupAt(index,kind);
      box.querySelector('[data-mode]').onchange = e => {group.mode = e.target.value; invalidate(kind);};
      const name = box.querySelector('[data-name]');
      if (name) name.oninput = e => {group.name = e.target.value; invalidate(kind);};
      box.querySelector('[data-add-rule]').onclick = () => {group.rules.push(rule('world','PP')); renderRecipe(kind); invalidate(kind);};
      const remove = box.querySelector('[data-remove-cohort]');
      if (remove) remove.onclick = () => {r.cohorts.splice(Number(index),1); renderRecipe(kind); invalidate(kind);};
    });
    builder.querySelectorAll('.recipe-rule').forEach(box => {
      const group = groupAt(box.dataset.group,kind), index = Number(box.dataset.index), condition = group.rules[index];
      box.querySelector('[data-field]').onchange = e => {
        condition.field = e.target.value;
        const f = state.fields.get(condition.field);
        condition.value = f?.type === 'boolean' ? true : f?.type === 'number' ? 0 : f?.values?.[0] || '';
        condition.op = 'eq'; renderRecipe(kind); invalidate(kind); validateRuleDisplay(box,condition);
      };
      box.querySelector('[data-op]').onchange = e => {condition.op = e.target.value; const v=condition.value; if(condition.op==='between')condition.value=Array.isArray(v)&&v.length===2?v:[typeof v==='number'?v:null,null]; else if(['in','not_in'].includes(condition.op))condition.value=Array.isArray(v)?v:[v]; else if(Array.isArray(v))condition.value=v[0]; renderRecipe(kind); invalidate(kind); validateRuleDisplay(box,condition);};
      const valueEl=box.querySelector('[data-value]'), f=state.fields.get(condition.field);
      const parse=v=>f?.type==='number'?(v.trim()===''?null:Number(v)):f?.type==='boolean'?(v==='true'?true:v==='false'?false:null):v;
      if(valueEl && !['present','missing'].includes(condition.op))valueEl.oninput=e=>{
        condition.value=e.target.multiple?[...e.target.selectedOptions].map(o=>parse(o.value)):parse(e.target.value);
        invalidate(kind);validateRuleDisplay(box,condition);
      };
      box.querySelectorAll('[data-bound]').forEach(el=>el.oninput=()=>{condition.value=[...box.querySelectorAll('[data-bound]')].map(el=>parse(el.value));invalidate(kind);validateRuleDisplay(box,condition);});
      box.querySelector('[data-value-search]')?.addEventListener('input',e=>{const q=e.target.value.toLowerCase();[...valueEl.options].forEach(o=>{o.hidden=!o.selected&&!o.text.toLowerCase().includes(q);});});
      box.querySelector('[data-remove-rule]').onclick = () => {group.rules.splice(index,1); renderRecipe(kind); invalidate(kind);};
    });
    builder.querySelector('[data-add-cohort]').onclick = () => {r.cohorts.push(cohort(`cohort_${Date.now()}`,`Group ${r.cohorts.length+1}`,[rule('world','PP')])); renderRecipe(kind); invalidate(kind);};
  }
  function operatorsFor(field) {
    if (!field || field.availability === 'unavailable') return [['eq','is']];
    if (field.type === 'boolean') return [['eq','is'],['ne','is not'],['present','is recorded'],['missing','is missing']];
    if (field.type === 'number') return [['eq','is'],['ne','is not'],['gt','greater than'],['gte','at least'],['lt','less than'],['lte','at most'],['between','between'],['present','is recorded'],['missing','is missing']];
    return [['eq','is'],['ne','is not'],['in','is one of'],['not_in','is not one of'],['present','is recorded'],['missing','is missing']];
  }
  function valueControl(field, condition, value) {
    if(['present','missing'].includes(condition.op))return '<span class="value-note">No value needed</span>';
    const count=v=>`${field?.value_counts?.[String(v)]??0} session rows`;
    if(field?.type==='boolean')return `<select data-value aria-label="Boolean value">${typeof condition.value!=='boolean'?'<option value="">Choose Yes / No</option>':''}${[true,false].map(v=>`<option value="${v}" ${condition.value===v?'selected':''}>${v?'Yes':'No'} · ${count(v)}</option>`).join('')}</select>`;
    if(field?.type==='category'&&Array.isArray(field.values)){
      const multi=['in','not_in'].includes(condition.op), selected=Array.isArray(condition.value)?condition.value:[condition.value], invalid=selected.filter(v=>!field.values.map(String).includes(String(v)));
      const choices=[...invalid,...field.values].map(v=>`<option value="${escape(v)}" ${selected.map(String).includes(String(v))?'selected':''}>${escape(v)} · ${invalid.includes(v)?'INVALID':count(v)}</option>`).join('');
      return `${field.values.length>12?'<input data-value-search type="search" aria-label="Search values" placeholder="Search recorded values…">':''}<select data-value aria-label="Recorded value" ${multi?'multiple size="4"':''}>${choices}</select>${multi?'<small class="value-note">Select one or more; use Cmd/Ctrl to toggle values.</small>':''}`;
    }
    if(condition.op==='between'){const v=Array.isArray(condition.value)?condition.value:[null,null];return `<div class="numeric-bounds"><label>Lower<input data-bound="0" type="number" step="any" value="${v[0]??''}" aria-label="Lower bound"></label><label>Upper<input data-bound="1" type="number" step="any" value="${v[1]??''}" aria-label="Upper bound"></label></div>`;}
    return `<input data-value type="number" step="any" aria-label="Condition value" value="${escape(value)}" placeholder="Finite number">`;
  }

  function fillRecipeControls(kind = 'unit') {
    const r = state.recipes[kind] || defaultRecipe(); state.recipes[kind] = r;
    for (const [base,key,special] of [['Facet','facet','none'],['GroupBy','group_by','cohort'],['SplitBy','split_by','none']]) {
      const id = recipeId(kind,key), control=$(id); if(!control) return; control.innerHTML = fieldOptions(r[key],special,'grouping'); control.value = r[key] || special;
    }
    for (const base of ['overlap','strata','gate']) {const id=recipeId(kind,base); $(id).value = r[base] || (base === 'overlap' ? 'exclude' : 'none');}
    $(recipeId(kind,'enabled')).checked = r.enabled !== false;
    renderRecipe(kind); updateGroupBins(kind);
  }
  function updateGroupBins(kind) { const host=$(kind==='unit'?'groupBins':'popGroupBins'); if(!host)return; const r=state.recipes[kind]||defaultRecipe();for(const key of ['facet','group_by','split_by'])r[key]=$(recipeId(kind,key)).value;const keys=[r.facet,r.group_by,r.split_by].filter(k=>k&&k!=='none'&&k!=='cohort'), numeric=[...new Set(keys)].map(k=>state.fields.get(k)).filter(f=>f?.type==='number'); host.innerHTML=numeric.map(f=>`<label class="field"><span>Bins for ${escape(f.label)} (${escape(f.units||'numeric')})</span><input data-bin-field="${escape(f.key)}" value="${escape((r.group_bins?.[f.key]||[]).join(', '))}" placeholder="e.g. 0, 1, 2"><small class="help">Explicit ascending edges are required for numeric grouping; observed range ${escape((f.range||[]).join('–'))}</small></label>`).join(''); host.querySelectorAll('[data-bin-field]').forEach(input=>input.oninput=e=>{r.group_bins=r.group_bins||{};r.group_bins[e.target.dataset.binField]=e.target.value.split(',').map(v=>v.trim()===''?null:Number(v.trim()));invalidate(kind);}); }
  async function loadSession(id) {
    const sequence = ++state.loadSequence;
    $('stableRosterSummary').hidden = true;
    state.session = null; state.units = []; state.loading = true; state.recipes = {unit:defaultRecipe(),population:defaultRecipe()};
    for (const kind of ['unit','population']) { const w=ws(kind); w.revision++; w.result=null; w.previous=null; w.job=null; w.dirty=true; w.preview=null; w.overlayRevision++; w.overlayJob=null; w.annotations=[]; w.previewRevision=null;clearTimeout(previewTimers[kind]);clearTimeout(annotationTimers[kind]); }
    state.results={};state.jobs={};state.testBlocked=false;$('unitTitle').textContent='Unit result';$('sourceHash').textContent='Verifying source';$('setupSummary').hidden=true;for(const id of ['popAnnotationPlot'])$(id).hidden=true;
    document.querySelectorAll('canvas').forEach(c=>c.getContext('2d').clearRect(0,0,c.width,c.height));
    for(const id of ['unitSupport','popSupport','statsPanel','membershipPanel','provenancePanel','popDetails','unitLegend','popLegend','annotationStatus','popAnnotationStatus'])$(id).textContent='';
    for(const kind of ['unit','population']){updateResultState(kind);updateCompute(kind);$(kind==='unit'?'unitMeta':'popMeta').textContent='Loading exact session source…';}
    progress();
    $('unitSelect').replaceChildren(new Option('Loading…',''));
    $('sourceStatus').textContent = 'Verifying and preparing session…';
    try {
      const job = await api('/api/jobs',{method:'POST',body:JSON.stringify({action:'load',session_id:id})});
      const result = await waitJob(job.id,() => sequence === state.loadSequence);
      if (!result) return false;
      state.session = result; state.units = result.units; state.fields = new Map(result.fields.map(f => [f.key,f]));
      state.roster = new Set(); $('rosterSelectedOnly').checked=false;
      options($('rosterArea'),[['','All areas'],...[...new Set(state.units.map(u=>u.area))].sort()], '');options($('rosterQuality'),[['','All qualities'],...[...new Set(state.units.map(u=>u.quality))].sort()], '');
      state.alignments.unit = result.alignments; state.alignments.population = result.alignments;
      fillAlignments('unit'); fillAlignments('population');
      $('unitSearch').value = ''; renderUnits(); renderRoster(); fillRecipeControls('unit'); fillRecipeControls('population'); renderAnnotations('unit'); renderAnnotations('population');
      $('sourceStatus').textContent = `${result.session_id} · loaded`;
      $('sourceDot').className = 'status-dot ok';
      $('sourceHash').textContent = `SHA256 ${result.source.sha256.slice(0,20)}…`;
      $('sourceHash').title = result.source.sha256;
      $('footerSource').textContent = result.source.path;
      $('eligibilityNote').textContent = `${result.units.length} units · ${result.counts.trials} trials · local NWB`;
      notice((result.notices || []).join('; ')); updateSharedSummary(); schedulePreview('unit'); schedulePreview('population');
      return true;
    } catch (error) {
      if (sequence === state.loadSequence) {notice(error.message,true); $('sourceStatus').textContent = 'Session unavailable'; $('sourceDot').className = 'status-dot error';}
      return false;
    } finally {if (sequence === state.loadSequence) {state.loading = false; progress();schedulePreview('unit');schedulePreview('population');}}
  }
  function renderUnits() {
    const previous = $('unitSelect').value, query = $('unitSearch').value.toLowerCase();
    const units = state.units.filter(u => `${u.id} ${u.area} ${u.quality}`.toLowerCase().includes(query));
    options($('unitSelect'),units.map(u => [u.id,`${u.id} · ${u.area || 'unknown area'} · ${u.quality || 'unclassified'}`]),previous || (units.some(u => u.id === 315) ? 315 : units[0]?.id));
    if (previous && previous !== $('unitSelect').value) invalidate('unit','unit changed');
  }
  function filteredRoster() {
    const tokens = $('rosterFilter').value.toLowerCase().split(/\s+/).filter(Boolean);
    const matches=state.units.filter(u => (!$('rosterArea').value||u.area===$('rosterArea').value)&&(!$('rosterQuality').value||u.quality===$('rosterQuality').value)&&tokens.every(t => `${u.id} ${u.area} ${u.quality}`.toLowerCase().includes(t)));
    return $('rosterSelectedOnly')?.checked ? matches.filter(u=>state.roster.has(u.id)) : matches;
  }
  function renderRoster() {
    $('roster').innerHTML = filteredRoster().map(u => `<label title="${escape(u.area)} ${escape(u.quality)}"><input type="checkbox" value="${u.id}" ${state.roster.has(u.id) ? 'checked' : ''}>${u.id} · ${escape(u.area || '?')} · ${escape(u.quality||'unclassified')}</label>`).join('');
    $('roster').querySelectorAll('input').forEach(input => {input.onchange = () => {input.checked ? state.roster.add(Number(input.value)) : state.roster.delete(Number(input.value)); invalidate('population','roster changed'); renderRoster();};});
    const areas=[...new Set([...state.roster].map(id=>state.units.find(u=>u.id===id)?.area).filter(Boolean))];
    $('rosterCount').textContent = `${state.roster.size} units selected · ${filteredRoster().length} shown. Selection is retained when filtering.`;
    $('rosterWarning').textContent = areas.length>1 ? `Joint population across ${areas.join(', ')}; unit areas are retained in the result.` : state.roster.size===0 ? 'Choose units explicitly; no default roster is applied.' : '';
    updateCompute('population');
  }
  async function selectStableRoster() {
    if (!state.session || state.loading || state.running.stableSelection) return;
    const sequence = state.loadSequence, revision = ws('population').revision;
    const current = () => sequence === state.loadSequence && revision === ws('population').revision;
    state.running.stableSelection = true; updateCompute('population'); progress();
    $('stableRosterSummary').hidden = true;
    try {
      const job = await api('/api/jobs', {method:'POST', body:JSON.stringify({action:'stable_selection', session_id:state.session.session_id})});
      const result = await waitJob(job.id, current);
      if (!result || !current()) return;
      if (!result.n_units || !result.n_trials) throw Error('No SUA/MUA units have verified stable complete trials. Current selection retained.');
      state.roster = new Set(result.unit_ids);
      $('popStability').value = 'verified_stable';
      $('rosterFilter').value = ''; $('rosterArea').value = ''; $('rosterQuality').value = ''; $('rosterSelectedOnly').checked = true;
      invalidate('population', 'shared-stable SUA/MUA selected'); renderRoster();
      $('stableRosterSummary').textContent = `${result.n_units} neurons × ${result.n_trials} shared stable trials = ${result.coverage.toLocaleString()} neuron-trials. Heuristic selection from ${result.candidate_units} SUA/MUA; trial support may span multiple periods. Event, condition and window filters apply afterward.`;
      $('stableRosterSummary').dataset.roster = [...state.roster].sort((a,b)=>a-b).join(',');
      $('stableRosterSummary').hidden = false;
      notice('Shared-stable SUA/MUA selection applied. Eligibility set to Verified stable.');
    } catch (error) { if(current()) notice(error.message, true); }
    finally { state.running.stableSelection = false; progress(); updateCompute('population'); }
  }
  async function run(kind) {
    if (state.running[kind]) return;
    const w=ws(kind); invalidate(kind,'draft submitted'); w.overlayRevision++; w.overlayJob=null; const revision = w.revision, sequence=state.loadSequence;
    state.running[kind] = true; progress(); $(`run${kind === 'unit' ? 'Unit' : 'Population'}`).disabled = true;
    try {
      if (kind==='unit'&&state.blockedPresetReason) throw Error(state.blockedPresetReason);
      if (kind==='unit' && state.testBlocked) throw Error('The selected significance design is not applicable to the current selection; review the preview explanation.');
      const body = {action:kind,...requestBase(kind)};
      if (kind === 'unit') {
        if (!$('unitSelect').value) throw Error('Select a unit.');
        body.unit_id = Number($('unitSelect').value);
      } else {
        Object.assign(body,{unit_ids:[...state.roster],method:$('popMethod').value,scaling:$('popScaling').value,components:Number($('popComponents').value),test:'none'});
      }
      const job = await api('/api/jobs',{method:'POST',body:JSON.stringify(body)});
      const result = await waitJob(job.id,() => sequence===state.loadSequence);
      if (!result || revision!==w.revision) return;
      w.previous = w.result; w.result = result; w.job = job.id; w.dirty = false; state.results[kind] = result; state.jobs[kind] = job.id;
      kind === 'unit' ? renderUnit(result) : renderPopulation(result);
      document.querySelectorAll(kind === 'unit' ? '.export' : '.pop-export').forEach(b => {b.disabled = false; b.dataset.job = job.id;});
      notice((result.rows || result.groups || []).length ? '' : 'No eligible events. Review the support exclusions, selected conditions, time window, and eligibility policy.');
      updateResultState(kind,'');if(JSON.stringify(body.annotations)!==JSON.stringify(w.annotations))scheduleAnnotation(kind);
    } catch (error) {if (revision === w.revision) notice(error.message,true);}
    finally {state.running[kind] = false; progress(); updateCompute(kind);}
  }
  function supportText(s) {return `${s.selected_trials ?? 0} trials · ${s.unique_events ?? s.selected_events ?? 0} unique events · ${s.selected_blocks ?? 0} blocks`;}
  function legend(id,groups) {
    $(id).innerHTML = groups.map(g => `<span class="legend-item"><i style="display:inline-block;width:16px;border-top:2px ${g.line_dashed ? 'dashed' : 'solid'} ${groupColor(g)}"></i>${escape(g.label)}${g.trials == null ? '' : ` · ${g.trials} trials`}</span>`).join('');
  }
  function canvas(id,height) {
    const el = $(id), width = Math.max(260,el.getBoundingClientRect().width || 650), dpr = window.devicePixelRatio || 1;
    el.width = width*dpr; el.height = height*dpr; el.style.height = `${height}px`;
    const c = el.getContext('2d'); c.scale(dpr,dpr); c.font = '11px -apple-system, sans-serif';
    return {c,w:width,h:height};
  }
  function frame(plot, x0, x1, y0, y1, offset = 0, height = plot.h, xlabel = 'Time from alignment (s)', ylabel = '') {
    const {c,w} = plot, l = 58, r = w-18, top = offset+27, bottom = offset+height-43;
    if (y0 === y1) y1 = y0+1;
    const x = value => l+(value-x0)/(x1-x0 || 1)*(r-l), y = value => bottom-(value-y0)/(y1-y0)*(bottom-top);
    c.lineWidth = 1; c.setLineDash([]); c.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--line');
    c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--muted');
    for (let i=0;i<4;i++) {
      const value = y0+(y1-y0)*i/3, yy = y(value);
      c.beginPath(); c.moveTo(l,yy); c.lineTo(r,yy); c.stroke(); c.textAlign='right'; c.fillText(fmt(value,Math.abs(y1-y0)>20?0:1),l-7,yy+4);
    }
    for (const value of [...new Set([x0,...(x0<0&&x1>0?[0]:[(x0+x1)/2]),x1])]) {c.textAlign='center';c.fillText(fmt(value,2),x(value),bottom+17);}
    c.textAlign='center'; c.fillText(xlabel,(l+r)/2,offset+height-6);
    c.save();c.translate(13,(top+bottom)/2);c.rotate(-Math.PI/2);c.fillText(ylabel,0,0);c.restore();
    if (x0<0&&x1>0) {c.setLineDash([4,4]);c.beginPath();c.moveTo(x(0),top);c.lineTo(x(0),bottom);c.stroke();c.setLineDash([]);}
    return {x,y,l,r,top,bottom};
  }
  function shaded(c,f,window) {c.fillStyle=document.documentElement.classList.contains('dark')?'#5b4a2438':'#ffdf813d';c.fillRect(f.x(window[0]),f.top,f.x(window[1])-f.x(window[0]),f.bottom-f.top);}
  function drawAnnotationLayers(plot,f,result,rows,pass='all') {
    const c=plot.c, annotationRows=result.annotations?.rows||{}, height=(f.bottom-f.top)/Math.max(1,rows.length);
    c.save();c.beginPath();c.rect(f.l,f.top,f.r-f.l,f.bottom-f.top);c.clip();
    for(const a of result.annotations?.layers||[]){
      if(a.visible===false || (pass==='background' && a.kind!=='interval') || (pass==='foreground' && a.kind==='interval'))continue;c.strokeStyle=a.color||color('A');c.fillStyle=a.color||color('A');c.lineWidth=a.kind==='reference'?1.6:1.2;c.setLineDash(a.kind==='reference'?[5,4]:[]);
      if(a.kind==='reference'){c.beginPath();c.moveTo(f.x(a.time),f.top);c.lineTo(f.x(a.time),f.bottom);c.stroke();continue;}
      rows.forEach((row,i)=>{const v=annotationRows[String(row.row_id)]?.[a.id]||{},top=f.top+i*height;
        if(a.kind==='event')for(const t of v.ticks||[]){c.beginPath();c.moveTo(f.x(t),top);c.lineTo(f.x(t),top+height);c.stroke();}
        if(a.kind==='interval')for(const band of v.intervals||[]){c.globalAlpha=.24;c.fillRect(f.x(band.onset),top,f.x(band.offset)-f.x(band.onset),height);c.globalAlpha=1;}
      });
    }c.restore();
  }
  function annotationStrips(kind,result) {
    if(kind==='unit') return; // Unit annotations belong to their raster rows.
    const id=kind==='unit'?'unitAnnotationPlot':'popAnnotationPlot',layers=(result.annotations?.layers||[]).filter(a=>a.visible!==false&&a.kind!=='reference');
    $(id).hidden=!layers.length;if(!layers.length)return;
    const plot=canvas(id,60+layers.length*45),c=plot.c,left=35,right=plot.w-15,lo=result.settings.pre,hi=result.settings.post,x=t=>left+(t-lo)/(hi-lo)*(right-left);
    c.save();c.beginPath();c.rect(left,0,right-left,plot.h);c.clip();
    layers.forEach((layer,i)=>{const a=result.annotations.summary.aggregates[layer.id],y=25+i*45;if(!a)return;c.fillStyle=layer.color||color('A');c.textAlign='left';c.fillText(`${layer.name}: ${a.kind==='interval'?'occupancy (0–100%)':'event times'} · pooled selected anchors`,left,y-8,right-left);
      if(a.kind==='event')for(const t of a.times||[])c.fillRect(x(t),y,1,11);
      if(a.kind==='interval')for(let j=0;j<(a.occupancy?.fraction||[]).length;j++){c.globalAlpha=a.occupancy.fraction[j];c.fillRect(x(a.occupancy.edges[j]),y,Math.max(1,x(a.occupancy.edges[j+1])-x(a.occupancy.edges[j])),11);}c.globalAlpha=1;
    });c.restore();c.fillStyle=color('NA');c.textAlign='center';for(const t of [lo,0,hi])if(t>=lo&&t<=hi)c.fillText(fmt(t,2),x(t),plot.h-20);c.fillText('Time from alignment (s)',(left+right)/2,plot.h-4);
  }
  function annotationSummary(kind,result) {
    const host=$(kind==='unit'?'annotationStatus':'popAnnotationStatus'),a=result.annotations;annotationStrips(kind,result);
    host.hidden=!a?.layers?.length;
    if(host.hidden){host.textContent='';return;}
    host.innerHTML=`<strong>Recorded-event overlays</strong><p class="help">Coverage counts selected memberships. Endpoint problems accumulate across those rows. ${kind==='unit'?'Reference lines and event ticks are drawn directly on the raster; duration bands stay behind the spikes.':'Mean-panel strips pool unique selected anchors; event strips are times, not a rate.'} Recorded joystick edges are not detected movement bouts.</p>${a.layers.map(l=>{const x=a.summary.layers[l.id];return `<p><i style="border-top:3px solid ${escape(l.color)};display:inline-block;width:15px"></i> ${escape(l.name)}${l.visible===false?' (hidden)':''} · ${x.coverage}/${a.summary.selected_rows} covered · ${x.missing} missing · ${x.ambiguous} ambiguous · ${x.clipped} clipped/outside</p>`;}).join('')}<details><summary>Inspect exact source rows and paired endpoints</summary><pre>${escape(JSON.stringify({source:result.provenance.computation_identity?.source_nwb,layers:a.layers,summary:a.summary.layers,sample_rows:Object.fromEntries(Object.entries(a.rows).filter(([,v])=>Object.values(v).some(x=>x.ticks?.length||x.intervals?.length)).slice(0,8))},null,2))}</pre><small>All source identities and relative endpoints are retained in JSON and counts/events exports.</small></details>`;
  }

  function facetKeys(result) {return [...new Set(result.groups.map(g => g.facet_key))];}
  function drawUnitRaster(result,id='raster',window=[result.settings.pre,result.settings.post]) {
    const facets = facetKeys(result), height = id === 'raster' ? 205 : 155;
    const plot = canvas(id,Math.max(1,facets.length)*height);
    facets.forEach((facet,index) => {
      const groups = result.groups.filter(g => g.facet_key === facet), names = new Set(groups.map(g => g.name));
      const rows = result.rows.filter(r => names.has(r.group));
      const f = frame(plot,...window,Math.max(1,rows.length),0,index*height,height,'Time from alignment (s)','Event row');
      shaded(plot.c,f,[Math.max(window[0],result.settings.count_window[0]),Math.min(window[1],result.settings.count_window[1])]);
      drawAnnotationLayers(plot,f,result,rows,'background');
      plot.c.save();plot.c.beginPath();plot.c.rect(f.l,f.top,f.r-f.l,f.bottom-f.top);plot.c.clip();
      const styles = new Map(groups.map(g => [g.name,groupColor(g)]));
      rows.forEach((row,i) => {
        const y = f.top+(i+.5)/Math.max(1,rows.length)*(f.bottom-f.top);
        plot.c.strokeStyle=styles.get(row.group);plot.c.lineWidth=.7;
        for (const t of row.spikes) if (t>=window[0]&&t<window[1]) {plot.c.beginPath();plot.c.moveTo(f.x(t),y-1.5);plot.c.lineTo(f.x(t),y+1.5);plot.c.stroke();}
      });
      plot.c.restore();
      drawAnnotationLayers(plot,f,result,rows,'foreground');
      plot.c.fillStyle=color('A');plot.c.textAlign='left';
      plot.c.fillText(facet==='none'?'All selected events':`${result.settings.recipe.facet} = ${groups[0].facet_value ?? 'missing'}`,f.l,index*height+14);
    });
  }
  function drawPsth(result) {
    const facets=facetKeys(result),height=230,plot=canvas('psth',Math.max(1,facets.length)*height);
    const max=Math.max(1,...result.groups.flatMap(g => g.mean.map((v,i) => v+g.sem[i])))*1.08;
    facets.forEach((facet,index) => {
      const groups=result.groups.filter(g=>g.facet_key===facet);
      const f=frame(plot,result.settings.pre,result.settings.post,0,max,index*height,height,'Time from alignment (s)','Rate (Hz)');
      shaded(plot.c,f,result.settings.count_window);
      drawAnnotationLayers(plot,f,result,[]);
      groups.forEach(g => {
        plot.c.fillStyle=groupColor(g);plot.c.globalAlpha=.13;plot.c.beginPath();
        g.mean.forEach((v,i)=>{const x=f.x(result.times[i]),y=f.y(v+g.sem[i]);i?plot.c.lineTo(x,y):plot.c.moveTo(x,y);});
        for(let i=g.mean.length-1;i>=0;i--)plot.c.lineTo(f.x(result.times[i]),f.y(Math.max(0,g.mean[i]-g.sem[i])));
        plot.c.closePath();plot.c.fill();plot.c.globalAlpha=1;plot.c.strokeStyle=groupColor(g);plot.c.lineWidth=1.8;plot.c.setLineDash(g.line_dashed?[5,4]:[]);plot.c.beginPath();
        g.mean.forEach((v,i)=>{const x=f.x(result.times[i]),y=f.y(v);i?plot.c.lineTo(x,y):plot.c.moveTo(x,y);});plot.c.stroke();plot.c.setLineDash([]);
      });
      plot.c.textAlign='left';plot.c.fillStyle=color('A');plot.c.fillText(facet==='none'?'Equal-trial mean ± SEM':`${result.settings.recipe.facet} = ${groups[0].facet_value ?? 'missing'}`,f.l,index*height+14);
    });
  }
  function drawHistogram(result) {
    const plot=canvas('countHistogram',210), distributions=result.groups.map(group=>{
      const trials=new Map();result.rows.filter(r=>r.group===group.name).forEach(r=>{if(!trials.has(r.trial))trials.set(r.trial,[]);trials.get(r.trial).push(r.rate);});
      return {group,values:[...trials.values()].map(v=>v.reduce((a,b)=>a+b,0)/v.length)};
    });
    const max=Math.max(1,...distributions.flatMap(d=>d.values))*1.001,n=12;
    distributions.forEach(d=>{d.bins=Array(n).fill(0);d.values.forEach(v=>d.bins[Math.min(n-1,Math.floor(v/max*n))]++);d.bins=d.bins.map(v=>v/d.values.length);});
    const ymax=Math.max(.1,...distributions.flatMap(d=>d.bins))*1.05,f=frame(plot,0,max,0,ymax,0,210,'Trial mean rate in count window (Hz)','Trial fraction');
    distributions.forEach(d=>{plot.c.strokeStyle=groupColor(d.group);plot.c.setLineDash(d.group.line_dashed?[5,4]:[]);plot.c.beginPath();d.bins.forEach((v,i)=>{const x0=f.x(max*i/n),x1=f.x(max*(i+1)/n),y=f.y(v);if(!i)plot.c.moveTo(x0,y);else plot.c.lineTo(x0,y);plot.c.lineTo(x1,y);});plot.c.stroke();plot.c.setLineDash([]);});
  }
  function renderUnit(result) {
    $('unitTitle').textContent=`Unit ${result.unit.id} · ${result.unit.area || 'unknown area'} · ${result.unit.quality}`;
    $('unitMeta').textContent=`${result.settings.alignment} · ${result.settings.stability} · bin ${result.settings.bin*1000} ms · σ ${result.settings.sigma*1000} ms`;
    $('unitSupport').textContent=supportText(result.support);
    $('rasterCaption').textContent=`${result.rows.length} memberships · each row is an event`;
    $('windowCaption').textContent=`[${result.settings.count_window.join(', ')}) s · raw counts`;
    legend('unitLegend',result.groups);drawUnitRaster(result);drawPsth(result);drawUnitRaster(result,'windowRaster',result.settings.count_window);drawHistogram(result);
    const s=result.statistics;
    $('statsPanel').innerHTML=`<div class="stat-grid">${[['Test',s.status],['Effect (Hz)',fmt(s.effect)],['Two-sided p',fmt(s.p_value,5)],['Blocks',s.n_blocks??'—']].map(([label,value])=>`<div class="stat"><strong>${escape(value)}</strong><small>${label}</small></div>`).join('')}</div>
      <p class="stats-note">${escape(s.reason||s.estimator||'Descriptive result. Select a significance test to evaluate a declared A/B comparison.')}</p><p class="help">${escape(s.correction||'')} ${escape(s.scope||'')}</p>
      <details><summary>Support and test details</summary><pre>${escape(JSON.stringify({support:result.support,statistics:s},null,2))}</pre></details>`;
    $('membershipPanel').innerHTML=`<p class="help">First 60 memberships. Counts / events CSV and JSON contain every row.</p><table class="data-table"><thead><tr><th>Trial</th><th>Cohort</th><th>Count</th><th>Rate Hz</th><th>Source row</th></tr></thead><tbody>${result.rows.slice(0,60).map(r=>`<tr><td>${r.trial}</td><td>${escape(r.cohort_name)}</td><td>${r.count}</td><td>${fmt(r.rate,2)}</td><td>${r.row_id}</td></tr>`).join('')}</tbody></table>`;
    $('provenancePanel').innerHTML=`<pre>${escape(JSON.stringify(result.provenance,null,2))}</pre>`;
    annotationSummary('unit',result);updateResultState('unit');
  }
  function projection(result) {
    const a=Number($('popX').value),b=Number($('popY').value),z=Number($('popZ').value);
    const three=$('popDims').value==='3'&&result.components>=3;
    return point => {
      if(!three)return [point[a],point[b]];
      const x=point[a],y=point[b],depth=point[z],cy=Math.cos(state.yaw),sy=Math.sin(state.yaw),cp=Math.cos(state.pitch),sp=Math.sin(state.pitch);
      return [cy*x+sy*depth,cp*y-sp*(-sy*x+cy*depth)];
    };
  }
  function drawTrajectory(result) {
    const plot=canvas('trajectory',360),project=projection(result),points=result.groups.flatMap(g=>g.coordinates.map(project));
    if(!points.length)return;
    let x0=Math.min(...points.map(p=>p[0])),x1=Math.max(...points.map(p=>p[0])),y0=Math.min(...points.map(p=>p[1])),y1=Math.max(...points.map(p=>p[1]));
    const dx=(x1-x0||1)*.08,dy=(y1-y0||1)*.08;
    const three=$('popDims').value==='3';
    const f=frame(plot,x0-dx,x1+dx,y0-dy,y1+dy,0,360,three?'3D projection · horizontal':`Component ${Number($('popX').value)+1}`,three?'3D projection · vertical':`Component ${Number($('popY').value)+1}`);
    result.groups.forEach(g=>{
      plot.c.strokeStyle=groupColor(g);plot.c.lineWidth=1.8;plot.c.setLineDash(g.line_dashed?[5,4]:[]);plot.c.beginPath();
      g.coordinates.map(project).forEach((v,i)=>{i?plot.c.lineTo(f.x(v[0]),f.y(v[1])):plot.c.moveTo(f.x(v[0]),f.y(v[1]));});plot.c.stroke();plot.c.setLineDash([]);
      const first=project(g.coordinates[0]);plot.c.beginPath();plot.c.arc(f.x(first[0]),f.y(first[1]),4,0,Math.PI*2);plot.c.stroke();
      const point=project(g.coordinates[Math.min(Number($('popTime').value),g.coordinates.length-1)]);plot.c.fillStyle=groupColor(g);plot.c.beginPath();plot.c.arc(f.x(point[0]),f.y(point[1]),4,0,Math.PI*2);plot.c.fill();
    });
  }
  function drawTimecourses(result) {
    const components=[...new Set([Number($('popX').value),Number($('popY').value),...($('popDims').value==='3'?[Number($('popZ').value)]:[])])];
    const height=185,plot=canvas('timecourses',height*components.length);
    components.forEach((component,index)=>{
      const values=result.groups.flatMap(g=>g.coordinates.map(p=>p[component]));
      const lo=Math.min(0,...values),hi=Math.max(0,...values),pad=(hi-lo||1)*.1;
      const f=frame(plot,result.settings.pre,result.settings.post,lo-pad,hi+pad,index*height,height,'Time from alignment (s)',`Component ${component+1}`);
      result.groups.forEach(g=>{plot.c.strokeStyle=groupColor(g);plot.c.lineWidth=1.5;plot.c.setLineDash(g.line_dashed?[5,4]:[]);plot.c.beginPath();g.coordinates.forEach((point,i)=>{const x=f.x(result.times[i]),y=f.y(point[component]);i?plot.c.lineTo(x,y):plot.c.moveTo(x,y);});plot.c.stroke();plot.c.setLineDash([]);});
      drawAnnotationLayers(plot,f,result,[]);
      const t=result.times[Number($('popTime').value)];plot.c.strokeStyle=color('NA');plot.c.setLineDash([2,3]);plot.c.beginPath();plot.c.moveTo(f.x(t),f.top);plot.c.lineTo(f.x(t),f.bottom);plot.c.stroke();plot.c.setLineDash([]);
    });
    $('trajectoryHelp').textContent=`Time ${fmt(result.times[Number($('popTime').value)],3)} s · hollow start, filled current time. Drag in 3D; SVG exports the X/Y plane.`;
  }
  function drawLoadings(result) {
    const component=Number($('loadingComponent').value),roster=result.active_unit_ids;
    const values=result.loadings.map((v,i)=>({value:v[component],id:roster[i]})).sort((a,b)=>Math.abs(b.value)-Math.abs(a.value)).slice(0,24);
    const plot=canvas('loadings',Math.max(240,values.length*15+35)),max=Math.max(1e-9,...values.map(p=>Math.abs(p.value))),mid=plot.w/2;
    plot.c.font='10px sans-serif';plot.c.textAlign='right';plot.c.fillStyle=color('NA');
    values.forEach((p,i)=>{const y=20+i*15,x=mid+p.value/max*(plot.w/2-65);plot.c.fillStyle=color('A');plot.c.fillRect(Math.min(x,mid),y,Math.abs(x-mid),8);plot.c.fillStyle=color('NA');plot.c.fillText(String(p.id),45,y+8);});
    $('loadingCaption').textContent=`Component ${component+1} · ${values.length} largest absolute weights; all exported`;
  }
  function drawDiagnostic(result) {
    const plot=canvas('diagnostic',240),d=result.diagnostics;
    plot.c.fillStyle=color('NA');plot.c.textAlign='left';
    const lines=[`${d.method.toUpperCase()} · ${d.scaling}`,`Rank ${d.rank} · ${d.fit_rows} fit rows`,
      `Reconstruction R² ${fmt(d.reconstruction_r2,3)}`,`Converged: ${d.converged ? 'yes' : 'NO'} · ${d.iterations} iterations`,'Joint fit to displayed means · in-sample'];
    lines.forEach((line,i)=>plot.c.fillText(line,12,20+i*20));
    if(d.explained_variance_ratio){const values=d.explained_variance_ratio,max=Math.max(...values),width=(plot.w-45)/values.length;values.forEach((v,i)=>{plot.c.fillStyle=color('A');plot.c.fillRect(25+i*width,215-75*v/max,width-8,75*v/max);plot.c.fillStyle=color('NA');plot.c.fillText(`${i+1}: ${fmt(v*100,1)}%`,25+i*width,232);});}
    $('diagnosticCaption').textContent=d.converged?'Descriptive fit':'Convergence warning';
  }
  function renderPopulation(result) {
    const dropped=result.diagnostics.dropped_constant_units||result.dropped_constant_units||[];
    $('popMeta').textContent=`${result.diagnostics.method.toUpperCase()} · ${result.unit_ids.length} units · ${result.settings.stability} · one joint descriptive fit${dropped.length ? ` · ${dropped.length} constant unit${dropped.length===1?'':'s'} dropped` : ''}`;
    $('popSupport').textContent=supportText(result.support);legend('popLegend',result.groups);
    for(const [id,fallback] of [['popX',0],['popY',1],['popZ',2],['loadingComponent',0]]){
      const previous=state.popView[{popX:'x',popY:'y',popZ:'z',loadingComponent:'loading'}[id]];options($(id),Array.from({length:result.components},(_,i)=>[i,`Component ${i+1}`]),previous!==''&&Number(previous)<result.components?previous:Math.min(fallback,result.components-1));
    }
    $('popDims').querySelector('[value="3"]').disabled=result.components<3;$('popDims').value=state.popView.dims;
    if(result.components<3)$('popDims').value='2'; state.popView.time=state.popView.time||'0';
    $('popTime').max=result.times.length-1;$('popTime').value=Math.min(Number(state.popView.time),result.times.length-1);
    drawTrajectory(result);drawTimecourses(result);drawLoadings(result);drawDiagnostic(result);
    $('popDetails').textContent=JSON.stringify({diagnostics:result.diagnostics,support:result.support,model:result.model,provenance:result.provenance},null,2);
    annotationSummary('population',result);updateResultState('population');
    if(!result.diagnostics.converged)notice(result.diagnostics.warnings.join('; '),true);
  }
  function updateSharedSummary() {
    for(const kind of ['unit','population']){const el=$(kind==='unit'?'draftSummary':'popDraftSummary');if(el)el.textContent=`${kind==='unit'?`Unit ${$('unitSelect').value}`:`${state.roster.size} neurons · ${$('popMethod').value.toUpperCase()}`} · ${$(inputId(kind,'alignment')).value} · ${$(inputId(kind,'pre')).value} to ${$(inputId(kind,'post')).value} s · ${$(inputId(kind,'stability')).value}`;}
    if(!$('sharedSummary'))return;
    $('sharedSummary').textContent=`Unit and Population are independent drafts. Unit: ${$('alignment').value||'Choose alignment'} · ${$('pre').value} to ${$('post').value} s. Population: ${$('popAlignment')?.value||'Choose alignment'} · ${$('popPre')?.value||'—'} to ${$('popPost')?.value||'—'} s.`;
  }
  function switchView(view) {
    state.view=view;$('unitView').hidden=view!=='unit';$('populationView').hidden=view!=='population';
    for(const name of ['unit','population']){$(`${name}Tab`).classList.toggle('active',name===view);$(`${name}Tab`).setAttribute('aria-selected',String(name===view));}
    const result=state.results[view];if(result)view==='unit'?renderUnit(result):renderPopulation(result);
  }
  const presets={
    world:{label:'World PP / PM / MM',help:'All eligible events, grouped by recorded task world.'},
    prey315:{label:'touched prey PP vs PM',unit:315,date:'2026_09_15',shared:[rule('bar',false),rule('role','prey'),rule('action','touch')],a:[rule('world','PP')],b:[rule('world','PM')],names:['PP','PM'],help:'Non-bar touched prey. World and observed strategy remain distinct fields.'},
    history315:{label:'early history',unit:315,date:'2026_09_15',shared:[rule('bar',false),rule('role','prey'),rule('action','touch')],a:[rule('world','PP')],b:[rule('world','PM')],names:['PP','PM'],facet:'previous_role',pre:-3,post:1,window:[-2.5,-1.5],help:'Earlier pre-outcome counts, faceted by previous resolved object role. Missing history has its own facet.'},
    miss315:{label:'missed prey before next outcome',unit:315,date:'2026_09_15',shared:[rule('bar',false),rule('outcome','prey_miss')],a:[rule('world','PP')],b:[rule('world','PM')],names:['PP','PM'],gate:'before_next_outcome',window:[0,.5],help:'Whole count interval must end before the next actual outcome; missing endpoints are excluded.'},
    role893:{label:'touched predator vs prey within PM',unit:893,date:'2026_09_15',shared:[rule('bar',false),rule('world','PM'),rule('action','touch')],a:[rule('role','predator')],b:[rule('role','prey')],names:['Predator touch','Prey touch'],strata:'trial',help:'Restrict to trials containing both cohorts. History is not automatically a nuisance variable.'},
    error893:{label:'PM trial error state',unit:893,date:'2026_09_15',shared:[rule('world','PM')],a:[rule('trial_error_free',true)],b:[rule('trial_has_predator_touch',true)],names:['Error-free','Predator touch'],align:'trial_initiation',help:'Retrospective observed trial state. Miss-only trials are excluded from both cohorts.'},
    mm218:{label:'MM vs other strategy before initiation',unit:218,date:'2026_09_15',a:[rule('intention','MM')],b:[rule('intention',['PP','PM'],'in')],names:['Observed MM','Other decided'],align:'trial_initiation',pre:-1,post:1,window:[-.75,0],help:'Pre-initiation firing by eventual observed strategy. This is descriptive; no decoder or automatic covariate adjustment runs.'},
    role666:{label:'role, world and correctness',unit:666,date:'2026_09_02',shared:[rule('bar',false)],world:true,facet:'role',split:'correct',help:'Role facets, world hues, solid correct/dashed incorrect, correct rows first.'},
    switch716:{label:'preswitch specification',unit:716,date:'2026_09_04',a:[rule('pre_switch_position',-1)],b:[rule('pre_switch_position',0)],names:['Before switch','Stay'],align:'trial_display_end',help:'Blocked until a declared preswitch/NA-bridge derivation is implemented. No nearby event or unit is substituted.'}
  };
  async function applyPreset(key) {
    const p=presets[key];if(!p)return;
    state.blockedPresetReason='The requested preset has not loaded successfully.';
    invalidate('unit','preset changed');

    const r=defaultRecipe();r.shared.rules=clone(p.shared||[]);
    if(p.a)r.cohorts=[cohort('A',p.names[0],clone(p.a)),cohort('B',p.names[1],clone(p.b))];
    r.facet=p.facet||'none';r.split_by=p.split||'none';r.strata=p.strata||'none';r.gate=p.gate||'none';
    state.recipes.unit=r;fillRecipeControls('unit');
    const align=p.align||'object_outcome';
    if(!state.session?.alignments.includes(align)){notice(`Alignment ${align} is unavailable in this session.`,true);return;}
    $('alignment').value=align;$('pre').value=p.pre??-.8;$('post').value=p.post??.8;
    $('countLo').value=(p.window||[0,.5])[0];$('countHi').value=(p.window||[0,.5])[1];$('unitTest').value='none';
    $('presetHelp').textContent=p.help;invalidate('unit','preset changed');
    state.blockedPresetReason=null;
    if(key==='switch716')notice(p.help,true);else notice('Preset loaded. Edit the recipe or compute the current unit.');
  }
  function installControls() {
    const makeSearch=(id,host)=>{if(!host||!host.parentElement)return;const label=document.createElement('label');label.className='field';label.innerHTML=`<span>Search fields</span><input id="${id}" type="search" placeholder="world, outcome, history…" autocomplete="off">`;host.parentElement.insertBefore(label,host);};
    makeSearch('conditionSearch',$('recipeBuilder')); makeSearch('popConditionSearch',$('popRecipeBuilder'));
    const bins=(id,host)=>{if(!host||!host.parentElement)return;const box=document.createElement('div');box.id=id;box.className='group-bins';host.parentElement.append(box);}; bins('groupBins',$('recipeBuilder')); bins('popGroupBins',$('popRecipeBuilder'));
    const summary=document.createElement('p');summary.id='setupSummary';summary.className='notice';summary.hidden=true;$('app').insertBefore(summary,$('unitView'));
    const filters=document.createElement('div');filters.className='grid2';filters.innerHTML='<label class="field"><span>Area</span><select id="rosterArea"><option value="">All areas</option></select></label><label class="field"><span>Quality</span><select id="rosterQuality"><option value="">All qualities</option></select></label>';$('rosterFilter').parentElement.after(filters);
    for(const kind of ['unit','population']){
      const view=$(kind==='unit'?'unitView':'populationView'),workspace=view.querySelector('.workspace'),bar=document.createElement('section');bar.className='compute-bar panel';
      bar.innerHTML=`<div><strong id="${kind==='unit'?'resultState':'popResultState'}">No completed result</strong><p id="${kind==='unit'?'draftSummary':'popDraftSummary'}" class="help"></p></div><button id="${kind==='unit'?'runUnitNear':'runPopulationNear'}" class="button primary" type="button">Compute ${kind==='unit'?'unit result':'population'}</button>`;workspace.prepend(bar);bar.querySelector('button').onclick=()=>run(kind);
      if(kind==='unit') {
        const annotations=document.createElement('div');annotations.id='annotationStatus';annotations.hidden=true;
        $('raster').closest('.plot-card').append(annotations);
      } else {
        const annotations=document.createElement('section');annotations.className='annotation-report panel';annotations.innerHTML='<canvas id="popAnnotationPlot" hidden aria-label="Pooled annotation distributions"></canvas><div id="popAnnotationStatus"></div>';workspace.append(annotations);
      }
      const groupOptions=view.querySelector('.recipe-options'),advanced=document.createElement('details');advanced.className='advanced';advanced.innerHTML='<summary>Grouping and support policies</summary><p class="help">Separate panels, curve groups and subdivisions partition selected events; they do not add events. Numeric fields require explicit bins.</p>';groupOptions.before(advanced);advanced.append(groupOptions,$(kind==='unit'?'groupBins':'popGroupBins'));
      const sidebar=view.querySelector('.sidebar'),shell=document.createElement('details');shell.className='settings-shell';shell.open=window.innerWidth>900;shell.innerHTML='<summary>Analysis settings · edit draft</summary>';sidebar.before(shell);shell.append(sidebar);
    }
    const significance=document.createElement('details');significance.className='advanced';significance.innerHTML='<summary>Significance design (optional)</summary>';const test=$('unitTest').parentElement;test.before(significance);significance.append(test,test.nextElementSibling);const reasons=document.createElement('p');reasons.id='testEligibility';reasons.className='help';significance.append(reasons);
    const section=document.createElement('section');section.innerHTML='<h2>Question template</h2><label class="field"><span>Starting recipe</span><select id="preset"></select></label><p class="help preset-help" id="presetHelp">Editable questions for the current session and unit; applying a template never changes either.</p>';
    $('unitView').querySelector('.sidebar').prepend(section);options($('preset'),Object.entries(presets).map(([key,p])=>[key,p.label]),'world');
    $('preset').onchange=e=>applyPreset(e.target.value);
    const annotation=document.createElement('section'); annotation.innerHTML='<h2>Plot annotations</h2><p class="help">Display-only layers; numerical support is unchanged.</p><div id="popAnnotations"></div><button id="addPopAnnotation" type="button" class="text-button">+ add annotation</button>'; $('populationView').querySelector('.sidebar').append(annotation);
    const preview=document.createElement('div'); preview.id='popPreview'; preview.setAttribute('aria-live','polite'); preview.innerHTML='<strong>Selection preview</strong><span>Choose an explicit roster.</span>'; $('populationView').querySelector('.compute-bar').append(preview);$('unitView').querySelector('.compute-bar').append($('unitPreview'));
  }
  function setupSnapshot(kind) {
    const base=requestBase(kind), w=ws(kind);
    return {settings:{...base,...(kind==='unit'?{unit_id:Number($('unitSelect').value),test:$('unitTest').value}:{})}, recipe:clone(base.recipe), annotations:clone(w.annotations), roster:kind==='population'?[...state.roster]:[], model:kind==='population'?{method:$('popMethod').value,scaling:$('popScaling').value,components:Number($('popComponents').value),dims:$('popDims').value||state.popView.dims,x:$('popX').value||state.popView.x,y:$('popY').value||state.popView.y,z:String(Math.min(Number($('popZ').value||state.popView.z),Number($('popComponents').value)-1)),loading:$('loadingComponent').value||state.popView.loading,time:$('popTime').value||state.popView.time,yaw:state.yaw,pitch:state.pitch}:null};
  }
  function downloadJson(payload, filename) { const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}), a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=filename; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000); }
  function validateSetup(imported) {
    if(imported?.schema===1)throw Error('Legacy files lack a complete source-bound setup. Use Import conditions only, then review the remaining settings.');
    if(imported?.schema!==2||!['unit','population'].includes(imported.workspace)||!imported.setup)throw Error('Not a complete electro_gui analysis setup.');
    if(!state.session)throw Error('Load the target session before applying a setup.');
    if(imported.session_id!==state.session.session_id)throw Error(`Setup targets ${imported.session_id}; select and load that exact session first.`);
    if(!imported.source?.sha256||imported.source.sha256!==state.session.source.sha256)throw Error('Setup source fingerprint differs or is missing. Load the exact source before applying it.');
    const kind=imported.workspace,snap=clone(imported.setup),settings=snap.settings,r=snap.recipe;
    if(kind!==state.view)throw Error(`Switch to the ${kind==='unit'?'Unit':'Population'} workspace before loading this setup.`);
    if(!settings||!r?.shared||!Array.isArray(r.shared.rules)||!Array.isArray(r.cohorts)||r.cohorts.some(c=>!Array.isArray(c.rules))||!Array.isArray(snap.annotations))throw Error('Setup is incomplete; no controls were changed.');
    if(!state.session.alignments.includes(settings.alignment)||!['verified_stable','all_complete'].includes(settings.stability))throw Error('Unknown alignment or eligibility policy.');
    const nums=[settings.pre,settings.post,settings.bin,settings.sigma,...(settings.count_window||[])];
    if(nums.length!==6||nums.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw Error('Window settings require six finite numeric values.');
    const [pre,post,bin,sigma,lo,hi]=nums;
    if(!(pre<post&&pre>=-10&&post<=10&&pre<=lo&&lo<hi&&hi<=post&&[.025,.05,.1].includes(bin)&&sigma>=0&&sigma<=.1&&Math.abs((post-pre)/bin-Math.round((post-pre)/bin))<1e-6))throw Error('Invalid display/count window, bin width or smoothing.');
    for(const g of [r.shared,...r.cohorts]){if(!['all','any'].includes(g.mode))throw Error('Unknown condition mode.');for(const c of g.rules){const f=state.fields.get(c.field),error=fieldError(f,c);if(error||!operatorsFor(f).some(([op])=>op===c.op))throw Error(`${c.field}: ${error||'unsupported operator'}`);}}
    for(const [key,special] of [['facet','none'],['group_by','cohort'],['split_by','none']]){const f=state.fields.get(r[key]);if(r[key]!==special&&(!f||f.availability==='unavailable'))throw Error(`Unavailable grouping field ${r[key]}.`);if(f?.type==='number'){const edges=r.group_bins?.[r[key]];if(!Array.isArray(edges)||edges.length<2||edges.some((v,i)=>typeof v!=='number'||!Number.isFinite(v)||(i&&v<=edges[i-1])))throw Error(`Invalid numeric bins for ${r[key]}.`);}}
    if(!['exclude','allow'].includes(r.overlap)||!['none','trial','world'].includes(r.strata)||!['none','before_next_outcome','before_trial_end'].includes(r.gate))throw Error('Unknown selection policy.');
    const ae=annotationError(snap.annotations);if(ae)throw Error(ae);
    const layerIds=new Set();for(const a of snap.annotations){if(!a.id||layerIds.has(a.id)||!['reference','event','interval'].includes(a.kind)||!/^#[0-9a-f]{6}$/i.test(a.color||''))throw Error('Invalid annotation identity, kind or color.');layerIds.add(a.id);if(a.kind!=='reference'){if(a.source!=='recorded_events'||!['same_trial','same_object'].includes(a.match)||!['first','last','all'].includes(a.occurrence))throw Error('Unknown annotation source/matching policy.');for(const key of a.kind==='event'?['event']:['onset','offset'])if(!state.session.alignments.includes(a[key])||a[key]==='object_outcome')throw Error(`Unknown recorded event ${a[key]}.`);}}
    if(kind==='unit'){if(!state.units.some(u=>u.id===settings.unit_id)||!['none','paired_permutation','block_permutation'].includes(settings.test))throw Error('Unknown unit or significance design.');}
    else {const m=snap.model,ids=snap.roster;if(!m||!Array.isArray(ids)||new Set(ids).size!==ids.length||ids.some(id=>!state.units.some(u=>u.id===id)))throw Error('Population setup requires a complete model and explicit valid roster.');if(!['pca','ica','fa'].includes(m.method)||!['center','zscore'].includes(m.scaling)||!Number.isInteger(m.components)||m.components<2||m.components>10)throw Error('Invalid population model settings.');for(const key of ['x','y','z','loading'])if(m[key]==null||m[key]===''||!Number.isInteger(Number(m[key]))||Number(m[key])<0||Number(m[key])>=m.components)throw Error('Invalid saved component view.');if(!['2','3'].includes(String(m.dims))||Number(m.dims)>m.components||Number(m.x)===Number(m.y)||!Number.isFinite(Number(m.time))||Number(m.time)<0||![m.yaw,m.pitch].every(Number.isFinite))throw Error('Invalid population display settings.');}
    return {kind,snap};
  }
  function applySetup(imported) {
    const {kind,snap}=validateSetup(imported),settings=snap.settings;
    state.recipes[kind]=snap.recipe;fillRecipeControls(kind);ws(kind).annotations=snap.annotations;renderAnnotations(kind);
    $(kind==='unit'?'alignmentSearch':'popAlignmentSearch').value='';fillAlignments(kind,settings.alignment);
    for(const name of ['stability','pre','post','bin','sigma'])$(inputId(kind,name)).value=settings[name];
    $(inputId(kind,'countLo')).value=settings.count_window[0];$(inputId(kind,'countHi')).value=settings.count_window[1];
    if(kind==='unit'){$('unitSearch').value='';renderUnits();$('unitSelect').value=settings.unit_id;$('unitTest').value=settings.test;state.blockedPresetReason=null;}
    else {const m=snap.model;state.roster=new Set(snap.roster);$('popMethod').value=m.method;$('popScaling').value=m.scaling;$('popComponents').value=m.components;state.popView={dims:String(m.dims),x:String(m.x),y:String(m.y),z:String(m.z),loading:String(m.loading),time:String(m.time)};state.yaw=m.yaw;state.pitch=m.pitch;for(const [id,key] of [['popX','x'],['popY','y'],['popZ','z'],['loadingComponent','loading']])options($(id),Array.from({length:m.components},(_,i)=>[i,`Component ${i+1}`]),m[key]);$('popDims').value=m.dims;renderRoster();}
    invalidate(kind,'setup restored');
    // Existing completed plots keep their own model; the imported view is used on Compute.
    const summary=`${kind==='unit'?`Unit ${settings.unit_id}`:`${snap.roster.length} neurons · ${snap.model.method.toUpperCase()} · ${snap.model.components} components`} · ${settings.alignment} · display [${settings.pre}, ${settings.post}] s · counts [${settings.count_window.join(', ')}] s · ${settings.stability} · ${snap.recipe.cohorts.length} comparison groups · ${snap.annotations.length} annotation layers`;
    $('setupSummary').textContent=`Restored setup: ${summary}. Review the support preview, then Compute.`;$('setupSummary').hidden=false;notice('Analysis setup restored. The summary describes the draft; existing plots retain completed settings.');
  }
  function bind() {
    $('sessionSelect').onchange=e=>{state.blockedPresetReason=null;loadSession(e.target.value);};
    $('loadSession').onclick=()=>loadSession($('sessionSelect').value);
    $('unitSearch').oninput=renderUnits;$('unitSelect').onchange=()=>{state.blockedPresetReason=null;invalidate('unit','unit changed');};
    $('unitTab').onclick=()=>switchView('unit');$('populationTab').onclick=()=>switchView('population');
    $('runUnit').onclick=()=>run('unit');$('runPopulation').onclick=()=>run('population');
    const unitIds=['pre','post','bin','sigma','countLo','countHi','alignment','stability','unitTest','recipeEnabled','facet','groupBy','splitBy','overlap','strata','gate'];
    const popIds=['popPre','popPost','popBin','popSigma','popCountLo','popCountHi','popAlignment','popStability','popRecipeEnabled','popFacet','popGroupBy','popSplitBy','popOverlap','popStrata','popGate','popMethod','popScaling','popComponents'];
    for(const id of unitIds)$(id).addEventListener('input',()=>invalidate('unit'));
    for(const id of popIds)$(id).addEventListener('input',()=>invalidate('population'));
    for(const id of ['facet','groupBy','splitBy','popFacet','popGroupBy','popSplitBy'])$(id).addEventListener('change',()=>{const kind=id.startsWith('pop')?'population':'unit';updateGroupBins(kind);});
    $('alignmentSearch').oninput=()=>fillAlignments('unit',$('alignment').value); $('popAlignmentSearch').oninput=()=>fillAlignments('population',$('popAlignment').value);
    $('conditionSearch').oninput=()=>renderRecipe('unit'); $('popConditionSearch').oninput=()=>renderRecipe('population');
    $('alignment').onchange=()=>{fillAlignments('unit',$('alignment').value);invalidate('unit')}; $('popAlignment').onchange=()=>{fillAlignments('population',$('popAlignment').value);invalidate('population')};
    $('resetRecipe').onclick=()=>{state.blockedPresetReason=null;state.recipes.unit=defaultRecipe();fillRecipeControls('unit');$('preset').value='world';invalidate('unit');};
    $('popResetRecipe').onclick=()=>{state.recipes.population=defaultRecipe();fillRecipeControls('population');invalidate('population');};
    $('rosterFilter').oninput=renderRoster;$('rosterArea').onchange=renderRoster;$('rosterQuality').onchange=renderRoster;
    $('rosterSelectedOnly').onchange=renderRoster;
    $('replaceRoster').onclick=()=>{state.roster=new Set(filteredRoster().map(u=>u.id));renderRoster();invalidate('population');};
    $('addRoster').onclick=()=>{filteredRoster().forEach(u=>state.roster.add(u.id));renderRoster();invalidate('population');};
    $('stableRoster').onclick=selectStableRoster;
    $('clearRoster').onclick=()=>{state.roster.clear();renderRoster();invalidate('population');};
    $('copyUnitSettings').onclick=()=>{for(const base of ['Alignment','Stability','Pre','Post','Bin','Sigma','CountLo','CountHi'])$(`pop${base}`).value=$(`${base[0].toLowerCase()+base.slice(1)}`).value;state.recipes.population=clone(recipeFromUI('unit'));fillRecipeControls('population');ws('population').annotations=clone(ws('unit').annotations);renderAnnotations('population');invalidate('population','copied Unit snapshot');notice('Copied the current Unit settings into an independent Population draft.');};
    $('addAnnotation').onclick=()=>{ws('unit').annotations.push({id:`annotation_${Date.now()}`,kind:'reference',name:'Reference line',visible:true,color:'#225f72',time:0,source:'recorded_events',match:'same_trial',occurrence:'all'});renderAnnotations('unit');scheduleAnnotation('unit');};
    $('addPopAnnotation').onclick=()=>{ws('population').annotations.push({id:`annotation_${Date.now()}`,kind:'reference',name:'Reference line',visible:true,color:'#225f72',time:0,source:'recorded_events',match:'same_trial',occurrence:'all'});renderAnnotations('population');scheduleAnnotation('population');};
    for(const id of ['popX','popY','popZ','popDims','loadingComponent'])$(id).onchange=()=>{
      state.popView={...state.popView,dims:$('popDims').value,x:$('popX').value,y:$('popY').value,z:$('popZ').value,loading:$('loadingComponent').value};
      const r=state.results.population;if(!r)return;
      if($('popX').value===$('popY').value){$('popY').value=String((Number($('popX').value)+1)%r.components);}
      if($('popDims').value==='3'&&[$('popX').value,$('popY').value].includes($('popZ').value))$('popZ').value=String(Array.from({length:r.components},(_,i)=>i).find(i=>![Number($('popX').value),Number($('popY').value)].includes(i)));
      state.popView={...state.popView,dims:$('popDims').value,x:$('popX').value,y:$('popY').value,z:$('popZ').value,loading:$('loadingComponent').value};drawTrajectory(r);drawTimecourses(r);drawLoadings(r);
    };
    $('popTime').oninput=()=>{state.popView.time=$('popTime').value;const r=state.results.population;if(r){drawTrajectory(r);drawTimecourses(r);}};
    let drag=null;
    $('trajectory').onpointerdown=e=>{if($('popDims').value==='3'){drag=[e.clientX,e.clientY];e.target.setPointerCapture(e.pointerId);}};
    $('trajectory').onpointermove=e=>{if(drag&&state.results.population){state.yaw+=(e.clientX-drag[0])*.01;state.pitch+=(e.clientY-drag[1])*.01;drag=[e.clientX,e.clientY];drawTrajectory(state.results.population);}};
    $('trajectory').onpointerup=()=>{drag=null;};
    $('themeToggle').onclick=()=>{document.documentElement.classList.toggle('dark');$('themeToggle').textContent=document.documentElement.classList.contains('dark')?'Light mode':'Dark mode';switchView(state.view);};
    document.querySelectorAll('.subtab').forEach(button=>button.onclick=()=>{document.querySelectorAll('.subtab').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.subpanel').forEach(p=>p.hidden=p.id!==button.dataset.panel);});
    document.querySelectorAll('.export,.pop-export').forEach(button=>button.onclick=()=>{
      if(!button.dataset.job)return;
      const link=document.createElement('a');link.href=`/api/jobs/${button.dataset.job}/export?format=${button.dataset.format}&x=${$('popX').value||0}&y=${$('popY').value||1}`;link.download='';link.click();
    });
    $('saveSetup').onclick=()=>{try{const payload={schema:2,workspace:state.view,source:state.session?.source,session_id:state.session?.session_id,setup:setupSnapshot(state.view)};downloadJson(payload,`electro_gui_${state.view}_analysis_setup.json`);notice(`${state.view === 'unit' ? 'Unit' : 'Population'} setup saved.`);}catch(error){notice(error.message,true);}};
    $('loadSetup').onchange=async e=>{try{const imported=JSON.parse(await e.target.files[0].text());applySetup(imported);}catch(error){notice(`Setup not applied: ${error.message}`,true);}finally{e.target.value='';}};
    $('importRecipe').onchange=async e=>{
      try{const imported=JSON.parse(await e.target.files[0].text()),r=imported.setup?.recipe||imported.recipe||imported;if(!r.shared||!Array.isArray(r.shared.rules)||!Array.isArray(r.cohorts)||r.cohorts.some(c=>!Array.isArray(c.rules)))throw Error('A recipe requires shared rules and cohort rule arrays.');state.recipes[state.view]=r;fillRecipeControls(state.view);invalidate(state.view,'conditions imported');notice('Conditions imported only; alignment, windows, roster, model, and annotations were retained.');}catch(error){notice(`Invalid conditions: ${error.message}`,true);}finally{e.target.value='';}
    };
    window.addEventListener('resize',()=>{const r=state.results[state.view];if(r)state.view==='unit'?renderUnit(r):renderPopulation(r);});
  }
  async function start() {
    state.recipes={unit:defaultRecipe(),population:defaultRecipe()};installControls();bind();
    // The raster explorer links here as #view=population&session=<id>.
    const linked=new URLSearchParams(location.hash.slice(1));if(linked.get('view')==='population')switchView('population');
    try{const catalog=await api('/api/catalog');state.sessions=catalog.sessions;
      const first=catalog.sessions.some(s=>s.id===linked.get('session'))?linked.get('session'):catalog.default_session;
      options($('sessionSelect'),catalog.sessions.map(s=>s.id),first);$('footerVersion').textContent=`electro_gui ${catalog.version}`;
      if(catalog.sessions.length)await loadSession(first);else notice('No assembled sessions found. Launch with --session-file or --data-root, or mount T7/Transfer.',true);
    }catch(error){notice(error.message,true);}
  }
  start();
})();
