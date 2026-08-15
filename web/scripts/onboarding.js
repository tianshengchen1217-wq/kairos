/* ═══ Kairos · onboarding.js — 三屏引导 ═══
   屏1 启动（每次显示，已绑定则 1.4s 自动淡出）
   屏2 连接邮箱（原型：前端占位，OAuth 需服务端）
   屏3 隐私与功能说明（勾选后进入，之后不再出现）        */

const Onboard = (() => {
  const $ = s => document.querySelector(s);

  const OB = {
   zh:{
    tag:"YOUR PRIVATE AI CALENDAR AGENT", hint:"TAP TO CONTINUE",
    h2:"连接你的邮箱",
    l2:"Kairos 从邮件里找出未来的时间点——账单扣款、快递送达、预约和截止日期——自动整理成日历。",
    mboxSb:"读取权限 · 只读不发送", connect:"连接 Gmail", connecting:"正在授权…",
    connected:"已连接", fine:"原型演示：此处为前端占位，OAuth 授权需在服务端完成",
    h3:"开始之前", l3:"Kairos 会怎么处理你的邮件：",
    pts:[
     ["只读取，不修改。","Kairos 只读你的邮件，不会代你发送、回复或删除任何内容。"],
     ["大部分邮件不会离开本地。","约一半邮件（促销、收据、往返回复）由本地规则直接判掉，根本不发出去。"],
     ["发出去的也不是全文。","剩下的邮件只截取含时间表达的正文切片，送到 Anthropic 的模型做一次识别，少数难判的再由更强的模型复核。抽取完即弃，不留存正文——只保存识别出的日期、类型和一句简短描述。"],
     ["只处理接入之后的新邮件。","加上向前回溯 30 天，更早的历史邮件不会被翻出来。"],
     ["随时可断开。","断开连接会一并删除已抽取的事件。"],
    ],
    agree:"我已阅读并理解以上说明", enter:"进入 Kairos",
   },
   en:{
    tag:"YOUR PRIVATE AI CALENDAR AGENT", hint:"TAP TO CONTINUE",
    h2:"Connect your inbox",
    l2:"Kairos finds future moments in your email — charges, deliveries, appointments and deadlines — and lays them out as a calendar.",
    mboxSb:"Read access · never sends", connect:"Connect Gmail", connecting:"Authorising…",
    connected:"Connected", fine:"Prototype: front-end placeholder — OAuth must be completed server-side",
    h3:"Before you start", l3:"How Kairos handles your mail:",
    pts:[
     ["Read-only.","Kairos reads your mail. It never sends, replies or deletes on your behalf."],
     ["Most mail never leaves your device.","Around half of it — promotions, receipts, reply threads — is ruled out locally and never sent anywhere."],
     ["What is sent isn't the full text.","For the rest, only the slices of the body containing time expressions go to Anthropic's models for one identification pass, with a stronger model reviewing the harder cases. Nothing is retained afterwards — only the date, type and a short description are stored."],
     ["Only mail from now on.","Plus a 30-day look-back. Anything older stays untouched."],
     ["Disconnect any time.","Disconnecting also deletes the events already extracted."],
    ],
    agree:"I've read and understood the above", enter:"Enter Kairos",
   }
  };
  const t = () => OB[LANG];
  let bound = false;
  try{ bound = localStorage.getItem("kairos_bound")==="1"; }catch(e){}

  function draw1(){
    const now=new Date();
    $("#obWd").textContent=["SUNDAY","MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"][now.getDay()];
    $("#obDate").textContent=`${String(now.getDate()).padStart(2,"0")}.${String(now.getMonth()+1).padStart(2,"0")}`;
    $("#obMo").innerHTML=`${MO_EN[now.getMonth()].toUpperCase()} <span class="yr">${now.getFullYear()}</span>`;
    let h=now.getHours(); const ap=h>=12?"PM":"AM"; h=h%12||12;
    $("#obTime").textContent=`${h}:${String(now.getMinutes()).padStart(2,"0")}`;
    $("#obAp").textContent=ap;
    let tz="LOCAL";
    try{
      const z=Intl.DateTimeFormat().resolvedOptions().timeZone||"";
      const city=z.split("/").pop().replace(/_/g," ");
      const off=-now.getTimezoneOffset()/60;
      tz = (/^(UTC|GMT|Etc)/i.test(z)||!city) ? "UTC"+(off>=0?"+":"")+off : city.toUpperCase();
    }catch(e){}
    $("#obTz").textContent=tz;
    $("#obTag").textContent=t().tag;
    $("#obHint").textContent=t().hint;
    const q=QUOTES[Math.floor(Math.random()*QUOTES.length)];
    $("#obQe").textContent=q.en; $("#obQo").textContent=q.or; $("#obQb").textContent=q.by;
  }
  function draw23(){
    const x=t();
    $("#ob2h").textContent=x.h2; $("#ob2l").textContent=x.l2;
    $("#mboxSb").textContent=x.mboxSb; $("#obConnect").textContent=x.connect;
    $("#obFine").textContent=x.fine;
    $("#ob3h").textContent=x.h3; $("#ob3l").textContent=x.l3;
    $("#obPts").innerHTML=x.pts.map(([b,d])=>
      `<div class="pt"><span class="d"></span><span class="tx"><b>${b}</b> ${d}</span></div>`).join("");
    $("#obAgreeLb").textContent=x.agree; $("#obEnter").textContent=x.enter;
  }
  function show(n){
    document.body.classList.remove("ob-step2","ob-step3");
    if(n>1) document.body.classList.add("ob-step"+n);
    [1,2,3].forEach(i=>{
      const el=$("#ob"+i);
      if(i===n){ el.classList.remove("hidden");
        requestAnimationFrame(()=>el.classList.remove("gone")); }
      else { el.classList.add("gone"); setTimeout(()=>el.classList.add("hidden"),500); }
    });
  }
  function finish(){
    [1,2,3].forEach(i=>{ const e=$("#ob"+i); e.classList.add("gone");
      setTimeout(()=>e.classList.add("hidden"),500); });
    document.body.classList.remove("ob-step2","ob-step3");
    const lb=$("#obLang"); lb.style.opacity="0";
    setTimeout(()=>lb.style.display="none",500);
    try{ localStorage.setItem("kairos_bound","1"); }catch(e){ bound=true; }
    requestAnimationFrame(()=>Cal.Sheet.init());
  }

  return {
    init(){
      draw1(); draw23();
      $("#obLang").textContent = LANG==="zh"?"EN":"中";
      $("#ob1").onclick = () => bound ? finish() : show(2);
      $("#obConnect").onclick = () => {
        const b=$("#obConnect"); b.disabled=true; b.textContent=t().connecting;
        $("#mboxRt").innerHTML='<div class="spin"></div>';
        // TODO(后端)：改为 location.href = "/auth/google"
        setTimeout(()=>{
          $("#mbox").classList.add("done"); $("#mboxIc").textContent="✓";
          $("#mboxRt").innerHTML=`<span style="font-size:11.5px;color:#0A5B52">${t().connected}</span>`;
          setTimeout(()=>show(3),620);
        },1150);
      };
      $("#obAgree").onclick = () => {
        const a=$("#obAgree"); a.classList.toggle("on");
        $("#obEnter").disabled = !a.classList.contains("on");
      };
      $("#obEnter").onclick = finish;
      $("#obLang").onclick = e => {
        e.stopPropagation();
        setLang(LANG==="zh"?"en":"zh");
        $("#obLang").textContent = LANG==="zh"?"EN":"中";
        draw1(); draw23(); App.applyLang();
      };
      if(bound){
        $("#ob2").classList.add("hidden"); $("#ob3").classList.add("hidden");
        setTimeout(finish,1400);
      }
    },
    relang(){ draw1(); draw23(); },
  };
})();