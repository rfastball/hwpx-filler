(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const actions = window.documentActions;
  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const employees = [
    {id:1,name:"김민수",department:"인사운영팀",date:"2026-07-25",salary:4200000,bonus:350000,performanceBonus:350000,company:"가람상사",item:"업무용 노트북",quantity:3,amount:4650000},
    {id:2,name:"이서연",department:"재정기획팀",date:"2026-07-25",salary:3850000,bonus:0,performanceBonus:0,company:"나래기획",item:"회의실 모니터",quantity:2,amount:1280000},
    {id:3,name:"박준호",department:"민원지원팀",date:"2026-07-25",salary:4010000,bonus:220000,performanceBonus:220000,company:"다온유통",item:"문서 보관함",quantity:12,amount:960000},
    {id:4,name:"최유진",department:"정보화담당관",date:"2026-07-25",salary:4480000,bonus:180000,performanceBonus:180000,company:"라온테크",item:"보안 키보드",quantity:8,amount:704000},
    {id:5,name:"정하늘",department:"정책홍보팀",date:"2026-07-25",salary:3960000,bonus:0,performanceBonus:0,company:"마루산업",item:"홍보물 인쇄",quantity:500,amount:1250000}
  ];
  const customers = [
    {id:101,name:"한빛복지관",contact:"오지현",phone:"02-710-2210",requestDate:"2026-07-28",amount:1800000},
    {id:102,name:"푸른도서관",contact:"강현우",phone:"02-710-2232",requestDate:"2026-07-29",amount:950000},
    {id:103,name:"새봄센터",contact:"윤하린",phone:"02-710-2251",requestDate:"2026-07-30",amount:2300000}
  ];
  const scenarios = {
    normal:{file:"7월_급여자료.xlsx",meta:"직원 5건 · 열 9개",status:"직원 데이터로 인식됨",kind:"employee"},
    newField:{file:"7월_급여자료_성과급추가.xlsx",meta:"직원 5건 · 새 열 ‘성과급’ 감지",status:"새 필드 감지",kind:"employee"},
    missing:{file:"7월_급여자료_성명누락.xlsx",meta:"직원 5건 · 필수 열 ‘성명’ 없음",status:"필수 필드 누락",kind:"employee"},
    customer:{file:"고객_요청목록.csv",meta:"고객 3건 · 처음 보는 데이터 형식",status:"새 데이터 형식",kind:"customer"}
  };
  const baseColumns = [
    {key:"name",label:"성명",type:"text"},{key:"department",label:"소속부서",type:"text"},
    {key:"date",label:"급여기준일",type:"date"},{key:"salary",label:"기본급",type:"amount"},
    {key:"bonus",label:"상여금",type:"amount"},{key:"company",label:"업체명",type:"text"},
    {key:"item",label:"요청 품목",type:"text"},{key:"quantity",label:"수량",type:"amount"},
    {key:"amount",label:"요청 금액",type:"amount"}
  ];
  const customerColumns = [
    {key:"name",label:"고객명",type:"text"},{key:"contact",label:"담당자",type:"text"},
    {key:"phone",label:"연락처",type:"text"},{key:"requestDate",label:"요청일",type:"date"},
    {key:"amount",label:"예상 금액",type:"amount"}
  ];
  const works = {
    salary:{id:"salary",name:"급여명세서",templatePath:"templates/salary.hwpx",dataset:"직원 데이터",filenamePattern:"{성명}_급여명세서",templateRevision:1,bindingRevision:1},
    order:{id:"order",name:"발주 요청문",templatePath:"templates/order.txt",dataset:"직원 데이터",filenamePattern:null,templateRevision:1,bindingRevision:1},
    employment:{id:"employment",name:"재직증명서",templatePath:"templates/employment.hwpx",dataset:"직원 데이터",filenamePattern:"{성명}_재직증명서",templateRevision:1,bindingRevision:1}
  };
  const fieldDefs = {
    salary:[
      {key:"name",label:"이름",required:true,source:"name",type:"text",format:"raw"},
      {key:"date",label:"지급일",required:true,source:"date",type:"date",format:"dateDot"},
      {key:"salary",label:"기본급",required:true,source:"salary",type:"amount",format:"won"},
      {key:"bonus",label:"상여금",required:false,source:"bonus",type:"amount",format:"won"}
    ],
    order:[
      {key:"company",label:"업체명",required:true,source:"company",type:"text",format:"raw"},
      {key:"item",label:"요청 품목",required:true,source:"item",type:"text",format:"raw"},
      {key:"quantity",label:"수량",required:true,source:"quantity",type:"amount",format:"number"},
      {key:"amount",label:"요청 금액",required:false,source:"amount",type:"amount",format:"won"}
    ],
    employment:[
      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
      {key:"department",label:"소속",required:true,source:"department",type:"text",format:"raw"},
      {key:"date",label:"발급 기준일",required:false,source:"date",type:"date",format:"dateDot"}
    ]
  };
  const bindings = Object.fromEntries(Object.entries(fieldDefs).map(([workId, fields]) => [
    workId,
    Object.fromEntries(fields.map((field) => [field.key, {
      source:field.source,type:field.type,format:field.format,constant:"",provenance:"saved",intentionallyUnused:false
    }]))
  ]));
  const formatCatalog = {
    text:[["raw","원문 그대로"],["phone","전화번호"]],
    date:[["dateDot","2026. 07. 25."],["dateLongKo","2026년 7월 25일"],["dateDash","2026-07-25"]],
    amount:[["won","4,200,000원"],["number","4,200,000"]],
    const:[["raw","입력한 값 그대로"]]
  };
  const typeLabels = {text:"텍스트",date:"날짜",amount:"금액",const:"직접 입력"};

  const state = {
    view:"data",scenario:"normal",outcome:"success",records:employees,selected:new Set(employees.map((r)=>r.id)),
    search:"",activeWorkId:"salary",validation:{status:"pending",id:null},preview:{open:false,index:0,status:"idle",required:false,approved:false,id:null},
    bindings,runOverrides:{},dismissedSuggestions:new Set(),result:null,librarySearch:"",
    editContext:null,editSession:null,pendingTab:null,lastEditorTrigger:null,returnMarker:null,
    workIndex:0,workMode:"filled",workPatch:{},workValues:{},copied:new Set(),review:new Set(),
    menuTrigger:null,resultMenuTrigger:null,newWorkDraft:null,pendingActiveValidation:null
  };
  window.v4PrototypeState = state;
  const mediaFor = (workId) => works[workId].templatePath.toLowerCase().endsWith(".txt") ? "txt" : "hwpx";
  const currentColumns = () => state.scenario === "customer" ? customerColumns : state.scenario === "missing" ? baseColumns.filter((c)=>c.key!=="name") : state.scenario === "newField" ? [...baseColumns,{key:"performanceBonus",label:"성과급",type:"amount"}] : baseColumns;
  const selectedRecords = () => state.records.filter((record)=>state.selected.has(record.id));
  const workLabel = (workId) => mediaFor(workId)==="txt" ? "텍스트 검토·복사" : "HWPX 일괄 생성";
  const cloneSet = (set) => new Set([...set]);
  const fieldDef = (workId, key) => fieldDefs[workId]?.find((field)=>field.key===key);
  const toast = (message) => {$("toast").textContent=message;$("toast").classList.add("on");window.setTimeout(()=>$("toast").classList.remove("on"),2200)};

  function showScreen(view) {
    state.view=view;
    document.querySelectorAll(".screen").forEach((screen)=>screen.classList.toggle("on",screen.id===`screen-${view}`));
    $("topbar").hidden=view==="workbench";
    document.querySelectorAll("[data-nav]").forEach((button)=>button.setAttribute("aria-current",button.dataset.nav===view?"page":"false"));
    if(view==="data"&&state.pendingActiveValidation){
      $("dataNotice").hidden=false;$("dataNotice").textContent=state.pendingActiveValidation;
      state.pendingActiveValidation=null;requestValidation();
    }
  }
  function columnsForOptions(selected) {
    const list=[`<option value="">연결 안 함</option>`,`<option value="__direct__">직접 입력</option>`];
    if(selected&&!["__direct__"].includes(selected)&&!currentColumns().some((column)=>column.key===selected))list.push(`<option value="${esc(selected)}" selected>${esc(selected)} · 현재 없음</option>`);
    currentColumns().forEach((column)=>list.push(`<option value="${column.key}" ${column.key===selected?"selected":""}>${esc(column.label)}</option>`));
    return list.join("");
  }
  function formatValue(value, format) {
    if(value===null||value===undefined||value==="")return "—";
    if(format==="dateLongKo"){const [y,m,d]=String(value).split("-");return `${y}년 ${Number(m)}월 ${Number(d)}일`}
    if(format==="dateDot"){const [y,m,d]=String(value).split("-");return `${y}. ${m}. ${d}.`}
    if(format==="dateDash")return String(value);
    if(format==="won")return `${new Intl.NumberFormat("ko-KR").format(Number(value))}원`;
    if(format==="number")return new Intl.NumberFormat("ko-KR").format(Number(value));
    if(format==="phone")return String(value);
    return String(value);
  }
  function effectiveField(workId,key,recordId=null) {
    const base=clone(state.bindings[workId][key]);
    const override=state.runOverrides[workId]?.fields?.[key];
    return override ? {...base,...clone(override)} : base;
  }
  function valueFor(workId,key,record,binding=effectiveField(workId,key,record.id)) {
    if(binding.source==="__direct__")return binding.constant;
    return record?.[binding.source];
  }
  function filenameFor(workId,record) {
    const recordOverride=state.runOverrides[workId]?.records?.[record.id]?.filename;
    if(recordOverride)return recordOverride;
    const pattern=state.runOverrides[workId]?.filenamePattern ?? works[workId].filenamePattern ?? works[workId].name;
    const name=record.name||record.contact||"항목";
    return pattern.replaceAll("{성명}",name).replaceAll("{고객명}",record.name||"고객").replaceAll("{담당자}",record.contact||"담당자")+".hwpx";
  }
  function currentIssue() {
    if(state.scenario==="newField"&&!state.dismissedSuggestions.has("newField:salary"))return "newField";
    if(state.scenario==="missing"&&!state.bindings.salary.name.source)return "missing";
    if(state.scenario==="missing")return "missing";
    return null;
  }
  function makeReturn(surface, extra={}) {
    return {surface,previewIndex:state.preview.index,focusTarget:null,scrollTarget:null,reopenDrawer:surface==="preview",workIndex:state.workIndex,workMode:state.workMode,search:state.search,librarySearch:state.librarySearch,...extra};
  }
  function makeContext({workId,section,target={kind:"none",id:null},entryReason="voluntary",evidence={},returnContext,initialPatch=null}) {
    return {workId,section,target,entryReason,evidence,returnContext,initialPatch};
  }
  function baseSnapshot(workId) {
    return {binding:clone(state.bindings[workId]),filenamePattern:works[workId].filenamePattern,templateRevision:works[workId].templateRevision,bindingRevision:works[workId].bindingRevision};
  }
  function inheritedOverrides(workId) {
    return clone(state.runOverrides[workId]||{fields:{},records:{}});
  }
  function createEditSession(context) {
    return {baseSnapshot:baseSnapshot(context.workId),inheritedRunOverrides:inheritedOverrides(context.workId),patch:context.initialPatch?clone(context.initialPatch):null,dirtySection:context.initialPatch?context.section:null,userConfirmed:new Set(),draftWork:works[context.workId].draft===true};
  }
  function effectiveDraft() {
    const session=state.editSession,context=state.editContext,base=clone(session.baseSnapshot);
    Object.entries(session.inheritedRunOverrides.fields||{}).forEach(([key,value])=>base.binding[key]={...base.binding[key],...value});
    if(session.inheritedRunOverrides.filenamePattern)base.filenamePattern=session.inheritedRunOverrides.filenamePattern;
    const patch=session.patch;
    if(patch?.section==="binding")Object.entries(patch.changes).forEach(([key,value])=>base.binding[key]={...base.binding[key],...value});
    if(patch?.section==="filename"&&patch.changes.filenamePattern!==undefined)base.filenamePattern=patch.changes.filenamePattern;
    return base;
  }
  function patchSummary() {
    const patch=state.editSession?.patch;if(!patch)return "변경 없음";
    if(patch.section==="binding")return Object.keys(patch.changes).map((key)=>fieldDef(state.editContext.workId,key)?.label||key).join(", ")+" 규칙";
    if(patch.section==="filename")return "파일 이름 규칙";
    if(patch.section==="template")return "템플릿 판본 후보";
    return "현재 변경";
  }
  function activeRunContext(context=state.editContext) {
    return context&&state.activeWorkId===context.workId&&["preview","data","result","workbench"].includes(context.returnContext.surface);
  }
  function scopeActions() {
    const context=state.editContext,patch=state.editSession?.patch;
    if(!context||!patch)return {primary:null,secondary:null};
    if(context.section==="template")return {primary:{scope:"default",label:"새 템플릿 판본으로 저장"},secondary:{scope:"fork",label:"별도 작업으로 만들기"}};
    if(context.returnContext.surface==="library")return {primary:{scope:"default",label:"변경 저장"},secondary:null};
    if(activeRunContext(context))return {primary:{scope:"run",label:"이번 생성에 적용"},secondary:{scope:"default",label:"기본 규칙으로 저장…"}};
    return {primary:{scope:"default",label:"변경 저장"},secondary:null};
  }

  function renderRecords() {
    const customer=state.scenario==="customer";
    $("recordHead").innerHTML=customer?`<tr><th><input id="selectAll" type="checkbox" aria-label="전체 항목 선택"></th><th>고객명</th><th>담당자</th><th>요청일</th><th>예상 금액</th></tr>`:`<tr><th><input id="selectAll" type="checkbox" aria-label="전체 항목 선택"></th><th>성명</th><th>부서</th><th>기준일</th><th>기본급</th></tr>`;
    const query=state.search.trim().toLowerCase();
    const filtered=state.records.filter((record)=>Object.values(record).some((value)=>String(value).toLowerCase().includes(query)));
    $("recordBody").innerHTML=filtered.map((record)=>customer
      ?`<tr class="${state.selected.has(record.id)?"selected":""}"><td><input type="checkbox" data-record="${record.id}" ${state.selected.has(record.id)?"checked":""} aria-label="${esc(record.name)} 선택"></td><td>${esc(record.name)}</td><td>${esc(record.contact)}</td><td>${esc(record.requestDate)}</td><td>${formatValue(record.amount,"won")}</td></tr>`
      :`<tr class="${state.selected.has(record.id)?"selected":""}"><td><input type="checkbox" data-record="${record.id}" ${state.selected.has(record.id)?"checked":""} aria-label="${esc(record.name)} 선택"></td><td>${esc(state.scenario==="missing"?"열 없음":record.name)}</td><td>${esc(record.department)}</td><td>${esc(record.date)}</td><td>${formatValue(record.salary,"won")}</td></tr>`
    ).join("");
    const selectAll=$("selectAll");if(selectAll){selectAll.checked=state.selected.size===state.records.length;selectAll.indeterminate=state.selected.size>0&&state.selected.size<state.records.length}
    $("selectionTitle").textContent=`${state.selected.size}건 선택`;
    $("selectionType").textContent=customer?`고객 ${state.selected.size}곳`:`직원 ${state.selected.size}명`;
  }
  function workMenuItems(workId) {
    const common=[["template","템플릿 열기"],["binding","필드 연결·표시 수정"]];
    if(mediaFor(workId)==="hwpx")common.push(["filename","파일 이름 규칙"]);
    return common;
  }
  function renderWorkChooser() {
    const customer=state.scenario==="customer"&&!works[state.activeWorkId]?.dataset.startsWith("고객");
    $("customerEmpty").hidden=!customer;$("workList").hidden=customer;$("validationCard").hidden=customer;$("runButton").hidden=customer;$("previewButton").hidden=customer;
    if(customer){$("workCount").textContent="일치 작업 없음";return}
    const eligible=Object.values(works).filter((work)=>state.scenario==="customer"?work.dataset.startsWith("고객"):!work.dataset.startsWith("고객"));
    $("workCount").textContent=`${eligible.length}건 준비됨`;
    $("workList").innerHTML=eligible.map((work)=>`<div class="work-item ${state.activeWorkId===work.id?"selected":""}" data-work-card="${work.id}"><button type="button" data-select-work="${work.id}"><strong>${esc(work.name)}</strong><span>${esc(work.dataset)} · ${workLabel(work.id)} · 연결 ${hasRequiredIssue(work.id)?"확인 필요":"정상"}</span></button><button class="icon-button" type="button" data-work-menu="${work.id}" aria-label="${esc(work.name)} 변경 메뉴" aria-expanded="false">⋯</button></div>`).join("");
  }
  function renderEvidence() {
    $("compatNote").hidden=false;
    if(state.scenario==="newField"){
      $("compatTitle").textContent="새 ‘성과급’ 열을 발견했습니다.";
      $("compatText").textContent=state.dismissedSuggestions.has("newField:salary")?"이번 분석에서는 사용하지 않도록 표시했습니다. 기존 Binding은 유지되며 실행을 막지 않습니다.":"급여명세서의 ‘상여금’에 연결할 수 있습니다. 추천은 아직 저장된 연결이 아닙니다.";
      $("compatPrimary").hidden=state.dismissedSuggestions.has("newField:salary");$("compatSecondary").hidden=state.dismissedSuggestions.has("newField:salary");
      $("compatPrimary").textContent="상여금에 연결";$("compatSecondary").textContent="이번에는 사용하지 않음";
    }else if(state.scenario==="missing"){
      const repaired=state.activeWorkId==="salary"&&!hasRequiredIssue("salary");
      const source=effectiveField("salary","name").source;
      const sourceLabel=currentColumns().find((column)=>column.key===source)?.label||source;
      $("compatTitle").textContent=repaired?"‘이름’ 연결을 복구했습니다.":"현재 데이터에서 ‘성명’ 열을 찾을 수 없습니다.";
      $("compatText").textContent=repaired?`현재 적용: 이름 ← ${sourceLabel}. 원본 ‘성명’ 열은 없지만 선택한 대체 열로 검증했습니다.`:"급여명세서의 ‘이름’ 필드가 영향을 받습니다. 기존 연결: 이름 ← 성명";
      $("compatPrimary").hidden=false;$("compatSecondary").hidden=false;$("compatPrimary").textContent=repaired?"이름 연결 다시 확인":"이름 연결 복구";$("compatSecondary").textContent="원본 파일에서 수정";
    }else if(state.scenario==="customer"){
      $("compatTitle").textContent="처음 보는 고객 데이터입니다.";
      $("compatText").textContent="기존 문서 작업의 연결을 덮어쓰지 않습니다. 새 작업을 만든 뒤 현재 선택으로 검증합니다.";
      $("compatPrimary").hidden=true;$("compatSecondary").hidden=true;
    }else{
      $("compatTitle").textContent="정상 반복 실행";
      $("compatText").textContent="필수 연결이 유효합니다. 미리보기는 선택이며 자동 검증 뒤 바로 생성할 수 있습니다.";
      $("compatPrimary").hidden=true;$("compatSecondary").hidden=true;
    }
  }
  function hasRequiredIssue(workId) {
    if(state.scenario!=="missing")return false;
    return fieldDefs[workId]?.some((field)=>{
      if(!field.required)return false;
      const binding=effectiveField(workId,field.key);
      return !binding.source||(binding.source!=="__direct__"&&!currentColumns().some((column)=>column.key===binding.source));
    });
  }
  function renderValidation() {
    const bad=hasRequiredIssue(state.activeWorkId),pending=state.validation.status==="pending";
    $("validationCard").dataset.state=bad?"bad":pending?"pending":"ready";
    $("validationMark").textContent=bad?"!":pending?"…":"✓";
    $("validationTitle").textContent=bad?"생성할 수 없음":pending?"자동 검증 중":"실행 준비 완료";
    $("validationText").textContent=bad?"필수 이름 필드의 원본 열을 찾을 수 없습니다.":pending?"선택, 연결, 표시 결과를 확인합니다.":state.preview.required&&!state.preview.approved?"새 작업 또는 기본 규칙 변경 · 결과 확인 필요":"연결과 표시 결과가 정상입니다.";
    const gated=state.preview.required&&!state.preview.approved;
    $("runButton").disabled=bad||pending||!state.selected.size||gated;
    $("runButton").textContent=mediaFor(state.activeWorkId)==="txt"?"검토·복사 시작":`${state.selected.size}개 생성`;
    $("previewButton").textContent=gated?"결과 확인 필요":"미리보기";
  }
  function renderData() {
    const scenario=scenarios[state.scenario];$("fileName").textContent=scenario.file;$("fileMeta").textContent=scenario.meta;$("fileStatus").textContent=scenario.status;
    renderRecords();renderEvidence();renderWorkChooser();renderValidation();
    $("workflowState").textContent=state.validation.status==="pending"?"검증 중":hasRequiredIssue(state.activeWorkId)?"교정 필요":"준비됨";
    $("workflowMessage").textContent=state.preview.required&&!state.preview.approved?"변경 결과를 확인해야 실행할 수 있습니다.":"선택과 이전 성공 상태를 유지합니다.";
    renderResult();
  }
  async function requestValidation() {
    if(!state.activeWorkId||state.scenario==="customer"&&!works[state.activeWorkId]?.dataset.startsWith("고객"))return;
    state.validation={status:"pending",id:null};renderValidation();
    if(hasRequiredIssue(state.activeWorkId)){state.validation={status:"failed",id:null};renderValidation();return}
    try{
      const result=await actions.validateRun({selectedCount:state.selected.size,documentId:state.activeWorkId,bindingRevision:works[state.activeWorkId].bindingRevision});
      state.validation={status:"completed",id:result.validationId};renderData();
    }catch(error){state.validation={status:"failed",id:null};showNotice(error.message,"bad")}
  }
  function showNotice(message,type=""){$("dataNotice").hidden=false;$("dataNotice").className=`notice ${type}`;$("dataNotice").textContent=message}

  function openMenu(workId,trigger) {
    const menu=$("objectMenu");state.menuTrigger=trigger;
    menu.innerHTML=workMenuItems(workId).map(([section,label])=>`<button type="button" role="menuitem" data-menu-open="${section}" data-menu-work="${workId}">${label}</button>`).join("");
    menu.hidden=false;trigger.setAttribute("aria-expanded","true");menu.querySelector("button")?.focus();
  }
  function closeMenu(restore=false) {
    $("objectMenu").hidden=true;if(state.menuTrigger){state.menuTrigger.setAttribute("aria-expanded","false");if(restore)state.menuTrigger.focus()}state.menuTrigger=null;
  }
  function libraryReturn(workId) {return {surface:"library",librarySearch:state.librarySearch,focusTarget:`library-${workId}`,scrollY:window.scrollY}}
  function renderLibrary() {
    const query=state.librarySearch.toLowerCase();
    $("libraryGrid").innerHTML=Object.values(works).filter((work)=>work.name.toLowerCase().includes(query)).map((work)=>`<article class="library-card" id="library-${work.id}"><span class="badge">${mediaFor(work.id).toUpperCase()}</span><h2>${esc(work.name)}</h2><p>${esc(work.dataset)} · ${workLabel(work.id)} · Binding r${work.bindingRevision}</p><button class="button" type="button" data-library-open="${work.id}">작업 열기</button></article>`).join("");
  }

  function bannerContent(context) {
    const labels={preview_result:`미리보기 ${Number(context.returnContext.previewIndex)+1}/${selectedRecords().length}에서 열었습니다.`,schema_new_field:"새 데이터 열에서 열었습니다.",schema_missing_field:"필수 필드 누락에서 열었습니다.",run_failure:"실패한 실행에서 열었습니다.",workbench_result:`작업대 ${Number(context.returnContext.workIndex)+1}/${state.records.length}에서 열었습니다.`,library:"문서 작업 목록에서 열었습니다.",voluntary:""};
    return labels[context.entryReason]||"";
  }
  function renderEditorChrome() {
    const context=state.editContext,work=works[context.workId],dirty=Boolean(state.editSession.patch);
    $("editorTitle").textContent=work.name;$("editorSubtitle").textContent=`${work.dataset} · ${workLabel(work.id)} · ${work.templatePath}`;
    $("saveState").textContent=dirty?"저장하지 않은 변경":"저장됨";
    const banner=bannerContent(context);$("contextBanner").hidden=!banner;
    $("contextTitle").textContent=banner;$("contextMessage").textContent=context.evidence.message||"";
    $("contextReturn").textContent={preview:"미리보기로 돌아가기",data:"데이터로 돌아가기",result:"실패 결과로 돌아가기",workbench:"작업대로 돌아가기",library:"문서 작업 목록으로 돌아가기"}[context.returnContext.surface]||"원래 업무로 돌아가기";
    $("evidenceGrid").innerHTML=Object.entries(context.evidence).filter(([,value])=>value!==null&&value!==undefined&&value!=="").map(([key,value])=>`<span><strong>${esc({rawValue:"원본 값",displayValue:"현재 표시",sourceField:"원본 열",failedFile:"실패 파일",confirmedCause:"확인된 원인",label:"대상",sampleValues:"샘플 값"}[key]||key)}</strong> ${esc(value)}</span>`).join("");
    document.querySelectorAll("[data-tab]").forEach((button)=>{
      const hide=button.dataset.tab==="filename"&&mediaFor(context.workId)==="txt";button.hidden=hide;
      const selected=button.dataset.tab===context.section;button.setAttribute("aria-selected",String(selected));button.tabIndex=selected?0:-1;
    });
    document.querySelectorAll(".editor-panel").forEach((panel)=>panel.classList.toggle("on",panel.id===`panel-${context.section}`));
  }
  function renderTemplate() {
    const context=state.editContext,work=works[context.workId],isText=mediaFor(work.id)==="txt";
    $("templateKicker").textContent=isText?"TXT 토큰 개요":"HWPX 구조 개요";$("templateName").textContent=work.name;
    $("templateBoundary").textContent=isText?"텍스트 템플릿 본문 편집기는 아직 연결되지 않았습니다. 토큰 구조만 정직하게 표시합니다.":"HWPX는 외부 한글 편집 뒤 변경 후보를 확인하는 조합 흐름입니다.";
    $("templateInspect").textContent=isText?"텍스트 편집 지원 범위":"외부 편집 뒤 변경 확인";
    $("templateTokens").innerHTML=fieldDefs[work.id].slice(0,4).map((field)=>`<div class="token"><span>${esc(field.label)}</span><code>{{${esc(field.label)}}}</code></div>`).join("");
    $("templateCandidate").hidden=!state.editSession.patch||state.editSession.patch.section!=="template";
    if(!$("templateCandidate").hidden)$("templateCandidate").innerHTML="<strong>Template revision 후보 · 샘플</strong><p>추가 토큰 1개 · 영향받는 연결 1개 · 시험 필요. 실제 diff 결과가 아닙니다.</p>";
  }
  function mappingStatus(field,draft) {
    const sourceExists=draft.source==="__direct__"||currentColumns().some((column)=>column.key===draft.source);
    if(field.required&&(!draft.source||!sourceExists))return {value:"결과 없음",level:"bad",text:!draft.source?"필수 데이터 항목을 선택하세요":"원본 열이 현재 파일에 없습니다"};
    if(draft.source==="__direct__"&&!draft.constant)return {value:"결과 없음",level:"bad",text:"직접 입력 값을 입력하세요"};
    if(!draft.source)return {value:"표시하지 않음",level:"",text:draft.intentionallyUnused?"의도적 미사용":"연결 안 함"};
    const record=selectedRecords()[state.preview.index]||state.records[0];
    return {value:formatValue(valueFor(state.editContext.workId,field.key,record,draft),draft.format),level:"",text:{suggested:"추천 초안",saved:"저장된 연결",user:"사용자 선택",unused:"의도적 미사용"}[draft.provenance]||"사용자 선택"};
  }
  function renderMappings() {
    const context=state.editContext,draft=effectiveDraft();
    $("mappingList").innerHTML=fieldDefs[context.workId].map((field)=>{
      const value=draft.binding[field.key],status=mappingStatus(field,value),target=context.section==="binding"&&context.target.id===field.key;
      const provenance={suggested:"추천 초안",saved:"저장된 연결",user:"사용자 선택",unused:"의도적 미사용"}[value.provenance]||"저장된 연결";
      let evidence="";
      if(target&&context.entryReason==="preview_result")evidence=`<div class="row-evidence">원본 값 <strong>${esc(context.evidence.rawValue)}</strong> · 현재 표시 <strong>${esc(context.evidence.displayValue)}</strong> · 바꾸려는 규칙 <strong>${esc(context.evidence.label)}</strong></div>`;
      if(target&&context.entryReason==="schema_new_field")evidence=`<div class="row-evidence">새 데이터 열 <strong>성과급</strong> · 샘플 값 <strong>350000, 0, 220000</strong> · 추천 대상 <strong>상여금</strong> · 추천은 아직 저장된 연결이 아닙니다.</div>`;
      if(target&&context.entryReason==="schema_missing_field")evidence=`<div class="row-evidence">기존 연결 <strong>이름 ← 성명</strong> · 원본 열 <strong>현재 없음</strong>. 다른 열을 고르거나 원본 파일을 수정해야 합니다.</div>`;
      const typeOptions=(value.source==="__direct__"?["const"]:["text","date","amount"]).map((type)=>`<option value="${type}" ${type===value.type?"selected":""}>${typeLabels[type]}</option>`).join("");
      const formats=(formatCatalog[value.type]||formatCatalog.text).map(([key,label])=>`<option value="${key}" ${key===value.format?"selected":""}>${label}</option>`).join("");
      return `<div class="mapping-row ${target?"target":""} ${value.provenance==="suggested"?"suggested":""}" data-field-id="${field.key}"><div class="field-name"><strong>${esc(field.label)}${field.required?" *":""}</strong><span>${field.required?"필수":"선택"} 필드</span></div><div><select data-map-kind="source" aria-label="${esc(field.label)} 데이터 항목">${columnsForOptions(value.source)}</select>${value.source==="__direct__"?`<input data-map-kind="constant" value="${esc(value.constant)}" aria-label="${esc(field.label)} 직접 입력 값" placeholder="고정값">`:""}</div><div><select data-map-kind="type" ${value.source==="__direct__"?"disabled":""} aria-label="${esc(field.label)} 값 유형">${typeOptions}</select><span class="provenance">${provenance}</span></div><div><select data-map-kind="format" aria-label="${esc(field.label)} 표시형">${formats}</select></div><div class="result-cell"><strong>${esc(status.value)}</strong><span>${esc(status.text)}</span></div>${evidence}</div>`;
    }).join("");
  }
  function renderFilename() {
    const context=state.editContext,draft=effectiveDraft(),record=selectedRecords()[state.preview.index]||state.records[0];
    $("filenamePattern").value=draft.filenamePattern||"";$("filenamePattern").closest(".form-field").classList.toggle("target",context.section==="filename"&&context.target.id==="filenamePattern");
    $("filenameExample").textContent=`예: ${filenameForDraft(draft.filenamePattern,record)}`;
    $("filenameTokens").textContent=state.scenario==="customer"?"{고객명}, {담당자}":"{성명}";
  }
  function filenameForDraft(pattern,record){return (pattern||"문서").replaceAll("{성명}",record.name||"항목").replaceAll("{고객명}",record.name||"고객").replaceAll("{담당자}",record.contact||"담당자")+".hwpx"}
  function renderTest() {
    const context=state.editContext,draft=effectiveDraft(),record=selectedRecords()[state.preview.index]||state.records[0],dateKey=fieldDefs[context.workId].find((field)=>field.type==="date")?.key;
    $("testValidation").textContent=state.validation.status==="completed"?"검증 완료":state.validation.status==="pending"?"검증 중":"검증 필요";
    $("testTemplate").textContent=`r${works[context.workId].templateRevision}`;$("testBinding").textContent=`r${works[context.workId].bindingRevision}`;
    $("testCreated").textContent=state.preview.status==="completed"?"생성됨":"아직 없음";$("testApproved").textContent=state.preview.approved?"명시적 승인 완료":"승인 안 됨";
    const date=dateKey?formatValue(valueFor(context.workId,dateKey,record,draft.binding[dateKey]),draft.binding[dateKey].format):"해당 없음";
    $("testSample").textContent=`${record.name||"대표 항목"} · 날짜 ${date}${mediaFor(context.workId)==="hwpx"?` · ${filenameForDraft(draft.filenamePattern,record)}`:""}`;
  }
  function invalidPatch() {
    if(state.editContext.section!=="binding")return false;
    const draft=effectiveDraft();
    return fieldDefs[state.editContext.workId].some((field)=>mappingStatus(field,draft.binding[field.key]).level==="bad");
  }
  function renderFooter() {
    const choices=scopeActions(),dirty=Boolean(state.editSession.patch);
    $("primaryApply").hidden=!choices.primary;$("secondaryApply").hidden=!choices.secondary;
    if(choices.primary){$("primaryApply").textContent=choices.primary.label;$("primaryApply").dataset.scope=choices.primary.scope}
    if(choices.secondary){$("secondaryApply").textContent=choices.secondary.label;$("secondaryApply").dataset.scope=choices.secondary.scope}
    $("primaryApply").disabled=!dirty||invalidPatch();$("secondaryApply").disabled=!dirty||invalidPatch();
    $("scopeTitle").textContent=dirty?patchSummary():"변경 범위";$("scopeHelp").textContent=choices.primary?.scope==="run"?"주 행동은 현재 실행의 patch만 저장합니다. 기본 규칙 저장은 별도 확인을 거칩니다.":state.editContext.section==="template"?"구조 변경은 이번 실행에만 적용할 수 없습니다.":"저장할 변경을 시작하세요.";
  }
  function renderEditor() {renderEditorChrome();renderTemplate();renderMappings();renderFilename();renderTest();renderFooter()}
  function focusTarget() {
    const context=state.editContext;if(!context.target.id)return;
    const element=context.section==="binding"?document.querySelector(`[data-field-id="${CSS.escape(context.target.id)}"]`):document.querySelector(`[data-rule-id="${CSS.escape(context.target.id)}"]`);
    if(!element)return;element.scrollIntoView({block:"center"});element.querySelector("select:not(:disabled),input:not(:disabled),button:not(:disabled)")?.focus();
  }
  function openWorkEditor(context) {
    if(!works[context.workId])throw new Error("유효한 문서 작업이 필요합니다.");
    if(context.section==="filename"&&mediaFor(context.workId)==="txt")throw new Error("TXT 작업에는 파일 이름 탭이 없습니다.");
    if(state.preview.open)suspendPreview();
    closeMenu();state.editContext=clone(context);state.editSession=createEditSession(state.editContext);state.lastEditorTrigger=document.activeElement;
    renderEditor();showScreen("editor");requestAnimationFrame(focusTarget);
  }
  window.openWorkEditor=openWorkEditor;
  function renderEditorMeta() {
    renderEditorChrome();renderTest();renderFooter();
  }
  function setPatch(section,key,change,{preserveInput=false}={}) {
    const session=state.editSession;
    if(session.patch&&session.patch.section!==section)throw new Error("한 편집 진입에서는 한 섹션의 patch만 허용됩니다.");
    session.patch??={section,changes:{}};
    session.dirtySection=section;
    if(section==="binding")session.patch.changes[key]={...(session.patch.changes[key]||{}),...change};
    else session.patch.changes={...session.patch.changes,...change};
    if(preserveInput)renderEditorMeta();else renderEditor();
  }
  function discardPatch() {state.editSession.patch=null;state.editSession.dirtySection=null;renderEditor()}
  function switchTab(section) {
    if(section==="filename"&&mediaFor(state.editContext.workId)==="txt")return;
    if(state.editSession.patch&&state.editSession.dirtySection!==section){
      state.pendingTab=section;$("sectionGuardSummary").textContent=`${patchSummary()}을 적용하거나 버린 뒤 ${document.querySelector(`[data-tab="${section}"]`).textContent} 탭으로 이동할 수 있습니다.`;$("sectionGuardDialog").showModal();return;
    }
    state.editContext.section=section;renderEditor();document.querySelector(`[data-tab="${section}"]`)?.focus();
  }
  async function savePatch(scope) {
    const context=state.editContext,session=state.editSession,patch=clone(session.patch);if(!patch)return;
    if(scope==="fork"){showDeferred("별도 작업 만들기는 후속 범위입니다. 현재 작업과 patch는 바꾸지 않았습니다.");return}
    $("editorNotice").hidden=false;$("editorNotice").className="notice";$("editorNotice").textContent=scope==="run"?"이번 생성 patch를 저장하고 미리보기를 갱신합니다.":"새 기본 판본을 저장합니다. 실행 검증은 별도입니다.";
    try{
      if(scope==="run"){
        await actions.saveRunOverride({documentId:context.workId,section:patch.section,changedTarget:Object.keys(patch.changes)});
        applyPatchToRun(context.workId,patch);
        state.preview.approved=false;state.preview.required=state.activeWorkId===context.workId;state.preview.status="completed";state.preview.id=`preview-v4-${Date.now()}`;
        if(state.activeWorkId===context.workId){
          state.validation={status:"pending",id:null};
          if(hasRequiredIssue(context.workId))throw new Error("필수 연결이 아직 해결되지 않았습니다.");
          const result=await actions.validateRun({selectedCount:state.selected.size,documentId:context.workId,bindingRevision:works[context.workId].bindingRevision});
          state.validation={status:"completed",id:result.validationId};
        }
      }else{
        const saved=await actions.saveEditorChange({outcome:state.outcome,documentId:context.workId,section:patch.section==="filename"?"binding":patch.section,bindingRevision:works[context.workId].bindingRevision,templateRevision:works[context.workId].templateRevision});
        applyPatchToBase(context.workId,patch);
        if(patch.section==="binding"||patch.section==="filename")works[context.workId].bindingRevision=saved.bindingRevision;
        if(patch.section==="template")works[context.workId].templateRevision=saved.templateRevision;
        state.preview.approved=false;state.preview.required=state.activeWorkId===context.workId;
        state.validation={status:"pending",id:null};
        if(context.entryReason==="schema_new_field")state.dismissedSuggestions.add("connected:newField:salary");
        if(works[context.workId].draft)await completeNewWork(context.workId);
        if(state.activeWorkId===context.workId){
          $("editorNotice").textContent="판본 저장 완료 · 현재 실행 컨텍스트를 다시 검증합니다.";
          const result=await actions.validateRun({selectedCount:state.selected.size,documentId:context.workId,bindingRevision:works[context.workId].bindingRevision});
          state.validation={status:"completed",id:result.validationId};state.preview.status="completed";state.preview.id=`preview-v4-${Date.now()}`;
        }else{
          state.pendingActiveValidation=`${works[context.workId].name} 규칙이 저장되었습니다. 활성 작업에 영향이 있으면 문서 만들기로 돌아올 때 다시 검증합니다.`;
        }
      }
      session.patch=null;$("editorNotice").className="notice ok";$("editorNotice").textContent=scope==="run"?"이번 생성에만 적용했습니다. 기본 Binding은 바뀌지 않았습니다.":"판본 저장과 실행 검증을 각각 마쳤습니다. 새 미리보기는 아직 승인되지 않았습니다.";
      renderEditor();await wait(180);returnFromWorkEditor({scope,changedTarget:context.target});
    }catch(error){$("editorNotice").className="notice bad";$("editorNotice").textContent=`${error.message} 입력한 patch는 보존했습니다.`;renderFooter()}
  }
  function applyPatchToRun(workId,patch) {
    state.runOverrides[workId]??={fields:{},records:{}};
    if(patch.section==="binding")Object.entries(patch.changes).forEach(([key,value])=>state.runOverrides[workId].fields[key]={...(state.runOverrides[workId].fields[key]||{}),...clone(value)});
    if(patch.section==="filename")state.runOverrides[workId].filenamePattern=patch.changes.filenamePattern;
  }
  function applyPatchToBase(workId,patch) {
    if(patch.section==="binding")Object.entries(patch.changes).forEach(([key,value])=>{
      state.bindings[workId][key]={...state.bindings[workId][key],...clone(value),provenance:value.intentionallyUnused?"unused":value.provenance==="suggested"?"saved":"user"};
      delete state.runOverrides[workId]?.fields?.[key];
    });
    if(patch.section==="filename"){works[workId].filenamePattern=patch.changes.filenamePattern;delete state.runOverrides[workId]?.filenamePattern}
  }
  async function completeNewWork(workId) {
    await wait(260);delete works[workId].draft;state.activeWorkId=workId;state.preview.required=true;state.preview.approved=false;
    toast(`${works[workId].name} 작업을 만들었습니다.`);
  }
  function returnFromWorkEditor({scope=null,changedTarget=null,cancelled=false}={}) {
    const context=clone(state.editContext),ret=context.returnContext;state.editContext=null;state.editSession=null;
    if(ret.surface==="preview"){
      showScreen("data");renderData();state.preview.index=ret.previewIndex??state.preview.index;openPreview({preserve:true,focusTarget:ret.focusTarget,message:cancelled?"저장하지 않은 변경을 버렸습니다.":null});
    }else if(ret.surface==="workbench"){
      state.workIndex=ret.workIndex??state.workIndex;renderWorkbench();showScreen("workbench");highlight(ret.focusTarget);
    }else if(ret.surface==="result"){showScreen("data");renderData();highlight(ret.focusTarget)}
    else if(ret.surface==="library"){state.librarySearch=ret.librarySearch||"";renderLibrary();showScreen("library");window.scrollTo(0,ret.scrollY||0);highlight(ret.focusTarget)}
    else{showScreen("data");renderData();highlight(ret.focusTarget)}
  }
  window.returnFromWorkEditor=returnFromWorkEditor;
  function cancelEditor(){if(!state.editContext)return;returnFromWorkEditor({cancelled:true})}
  function highlight(id){if(!id)return;const element=$(id)||document.querySelector(`[data-focus-id="${CSS.escape(id)}"]`);if(!element)return;element.classList.add("return-highlight");element.scrollIntoView({block:"center"});(element.matches("button,input,select")?element:element.querySelector("button,input,select"))?.focus();setTimeout(()=>element.classList.remove("return-highlight"),2500)}

  function previewContext(key) {
    const record=selectedRecords()[state.preview.index],base=makeReturn("preview",{previewIndex:state.preview.index,focusTarget:`preview-${key}`});
    if(key==="filename")return makeContext({workId:state.activeWorkId,section:"filename",target:{kind:"rule",id:"filenamePattern"},entryReason:"preview_result",evidence:{label:"파일 이름 규칙",displayValue:filenameFor(state.activeWorkId,record),message:"현재 파일 이름에서 열었습니다."},returnContext:base});
    if(key==="template")return makeContext({workId:state.activeWorkId,section:"template",target:{kind:"paragraph",id:"document"},entryReason:"preview_result",evidence:{label:"문서 내용과 구조",message:"미리보기의 템플릿 증거에서 열었습니다."},returnContext:base});
    const binding=effectiveField(state.activeWorkId,key,record.id),field=fieldDef(state.activeWorkId,key),raw=valueFor(state.activeWorkId,key,record,binding);
    return makeContext({workId:state.activeWorkId,section:"binding",target:{kind:"field",id:key},entryReason:"preview_result",evidence:{label:`${field.label} ${key==="date"?"표시형":"값·표시"}`,rawValue:raw,displayValue:formatValue(raw,binding.format),sourceField:currentColumns().find((column)=>column.key===binding.source)?.label||binding.source,message:"미리보기 결과에서 정확한 필드 규칙을 열었습니다."},returnContext:base});
  }
  async function openPreview({preserve=false,focusTarget=null,message=null}={}) {
    if(!preserve)state.preview.index=Math.min(state.preview.index,Math.max(0,selectedRecords().length-1));
    state.preview.open=true;state.preview.status="loading";$("scrim").classList.add("on");$("previewDrawer").classList.add("open");$("previewDrawer").removeAttribute("inert");$("previewDrawer").setAttribute("aria-hidden","false");$("workspace").setAttribute("inert","");
    renderPreview(message);try{const result=await actions.createValuePreview({outcome:"success",recordCount:selectedRecords().length});state.preview.status="completed";state.preview.id=result.previewId;renderPreview(message);if(focusTarget)requestAnimationFrame(()=>highlight(focusTarget));else $("closePreview").focus()}catch(error){state.preview.status="failed";renderPreview(error.message)}
  }
  function suspendPreview() {$("scrim").classList.remove("on");$("previewDrawer").classList.remove("open");$("previewDrawer").setAttribute("inert","");$("previewDrawer").setAttribute("aria-hidden","true");$("workspace").removeAttribute("inert");state.preview.open=false}
  function closePreview() {suspendPreview();$("previewButton").focus()}
  function renderPreview(message=null) {
    const records=selectedRecords(),record=records[state.preview.index]||state.records[0],workId=state.activeWorkId;
    $("previewPosition").textContent=`${state.preview.index+1} / ${records.length}`;$("previewPrev").disabled=state.preview.index===0;$("previewNext").disabled=state.preview.index>=records.length-1;
    $("previewState").textContent=message||(state.preview.status==="loading"?"실제로 들어갈 값을 준비하고 있습니다.":state.preview.required&&!state.preview.approved?"기본 규칙이 바뀌어 결과 확인이 필요합니다.":"대표 값입니다. 미리보기 생성은 승인과 다릅니다.");
    const fields=fieldDefs[workId],overrideFields=state.runOverrides[workId]?.fields||{};
    const fieldRows=fields.map((field)=>{
      const binding=effectiveField(workId,field.key,record.id),value=formatValue(valueFor(workId,field.key,record,binding),binding.format),changed=Boolean(overrideFields[field.key]);
      return `<div class="preview-row ${changed?"changed":""}" id="preview-${field.key}"><strong>${esc(field.label)}</strong><span>${esc(value)}${changed?' <span class="badge">이번 생성에 적용됨</span>':""}</span><button class="button" type="button" data-preview-edit="${field.key}" aria-label="${esc(field.label)} 수정">수정</button></div>`;
    }).join("");
    const templateAction=`<div class="preview-template" id="preview-template"><button class="button" type="button" data-preview-edit="template">템플릿 열기</button></div>`;
    const filenameRow=mediaFor(workId)==="hwpx"?`<section class="preview-filename-block ${state.runOverrides[workId]?.filenamePattern?"changed":""}" id="preview-filename" aria-label="생성 파일 이름"><div><span class="preview-filename-kicker">생성 파일</span><strong>파일 이름</strong></div><span class="preview-filename-value">${esc(filenameFor(workId,record))}${state.runOverrides[workId]?.filenamePattern?' <span class="badge">이번 생성에 적용됨</span>':""}</span><button class="button" type="button" data-preview-edit="filename" aria-label="파일 이름 수정">수정</button></section>`:"";
    $("previewContent").innerHTML=`<div class="preview-fields">${fieldRows}</div>${templateAction}${filenameRow}`;
    $("drawerFilename").textContent=mediaFor(workId)==="hwpx"?filenameFor(workId,record):"TXT 작업에는 파일 이름 규칙 없음";
    $("drawerScope").textContent=Object.keys(overrideFields).length||state.runOverrides[workId]?.filenamePattern?"이번 생성 override":"기본 규칙";
    $("approvePreview").hidden=!state.preview.required||state.preview.approved;$("drawerRun").disabled=state.preview.required&&!state.preview.approved;
    $("drawerRun").textContent=mediaFor(workId)==="txt"?"검토·복사 시작":`${records.length}개 생성`;
  }

  async function runCurrent() {
    if(mediaFor(state.activeWorkId)==="txt"){setupWorkbench();return}
    suspendPreview();showNotice("문서를 처리하고 있습니다. 중복 실행은 잠겼습니다.");$("runButton").disabled=true;
    try{
      const records=selectedRecords(),result=await actions.runDocuments({recordCount:records.length,recordIds:records.map((r)=>r.id),outcome:state.outcome});
      state.result={...result,kind:state.outcome,successNames:records.slice(0,result.succeeded).map((r)=>filenameFor(state.activeWorkId,r))};renderData();
    }catch(error){state.result={status:"failed",kind:"processingFailure",message:error.message,runId:"run-unknown",recordId:selectedRecords()[0]?.id};renderData()}
  }
  function renderResult() {
    if(!state.result){$("resultPanel").hidden=true;return}$("resultPanel").hidden=false;
    const result=state.result;
    if(result.status==="completed"){
      $("resultTitle").textContent="문서 생성 완료";
      $("resultBody").innerHTML=`<div class="result-summary"><strong>${result.succeeded}개</strong><span>mock 이름과 상태만 표시합니다. 실제 파일이나 다운로드는 없습니다.</span></div><div class="actions"><div class="more-wrap"><button class="button" id="resultMore" type="button" aria-label="완료 결과 더보기" aria-expanded="false">⋯</button><div class="more-menu" id="resultMoreMenu" role="menu" hidden><button type="button" role="menuitem" data-result-action="filename">파일 이름 규칙 수정</button></div></div></div>`;
    }else if(result.status==="partiallyCompleted"){
      const failedId=result.failedRecordIds[0],record=state.records.find((r)=>r.id===failedId);
      $("resultTitle").textContent="4개 성공 · 1개 실패";
      $("resultBody").innerHTML=`<div class="result-list">${result.successNames.map((name)=>`<div class="result-row">성공 · ${esc(name)}</div>`).join("")}<div class="result-row failure" id="failed-output"><strong>${esc(filenameFor(state.activeWorkId,record))} 저장 실패</strong><p>확인된 원인: 같은 이름의 파일이 있습니다. 성공한 4건은 그대로 보존합니다.</p><div class="actions"><button class="button primary" type="button" data-runtime-action="number" data-record-id="${failedId}">번호를 붙여 이 1건 다시 시도</button><button class="button" type="button" data-runtime-action="rename" data-record-id="${failedId}">이번 실패 파일 이름 바꾸기</button><button class="button" type="button" data-runtime-action="folder">다른 폴더에서 다시 시도</button></div></div></div>`;
    }else{
      $("resultTitle").textContent="문서 처리 실패";
      $("resultBody").innerHTML=`<div class="result-row failure" id="unknown-failure"><strong>원인 진단 미연결</strong><p>${esc(result.message||"처리 단계가 완료되지 않았습니다.")}</p><button class="button primary" type="button" data-runtime-action="inspect">확인 가능한 증거 보기</button></div>`;
    }
  }
  async function retryOne(recordId,filename=null) {
    const record=state.records.find((r)=>r.id===recordId);state.runOverrides[state.activeWorkId]??={fields:{},records:{}};state.runOverrides[state.activeWorkId].records??={};
    if(filename)state.runOverrides[state.activeWorkId].records[recordId]={filename};
    showNotice(`${record.name} 1건만 다시 처리합니다. 성공한 결과는 유지됩니다.`);
    const retried=await actions.retryFailedDocuments({recordCount:1,recordIds:[recordId],outcome:"success"});
    state.result={...retried,status:"completed",succeeded:5,successNames:[...(state.result.successNames||[]),filenameFor(state.activeWorkId,record)]};renderData();highlight("resultPanel");
  }
  function resultFilenameEditor() {
    const context=makeContext({workId:state.activeWorkId,section:"filename",target:{kind:"rule",id:"filenamePattern"},entryReason:"output_result",evidence:{label:"파일 이름 규칙",message:"완료 결과의 더보기에서 열었습니다."},returnContext:makeReturn("result",{focusTarget:"resultPanel"})});openWorkEditor(context);
  }

  function setupWorkbench() {state.workIndex=Math.min(state.workIndex,state.records.length-1);state.workValues=clone(state.bindings.order);state.workPatch={};renderWorkbench();showScreen("workbench")}
  function workRecord(){return state.records[state.workIndex]}
  function renderWorkbench() {
    const record=workRecord();$("workPosition").textContent=`${state.workIndex+1} / ${state.records.length}`;$("copyCount").textContent=`${state.copied.size} / ${state.records.length}`;$("workPrev").disabled=state.workIndex===0;$("workNext").disabled=state.workIndex===state.records.length-1;
    $("persistWorkPatch").disabled=!Object.keys(state.workPatch).length;$("sessionStatus").textContent=Object.keys(state.workPatch).length?"이번 작업에만 적용 중":"기본 규칙";
    $("workMappings").innerHTML=fieldDefs.order.map((field)=>{
      const value={...state.bindings.order[field.key],...(state.workPatch[field.key]||{})};
      const formats=(formatCatalog[value.type]||formatCatalog.text).map(([key,label])=>`<option value="${key}" ${key===value.format?"selected":""}>${label}</option>`).join("");
      return `<div class="work-map-row" data-work-key="${field.key}" id="work-rule-${field.key}"><strong>${esc(field.label)}</strong><select data-work-source aria-label="${esc(field.label)} 데이터 항목">${columnsForOptions(value.source)}</select><select data-work-format aria-label="${esc(field.label)} 표시형">${formats}</select></div>`;
    }).join("");
    const value=(key)=>{const binding={...state.bindings.order[key],...(state.workPatch[key]||{})};return formatValue(record[binding.source],binding.format)};
    $("reviewState").textContent=state.review.has(record.id)?"규칙 변경 뒤 다시 확인 필요":state.copied.has(record.id)?"복사 완료":"복사 전";
    $("workPreview").innerHTML=state.workMode==="raw"?`<h2>발주 요청문 원문</h2><p>{{업체명}}에 {{요청 품목}} {{수량}}개를 요청합니다.</p>`:`<h2>발주 요청문</h2><p><button type="button" data-work-result="company">${esc(value("company"))}</button>에 <button type="button" data-work-result="item">${esc(value("item"))}</button> <button type="button" data-work-result="quantity">${esc(value("quantity"))}</button>개를 요청합니다.</p><p>요청 금액 <button type="button" data-work-result="amount">${esc(value("amount"))}</button></p>`;
  }
  function dirtyCopiedForReview(){state.copied.forEach((id)=>state.review.add(id))}
  async function persistWorkbenchPatch() {
    const patch=clone(state.workPatch);if(!Object.keys(patch).length)return;
    const result=await actions.saveEditorChange({outcome:state.outcome,documentId:"order",section:"binding",bindingRevision:works.order.bindingRevision,templateRevision:works.order.templateRevision});
    Object.entries(patch).forEach(([key,value])=>state.bindings.order[key]={...state.bindings.order[key],...value,provenance:"user"});
    works.order.bindingRevision=result.bindingRevision;state.workPatch={};state.validation={status:"pending",id:null};
    await actions.validateRun({selectedCount:state.selected.size,documentId:"order",bindingRevision:works.order.bindingRevision});state.validation.status="completed";state.preview.required=true;state.preview.approved=false;renderWorkbench();toast(`Binding r${works.order.bindingRevision} 저장 · 재검증 완료 · 작업점 ${state.workIndex+1} 유지`);
  }

  function startCustomerWork() {$("newWorkName").value="고객 급여 안내문";$("newWorkDialog").showModal();$("newWorkName").focus()}
  function createCustomerDraft() {
    const templateId=$("newWorkTemplate").value,workId=`customer-${Date.now()}`,source=works[templateId];
    works[workId]={id:workId,name:$("newWorkName").value.trim()||"고객 문서 작업",templatePath:source.templatePath,dataset:"고객 데이터",filenamePattern:"{고객명}_급여안내문",templateRevision:1,bindingRevision:0,draft:true};
    fieldDefs[workId]=clone(fieldDefs[templateId]);state.bindings[workId]=Object.fromEntries(fieldDefs[workId].map((field)=>[field.key,{source:"",type:field.type,format:field.format,constant:"",provenance:"suggested",intentionallyUnused:false}]));
    const suggestions={name:"name",date:"requestDate",salary:"amount",bonus:""};
    const changes={};fieldDefs[workId].forEach((field)=>{const sourceKey=suggestions[field.key]??"";changes[field.key]={source:sourceKey,type:currentColumns().find((c)=>c.key===sourceKey)?.type||field.type,format:field.format,provenance:sourceKey?"suggested":"unused",intentionallyUnused:!sourceKey}});
    state.newWorkDraft=workId;
    openWorkEditor(makeContext({workId,section:"binding",target:{kind:"field",id:fieldDefs[workId][0].key},entryReason:"voluntary",evidence:{label:"새 고객 데이터 작업",message:"기존 급여명세서의 연결은 유지됩니다. 이 새 identity의 필드만 저장합니다."},returnContext:makeReturn("data",{focusTarget:"documentSideCard"}),initialPatch:{section:"binding",changes}}));
  }
  function showDeferred(message){$("deferredText").textContent=message;$("deferredDialog").showModal()}

  $("scenarioSelect").addEventListener("change",(event)=>{
    state.scenario=event.target.value;state.records=state.scenario==="customer"?customers:employees;state.selected=new Set(state.records.map((r)=>r.id));state.search="";state.result=null;state.preview={open:false,index:0,status:"idle",required:false,approved:false,id:null};
    if(state.scenario==="customer")state.activeWorkId="salary";else if(works[state.activeWorkId]?.dataset.startsWith("고객"))state.activeWorkId="salary";
    renderData();requestValidation();
  });
  $("outcomeSelect").addEventListener("change",(event)=>{state.outcome=event.target.value;state.result=null;renderData()});
  $("recordSearch").addEventListener("input",(event)=>{state.search=event.target.value;renderRecords()});
  $("recordBody").addEventListener("change",(event)=>{const input=event.target.closest("[data-record]");if(!input)return;const id=Number(input.dataset.record);input.checked?state.selected.add(id):state.selected.delete(id);renderData();requestValidation()});
  $("recordHead").addEventListener("change",(event)=>{if(event.target.id!=="selectAll")return;state.selected=event.target.checked?new Set(state.records.map((r)=>r.id)):new Set();renderData();requestValidation()});
  $("workList").addEventListener("click",(event)=>{
    const select=event.target.closest("[data-select-work]"),menu=event.target.closest("[data-work-menu]");
    if(select){state.activeWorkId=select.dataset.selectWork;state.preview.required=false;state.preview.approved=false;state.result=null;renderData();requestValidation()}
    if(menu)openMenu(menu.dataset.workMenu,menu);
  });
  $("objectMenu").addEventListener("click",(event)=>{const button=event.target.closest("[data-menu-open]");if(!button)return;const context=makeContext({workId:button.dataset.menuWork,section:button.dataset.menuOpen,target:{kind:"none",id:null},entryReason:"voluntary",evidence:{},returnContext:makeReturn("data",{focusTarget:"documentSideCard"})});openWorkEditor(context)});
  document.querySelectorAll("[data-nav]").forEach((button)=>button.addEventListener("click",()=>{if(button.dataset.nav==="library"){renderLibrary();showScreen("library")}else{showScreen("data");renderData()}}));
  $("librarySearch").addEventListener("input",(event)=>{state.librarySearch=event.target.value;renderLibrary()});
  $("libraryGrid").addEventListener("click",(event)=>{const button=event.target.closest("[data-library-open]");if(button)openWorkEditor(makeContext({workId:button.dataset.libraryOpen,section:"template",entryReason:"library",evidence:{},returnContext:libraryReturn(button.dataset.libraryOpen)}))});
  $("libraryNewWork").addEventListener("click",()=>showDeferred("완전한 새 문서 작업 마법사는 후속 범위입니다. 고객 데이터에서 시작하는 최소 생성 흐름만 이 시안에서 조합합니다."));
  $("compatPrimary").addEventListener("click",()=>{
    if(state.scenario==="newField")openWorkEditor(makeContext({workId:"salary",section:"binding",target:{kind:"field",id:"bonus"},entryReason:"schema_new_field",evidence:{label:"상여금",sourceField:"성과급",sampleValues:"350000, 0, 220000",message:"추천은 저장 전 초안이며 기존 연결은 유지됩니다."},returnContext:makeReturn("data",{focusTarget:"compatNote"}),initialPatch:{section:"binding",changes:{bonus:{source:"performanceBonus",type:"amount",format:"won",provenance:"suggested",intentionallyUnused:false}}}}));
    if(state.scenario==="missing")openWorkEditor(makeContext({workId:"salary",section:"binding",target:{kind:"field",id:"name"},entryReason:"schema_missing_field",evidence:{label:"이름",sourceField:"성명 · 현재 없음",message:"필수 원본 열 누락에서 열었습니다."},returnContext:makeReturn("data",{focusTarget:"compatNote"})}));
  });
  $("compatSecondary").addEventListener("click",()=>{if(state.scenario==="newField"){state.dismissedSuggestions.add("newField:salary");renderData();toast("이번 분석에서만 추천을 숨겼습니다.")}else $("sourceBoundaryDialog").showModal()});
  $("startNewWork").addEventListener("click",startCustomerWork);
  $("newWorkDialog").addEventListener("close",()=>{if($("newWorkDialog").returnValue==="continue")createCustomerDraft()});

  document.querySelector(".editor-tabs").addEventListener("click",(event)=>{const button=event.target.closest("[data-tab]");if(button)switchTab(button.dataset.tab)});
  document.querySelector(".editor-tabs").addEventListener("keydown",(event)=>{
    if(!["ArrowLeft","ArrowRight"].includes(event.key))return;const tabs=[...document.querySelectorAll("[data-tab]:not([hidden])")],index=tabs.indexOf(document.activeElement),next=tabs[(index+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length];event.preventDefault();switchTab(next.dataset.tab);
  });
  $("mappingList").addEventListener("change",(event)=>{
    const row=event.target.closest("[data-field-id]");if(!row)return;const key=row.dataset.fieldId,kind=event.target.dataset.mapKind,change={provenance:"user"};
    if(kind==="constant")return;
    if(kind==="source"){change.source=event.target.value;change.intentionallyUnused=!event.target.value;change.type=event.target.value==="__direct__"?"const":currentColumns().find((c)=>c.key===event.target.value)?.type||effectiveDraft().binding[key].type;change.format=change.type==="date"?"dateDot":change.type==="amount"?"won":"raw"}
    if(kind==="type"){change.type=event.target.value;change.format=event.target.value==="date"?"dateDot":event.target.value==="amount"?"won":"raw"}
    if(kind==="format")change.format=event.target.value;setPatch("binding",key,change);
  });
  $("mappingList").addEventListener("input",(event)=>{
    if(event.target.dataset.mapKind!=="constant")return;
    const row=event.target.closest("[data-field-id]"),key=row.dataset.fieldId;
    setPatch("binding",key,{constant:event.target.value,provenance:"user"},{preserveInput:true});
    const field=fieldDef(state.editContext.workId,key),status=mappingStatus(field,effectiveDraft().binding[key]);
    row.querySelector(".result-cell strong").textContent=status.value;row.querySelector(".result-cell span").textContent=status.text;
  });
  $("recommendButton").addEventListener("click",()=>{
    const draft=effectiveDraft();let count=0;
    fieldDefs[state.editContext.workId].forEach((field)=>{
      const current=draft.binding[field.key],sourcePresent=current.source&&currentColumns().some((column)=>column.key===current.source);
      const unresolved=!current.source||!sourcePresent||current.missingSource;
      const protectedChoice=current.provenance==="user"||current.source==="__direct__"||current.intentionallyUnused||state.editSession.userConfirmed.has(field.key);
      if(!unresolved||protectedChoice)return;
      const exact=currentColumns().find((column)=>column.key===field.key||column.label===field.label);
      if(exact){setPatch("binding",field.key,{source:exact.key,type:exact.type,format:exact.type==="date"?"dateDot":exact.type==="amount"?"won":"raw",provenance:"suggested",intentionallyUnused:false});count++}
    });
    if(!count)toast("안전하게 추천할 연결이 없습니다. 누락된 이름 행은 그대로 확인 대상으로 남겼습니다.");
  });
  $("filenamePattern").addEventListener("input",(event)=>{
    setPatch("filename","filenamePattern",{filenamePattern:event.target.value},{preserveInput:true});
    const record=selectedRecords()[state.preview.index]||state.records[0];
    $("filenameExample").textContent=`예: ${filenameForDraft(event.target.value,record)}`;
  });
  $("templateInspect").addEventListener("click",()=>{
    if(mediaFor(state.editContext.workId)==="txt"){showDeferred("TXT 본문 편집은 후속 범위입니다. 이 화면은 저장 성공을 연출하지 않습니다.");return}
    setPatch("template","template",{candidate:true});$("templateCandidate").hidden=false;
  });
  $("testPreview").addEventListener("click",async()=>{state.preview.status="loading";renderTest();await actions.createValuePreview({outcome:"success",recordCount:1});state.preview.status="completed";state.preview.approved=false;renderTest();toast("미리보기를 만들었습니다. 승인 상태는 바뀌지 않았습니다.")});
  $("primaryApply").addEventListener("click",()=>savePatch($("primaryApply").dataset.scope));
  $("secondaryApply").addEventListener("click",()=>{
    const scope=$("secondaryApply").dataset.scope;if(scope==="fork"){savePatch("fork");return}
    $("confirmDefaultSummary").textContent=`${patchSummary()}만 기본 규칙에 저장합니다. 이번 실행 override의 다른 값은 포함하지 않습니다.`;$("confirmDefaultDialog").showModal();
  });
  $("confirmDefaultDialog").addEventListener("close",()=>{if($("confirmDefaultDialog").returnValue==="confirm")savePatch("default")});
  $("sectionGuardDialog").addEventListener("close",()=>{
    const result=$("sectionGuardDialog").returnValue;if(result==="discard"){discardPatch();const target=state.pendingTab;state.pendingTab=null;switchTab(target)}
    else if(result==="apply"){const choices=scopeActions();savePatch(choices.primary.scope)}
    else state.pendingTab=null;
  });
  $("editorBack").addEventListener("click",cancelEditor);$("cancelEdit").addEventListener("click",cancelEditor);$("contextReturn").addEventListener("click",cancelEditor);

  $("previewButton").addEventListener("click",()=>openPreview());
  $("runButton").addEventListener("click",runCurrent);
  $("closePreview").addEventListener("click",closePreview);$("drawerBack").addEventListener("click",closePreview);$("scrim").addEventListener("click",closePreview);
  $("previewPrev").addEventListener("click",()=>{state.preview.index=Math.max(0,state.preview.index-1);renderPreview()});$("previewNext").addEventListener("click",()=>{state.preview.index=Math.min(selectedRecords().length-1,state.preview.index+1);renderPreview()});
  $("previewContent").addEventListener("click",(event)=>{const button=event.target.closest("[data-preview-edit]");if(button)openWorkEditor(previewContext(button.dataset.previewEdit))});
  $("approvePreview").addEventListener("click",()=>{state.preview.approved=true;renderPreview();renderValidation();toast("이 미리보기를 명시적으로 승인했습니다.")});
  $("drawerRun").addEventListener("click",runCurrent);

  $("resultPanel").addEventListener("click",(event)=>{
    const more=event.target.closest("#resultMore");if(more){const menu=$("resultMoreMenu"),open=menu.hidden;menu.hidden=!open;more.setAttribute("aria-expanded",String(open));if(open){state.resultMenuTrigger=more;menu.querySelector("button").focus()}return}
    const resultAction=event.target.closest("[data-result-action]");if(resultAction?.dataset.resultAction==="filename")resultFilenameEditor();
    const runtime=event.target.closest("[data-runtime-action]");if(!runtime)return;
    const recordId=Number(runtime.dataset.recordId);
    if(runtime.dataset.runtimeAction==="number"){const record=state.records.find((r)=>r.id===recordId),base=filenameFor(state.activeWorkId,record).replace(/\.hwpx$/,"");retryOne(recordId,`${base} (1).hwpx`)}
    if(runtime.dataset.runtimeAction==="rename"){const record=state.records.find((r)=>r.id===recordId),name=window.prompt("이 실패 레코드에만 사용할 파일 이름",filenameFor(state.activeWorkId,record).replace(/\.hwpx$/,""));if(name)retryOne(recordId,`${name.replace(/\.hwpx$/,"")}.hwpx`)}
    if(runtime.dataset.runtimeAction==="folder")$("runtimeFolderDialog").showModal();
    if(runtime.dataset.runtimeAction==="inspect"){$("unknownEvidence").innerHTML=`<dt>실패 단계</dt><dd>문서 처리</dd><dt>영향 레코드</dt><dd>${esc(state.result.recordId)}</dd><dt>받은 메시지</dt><dd>${esc(state.result.message)}</dd><dt>사용한 판본</dt><dd>Template r${works[state.activeWorkId].templateRevision} · Binding r${works[state.activeWorkId].bindingRevision}</dd>`;$("unknownFailureDialog").showModal()}
  });
  $("closeResult").addEventListener("click",()=>{state.result=null;renderData()});

  $("workMappings").addEventListener("change",(event)=>{
    const row=event.target.closest("[data-work-key]");if(!row)return;const key=row.dataset.workKey,value=state.workPatch[key]||{};
    if(event.target.matches("[data-work-source]"))value.source=event.target.value;if(event.target.matches("[data-work-format]"))value.format=event.target.value;
    state.workPatch[key]=value;dirtyCopiedForReview();renderWorkbench();
  });
  $("workPreview").addEventListener("click",(event)=>{const button=event.target.closest("[data-work-result]");if(!button)return;highlight(`work-rule-${button.dataset.workResult}`)});
  $("persistWorkPatch").addEventListener("click",()=>{$("workPatchList").innerHTML=Object.keys(state.workPatch).map((key)=>`<li>${esc(fieldDef("order",key).label)} · ${state.workPatch[key].source!==undefined?"데이터 항목 ":""}${state.workPatch[key].format!==undefined?"표시형":""}</li>`).join("");$("workPatchDialog").showModal()});
  $("workPatchDialog").addEventListener("close",()=>{if($("workPatchDialog").returnValue==="confirm")persistWorkbenchPatch()});
  $("workPrev").addEventListener("click",()=>{state.workIndex=Math.max(0,state.workIndex-1);renderWorkbench()});$("workNext").addEventListener("click",()=>{state.workIndex=Math.min(state.records.length-1,state.workIndex+1);renderWorkbench()});
  $("copyRecord").addEventListener("click",()=>{const id=workRecord().id;state.copied.add(id);state.review.delete(id);if($("autoAdvance").checked&&state.workIndex<state.records.length-1)state.workIndex++;renderWorkbench()});
  document.querySelectorAll("[data-work-mode]").forEach((button)=>button.addEventListener("click",()=>{state.workMode=button.dataset.workMode;renderWorkbench()}));
  $("workbenchBack").addEventListener("click",()=>{showScreen("data");renderData()});

  $("helpButton").addEventListener("click",()=>showDeferred("지원: 증거 deep-link, patch 단위 저장, 실행 override, 새 고객 작업 최소 흐름, 런타임 1건 재시도.\n조합: HWPX 외부 편집 복귀, 고객 작업 생성.\n후속: 실제 파일·외부 앱·다운로드, 전체 생성 마법사, 여러 Binding."));
  document.addEventListener("click",(event)=>{if(!$("objectMenu").hidden&&!event.target.closest("#objectMenu")&&!event.target.closest("[data-work-menu]"))closeMenu()});
  document.addEventListener("keydown",(event)=>{
    if(event.key!=="Escape")return;
    const openDialog=document.querySelector("dialog[open]");if(openDialog)return;
    if(!$("objectMenu").hidden){event.preventDefault();closeMenu(true);return}
    const resultMenu=$("resultMoreMenu");if(resultMenu&&!resultMenu.hidden){event.preventDefault();resultMenu.hidden=true;state.resultMenuTrigger?.setAttribute("aria-expanded","false");state.resultMenuTrigger?.focus();return}
    if(state.preview.open){event.preventDefault();closePreview();return}
    if(state.view==="editor"){event.preventDefault();cancelEditor()}
  });

  renderLibrary();renderData();requestValidation();
})();
