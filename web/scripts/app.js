/* ═══ Kairos · app.js — 入口：接线、语言、连接状态、弹窗 ═══ */

const QUOTES=[
 {en:"Know the right moment.", or:"καιρὸν γνῶθι", by:"PITTACUS OF MYTILENE"},
 {en:"Seize the day, trusting little in the future.", or:"Carpe diem", by:"HORACE"},
 {en:"Knowing when is the foundation of greatness.", or:"", by:"T.S. CHEN"},
];

const App = (() => {
  const $ = s => document.querySelector(s);

  /* ── 语言 ── */
  function applyLang(){
    document.documentElement.lang = LANG==="zh"?"zh-CN":"en";
    document.querySelectorAll("[data-t]").forEach(el=>{
      const v=L()[el.dataset.t]; if(typeof v==="string") el.textContent=v;
    });
    document.querySelectorAll("[data-tp]").forEach(el=>{
      const v=L()[el.dataset.tp]; if(typeof v==="string") el.placeholder=v;
    });
    $("#wdrow").innerHTML=L().wd.map(w=>`<span>${w}</span>`).join("");
    $("#subNote").innerHTML=L().subNote;
    $("#langBtn").textContent = LANG==="zh"?"EN":"中";
    drawQuote(); drawConn(); Cal.render();
  }
  function drawQuote(){
    const q=QUOTES[Math.floor(Math.random()*QUOTES.length)];
    $("#quote").innerHTML=`<i>${q.en}</i>`
      + (q.or?`<b style="font-style:italic;font-size:11px;letter-spacing:0;opacity:.85">${q.or}</b>`:"")
      + `<b>${q.by}</b>`;
  }

  /* ── 连接状态条 ── */
  function drawConn(){
    const c=Store.connection(), bar=$("#connbar");
    if(c.state==="expired"){
      bar.classList.add("on");
      bar.querySelector("span").textContent=L().connExpired;
      bar.querySelector("button").textContent=L().reconnect;
    }else if(c.state==="none"){
      bar.classList.add("on");
      bar.querySelector("span").textContent=L().connNone;
      bar.querySelector("button").textContent=L().connect;
    }else{
      bar.classList.remove("on");
    }
  }

  /* ── 添加事项 ── */
  function openAdd(){
    $("#fDate").value=Cal.selected();
    $("#fTitle").value=""; $("#fTime").value="";
    $("#fKind").value = Cal.getTab()==="bill" ? "billing" : "appointment";
    $("#mask").classList.add("on"); $("#addModal").classList.add("on");
    setTimeout(()=>$("#fTitle").focus(),320);
  }
  function closeAll(){
    $("#mask").classList.remove("on");
    $("#addModal").classList.remove("on");
    $("#subModal").classList.remove("on");
  }

  /* ── 订阅外部日历 ── */
  async function drawSubs(){
    const list=await Store.feeds(), el=$("#subList");
    if(!list.length){ el.innerHTML=""; return; }
    el.innerHTML=`<div style="font-size:11px;color:var(--ink3);letter-spacing:.1em;
      margin-top:14px">${L().subbed}</div>`
      + list.map((x,i)=>`<div class="subrow"><span class="nm">${x.name}
        <span class="st">${x.kind==="billing"?L().bills:L().agenda} · ${L().subSync}</span></span>
        <button data-del="${i}">${L().subRemove}</button></div>`).join("");
    el.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{
      await Store.removeFeed(+b.dataset.del); drawSubs(); Cal.toast(L().tUnsub);
    });
  }

  async function reload(){
    Cal.setEvents(await Store.list());
    Cal.render();
    drawConn();          // 数据(连带 conn)取回后重画提示条
  }

  return {
    applyLang, drawConn, reload,

    async init(){
      /* 标签切换 */
      document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{
        document.querySelectorAll("[data-tab]").forEach(x=>x.classList.remove("on"));
        b.classList.add("on");
        Cal.setTab(b.dataset.tab);
        document.body.classList.remove("all","day","bill");
        document.body.classList.add(b.dataset.tab);
        document.querySelector('meta[name=theme-color]').setAttribute("content",
          b.dataset.tab==="bill"?"#F7F9FA":b.dataset.tab==="all"?"#FAF8F5":"#FCF8F2");
        Cal.render();
      });
      /* 月导航 */
      document.querySelectorAll("[data-nav]").forEach(b=>
        b.onclick=()=>navMonth(+b.dataset.nav));
      /* 网格空白 → 抽屉降到最低 */
      $("#grid").addEventListener("click",e=>{
        if(!e.target.closest(".cell")) Cal.Sheet.to(0);
      });
      $("#wdrow").addEventListener("click",()=>Cal.Sheet.to(0));
      /* 语言 */
      $("#langBtn").onclick=()=>{
        setLang(LANG==="zh"?"en":"zh"); applyLang(); Onboard.relang();
      };
      /* 添加 */
      $("#addBtn").onclick=openAdd;
      $("#mask").onclick=closeAll;
      $("#fCancel").onclick=closeAll;
      $("#fSave").onclick=async()=>{
        const d=$("#fDate").value, t=$("#fTitle").value.trim(),
              tm=$("#fTime").value, k=$("#fKind").value;
        if(!d||!t){ Cal.toast(L().tNeed); return; }
        await Store.add({datetime: tm?`${d} ${tm}`:d, type:k, title:t});
        closeAll();
        const [yy,mm]=d.split("-").map(Number);
        Cal.goMonth(yy,mm-1); Cal.setSelected(d);
        await reload();
        const other=(k==="billing")!==(Cal.getTab()==="bill") && Cal.getTab()!=="all";
        Cal.toast(other?L().tAddedOther(k==="billing"):L().tAdded);
      };
      /* 订阅 */
      $("#subBtn").onclick=()=>{
        $("#sUrl").value=""; $("#sName").value=""; drawSubs();
        $("#mask").classList.add("on"); $("#subModal").classList.add("on");
      };
      $("#sCancel").onclick=closeAll;
      $("#sAdd").onclick=async()=>{
        const u=$("#sUrl").value.trim(), n=$("#sName").value.trim()||L().untitled;
        if(!/^(webcal|https?):\/\/.+/i.test(u)){ Cal.toast(L().tBadUrl); return; }
        await Store.addFeed({url:u,name:n,kind:$("#sKind").value});
        drawSubs(); Cal.toast(L().tSubbed(n));
        $("#sUrl").value=""; $("#sName").value="";
      };
      /* 连接状态条上的按钮 */
      $("#connbar button").onclick=()=>{ location.href="/api/auth/google"; };

      /* 调试：载入真实抽取结果 */
      const f=$("#fileIn");
      if(f) f.onchange=ev=>{
        const file=ev.target.files[0]; if(!file) return;
        const r=new FileReader();
        r.onload=()=>{
          try{
            const arr=JSON.parse(r.result);
            if(!Array.isArray(arr)) throw 0;
            Store.loadRaw(arr); reload();
            Cal.toast(`${arr.length}`);
          }catch(e){ Cal.toast("JSON?"); }
        };
        r.readAsText(file);
      };

      /* auth=ok:授权跳回,清掉 URL 参数并强制取新状态 */
      const authBack = new URLSearchParams(location.search).get("auth");
      if (authBack) history.replaceState(null, "", location.pathname);

      applyLang();          // UI 先立起来——数据失败也要有完整界面
      Onboard.init();
      try {
        await reload();     // 数据最后取:失败只影响内容,不影响交互
      } catch (e) {
        Cal.setEvents([]);  // 空日历
        Cal.render();
        drawConn();         // 此刻 conn 已被 store.js 置为 none/expired,提示条亮起
      }
    }
  };
})();

document.addEventListener("DOMContentLoaded",()=>App.init());