const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const numberFormat = new Intl.NumberFormat("en-IN", {maximumFractionDigits:0});
let charts = {};
let currentPage = "overview";
let sessionActive = false;
let csrfToken = "";
let lastDashboard = null;
let dashboardController = null;
let explorerController = null;
let filterController = null;
let dashboardRequestId = 0;
let explorerRequestId = 0;
let filterRequestId = 0;
let explorerPage = 1;
const pageSize = 25;
let metadata = null;
let selectedColumns = [];
const defaultColumns = ["Village_Name","Taluka","Population_Total","Households","Literacy_Rate_Percent","Households_Internet_Percent","Main_Crop","Health_Facility_Available","Household_Poverty_Rate_Percent","Year"];
const pages = new Set(["overview","people","services","agriculture","explorer","methodology","about"]);
const titles = {overview:"District overview",people:"Population",services:"Education & infrastructure",agriculture:"Agriculture & employment",explorer:"Data explorer",methodology:"Methodology",about:"About"};
const baseColor = "#176b50";
const compareColor = "#cf7654";
const categoryColors = ["#176b50","#cf7654","#b28a35","#6689a0","#7d9464","#8c6e9b","#4c9a9a","#a85e70"];

function toast(message, isError=false) {
  const el=$("#toast");
  el.textContent=message;
  el.className="toast show"+(isError?" error":"");
  el.setAttribute("role",isError?"alert":"status");
  el.setAttribute("aria-live",isError?"assertive":"polite");
  clearTimeout(toast.timer);
  toast.timer=setTimeout(()=>el.className="toast",isError?8500:4500);
}

function sessionExpired() {
  if(!sessionActive)return;
  sessionActive=false;
  Object.values(charts).forEach(chart=>chart.destroy());
  charts={};
  $("#app-screen").classList.add("hidden");
  $("#auth-screen").classList.remove("hidden");
  setAuthMode("login");
  toast("Your session expired. Please sign in again.",true);
}

async function api(url, options={}) {
  const headers={...(options.headers||{})};
  if(options.method && options.method!=="GET")headers["Content-Type"]="application/json";
  if(csrfToken && options.method && options.method!=="GET")headers["X-CSRF-Token"]=csrfToken;
  const res=await fetch(url,{credentials:"same-origin",...options,headers});
  const isJson=res.headers.get("content-type")?.includes("application/json");
  const data=isJson?await res.json():res;
  if(!res.ok){
    let expired=false;
    if(res.status===401 && sessionActive && !["/api/login","/api/signup","/api/forgot-password"].some(p=>url.startsWith(p))){sessionExpired();expired=true;}
    const error=new Error(data.error||"Something went wrong.");
    error.status=res.status;error.field=data.field||"";error.expired=expired;
    throw error;
  }
  return data;
}

function setAuthMode(mode){
  $("#login-form").classList.toggle("hidden",mode!=="login");
  $("#signup-form").classList.toggle("hidden",mode!=="signup");
  $("#forgot-form").classList.toggle("hidden",mode!=="forgot");
  $("#auth-tabs").classList.toggle("hidden",mode==="forgot");
  if(mode==="login"){
    $("#auth-eyebrow").textContent="YOUR WORKSPACE";$("#auth-title").textContent="Welcome back.";
    $("#auth-subtitle").textContent="Sign in, or explore the synthetic dataset as a guest.";
  }else if(mode==="signup"){
    $("#auth-eyebrow").textContent="GET STARTED";$("#auth-title").textContent="Create your account.";
    $("#auth-subtitle").textContent="A private workspace for exploring the data.";
  }else{
    $("#auth-eyebrow").textContent="ACCOUNT RECOVERY";$("#auth-title").textContent="Reset your password.";
    $("#auth-subtitle").textContent="Use the recovery code saved during registration.";
  }
}

function fieldErrorElement(form,field){
  const suffix=field==="full_name"?"name":field;
  return $$(".field-error",form).find(el=>el.id.endsWith("-"+suffix+"-error"));
}
function clearErrors(form){
  $$(".field-error",form).forEach(el=>{el.textContent="";el.classList.add("hidden");});
  $$("[aria-invalid=true]",form).forEach(el=>el.removeAttribute("aria-invalid"));
}
function showFieldError(form,field,message){
  const input=field?form.elements.namedItem(field):null;
  if(input && input.id){
    input.setAttribute("aria-invalid","true");
    const target=fieldErrorElement(form,field);
    if(target){target.textContent=message;target.classList.remove("hidden");input.focus();return;}
  }
  toast(message,true);
}
function formBusy(form,busy,workingText="Working…"){
  const button=$("button[type=submit]",form);
  if(!button)return;
  if(busy){button.dataset.originalText=button.textContent.trim();button.textContent=workingText;button.disabled=true;}
  else{button.textContent=button.dataset.originalText||button.textContent;button.disabled=false;}
}

$$(".auth-tab").forEach(button=>button.addEventListener("click",()=>setAuthMode(button.dataset.mode)));
$("#forgot-link").addEventListener("click",()=>setAuthMode("forgot"));
$("#back-login").addEventListener("click",()=>setAuthMode("login"));
$$('input').forEach(input=>input.addEventListener("input",()=>{
  input.removeAttribute("aria-invalid");
  const err=input.form?fieldErrorElement(input.form,input.name):null;
  if(err){err.textContent="";err.classList.add("hidden");}
}));
$("body").addEventListener("click",event=>{
  const button=event.target.closest(".password-toggle");if(!button)return;
  const input=$("#"+CSS.escape(button.dataset.target));if(!input)return;
  const visible=input.type==="password";input.type=visible?"text":"password";
  button.textContent=visible?"Hide":"Show";button.setAttribute("aria-label",visible?"Hide password":"Show password");button.setAttribute("aria-pressed",String(visible));
});

$("#signup-form").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget;clearErrors(form);formBusy(form,true,"Creating account…");
  try{
    const result=await api("/api/signup",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form).entries()))});
    form.reset();$("#generated-recovery-code").textContent=result.recovery_code;
    $("#recovery-dialog").showModal();
  }catch(error){if(!error.expired)showFieldError(form,error.field,error.message);}
  finally{formBusy(form,false);}
});
$("#recovery-continue").addEventListener("click",()=>{
  $("#recovery-dialog").close();$("#generated-recovery-code").textContent="";setAuthMode("login");
  toast("Account created. Sign in with your new Login ID.");
});
$("#copy-recovery").addEventListener("click",async()=>{
  const code=$("#generated-recovery-code").textContent;
  try{await navigator.clipboard.writeText(code);toast("Recovery code copied.");}
  catch{const range=document.createRange();range.selectNodeContents($("#generated-recovery-code"));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);toast("Select and copy the highlighted recovery code.",true);}
});
$("#download-recovery").addEventListener("click",()=>{
  const code=$("#generated-recovery-code").textContent;
  const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([`Sabarkantha Village Insights recovery code\n\n${code}\n\nKeep this code private. It is shown only once.\n`],{type:"text/plain"}));
  link.download="sabarkantha-recovery-code.txt";link.click();URL.revokeObjectURL(link.href);toast("Recovery code downloaded.");
});
$("#login-form").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget;clearErrors(form);formBusy(form,true,"Signing in…");
  try{const user=await api("/api/login",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form).entries()))});csrfToken=user.csrf_token||csrfToken;sessionActive=true;await enterApp(user);}
  catch(error){if(!error.expired)showFieldError(form,error.field,error.message);}
  finally{formBusy(form,false);}
});
$("#guest-button").addEventListener("click",async event=>{
  const button=event.currentTarget;button.disabled=true;
  try{const user=await api("/api/guest",{method:"POST",body:"{}"});csrfToken=user.csrf_token||csrfToken;sessionActive=true;await enterApp({...user,guest:true});}
  catch(error){toast(error.message,true);}
  finally{button.disabled=false;}
});
$("#forgot-form").addEventListener("submit",async event=>{
  event.preventDefault();const form=event.currentTarget;clearErrors(form);formBusy(form,true,"Resetting…");
  try{const result=await api("/api/forgot-password",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form).entries()))});form.reset();setAuthMode("login");toast(result.message);}
  catch(error){if(!error.expired)showFieldError(form,error.field,error.message);}
  finally{formBusy(form,false);}
});

function escapeHtml(value){return String(value).replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[char]));}
function setText(selector,value){const el=$(selector);if(el)el.textContent=value;}
function fmtNumber(value,digits=0){return Number(value||0).toLocaleString("en-IN",{minimumFractionDigits:digits,maximumFractionDigits:digits});}
function fmtPercent(value){return `${fmtNumber(value,1)}%`;}
function fmtUnit(value,unit){
  const digits=(unit==="km²"||unit==="km"||unit==="pp")?1:0;
  const label=unit==="pp"?"percentage points":unit;
  return `${fmtNumber(value,digits)}${label?` ${label}`:""}`;
}
function labelsValues(rows){return {labels:(rows||[]).map(item=>item.label),values:(rows||[]).map(item=>item.value)};}
function sum(rows){return (rows||[]).reduce((total,row)=>total+Number(row.value||0),0);}

function pageQuery(){
  const params=new URLSearchParams();
  params.set("view",currentPage);
  if($("#taluka-filter").value!=="All")params.set("taluka",$("#taluka-filter").value);
  if($("#village-filter").value!=="All")params.set("village",$("#village-filter").value);
  if($("#crop-filter").value!=="All")params.set("crop",$("#crop-filter").value);
  if(currentPage==="explorer"){
    if($("#table-search").value.trim())params.set("search",$("#table-search").value.trim());
    params.set("sort",$("#sort-field").value||"Village_Name");
    params.set("direction",$("#sort-direction").value||"desc");
    if(selectedColumns.length)params.set("columns",selectedColumns.join(","));
  }
  return params;
}
function syncUrl(push=false){
  const query=pageQuery().toString();
  const url=location.pathname+(query?`?${query}`:"");
  if(push)history.pushState({view:currentPage},"",url);else history.replaceState({view:currentPage},"",url);
}
async function restoreFromUrl(){
  const params=new URLSearchParams(location.search);
  const taluka=params.get("taluka")||"All";
  $("#taluka-filter").value=[...$("#taluka-filter").options].some(option=>option.value===taluka)?taluka:"All";
  await refreshVillageOptions();
  const village=params.get("village")||"All";
  $("#village-filter").value=[...$("#village-filter").options].some(option=>option.value===village)?village:"All";
  const crop=params.get("crop")||"All";
  $("#crop-filter").value=[...$("#crop-filter").options].some(option=>option.value===crop)?crop:"All";
  $("#table-search").value=params.get("search")||"";
  const direction=params.get("direction");if(direction)$("#sort-direction").value=direction;
  const sort=params.get("sort");if(sort && [...$("#sort-field").options].some(option=>option.value===sort))$("#sort-field").value=sort;
  const cols=params.get("columns");if(cols)selectColumns(cols.split(","));
  const view=pages.has(params.get("view"))?params.get("view"):"overview";
  showPage(view,false);
}

async function loadFilters(){
  const [filtersResult,meta]=await Promise.all([api("/api/filters"),api("/api/metadata")]);
  metadata=meta;
  const fill=(selector,values,first)=>{const el=$(selector);el.replaceChildren(new Option(first,"All"));values.forEach(value=>el.add(new Option(value,value)));};
  fill("#taluka-filter",filtersResult.talukas,"All talukas");
  fill("#crop-filter",filtersResult.crops,"All crops");
  updateVillageOptions(filtersResult.villages);
  const select=$("#sort-field");select.replaceChildren();
  const preferred=["Village_Name","Population_Total","Literacy_Rate_Percent","Households","Taluka","Main_Crop"];
  [...preferred,...meta.columns.map(item=>item.key).filter(key=>!preferred.includes(key))].forEach(key=>{
    const item=meta.columns.find(col=>col.key===key);if(item)select.add(new Option(item.label,key));
  });
  selectedColumns=defaultColumns.filter(key=>meta.columns.some(item=>item.key===key));
  renderColumnPicker(meta.columns);
}
function updateVillageOptions(values){
  const el=$("#village-filter"),previous=el.value;
  el.replaceChildren(new Option("All villages","All"));
  (values||[]).forEach(value=>el.add(new Option(value,value)));
  if((values||[]).includes(previous))el.value=previous;
}
async function refreshVillageOptions(){
  const id=++filterRequestId;
  if(filterController)filterController.abort();filterController=new AbortController();
  const taluka=$("#taluka-filter").value;const params=new URLSearchParams();if(taluka!=="All")params.set("taluka",taluka);
  const result=await api("/api/filters?"+params.toString(),{signal:filterController.signal});
  if(id===filterRequestId && taluka===$("#taluka-filter").value)updateVillageOptions(result.villages);
}

function renderColumnPicker(columns){
  const container=$("#column-options");container.replaceChildren();
  columns.forEach(item=>{
    const label=document.createElement("label"),input=document.createElement("input");
    input.type="checkbox";input.value=item.key;input.checked=selectedColumns.includes(item.key);
    input.addEventListener("change",()=>{
      if(input.checked){if(!selectedColumns.includes(item.key))selectedColumns.push(item.key);}
      else selectedColumns=selectedColumns.filter(key=>key!==item.key);
      if(!selectedColumns.length){input.checked=true;selectedColumns=[item.key];}
      updateColumnPickerSummary();explorerPage=1;syncUrl();loadVillages();
    });
    label.append(input,document.createTextNode(` ${item.label}`));container.append(label);
  });
  updateColumnPickerSummary();
}
function selectColumns(columns){
  if(!metadata)return;
  const valid=columns.filter(key=>metadata.columns.some(item=>item.key===key));
  if(valid.length)selectedColumns=[...new Set(valid)];
  $$("input[type=checkbox]",$("#column-options")).forEach(input=>input.checked=selectedColumns.includes(input.value));
  updateColumnPickerSummary();
}
function updateColumnPickerSummary(){setText("#column-summary",`Columns (${selectedColumns.length}/${metadata?.columns.length||0})`);}

function filterParams(includeSearch=false){
  const params=new URLSearchParams();
  if($("#taluka-filter").value!=="All")params.set("taluka",$("#taluka-filter").value);
  if($("#village-filter").value!=="All")params.set("village",$("#village-filter").value);
  if($("#crop-filter").value!=="All")params.set("crop",$("#crop-filter").value);
  if(includeSearch && $("#table-search").value.trim())params.set("search",$("#table-search").value.trim());
  return params;
}
function filtersChanged(){explorerPage=1;syncUrl();loadDashboard();}
$("#taluka-filter").addEventListener("change",async()=>{try{await refreshVillageOptions();filtersChanged();}catch(error){if(error.name!=="AbortError")toast(error.message,true);}});
$("#village-filter").addEventListener("change",filtersChanged);
$("#crop-filter").addEventListener("change",filtersChanged);
$("#reset-filters").addEventListener("click",async()=>{
  $("#taluka-filter").value="All";$("#village-filter").value="All";$("#crop-filter").value="All";
  $("#table-search").value="";explorerPage=1;
  try{await refreshVillageOptions();syncUrl();loadDashboard();}catch(error){if(error.name!=="AbortError")toast(error.message,true);}
});
$("#mobile-filter-toggle").addEventListener("click",()=>{
  const open=$("#filterbar").classList.toggle("open");$("#mobile-filter-toggle").setAttribute("aria-expanded",String(open));
});

function setLoading(loading){
  $("#dashboard-loading").classList.toggle("hidden",!loading);
  $("#app-screen").setAttribute("aria-busy",String(loading));
  if(loading)setText("#filter-status","Updating the selected summaries…");
  else setText("#filter-status","Taluka and village scope all summaries. Crop only scopes agriculture, employment and explorer rows.");
}

function setTakeaways(data){
  const k=data.kpis,allTalukas=$("#taluka-filter").value==="All";
  const talukas=data.population_by_taluka||[];
  const topTaluka=talukas[0],bottomTaluka=talukas.at(-1);
  const topVillage=(data.top_villages||[])[0],bottomVillage=(data.bottom_villages||[])[0];
  setText("#takeaway-population-taluka",topTaluka?`${topTaluka.label} has the largest selected population (${fmtNumber(topTaluka.value)} people).`:"No population data matches this scope.");
  if(allTalukas){
    setText("#takeaway-top-villages",topTaluka?`${topTaluka.label}: ${fmtNumber(topTaluka.value)} people.`:"No talukas match these filters.");
    setText("#takeaway-bottom-villages",bottomTaluka?`${bottomTaluka.label}: ${fmtNumber(bottomTaluka.value)} people.`:"No talukas match these filters.");
  }else{
    setText("#takeaway-top-villages",topVillage?`${topVillage.village}: ${fmtNumber(topVillage.value)} people in ${topVillage.taluka}.`:"No matching villages.");
    setText("#takeaway-bottom-villages",bottomVillage?`${bottomVillage.village}: ${fmtNumber(bottomVillage.value)} people in ${bottomVillage.taluka}.`:"No matching villages.");
  }
  setText("#takeaway-literacy-gender",`Women average ${fmtPercent(k.female_literacy)} vs men ${fmtPercent(k.male_literacy)}; gap ${fmtNumber(k.literacy_gap,1)} percentage points.`);
  const largestGap=[...data.gender_literacy_by_taluka].sort((a,b)=>b.gap-a.gap)[0];
  setText("#takeaway-literacy-gap",largestGap?`${largestGap.label} has the widest gap (${fmtNumber(largestGap.gap,1)} pp); district mean ${fmtNumber(k.literacy_gap,1)} pp.`:"No gap data.");
  const smallTotal=sum(data.population_size),under1000=data.population_size.filter(row=>["1–250","251–500","501–1,000"].includes(row.label)).reduce((n,row)=>n+row.value,0);
  setText("#takeaway-size",smallTotal?`${fmtPercent(under1000/smallTotal*100)} of selected villages have fewer than 1,001 residents.`:"No population data.");
  setText("#takeaway-age",`Population counts sum to ${fmtNumber(sum(data.age))} people.`);
  const utilities=[...data.utilities].sort((a,b)=>b.value-a.value),highUtility=utilities[0],lowUtility=utilities.at(-1);
  setText("#takeaway-utilities",highUtility&&lowUtility?`${highUtility.label} is highest (${fmtPercent(highUtility.value)}); ${lowUtility.label} is lowest (${fmtPercent(lowUtility.value)}).`:"No utility data.");
  const education=[...data.education_by_taluka].sort((a,b)=>a.attendance-b.attendance)[0];
  setText("#takeaway-education",education?`${education.label} has lowest school attendance (${fmtPercent(education.attendance)}). Chart compares attendance and maternal access.`:"No data.");
  const health=[...data.facility_heatmap].sort((a,b)=>(a["Health facility"]||0)-(b["Health facility"]||0))[0];
  setText("#takeaway-heatmap",health?`${health.taluka} reports the lowest health-facility availability (${fmtPercent(health["Health facility"]||0)} of villages).`:"Facility shares by taluka.");
  const poor=[...data.poverty_by_taluka].sort((a,b)=>b.value-a.value)[0];
  setText("#takeaway-poverty",poor?`${poor.label} has the highest mean rate (${fmtPercent(poor.value)}).`:"No poverty data.");
  const distant=[...data.distance_by_taluka].sort((a,b)=>b.district_km-a.district_km)[0];
  setText("#takeaway-distance",distant?`${distant.label} has the greatest mean distance to the district centre (${fmtNumber(distant.district_km,1)} km).`:"No distance data.");
  const largestCrop=[...data.crop_area].sort((a,b)=>b.value-a.value)[0];
  setText("#takeaway-crops",largestCrop?`${largestCrop.label} has the largest recorded area (${fmtNumber(largestCrop.value,1)} km²).`:"No crop-area records match these filters.");
  const irrigation=[...data.irrigation].sort((a,b)=>b.value-a.value)[0];
  setText("#takeaway-irrigation",irrigation?`${irrigation.label} is the leading source by village area (${fmtNumber(irrigation.value,1)} km²).`:"No irrigation records.");
  const workforce=[...data.workforce].sort((a,b)=>b.value-a.value)[0];
  setText("#takeaway-workforce",workforce?`${workforce.label}: ${fmtNumber(workforce.value)} workers in selected crop villages.`:"No employment records.");
  const soil=[...data.soil].sort((a,b)=>b.value-a.value)[0];
  setText("#takeaway-soil",soil?`${soil.label} is most common in ${fmtNumber(soil.value)} selected villages.`:"No soil records.");
}

function renderKpis(data){
  const k=data.kpis,a=data.agriculture_kpis;
  setText("#kpi-population",fmtNumber(k.population));setText("#kpi-villages",fmtNumber(k.villages));
  setText("#kpi-literacy-gap",`${fmtNumber(k.literacy_gap,1)} pp`);setText("#kpi-literacy",fmtPercent(k.literacy));
  setText("#finding-health",fmtPercent(k.health_facility));setText("#finding-bank",fmtPercent(k.bank));setText("#finding-solar",fmtPercent(k.solar));
  setText("#finding-digital-gap",`${fmtNumber(k.digital_gap,1)} pp`);setText("#finding-digital-detail",`Mobile ${fmtPercent(k.mobile)} · internet ${fmtPercent(k.internet)}`);setText("#finding-sex-ratio",fmtNumber(k.sex_ratio,1));
  setText("#finding-sc",fmtPercent(k.sc_share));setText("#finding-st",fmtPercent(k.st_share));
  setText("#finding-size",`${fmtNumber(k.median_population)} / ${fmtNumber(k.largest_population)}`);
  setText("#kpi-attendance",fmtPercent(k.school_attendance));setText("#kpi-maternal",fmtPercent(k.maternal_access));setText("#kpi-poverty",fmtPercent(k.poverty));
  setText("#agri-villages",fmtNumber(a.villages));setText("#agri-area",`${fmtNumber(a.area,1)} km²`);
  setText("#agri-rainfall",`${fmtNumber(a.rainfall,1)} mm`);setText("#agri-workers",fmtNumber(a.workers));setText("#agri-women-work",fmtPercent(a.women_workforce));
  $("#agri-empty").classList.toggle("hidden",a.villages>0);
}

const valueLabelsPlugin={
  id:"valueLabels",
  afterDatasetsDraw(chart,args,pluginOptions){
    const ctx=chart.ctx;ctx.save();ctx.font="600 11px Segoe UI, sans-serif";ctx.fillStyle="#324c3c";
    chart.data.datasets.forEach((dataset,index)=>{
      const meta=chart.getDatasetMeta(index);if(meta.type!=="bar")return;
      meta.data.forEach((element,i)=>{
        const value=dataset.data[i];if(value==null)return;
        const props=element.getProps(["x","y","base"],true);const text=fmtUnit(value,pluginOptions.unit||"");
        if(chart.options.indexAxis==="y"){
          const inside=props.x>chart.chartArea.right-48;ctx.textAlign=inside?"right":"left";ctx.textBaseline="middle";
          ctx.fillStyle=inside?"#fff":"#324c3c";ctx.fillText(text,inside?props.x-6:props.x+6,props.y);
        }else{ctx.textAlign="center";ctx.textBaseline="bottom";ctx.fillStyle="#324c3c";ctx.fillText(text,props.x,props.y-4);}
      });
    });ctx.restore();
  }
};
const referenceLinePlugin={
  id:"districtReferenceLine",
  afterDraw(chart,args,opts){
    if(opts?.value==null||!chart.chartArea)return;
    const horizontal=chart.options.indexAxis==="y",scale=horizontal?chart.scales.x:chart.scales.y;
    const pixel=scale.getPixelForValue(opts.value),ctx=chart.ctx,area=chart.chartArea;
    if(horizontal && (pixel<area.left||pixel>area.right))return;
    if(!horizontal && (pixel<area.top||pixel>area.bottom))return;
    ctx.save();ctx.strokeStyle="#bd684d";ctx.lineWidth=2;ctx.setLineDash([5,4]);ctx.beginPath();
    if(horizontal){ctx.moveTo(pixel,area.top);ctx.lineTo(pixel,area.bottom);}else{ctx.moveTo(area.left,pixel);ctx.lineTo(area.right,pixel);}ctx.stroke();ctx.setLineDash([]);
    ctx.font="600 10px Segoe UI, sans-serif";ctx.fillStyle="#8b4b36";ctx.textAlign="right";ctx.textBaseline="top";ctx.fillText(opts.label||"District mean",area.right-3,area.top+3);ctx.restore();
  }
};
let pluginsRegistered=false;
function ensurePlugins(){if(window.Chart&&!pluginsRegistered){Chart.register(valueLabelsPlugin,referenceLinePlugin);pluginsRegistered=true;}}
function ensureFallbackNode(canvas){
  let fallback=$(".chart-fallback",canvas.parentElement);
  if(!fallback){fallback=document.createElement("div");fallback.className="chart-fallback hidden";fallback.setAttribute("aria-hidden","true");canvas.insertAdjacentElement("afterend",fallback);}
  return fallback;
}
function chartDescription(canvas,labels,datasets,unit){
  const card=canvas.closest(".chart-card"),title=$("h3",card)?.textContent||canvas.getAttribute("aria-label")||"Chart";
  const altId=`${canvas.id}-text-alt`;let alt=$("#"+CSS.escape(altId));
  if(!alt){alt=document.createElement("p");alt.id=altId;alt.className="sr-only chart-text-alt";canvas.insertAdjacentElement("afterend",alt);}
  const rows=[];
  labels.forEach((label,index)=>rows.push(`${label}: ${datasets.map(ds=>`${ds.label?ds.label+" " : ""}${fmtUnit(ds.data[index],unit)}`).join("; ")}`));
  alt.textContent=`${title}. ${rows.join(". ")}`;
  canvas.setAttribute("aria-describedby",altId);
}
function fallbackChart(canvas,type,labels,datasets,options){
  const fallback=ensureFallbackNode(canvas);fallback.replaceChildren();fallback.classList.remove("hidden");canvas.classList.add("hidden");fallback.removeAttribute("aria-hidden");
  const max=Math.max(1,...datasets.flatMap(ds=>ds.data.map(Number)));
  labels.forEach((label,index)=>{
    const row=document.createElement("div");row.className="fallback-row";
    const labelEl=document.createElement("span");labelEl.className="fallback-label";labelEl.textContent=label;
    const values=document.createElement("div");values.className="fallback-values";
    datasets.forEach((dataset,series)=>{
      const value=Number(dataset.data[index]||0),item=document.createElement("div");item.className="fallback-series";
      const track=document.createElement("span");track.className="fallback-track";
      const bar=document.createElement("span");bar.className="fallback-bar";bar.style.width=`${Math.max(value>0?1:0,value/max*100)}%`;bar.style.backgroundColor=dataset.color||baseColor;track.append(bar);
      const text=document.createElement("span");text.className="fallback-value";text.textContent=`${dataset.label?dataset.label+": ":""}${fmtUnit(value,options.unit||"")}`;
      item.append(track,text);values.append(item);
    });
    row.append(labelEl,values);fallback.append(row);
  });
}
function makeChart(id,type,labels,datasets,options={}){
  const canvas=$("#"+CSS.escape(id));if(!canvas)return;
  if(charts[id]){charts[id].destroy();delete charts[id];}
  chartDescription(canvas,labels,datasets,options.unit||"");
  const fallback=ensureFallbackNode(canvas);
  if(!window.Chart){fallbackChart(canvas,type,labels,datasets,options);return;}
  fallback.classList.add("hidden");fallback.setAttribute("aria-hidden","true");canvas.classList.remove("hidden");ensurePlugins();
  const horizontal=Boolean(options.horizontal),isCircle=type==="doughnut";
  const colors=type==="doughnut"?datasets.map((_,i)=>categoryColors[i%categoryColors.length]):datasets.map(d=>d.color||baseColor);
  const chartData={labels,datasets:datasets.map((d,i)=>({
    label:d.label||"",data:d.data,backgroundColor:isCircle?colors[i]:colors[i],borderColor:isCircle?"#fff":colors[i],
    borderWidth:isCircle?2:0,borderRadius:type==="bar"?5:0,barThickness:type==="bar"?18:undefined,
    tension:.25,fill:false,pointRadius:3
  }))};
  const plugins={legend:{display:options.legend??(type==="doughnut"),position:"bottom",labels:{usePointStyle:true,boxWidth:8,padding:14,color:"#43584b",font:{size:12}}},
    tooltip:{backgroundColor:"#173d30",padding:11,titleFont:{weight:"700"},callbacks:{label:context=>{
      const val=horizontal?context.parsed.x:context.parsed.y;
      return `${context.dataset.label?context.dataset.label+": ":""}${fmtUnit(val,options.unit||"")}`;
    }}}};
  if(options.reference)plugins.districtReferenceLine=options.reference;
  const scales=isCircle?{}:{
    x:{beginAtZero:true,grid:{color:horizontal?"#edf1eb":"transparent"},border:{display:false},ticks:{color:"#58685f",font:{size:11},callback:value=>options.unit==="%"?`${value}%`:numberFormat.format(value)}},
    y:{beginAtZero:true,grid:{color:horizontal?"transparent":"#edf1eb"},border:{display:false},ticks:{color:"#43584b",font:{size:11}},...(options.percent&&!horizontal?{max:100}:{})}
  };
  if(options.percent&&horizontal)scales.x.max=100;
  charts[id]=new Chart(canvas,{type,data:chartData,options:{responsive:true,maintainAspectRatio:false,indexAxis:horizontal?"y":"x",layout:{padding:{top:type==="bar"&&!horizontal?18:8,right:options.unit==="%"?8:42}},plugins,scales,cutout:isCircle?"63%":undefined}});
}

function renderHeatmap(rows){
  const host=$("#facility-heatmap");host.replaceChildren();
  const fields=[...new Set(rows.flatMap(row=>Object.keys(row).filter(key=>key!=="taluka")))];
  if(!rows.length||!fields.length){host.textContent="No facility records match this geographic selection.";return;}
  const table=document.createElement("table");table.className="heatmap-table";
  const caption=document.createElement("caption");caption.textContent="Percent of village records reporting each facility by taluka";table.append(caption);
  const thead=document.createElement("thead"),header=document.createElement("tr"),blank=document.createElement("th");blank.scope="col";blank.textContent="Taluka";header.append(blank);
  fields.forEach(field=>{const th=document.createElement("th");th.scope="col";th.textContent=field;header.append(th);});thead.append(header);table.append(thead);
  const tbody=document.createElement("tbody");
  rows.forEach(row=>{const tr=document.createElement("tr"),th=document.createElement("th");th.scope="row";th.textContent=row.taluka;tr.append(th);
    fields.forEach(field=>{const value=Number(row[field]||0),td=document.createElement("td"),alpha=.08+(value/100)*.48;td.textContent=fmtPercent(value);td.style.backgroundColor=`rgba(23,107,80,${alpha})`;td.style.color=value>=60?"#fff":"#18392c";td.title=`${row.taluka}: ${field} available in ${fmtPercent(value)} of villages`;td.setAttribute("aria-label",td.title);tr.append(td);});tbody.append(tr);});
  table.append(tbody);host.append(table);
}

function renderCharts(data){
  const pop=labelsValues(data.population_by_taluka);
  makeChart("population-chart","bar",pop.labels,[{data:pop.values}],{horizontal:true,unit:"people"});
  const allTalukas=$("#taluka-filter").value==="All";
  const rankCards=$$("#top-villages-chart, #bottom-villages-chart").map(canvas=>canvas.closest(".chart-card"));
  const [topTitle,bottomTitle]=allTalukas?["Most populous talukas","Least populous talukas"]:["10 most populous villages","10 least populous villages"];
  rankCards.forEach((card,index)=>{const title=$("h3",card);if(title)title.textContent=index===0?topTitle:bottomTitle;});
  const topCanvas=$("#top-villages-chart"),bottomCanvas=$("#bottom-villages-chart");
  const topRows=allTalukas?(data.population_by_taluka||[]).slice(0,Math.ceil((data.population_by_taluka||[]).length/2)):(data.top_villages||[]);
  const bottomRows=allTalukas?(data.population_by_taluka||[]).slice(Math.ceil((data.population_by_taluka||[]).length/2)).reverse():(data.bottom_villages||[]);
  topCanvas.setAttribute("aria-label",allTalukas?"Talukas with the largest populations":"Villages with the largest populations in the selected taluka");
  bottomCanvas.setAttribute("aria-label",allTalukas?"Talukas with the smallest populations":"Villages with the smallest populations in the selected taluka");
  const topLabels=topRows.map(row=>allTalukas?row.label:`${row.village} · ${row.taluka}`);
  makeChart("top-villages-chart","bar",topLabels,[{data:topRows.map(row=>row.value),color:baseColor}],{horizontal:true,unit:"people"});
  const bottomLabels=bottomRows.map(row=>allTalukas?row.label:`${row.village} · ${row.taluka}`);
  makeChart("bottom-villages-chart","bar",bottomLabels,[{data:bottomRows.map(row=>row.value),color:compareColor}],{horizontal:true,unit:"people"});
  const literacy=[...(data.gender_literacy_by_taluka||[])].sort((a,b)=>b.gap-a.gap);
  makeChart("gender-literacy-chart","bar",literacy.map(row=>row.label),[
    {label:"Male literacy",data:literacy.map(row=>row.male),color:baseColor},
    {label:"Female literacy",data:literacy.map(row=>row.female),color:compareColor}
  ],{horizontal:true,unit:"%",percent:true,reference:{value:data.kpis.literacy,label:`District average ${fmtPercent(data.kpis.literacy)}`}});
  const gaps=[...literacy].sort((a,b)=>b.gap-a.gap);
  makeChart("literacy-gap-chart","bar",gaps.map(row=>row.label),[{data:gaps.map(row=>row.gap),color:compareColor}],{horizontal:true,unit:"pp",reference:{value:data.kpis.literacy_gap,label:`District mean ${fmtNumber(data.kpis.literacy_gap,1)} pp`}});
  const size=labelsValues(data.population_size);
  makeChart("population-size-chart","bar",size.labels,[{data:size.values}],{unit:"villages"});
  const age=labelsValues(data.age);
  makeChart("age-chart","doughnut",age.labels,[{data:age.values}],{legend:true,unit:"people"});
  const utilities=labelsValues([...data.utilities].sort((a,b)=>b.value-a.value));
  makeChart("utilities-chart","bar",utilities.labels,[{data:utilities.values}],{horizontal:true,unit:"%",percent:true});
  const education=[...(data.education_by_taluka||[])].sort((a,b)=>a.attendance-b.attendance);
  makeChart("education-chart","bar",education.map(row=>row.label),[
    {label:"Child school attendance",data:education.map(row=>row.attendance),color:baseColor},
    {label:"Maternal health access",data:education.map(row=>row.maternal),color:compareColor}
  ],{horizontal:true,unit:"%",percent:true});
  renderHeatmap(data.facility_heatmap||[]);
  const poverty=[...(data.poverty_by_taluka||[])].sort((a,b)=>b.value-a.value);
  makeChart("poverty-chart","bar",poverty.map(row=>row.label),[{data:poverty.map(row=>row.value),color:compareColor}],{horizontal:true,unit:"%",percent:true});
  const distance=[...(data.distance_by_taluka||[])].sort((a,b)=>b.district_km-a.district_km);
  makeChart("distance-chart","bar",distance.map(row=>row.label),[
    {label:"Taluka centre",data:distance.map(row=>row.taluka_km),color:baseColor},
    {label:"District centre",data:distance.map(row=>row.district_km),color:compareColor}
  ],{horizontal:true,unit:"km"});
  const crops=labelsValues(data.crop_area);
  makeChart("crop-chart","bar",crops.labels,[{data:crops.values}],{horizontal:true,unit:"km²"});
  const irrigation=labelsValues(data.irrigation);
  makeChart("irrigation-chart","doughnut",irrigation.labels,[{data:irrigation.values}],{legend:true,unit:"km²"});
  const workers=labelsValues([...data.workforce].sort((a,b)=>b.value-a.value));
  makeChart("workforce-chart","bar",workers.labels,[{data:workers.values}],{horizontal:true,unit:"workers"});
  const soil=labelsValues(data.soil);
  makeChart("soil-chart","bar",soil.labels,[{data:soil.values}],{horizontal:true,unit:"villages"});
}

async function loadDashboard(){
  const requestId=++dashboardRequestId;
  if(dashboardController)dashboardController.abort();dashboardController=new AbortController();
  setLoading(true);
  try{
    const data=await api("/api/dashboard?"+filterParams().toString(),{signal:dashboardController.signal});
    if(requestId!==dashboardRequestId)return;
    lastDashboard=data;renderKpis(data);setTakeaways(data);renderCharts(data);
    if(currentPage==="explorer")loadVillages();
  }catch(error){if(error.name!=="AbortError"&&requestId===dashboardRequestId)toast(error.message,true);}
  finally{if(requestId===dashboardRequestId)setLoading(false);}
}

function renderColumnCell(value,key){
  if(value===null||value===undefined)return "<span class=\"muted-cell\">—</span>";
  const isFlag=/_Available$|_Connected$/.test(key);
  if(isFlag && (value===0||value===1))return `<span class="value-badge ${value?"yes":"no"}">${value?"Yes":"No"}</span>`;
  if(typeof value==="number"){
    if(/Percent$/.test(key))return `${fmtNumber(value,1)}%`;
    if(/Latitude|Longitude/.test(key))return fmtNumber(value,4);
    if(Number.isInteger(value))return fmtNumber(value);
    return fmtNumber(value,1);
  }
  return escapeHtml(value);
}
function explorerParams({includeColumns=true,includeSearch=true}={}){
  const params=filterParams(includeSearch);
  params.set("page",String(explorerPage));params.set("per_page",String(pageSize));
  params.set("sort",$("#sort-field").value||"Village_Name");params.set("direction",$("#sort-direction").value||"desc");
  if(includeColumns)params.set("columns",selectedColumns.join(","));
  return params;
}
function updateExportLink(){
  const params=filterParams(true);
  if($("#export-mode").value==="visible")params.set("columns",selectedColumns.join(","));
  $("#export-link").href="/api/export?"+params.toString();
}
async function loadVillages(){
  const requestId=++explorerRequestId;
  if(explorerController)explorerController.abort();explorerController=new AbortController();
  try{
    const data=await api("/api/villages?"+explorerParams().toString(),{signal:explorerController.signal});
    if(requestId!==explorerRequestId)return;
    setText("#table-count",`${fmtNumber(data.total)} matching records · ${fmtNumber(data.rows.length)} on this page`);
    const head=$("#table-head");head.replaceChildren();const row=document.createElement("tr");
    data.columns.forEach(column=>{const th=document.createElement("th");th.scope="col";th.textContent=column.label;row.append(th);});head.append(row);
    const body=$("#table-body");body.replaceChildren();
    if(!data.rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=Math.max(1,data.columns.length);td.className="empty-cell";td.textContent="No village records match. Adjust the filters or search term.";tr.append(td);body.append(tr);}
    else data.rows.forEach(record=>{const tr=document.createElement("tr");data.columns.forEach(column=>{const td=document.createElement("td");td.innerHTML=renderColumnCell(record[column.key],column.key);tr.append(td);});body.append(tr);});
    setText("#page-label",`Page ${fmtNumber(data.page)} of ${fmtNumber(data.pages)}`);
    $("#prev-page").disabled=data.page<=1;$("#next-page").disabled=data.page>=data.pages;
    updateExportLink();
  }catch(error){if(error.name!=="AbortError"&&requestId===explorerRequestId)toast(error.message,true);}
}
let searchTimer;
$("#table-search").addEventListener("input",()=>{
  clearTimeout(searchTimer);explorerPage=1;syncUrl();searchTimer=setTimeout(loadVillages,250);
});
$("#sort-field").addEventListener("change",()=>{explorerPage=1;syncUrl();loadVillages();});
$("#sort-direction").addEventListener("change",()=>{explorerPage=1;syncUrl();loadVillages();});
$("#export-mode").addEventListener("change",()=>{syncUrl();updateExportLink();});
$("#prev-page").addEventListener("click",()=>{if(explorerPage>1){explorerPage--;loadVillages();}});
$("#next-page").addEventListener("click",()=>{explorerPage++;loadVillages();});

function showPage(page,updateHistory=true){
  if(!pages.has(page))page="overview";
  const changed=currentPage!==page;currentPage=page;
  $$(".nav-item").forEach(button=>button.classList.toggle("active",button.dataset.page===page));
  $$(".content").forEach(section=>section.classList.toggle("hidden",section.id!==`page-${page}`));
  setText("#topbar-title",titles[page]);setText("#breadcrumb-page",page.replaceAll("-"," ").toUpperCase());
  if(updateHistory)syncUrl(changed);
  if(page==="explorer")loadVillages();
  requestAnimationFrame(()=>Object.values(charts).forEach(chart=>chart.resize()));
  if(innerWidth<760){$("#filterbar").classList.remove("open");$("#mobile-filter-toggle").setAttribute("aria-expanded","false");}
}
$$('.nav-item').forEach(button=>button.addEventListener("click",()=>showPage(button.dataset.page,true)));
window.addEventListener("popstate",async()=>{
  if(!sessionActive)return;
  try{await restoreFromUrl();loadDashboard();}catch(error){if(error.name!=="AbortError")toast(error.message,true);}
});

async function enterApp(user){
  $("#auth-screen").classList.add("hidden");$("#app-screen").classList.remove("hidden");
  setText("#user-name",user.user||"User");setText("#user-id",user.guest?"Read-only preview":`@${user.username||"user"}`);
  setText("#user-avatar",(user.user||"U").trim().charAt(0).toUpperCase());
  $("#guest-pill").classList.toggle("hidden",!user.guest);
  await loadFilters();await restoreFromUrl();await loadDashboard();
}
$("#logout-btn").addEventListener("click",async()=>{
  try{await api("/api/logout",{method:"POST",body:"{}"});}catch(error){}
  sessionActive=false;csrfToken="";Object.values(charts).forEach(chart=>chart.destroy());charts={};
  $("#app-screen").classList.add("hidden");$("#auth-screen").classList.remove("hidden");setAuthMode("login");
});

function startChartJs(){
  if(window.Chart)return;
  const script=document.createElement("script");script.src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js";script.crossOrigin="anonymous";
  script.onload=()=>{if(lastDashboard)renderCharts(lastDashboard);};
  script.onerror=()=>{if(lastDashboard)renderCharts(lastDashboard);};
  document.head.append(script);
  setTimeout(()=>{if(lastDashboard&&!window.Chart)renderCharts(lastDashboard);},1800);
}

async function boot(){
  startChartJs();
  try{
    const state=await api("/api/session");csrfToken=state.csrf_token||"";sessionActive=state.authenticated;
    if(state.authenticated)await enterApp({user:state.user,username:state.username,guest:state.guest});
    else syncUrl(false);
  }catch(error){toast("Could not start the dashboard. Check that Flask is running and refresh.",true);}
}
boot();
