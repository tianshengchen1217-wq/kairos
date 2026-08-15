/* ── i18n：界面文案中英切换。用户输入与邮件抽取出的标题不翻译 ── */
const MO_EN=["January","February","March","April","May","June","July",
             "August","September","October","November","December"];
const MO_AB=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const I18N={
 zh:{
  all:"全部", agenda:"日程", bills:"账单", todayBtn:"今天", today:"今天",
  wd:["一","二","三","四","五","六","日"],
  wdFull:["日","一","二","三","四","五","六"],
  monthOf:(y,m)=>`${m+1}月`,
  dayTitle:(m,d,w)=>`${m+1}月${d}日 周${w}`,
  monthAll:m=>`${m+1}月 全部`,
  nItems:n=>`${n} 项`,
  monthCount:n=>`本月 ${n} 项`, upcoming:"待发生", monthTotal:"本月合计",
  allDay:"全天", pullUp:"上拉查看安排",
  emptyDay:k=>`这天没有${k?"扣款":"安排"}。`,
  emptyDayHint:"上拉查看整月，或 ＋ 添加一项。",
  emptyMonth:k=>`这个月还没有${k?"扣款":"安排"}。`,
  tag:{appointment:"约",deadline:"截止",delivery:"到货",billing:"扣款",other:"其他"},
  addTitle:"添加一项", fDate:"日期", fTime:"时间（可留空）",
  fContent:"内容", fContentPh:"如：牙医复诊 / Netflix ¥68.00",
  fWhich:"加到哪个日历",
  optAppt:"日程 · 预约", optDue:"日程 · 截止",
  optDeliv:"日程 · 到货", optOther:"日程 · 其他", optBill:"账单 · 扣款",
  cancel:"取消", save:"加入",
  subTitle:"订阅外部日历", subUrl:"日历链接（webcal:// 或 .ics）",
  subName:"名称", subNamePh:"如：本学期课表", subWhich:"并入哪个日历",
  subAdd:"订阅", subbed:"已订阅", subRemove:"移除", subSync:"每 6 小时同步",
  subNote:"学校课表、球队赛程这类页面通常提供一个 .ics 链接。订阅后按固定周期自动同步，对方改了时间这边跟着变。<br>当前为原型：链接只做格式校验，尚未真正拉取。",
  demo:"演示数据",
  tNeed:"填一下日期和内容", tAdded:"已加入",
  tAddedOther:k=>`已加入${k?"账单":"日程"} — 切标签查看`,
  tSubbed:n=>`已订阅「${n}」`, tUnsub:"已取消订阅",
  tBadUrl:"链接要以 webcal:// 或 https:// 开头",
  untitled:"未命名日历",
  connExpired:"邮箱连接已过期", reconnect:"重新连接",
  connNone:"未连接邮箱", connect:"连接",
  demoTip:"当前为演示数据"
 },
 en:{
  all:"All", agenda:"Agenda", bills:"Bills", todayBtn:"Today", today:"Today",
  wd:["M","T","W","T","F","S","S"],
  wdFull:["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],
  monthOf:(y,m)=>MO_EN[m],
  dayTitle:(m,d,w)=>`${MO_AB[m]} ${d}, ${w}`,
  monthAll:m=>`${MO_EN[m]} · All`,
  nItems:n=>`${n} item${n===1?"":"s"}`,
  monthCount:n=>`${n} this month`, upcoming:"upcoming", monthTotal:"Month total",
  allDay:"All day", pullUp:"Pull up for schedule",
  emptyDay:k=>`No ${k?"charges":"plans"} today.`,
  emptyDayHint:"Pull up for the month, or ＋ to add one.",
  emptyMonth:k=>`No ${k?"charges":"plans"} this month.`,
  tag:{appointment:"Appt",deadline:"Due",delivery:"Arriving",billing:"Charge",other:"Other"},
  addTitle:"Add an item", fDate:"Date", fTime:"Time (optional)",
  fContent:"What", fContentPh:"e.g. Dentist 2pm / Netflix $9.99",
  fWhich:"Which calendar",
  optAppt:"Agenda · Appointment", optDue:"Agenda · Deadline",
  optDeliv:"Agenda · Delivery", optOther:"Agenda · Other", optBill:"Bills · Charge",
  cancel:"Cancel", save:"Add",
  subTitle:"Subscribe to a calendar", subUrl:"Calendar link (webcal:// or .ics)",
  subName:"Name", subNamePh:"e.g. This semester's timetable", subWhich:"Merge into",
  subAdd:"Subscribe", subbed:"Subscribed", subRemove:"Remove", subSync:"syncs every 6h",
  subNote:"University timetables and team fixtures usually publish an .ics link. Once subscribed it re-syncs on a schedule — if they move a time, it updates here.<br>Prototype: the link is validated but not fetched yet.",
  demo:"Demo data",
  tNeed:"Add a date and some text", tAdded:"Added",
  tAddedOther:k=>`Added to ${k?"Bills":"Agenda"} — switch tabs to see it`,
  tSubbed:n=>`Subscribed to "${n}"`, tUnsub:"Unsubscribed",
  tBadUrl:"Link must start with webcal:// or https://",
  untitled:"Untitled calendar",
  connExpired:"Mailbox connection expired", reconnect:"Reconnect",
  connNone:"No mailbox connected", connect:"Connect",
  demoTip:"Showing demo data"
 }
};
/* 语言偏好：优先读上次选择，否则跟随系统 */
let LANG=(()=>{
  try{ const v=localStorage.getItem("kairos_lang"); if(v==="zh"||v==="en") return v; }catch(e){}
  return (navigator.language||"en").toLowerCase().startsWith("zh")?"zh":"en";
})();
function setLang(v){
  LANG=v;
  try{ localStorage.setItem("kairos_lang",v); }catch(e){}
}
const L=()=>I18N[LANG];