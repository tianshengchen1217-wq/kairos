/* ═══════════════════════════════════════════════════════════
   Kairos · store.js — 数据层
   ───────────────────────────────────────────────────────────
   这一层是前端与后端之间唯一的边界。渲染代码只准通过 Store
   取数据，不准直接碰 EVENTS 数组。

   现在：返回内置演示数据（离线可跑）
   以后：把 MODE 改成 "api"，实现下面几个 fetch，
        渲染层一行都不用动。

   全部方法都是 async —— 即便演示数据是同步的，也刻意保持
   异步签名，这样切到网络请求时调用点不需要改。
   ═══════════════════════════════════════════════════════════ */

const Store = (() => {
  const MODE = "api";                 // "demo" | "api"
  const API  = "/api";

  /* ── 演示数据 ─────────────────────────────────────────
     注意：以下为 UI 原型用的虚构数据，不是真实邮件抽取结果。 */
  const SUBS=[
    [2,"Netflix 标准套餐 ¥68.00"],[3,"iCloud+ 200GB ¥21.00"],
    [5,"哔哩哔哩 连续包月大会员 ¥15.00"],[7,"ChatGPT Plus 月度 $29.99"],
    [9,"网易云音乐黑胶VIP ¥12.00"],[12,"百度网盘超级会员 ¥18.00"],
    [13,"QQ音乐绿钻豪华版 ¥12.00"],[16,"芒果TV 连续包月 ¥18.00"],
    [17,"Spotify Premium $11.99"],[20,"夸克网盘会员 ¥20.00"],
    [23,"iQIYI 黄金会员 ¥25.00"],[26,"Adobe Creative Cloud $54.99"],
    [28,"Notion Plus $10.00"],
  ];
  const ONEOFF=[
    ["2026-08-03 09:30","appointment","牙科复诊 Dr. Lim（Orchard 分店）"],
    ["2026-08-03","delivery","Uniqlo 秋季外套送达"],
    ["2026-08-05 19:00","appointment","Rata Restaurant 订位 4人"],
    ["2026-08-05","deadline","提交房屋保险续保材料"],
    ["2026-08-05","delivery","Amazon 机械键盘送达"],
    ["2026-08-06 14:00","appointment","签证面谈 新西兰移民局"],
    ["2026-08-11","deadline","缴纳 SCE 电费 $178.63"],
    ["2026-08-12 10:00","appointment","公寓年检 Essex Skyline"],
    ["2026-08-13 08:00","appointment","晨会 产品评审"],
    ["2026-08-13 11:00","appointment","体检 中山医院"],
    ["2026-08-13 16:30","appointment","与房东看房 Clarke Quay"],
    ["2026-08-13","deadline","提交签证补充材料"],
    ["2026-08-13","delivery","戴森吹风机送达"],
    ["2026-08-14 15:15","appointment","NiCHU Hair Studio 理发"],
    ["2026-08-14","delivery","Sephora 护肤品送达"],
    ["2026-08-14","deadline","回复 Pilot 订单问题"],
    ["2026-08-18 20:30","appointment","Bistecca Tuscan Steakhouse 订位 2人"],
    ["2026-08-19","deadline","提交季度报税材料"],
    ["2026-08-20 09:00","appointment","DHL 上门取件（须在场）"],
    ["2026-08-21","delivery","IKEA 书架配送"],
    ["2026-08-24 18:30","appointment","Mani Restaurant 订位 2人"],
    ["2026-08-25","deadline","护照换发预约截止"],
    ["2026-08-27 21:00","appointment","HOYTS 电影 Odyssey"],
    ["2026-08-31","deadline","健身房会员续费决定"],
    ["2026-09-02 11:30","appointment","Kia Ora Onsen 预约 2人"],
    ["2026-09-08","delivery","Apple Studio Display 送达"],
    ["2026-09-15","deadline","提交学期选课确认"],
    ["2026-07-04 18:30","appointment","Mani Restaurant 订位 2人"],
    ["2026-07-09","delivery","Walmart 生活用品送达"],
    ["2026-07-16","deadline","缴纳 PPL 电费 $326.25"],
    ["2026-07-25 20:40","appointment","HOYTS 电影 Odyssey"],
  ];
  function seed(){
    const out=[];
    for(let mo=5;mo<=10;mo++){
      SUBS.forEach(([d,t])=>{
        if(mo%2===1 && d%7===0) return;
        out.push({datetime:`2026-${String(mo+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`,
                  type:"billing", title:t});
      });
    }
    ["Amazon Prime ¥88.00","YouTube Premium $13.99","Kindle Unlimited ¥12.00",
     "Microsoft 365 ¥98.00"].forEach(t=>
      out.push({datetime:"2026-08-13",type:"billing",title:t}));
    ONEOFF.forEach(([dt,ty,ti])=>out.push({datetime:dt,type:ty,title:ti}));
    return out.map((e,i)=>({id:"demo-"+i, ...e}));
  }

  let cache = MODE==="demo" ? seed() : null;
  let conn  = MODE==="demo"
    ? {state:"demo", email:null}
    : {state:"none", email:null};      // none | connected | expired | demo

  async function json(path, opt){
    const r = await fetch(API+path, {credentials:"include", ...opt});
    if(r.status===401){ conn={state:"none",email:null}; throw new Error("unauthenticated"); }
    if(r.status===419){ conn.state="expired"; throw new Error("token-expired"); }
    if(!r.ok) throw new Error("http "+r.status);
    return r.json();
  }

  return {
    /* 事件列表。后端版本应支持按月拉取以免一次拖太多。 */
    async list(){
      if(MODE==="demo") return cache;
      if(!cache){
        cache = await json("/events");
        try{ conn = await json("/connection"); }catch(e){}
      }
      return cache;
    },
    /* 手动添加一项。后端版本 POST 后用返回值替换本地。 */
    async add(ev){
      const rec = {id:"local-"+Date.now(), ...ev};
      if(MODE==="demo"){ cache.push(rec); return rec; }
      const saved = await json("/events",{method:"POST",
        headers:{"Content-Type":"application/json"}, body:JSON.stringify(ev)});
      cache.push(saved); return saved;
    },
    /* 外部 .ics 订阅源 */
    async feeds(){ return MODE==="demo" ? (this._feeds||(this._feeds=[])) : json("/feeds"); },
    async addFeed(f){
      if(MODE==="demo"){ (this._feeds||(this._feeds=[])).push(f); return f; }
      return json("/feeds",{method:"POST",
        headers:{"Content-Type":"application/json"}, body:JSON.stringify(f)});
    },
    async removeFeed(i){
      if(MODE==="demo"){ this._feeds.splice(i,1); return; }
      return json("/feeds/"+i,{method:"DELETE"});
    },
    /* 连接状态：驱动顶部提示条 */
    connection(){ return conn; },
    setConnection(c){ conn = c; },
    /* 从文件载入（调试用：读真实抽取结果 calendar_events.json） */
    loadRaw(arr){
      cache = arr.filter(e=>e && e.datetime && e.title)
                 .map((e,i)=>({id:"file-"+i, ...e}));
      conn = {state:"demo", email:null};
      return cache;
    },
    isDemo(){ return conn.state==="demo"; },
  };
})();