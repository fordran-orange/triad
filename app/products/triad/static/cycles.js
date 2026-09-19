"use strict";
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const date=value=>value?new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'long'}):'Not recorded';
let cycles=[];
function render(){
 const root=document.querySelector('#cycles');root.replaceChildren();const filter=document.querySelector('#filter').value;
 for(const c of cycles.filter(c=>filter==='ALL'||c.execution_mode===filter||c.status===filter)){
  const card=node('article');card.append(node('h2',c.cycle_type==='PRODUCT_BUILD'?'Product build cycle':'Improvement rotation'));
  card.append(node('span',c.status,'badge'),node('span',c.execution_mode,'badge'),node('p',date(c.created_at),'muted'));
  const proposal=c.selected_proposal;card.append(node('p',proposal?.problem||proposal?.title||proposal?.summary||'No selected proposal recorded'));
  const values=[['Agents',c.agents_run.join(', ')||'No provider run recorded'],['Builder',[...new Set(c.implementation_runs.map(r=>r.builder).filter(Boolean))].join(', ')||'None recorded'],['Independent QA',c.qa_runs.map(r=>r.qa_agent||r.decision).filter(Boolean).join(', ')||'None recorded'],['Merge',c.merge_commit?c.merge_commit.slice(0,12):'No merge recorded'],['Duration',c.started_at&&c.finished_at?Math.max(0,(new Date(c.finished_at)-new Date(c.started_at))/1000).toFixed(1)+' seconds':'Not recorded'],['Billing',c.billing_sources.join(', ')||'No usage recorded'],['Quality debt',c.quality_debt.length?c.quality_debt.map(d=>d.resolutions?.length?'Resolution recorded':d.status||'Open').join(', '):'None recorded']];
  const dl=node('dl');for(const [key,value]of values)dl.append(node('dt',key),node('dd',value));card.append(dl);
  if(c.failures.length)card.append(node('p',c.failures.map(f=>f.code||'Recorded failure').join(' · '),'warning'));
  if(c.recovered_by_cycle_id)card.append(node('p','Recovery cycle: '+c.recovered_by_cycle_id));
  if(c.recovery_action)card.append(node('p',c.recovery_action));
  const inspect=node('button','Inspect cycle evidence');inspect.onclick=()=>{document.querySelector('#body').replaceChildren(TriadRecord.render(c));document.querySelector('#detail').showModal()};card.append(inspect);root.append(card);
 }
 if(!root.children.length)root.append(node('p','No cycles match this view.','empty'));
}
document.querySelector('#filter').onchange=render;document.querySelector('#close').onclick=()=>document.querySelector('#detail').close();
fetch('/triad/api/cycles').then(async r=>{if(!r.ok)throw Error('Cycle history is unavailable.');return r.json()}).then(data=>{cycles=data.cycles;render()}).catch(e=>{document.querySelector('#notice').textContent=e.message;document.querySelector('#cycles').replaceChildren()});
