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
  function makeScaleRecords(count) {
    const familyNames=["김민수","이서연","박준호","최유진","정하늘","윤지호","한수빈","오세훈","강유나","임도현"];
    const departments=["인사운영팀","재정기획팀","민원지원팀","정보화담당관","정책홍보팀","시설관리팀","법무지원팀"];
    const companies=["가람상사","나래기획","다온유통","라온테크","마루산업"];
    const items=["업무용 노트북","회의실 모니터","문서 보관함","보안 키보드","홍보물 인쇄"];
    return Array.from({length:count},(_,index)=>{
      const day=String((index%28)+1).padStart(2,"0");
      return {
        id:10000+index,
        name:`${familyNames[index%familyNames.length]} ${String(index+1).padStart(3,"0")}`,
        department:departments[index%departments.length],
        date:`2026-${String((index%7)+1).padStart(2,"0")}-${day}`,
        salary:3000000+(index%17)*125000,
        bonus:index%4===0?0:100000+(index%9)*50000,
        performanceBonus:index%4===0?0:100000+(index%9)*50000,
        company:companies[index%companies.length],
        item:items[index%items.length],
        quantity:(index%12)+1,
        amount:450000+(index%21)*175000,
        note:index%11===0?"":index%3===0?"확인 필요":""
      };
    });
  }
  const customers = [
    {id:101,name:"한빛복지관",contact:"오지현",phone:"02-710-2210",requestDate:"2026-07-28",amount:1800000},
    {id:102,name:"푸른도서관",contact:"강현우",phone:"02-710-2232",requestDate:"2026-07-29",amount:950000},
    {id:103,name:"새봄센터",contact:"윤하린",phone:"02-710-2251",requestDate:"2026-07-30",amount:2300000}
  ];
  const departmentRows = [
    {id:201,department:"인사운영팀",headcount:14,salaryTotal:58800000,bonusTotal:4900000},
    {id:202,department:"재정기획팀",headcount:11,salaryTotal:43800000,bonusTotal:3300000},
    {id:203,department:"민원지원팀",headcount:19,salaryTotal:76200000,bonusTotal:5100000}
  ];
  const guideRows = [{id:301,guide:"첫 행에서 사용할 시트를 선택하세요."}];
  const personnelRows = employees.slice(0,4);
  const dataFiles = {
    august:{
      path:"C:\\Downloads\\8월_ERP급여.xlsx",fileName:"8월_ERP급여.xlsx",kind:"excel",
      sheets:[
        {name:"급여현황",rows:118,columns:6,headerSample:["사번","성명","부서","기준일","기본급","성과급"],fields:null,records:employees},
        {name:"부서별 합계",rows:12,columns:4,headerSample:["부서","인원","기본급 합계","성과급 합계"],fields:null,records:departmentRows},
        {name:"안내",rows:8,columns:1,headerSample:["설명"],fields:null,records:guideRows}
      ]
    },
    september:{
      path:"C:\\Downloads\\9월_ERP급여.xlsx",fileName:"9월_ERP급여.xlsx",kind:"excel",
      sheets:[
        {name:"급여현황",rows:124,columns:10,headerSample:["사번","성명","부서","기준일","기본급","성과급","비고"],fields:null,records:employees},
        {name:"부서별 합계",rows:12,columns:4,headerSample:["부서","인원","기본급 합계","성과급 합계"],fields:null,records:departmentRows},
        {name:"안내",rows:8,columns:1,headerSample:["설명"],fields:null,records:guideRows}
      ]
    },
    personnel:{
      path:"C:\\업무\\인사자료.xlsx",fileName:"인사자료.xlsx",kind:"excel",
      sheets:[
        {name:"재직자",rows:42,columns:9,headerSample:["사번","성명","부서","기준일","업체명","요청 품목"],fields:null,records:personnelRows},
        {name:"퇴직자",rows:9,columns:4,headerSample:["사번","성명","부서","퇴직일"],fields:null,records:personnelRows.slice(0,2)}
      ]
    },
    customer:{
      path:"C:\\Downloads\\고객_요청목록.csv",fileName:"고객_요청목록.csv",kind:"csv",
      sheets:[{name:null,rows:3,columns:5,headerSample:["고객명","담당자","연락처","요청일","예상 금액"],fields:null,records:customers}]
    },
    cumulative:{
      path:"C:\\Downloads\\누적_직원_데이터.xlsx",fileName:"누적_직원_데이터.xlsx",kind:"excel",
      sheets:[{name:"직원현황",rows:320,columns:10,headerSample:["사번","성명","부서","기준일","기본급","성과급"],fields:null,records:makeScaleRecords(320)}]
    },
    corrupt:{path:"C:\\Downloads\\손상된_급여.xlsx",fileName:"손상된_급여.xlsx",kind:"excel",error:"파일 구조를 읽을 수 없습니다.",sheets:[]}
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
  const departmentColumns = [
    {key:"department",label:"부서",type:"text"},{key:"headcount",label:"인원",type:"amount"},
    {key:"salaryTotal",label:"기본급 합계",type:"amount"},{key:"bonusTotal",label:"성과급 합계",type:"amount"}
  ];
  const guideColumns = [{key:"guide",label:"설명",type:"text"}];
  dataFiles.august.sheets[0].fields=baseColumns;
  dataFiles.september.sheets[0].fields=[...baseColumns,{key:"performanceBonus",label:"성과급",type:"amount"},{key:"note",label:"비고",type:"text"}];
  dataFiles.august.sheets[1].fields=dataFiles.september.sheets[1].fields=departmentColumns;
  dataFiles.august.sheets[2].fields=dataFiles.september.sheets[2].fields=guideColumns;
  dataFiles.personnel.sheets[0].fields=baseColumns;
  dataFiles.personnel.sheets[1].fields=baseColumns.filter((column)=>["name","department"].includes(column.key));
  dataFiles.customer.sheets[0].fields=customerColumns;
  dataFiles.cumulative.sheets[0].fields=[...baseColumns,{key:"performanceBonus",label:"성과급",type:"amount"},{key:"note",label:"비고",type:"text"}];
	  const works = {
	    salary:{id:"salary",name:"급여명세서",templatePath:"templates/salary.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_급여명세서",templateRevision:1,bindingRevision:1,default_dataset_ref:"직원 현황",dataFamily:"person",favoritedAt:"2026-07-26T10:30:00",last_run_at:"2026-07-26T08:20:00"},
	    order:{id:"order",name:"발주 요청문",templatePath:"templates/order.txt",dataset:"저장된 작업",filenamePattern:null,templateRevision:1,bindingRevision:1,dataFamily:"procurement",favoritedAt:"",last_run_at:""},
	    employment:{id:"employment",name:"재직증명서",templatePath:"templates/employment.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_재직증명서",templateRevision:1,bindingRevision:1,default_dataset_ref:"직원 현황",dataFamily:"person",favoritedAt:"2026-07-25T16:10:00",last_run_at:"2026-07-25T14:00:00"},
	    department:{id:"department",name:"부서별 급여대장",templatePath:"templates/department.hwpx",dataset:"저장된 작업",filenamePattern:"{부서}_급여대장",templateRevision:1,bindingRevision:1,dataFamily:"department",favoritedAt:"",last_run_at:"2026-07-22T09:00:00"},
	    payrollLedger:{id:"payrollLedger",name:"개인별 급여대장",templatePath:"templates/payroll-ledger.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_급여대장",templateRevision:2,bindingRevision:3,dataFamily:"person",favoritedAt:"",last_run_at:"2026-07-24T11:30:00"},
	    taxNotice:{id:"taxNotice",name:"근로소득 안내문",templatePath:"templates/tax-notice.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_근로소득안내",templateRevision:1,bindingRevision:2,dataFamily:"person",favoritedAt:"",last_run_at:"2025-12-30T15:00:00"},
	    bonusReview:{id:"bonusReview",name:"성과급 검토표",templatePath:"templates/bonus-review.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_성과급검토",templateRevision:1,bindingRevision:1,dataFamily:"person",favoritedAt:"",last_run_at:""},
	    payChange:{id:"payChange",name:"급여 변경 통지서",templatePath:"templates/pay-change.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_급여변경",templateRevision:1,bindingRevision:1,dataFamily:"person",favoritedAt:"",last_run_at:""},
	    annualSummary:{id:"annualSummary",name:"연간 보수 요약",templatePath:"templates/annual-summary.hwpx",dataset:"저장된 작업",filenamePattern:"{성명}_연간보수",templateRevision:1,bindingRevision:1,dataFamily:"person",favoritedAt:"",last_run_at:""},
	    damaged:{id:"damaged",name:"손상된 이전 지급명세",templatePath:"",dataset:"저장된 작업",filenamePattern:null,templateRevision:0,bindingRevision:0,dataFamily:"person",favoritedAt:"",last_run_at:"",damaged:true,damageReason:"작업 JSON 또는 Template 파일을 확인해야 합니다."}
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
    ],
	    department:[
	      {key:"department",label:"부서",required:true,source:"department",type:"text",format:"raw"},
	      {key:"headcount",label:"인원",required:true,source:"headcount",type:"amount",format:"number"},
	      {key:"salaryTotal",label:"기본급 합계",required:true,source:"salaryTotal",type:"amount",format:"won"},
	      {key:"bonusTotal",label:"성과급 합계",required:false,source:"bonusTotal",type:"amount",format:"won"}
	    ],
	    payrollLedger:[
	      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
	      {key:"department",label:"소속",required:true,source:"department",type:"text",format:"raw"},
	      {key:"salary",label:"기본급",required:true,source:"salary",type:"amount",format:"won"}
	    ],
	    taxNotice:[
	      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
	      {key:"date",label:"기준일",required:true,source:"date",type:"date",format:"dateLongKo"},
	      {key:"salary",label:"보수액",required:true,source:"salary",type:"amount",format:"won"}
	    ],
	    bonusReview:[
	      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
	      {key:"bonus",label:"성과급",required:true,source:"bonus",type:"amount",format:"won"},
	      {key:"department",label:"소속",required:false,source:"department",type:"text",format:"raw"}
	    ],
	    payChange:[
	      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
	      {key:"date",label:"변경 기준일",required:true,source:"date",type:"date",format:"dateLongKo"},
	      {key:"salary",label:"변경 급여",required:true,source:"salary",type:"amount",format:"won"}
	    ],
	    annualSummary:[
	      {key:"name",label:"성명",required:true,source:"name",type:"text",format:"raw"},
	      {key:"department",label:"소속",required:true,source:"department",type:"text",format:"raw"},
	      {key:"salary",label:"월 보수",required:true,source:"salary",type:"amount",format:"won"},
	      {key:"bonus",label:"성과급",required:false,source:"bonus",type:"amount",format:"won"}
	    ],
	    damaged:[]
	  };
	  const templateOnlyItems = [
	    {id:"template-customer-reply",name:"고객 요청 회신",templatePath:"templates/customer-reply.hwpx",templateWorkId:"salary"},
	    {id:"template-department-report",name:"부서 현황 보고서",templatePath:"templates/department-report.hwpx",templateWorkId:"department"}
	  ];
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

	  const MAIN_DOCUMENT_LIMIT = 5;
	  const documentWorkState = {
	    activeWorkId:null,works,bindings,templateRevisions:{},bindingRevisions:{},librarySearch:"",
	    documentBrowser:{tab:"available",query:"",scrollY:0,focusTarget:null}
	  };
  const editState = {editContext:null,editSession:null,pendingTab:null,lastEditorTrigger:null,returnMarker:null};
  const emptyRecordRange = (snapshotId=null) => ({
    snapshotId,selectedIds:new Set(),search:"",columnFilters:{},viewOrder:"sourceDesc",shiftAnchorId:null,selectedOnly:false
  });
  const runState = {
    recordRange:emptyRecordRange(),rangeEditor:null,validation:{status:"idle",id:null},
    preview:{open:false,index:0,status:"idle",required:false,approved:false,id:null},runOverrides:{},
    dismissedSuggestions:new Set(),result:null,pendingActiveValidation:null
  };
  const workbenchState = {session:null,workMode:"filled",workPatch:{},workValues:{},copied:new Set(),review:new Set()};
  const defaultPinnedDataRefs = [
    {datasetRefName:"직원 현황",name:"직원 현황",path:dataFiles.personnel.path,fileName:dataFiles.personnel.fileName,sheet:"재직자",headerRow:null,status:"active",note:"반복 사용하는 인사 참조"},
    {datasetRefName:"이전 직원 현황",name:"이전 직원 현황",path:"C:\\옛폴더\\인사자료.xlsx",fileName:"인사자료.xlsx",sheet:"재직자",headerRow:null,status:"missing",note:"연결된 파일을 찾을 수 없음"}
  ];
  const dataState = {
    mountedDataRef:null,pendingMount:null,pinnedDataRefs:clone(defaultPinnedDataRefs),
    runtimeData:{loadState:"empty",snapshotId:null,target:null,fields:[],records:[],error:null},
    dataLoadState:"empty",pendingRelinkName:null,pendingSuggestedWork:null
  };
	  const state = {view:"data",outcome:"success",menuTrigger:null,resultMenuTrigger:null,newWorkDraft:null,newWorkSource:null};
  const testScenarios = [
    {id:"empty",label:"① 데이터 없이 시작"},
    {id:"august-payroll",label:"② 기존 형식 데이터 연결"},
    {id:"september-payroll",label:"③ 새 항목이 추가된 데이터"},
    {id:"september-department",label:"④ 다른 구조의 시트 선택"},
    {id:"september-guide",label:"⑤ 작업에 맞지 않는 시트 선택"},
    {id:"customer",label:"⑥ 기존 작업과 맞지 않는 데이터"},
    {id:"pinned",label:"⑦ 고정 데이터 다시 사용"},
    {id:"missing",label:"⑧ 고정 데이터 연결 끊김"},
    {id:"corrupt",label:"⑨ 손상 파일 실패"},
    {id:"guard",label:"⑩ 작업 중 데이터 바꾸기"},
    {id:"record-scale",label:"⑪ 누적 직원 데이터 · 320건"}
  ];
  let testScenarioIndex=-1;
  let snapshotSequence=0;
  let filterDialogContext=null;
  const bridge=(source,keys)=>keys.forEach((key)=>Object.defineProperty(state,key,{enumerable:true,get:()=>source[key],set:(value)=>{source[key]=value}}));
	  bridge(documentWorkState,["activeWorkId","bindings","librarySearch","documentBrowser"]);
  bridge(editState,["editContext","editSession","pendingTab","lastEditorTrigger","returnMarker"]);
  bridge(runState,["validation","preview","runOverrides","dismissedSuggestions","result","pendingActiveValidation"]);
  bridge(workbenchState,["workMode","workPatch","workValues","copied","review"]);
  Object.defineProperties(state,{
    records:{enumerable:true,get:()=>dataState.runtimeData.records},
    selected:{enumerable:true,get:()=>runState.recordRange.selectedIds,set:(value)=>{runState.recordRange.selectedIds=value}},
    search:{enumerable:true,get:()=>runState.recordRange.search,set:(value)=>{runState.recordRange.search=value}},
    workIndex:{enumerable:true,get:()=>workbenchState.session?.index??0,set:(value)=>{if(workbenchState.session)workbenchState.session.index=value}}
  });
  window.v5PrototypeState = {documentWorkState,editState,runState,workbenchState,dataState,state};
  const mediaFor = (workId) => works[workId].templatePath.toLowerCase().endsWith(".txt") ? "txt" : "hwpx";
  const currentColumns = () => dataState.runtimeData.fields;
  const currentTarget = () => dataState.runtimeData.target;
  const isCustomerData = () => currentColumns().some((column)=>column.key==="contact");
  const hasPerformanceBonus = () => currentColumns().some((column)=>column.key==="performanceBonus");
  const workLabel = (workId) => mediaFor(workId)==="txt" ? "텍스트 검토·복사" : "HWPX 일괄 생성";
  const cloneSet = (set) => new Set([...set]);
  const recordKey = (record) => String(record?.snapshotRecordId??"");
  const recordLabel = (record) => record?.name||record?.department||record?.contact||record?.guide||`원본 행 ${record?.sourceRowNumber??"?"}`;
  const cloneRange = (range) => ({
    snapshotId:range.snapshotId,
    selectedIds:cloneSet(range.selectedIds),
    search:range.search,
    columnFilters:clone(range.columnFilters),
    viewOrder:range.viewOrder,
    shiftAnchorId:range.shiftAnchorId,
    selectedOnly:Boolean(range.selectedOnly)
  });
  function normalizeSnapshotRecords(records,snapshotId) {
    return records.map((record,index)=>({
      ...clone(record),
      snapshotRecordId:`${snapshotId}:record-${index}`,
      snapshotOrdinal:index,
      sourceRowNumber:index+2
    }));
  }
  function orderedSnapshotRecords(rangeState=runState.recordRange) {
    const direction=rangeState.viewOrder==="sourceAsc"?1:-1;
    return [...dataState.runtimeData.records].sort((a,b)=>direction*(a.snapshotOrdinal-b.snapshotOrdinal));
  }
  function comparableValue(value,type) {
    if(value===null||value===undefined||value==="")return null;
    if(type==="amount"){
      const parsed=Number(String(value).replace(/[,\s원]/g,""));
      return Number.isFinite(parsed)?parsed:null;
    }
    if(type==="date"){
      const parsed=Date.parse(String(value));
      return Number.isFinite(parsed)?parsed:null;
    }
    return String(value).toLocaleLowerCase("ko");
  }
  function clausePass(value,clause,type) {
    if(!clause||!String(clause.operand??"").trim())return true;
    const left=comparableValue(value,type),right=comparableValue(clause.operand,type);
    if(left===null||right===null)return false;
    return {eq:left===right,ne:left!==right,gt:left>right,ge:left>=right,lt:left<right,le:left<=right}[clause.op]??false;
  }
  function columnFilterPass(record,column,filter) {
    const raw=record[column.key],text=String(raw??"").toLocaleLowerCase("ko");
    if(filter.text&&!text.includes(String(filter.text).trim().toLocaleLowerCase("ko")))return false;
    if(Array.isArray(filter.values)&&!filter.values.includes(String(raw??"")))return false;
    if(filter.range?.first){
      const first=clausePass(raw,filter.range.first,column.type);
      const second=filter.range.second&&String(filter.range.second.operand??"").trim()?clausePass(raw,filter.range.second,column.type):null;
      if(second!==null){
        if(filter.range.joiner==="or"?!first&&!second:!first||!second)return false;
      }else if(!first)return false;
    }
    return true;
  }
  function filteredRecordIds(rangeState=runState.recordRange) {
    const query=rangeState.search.trim().toLocaleLowerCase("ko");
    const columns=currentColumns();
    return new Set(dataState.runtimeData.records.filter((record)=>{
      if(query&&!columns.some((column)=>String(record[column.key]??"").toLocaleLowerCase("ko").includes(query)))return false;
      return Object.entries(rangeState.columnFilters).every(([key,filter])=>{
        const column=columns.find((item)=>item.key===key);
        return !column||columnFilterPass(record,column,filter);
      });
    }).map(recordKey));
  }
  function visibleOrderedRecords(rangeState=runState.recordRange) {
    if(rangeState.selectedOnly)return orderedSnapshotRecords(rangeState).filter((record)=>rangeState.selectedIds.has(recordKey(record)));
    const visible=filteredRecordIds(rangeState);
    return orderedSnapshotRecords(rangeState).filter((record)=>visible.has(recordKey(record)));
  }
  function orderedSelectedRecords(rangeState=runState.recordRange) {
    return orderedSnapshotRecords(rangeState).filter((record)=>rangeState.selectedIds.has(recordKey(record)));
  }
  function hiddenSelectedRecords(rangeState=runState.recordRange) {
    const visible=new Set(visibleOrderedRecords({...rangeState,selectedOnly:false}).map(recordKey));
    return orderedSelectedRecords(rangeState).filter((record)=>!visible.has(recordKey(record)));
  }
  function headerSelectionState(rangeState=runState.recordRange) {
    const visibleIds=visibleOrderedRecords(rangeState).map(recordKey);
    const checked=visibleIds.length>0&&visibleIds.every((id)=>rangeState.selectedIds.has(id));
    return {checked,indeterminate:visibleIds.some((id)=>rangeState.selectedIds.has(id))&&!checked};
  }
  function selectionFingerprint(rangeState=runState.recordRange) {
    return JSON.stringify([rangeState.snapshotId,rangeState.viewOrder,orderedSelectedRecords(rangeState).map(recordKey)]);
  }
  function activeFilterCount(rangeState=runState.recordRange) {
    return Object.keys(rangeState.columnFilters).length;
  }
  function rangeDefinitionFingerprint(rangeState) {
    return JSON.stringify({
      snapshotId:rangeState.snapshotId,
      selectedIds:[...rangeState.selectedIds].sort(),
      search:rangeState.search,
      columnFilters:rangeState.columnFilters,
      viewOrder:rangeState.viewOrder
    });
  }
  function filterSummaries(rangeState=runState.recordRange) {
    return Object.entries(rangeState.columnFilters).map(([key,filter])=>{
      const column=currentColumns().find((item)=>item.key===key),parts=[];
      if(filter.text)parts.push(`‘${filter.text}’ 포함`);
      if(Array.isArray(filter.values))parts.push(`${filter.values.length}개 값`);
      if(filter.range?.first)parts.push(`${{eq:"=",ne:"≠",gt:">",ge:"≥",lt:"<",le:"≤"}[filter.range.first.op]} ${filter.range.first.operand}`);
      return {key,label:`${column?.label||key}: ${parts.join(" · ")||"조건"}`};
    });
  }
  function editorSampleRecord() {
    return orderedSelectedRecords()[state.preview.index]||orderedSnapshotRecords()[0]||null;
  }
  function invalidateRunEvidence() {
    const required=runState.preview.required;
    if(state.preview.open)suspendPreview();
    runState.validation={status:"idle",id:null};
    runState.preview={open:false,index:0,status:"idle",required,approved:false,id:null};
    runState.result=null;
  }
  function finishRunInputMutation(beforeFingerprint,{editor=false}={}) {
    const range=editor?runState.rangeEditor?.draft:runState.recordRange;
    if(!range)return false;
    if(editor){
      runState.rangeEditor.dirty=rangeDefinitionFingerprint(range)!==runState.rangeEditor.baseDefinitionFingerprint;
      renderRangeEditor();
      return false;
    }
    const changed=beforeFingerprint!==selectionFingerprint(range);
    if(changed)invalidateRunEvidence();
    renderData();
    if(changed)requestValidation();
    return changed;
  }
  function setRecordSelection(rangeState,id,checked,shiftKey=false) {
    const visibleIds=visibleOrderedRecords(rangeState).map(recordKey);
    const anchorIndex=visibleIds.indexOf(String(rangeState.shiftAnchorId));
    const currentIndex=visibleIds.indexOf(String(id));
    if(shiftKey&&anchorIndex>=0&&currentIndex>=0){
      const [start,end]=[anchorIndex,currentIndex].sort((a,b)=>a-b);
      visibleIds.slice(start,end+1).forEach((visibleId)=>checked?rangeState.selectedIds.add(visibleId):rangeState.selectedIds.delete(visibleId));
    }else{
      checked?rangeState.selectedIds.add(String(id)):rangeState.selectedIds.delete(String(id));
    }
    rangeState.shiftAnchorId=String(id);
  }
  const fieldDef = (workId, key) => fieldDefs[workId]?.find((field)=>field.key===key);
  const toast = (message) => {$("toast").textContent=message;$("toast").classList.add("on");window.setTimeout(()=>$("toast").classList.remove("on"),2200)};

	  function showScreen(view) {
	    state.view=view;
	    document.querySelectorAll(".screen").forEach((screen)=>screen.classList.toggle("on",screen.id===`screen-${view}`));
	    $("topbar").hidden=view==="workbench";
	    const navView=["documents","record-range"].includes(view)?"data":view;
	    document.querySelectorAll("[data-nav]").forEach((button)=>button.setAttribute("aria-current",button.dataset.nav===navView?"page":"false"));
    if(view==="data"&&state.pendingActiveValidation){
      $("dataNotice").hidden=false;$("dataNotice").textContent=state.pendingActiveValidation;
      state.pendingActiveValidation=null;requestValidation();
    }
  }
	  function columnsForOptions(selected) {
	    const list=[`<option value="" ${!selected?"selected":""}>연결 안 함</option>`,`<option value="__direct__" ${selected==="__direct__"?"selected":""}>직접 입력</option>`];
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
  function valueFor(workId,key,record,binding=effectiveField(workId,key,recordKey(record))) {
    if(binding.source==="__direct__")return binding.constant;
    return record?.[binding.source];
  }
  function filenameFor(workId,record) {
    const recordOverride=state.runOverrides[workId]?.records?.[recordKey(record)]?.filename;
    if(recordOverride)return recordOverride;
    const pattern=state.runOverrides[workId]?.filenamePattern ?? works[workId].filenamePattern ?? works[workId].name;
    const name=record?.name||record?.contact||"항목";
    return pattern.replaceAll("{성명}",name).replaceAll("{고객명}",record?.name||"고객").replaceAll("{담당자}",record?.contact||"담당자").replaceAll("{부서}",record?.department||"부서")+".hwpx";
  }
  function currentIssue() {
    if(hasPerformanceBonus()&&!state.dismissedSuggestions.has("performanceBonus:salary"))return "newField";
    if(state.activeWorkId&&hasRequiredIssue(state.activeWorkId))return "missing";
    return null;
  }
	  function compatibilityFor(workId,currentFields=currentColumns()) {
	    const missing=[];
	    const columnsByKey=new Map(currentFields.map((column)=>[column.key,column]));
	    for(const field of fieldDefs[workId]||[]){
	      if(!field.required)continue;
	      const binding=state.bindings[workId]?.[field.key];
	      if(!binding?.source){
	        missing.push({fieldId:field.key,fieldLabel:field.label,reason:"source_missing"});
	        continue;
	      }
	      if(binding.source==="__direct__"){
	        if(binding.constant===null||binding.constant===undefined||String(binding.constant).trim()===""){
	          missing.push({fieldId:field.key,fieldLabel:field.label,reason:"constant_missing"});
	        }
	        continue;
	      }
	      if(!columnsByKey.has(binding.source)){
	        missing.push({fieldId:field.key,fieldLabel:field.label,source:binding.source,reason:"source_not_present"});
	      }
	    }
	    return {kind:missing.length?"needsAction":"available",missing};
	  }
	  function requiredSources(workId) {
	    return compatibilityFor(workId).missing;
	  }
	  function canUseWork(workId) {
	    return dataState.runtimeData.loadState==="ready"&&!works[workId]?.damaged&&compatibilityFor(workId).kind==="available";
	  }
	  function compatibleWorks() {
	    if(dataState.runtimeData.loadState!=="ready")return [];
	    return Object.values(works).filter((work)=>!work.draft&&!work.damaged&&compatibilityFor(work.id).kind==="available");
	  }
	  function makeReturn(surface, extra={}) {
	    return {surface,previewIndex:state.preview.index,focusTarget:null,scrollTarget:null,reopenDrawer:surface==="preview",workIndex:state.workIndex,workMode:state.workMode,search:state.search,librarySearch:state.librarySearch,...extra};
	  }
	  function makeDocumentBrowserReturn(focusTarget) {
	    return makeReturn("documents",{
	      documentTab:state.documentBrowser.tab,
	      documentQuery:state.documentBrowser.query,
	      scrollY:window.scrollY,
	      focusTarget
	    });
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
	    if(context.returnContext.surface==="documents")return {primary:{scope:"default",label:context.entryReason==="document_browser_new_work"?"문서 작업 저장":"연결 저장"},secondary:null};
	    if(context.returnContext.surface==="library")return {primary:{scope:"default",label:"변경 저장"},secondary:null};
    if(activeRunContext(context))return {primary:{scope:"run",label:"이번 생성에 적용"},secondary:{scope:"default",label:"기본 규칙으로 저장…"}};
    return {primary:{scope:"default",label:"변경 저장"},secondary:null};
  }

  function renderFilterChips(containerId,rangeState,surface) {
    $(containerId).innerHTML=filterSummaries(rangeState).map((item)=>`<span class="filter-chip">${esc(item.label)} <button type="button" data-remove-filter="${esc(item.key)}" data-filter-surface="${surface}" aria-label="${esc(item.label)} 필터 제거">×</button></span>`).join("");
  }
  function renderRecords() {
    const ready=dataState.runtimeData.loadState==="ready",range=runState.recordRange,columns=currentColumns().slice(0,4);
    const records=ready?visibleOrderedRecords(range):[];
    $("recordHead").innerHTML=ready?`<tr><th><input id="selectAll" type="checkbox" aria-label="현재 검색·필터 결과 모두 선택"></th>${columns.map((column)=>`<th>${esc(column.label)}</th>`).join("")}</tr>`:"";
    $("recordBody").innerHTML=records.length?records.map((record)=>{
      const key=recordKey(record),selected=range.selectedIds.has(key);
      return `<tr class="${selected?"selected":""}"><td><input type="checkbox" data-record="${esc(key)}" ${selected?"checked":""} aria-label="${esc(recordLabel(record))} 선택"></td>${columns.map((column)=>`<td>${esc(formatValue(record[column.key],column.type==="amount"?"number":column.type==="date"?"dateDash":"raw"))}</td>`).join("")}</tr>`;
    }).join(""):`<tr><td colspan="${columns.length+1}"><div class="empty">${ready?"현재 검색·필터 결과가 없습니다.":"데이터를 선택하면 레코드가 표시됩니다."}</div></td></tr>`;
    const selectAll=$("selectAll"),header=headerSelectionState(range);
    if(selectAll){selectAll.checked=header.checked;selectAll.indeterminate=header.indeterminate;selectAll.disabled=!records.length}
    $("selectionTitle").textContent=`선택 ${range.selectedIds.size}건`;
    $("selectionType").textContent=ready?`현재 결과 ${records.length}건 · 전체 ${state.records.length}건`:"데이터를 선택하면 레코드가 표시됩니다.";
    $("recordSearch").disabled=!ready;$("recordSearch").value=range.search;
    $("recordFilterButton").disabled=!ready;$("recordFilterButton").textContent=`필터 ${activeFilterCount(range)}`;
    $("recordOrder").disabled=!ready;$("recordOrder").value=range.viewOrder;
    $("recordRangeButton").disabled=!ready;
    $("clearRecordSelection").disabled=!ready||!range.selectedIds.size;
    renderFilterChips("activeFilterChips",range,"main");
    const hidden=ready?hiddenSelectedRecords(range):[];
    $("hiddenSelectionSummary").hidden=!hidden.length;
    $("hiddenSelectionTitle").textContent=hidden.length?`필터 밖에 선택 ${hidden.length}건 있음`:"";
    $("hiddenSelectionSamples").innerHTML=hidden.slice(0,3).map((record)=>`<span class="hidden-chip">${esc(recordLabel(record))} <button type="button" data-remove-hidden="${esc(recordKey(record))}" aria-label="${esc(recordLabel(record))} 선택 해제">×</button></span>`).join("")+(hidden.length>3?`<span>외 ${hidden.length-3}건</span>`:"");
  }
  function filterValueOptions(column) {
    const values=[...new Set(state.records.map((record)=>String(record[column.key]??"")))];
    return values.sort((a,b)=>a===""?1:b===""?-1:a.localeCompare(b,"ko",{numeric:true}));
  }
  function renderFilterDialogColumn() {
    if(!filterDialogContext)return;
    const range=filterDialogContext.range,column=currentColumns().find((item)=>item.key===$("filterColumn").value)||currentColumns()[0];
    if(!column)return;
    const current=range.columnFilters[column.key]||{},values=filterValueOptions(column),selected=current.values;
    $("filterText").value=current.text||"";
    $("filterValueOptions").innerHTML=values.map((value,index)=>`<label><input type="checkbox" data-filter-value="${index}" value="${esc(value)}" ${!Array.isArray(selected)||selected.includes(value)?"checked":""}><span>${esc(value||"(빈값)")}</span></label>`).join("");
    const rangeCondition=current.range||{};
    $("filterRangeFields").hidden=!["date","amount"].includes(column.type);
    $("filterFirstOp").value=rangeCondition.first?.op||"ge";$("filterFirstOperand").value=rangeCondition.first?.operand||"";
    $("filterJoiner").value=rangeCondition.joiner||"and";$("filterSecondOp").value=rangeCondition.second?.op||"le";$("filterSecondOperand").value=rangeCondition.second?.operand||"";
    $("filterError").textContent="";
  }
  function openFilterDialog(range,surface,trigger) {
    if(!currentColumns().length)return;
    filterDialogContext={range,surface};
    $("filterColumn").innerHTML=currentColumns().map((column)=>`<option value="${esc(column.key)}">${esc(column.label)}</option>`).join("");
    const existing=Object.keys(range.columnFilters)[0];if(existing)$("filterColumn").value=existing;
    renderFilterDialogColumn();openDialog($("recordFilterDialog"),trigger);
  }
  function collectFilterDialog() {
    const column=currentColumns().find((item)=>item.key===$("filterColumn").value);
    const text=$("filterText").value.trim(),options=[...$("filterValueOptions").querySelectorAll("[data-filter-value]")];
    const checked=options.filter((input)=>input.checked).map((input)=>input.value);
    const values=checked.length===options.length?null:checked;
    let range=null;
    if(["date","amount"].includes(column.type)&&$("filterFirstOperand").value.trim()){
      const firstOperand=$("filterFirstOperand").value.trim(),secondOperand=$("filterSecondOperand").value.trim();
      if(comparableValue(firstOperand,column.type)===null)throw new Error(`${column.label}의 첫 번째 비교 값을 확인하세요.`);
      if(secondOperand&&comparableValue(secondOperand,column.type)===null)throw new Error(`${column.label}의 두 번째 비교 값을 확인하세요.`);
      range={first:{op:$("filterFirstOp").value,operand:firstOperand},joiner:$("filterJoiner").value,second:secondOperand?{op:$("filterSecondOp").value,operand:secondOperand}:null};
    }
    const filter={};if(text)filter.text=text;if(values!==null)filter.values=values;if(range)filter.range=range;
    return {column,filter,empty:!Object.keys(filter).length};
  }
  function openRangeEditor({selectedOnly=false,focusTarget="recordRangeButton"}={}) {
    if(dataState.runtimeData.loadState!=="ready")return;
    const draft=cloneRange(runState.recordRange);draft.selectedOnly=selectedOnly;draft.shiftAnchorId=null;
    runState.rangeEditor={
      draft,
      baseFingerprint:selectionFingerprint(runState.recordRange),
      baseDefinitionFingerprint:rangeDefinitionFingerprint(draft),
      dirty:false,
      pendingExit:null,
      returnContext:{surface:"data",focusTarget,scrollY:window.scrollY}
    };
    renderRangeEditor();showScreen("record-range");window.scrollTo(0,0);requestAnimationFrame(()=>$("recordRangeBack").focus());
  }
  function renderRangeEditor() {
    const editor=runState.rangeEditor;if(!editor)return;
    const range=editor.draft,columns=currentColumns(),records=visibleOrderedRecords(range),header=headerSelectionState(range);
    $("rangeEditorCounts").textContent=`전체 ${state.records.length} · 현재 결과 ${records.length} · 선택 ${range.selectedIds.size}`;
    $("rangeEditorSearch").value=range.search;$("rangeEditorSearch").disabled=range.selectedOnly;
    $("rangeEditorFilterButton").textContent=`필터 ${activeFilterCount(range)}`;$("rangeEditorFilterButton").disabled=range.selectedOnly;
    $("rangeEditorOrder").value=range.viewOrder;
    $("rangeEditorSelectedOnly").setAttribute("aria-pressed",String(range.selectedOnly));
    $("rangeEditorSelectedOnly").textContent=range.selectedOnly?"전체 결과 보기":"선택된 항목만 보기";
    $("rangeEditorSelectedOnly").disabled=!range.selectedIds.size;
    $("rangeEditorClearSelection").disabled=!range.selectedIds.size;
    $("selectedOnlyNotice").hidden=!range.selectedOnly;
    $("rangeEditorApply").textContent=`선택 적용: ${range.selectedIds.size}건`;
    $("rangeEditorFooterNote").textContent=editor.dirty?"적용하지 않은 범위 변경이 있습니다.":"변경은 적용하기 전까지 문서 만들기 화면에 반영되지 않습니다.";
    renderFilterChips("rangeEditorFilterChips",range,"editor");
    $("rangeEditorHead").innerHTML=`<tr><th><input id="rangeEditorSelectAll" type="checkbox" aria-label="현재 검색·필터 결과 모두 선택"></th><th>원본 행</th>${columns.map((column)=>`<th>${esc(column.label)}</th>`).join("")}</tr>`;
    $("rangeEditorBody").innerHTML=records.length?records.map((record)=>{
      const key=recordKey(record),selected=range.selectedIds.has(key);
      return `<tr class="${selected?"selected":""}"><td><input type="checkbox" data-range-record="${esc(key)}" ${selected?"checked":""} aria-label="${esc(recordLabel(record))} 선택"></td><td>${record.sourceRowNumber}</td>${columns.map((column)=>`<td>${esc(formatValue(record[column.key],column.type==="amount"?"number":column.type==="date"?"dateDash":"raw"))}</td>`).join("")}</tr>`;
    }).join(""):`<tr><td colspan="${columns.length+2}"><div class="empty">${range.selectedOnly?"선택한 항목이 없습니다.":"현재 검색·필터 결과가 없습니다."}</div></td></tr>`;
    const selectAll=$("rangeEditorSelectAll");selectAll.checked=header.checked;selectAll.indeterminate=header.indeterminate;selectAll.disabled=!records.length;
  }
  function applyRangeEditor() {
    const editor=runState.rangeEditor;if(!editor)return;
    if(editor.draft.snapshotId!==dataState.runtimeData.snapshotId){
      runState.rangeEditor=null;showScreen("data");renderData();showNotice("데이터가 바뀌어 범위 초안을 적용하지 않았습니다. 새 데이터에서 다시 선택하세요.","bad");return;
    }
    const before=selectionFingerprint(runState.recordRange),returnContext=editor.returnContext;
    const committed=cloneRange(editor.draft);committed.selectedOnly=false;committed.shiftAnchorId=null;
    runState.recordRange=committed;runState.rangeEditor=null;
    const changed=before!==selectionFingerprint(committed);
    if(changed)invalidateRunEvidence();
    showScreen("data");renderData();window.scrollTo(0,returnContext.scrollY||0);
    if(changed)requestValidation();
    requestAnimationFrame(()=>highlight(returnContext.focusTarget));
  }
  function discardRangeEditor() {
    const editor=runState.rangeEditor;if(!editor)return;
    const ret=editor.returnContext;runState.rangeEditor=null;showScreen("data");renderData();window.scrollTo(0,ret.scrollY||0);requestAnimationFrame(()=>highlight(ret.focusTarget));
  }
  function requestRangeEditorExit() {
    const editor=runState.rangeEditor;if(!editor)return;
    if(!editor.dirty){discardRangeEditor();return}
    openDialog($("recordRangeGuardDialog"),$("recordRangeBack"));
    requestAnimationFrame(()=>$("recordRangeGuardDialog").querySelector('[value="stay"]')?.focus());
  }
  function workMenuItems(workId) {
    const common=[["template","템플릿 열기"],["binding","필드 연결·표시 수정"]];
    if(mediaFor(workId)==="hwpx")common.push(["filename","파일 이름 규칙"]);
    return common;
  }
	  function currentDataFamily() {
	    const keys=new Set(currentColumns().map((column)=>column.key));
	    if(keys.has("contact")&&keys.has("phone"))return "customer";
	    if(keys.has("headcount")&&keys.has("salaryTotal"))return "department";
	    if(keys.has("name")&&keys.has("department"))return "person";
	    if(keys.has("company")&&keys.has("item"))return "procurement";
	    return "other";
	  }
	  function activeDatasetReference(name) {
	    return dataState.pinnedDataRefs.find((item)=>item.datasetRefName===name&&item.status==="active"&&findFileByPath(item.path));
	  }
	  function documentEntryForWork(work) {
	    if(work.damaged)return {id:work.id,name:work.name,kind:"work",work,status:"needsAction",reasonKind:"damaged",reason:work.damageReason,action:"boundary"};
	    const compatibility=compatibilityFor(work.id);
	    if(compatibility.kind==="available")return {id:work.id,name:work.name,kind:"work",work,status:"available",compatibility};
	    const defaultReference=work.default_dataset_ref&&activeDatasetReference(work.default_dataset_ref);
	    if(defaultReference)return {id:work.id,name:work.name,kind:"work",work,status:"needsAction",reasonKind:"defaultData",reason:`현재 데이터에는 필수 항목이 없습니다. ‘${work.default_dataset_ref}’ 참조로 전환할 수 있습니다.`,action:"defaultData",compatibility};
	    if(work.default_dataset_ref)return {id:work.id,name:work.name,kind:"work",work,status:"needsAction",reasonKind:"brokenReference",reason:`기본 데이터 ‘${work.default_dataset_ref}’ 참조를 다시 연결해야 합니다.`,action:"relinkDefault",compatibility};
	    if(work.dataFamily===currentDataFamily())return {id:work.id,name:work.name,kind:"work",work,status:"needsAction",reasonKind:"bindingDrift",reason:"같은 업무 계열이지만 현재 항목에서 필수 연결 일부를 찾을 수 없습니다.",action:"repair",compatibility};
	    return {id:work.id,name:work.name,kind:"work",work,status:"needsAction",reasonKind:"differentData",reason:"현재 데이터와 다른 업무 구조의 작업입니다. 기존 Binding은 변경하지 않습니다.",action:"newWork",compatibility};
	  }
	  function documentEntries() {
	    if(dataState.runtimeData.loadState!=="ready")return [];
	    const stored=Object.values(works).filter((work)=>!work.draft).map(documentEntryForWork);
	    const templates=templateOnlyItems.map((template)=>({
	      ...template,kind:"template",status:"needsAction",reasonKind:"templateOnly",
	      reason:"Template 자산은 있지만 저장 문서 작업 identity가 없습니다.",action:"newWork"
	    }));
	    return [...stored,...templates];
	  }
	  function workNameCompare(a,b){return a.name.localeCompare(b.name,"ko")}
	  function sortedAvailableWorks() {
	    return compatibleWorks().sort((a,b)=>{
	      const favoriteA=Boolean(a.favoritedAt),favoriteB=Boolean(b.favoritedAt);
	      if(favoriteA!==favoriteB)return favoriteA?-1:1;
	      if(favoriteA&&favoriteB){
	        const favoriteOrder=String(b.favoritedAt).localeCompare(String(a.favoritedAt));
	        if(favoriteOrder)return favoriteOrder;
	      }
	      const recentA=Boolean(a.last_run_at),recentB=Boolean(b.last_run_at);
	      if(recentA!==recentB)return recentA?-1:1;
	      if(recentA&&recentB){
	        const recentOrder=String(b.last_run_at).localeCompare(String(a.last_run_at));
	        if(recentOrder)return recentOrder;
	      }
	      return workNameCompare(a,b);
	    });
	  }
	  function lastRunLabel(value) {
	    if(!value)return "사용한 적 없음";
	    const date=new Date(value),today=new Date();
	    if(date.getFullYear()===today.getFullYear()&&date.getMonth()===today.getMonth()&&date.getDate()===today.getDate())return "오늘";
	    if(date.getFullYear()===today.getFullYear())return `${date.getMonth()+1}월 ${date.getDate()}일`;
	    return `${date.getFullYear()}년 ${date.getMonth()+1}월 ${date.getDate()}일`;
	  }
	  function favoriteButton(work) {
	    const favorite=Boolean(work.favoritedAt),verb=favorite?"즐겨찾기에서 제거":"즐겨찾기에 추가";
	    return `<button class="favorite-button" type="button" data-favorite-work="${work.id}" aria-pressed="${favorite}" aria-label="${esc(work.name)} ${verb}">${favorite?"★":"☆"}</button>`;
	  }
	  function workCard(work) {
	    return `<div class="work-item ${state.activeWorkId===work.id?"selected":""}" id="main-work-${work.id}" data-work-card="${work.id}">${favoriteButton(work)}<button type="button" data-select-work="${work.id}" aria-pressed="${state.activeWorkId===work.id}"><strong>${esc(work.name)}</strong><span>${workLabel(work.id)}</span><span class="work-meta"><span>연결됨</span><span>마지막 성공 ${esc(lastRunLabel(work.last_run_at))}</span></span></button><button class="icon-button" type="button" data-work-menu="${work.id}" aria-label="${esc(work.name)} 변경 메뉴" aria-expanded="false">⋯</button></div>`;
	  }
	  function renderWorkChooser() {
	    const ready=dataState.runtimeData.loadState==="ready";
	    const eligible=sortedAvailableWorks(),visible=eligible.slice(0,MAIN_DOCUMENT_LIMIT),empty=!eligible.length;
	    const needsCount=documentEntries().filter((entry)=>entry.status==="needsAction").length;
	    $("customerEmpty").hidden=!empty;$("workList").hidden=empty;$("validationCard").hidden=empty;$("runButton").hidden=empty;$("previewButton").hidden=empty;
	    $("workCount").textContent=ready?`사용 가능 ${eligible.length} · 확인 필요 ${needsCount}`:"사용 가능 0 · 확인 필요 0";
	    $("browseOtherWorks").hidden=!ready;
	    if(empty){$("workList").innerHTML="";return}
	    const groups=[
	      ["즐겨찾기",visible.filter((work)=>work.favoritedAt)],
	      ["최근 사용",visible.filter((work)=>!work.favoritedAt&&work.last_run_at)],
	      ["다른 문서",visible.filter((work)=>!work.favoritedAt&&!work.last_run_at)]
	    ];
	    $("workList").innerHTML=groups.filter(([,items])=>items.length).map(([label,items])=>`<section class="work-section" aria-label="${label}"><h3>${label}</h3>${items.map(workCard).join("")}</section>`).join("");
	  }
	  function renderDocumentBrowser() {
	    if(dataState.runtimeData.loadState!=="ready"){showScreen("data");renderData();return}
	    const target=currentTarget(),entries=documentEntries(),available=entries.filter((entry)=>entry.status==="available"),needsAction=entries.filter((entry)=>entry.status==="needsAction");
	    $("documentsTitle").textContent=`${targetLabel(target)}에 사용할 문서`;
	    $("documentsAvailableTab").textContent=`사용 가능 ${available.length}`;
	    $("documentsNeedsActionTab").textContent=`확인 필요 ${needsAction.length}`;
	    $("documentSearch").value=state.documentBrowser.query;
	    document.querySelectorAll("[data-document-tab]").forEach((tab)=>{
	      const selected=tab.dataset.documentTab===state.documentBrowser.tab;
	      tab.setAttribute("aria-selected",String(selected));tab.tabIndex=selected?0:-1;
	    });
	    const activeTab=state.documentBrowser.tab==="available"?$("documentsAvailableTab"):$("documentsNeedsActionTab");
	    $("documentsPanel").setAttribute("aria-labelledby",activeTab.id);
	    const query=state.documentBrowser.query.trim().toLowerCase();
	    const visible=(state.documentBrowser.tab==="available"?available:needsAction).filter((entry)=>entry.name.toLowerCase().includes(query));
	    $("documentBrowserList").innerHTML=visible.length?visible.map(documentBrowserCard).join(""):`<div class="document-empty">이름이 맞는 문서가 없습니다. 검색어를 지우거나 다른 탭을 확인하세요.</div>`;
	  }
	  function documentBrowserCard(entry) {
	    if(entry.status==="available"){
	      const work=entry.work;
	      return `<article class="document-card ${state.activeWorkId===work.id?"active":""}" id="document-work-${work.id}" data-document-entry="${work.id}">${favoriteButton(work)}<div><h2>${esc(work.name)}</h2><p>${workLabel(work.id)}</p><div class="document-meta"><span>연결됨</span><span>마지막 성공 ${esc(lastRunLabel(work.last_run_at))}</span>${state.activeWorkId===work.id?"<span>현재 선택</span>":""}</div></div><div class="document-actions"><button class="button primary" type="button" data-document-select="${work.id}">이 문서 선택</button></div></article>`;
	    }
	    const labels={repair:"연결 복구",defaultData:"기본 데이터 사용",relinkDefault:"데이터 참조 다시 연결",newWork:entry.kind==="template"?"이 템플릿으로 새 문서 작업 만들기":"이 템플릿으로 새 작업",boundary:"지원 범위 확인"};
	    const action=entry.action==="boundary"?`<button class="button" type="button" data-document-boundary="${entry.id}">${labels[entry.action]}</button>`:`<button class="button primary" type="button" data-document-action="${entry.action}" data-document-entry-id="${entry.id}">${labels[entry.action]}</button>`;
	    const identityControl=entry.kind==="work"&&entry.reasonKind!=="damaged"?favoriteButton(entry.work):"<span aria-hidden=\"true\">◇</span>";
	    return `<article class="document-card needs-action ${entry.reasonKind==="damaged"?"damaged":""}" id="document-work-${entry.id}" data-document-entry="${entry.id}">${identityControl}<div><h2>${esc(entry.name)}</h2><p>${entry.kind==="work"?workLabel(entry.work.id):"Template-only · 저장 작업 없음"}</p><div class="document-meta"><span>${entry.reasonKind==="bindingDrift"?"연결 확인 필요":entry.reasonKind==="damaged"?"손상 작업":"새 작업 또는 데이터 전환 필요"}</span></div><p>${esc(entry.reason)}</p></div><div class="document-actions">${action}</div></article>`;
	  }
  function renderEvidence() {
    if(dataState.runtimeData.loadState!=="ready"){$("compatNote").hidden=true;return}
    if(hasPerformanceBonus()&&!state.dismissedSuggestions.has("performanceBonus:salary")&&compatibleWorks().some((work)=>work.id==="salary")){
      $("compatNote").hidden=false;
      $("compatTitle").textContent="새 ‘성과급’ 열을 발견했습니다.";
      $("compatText").textContent="급여명세서의 ‘상여금’에 연결할 수 있습니다. 추천은 아직 저장된 연결이 아닙니다.";
      $("compatPrimary").hidden=false;$("compatSecondary").hidden=false;
      $("compatPrimary").textContent="상여금에 연결";$("compatSecondary").textContent="이번에는 사용하지 않음";
    }else if(isCustomerData()&&!compatibleWorks().length){
      $("compatNote").hidden=false;
      $("compatTitle").textContent="현재 항목과 정확히 일치하는 저장 작업이 없습니다.";
      $("compatText").textContent="기존 문서 작업의 연결을 덮어쓰지 않습니다. 새 작업을 만든 뒤 현재 선택으로 검증합니다.";
      $("compatPrimary").hidden=true;$("compatSecondary").hidden=true;
    }else if(!compatibleWorks().length){
      $("compatNote").hidden=false;
      $("compatTitle").textContent="사용 가능한 문서 작업이 없습니다.";
      $("compatText").textContent="현재 데이터의 실제 항목으로 비교했습니다. 저장 작업의 Binding은 변경하지 않았습니다.";
      $("compatPrimary").hidden=true;$("compatSecondary").hidden=true;
    }else{
      $("compatNote").hidden=true;
    }
  }
	  function hasRequiredIssue(workId) {
	    if(!workId)return true;
	    return compatibilityFor(workId).kind==="needsAction";
	  }
  function renderValidation() {
    const noSelection=!runState.recordRange.selectedIds.size,noWork=!state.activeWorkId||!canUseWork(state.activeWorkId),bad=!noWork&&hasRequiredIssue(state.activeWorkId),pending=state.validation.status==="pending";
    $("validationCard").dataset.state=bad?"bad":pending?"pending":noSelection?"pending":"ready";
    $("validationMark").textContent=bad?"!":pending||noSelection?"…":"✓";
    $("validationTitle").textContent=noSelection?"처리할 항목 선택 필요":noWork?"문서 작업 선택 필요":bad?"생성할 수 없음":pending?"자동 검증 중":"실행 준비 완료";
    $("validationText").textContent=noSelection?"현재 스냅샷에서 처리할 항목을 선택하세요.":noWork?"현재 항목에 사용할 문서 작업을 선택하세요.":bad?"필수 데이터 항목을 찾을 수 없습니다.":pending?"선택, 연결, 표시 결과를 확인합니다.":state.preview.required&&!state.preview.approved?"새 작업 또는 기본 규칙 변경 · 결과 확인 필요":"연결과 표시 결과가 정상입니다.";
    const gated=state.preview.required&&!state.preview.approved;
    $("validationCard").hidden=!noSelection&&!noWork&&!bad&&!pending&&!gated;
    $("runButton").disabled=noSelection||noWork||bad||pending||gated;
    $("previewButton").disabled=noSelection||noWork||bad||pending;
    $("runButton").textContent=state.activeWorkId&&mediaFor(state.activeWorkId)==="txt"?`검토·복사 시작 · ${runState.recordRange.selectedIds.size}건`:`${runState.recordRange.selectedIds.size}개 생성`;
    $("previewButton").textContent=gated?"결과 확인 필요":"미리보기";
    const hidden=hiddenSelectedRecords();
    $("runScopeNote").textContent=noSelection?"처리할 항목을 선택하세요.":hidden.length?`${runState.recordRange.selectedIds.size}건 선택됨 · 현재 필터 밖 선택 ${hidden.length}건 포함`:`${runState.recordRange.selectedIds.size}건 선택됨 · 화면의 전체 표시순서로 처리`;
  }
  function renderData() {
    const runtime=dataState.runtimeData,target=runtime.target,pinned=dataState.mountedDataRef?.origin==="datasetPool";
    $("recordSearch").value=runState.recordRange.search;
    $("fileName").textContent=target?`${target.fileName}${target.sheet?` / ${target.sheet}`:""}`:"데이터 없음";
    $("filePath").textContent=target?.path||runtime.error||"문서를 만들 데이터를 선택하세요.";
    $("fileMeta").textContent=target?`${runtime.records.length}건 · ${runtime.fields.length}개 항목`:"";
    $("fileStatus").textContent=runtime.loadState==="error"?"복원 실패":"선택 전";
    $("fileStatus").hidden=runtime.loadState==="ready";
    $("fileStatus").className=`status ${runtime.loadState==="ready"?"ready":""}`;
    $("dataOrigin").textContent=pinned?`📌 ${dataState.mountedDataRef.datasetRefName} · 고정한 데이터`:"직접 선택한 파일";
    $("pinCurrentData").hidden=!target||pinned;
    $("changeData").textContent=target?"데이터 바꾸기":"데이터 선택";
    renderRecords();renderEvidence();renderWorkChooser();renderValidation();
    const noSelection=!runState.recordRange.selectedIds.size;
    $("workflowState").textContent=!target?"데이터 선택 필요":noSelection?"처리 범위 선택 필요":state.validation.status==="pending"?"검증 중":hasRequiredIssue(state.activeWorkId)?"작업 선택 필요":"준비됨";
    $("workflowMessage").textContent=!target?"파일과 필요한 경우 시트를 먼저 선택하세요.":noSelection?"최신 행부터 보이는 현재 스냅샷에서 처리할 항목을 선택하세요.":state.preview.required&&!state.preview.approved?"변경 결과를 확인해야 실행할 수 있습니다.":"현재 데이터의 실제 항목으로 실행 가능성을 계산했습니다.";
    $("workflowStrip").hidden=Boolean(target)&&!noSelection&&state.validation.status!=="pending"&&!hasRequiredIssue(state.activeWorkId)&&!(state.preview.required&&!state.preview.approved);
    renderResult();
  }
	  async function requestValidation() {
	    if(!runState.recordRange.selectedIds.size||!state.activeWorkId||!canUseWork(state.activeWorkId)){state.validation={status:"idle",id:null};renderValidation();return}
    state.validation={status:"pending",id:null};renderValidation();
    if(hasRequiredIssue(state.activeWorkId)){state.validation={status:"failed",id:null};renderValidation();return}
    try{
      const result=await actions.validateRun({selectedCount:orderedSelectedRecords().length,documentId:state.activeWorkId,bindingRevision:works[state.activeWorkId].bindingRevision});
      state.validation={status:"completed",id:result.validationId};renderData();
    }catch(error){state.validation={status:"failed",id:null};showNotice(error.message,"bad")}
	  }
	  function selectDocumentWork(workId,{fromBrowser=false}={}) {
	    if(!canUseWork(workId))return;
	    state.activeWorkId=workId;
	    state.validation={status:"idle",id:null};
	    state.preview={open:false,index:0,status:"idle",required:false,approved:false,id:null};
	    state.result=null;
	    if(fromBrowser)showScreen("data");
	    renderData();requestValidation();
	    if(fromBrowser)requestAnimationFrame(()=>highlight(`main-work-${workId}`));
	  }
	  function toggleFavorite(workId) {
	    const work=works[workId];if(!work||work.draft||work.damaged)return;
	    work.favoritedAt=work.favoritedAt?"":new Date().toISOString();
	    saveWorkFavorites();
	    renderWorkChooser();
	    if(state.view==="documents")renderDocumentBrowser();
	    if(state.view==="library")renderLibrary();
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
	    const labels={preview_result:`미리보기 ${Number(context.returnContext.previewIndex)+1}/${orderedSelectedRecords().length}에서 열었습니다.`,schema_new_field:"새 데이터 열에서 열었습니다.",schema_missing_field:"필수 필드 누락에서 열었습니다.",document_browser_repair:"현재 데이터 문서 탐색의 연결 복구에서 열었습니다.",document_browser_new_work:"현재 데이터 문서 탐색의 새 작업에서 열었습니다.",run_failure:"실패한 실행에서 열었습니다.",workbench_result:`작업대 ${Number(context.returnContext.workIndex)+1}/${workbenchState.session?.records.length||0}에서 열었습니다.`,library:"문서 작업 목록에서 열었습니다.",voluntary:""};
    return labels[context.entryReason]||"";
  }
  function renderEditorChrome() {
    const context=state.editContext,work=works[context.workId],dirty=Boolean(state.editSession.patch);
    $("editorTitle").textContent=work.name;$("editorSubtitle").textContent=`${work.dataset} · ${workLabel(work.id)} · ${work.templatePath}`;
    $("saveState").textContent=dirty?"저장하지 않은 변경":"저장됨";
    const banner=bannerContent(context);$("contextBanner").hidden=!banner;
    $("contextTitle").textContent=banner;$("contextMessage").textContent=context.evidence.message||"";
	    $("contextReturn").textContent={preview:"미리보기로 돌아가기",data:"데이터로 돌아가기",documents:"문서 탐색으로 돌아가기",result:"실패 결과로 돌아가기",workbench:"작업대로 돌아가기",library:"문서 작업 목록으로 돌아가기"}[context.returnContext.surface]||"원래 업무로 돌아가기";
	    $("evidenceGrid").innerHTML=Object.entries(context.evidence).filter(([,value])=>value!==null&&value!==undefined&&value!=="").map(([key,value])=>`<span><strong>${esc({rawValue:"원본 값",displayValue:"현재 표시",sourceField:"원본 열",missingFields:"확인할 필드",failedFile:"실패 파일",confirmedCause:"확인된 원인",label:"대상",sampleValues:"샘플 값"}[key]||key)}</strong> ${esc(value)}</span>`).join("");
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
    const record=editorSampleRecord();
    if(!record)return {value:"대표 데이터 없음",level:"",text:"실행 선택과 분리된 편집 샘플이 없습니다"};
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
	      if(target&&context.entryReason==="document_browser_repair")evidence=`<div class="row-evidence">현재 DataTarget <strong>${esc(targetLabel(currentTarget()))}</strong> · ${esc(context.evidence.message)} 기본 Binding revision에 저장해야 현재 데이터에서 사용할 수 있습니다.</div>`;
	      if(target&&context.entryReason==="document_browser_new_work")evidence=`<div class="row-evidence">새 문서 작업 identity의 연결입니다. 출발점 Template만 재사용하며 기존 저장 작업의 Binding과 실행 이력은 변경하지 않습니다.</div>`;
      const typeOptions=(value.source==="__direct__"?["const"]:["text","date","amount"]).map((type)=>`<option value="${type}" ${type===value.type?"selected":""}>${typeLabels[type]}</option>`).join("");
      const formats=(formatCatalog[value.type]||formatCatalog.text).map(([key,label])=>`<option value="${key}" ${key===value.format?"selected":""}>${label}</option>`).join("");
      return `<div class="mapping-row ${target?"target":""} ${value.provenance==="suggested"?"suggested":""}" data-field-id="${field.key}"><div class="field-name"><strong>${esc(field.label)}${field.required?" *":""}</strong><span>${field.required?"필수":"선택"} 필드</span></div><div><select data-map-kind="source" aria-label="${esc(field.label)} 데이터 항목">${columnsForOptions(value.source)}</select>${value.source==="__direct__"?`<input data-map-kind="constant" value="${esc(value.constant)}" aria-label="${esc(field.label)} 직접 입력 값" placeholder="고정값">`:""}</div><div><select data-map-kind="type" ${value.source==="__direct__"?"disabled":""} aria-label="${esc(field.label)} 값 유형">${typeOptions}</select><span class="provenance">${provenance}</span></div><div><select data-map-kind="format" aria-label="${esc(field.label)} 표시형">${formats}</select></div><div class="result-cell"><strong>${esc(status.value)}</strong><span>${esc(status.text)}</span></div>${evidence}</div>`;
    }).join("");
  }
  function renderFilename() {
    const context=state.editContext,draft=effectiveDraft(),record=editorSampleRecord();
    $("filenamePattern").value=draft.filenamePattern||"";$("filenamePattern").closest(".form-field").classList.toggle("target",context.section==="filename"&&context.target.id==="filenamePattern");
    $("filenameExample").textContent=`예: ${filenameForDraft(draft.filenamePattern,record)}`;
    $("filenameTokens").textContent=isCustomerData()?"{고객명}, {담당자}":"{성명}, {부서}";
  }
  function filenameForDraft(pattern,record){return (pattern||"문서").replaceAll("{성명}",record?.name||"항목").replaceAll("{고객명}",record?.name||"고객").replaceAll("{담당자}",record?.contact||"담당자")+".hwpx"}
  function renderTest() {
    const context=state.editContext,draft=effectiveDraft(),record=editorSampleRecord(),dateKey=fieldDefs[context.workId].find((field)=>field.type==="date")?.key;
    $("testValidation").textContent=state.validation.status==="completed"?"검증 완료":state.validation.status==="pending"?"검증 중":"검증 필요";
    $("testTemplate").textContent=`r${works[context.workId].templateRevision}`;$("testBinding").textContent=`r${works[context.workId].bindingRevision}`;
    $("testCreated").textContent=state.preview.status==="completed"?"생성됨":"아직 없음";$("testApproved").textContent=state.preview.approved?"명시적 승인 완료":"승인 안 됨";
    const date=dateKey?formatValue(valueFor(context.workId,dateKey,record,draft.binding[dateKey]),draft.binding[dateKey].format):"해당 없음";
    $("testSample").textContent=record?`${record.name||"대표 항목"} · 날짜 ${date}${mediaFor(context.workId)==="hwpx"?` · ${filenameForDraft(draft.filenamePattern,record)}`:""}`:"편집 샘플 데이터가 없습니다.";
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
        state.preview.approved=false;state.preview.required=state.activeWorkId===context.workId;state.preview.status="completed";state.preview.id=`preview-v5-${Date.now()}`;
        if(state.activeWorkId===context.workId){
          state.validation={status:"pending",id:null};
          if(hasRequiredIssue(context.workId))throw new Error("필수 연결이 아직 해결되지 않았습니다.");
          const result=await actions.validateRun({selectedCount:orderedSelectedRecords().length,documentId:context.workId,bindingRevision:works[context.workId].bindingRevision});
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
          const result=await actions.validateRun({selectedCount:orderedSelectedRecords().length,documentId:context.workId,bindingRevision:works[context.workId].bindingRevision});
          state.validation={status:"completed",id:result.validationId};state.preview.status="completed";state.preview.id=`preview-v5-${Date.now()}`;
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
	    else if(ret.surface==="documents"){
	      state.documentBrowser.tab=ret.documentTab||"available";
	      state.documentBrowser.query=ret.documentQuery||"";
	      state.documentBrowser.scrollY=ret.scrollY||0;
	      state.documentBrowser.focusTarget=ret.focusTarget||null;
	      if(!cancelled&&state.documentBrowser.focusTarget?.startsWith("document-work-")){
	        const entryId=state.documentBrowser.focusTarget.slice("document-work-".length);
	        const updatedEntry=documentEntries().find((entry)=>entry.id===entryId);
	        if(updatedEntry)state.documentBrowser.tab=updatedEntry.status;
	      }
	      renderDocumentBrowser();showScreen("documents");window.scrollTo(0,state.documentBrowser.scrollY);
	      requestAnimationFrame(()=>highlight(state.documentBrowser.focusTarget));
	    }
	    else{showScreen("data");renderData();highlight(ret.focusTarget)}
  }
  window.returnFromWorkEditor=returnFromWorkEditor;
  function cancelEditor(){if(!state.editContext)return;returnFromWorkEditor({cancelled:true})}
  function highlight(id){if(!id)return;const element=$(id)||document.querySelector(`[data-focus-id="${CSS.escape(id)}"]`);if(!element)return;element.classList.add("return-highlight");element.scrollIntoView({block:"center"});(element.matches("button,input,select")?element:element.querySelector("button,input,select"))?.focus();setTimeout(()=>element.classList.remove("return-highlight"),2500)}

  function previewContext(key) {
    const record=orderedSelectedRecords()[state.preview.index];if(!record)return null;
    const base=makeReturn("preview",{previewIndex:state.preview.index,focusTarget:`preview-${key}`});
    if(key==="filename")return makeContext({workId:state.activeWorkId,section:"filename",target:{kind:"rule",id:"filenamePattern"},entryReason:"preview_result",evidence:{label:"파일 이름 규칙",displayValue:filenameFor(state.activeWorkId,record),message:"현재 파일 이름에서 열었습니다."},returnContext:base});
    if(key==="template")return makeContext({workId:state.activeWorkId,section:"template",target:{kind:"paragraph",id:"document"},entryReason:"preview_result",evidence:{label:"문서 내용과 구조",message:"미리보기의 템플릿 증거에서 열었습니다."},returnContext:base});
    const binding=effectiveField(state.activeWorkId,key,recordKey(record)),field=fieldDef(state.activeWorkId,key),raw=valueFor(state.activeWorkId,key,record,binding);
    return makeContext({workId:state.activeWorkId,section:"binding",target:{kind:"field",id:key},entryReason:"preview_result",evidence:{label:`${field.label} ${key==="date"?"표시형":"값·표시"}`,rawValue:raw,displayValue:formatValue(raw,binding.format),sourceField:currentColumns().find((column)=>column.key===binding.source)?.label||binding.source,message:"미리보기 결과에서 정확한 필드 규칙을 열었습니다."},returnContext:base});
  }
  async function openPreview({preserve=false,focusTarget=null,message=null}={}) {
    const records=orderedSelectedRecords();
    if(!records.length){showNotice("처리할 항목을 선택하세요.","bad");$("recordRangeButton").focus();return false}
    if(!state.activeWorkId||!canUseWork(state.activeWorkId)){showNotice("현재 데이터에 사용할 문서 작업을 먼저 선택하세요.","bad");return false}
    if(!preserve)state.preview.index=Math.min(state.preview.index,records.length-1);
    state.preview.open=true;state.preview.status="loading";$("scrim").classList.add("on");$("previewDrawer").classList.add("open");$("previewDrawer").removeAttribute("inert");$("previewDrawer").setAttribute("aria-hidden","false");$("workspace").setAttribute("inert","");
    renderPreview(message);try{const result=await actions.createValuePreview({outcome:"success",recordCount:records.length});state.preview.status="completed";state.preview.id=result.previewId;renderPreview(message);if(focusTarget)requestAnimationFrame(()=>highlight(focusTarget));else $("closePreview").focus()}catch(error){state.preview.status="failed";renderPreview(error.message)}
    return true;
  }
  function suspendPreview() {$("scrim").classList.remove("on");$("previewDrawer").classList.remove("open");$("previewDrawer").setAttribute("inert","");$("previewDrawer").setAttribute("aria-hidden","true");$("workspace").removeAttribute("inert");state.preview.open=false}
  function closePreview() {suspendPreview();$("previewButton").focus()}
  function renderPreview(message=null) {
    const records=orderedSelectedRecords(),record=records[state.preview.index],workId=state.activeWorkId;
    if(!record||!workId){if(state.preview.open)suspendPreview();return}
    $("previewPosition").textContent=`${state.preview.index+1} / ${records.length}`;$("previewPrev").disabled=state.preview.index===0;$("previewNext").disabled=state.preview.index>=records.length-1;
    $("previewState").textContent=message||(state.preview.status==="loading"?"실제로 들어갈 값을 준비하고 있습니다.":state.preview.required&&!state.preview.approved?"기본 규칙이 바뀌어 결과 확인이 필요합니다.":"대표 값입니다. 미리보기 생성은 승인과 다릅니다.");
    const fields=fieldDefs[workId],overrideFields=state.runOverrides[workId]?.fields||{};
    const fieldRows=fields.map((field)=>{
      const binding=effectiveField(workId,field.key,recordKey(record)),value=formatValue(valueFor(workId,field.key,record,binding),binding.format),changed=Boolean(overrideFields[field.key]);
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
    const records=orderedSelectedRecords();
    if(!records.length){showNotice("처리할 항목을 선택하세요.","bad");if(state.preview.open)closePreview();return}
    if(!state.activeWorkId||!canUseWork(state.activeWorkId)){showNotice("현재 데이터에 사용할 문서 작업을 먼저 선택하세요.","bad");return}
    if(mediaFor(state.activeWorkId)==="txt"){setupWorkbench();return}
    suspendPreview();showNotice("문서를 처리하고 있습니다. 중복 실행은 잠겼습니다.");$("runButton").disabled=true;
    try{
      const result=await actions.runDocuments({recordCount:records.length,recordIds:records.map(recordKey),outcome:state.outcome});
      state.result={...result,kind:state.outcome,successNames:records.slice(0,result.succeeded).map((r)=>filenameFor(state.activeWorkId,r))};renderData();
    }catch(error){state.result={status:"failed",kind:"processingFailure",message:error.message,runId:"run-unknown",recordId:recordKey(records[0])};renderData()}
  }
  function renderResult() {
    if(!state.result){$("resultPanel").hidden=true;return}$("resultPanel").hidden=false;
    const result=state.result;
    if(result.status==="completed"){
      $("resultTitle").textContent="문서 생성 완료";
      $("resultBody").innerHTML=`<div class="result-summary"><strong>${result.succeeded}개</strong><span>mock 이름과 상태만 표시합니다. 실제 파일이나 다운로드는 없습니다.</span></div><div class="actions"><div class="more-wrap"><button class="button" id="resultMore" type="button" aria-label="완료 결과 더보기" aria-expanded="false">⋯</button><div class="more-menu" id="resultMoreMenu" role="menu" hidden><button type="button" role="menuitem" data-result-action="filename">파일 이름 규칙 수정</button></div></div></div>`;
    }else if(result.status==="partiallyCompleted"){
      const failedId=String(result.failedRecordIds[0]),record=state.records.find((r)=>recordKey(r)===failedId);
      $("resultTitle").textContent=`${result.succeeded}개 성공 · ${result.failed}개 실패`;
      $("resultBody").innerHTML=`<div class="result-list">${result.successNames.map((name)=>`<div class="result-row">성공 · ${esc(name)}</div>`).join("")}<div class="result-row failure" id="failed-output"><strong>${esc(filenameFor(state.activeWorkId,record))} 저장 실패</strong><p>확인된 원인: 같은 이름의 파일이 있습니다. 성공한 ${result.succeeded}건은 그대로 보존합니다.</p><div class="actions"><button class="button primary" type="button" data-runtime-action="number" data-record-id="${esc(failedId)}">번호를 붙여 이 1건 다시 시도</button><button class="button" type="button" data-runtime-action="rename" data-record-id="${esc(failedId)}">이번 실패 파일 이름 바꾸기</button><button class="button" type="button" data-runtime-action="folder">다른 폴더에서 다시 시도</button></div></div></div>`;
    }else{
      $("resultTitle").textContent="문서 처리 실패";
      $("resultBody").innerHTML=`<div class="result-row failure" id="unknown-failure"><strong>원인 진단 미연결</strong><p>${esc(result.message||"처리 단계가 완료되지 않았습니다.")}</p><button class="button primary" type="button" data-runtime-action="inspect">확인 가능한 증거 보기</button></div>`;
    }
  }
  async function retryOne(recordId,filename=null) {
    const record=state.records.find((r)=>recordKey(r)===String(recordId));if(!record)return;
    state.runOverrides[state.activeWorkId]??={fields:{},records:{}};state.runOverrides[state.activeWorkId].records??={};
    if(filename)state.runOverrides[state.activeWorkId].records[recordId]={filename};
    showNotice(`${record.name} 1건만 다시 처리합니다. 성공한 결과는 유지됩니다.`);
    const retried=await actions.retryFailedDocuments({recordCount:1,recordIds:[recordId],outcome:"success"});
    const previous=state.result;
    state.result={...retried,status:"completed",succeeded:(previous?.succeeded||0)+1,successNames:[...(previous?.successNames||[]),filenameFor(state.activeWorkId,record)]};renderData();highlight("resultPanel");
  }
  function resultFilenameEditor() {
    const context=makeContext({workId:state.activeWorkId,section:"filename",target:{kind:"rule",id:"filenamePattern"},entryReason:"output_result",evidence:{label:"파일 이름 규칙",message:"완료 결과의 더보기에서 열었습니다."},returnContext:makeReturn("result",{focusTarget:"resultPanel"})});openWorkEditor(context);
  }

  function setupWorkbench() {
    const records=orderedSelectedRecords();
    if(!records.length){showNotice("처리할 항목을 선택하세요.","bad");return}
    workbenchState.session={snapshotId:dataState.runtimeData.snapshotId,records:records.map(clone),index:0};
    state.workValues=clone(state.bindings.order);state.workPatch={};state.copied=new Set();state.review=new Set();renderWorkbench();showScreen("workbench");
  }
  function workRecord(){return workbenchState.session?.records[state.workIndex]||null}
  function renderWorkbench() {
    const session=workbenchState.session,record=workRecord(),total=session?.records.length||0;if(!record)return;
    $("workPosition").textContent=`${state.workIndex+1} / ${total}`;$("copyCount").textContent=`${state.copied.size} / ${total}`;$("workPrev").disabled=state.workIndex===0;$("workNext").disabled=state.workIndex===total-1;
    $("persistWorkPatch").disabled=!Object.keys(state.workPatch).length;$("sessionStatus").textContent=Object.keys(state.workPatch).length?"이번 작업에만 적용 중":"기본 규칙";
    $("workMappings").innerHTML=fieldDefs.order.map((field)=>{
      const value={...state.bindings.order[field.key],...(state.workPatch[field.key]||{})};
      const formats=(formatCatalog[value.type]||formatCatalog.text).map(([key,label])=>`<option value="${key}" ${key===value.format?"selected":""}>${label}</option>`).join("");
      return `<div class="work-map-row" data-work-key="${field.key}" id="work-rule-${field.key}"><strong>${esc(field.label)}</strong><select data-work-source aria-label="${esc(field.label)} 데이터 항목">${columnsForOptions(value.source)}</select><select data-work-format aria-label="${esc(field.label)} 표시형">${formats}</select></div>`;
    }).join("");
    const value=(key)=>{const binding={...state.bindings.order[key],...(state.workPatch[key]||{})};return formatValue(record[binding.source],binding.format)};
    $("reviewState").textContent=state.review.has(recordKey(record))?"규칙 변경 뒤 다시 확인 필요":state.copied.has(recordKey(record))?"복사 완료":"복사 전";
    $("workPreview").innerHTML=state.workMode==="raw"?`<h2>발주 요청문 원문</h2><p>{{업체명}}에 {{요청 품목}} {{수량}}개를 요청합니다.</p>`:`<h2>발주 요청문</h2><p><button type="button" data-work-result="company">${esc(value("company"))}</button>에 <button type="button" data-work-result="item">${esc(value("item"))}</button> <button type="button" data-work-result="quantity">${esc(value("quantity"))}</button>개를 요청합니다.</p><p>요청 금액 <button type="button" data-work-result="amount">${esc(value("amount"))}</button></p>`;
  }
  function dirtyCopiedForReview(){state.copied.forEach((id)=>state.review.add(id))}
  async function persistWorkbenchPatch() {
    const patch=clone(state.workPatch);if(!Object.keys(patch).length)return;
    const result=await actions.saveEditorChange({outcome:state.outcome,documentId:"order",section:"binding",bindingRevision:works.order.bindingRevision,templateRevision:works.order.templateRevision});
    Object.entries(patch).forEach(([key,value])=>state.bindings.order[key]={...state.bindings.order[key],...value,provenance:"user"});
    works.order.bindingRevision=result.bindingRevision;state.workPatch={};state.validation={status:"pending",id:null};
    await actions.validateRun({selectedCount:workbenchState.session?.records.length||0,documentId:"order",bindingRevision:works.order.bindingRevision});state.validation.status="completed";state.preview.required=true;state.preview.approved=false;renderWorkbench();toast(`Binding r${works.order.bindingRevision} 저장 · 재검증 완료 · 작업점 ${state.workIndex+1} 유지`);
  }

	  function startCustomerWork({templateId="salary",suggestedName=null,returnContext=null}={}) {
	    const template=works[templateId]||works.salary;
	    state.newWorkSource={templateId:template.id,returnContext:returnContext||makeReturn("data",{focusTarget:"documentSideCard"})};
	    $("newWorkName").value=suggestedName||`${targetLabel(currentTarget()).replace(/\.[^.]+(?: \/ .*)?$/,"")} ${template.name}`;
	    if(!$("newWorkTemplate").querySelector(`option[value="${CSS.escape(template.id)}"]`))$("newWorkTemplate").insertAdjacentHTML("beforeend",`<option value="${template.id}">${esc(template.name)} ${mediaFor(template.id).toUpperCase()}</option>`);
	    $("newWorkTemplate").value=template.id;
	    $("newWorkDescription").textContent="새 identity와 Binding draft를 만듭니다. 출발점 작업의 Binding, 즐겨찾기, 마지막 성공 실행, 기본 데이터 참조는 변경하거나 물려받지 않습니다.";
	    openDialog($("newWorkDialog"),document.activeElement);$("newWorkName").focus();
	  }
	  function createCustomerDraft() {
	    const templateId=$("newWorkTemplate").value,workId=`customer-${Date.now()}`,source=works[templateId];
	    works[workId]={id:workId,name:$("newWorkName").value.trim()||"새 문서 작업",templatePath:source.templatePath,dataset:"현재 데이터용 새 작업",filenamePattern:isCustomerData()?"{고객명}_문서":"{성명}_문서",templateRevision:1,bindingRevision:0,draft:true,dataFamily:currentDataFamily(),favoritedAt:"",last_run_at:"",default_dataset_ref:""};
	    fieldDefs[workId]=clone(fieldDefs[templateId]);state.bindings[workId]=Object.fromEntries(fieldDefs[workId].map((field)=>[field.key,{source:"",type:field.type,format:field.format,constant:"",provenance:"suggested",intentionallyUnused:false}]));
	    const aliases={date:["date","requestDate"],salary:["salary","amount"],name:["name"]};
	    const changes={};fieldDefs[workId].forEach((field)=>{
	      const sourceKey=(aliases[field.key]||[field.key]).find((key)=>currentColumns().some((column)=>column.key===key))||"";
	      changes[field.key]={source:sourceKey,type:currentColumns().find((c)=>c.key===sourceKey)?.type||field.type,format:field.format,provenance:sourceKey?"suggested":"unused",intentionallyUnused:!sourceKey};
	    });
	    state.newWorkDraft=workId;
	    const returnContext=state.newWorkSource?.returnContext||makeReturn("data",{focusTarget:"documentSideCard"});
	    openWorkEditor(makeContext({workId,section:"binding",target:{kind:"field",id:fieldDefs[workId][0].key},entryReason:returnContext.surface==="documents"?"document_browser_new_work":"voluntary",evidence:{label:"새 문서 작업",message:"기존 저장 작업은 유지됩니다. 이 새 identity의 필드만 저장합니다."},returnContext,initialPatch:{section:"binding",changes}}));
	  }
	  function openDocumentBrowser({restore=false}={}) {
	    if(dataState.runtimeData.loadState!=="ready")return;
	    renderDocumentBrowser();showScreen("documents");
	    if(restore)window.scrollTo(0,state.documentBrowser.scrollY||0);
	    else{state.documentBrowser.scrollY=0;window.scrollTo(0,0)}
	    requestAnimationFrame(()=>$("documentsBack").focus());
	  }
	  function openBindingRepair(workId) {
	    const compatibility=compatibilityFor(workId),first=compatibility.missing[0];
	    if(!first)return;
	    state.documentBrowser.scrollY=window.scrollY;
	    const summary=compatibility.missing.map((item)=>`${item.fieldLabel}(${item.reason})`).join(", ");
	    openWorkEditor(makeContext({
	      workId,section:"binding",target:{kind:"field",id:first.fieldId},entryReason:"document_browser_repair",
	      evidence:{label:"연결 복구",sourceField:first.source||"선언 없음",missingFields:summary,message:"현재 선택 시트에서 필요한 원본 항목을 찾을 수 없습니다."},
	      returnContext:makeDocumentBrowserReturn(`document-work-${workId}`)
	    }));
	  }
	  function proposeDefaultData(workId,trigger) {
	    const work=works[workId],datasetRefName=work?.default_dataset_ref;
	    const item=datasetRefName&&dataState.pinnedDataRefs.find((entry)=>entry.datasetRefName===datasetRefName);
	    if(!item||item.status!=="active"||!findFileByPath(item.path)){
	      $("documentsNotice").hidden=false;$("documentsNotice").className="notice bad";
	      $("documentsNotice").textContent=`${work.name}의 기본 데이터 ‘${datasetRefName||"없음"}’에 연결할 수 없습니다. 현재 데이터는 유지됩니다.`;
	      return;
	    }
	    dataState.pendingSuggestedWork={workId,datasetRefName};
	    $("defaultDataSuggestionText").textContent=`현재 데이터에는 ${work.name}의 필수 항목이 없습니다. 고정한 데이터 ‘${datasetRefName}’로 바꾸면 현재 선택·검색·검증·미리보기·결과가 초기화됩니다.`;
	    openDialog($("defaultDataSuggestionDialog"),trigger);
	  }
	  function startNewWorkFromEntry(entryId) {
	    const template=templateOnlyItems.find((item)=>item.id===entryId);
	    const source=template?works[template.templateWorkId]:works[entryId];
	    if(!source)return;
	    state.documentBrowser.scrollY=window.scrollY;
	    startCustomerWork({
	      templateId:source.id,
	      suggestedName:template?.name||`${source.name} - ${targetLabel(currentTarget())}`,
	      returnContext:makeDocumentBrowserReturn(`document-work-${entryId}`)
	    });
	  }
	  function showDeferred(message){$("deferredText").textContent=message;$("deferredDialog").showModal()}

	  const MOUNTED_DATA_KEY="narmi.prototype.mounted-data.v2";
	  const DATASET_POOL_KEY="narmi.prototype.dataset-pool.v1";
	  const WORK_FAVORITES_KEY="narmi.prototype.work-favorites.v1";
  const dialogOpeners=new WeakMap();
  function openDialog(dialog,trigger=document.activeElement) {
    dialogOpeners.set(dialog,trigger);
    dialog.showModal();
    requestAnimationFrame(()=>dialog.querySelector("button:not([disabled]),input:not([disabled]),select:not([disabled])")?.focus());
  }
  document.querySelectorAll("dialog").forEach((dialog)=>{
    dialog.addEventListener("close",()=>dialogOpeners.get(dialog)?.focus?.());
    dialog.addEventListener("keydown",(event)=>{
      if(event.key==="Escape"){event.preventDefault();dialog.close();return}
      if(event.key!=="Tab")return;
      const focusable=[...dialog.querySelectorAll("button:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex='-1'])")].filter((item)=>!item.hidden);
      if(!focusable.length)return;
      const first=focusable[0],last=focusable.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
    });
  });
	  function saveDataReferences() {
	    try{
	      localStorage.setItem(MOUNTED_DATA_KEY,JSON.stringify(dataState.mountedDataRef));
	      localStorage.setItem(DATASET_POOL_KEY,JSON.stringify(dataState.pinnedDataRefs));
	    }catch(error){showNotice(`시안 참조 저장 실패: ${error.message}`,"bad")}
	  }
	  function saveWorkFavorites() {
	    try{
	      const favorites=Object.fromEntries(Object.values(works).filter((work)=>work.favoritedAt).map((work)=>[work.id,work.favoritedAt]));
	      localStorage.setItem(WORK_FAVORITES_KEY,JSON.stringify(favorites));
	    }catch(error){showNotice(`문서 즐겨찾기 시안 저장 실패: ${error.message}`,"bad")}
	  }
	  function restoreWorkFavorites() {
	    try{
	      const stored=JSON.parse(localStorage.getItem(WORK_FAVORITES_KEY)||"null");
	      if(!stored||typeof stored!=="object"||Array.isArray(stored))return;
	      Object.values(works).forEach((work)=>{if(Object.prototype.hasOwnProperty.call(stored,work.id))work.favoritedAt=typeof stored[work.id]==="string"?stored[work.id]:""});
	    }catch(error){showNotice(`문서 즐겨찾기 시안 저장값을 읽지 못했습니다: ${error.message}`,"bad")}
	  }
  function findFileByPath(path){return Object.entries(dataFiles).find(([,file])=>file.path===path)?.[0]||null}
  function targetLabel(target){return target?`${target.fileName}${target.sheet?` / ${target.sheet}`:""}`:"데이터 없음"}
  function switchLosses() {
    const losses=[];
    const range=runState.recordRange;
    if(range.selectedIds.size)losses.push(`선택한 레코드 ${range.selectedIds.size}건`);
    if(range.search.trim())losses.push("검색어 1개");
    if(activeFilterCount(range))losses.push(`열 필터 ${activeFilterCount(range)}개`);
    if(range.viewOrder!=="sourceDesc")losses.push("원본 순서 표시");
    if(runState.rangeEditor?.dirty)losses.push("적용하지 않은 범위 편집 초안");
    const overrideCount=Object.values(state.runOverrides).reduce((count,value)=>count+Object.keys(value.fields||{}).length+Object.keys(value.records||{}).length+(value.filenamePattern?1:0),0);
    if(overrideCount)losses.push(`이번 생성에만 적용한 규칙 ${overrideCount}개`);
    if(state.preview.approved||state.preview.index)losses.push(`미리보기 ${state.preview.index+1}/${Math.max(orderedSelectedRecords().length,1)} 확인 상태`);
    if(state.result)losses.push("현재 처리 결과");
    if(state.copied.size)losses.push(`복사 완료 ${state.copied.size}건`);
    if(Object.keys(state.workPatch).length)losses.push(`작업대 표시 규칙 ${Object.keys(state.workPatch).length}개`);
    return losses;
  }
  function resetDataOwnedState(snapshotId=null) {
    runState.recordRange=emptyRecordRange(snapshotId);runState.rangeEditor=null;
    runState.validation={status:"idle",id:null};
    runState.preview={open:false,index:0,status:"idle",required:false,approved:false,id:null};
    runState.runOverrides={};runState.dismissedSuggestions=new Set();runState.result=null;runState.pendingActiveValidation=null;
    workbenchState.session=null;workbenchState.workMode="filled";workbenchState.workPatch={};workbenchState.workValues={};
    workbenchState.copied=new Set();workbenchState.review=new Set();
  }
	  function commitPreparedMount(prepared) {
	    const {loaded,origin,datasetRefName,relinkName,preferredWorkId}=prepared;
	    const previousActiveWorkId=state.activeWorkId;
	    const snapshotId=`snapshot-${Date.now()}-${++snapshotSequence}`,records=normalizeSnapshotRecords(loaded.records,snapshotId);
	    dataState.runtimeData={loadState:"ready",snapshotId,target:clone(loaded.target),fields:clone(loaded.fields),records,error:null};
    resetDataOwnedState(snapshotId);
    if(relinkName){
      const item=dataState.pinnedDataRefs.find((entry)=>entry.datasetRefName===relinkName);
      Object.assign(item,{path:loaded.target.path,fileName:loaded.target.fileName,sheet:loaded.target.sheet,headerRow:loaded.target.headerRow??null,status:"active"});
    }
    dataState.mountedDataRef=origin==="datasetPool"
      ?{origin:"datasetPool",directTarget:null,datasetRefName:datasetRefName||relinkName,mountedAt:new Date().toISOString()}
      :{origin:"direct",directTarget:clone(loaded.target),datasetRefName:null,mountedAt:new Date().toISOString()};
	    dataState.pendingMount=null;dataState.dataLoadState="ready";dataState.pendingRelinkName=null;
	    const eligible=compatibleWorks();
	    if(preferredWorkId&&eligible.some((work)=>work.id===preferredWorkId))state.activeWorkId=preferredWorkId;
	    else if(previousActiveWorkId&&eligible.some((work)=>work.id===previousActiveWorkId))state.activeWorkId=previousActiveWorkId;
	    else if(eligible.length===1)state.activeWorkId=eligible[0].id;
	    else state.activeWorkId=null;
	    if(preferredWorkId)showScreen("data");
	    saveDataReferences();renderData();
    if(state.activeWorkId)requestValidation();
    toast(`${targetLabel(loaded.target)} 데이터를 준비했습니다.`);
  }
  function acceptPreparedMount(prepared) {
    const losses=switchLosses();
    if(dataState.runtimeData.loadState==="ready"&&losses.length){
      dataState.pendingMount=prepared;
      $("dataSwitchLosses").innerHTML=losses.map((loss)=>`<li>${esc(loss)}</li>`).join("");
      openDialog($("dataSwitchGuardDialog"),$("changeData"));
      return;
    }
    commitPreparedMount(prepared);
  }
  async function loadCandidate(fileKey,sheetName,{origin="direct",datasetRefName=null,relinkName=null,preferredWorkId=null}={}) {
    const file=dataFiles[fileKey];
    dataState.dataLoadState="loading";
    $("dataPickerStatus").textContent=`${file.fileName}${sheetName?` / ${sheetName}`:""} 읽는 중…`;
    try{
      const loaded=await actions.mountDataTarget({path:file.path,fileName:file.fileName,kind:file.kind,sheet:sheetName,headerRow:null,file});
      if($("dataPickerDialog").open)$("dataPickerDialog").close();
      if($("sheetPickerDialog").open)$("sheetPickerDialog").close();
      acceptPreparedMount({loaded,origin,datasetRefName,relinkName,preferredWorkId});
    }catch(error){
      dataState.dataLoadState="error";dataState.pendingMount=null;
      if(!$("dataPickerDialog").open)openDialog($("dataPickerDialog"),$("changeData"));
      $("dataPickerStatus").textContent=`${file.fileName}을(를) 열 수 없습니다. ${dataState.runtimeData.loadState==="ready"?`현재 ${targetLabel(currentTarget())} 데이터는 그대로 유지됩니다.`:""} ${error.message}`;
      renderDataPicker();
    }
  }
  async function inspectFile(fileKey,{origin="direct",datasetRefName=null,relinkName=null}={}) {
    const file=dataFiles[fileKey];dataState.pendingMount={fileKey,origin,datasetRefName,relinkName};dataState.dataLoadState="inspecting";
    $("dataPickerStatus").textContent=`${file.fileName} 검사 중…`;
    try{
      const inspected=await actions.inspectDataFile({path:file.path,file});
      if(inspected.sheets.length>1){
        dataState.dataLoadState="choosingSheet";
        $("sheetList").innerHTML=inspected.sheets.map((sheet)=>`<button class="sheet-option" type="button" data-sheet-name="${esc(sheet.name)}"><span><strong>${esc(sheet.name)}</strong><span>약 ${sheet.rows}행×${sheet.columns}열</span><span class="header-sample">${esc(sheet.headerSample.join(" · "))}${sheet.headerSample.length>=6?" …":""}</span></span><span>선택</span></button>`).join("");
        if($("dataPickerDialog").open)$("dataPickerDialog").close();
        openDialog($("sheetPickerDialog"),$("changeData"));
      }else{
        await loadCandidate(fileKey,inspected.sheets[0]?.name||null,{origin,datasetRefName,relinkName});
      }
    }catch(error){
      dataState.dataLoadState="error";dataState.pendingMount=null;
      $("dataPickerStatus").textContent=`${file.fileName}을(를) 검사할 수 없습니다. ${dataState.runtimeData.loadState==="ready"?`현재 ${targetLabel(currentTarget())} 데이터는 그대로 유지됩니다.`:""} ${error.message}`;
      renderDataPicker();
    }
  }
  function renderDataPicker() {
    const target=currentTarget();
    $("pickerCurrent").innerHTML=target?`<div class="picker-item current"><span><strong>${esc(targetLabel(target))}</strong><span>${state.records.length}건 · ${currentColumns().length}개 항목</span></span><span class="status ready">선택됨</span></div>`:`<div class="empty">현재 데이터가 없습니다.</div>`;
    $("pinnedDataList").innerHTML=dataState.pinnedDataRefs.map((item)=>`<div class="picker-item ${item.status==="missing"?"missing":""}"><span><strong>📌 ${esc(item.name)}</strong><span>${esc(item.fileName)}${item.sheet?` / ${esc(item.sheet)}`:""}</span><span>${item.status==="missing"?"파일을 찾을 수 없음":esc(item.path)}</span></span><button class="button" type="button" data-pinned-name="${esc(item.datasetRefName)}">${item.status==="missing"?"다시 연결":"사용"}</button></div>`).join("");
    $("mockFileList").innerHTML=Object.entries(dataFiles).map(([key,file])=>`<div class="picker-item"><span><strong>${esc(file.fileName)}</strong><span>${file.kind.toUpperCase()}${file.sheets.length>1?` · 시트 ${file.sheets.length}개`:""}</span></span><button class="button" type="button" data-file-key="${key}">이 샘플 선택</button></div>`).join("");
  }
  function openDataPicker(trigger=$("changeData")) {
    $("dataPickerStatus").textContent="";
    renderDataPicker();openDialog($("dataPickerDialog"),trigger);
  }
  async function restoreMountedData(ref,{persist=false}={}) {
    if(!ref){dataState.mountedDataRef=null;dataState.runtimeData={loadState:"empty",snapshotId:null,target:null,fields:[],records:[],error:null};resetDataOwnedState();state.activeWorkId=null;if(persist)saveDataReferences();renderData();return}
    let target,datasetRefName=null;
    if(ref.origin==="datasetPool"){
      datasetRefName=ref.datasetRefName;
      const item=dataState.pinnedDataRefs.find((entry)=>entry.datasetRefName===datasetRefName);
      if(!item||item.status==="missing"){
        dataState.mountedDataRef=clone(ref);dataState.runtimeData={loadState:"error",snapshotId:null,target:item?{path:item.path,fileName:item.fileName,sheet:item.sheet,headerRow:item.headerRow}:null,fields:[],records:[],error:"연결된 파일을 찾을 수 없습니다."};
        resetDataOwnedState();state.activeWorkId=null;if(persist)saveDataReferences();renderData();return;
      }
      target=item;
    }else target=ref.directTarget;
    const fileKey=findFileByPath(target.path);
    if(!fileKey){
      dataState.mountedDataRef=clone(ref);dataState.runtimeData={loadState:"error",snapshotId:null,target:clone(target),fields:[],records:[],error:"파일을 찾을 수 없습니다."};
      resetDataOwnedState();state.activeWorkId=null;if(persist)saveDataReferences();renderData();return;
    }
    try{
      const loaded=await actions.mountDataTarget({path:target.path,fileName:target.fileName,kind:dataFiles[fileKey].kind,sheet:target.sheet||null,headerRow:target.headerRow??null,file:dataFiles[fileKey]});
      commitPreparedMount({loaded,origin:ref.origin,datasetRefName});
    }catch(error){
      dataState.mountedDataRef=clone(ref);dataState.runtimeData={loadState:"error",snapshotId:null,target:clone(target),fields:[],records:[],error:error.message};
      resetDataOwnedState();state.activeWorkId=null;if(persist)saveDataReferences();renderData();
    }
  }
  function directTestRef(fileKey,sheet=null) {
    const file=dataFiles[fileKey];
    return {origin:"direct",directTarget:{path:file.path,fileName:file.fileName,sheet,headerRow:null},datasetRefName:null,mountedAt:new Date().toISOString()};
  }
  function renderTestHarness() {
    $("testScenarioCurrent").textContent=testScenarioIndex<0?"선택 안 함":testScenarios[testScenarioIndex].label;
    $("testScenarioList").innerHTML=testScenarios.map((scenario,index)=>`<button class="button" type="button" data-test-scenario="${scenario.id}" aria-current="${index===testScenarioIndex}">${scenario.label}</button>`).join("");
  }
  async function applyTestScenario(scenarioId) {
    const index=testScenarios.findIndex((scenario)=>scenario.id===scenarioId);
    if(index<0)return;
    $("testHarness").setAttribute("aria-busy","true");
    $("dataNotice").hidden=true;$("dataNotice").textContent="";
    try{
      if(scenarioId==="empty")await restoreMountedData(null,{persist:true});
      if(scenarioId==="august-payroll")await restoreMountedData(directTestRef("august","급여현황"),{persist:true});
      if(scenarioId==="september-payroll")await restoreMountedData(directTestRef("september","급여현황"),{persist:true});
      if(scenarioId==="september-department")await restoreMountedData(directTestRef("september","부서별 합계"),{persist:true});
      if(scenarioId==="september-guide")await restoreMountedData(directTestRef("september","안내"),{persist:true});
      if(scenarioId==="customer")await restoreMountedData(directTestRef("customer"),{persist:true});
      if(scenarioId==="pinned")await restoreMountedData({origin:"datasetPool",directTarget:null,datasetRefName:"직원 현황",mountedAt:new Date().toISOString()},{persist:true});
      if(scenarioId==="missing")await restoreMountedData({origin:"datasetPool",directTarget:null,datasetRefName:"이전 직원 현황",mountedAt:new Date().toISOString()},{persist:true});
      if(scenarioId==="corrupt"){
        const file=dataFiles.corrupt;
        try{
          await actions.mountDataTarget({path:file.path,fileName:file.fileName,kind:file.kind,sheet:null,headerRow:null,file});
        }catch(error){
          showNotice(`손상 파일 실패를 재현했습니다. ${dataState.runtimeData.loadState==="ready"?`현재 ${targetLabel(currentTarget())} 데이터는 그대로 유지됩니다. `:""}${error.message}`,"bad");
        }
      }
      if(scenarioId==="guard"){
        await restoreMountedData(directTestRef("september","급여현황"),{persist:true});
        runState.recordRange.selectedIds=new Set(orderedSnapshotRecords().slice(0,2).map(recordKey));runState.recordRange.search="김";
        runState.recordRange.columnFilters={
          department:{values:["인사운영팀","재정기획팀"]},
          salary:{range:{first:{op:"ge",operand:"3000000"},joiner:"and",second:null}}
        };
        state.runOverrides.salary={fields:{date:{format:"dateLongKo"}},records:{}};state.preview={open:false,index:3,status:"completed",required:true,approved:true,id:"guard-preview"};
        state.copied=new Set(orderedSnapshotRecords().slice(0,2).map(recordKey));state.workPatch={amount:{format:"number"}};renderData();
      }
      if(scenarioId==="record-scale")await restoreMountedData(directTestRef("cumulative","직원현황"),{persist:true});
      testScenarioIndex=index;renderTestHarness();
    }finally{
      $("testHarness").setAttribute("aria-busy","false");
    }
  }
  window.loadRecordScale = (count=320) => {
    const safe=Math.max(0,Math.min(3000,Number(count)||0)),file={
      path:`C:\\Prototype\\record-scale-${safe}.xlsx`,fileName:`레코드_성능_${safe}건.xlsx`,kind:"excel",
      sheets:[{name:"직원현황",rows:safe,columns:10,headerSample:["사번","성명","부서","기준일","기본급","성과급"],fields:dataFiles.cumulative.sheets[0].fields,records:makeScaleRecords(safe)}]
    };
    dataFiles.recordScaleRuntime=file;
    const loaded={target:{path:file.path,fileName:file.fileName,kind:file.kind,sheet:"직원현황",headerRow:null},fields:clone(file.sheets[0].fields),records:clone(file.sheets[0].records)};
    const started=performance.now();commitPreparedMount({loaded,origin:"direct"});return {count:safe,renderMs:performance.now()-started,domRows:$("recordBody").rows.length,htmlBytes:new Blob([$("recordBody").innerHTML]).size};
  };
  window.measureRecordRangePerformance = () => {
    const rows=state.records.length,originalRange=cloneRange(runState.recordRange),originalEditor=runState.rangeEditor,result={rows};
    const elapsed=(task)=>{const started=performance.now();task();return performance.now()-started};
    try{
      const range=runState.recordRange;
      range.selectedIds.clear();range.search="";range.columnFilters={};range.viewOrder="sourceDesc";range.selectedOnly=false;
      result.renderMs=elapsed(renderRecords);
      range.search="인사";result.searchMs=elapsed(renderRecords);range.search="";
      range.columnFilters={department:{values:["인사운영팀"]}};result.filterMs=elapsed(renderRecords);
      range.viewOrder="sourceAsc";result.orderMs=elapsed(renderRecords);
      range.viewOrder="sourceDesc";
      result.selectVisibleMs=elapsed(()=>{visibleOrderedRecords(range).forEach((record)=>range.selectedIds.add(recordKey(record)));renderRecords()});
      result.unselectVisibleMs=elapsed(()=>{visibleOrderedRecords(range).forEach((record)=>range.selectedIds.delete(recordKey(record)));renderRecords()});
      range.columnFilters={};renderRecords();
      orderedSnapshotRecords(range).slice(0,Math.min(rows,100)).forEach((record)=>range.selectedIds.add(recordKey(record)));
      result.clearAllMs=elapsed(()=>{range.selectedIds.clear();renderRecords()});
      orderedSnapshotRecords(range).slice(0,Math.min(rows,100)).forEach((record)=>range.selectedIds.add(recordKey(record)));
      result.editorEnterMs=elapsed(()=>{
        const draft=cloneRange(range);
        runState.rangeEditor={draft,baseFingerprint:selectionFingerprint(range),baseDefinitionFingerprint:rangeDefinitionFingerprint(draft),dirty:false,pendingExit:null,returnContext:{surface:"data",focusTarget:"recordRangeButton",scrollY:0}};
        renderRangeEditor();
      });
      result.selectedOnlyMs=elapsed(()=>{runState.rangeEditor.draft.selectedOnly=true;renderRangeEditor()});
      result.applyMainMs=elapsed(()=>{const applied=cloneRange(runState.rangeEditor.draft);applied.selectedOnly=false;runState.recordRange=applied;renderData()});
      result.domRows=$("recordBody").rows.length;
      result.editorDomRows=$("rangeEditorBody").rows.length;
      result.htmlBytes=new Blob([$("recordBody").innerHTML]).size;
      return result;
    }finally{
      runState.recordRange=originalRange;runState.rangeEditor=originalEditor;renderData();
    }
  };

  $("outcomeSelect").addEventListener("change",(event)=>{state.outcome=event.target.value;state.result=null;renderData()});
  $("testHarness").addEventListener("click",(event)=>{
    const scaleButton=event.target.closest("[data-record-scale]");
    if(scaleButton){
      const loaded=window.loadRecordScale(Number(scaleButton.dataset.recordScale));
      const measured=window.measureRecordRangePerformance();
      $("recordPerformanceResult").textContent=JSON.stringify({...loaded,loadRenderMs:loaded.renderMs,...measured});
      return;
    }
    const scenarioButton=event.target.closest("[data-test-scenario]");
    if(scenarioButton){applyTestScenario(scenarioButton.dataset.testScenario);return}
    if(event.target.closest("#testScenarioPrev")){
      const previous=(testScenarioIndex<=0?testScenarios.length:testScenarioIndex)-1;
      applyTestScenario(testScenarios[previous].id);
    }
    if(event.target.closest("#testScenarioNext")){
      const next=(testScenarioIndex+1)%testScenarios.length;
      applyTestScenario(testScenarios[next].id);
    }
  });
	  $("changeData").addEventListener("click",(event)=>openDataPicker(event.currentTarget));
	  $("browseOtherWorks").addEventListener("click",()=>openDocumentBrowser());
	  $("documentsBack").addEventListener("click",()=>{state.documentBrowser.scrollY=window.scrollY;showScreen("data");renderData();requestAnimationFrame(()=>$("browseOtherWorks").focus())});
	  document.querySelector(".document-tabs").addEventListener("click",(event)=>{
	    const tab=event.target.closest("[data-document-tab]");if(!tab)return;
	    state.documentBrowser.tab=tab.dataset.documentTab;renderDocumentBrowser();tab.focus();
	  });
	  document.querySelector(".document-tabs").addEventListener("keydown",(event)=>{
	    if(!["ArrowLeft","ArrowRight"].includes(event.key))return;
	    const tabs=[...document.querySelectorAll("[data-document-tab]")],index=tabs.indexOf(document.activeElement);
	    const next=tabs[(index+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length];
	    event.preventDefault();state.documentBrowser.tab=next.dataset.documentTab;renderDocumentBrowser();next.focus();
	  });
	  $("documentSearch").addEventListener("input",(event)=>{state.documentBrowser.query=event.target.value;renderDocumentBrowser()});
	  $("documentBrowserList").addEventListener("click",(event)=>{
	    const favorite=event.target.closest("[data-favorite-work]");
	    if(favorite){event.stopPropagation();toggleFavorite(favorite.dataset.favoriteWork);return}
	    const select=event.target.closest("[data-document-select]");
	    if(select){selectDocumentWork(select.dataset.documentSelect,{fromBrowser:true});return}
	    const action=event.target.closest("[data-document-action]");
	    if(action){
	      const entryId=action.dataset.documentEntryId;
	      if(action.dataset.documentAction==="repair")openBindingRepair(entryId);
	      if(action.dataset.documentAction==="defaultData")proposeDefaultData(entryId,action);
	      if(action.dataset.documentAction==="newWork")startNewWorkFromEntry(entryId);
	      if(action.dataset.documentAction==="relinkDefault"){
	        const work=works[entryId];dataState.pendingRelinkName=work.default_dataset_ref;
	        openDataPicker(action);
	        $("dataPickerStatus").textContent=`${work.default_dataset_ref} 참조에 연결할 새 파일을 고르세요. 성공적으로 읽은 뒤에만 참조를 갱신합니다.`;
	      }
	      return;
	    }
	    const boundary=event.target.closest("[data-document-boundary]");
	    if(boundary)showDeferred("손상 작업은 연결 필요로 추측하지 않습니다. Job JSON과 Template 파일을 확인한 뒤 다시 탐색해야 합니다.");
	  });
	  $("defaultDataSuggestionDialog").addEventListener("close",()=>{
    const pending=dataState.pendingSuggestedWork;dataState.pendingSuggestedWork=null;
    if($("defaultDataSuggestionDialog").returnValue!=="switch"||!pending)return;
    const item=dataState.pinnedDataRefs.find((entry)=>entry.datasetRefName===pending.datasetRefName);
    const fileKey=item&&findFileByPath(item.path);
    if(!fileKey){showNotice("작업의 기본 데이터 참조를 읽을 수 없습니다. 현재 데이터는 유지됩니다.","bad");return}
    loadCandidate(fileKey,item.sheet,{origin:"datasetPool",datasetRefName:item.datasetRefName,preferredWorkId:pending.workId});
  });
  $("closeDataPicker").addEventListener("click",()=>$("dataPickerDialog").close());
  $("dataPickerDone").addEventListener("click",()=>$("dataPickerDialog").close());
  $("mockFileList").addEventListener("click",(event)=>{
    const button=event.target.closest("[data-file-key]");if(!button)return;
    const relinkName=dataState.pendingRelinkName;
    inspectFile(button.dataset.fileKey,{origin:relinkName?"datasetPool":"direct",datasetRefName:relinkName,relinkName});
  });
  $("pinnedDataList").addEventListener("click",(event)=>{
    const button=event.target.closest("[data-pinned-name]");if(!button)return;
    const item=dataState.pinnedDataRefs.find((entry)=>entry.datasetRefName===button.dataset.pinnedName);
    if(item.status==="missing"){
      dataState.pendingRelinkName=item.datasetRefName;
      $("dataPickerStatus").textContent=`📌 ${item.name}에 연결할 새 파일을 고르세요. 성공적으로 읽은 뒤에만 참조를 갱신합니다.`;
      return;
    }
    const fileKey=findFileByPath(item.path);
    if(!fileKey){$("dataPickerStatus").textContent="연결된 파일을 찾을 수 없습니다.";return}
    loadCandidate(fileKey,item.sheet,{origin:"datasetPool",datasetRefName:item.datasetRefName});
  });
  $("sheetList").addEventListener("click",(event)=>{
    const button=event.target.closest("[data-sheet-name]");if(!button||!dataState.pendingMount)return;
    const pending=clone(dataState.pendingMount);
    loadCandidate(pending.fileKey,button.dataset.sheetName,pending);
  });
  $("cancelSheetPicker").addEventListener("click",()=>{$("sheetPickerDialog").close();dataState.pendingMount=null;openDataPicker($("changeData"))});
  $("dataSwitchGuardDialog").addEventListener("close",()=>{
    const pending=dataState.pendingMount;
    if($("dataSwitchGuardDialog").returnValue==="switch"&&pending)commitPreparedMount(pending);
    else dataState.pendingMount=null;
  });
  $("pinCurrentData").addEventListener("click",(event)=>{
    $("pinDataName").value="";$("pinDataTarget").textContent=targetLabel(currentTarget());$("pinDataError").textContent="";
    openDialog($("pinDataDialog"),event.currentTarget);
  });
  $("pinDataDialog").addEventListener("close",()=>{
    if($("pinDataDialog").returnValue!=="pin")return;
    const name=$("pinDataName").value.trim();
    if(!name||dataState.pinnedDataRefs.some((item)=>item.datasetRefName===name)){
      $("pinDataError").textContent=!name?"이름을 입력하세요.":"같은 이름의 고정 데이터가 있습니다. 조용히 덮어쓰지 않습니다.";
      openDialog($("pinDataDialog"),$("pinCurrentData"));return;
    }
    const target=clone(currentTarget());
    dataState.pinnedDataRefs.push({datasetRefName:name,name,path:target.path,fileName:target.fileName,sheet:target.sheet,headerRow:target.headerRow??null,status:"active",note:null});
    dataState.mountedDataRef={origin:"datasetPool",directTarget:null,datasetRefName:name,mountedAt:new Date().toISOString()};
    saveDataReferences();renderData();toast(`📌 ${name} 참조를 고정했습니다. 레코드는 저장하지 않았습니다.`);
  });
  $("recordSearch").addEventListener("input",(event)=>{runState.recordRange.search=event.target.value;runState.recordRange.shiftAnchorId=null;renderData()});
  $("recordOrder").addEventListener("change",(event)=>{const before=selectionFingerprint();runState.recordRange.viewOrder=event.target.value;runState.recordRange.shiftAnchorId=null;finishRunInputMutation(before)});
  $("recordFilterButton").addEventListener("click",(event)=>openFilterDialog(runState.recordRange,"main",event.currentTarget));
  $("recordRangeButton").addEventListener("click",()=>openRangeEditor());
  $("clearRecordSelection").addEventListener("click",()=>{const before=selectionFingerprint();runState.recordRange.selectedIds.clear();runState.recordRange.shiftAnchorId=null;finishRunInputMutation(before)});
  $("clearHiddenSelection").addEventListener("click",()=>{const before=selectionFingerprint();runState.recordRange.selectedIds.clear();runState.recordRange.shiftAnchorId=null;finishRunInputMutation(before)});
  $("showSelectedRecords").addEventListener("click",()=>openRangeEditor({selectedOnly:true,focusTarget:"showSelectedRecords"}));
  $("hiddenSelectionSamples").addEventListener("click",(event)=>{const button=event.target.closest("[data-remove-hidden]");if(!button)return;const before=selectionFingerprint();runState.recordRange.selectedIds.delete(button.dataset.removeHidden);finishRunInputMutation(before)});
  $("activeFilterChips").addEventListener("click",(event)=>{const button=event.target.closest("[data-remove-filter]");if(!button)return;delete runState.recordRange.columnFilters[button.dataset.removeFilter];runState.recordRange.shiftAnchorId=null;renderData()});
  $("recordBody").addEventListener("click",(event)=>{const input=event.target.closest("[data-record]");if(!input)return;const before=selectionFingerprint();setRecordSelection(runState.recordRange,input.dataset.record,input.checked,event.shiftKey);finishRunInputMutation(before)});
	  $("recordHead").addEventListener("change",(event)=>{
	    if(event.target.id!=="selectAll")return;
	    const before=selectionFingerprint(),visible=visibleOrderedRecords();
	    visible.forEach((record)=>event.target.checked?runState.recordRange.selectedIds.add(recordKey(record)):runState.recordRange.selectedIds.delete(recordKey(record)));
	    runState.recordRange.shiftAnchorId=null;finishRunInputMutation(before);
	  });
  $("filterColumn").addEventListener("change",renderFilterDialogColumn);
  $("recordFilterDialog").addEventListener("close",()=>{
    if(!filterDialogContext)return;
    const context=filterDialogContext;filterDialogContext=null;
    if($("recordFilterDialog").returnValue!=="apply")return;
    try{
      const {column,filter,empty}=collectFilterDialog();
      if(empty)delete context.range.columnFilters[column.key];else context.range.columnFilters[column.key]=filter;
      context.range.shiftAnchorId=null;
      if(context.surface==="editor")finishRunInputMutation("",{editor:true});else renderData();
    }catch(error){
      filterDialogContext=context;$("filterError").textContent=error.message;openDialog($("recordFilterDialog"),context.surface==="editor"?$("rangeEditorFilterButton"):$("recordFilterButton"));
    }
  });
  $("clearColumnFilter").addEventListener("click",()=>{
    if(!filterDialogContext)return;
    const context=filterDialogContext,key=$("filterColumn").value;delete context.range.columnFilters[key];context.range.shiftAnchorId=null;
    filterDialogContext=null;$("recordFilterDialog").close("cleared");
    if(context.surface==="editor")finishRunInputMutation("",{editor:true});else renderData();
  });
  $("recordRangeBack").addEventListener("click",requestRangeEditorExit);
  $("rangeEditorCancel").addEventListener("click",requestRangeEditorExit);
  $("rangeEditorApply").addEventListener("click",applyRangeEditor);
  $("rangeEditorSearch").addEventListener("input",(event)=>{const editor=runState.rangeEditor;if(!editor)return;editor.draft.search=event.target.value;editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true})});
  $("rangeEditorOrder").addEventListener("change",(event)=>{const editor=runState.rangeEditor;if(!editor)return;editor.draft.viewOrder=event.target.value;editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true})});
  $("rangeEditorFilterButton").addEventListener("click",(event)=>{if(runState.rangeEditor)openFilterDialog(runState.rangeEditor.draft,"editor",event.currentTarget)});
  $("rangeEditorSelectedOnly").addEventListener("click",()=>{const editor=runState.rangeEditor;if(!editor)return;editor.draft.selectedOnly=!editor.draft.selectedOnly;editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true})});
  $("rangeEditorClearSelection").addEventListener("click",()=>{const editor=runState.rangeEditor;if(!editor)return;editor.draft.selectedIds.clear();editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true})});
  $("rangeEditorFilterChips").addEventListener("click",(event)=>{const button=event.target.closest("[data-remove-filter]"),editor=runState.rangeEditor;if(!button||!editor)return;delete editor.draft.columnFilters[button.dataset.removeFilter];editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true})});
  $("rangeEditorBody").addEventListener("click",(event)=>{const input=event.target.closest("[data-range-record]"),editor=runState.rangeEditor;if(!input||!editor)return;setRecordSelection(editor.draft,input.dataset.rangeRecord,input.checked,event.shiftKey);finishRunInputMutation("",{editor:true})});
  $("rangeEditorHead").addEventListener("change",(event)=>{
    const editor=runState.rangeEditor;if(event.target.id!=="rangeEditorSelectAll"||!editor)return;
    visibleOrderedRecords(editor.draft).forEach((record)=>event.target.checked?editor.draft.selectedIds.add(recordKey(record)):editor.draft.selectedIds.delete(recordKey(record)));
    editor.draft.shiftAnchorId=null;finishRunInputMutation("",{editor:true});
  });
  $("recordRangeGuardDialog").addEventListener("close",()=>{
    const result=$("recordRangeGuardDialog").returnValue;
    if(result==="apply")applyRangeEditor();
    else if(result==="discard")discardRangeEditor();
    else requestAnimationFrame(()=>$("recordRangeBack").focus());
  });
	  $("workList").addEventListener("click",(event)=>{
	    const favorite=event.target.closest("[data-favorite-work]"),select=event.target.closest("[data-select-work]"),menu=event.target.closest("[data-work-menu]");
	    if(favorite){event.stopPropagation();toggleFavorite(favorite.dataset.favoriteWork);return}
	    if(select){selectDocumentWork(select.dataset.selectWork)}
	    if(menu)openMenu(menu.dataset.workMenu,menu);
	  });
  $("objectMenu").addEventListener("click",(event)=>{const button=event.target.closest("[data-menu-open]");if(!button)return;const context=makeContext({workId:button.dataset.menuWork,section:button.dataset.menuOpen,target:{kind:"none",id:null},entryReason:"voluntary",evidence:{},returnContext:makeReturn("data",{focusTarget:"documentSideCard"})});openWorkEditor(context)});
  document.querySelectorAll("[data-nav]").forEach((button)=>button.addEventListener("click",()=>{if(button.dataset.nav==="library"){renderLibrary();showScreen("library")}else{showScreen("data");renderData()}}));
  $("librarySearch").addEventListener("input",(event)=>{state.librarySearch=event.target.value;renderLibrary()});
  $("libraryGrid").addEventListener("click",(event)=>{const button=event.target.closest("[data-library-open]");if(button)openWorkEditor(makeContext({workId:button.dataset.libraryOpen,section:"template",entryReason:"library",evidence:{},returnContext:libraryReturn(button.dataset.libraryOpen)}))});
  $("libraryNewWork").addEventListener("click",()=>showDeferred("완전한 새 문서 작업 마법사는 후속 범위입니다. 고객 데이터에서 시작하는 최소 생성 흐름만 이 시안에서 조합합니다."));
  $("compatPrimary").addEventListener("click",()=>{
    if(hasPerformanceBonus())openWorkEditor(makeContext({workId:"salary",section:"binding",target:{kind:"field",id:"bonus"},entryReason:"schema_new_field",evidence:{label:"상여금",sourceField:"성과급",sampleValues:"350000, 0, 220000",message:"추천은 저장 전 초안이며 기존 연결은 유지됩니다."},returnContext:makeReturn("data",{focusTarget:"compatNote"}),initialPatch:{section:"binding",changes:{bonus:{source:"performanceBonus",type:"amount",format:"won",provenance:"suggested",intentionallyUnused:false}}}}));
  });
  $("compatSecondary").addEventListener("click",()=>{if(hasPerformanceBonus()){state.dismissedSuggestions.add("performanceBonus:salary");renderData();toast("이번 분석에서만 추천을 숨겼습니다.")}else $("sourceBoundaryDialog").showModal()});
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
    const record=editorSampleRecord();
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
  $("previewPrev").addEventListener("click",()=>{state.preview.index=Math.max(0,state.preview.index-1);renderPreview()});$("previewNext").addEventListener("click",()=>{state.preview.index=Math.min(orderedSelectedRecords().length-1,state.preview.index+1);renderPreview()});
  $("previewContent").addEventListener("click",(event)=>{const button=event.target.closest("[data-preview-edit]"),context=button&&previewContext(button.dataset.previewEdit);if(context)openWorkEditor(context)});
  $("approvePreview").addEventListener("click",()=>{state.preview.approved=true;renderPreview();renderValidation();toast("이 미리보기를 명시적으로 승인했습니다.")});
  $("drawerRun").addEventListener("click",runCurrent);

  $("resultPanel").addEventListener("click",(event)=>{
    const more=event.target.closest("#resultMore");if(more){const menu=$("resultMoreMenu"),open=menu.hidden;menu.hidden=!open;more.setAttribute("aria-expanded",String(open));if(open){state.resultMenuTrigger=more;menu.querySelector("button").focus()}return}
    const resultAction=event.target.closest("[data-result-action]");if(resultAction?.dataset.resultAction==="filename")resultFilenameEditor();
    const runtime=event.target.closest("[data-runtime-action]");if(!runtime)return;
    const recordId=String(runtime.dataset.recordId);
    if(runtime.dataset.runtimeAction==="number"){const record=state.records.find((r)=>recordKey(r)===recordId),base=filenameFor(state.activeWorkId,record).replace(/\.hwpx$/,"");retryOne(recordId,`${base} (1).hwpx`)}
    if(runtime.dataset.runtimeAction==="rename"){const record=state.records.find((r)=>recordKey(r)===recordId),name=window.prompt("이 실패 레코드에만 사용할 파일 이름",filenameFor(state.activeWorkId,record).replace(/\.hwpx$/,""));if(name)retryOne(recordId,`${name.replace(/\.hwpx$/,"")}.hwpx`)}
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
  $("workPrev").addEventListener("click",()=>{state.workIndex=Math.max(0,state.workIndex-1);renderWorkbench()});$("workNext").addEventListener("click",()=>{state.workIndex=Math.min((workbenchState.session?.records.length||1)-1,state.workIndex+1);renderWorkbench()});
  $("copyRecord").addEventListener("click",()=>{const id=recordKey(workRecord()),total=workbenchState.session?.records.length||0;state.copied.add(id);state.review.delete(id);if($("autoAdvance").checked&&state.workIndex<total-1)state.workIndex++;renderWorkbench()});
  document.querySelectorAll("[data-work-mode]").forEach((button)=>button.addEventListener("click",()=>{state.workMode=button.dataset.workMode;renderWorkbench()}));
  $("workbenchBack").addEventListener("click",()=>{showScreen("data");renderData()});

  $("helpButton").addEventListener("click",(event)=>openDialog($("helpDialog"),event.currentTarget));
  $("closeHelp").addEventListener("click",()=>$("helpDialog").close());
  $("helpDone").addEventListener("click",()=>$("helpDialog").close());
  document.addEventListener("click",(event)=>{if(!$("objectMenu").hidden&&!event.target.closest("#objectMenu")&&!event.target.closest("[data-work-menu]"))closeMenu()});
  document.addEventListener("keydown",(event)=>{
    if(event.key!=="Escape")return;
    const openDialog=document.querySelector("dialog[open]");if(openDialog)return;
    if(!$("objectMenu").hidden){event.preventDefault();closeMenu(true);return}
    const resultMenu=$("resultMoreMenu");if(resultMenu&&!resultMenu.hidden){event.preventDefault();resultMenu.hidden=true;state.resultMenuTrigger?.setAttribute("aria-expanded","false");state.resultMenuTrigger?.focus();return}
    if(state.preview.open){event.preventDefault();closePreview();return}
    if(state.view==="record-range"){event.preventDefault();requestRangeEditorExit();return}
    if(state.view==="editor"){event.preventDefault();cancelEditor()}
  });

	  async function initializeDataState() {
	    restoreWorkFavorites();
	    try{
      const storedPool=JSON.parse(localStorage.getItem(DATASET_POOL_KEY)||"null");
      if(Array.isArray(storedPool))dataState.pinnedDataRefs=storedPool;
    }catch(error){showNotice(`고정 데이터 시안 저장값을 읽지 못했습니다: ${error.message}`,"bad")}
    let restored=null;
    try{restored=JSON.parse(localStorage.getItem(MOUNTED_DATA_KEY)||"null")}catch(error){showNotice(`마지막 물림 시안 저장값을 읽지 못했습니다: ${error.message}`,"bad")}
    await restoreMountedData(restored);
  }
	  renderLibrary();renderData();renderTestHarness();initializeDataState();
})();
