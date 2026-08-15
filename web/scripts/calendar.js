/* ═══════════════════════════════════════════════════════════
   Kairos · calendar.js — hero / 网格 / 抽屉 / 手势
   ───────────────────────────────────────────────────────────
   性能约定（改动前必读）：
   ① 动画热路径（applyY / slide / ease / 拖拽 move）内
      禁止读取 offsetWidth / getBoundingClientRect / scrollTop
      等属性 —— 每读一次强制同步重排，必掉帧。
      所有几何量在手势开始或 resize 时测一次，缓存起来。
   ② will-change 只在动画期间由 JS 挂载，结束立即清除。
   ③ 弹簧用固定子步长积分（1/240s），掉帧也不会"顿一下"。
   ④ 松手不是 snap 到最近档，而是先按速度投影落点再选档，
      这是"甩得出去"的手感来源。
   ═══════════════════════════════════════════════════════════ */

const Cal = (() => {
  const $ = s => document.querySelector(s);
  const TAG  = () => L().tag;
  const CLS  = {appointment:"",deadline:"dl",delivery:"dv",billing:"bl",other:"ot"};
  const iso  = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;

  let TODAY = new Date();
  let T0    = iso(TODAY);
  let cur   = new Date(TODAY.getFullYear(), TODAY.getMonth(), 1);
  let sel   = T0;
  let tab   = "all";
  let EV    = [];                       // 由 Store 灌入，本模块只读

  /* ── 工具 ── */
  function money(t){
    const m=/(S\$|A\$|[¥$€£])\s?([\d,]+(?:\.\d{1,2})?)/.exec(t||"");
    return m?{c:m[1],v:parseFloat(m[2].replace(/,/g,""))}:null;
  }
  const fits = e => tab==="all" || (tab==="bill") === (e.type==="billing");
  function byDay(){
    const m={};
    EV.filter(fits).forEach(e=>{const k=e.datetime.slice(0,10);(m[k]=m[k]||[]).push(e);});
    Object.values(m).forEach(a=>a.sort((x,y)=>x.datetime.localeCompare(y.datetime)));
    return m;
  }
  function monthList(){
    const p=`${cur.getFullYear()}-${String(cur.getMonth()+1).padStart(2,"0")}`;
    return EV.filter(e=>fits(e)&&e.datetime.startsWith(p))
             .sort((a,b)=>a.datetime.localeCompare(b.datetime));
  }
  function toast(m){
    const t=$("#toast"); t.textContent=m; t.classList.add("on");
    clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("on"),1900);
  }

  /* ── Hero ── */
  function drawHero(){
    const d=new Date(sel+"T00:00");
    $("#hWd").textContent=["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"][d.getDay()];
    $("#hDate").innerHTML=`${d.getDate()}<span class="mo">${MO_EN[d.getMonth()].toUpperCase()} ${d.getFullYear()}</span>`;
    const ml=monthList(), meta=$("#hMeta");
    if(tab==="bill"){
      const s={}; ml.forEach(e=>{const v=money(e.title); if(v)s[v.c]=(s[v.c]||0)+v.v;});
      const ks=Object.keys(s);
      meta.className="heroMeta mono";
      meta.innerHTML=ks.length
        ? `${L().monthTotal}<b>${ks.map(k=>k+s[k].toFixed(2)).join("</b><b>")}</b>`
        : `${L().monthTotal}<b>0</b>`;
    }else{
      const later=ml.filter(e=>e.datetime.slice(0,10)>=T0).length;
      meta.className="heroMeta";
      meta.innerHTML=`${L().monthCount(ml.length)}<b>${later}</b>${L().upcoming}`;
    }
  }

  /* ── 网格 ── */
  function drawGrid(){
    const g=$("#grid"); g.innerHTML="";
    const y=cur.getFullYear(), m=cur.getMonth();
    const lead=(new Date(y,m,1).getDay()+6)%7;
    const start=new Date(y,m,1-lead), map=byDay();
    for(let i=0;i<42;i++){
      const d=new Date(start.getFullYear(),start.getMonth(),start.getDate()+i);
      const k=iso(d), out=d.getMonth()!==m, list=out?[]:(map[k]||[]);
      const c=document.createElement("div");
      c.className="cell"+(out?" out":"")+(k===T0?" today":"")+(k===sel?" sel":"");
      let dots=list.slice(0,3).map(e=>`<i class="dot ${CLS[e.type]}"></i>`).join("");
      if(list.length>3) dots+=`<i class="dot more"></i>`;
      c.innerHTML=`<span class="n">${d.getDate()}</span><span class="dots">${dots}</span>`;
      c.onclick=()=>{
        sel=k;
        if(out) cur=new Date(d.getFullYear(),d.getMonth(),1);
        Sheet.to(1); render();
      };
      g.appendChild(c);
    }
    $("#mLbl").innerHTML=`${L().monthOf(y,m)} <span>${y}</span>`;
  }

  /* ── 抽屉内容 ── */
  function evRow(e){
    const tm=e.datetime.length>10?e.datetime.slice(11,16):L().allDay;
    const v=e.type==="billing"?money(e.title):null;
    const past=e.datetime.slice(0,10)<T0;
    return `<div class="ev${past?" past":""}">
      <span class="bar ${CLS[e.type]}"></span>
      <span class="tm">${tm}</span>
      <span class="bd"><span class="ti">${e.title}</span></span>
      <span class="rt">${v?`<span class="amt">${v.c}${v.v.toFixed(2)}</span>`
        :`<span class="tag ${CLS[e.type]}">${TAG()[e.type]||""}</span>`}</span>
    </div>`;
  }
  function drawSheet(){
    const box=$("#sList");
    if(Sheet.idx()<2){                          // 当天
      const d=new Date(sel+"T00:00"), list=byDay()[sel]||[];
      $("#sTitle").textContent = sel===T0 ? L().today
        : L().dayTitle(d.getMonth(), d.getDate(), L().wdFull[d.getDay()]);
      let cnt=L().nItems(list.length);
      if(tab==="bill"){
        const s={}; list.forEach(e=>{const v=money(e.title); if(v)s[v.c]=(s[v.c]||0)+v.v;});
        const ks=Object.keys(s);
        if(ks.length) cnt=`<b>${ks.map(k=>k+s[k].toFixed(2)).join(" ")}</b>`;
      }
      $("#sCnt").innerHTML=cnt;
      box.innerHTML = list.length ? list.map(evRow).join("")
        : `<div class="mt">${L().emptyDay(tab==="bill")}<br>${L().emptyDayHint}</div>`;
    }else{                                       // 整月
      const ml=monthList();
      $("#sTitle").textContent=L().monthAll(cur.getMonth());
      $("#sCnt").innerHTML=L().nItems(ml.length);
      if(!ml.length){ box.innerHTML=`<div class="mt">${L().emptyMonth(tab==="bill")}</div>`; return; }
      const g={}; ml.forEach(e=>{const k=e.datetime.slice(0,10);(g[k]=g[k]||[]).push(e);});
      box.innerHTML=Object.keys(g).sort().map(k=>{
        const d=new Date(k+"T00:00");
        const lb=k===T0?L().today:L().dayTitle(d.getMonth(),d.getDate(),L().wdFull[d.getDay()]);
        return `<div class="grp${k===T0?" tdy":""}" data-d="${k}">${lb}</div>`
             + g[k].map(evRow).join("");
      }).join("");
      const t=box.querySelector(`[data-d="${sel}"]`);
      if(t) box.scrollTop = t.offsetTop - 4;     // 非热路径，可读布局
    }
  }

  /* ── 抽屉：三档 + 速度投影 + 弹簧 ── */
  const Sheet = (() => {
    const sheet=$("#sheet"), bp=$("#brandpad");
    let idx=1, y=0, raf=null, geo=null, tight=false, drawn=-1;

    function measure(){
      const H=sheet.offsetHeight, vh=window.innerHeight;
      geo={ pts:[H-52, H-vh*0.38, 0], hi:H-52 };
      const g=$("#grid").getBoundingClientRect(), ph=$("#phone").getBoundingClientRect();
      document.documentElement.style.setProperty("--grid-end",
        Math.round(g.bottom-ph.top+10)+"px");
      return geo;
    }
    function apply(v){
      y=v; sheet.style.transform=`translate3d(0,${v}px,0)`;
      if(geo&&bp){                                // 仅跨阈值时改 class
        const t=(geo.hi-v)>geo.hi*0.5;
        if(t!==tight){ tight=t; bp.classList.toggle("tight",t); }
      }
    }
    function spring(target,v0){
      cancelAnimationFrame(raf);
      const K=430, C=2*Math.sqrt(K), STEP=1/240;
      let x=y-target, v=v0, last=performance.now(), acc=0;
      sheet.style.willChange="transform"; sheet.classList.add("moving");
      raf=requestAnimationFrame(function f(now){
        acc+=Math.min((now-last)/1000,0.05); last=now;
        while(acc>0){ const dt=Math.min(STEP,acc); acc-=dt;
          v+=(-K*x - C*v)*dt; x+=v*dt; }
        if(Math.abs(x)<0.4 && Math.abs(v)<12){
          apply(target); sheet.style.willChange=""; sheet.classList.remove("moving");
          sheet.classList.toggle("peeking", idx===0);
          if(drawn!==idx){ drawn=idx; drawSheet(); }
          return;
        }
        apply(target+x); raf=requestAnimationFrame(f);
      });
    }
    function to(i,v0=0){
      idx=Math.max(0,Math.min(2,i));
      if(idx!==0) sheet.classList.remove("peeking");
      if(!geo) measure();
      spring(geo.pts[idx], v0);
    }

    let sy=0, base=0, on=false, ly=0, lt=0, vel=0, pend=null, q=false;
    const RATE=0.995;
    const project=v=>(v/1000)*RATE/(1-RATE);
    const rubber=(o,d)=>(1-1/(o/d*0.55+1))*d;

    function down(e){
      cancelAnimationFrame(raf);
      if(!geo) measure();
      on=true; sy=ly=(e.touches?e.touches[0]:e).clientY;
      lt=performance.now(); vel=0; base=y;
      sheet.style.willChange="transform"; sheet.classList.add("moving");
    }
    function move(e){
      if(!on) return;
      const p=(e.touches?e.touches[0]:e).clientY, now=performance.now(), dt=now-lt;
      if(dt>4){ vel=0.75*vel+0.25*((p-ly)/dt*1000); ly=p; lt=now; }
      pend=p;
      if(!q){ q=true; requestAnimationFrame(()=>{
        q=false; if(!on) return;
        let t=base+(pend-sy);
        if(t<geo.pts[2]) t=geo.pts[2]-rubber(geo.pts[2]-t,120);
        if(t>geo.pts[0]) t=geo.pts[0]+rubber(t-geo.pts[0],120);
        apply(t);
      }); }
      e.preventDefault();
    }
    function up(){
      if(!on) return; on=false;
      const land=y+project(vel);
      let best=0,bd=1e9;
      geo.pts.forEach((p,i)=>{const d=Math.abs(p-land); if(d<bd){bd=d;best=i;}});
      idx=best; if(best!==0) sheet.classList.remove("peeking");
      spring(geo.pts[best], vel);
    }

    [$("#grab"),$(".shd")].forEach(el=>{
      el.addEventListener("touchstart",down,{passive:true});
      el.addEventListener("mousedown",down);
    });
    document.addEventListener("touchmove",move,{passive:false});
    document.addEventListener("mousemove",move);
    document.addEventListener("touchend",up);
    document.addEventListener("mouseup",up);

    const box=$("#sList"); let bly=0;
    box.addEventListener("touchstart",e=>{bly=e.touches[0].clientY;},{passive:true});
    box.addEventListener("touchmove",e=>{
      if(idx===2 && box.scrollTop<=0 && e.touches[0].clientY-bly>64) to(1);
    },{passive:true});
    $("#grab").addEventListener("click",()=>{
      if(Math.abs(vel)>60) return;
      to(idx===0?1:(idx===1?2:1));
    });
    window.addEventListener("resize",()=>{ geo=null; measure(); apply(geo.pts[idx]); });

    return { to, idx:()=>idx, measure, init(){ measure(); apply(geo.pts[1]); idx=1; drawn=1; } };
  })();

  /* ── 横滑翻月 ── */
  (function(){
    const g=$("#grid"), wrap=$(".gwrap");
    let x0=0,y0=0,dx=0,on=false,lock=null,vx=0,lt=0,lx=0,anim=null,w=0;
    const lift=v=>{ g.style.willChange = v?"transform,opacity":""; };
    function slide(x,op){
      g.style.transform=`translate3d(${x}px,0,0)`;
      if(op!==undefined) g.style.opacity=op;
    }
    function ease(from,to,dur,after){
      cancelAnimationFrame(anim);
      const t0=performance.now();
      anim=requestAnimationFrame(function f(now){
        const p=Math.min((now-t0)/dur,1), e=1-Math.pow(1-p,3);
        const x=from+(to-from)*e;
        slide(x, 1-Math.min(Math.abs(x)/w,.6)*0.9);
        if(p<1) anim=requestAnimationFrame(f);
        else { slide(to, to===0?1:undefined); if(!after) lift(false); after&&after(); }
      });
    }
    function commit(dir){
      const half=w*0.5;
      ease(dx,-dir*half,180,()=>{
        cur=new Date(cur.getFullYear(),cur.getMonth()+dir,1);
        render(); slide(dir*half,.4); ease(dir*half,0,250);
      });
    }
    g.addEventListener("touchstart",e=>{
      cancelAnimationFrame(anim);
      w=wrap.offsetWidth||360; lift(true);
      x0=lx=e.touches[0].clientX; y0=e.touches[0].clientY;
      dx=0; vx=0; lt=performance.now(); on=true; lock=null;
    },{passive:true});
    g.addEventListener("touchmove",e=>{
      if(!on) return;
      const x=e.touches[0].clientX, yy=e.touches[0].clientY;
      if(lock===null && (Math.abs(x-x0)>8||Math.abs(yy-y0)>8))
        lock = Math.abs(x-x0)>Math.abs(yy-y0)*1.3 ? "x":"y";
      if(lock!=="x") return;
      const now=performance.now(), dt=now-lt;
      if(dt>4){ vx=0.7*vx+0.3*((x-lx)/dt*1000); lx=x; lt=now; }
      dx=(x-x0)*0.9;
      slide(dx, 1-Math.min(Math.abs(dx)/w,.6)*0.9);
      e.preventDefault();
    },{passive:false});
    g.addEventListener("touchend",()=>{
      if(!on) return; on=false;
      if(lock!=="x"){ slide(0,1); lift(false); return; }
      const land=dx+(vx/1000)*0.995/(1-0.995);
      if(land<-w*0.28) commit(1);
      else if(land>w*0.28) commit(-1);
      else ease(dx,0,240);
    },{passive:true});
    window.addEventListener("resize",()=>{ w=0; });
    window.navMonth=n=>{
      w=wrap.offsetWidth||360;
      if(n===0){ cur=new Date(TODAY.getFullYear(),TODAY.getMonth(),1); sel=T0; render(); return; }
      dx=0; lift(true); commit(n);
    };
  })();

  function render(){ drawHero(); drawGrid(); drawSheet(); }

  return {
    render, toast, money, Sheet,
    setEvents(list){ EV=list; },
    setTab(t){ tab=t; },
    getTab(){ return tab; },
    selected(){ return sel; },
    setSelected(d){ sel=d; },
    goMonth(y,m){ cur=new Date(y,m,1); },
    today(){ return T0; },
    refreshToday(){ TODAY=new Date(); T0=iso(TODAY); },
  };
})();