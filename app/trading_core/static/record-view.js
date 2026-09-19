/* Shared read-only record presentation. All persisted/provider text is untrusted. */
window.TriadRecord = (() => {
  const labels = {work_item_id:'Work item ID', input_tokens:'Input tokens', output_tokens:'Output tokens',
    execution_mode:'Execution mode', git:'Git history', lineage:'Related records and evidence',
    allowed_tools:'Permitted tools', allowed_paths:'Permitted files and folders',
    compute_budget:'Per-run limits', tests_run:'Checks performed', tests_repeated:'Checks repeated',
    files_changed:'Files changed', proposed_change:'Proposed improvement',
    permission_requests:'Requested permissions', context_packet:'Context supplied to the agent',
    claims_in_conflict:'Points of disagreement', required_changes:'Changes required',
    mode:'Execution mode', estimated_cost:'Estimated API cost (USD)', duration:'Run time (seconds)',
    max_cloud_cost_day:'Daily API spending ceiling (USD)', max_tokens_day:'Optional daily token ceiling',
    max_compute_seconds_day:'Optional daily run-time ceiling (seconds)', daily_execution_caps:'Daily usage caps'};
  const priority = ['title','name','kind','status','decision','review_decision','summary','results',
    'objective','description','problem','proposed_change','reason','findings','required_changes',
    'evidence','tests_run','tests_repeated','known_issues','risks','recommended_next_step'];
  const node = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const label = key => labels[key] || key.replace(/([a-z])([A-Z])/g,'$1 $2').replaceAll('_',' ').replace(/\bid\b/gi,'ID').replace(/^./,c=>c.toUpperCase());
  const technical = key => /(^id$|_id$|_ids$|hash|checksum|digest|(^|_)commit$|^revision$|^schema|^required_output_schema$)/.test(key);
  function scalar(value,key){
    if(value===null||value===undefined)return 'Not recorded';
    if(typeof value==='boolean')return value?'Yes':'No';
    if(typeof value==='number')return value.toLocaleString(undefined,{maximumFractionDigits:20});
    if(value==='')return 'None recorded';
    if(typeof value==='string' && ['event','event_kind','kind','work_type','mode','execution_mode','allowed_tools','execution_permissions','permissions_required','rules_triggered','transport','active_transport','selected_transport','resolution_method'].includes(key) && /^[a-zA-Z][a-zA-Z_]*$/.test(value) && /[a-z]/.test(value))
      return ({ollama:'Ollama (local)',cli:'CLI (signed-in account)',api:'API'})[value] || label(value);
    if(typeof value==='string' && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:/.test(value) && !isNaN(Date.parse(value.replace(' ','T'))))
      return new Date(value.replace(' ','T')).toLocaleString(undefined,{timeZoneName:'short'});
    if(typeof value==='string' && /^[A-Z][A-Z_]+$/.test(value) && !technical(key))
      return ({REAL:'Real provider run',SIMULATED:'Simulated test',LOCAL_QWEN:'Local Qwen',NO_CHANGE_JUSTIFIED:'No change needed',NEVER:'Never',UNKNOWN:'Not yet known'})[value] || value.replaceAll('_',' ');
    return String(value);
  }
  function render(value,key='',depth=0){
    const area=node('div',undefined,'record-view');
    // Some historical fields contain serialized structured output as strings.
    if(typeof value==='string' && /^[\s]*[\[{]/.test(value)){
      try {const parsed=JSON.parse(value);if(parsed && typeof parsed==='object')value=parsed;}catch{/* Ordinary text. */}
    }
    if(value===null || typeof value!=='object'){
      area.append(node('p',scalar(value,key),'rv-text'));return area;
    }
    if(Array.isArray(value)){
      if(!value.length){area.append(node('p','None recorded','rv-empty'));return area;}
      const list=node('ol',undefined,'rv-list');
      for(const item of value){const li=node('li');li.append(render(item,key,depth+1));list.append(li);}
      area.append(list);return area;
    }
    const entries=Object.entries(value);
    if(!entries.length){area.append(node('p','No details recorded','rv-empty'));return area;}
    entries.sort(([a],[b])=>{const x=priority.indexOf(a),y=priority.indexOf(b);return (x<0?999:x)-(y<0?999:y);});
    const identifiers=node('details',undefined,'rv-identifiers');
    identifiers.append(node('summary','Record identifiers and technical details'));
    let count=0;
    for(const [field,item] of entries){
      const section=node('section',undefined,'rv-field');
      section.append(node('h3',label(field)),render(item,field,depth+1));
      if(technical(field)){identifiers.append(section);count++;}else area.append(section);
    }
    if(count)area.append(identifiers);
    return area;
  }
  return {render,label};
})();
