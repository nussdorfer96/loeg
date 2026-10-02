// Mobile nav, sortable tables, lore filters. No dependencies.
document.addEventListener('DOMContentLoaded',()=>{
  // Wide tables: sticky first column + swipe hint on phones
  document.querySelectorAll('.tbl-wrap').forEach(w=>{
    const t=w.querySelector('table');if(!t||t.classList.contains('matrix'))return;
    t.classList.add('sticky1');
    if(w.scrollWidth>w.clientWidth+8){const h=document.createElement('div');h.className='scroll-hint';h.textContent='← swipe table →';w.parentNode.insertBefore(h,w);}
  });
  document.querySelectorAll('table.sortable').forEach(t=>{
    t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
      const tb=t.tBodies[0],rows=[...tb.rows],asc=th.dataset.dir!=='asc';
      t.querySelectorAll('th').forEach(x=>delete x.dataset.dir);th.dataset.dir=asc?'asc':'desc';
      const v=r=>{const c=r.cells[i];const s=(c.dataset.v??c.textContent).trim();const f=parseFloat(s.replace(/[,%]/g,''));return isNaN(f)?s.toLowerCase():f};
      rows.sort((a,b)=>{const x=v(a),y=v(b);return (x>y?1:x<y?-1:0)*(asc?1:-1)});rows.forEach(r=>tb.appendChild(r));
    }));
  });
  document.querySelectorAll('.filters').forEach(f=>{
    const items=document.querySelectorAll(f.dataset.target);
    f.addEventListener('click',e=>{
      if(e.target.tagName!=='BUTTON')return;
      f.querySelectorAll('button').forEach(x=>x.classList.remove('on'));e.target.classList.add('on');
      const k=e.target.dataset.k;items.forEach(it=>{it.style.display=(k==='all'||it.dataset.k.split(' ').includes(k))?'':'none'});
    });
  });
});

// race charts: tap a legend name to spotlight one manager
document.querySelectorAll('.race').forEach(function(r){
  r.querySelectorAll('.legend button').forEach(function(b){
    b.addEventListener('click',function(){
      var m=b.dataset.m, on=b.classList.contains('on');
      r.querySelectorAll('.on').forEach(function(x){x.classList.remove('on');});
      if(on){r.classList.remove('sel');return;}
      r.classList.add('sel'); b.classList.add('on');
      r.querySelectorAll('[data-m="'+m+'"]').forEach(function(x){x.classList.add('on');});
      var ln=r.querySelector('polyline[data-m="'+m+'"]'); if(ln) ln.parentNode.appendChild(ln);
    });
  });
});
// keep the active sub-tab visible on narrow screens
(function(){var a=document.querySelector('.subnav a.on');if(a&&a.parentNode.scrollWidth>a.parentNode.clientWidth){a.parentNode.scrollLeft=a.offsetLeft-16;}})();
// Lore: collapsible entries; deep links (#id) auto-expand and scroll
(function(){
  if(!document.querySelector('details.lx'))return;
  function reveal(id,scroll){
    if(!id)return;var el=document.getElementById(id);if(!el)return;
    var d=el.tagName==='DETAILS'?el:el.closest('details');
    while(d){d.open=true;d=d.parentElement&&d.parentElement.closest('details');}
    var t=el.tagName==='DETAILS'?el:(el.closest('details.lx')||el);
    if(scroll)requestAnimationFrame(function(){t.scrollIntoView({block:'start',behavior:'instant'});});
  }
  function fromHash(){try{reveal(decodeURIComponent(location.hash.slice(1)),true);}catch(e){}}
  fromHash();window.addEventListener('hashchange',fromHash);window.addEventListener('load',fromHash,{once:true});
  document.addEventListener('click',function(e){
    var a=e.target.closest&&e.target.closest('a[href^="#"]');if(a){var id=decodeURIComponent(a.getAttribute('href').slice(1));if(id&&('#'+id)===location.hash)reveal(id,true);else reveal(id,false);}
    var b=e.target.closest&&e.target.closest('[data-lx]');if(b){var o=b.dataset.lx==='open';document.querySelectorAll('details.lx').forEach(function(d){d.open=o;});}
  });
})();

// Quick-jump search (managers, seasons, players); index loaded on first open
(function(){
  var btn=document.getElementById('qs-open'),box=document.getElementById('qs');if(!btn||!box)return;
  var q=document.getElementById('qs-q'),out=document.getElementById('qs-out'),root=btn.dataset.root||'',IDX=null;
  function n(s){return String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[.'’]/g,'').replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();}
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function open_(){box.hidden=false;document.documentElement.classList.add('qs-on');setTimeout(function(){q.focus();},30);
    if(!IDX)fetch(root+'static/search.json').then(function(r){return r.json();}).then(function(d){IDX=d;run();}).catch(function(){out.innerHTML='<p class="muted small">Search index unavailable.</p>';});}
  function close_(){box.hidden=true;document.documentElement.classList.remove('qs-on');}
  function score(name,extra,v){var a=n(name),i=a.indexOf(v);if(i===0)return 0;if(i>0)return a.charAt(i-1)===' '?1:2;if(extra&&n(extra).indexOf(v)>=0)return 3;return -1;}
  function run(){var v=n(q.value);if(!IDX)return;if(v.length<1){out.innerHTML='<p class="muted small">Try “Brian”, “2024” or “Josh Allen”.</p>';return;}
    var groups=[['Managers','m','👥'],['Seasons','s','📅'],['Players','p','🏈']],html='';
    groups.forEach(function(g){var rows=(IDX[g[1]]||[]).map(function(r){var sc=score(r[0],g[1]==='p'?'':r[2],v);return [sc,r];}).filter(function(x){return x[0]>=0&&(g[1]!=='p'||v.length>=2);})
      .sort(function(a,b){return a[0]-b[0]||a[1][0].length-b[1][0].length;}).slice(0,g[1]==='p'?8:6);
      if(!rows.length)return;html+='<div class="qs-h">'+g[0]+'</div>';
      rows.forEach(function(x){var r=x[1],href=g[1]==='p'?root+'tracker.html?q='+encodeURIComponent(r[0]):root+r[1],sub=g[1]==='p'?r[1]+' · league history':(r[3]||r[2]);
        html+='<a class="qs-item" href="'+href+'"><span class="qs-i">'+g[2]+'</span><span><b>'+esc(r[0])+'</b><br><span class="muted small">'+esc(sub)+'</span></span></a>';});});
    out.innerHTML=html||'<p class="muted small">No matches.</p>';}
  btn.addEventListener('click',open_);document.getElementById('qs-close').addEventListener('click',close_);
  box.addEventListener('click',function(e){if(e.target===box)close_();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!box.hidden)close_();if(e.key==='/'&&box.hidden&&!/input|textarea/i.test((e.target.tagName||''))){e.preventDefault();open_();}});
  q.addEventListener('input',run);
  q.addEventListener('keydown',function(e){if(e.key==='Enter'){var a=out.querySelector('a.qs-item');if(a){location.href=a.href;}}});
})();

// Draft Order Games: let an inline video grow from the Lore-photo-size poster to its own shape while playing
document.addEventListener('play',function(e){var v=e.target;if(v&&v.classList&&v.classList.contains('dog-vid'))v.classList.add('playing');},true);
