'use strict';
(() => {
  const $ = s => document.querySelector(s);
  let token = '', active = '', busy = false;
  const labels = {IDEA_INJECTION:'Optional idea',INFORMATION:'Information',OBSERVATION:'Observation',WORK_REQUEST:'Work request',COMMAND:'Explicit operator command'};
  const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; };
  const notice = text => { $('#notice').textContent=text; };
  async function api(path, body) {
    if(!token)throw new Error('Unlock this private workspace first.');
    const r=await fetch(path,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const data=await r.json();
    if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Core could not complete the request. Check the saved status and try again.');
    return data;
  }
  function renderMessages(rows) {
    $('#messages').replaceChildren();
    for(const m of rows){const box=el('article',undefined,'message');box.append(el('strong',m.role==='user'?'You':m.role==='error'?'Reply unavailable':'Core'),el('p',m.content,m.role==='error'?'error':''));if(m.provenance){const p=m.provenance;box.append(el('p',p.provider+' · '+p.model+' · '+p.transport+' · '+p.billing_source,'provenance'),el('p','Input: '+p.input_tokens+' tokens · Output: '+p.output_tokens+' tokens','provenance'));if(p.intake_ids.length)box.append(el('p','Intake references: '+p.intake_ids.join(', '),'provenance'));}$('#messages').append(box);}$('#messages').scrollTop=$('#messages').scrollHeight;
  }
  async function histories(){const rows=await api('/api/core/conversations');$('#history').replaceChildren(el('option','New conversation'));$('#history').firstChild.value='';for(const r of [...rows].reverse()){const n=el('option',r.provider+' · '+new Date(r.created_at).toLocaleString());n.value=r.id;$('#history').append(n);}$('#history').value=active;}
  async function loadConversation(){if(!active){renderMessages([]);$('#provider').disabled=false;return;}const data=await api('/api/core/conversations/'+encodeURIComponent(active));$('#provider').value=data.conversation.provider;$('#provider').disabled=true;renderMessages(data.messages);}
  async function intake(){const rows=await api('/api/core/intake?destination='+encodeURIComponent($('#destination').value));$('#intakeRecords').replaceChildren();for(const r of [...rows].reverse()){const box=el('article',undefined,'idea'),state=r.disposition?.status||r.status;box.append(el('strong',labels[r.effective_type]+' · '+state.toLowerCase().replaceAll('_',' ')),el('p',r.content),el('p',r.source_identity+' · '+new Date(r.received_at).toLocaleString()+' · '+(r.obligation==='NONE'?'No obligation':'Recorded request; not executed'),'provenance'),el('p','Reference: '+r.id,'provenance'));const actions=state==='NEW'?['CONSIDERING']:state==='CONSIDERING'?['USED','DEFERRED','REJECTED']:state==='DEFERRED'?['CONSIDERING']:[];if(r.effective_type==='IDEA_INJECTION')for(const status of actions){const b=el('button',status==='CONSIDERING'?'Consider':status==='USED'?'Mark used':status==='DEFERRED'?'Defer':'Reject');b.onclick=async()=>{const rationale=prompt('Reason for this optional idea disposition:');if(!rationale?.trim())return;try{await api('/api/core/intake/'+encodeURIComponent(r.id)+'/disposition',{status,rationale});await intake();}catch(e){notice(e.message);}};box.append(b);}$('#intakeRecords').append(box);}}
  $('#unlock').onclick=()=>$('#auth').showModal();$('#cancel').onclick=()=>$('#auth').close();
  $('#authForm').onsubmit=async e=>{e.preventDefault();token=$('#key').value;$('#key').value='';try{await api('/api/core/intelligence/auth/validate',{});$('#auth').close();$('#unlock').textContent='Workspace unlocked';await histories();await intake();notice('Ready. Provider selection is explicit; there is no paid API fallback.');}catch(err){token='';$('#authError').textContent=err.message;}};
  $('#new').onclick=()=>{if(busy)return;active='';$('#history').value='';$('#provider').disabled=false;renderMessages([]);notice('Choose a provider and send a message to start.');};
  $('#history').onchange=async()=>{if(busy){$('#history').value=active;return;}active=$('#history').value;try{await loadConversation();}catch(e){notice(e.message);}};
  $('#chatForm').onsubmit=async e=>{e.preventDefault();if(busy)return;const content=$('#message').value.trim();if(!content)return;busy=true;$('#send').disabled=true;$('#new').disabled=true;$('#history').disabled=true;notice('The selected provider is thinking…');try{if(!active){active=(await api('/api/core/conversations',{provider:$('#provider').value})).id;await histories();}$('#provider').disabled=true;await api('/api/core/conversations/'+encodeURIComponent(active)+'/messages',{content});$('#message').value='';await loadConversation();notice('Reply saved with provider and source details.');}catch(err){notice(err.message);if(active)try{await loadConversation();}catch(_){/* Preserve the original request error. */}}finally{busy=false;$('#send').disabled=false;$('#new').disabled=false;$('#history').disabled=false;}};
  $('#intakeForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/core/intake',{content:$('#intakeText').value,destination:$('#destination').value,declared_type:$('#kind').value});$('#intakeText').value='';await intake();notice('Saved. This does not create a task or execute a command.');}catch(err){notice(err.message);}};
  $('#destination').onchange=()=>intake().catch(e=>notice(e.message));
})();
