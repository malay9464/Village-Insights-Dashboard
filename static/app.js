const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let charts = {};
let currentPage = "overview";
let latestRows = [];
let explorerPage = 1;
const explorerPageSize = 25;
let csrfToken = "";
let dashboardRequestId = 0;
let explorerRequestId = 0;
let villageOptionsRequestId = 0;

function toast(message, isError=false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.className = "toast", 3400);
}
async function api(url, options={}) {
  const res = await fetch(url, {credentials:"same-origin", ...options, headers:{"Content-Type":"application/json", ...(csrfToken ? {"X-CSRF-Token":csrfToken} : {}), ...(options.headers||{})}});
  const data = res.headers.get("content-type")?.includes("application/json") ? await res.json() : res;
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}
function setAuthMode(mode) {
  $("#login-form").classList.toggle("hidden", mode !== "login");
  $("#signup-form").classList.toggle("hidden", mode !== "signup");
  $("#forgot-form").classList.toggle("hidden", mode !== "forgot");
  $("#auth-tabs").classList.toggle("hidden", mode === "forgot");
  $$(".auth-tab").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  if (mode === "login") {
    $("#auth-eyebrow").textContent = "YOUR WORKSPACE";
    $("#auth-title").textContent = "Welcome back.";
    $("#auth-subtitle").textContent = "Sign in to explore village-level insights.";
  } else if (mode === "signup") {
    $("#auth-eyebrow").textContent = "GET STARTED";
    $("#auth-title").textContent = "Create your account.";
    $("#auth-subtitle").textContent = "Your own space for exploring the data.";
  } else {
    $("#auth-eyebrow").textContent = "ACCOUNT RECOVERY";
    $("#auth-title").textContent = "Reset your password.";
    $("#auth-subtitle").textContent = "Use your Login ID and recovery code.";
  }
}
$$(".auth-tab").forEach(btn => btn.addEventListener("click", () => setAuthMode(btn.dataset.mode)));
$("#forgot-link").addEventListener("click", () => setAuthMode("forgot"));
$("#back-login").addEventListener("click", () => setAuthMode("login"));

$("#signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const f = new FormData(form);
  try {
    const result = await api("/api/signup", {method:"POST", body:JSON.stringify(Object.fromEntries(f.entries()))});
    toast(result.message);
    form.reset();
    setAuthMode("login");
  } catch(err) { toast(err.message, true); }
});
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.currentTarget);
  try {
    const result = await api("/api/login", {method:"POST", body:JSON.stringify(Object.fromEntries(f.entries()))});
    csrfToken=result.csrf_token||csrfToken;
    toast("Welcome, " + result.user);
    await enterApp(result);
  } catch(err) { toast(err.message, true); }
});
$("#forgot-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const f = new FormData(form);
  try {
    const result = await api("/api/forgot-password", {method:"POST", body:JSON.stringify(Object.fromEntries(f.entries()))});
    toast(result.message);
    form.reset();
    setAuthMode("login");
  } catch(err) { toast(err.message, true); }
});
$("#logout-btn").addEventListener("click", async () => {
  try { await api("/api/logout", {method:"POST", body:"{}"}); } catch(e) {}
  try { csrfToken=(await api("/api/session")).csrf_token||""; } catch(e) { csrfToken=""; }
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
  $("#app-screen").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  setAuthMode("login");
});
async function enterApp(user) {
  $("#auth-screen").classList.add("hidden");
  $("#app-screen").classList.remove("hidden");
  $("#user-name").textContent = user.user || "User";
  $("#user-id").textContent = "@" + (user.username || "user");
  $("#user-avatar").textContent = (user.user || "U").trim().charAt(0).toUpperCase();
  await loadFilters();
  await loadDashboard();
  showPage("overview");
}
async function boot() {
  try {
    const s = await api("/api/session");
    csrfToken=s.csrf_token||"";
    if (s.authenticated) await enterApp({user:s.user, username:s.username});
  } catch(e) {}
}
async function loadFilters() {
  const f = await api("/api/filters");
  const fill = (selector, values, firstLabel) => {
    const el = $(selector);
    el.innerHTML = `<option value="All">${firstLabel}</option>`;
    values.forEach(v => el.add(new Option(v, v)));
  };
  fill("#year-filter", f.years, "All years");
  fill("#taluka-filter", f.talukas, "All talukas");
  fill("#crop-filter", f.crops, "All crops");
  updateVillageOptions(f.villages);
  $("#year-filter").addEventListener("change", filtersChanged);
  $("#taluka-filter").addEventListener("change", async () => {
    await refreshVillageOptions();
    filtersChanged();
  });
  ["#village-filter","#crop-filter"].forEach(sel => $(sel).addEventListener("change", filtersChanged));
}
function filtersChanged(){explorerPage=1;loadDashboard();}
function updateVillageOptions(values){
  const el=$("#village-filter"), previous=el.value;
  el.innerHTML='<option value="All">All villages</option>';
  values.forEach(v=>el.add(new Option(v,v)));
  if(values.includes(previous))el.value=previous;
}
async function refreshVillageOptions(){
  const requestId=++villageOptionsRequestId;
  const taluka=$("#taluka-filter").value;
  const params=new URLSearchParams();
  if(taluka!=="All")params.set("taluka",taluka);
  const f=await api("/api/filters?"+params.toString());
  if(requestId!==villageOptionsRequestId||taluka!==$("#taluka-filter").value)return;
  updateVillageOptions(f.villages);
}
function queryString(includeSearch=false) {
  const params = new URLSearchParams();
  ["year","taluka","village","crop"].forEach(k => {
    const value = $(`#${k}-filter`).value;
    if (value !== "All") params.set(k, value);
  });
  if(includeSearch && $("#table-search").value.trim()) params.set("search",$("#table-search").value.trim());
  return params.toString();
}
$("#reset-filters").addEventListener("click", async () => {
  $("#year-filter").value = "All";
  $("#taluka-filter").value = "All";
  $("#village-filter").value = "All";
  $("#crop-filter").value = "All";
  await refreshVillageOptions();
  explorerPage=1;
  loadDashboard();
});
$("#mobile-filter-toggle").addEventListener("click", () => $("#filterbar").classList.toggle("open"));

const chartColors = ["#267653","#e97d62","#d5ad63","#8bb9a0","#6486a2","#a4b86b","#c58caa","#6b9b94","#b7a17b","#8c9aaf"];
function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }
function makeChart(id, type, labels, datasets, options={}) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  destroyChart(id);
  const isHorizontal = options.horizontal;
  const chartOptions = {
    responsive:true, maintainAspectRatio:false, indexAxis:isHorizontal ? "y" : "x",
    plugins:{legend:{display:options.legend ?? (type==="doughnut" || type==="pie"),position:"bottom",labels:{usePointStyle:true,boxWidth:7,padding:16,font:{family:"DM Sans",size:10},color:"#64746a"}},
      tooltip:{backgroundColor:"#173d30",padding:11,titleFont:{family:"DM Sans",weight:"700"},bodyFont:{family:"DM Sans"}}},
    scales: (type==="doughnut"||type==="pie") ? {} : {
      x:{grid:{display:!isHorizontal,color:"#edf1eb"},border:{display:false},ticks:{color:"#7b887e",font:{family:"DM Sans",size:9},maxRotation:0}},
      y:{grid:{display:isHorizontal,color:"#edf1eb"},border:{display:false},ticks:{color:"#65766b",font:{family:"DM Sans",size:9}}}
    }
  };
  if (options.percent) {
    const axis = isHorizontal ? chartOptions.scales.x : chartOptions.scales.y;
    if (axis) { axis.beginAtZero=true; axis.max=100; axis.ticks.callback=(v)=>v+"%"; }
  }
  if (type==="doughnut"||type==="pie") chartOptions.cutout=type==="doughnut"?"66%":undefined;
  charts[id] = new Chart(canvas, {
    type, data:{labels,datasets:datasets.map((d,i)=>({label:d.label||"",data:d.data,backgroundColor:d.backgroundColor||((type==="line")?"#267653":chartColors),borderColor:d.borderColor||"#ffffff",borderWidth:type==="line"?2:1,borderRadius:type==="bar"?5:0,fill:false,tension:.32,pointRadius:3}))},
    options:chartOptions
  });
}
function labelsValues(arr){return {labels:arr.map(x=>x.label),values:arr.map(x=>x.value)}}
function fmtNum(n){return Number(n||0).toLocaleString("en-IN",{maximumFractionDigits:0})}
function fmtPct(n){return Number(n||0).toFixed(1)+"%"}
async function loadDashboard() {
  const requestId=++dashboardRequestId;
  try {
    const d = await api("/api/dashboard?"+queryString());
    if(requestId!==dashboardRequestId)return;
    $("#kpi-population").textContent = fmtNum(d.kpis.population);
    $("#kpi-villages").textContent = fmtNum(d.kpis.villages);
    $("#kpi-literacy").textContent = fmtPct(d.kpis.literacy);
    $("#kpi-internet").textContent = fmtPct(d.kpis.internet);
    $("#people-households").textContent = fmtNum(d.kpis.households);
    $("#people-household-size").textContent = d.kpis.household_size ? Number(d.kpis.household_size).toFixed(1) : "—";
    $("#agri-villages").textContent = fmtNum(d.agriculture_kpis.villages);
    $("#agri-area").textContent = fmtNum(d.agriculture_kpis.area)+" km²";
    $("#agri-rainfall").textContent = fmtNum(d.agriculture_kpis.rainfall)+" mm";
    $("#agri-workforce-total").textContent = fmtNum(d.agriculture_kpis.total_workers);
    $("#agri-women-work").textContent = fmtPct(d.agriculture_kpis.women_workforce);
    $("#agri-empty").classList.toggle("hidden",d.agriculture_kpis.villages>0);
    let p=labelsValues(d.population_by_taluka);
    makeChart("population-chart","bar",p.labels,[{data:p.values}],{horizontal:true,legend:false});
    let s=labelsValues(d.services);
    makeChart("services-chart","bar",s.labels,[{data:s.values}],{horizontal:true,legend:false,percent:true});
    let c=labelsValues(d.crop_area);
    makeChart("crop-chart","bar",c.labels,[{data:c.values}],{horizontal:true,legend:false});
    let l=labelsValues(d.literacy_by_taluka);
    makeChart("literacy-chart","bar",l.labels,[{data:l.values}],{horizontal:true,legend:false});
    let g=labelsValues(d.gender);
    makeChart("gender-chart","doughnut",g.labels,[{data:g.values}],{legend:true});
    let a=labelsValues(d.age);
    makeChart("age-chart","doughnut",a.labels,[{data:a.values}],{legend:true});
    let h=labelsValues(d.households_by_taluka);
    makeChart("households-chart","bar",h.labels,[{data:h.values}],{horizontal:true,legend:false});
    makeChart("people-literacy-chart","bar",l.labels,[{data:l.values}],{horizontal:true,legend:false});
    makeChart("services-detail-chart","bar",s.labels,[{data:s.values}],{horizontal:true,legend:false,percent:true});
    makeChart("agri-crop-chart","bar",c.labels,[{data:c.values}],{horizontal:true,legend:false});
    let irr=labelsValues(d.irrigation);
    makeChart("irrigation-chart","doughnut",irr.labels,[{data:irr.values}],{legend:true});
    let w=labelsValues(d.workforce);
    makeChart("agri-workforce-chart","bar",w.labels,[{data:w.values}],{horizontal:true,legend:false});
    if (currentPage==="explorer") loadVillages();
  } catch(e) { if(requestId===dashboardRequestId)toast(e.message, true); }
}
async function loadVillages() {
  const requestId=++explorerRequestId;
  try {
    const params = new URLSearchParams(queryString(true));
    params.set("page", explorerPage);
    params.set("per_page", explorerPageSize);
    params.set("sort", $("#sort-field").value);
    params.set("direction", $("#sort-direction").value);
    const d = await api("/api/villages?"+params.toString());
    if(requestId!==explorerRequestId)return;
    latestRows = d.rows || [];
    $("#table-count").textContent = `${fmtNum(d.total)} matching village records · ${fmtNum(latestRows.length)} on this page`;
    const columns = latestRows.length ? Object.keys(latestRows[0]) : ["Village","Taluka","Year","Population","Households","Literacy (%)","Internet access (%)","Main crop","Health facility"];
    $("#table-head").innerHTML = "<tr>"+columns.map(c=>`<th>${escapeHtml(c)}</th>`).join("")+"</tr>";
    $("#table-body").innerHTML = latestRows.length ? latestRows.map(row=>"<tr>"+columns.map(c=>`<td>${escapeHtml(row[c]===null||row[c]===undefined?"—":String(row[c]))}</td>`).join("")+"</tr>").join("") : `<tr><td colspan="${columns.length}" class="empty-cell">No records match these filters. Try resetting a filter or changing your search.</td></tr>`;
    $("#page-label").textContent=`Page ${d.page} of ${d.pages}`;
    $("#prev-page").disabled=d.page<=1;
    $("#next-page").disabled=d.page>=d.pages;
    $("#export-link").href="/api/export?"+queryString(true);
  } catch(e) { if(requestId===explorerRequestId)toast(e.message,true); }
}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));}
let searchTimer;
$("#table-search").addEventListener("input",()=>{clearTimeout(searchTimer);explorerPage=1;searchTimer=setTimeout(loadVillages,250);});
$("#prev-page").addEventListener("click",()=>{if(explorerPage>1){explorerPage--;loadVillages();}});
$("#next-page").addEventListener("click",()=>{explorerPage++;loadVillages();});
$("#sort-field").addEventListener("change",()=>{explorerPage=1;loadVillages();});
$("#sort-direction").addEventListener("change",()=>{explorerPage=1;loadVillages();});
function showPage(page) {
  currentPage=page;
  $$(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.page===page));
  $$(".content").forEach(el=>el.classList.add("hidden"));
  $(`#page-${page}`).classList.remove("hidden");
  const titles={overview:"Village overview",people:"People & households",services:"Education & infrastructure",agriculture:"Agriculture & work",explorer:"Data explorer",methodology:"Methodology",about:"About"};
  $("#topbar-title").textContent=titles[page]||"Village overview";
  $("#breadcrumb-page").textContent=page.toUpperCase();
  if(page==="explorer") loadVillages();
  // Charts first created in hidden panels need a resize when their panel becomes visible.
  requestAnimationFrame(() => Object.values(charts).forEach(chart => chart.resize()));
  if(window.innerWidth<760) $("#filterbar").classList.remove("open");
}
$$(".nav-item").forEach(b=>b.addEventListener("click",()=>showPage(b.dataset.page)));
boot();
