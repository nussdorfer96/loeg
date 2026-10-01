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
