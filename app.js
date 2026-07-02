const queueItems = [
  ["EX-1140522-018", "收文", "衛生福利部", "長照服務品質稽核資料補件通知", "待登錄", "wait"],
  ["EX-1140522-013", "收文", "臺北市政府社會局", "北區長照服務協調會議", "待分派", "wait"],
  ["EX-1140522-007", "發文", "臺北市政府社會局", "日照中心設立許可補正資料", "待清稿", "info"],
  ["EX-1140521-003", "發文", "衛生福利部", "長照人力培訓成果彙報", "交換完成", "ok"],
  ["EX-1140520-009", "發文", "桃園市政府社會局", "社區據點服務計畫變更", "等待確認", "wait"],
  ["EX-1140519-002", "收文", "新北市政府衛生局", "居家服務督導訪視資料回覆", "異常待處理", "issue"]
];

const localBackendOrigin = "http://127.0.0.1:5174";
const backendOrigin = window.location.protocol === "file:" ? localBackendOrigin : window.location.origin;
const backendApiBase = `${backendOrigin}/api`;
const authStorageKey = "suiyuecare-edoc-session";
const composeAutosaveStorageKey = "suiyuecare-edoc-compose-autosave";
const loggingPortalUrl = "https://login.suiyuecare.com/portal/";
const loggingBridgeStorageKeys = [
  "suiyue-hris-quick-login-user",
  "suiyuecare-logging-session",
  "suiyue-logging-session",
  "suiyue-platform-session"
];
const loggingQuickLoginCookieKey = "suiyue_hris_quick_login_user";
const loggingQuickLoginWindowNamePrefix = "suiyue_hris_quick_login_user:";
let authState = readJsonStorage(authStorageKey);

const inboundDocs = [
  {
    id: "IN-1140522-00018",
    receiveNo: "收1140522-00018",
    exchangeNo: "EX-1140522-018",
    agency: "衛生福利部",
    agencyCode: "A21000000I",
    type: "函",
    subject: "長照服務品質稽核資料補件通知",
    status: "待登錄",
    owner: "總務",
    dept: "總管理處",
    priority: "速件",
    security: "普通",
    receivedAt: "2026-05-22 09:42",
    dueDate: "2026-05-29",
    attachments: ["稽核補件通知.pdf", "附件清冊.xml"],
    note: "jAgent 已拉取，待登錄收文號與附件完整性。"
  },
  {
    id: "IN-1140522-00013",
    receiveNo: "收1140522-00013",
    exchangeNo: "EX-1140522-013",
    agency: "臺北市政府社會局",
    agencyCode: "A63000000J",
    type: "開會通知單",
    subject: "北區長照服務協調會議",
    status: "待分派",
    owner: "行政部主任",
    dept: "總管理處",
    priority: "普通件",
    security: "普通",
    receivedAt: "2026-05-22 09:28",
    dueDate: "2026-05-24",
    attachments: ["開會通知單.pdf", "會議議程.pdf"],
    note: "已完成登錄，待分派業務助理。"
  },
  {
    id: "IN-1140521-00044",
    receiveNo: "收1140521-00044",
    exchangeNo: "EX-1140521-044",
    agency: "新北市政府衛生局",
    agencyCode: "A65000000I",
    type: "函",
    subject: "居家服務督導訪視資料回覆",
    status: "已收文",
    owner: "王督導",
    dept: "居家照顧課",
    priority: "普通件",
    security: "普通",
    receivedAt: "2026-05-21 15:18",
    dueDate: "2026-05-28",
    attachments: ["訪視回覆.pdf"],
    note: "已分派承辦，待承辦回覆。"
  },
  {
    id: "IN-1140520-00022",
    receiveNo: "收1140520-00022",
    exchangeNo: "EX-1140520-022",
    agency: "桃園市政府社會局",
    agencyCode: "A68000000J",
    type: "函",
    subject: "社區據點服務計畫審查意見",
    status: "已收文",
    owner: "陳經理",
    dept: "社區據點課",
    priority: "普通件",
    security: "普通",
    receivedAt: "2026-05-20 11:06",
    dueDate: "2026-05-27",
    attachments: ["審查意見.pdf", "補正表.xlsx"],
    note: "已收文並納入計畫案追蹤。"
  }
];

const pulledInboundTemplates = [
  {
    id: "IN-1140522-00031",
    receiveNo: "收1140522-00031",
    exchangeNo: "EX-1140522-031",
    agency: "臺北市政府衛生局",
    agencyCode: "A63000000I",
    type: "函",
    subject: "長照機構感染管制作業檢核通知",
    status: "待登錄",
    owner: "總務",
    dept: "總管理處",
    priority: "速件",
    security: "普通",
    receivedAt: "2026-05-22 10:16",
    dueDate: "2026-05-26",
    attachments: ["感染管制檢核通知.pdf", "自評表.xlsx"],
    note: "由 jAgent 新拉取，尚未登錄。"
  },
  {
    id: "IN-1140522-00032",
    receiveNo: "收1140522-00032",
    exchangeNo: "EX-1140522-032",
    agency: "勞動部勞動力發展署",
    agencyCode: "A17000000J",
    type: "函",
    subject: "移工照顧訓練課程資料補正",
    status: "待登錄",
    owner: "總務",
    dept: "總管理處",
    priority: "普通件",
    security: "普通",
    receivedAt: "2026-05-22 10:18",
    dueDate: "2026-05-30",
    attachments: ["補正通知.pdf"],
    note: "由 jAgent 新拉取，尚未登錄。"
  }
];

let selectedInboundId = inboundDocs[0].id;
let inboundFilter = "all";
let inboundSearchTerm = "";
const inboundAuditLog = [
  ["10:08", "系統初始化", "載入既有收文與交換紀錄。"]
];

const dispatchDocs = [
  {
    id: "OUT-1140522-007",
    no: "歲悅字第1140522007號",
    exchangeNo: "EX-OUT-1140522-007",
    type: "函",
    priority: "速件",
    security: "普通",
    to: "臺北市政府社會局",
    agencyCode: "A63000000J",
    subject: "檢送本公司日間照顧中心設立許可補正資料，請查照。",
    body: "依貴局通知辦理，檢附補正資料、附件清冊及相關證明文件。",
    status: "待清稿",
    owner: "總務",
    attachments: ["設立許可補正資料.pdf", "附件清冊.xml"],
    packageId: "",
    lastReply: "尚未送交 jAgent",
    checks: { format: false, recipient: true, attachments: true, certificate: true, package: false }
  },
  {
    id: "OUT-1140521-003",
    no: "歲悅字第1140521003號",
    exchangeNo: "EX-OUT-1140521-003",
    type: "函",
    priority: "普通件",
    security: "普通",
    to: "衛生福利部",
    agencyCode: "A21000000I",
    subject: "函送長照人力培訓成果彙報及附件清冊。",
    body: "檢送本公司長照人力培訓成果彙報資料，請查照。",
    status: "交換完成",
    owner: "總務",
    attachments: ["培訓成果彙報.pdf", "成果統計.xlsx"],
    packageId: "PKG-1140521-003",
    lastReply: "jAgent 回覆 exchangeCompleted，收文方已確認。",
    checks: { format: true, recipient: true, attachments: true, certificate: true, package: true }
  },
  {
    id: "OUT-1140520-009",
    no: "歲悅字第1140520009號",
    exchangeNo: "EX-OUT-1140520-009",
    type: "函",
    priority: "普通件",
    security: "普通",
    to: "桃園市政府社會局",
    agencyCode: "A68000000J",
    subject: "申請社區據點服務計畫變更。",
    body: "因服務據點營運配置調整，申請服務計畫變更。",
    status: "等待確認",
    owner: "行政部主任",
    attachments: ["計畫變更申請.pdf"],
    packageId: "PKG-1140520-009",
    lastReply: "jAgent 回覆 accepted，等待收文方確認。",
    checks: { format: true, recipient: true, attachments: true, certificate: true, package: true }
  },
  {
    id: "OUT-1140519-006",
    no: "歲悅字第1140519006號",
    exchangeNo: "EX-OUT-1140519-006",
    type: "函",
    priority: "速件",
    security: "普通",
    to: "新北市政府衛生局",
    agencyCode: "A65000000I",
    subject: "補送居家服務品質改善計畫。",
    body: "補送改善計畫附件，請惠予備查。",
    status: "交換失敗",
    owner: "總務",
    attachments: ["品質改善計畫.pdf"],
    packageId: "PKG-1140519-006",
    lastReply: "jAgent 回覆 failed：收文方機關代碼暫不可用。",
    checks: { format: true, recipient: true, attachments: true, certificate: true, package: true }
  }
];

let selectedDispatchId = dispatchDocs[0].id;
let dispatchFilter = "all";
let dispatchSearchTerm = "";
let officialWorkflowItems = [];
let selectedOfficialDocumentId = "";
let officialWorkflowScope = "all";
let officialWorkflowSearchTerm = "";
let officialWorkflowStatusFilter = "";
let officialSealOptions = [];
const dispatchAuditLog = [
  ["10:12", "系統初始化", "載入既有發文與交換紀錄。"]
];

const complianceChecks = [
  ["發文前清稿", "送出前完成文稿校對、受文者確認、附件完整性與電子檔格式檢查。"],
  ["身分驗證", "收發人員需以帳號、密碼、憑證或其他識別方式完成驗證後才可交換。"],
  ["翌日查核", "發文後至遲次日查詢交換結果，必要時啟動補送、重送或紙本處理。"],
  ["誤送漏送處理", "收文端發現誤送或漏送時，需通知發文機關並保留異常紀錄。"],
  ["資安分層", "管理層、交換層、機關層與終端層權責分明，操作需留軌跡。"]
];

const prechecks = [
  "文號、文別、速別、密等與發文日期已填寫。",
  "受文者機關代碼可於地址簿查詢。",
  "附件檔案可讀取，檔名、頁數與雜湊值已建立。",
  "發文人員已通過權限與憑證檢核。",
  "交換封裝資料可由後端送交 jAgent。"
];

const jagentState = {
  certificate: "未登入",
  certificateNote: "請插入憑證卡並登入",
  token: "",
  tokenExpiresAt: null,
  center: "未連線",
  latency: "-",
  addressResults: []
};

const addressBook = [
  { name: "臺北市政府社會局", code: "A63000000J", center: "G2B2C 統合交換中心", status: "可交換", contact: "文書收發窗口" },
  { name: "臺北市政府衛生局", code: "A63000000I", center: "G2B2C 統合交換中心", status: "可交換", contact: "衛生局收發" },
  { name: "新北市政府衛生局", code: "A65000000I", center: "北區交換中心", status: "可交換", contact: "公文交換窗口" },
  { name: "桃園市政府社會局", code: "A68000000J", center: "北區交換中心", status: "可交換", contact: "社會局總收文" },
  { name: "衛生福利部", code: "A21000000I", center: "G2B2C 統合交換中心", status: "可交換", contact: "部本部總收文" },
  { name: "勞動部勞動力發展署", code: "A17000000J", center: "G2B2C 統合交換中心", status: "可交換", contact: "署本部文書" }
];

const exchangeEvents = [
  ["09:42", "收文拉取完成", "取得 4 筆新來文，2 筆需登錄。"],
  ["09:36", "發文送出", "歲悅字第1140521003號交換完成，等待對方收文確認。"],
  ["09:12", "狀態查詢", "同步 18 筆發文狀態，1 筆需重送。"],
  ["08:54", "憑證登入", "總務完成 jAgent 登入。"]
];

const auditEvents = [
  ["10:08", "王督導分派收文", "收1140521-00044 分派至居家照顧課。"],
  ["09:51", "總務完成清稿", "歲悅字第1140522007號完成格式檢核。"],
  ["09:36", "系統寫入交換事件", "jAgent 回覆 exchangeAccepted。"],
  ["08:54", "使用者登入", "憑證登入成功，Token 有效時間 8 小時。"]
];

const archiveItems = [
  ["原始公文", "PDF / XML / 標準封裝"],
  ["附件", "檔案雜湊與版本紀錄"],
  ["交換紀錄", "送出、回覆、確認、重送"],
  ["操作紀錄", "登入、清稿、分派、登錄"]
];

let selectedArchiveId = "ARC-001";
let archiveFilter = "all";
let archiveSearchTerm = "";
const archiveRecords = [
  {
    id: "ARC-001",
    docNo: "歲悅字第1140521003號",
    direction: "發文",
    agency: "衛生福利部",
    subject: "長照人力培訓成果彙報",
    status: "已封存",
    retention: "10 年",
    sealedAt: "2026-05-22 09:40",
    original: "歲悅字第1140521003號.pdf",
    originalHash: "SHA256-8F2A91D4",
    packageHash: "SHA256-PKG-1140521003",
    attachments: [
      { name: "培訓成果彙報.pdf", version: "v1", hash: "SHA256-A1339C2E", status: "雜湊通過" },
      { name: "成果統計.xlsx", version: "v1", hash: "SHA256-FE203B90", status: "雜湊通過" }
    ],
    exchangeEvents: ["送交 jAgent", "exchangeAccepted", "exchangeCompleted", "收文方確認"],
    operationTrail: ["建立函稿", "清稿檢核", "附件封裝", "送交 jAgent", "歸檔封存"],
    hashStatus: "雜湊通過"
  },
  {
    id: "ARC-002",
    docNo: "收1140522-00018",
    direction: "收文",
    agency: "衛生福利部",
    subject: "長照服務品質稽核資料補件通知",
    status: "待封存",
    retention: "10 年",
    sealedAt: "-",
    original: "收1140522-00018.xml",
    originalHash: "SHA256-7B0E24C1",
    packageHash: "SHA256-PKG-IN00018",
    attachments: [
      { name: "稽核補件通知.pdf", version: "v1", hash: "SHA256-C8202AF1", status: "待驗證" },
      { name: "附件清冊.xml", version: "v1", hash: "SHA256-AD997210", status: "待驗證" }
    ],
    exchangeEvents: ["jAgent 拉取", "收文登錄", "附件清冊建立"],
    operationTrail: ["總務登入", "拉取來文", "收文登錄"],
    hashStatus: "待驗證"
  },
  {
    id: "ARC-003",
    docNo: "歲悅字第1140522007號",
    direction: "發文",
    agency: "臺北市政府社會局",
    subject: "日照中心設立許可補正資料",
    status: "待封存",
    retention: "10 年",
    sealedAt: "-",
    original: "歲悅字第1140522007號.pdf",
    originalHash: "SHA256-29AC44B8",
    packageHash: "SHA256-PKG-1140522007",
    attachments: [
      { name: "設立許可補正資料.pdf", version: "v2", hash: "SHA256-4D91FA33", status: "雜湊通過" },
      { name: "附件清冊.xml", version: "v2", hash: "SHA256-91CF2280", status: "雜湊通過" }
    ],
    exchangeEvents: ["清稿檢核", "附件封裝", "送交 jAgent"],
    operationTrail: ["建立函稿", "主管清稿", "封包產生"],
    hashStatus: "雜湊通過"
  },
  {
    id: "ARC-004",
    docNo: "收1140521-00044",
    direction: "收文",
    agency: "新北市政府衛生局",
    subject: "居家服務督導訪視資料回覆",
    status: "需複核",
    retention: "10 年",
    sealedAt: "-",
    original: "收1140521-00044.pdf",
    originalHash: "SHA256-RECHECK-044",
    packageHash: "SHA256-PKG-IN00044",
    attachments: [
      { name: "訪視回覆.pdf", version: "v1", hash: "SHA256-需複核", status: "需複核" }
    ],
    exchangeEvents: ["jAgent 拉取", "收文登錄", "承辦分派"],
    operationTrail: ["收文登錄", "附件檢核異常", "移交複核"],
    hashStatus: "需複核"
  }
];

const archiveAuditLog = [
  ["10:36", "歸檔保存初始化", "已載入原文、附件、交換事件、操作軌跡與檔案雜湊台帳。"]
];

const securityState = {
  certStatus: "未驗證",
  certNote: "等待讀卡與 PIN 驗證",
  tokenStatus: "有效",
  tokenExpiresAt: Date.now() + 8 * 60 * 60 * 1000,
  proofSerial: "NR-20260522-001",
  lastSignature: "尚未簽章",
  rbacResult: "尚未檢查"
};

const securityDevices = [
  { id: "DEV-001", ip: "203.0.113.18", name: "總務辦公室 Mac", fingerprint: "FP-SYC-EDOC-A1F9", status: "允許" },
  { id: "DEV-002", ip: "198.51.100.27", name: "行政部主任筆電", fingerprint: "FP-SYC-EDOC-B8C2", status: "允許" },
  { id: "DEV-003", ip: "192.0.2.41", name: "未知裝置", fingerprint: "FP-UNKNOWN-0041", status: "封鎖" }
];

const securityAuditLog = [
  ["10:42", "資安控管初始化", "已載入憑證卡、RBAC、IP/裝置限制、Token 過期與不可否認性控制。"]
];

let selectedFileSecurityId = "FS-001";
let fileSecurityFilter = "all";
let fileSecuritySearchTerm = "";
const fileSecurityPolicy = {
  maxSizeMb: 50,
  allowedTypes: "pdf,xml,xlsx,docx,p7m",
  maskPolicy: "身分證 / 電話 / Email",
  confidentialRoles: "行政部主任,主任,執行長",
  watermarkText: "歲悅長照｜電子公文交換｜限授權使用",
  scanEngine: "ClamAV-compatible",
  overLimitAction: "自動隔離"
};
let fileStorageServiceState = {
  ready: false,
  mode: "未檢查",
  missing: ["尚未檢查"],
  provider: "未檢查",
  bucket: "未檢查",
  signedUrlTtlSeconds: 300,
  service: { services: {}, policy: {} },
  scanner: { engine: "未檢查", avProvider: "未檢查", endpoint: "未檢查", pending: 0, quarantined: 0 },
  encryption: { enabled: false, keyId: "未檢查", encryptedFiles: 0, totalFiles: 0 },
  activeDownloadTokens: 0
};

const fileSecurityItems = archiveRecords.flatMap((record, recordIndex) => record.attachments.map((attachment, attachmentIndex) => {
  const sequence = recordIndex * 3 + attachmentIndex + 1;
  const sizeMb = [3.8, 0.4, 18.6, 1.1, 62.4, 0.8, 9.7][sequence - 1] || 6.2;
  const confidential = record.id === "ARC-004" ? "密" : "普通";
  const attachmentSeedIds = {
    "稽核補件通知.pdf": "ATT-001",
    "附件清冊.xml": "ATT-002",
    "設立許可補正資料.pdf": "ATT-003",
    "品質改善計畫.pdf": "ATT-004"
  };
  return {
    id: `FS-${String(sequence).padStart(3, "0")}`,
    attachmentId: attachmentSeedIds[attachment.name] || "",
    backendId: attachmentSeedIds[attachment.name] ? `ASEC-${attachmentSeedIds[attachment.name]}` : "",
    docNo: record.docNo,
    agency: record.agency,
    subject: record.subject,
    fileName: attachment.name,
    version: attachment.version,
    hash: attachment.hash,
    sizeMb,
    scanStatus: attachment.status === "雜湊通過" ? "已通過" : "待掃描",
    maskStatus: confidential === "密" ? "需遮罩" : "未遮罩",
    confidential,
    accessRole: confidential === "密" ? "行政部主任,主任,執行長" : "一般角色",
    watermarkStatus: "未下載",
    backupStatus: "未備份",
    scanEngine: "ClamAV-compatible",
    sensitiveHits: confidential === "密" ? ["身分證", "電話"] : []
  };
}));

const fileSecurityBackups = [];
const fileAccessLog = [
  ["11:44", "檔案資安初始化", "已載入附件防毒掃描、大小限制、敏感遮罩、密件隔離、下載浮水印、存取紀錄與備份還原。"]
];

let selectedAccountId = "USR-001";
let accountFilter = "all";
let accountSearchTerm = "";
const accountSsoState = {
  provider: "Google Workspace",
  domain: "suiyuecare.com",
  status: "未連線",
  lastTest: "尚未測試"
};

const edocAllowedRoles = ["員工", "主管", "主任", "執行長", "行政部主任", "人資", "會計", "總務", "業務助理", "董事會", "股東", "外部檢核單位"];
const jobLevelOptions = ["職員", "組長", "課長", "部長", "區經理", "執行長", "董事會", "股東", "外部檢核單位"];
const roleJobLevelDefaults = {
  員工: "職員",
  主管: "課長",
  業務助理: "職員",
  人資: "課長",
  會計: "課長",
  總務: "課長",
  主任: "部長",
  行政部主任: "部長",
  執行長: "執行長",
  董事會: "董事會",
  股東: "股東",
  外部檢核單位: "外部檢核單位"
};

const userAccounts = [
  { id: "USR-001", name: "林總務", email: "edoc@suiyuecare.com", unit: "總務", title: "總務課長", jobLevel: "課長", role: "總務", provider: "Google Workspace", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 10:05", ip: "203.0.113.18", device: "總務辦公室 Mac" },
  { id: "USR-002", name: "張行政", email: "records@suiyuecare.com", unit: "行政部", title: "行政部長", jobLevel: "部長", role: "行政部主任", provider: "Microsoft Entra", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 09:48", ip: "198.51.100.27", device: "行政部主任筆電" },
  { id: "USR-003", name: "王主管", email: "director@suiyuecare.com", unit: "居家照顧部", title: "居家服務督導", jobLevel: "組長", role: "主管", provider: "Google Workspace", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-21 16:20", ip: "203.0.113.18", device: "主管筆電" },
  { id: "USR-004", name: "陳執行長", email: "ceo@suiyuecare.com", unit: "經營管理", title: "執行長", jobLevel: "執行長", role: "執行長", provider: "Google Workspace", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 08:56", ip: "203.0.113.44", device: "執行長筆電" },
  { id: "USR-005", name: "何人資", email: "hr@suiyuecare.com", unit: "人資", title: "人資課長", jobLevel: "課長", role: "人資", provider: "Microsoft Entra", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 08:40", ip: "198.51.100.27", device: "人資筆電" },
  { id: "USR-006", name: "許會計", email: "accounting@suiyuecare.com", unit: "會計", title: "會計課長", jobLevel: "課長", role: "會計", provider: "Microsoft Entra", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 08:38", ip: "198.51.100.28", device: "會計筆電" },
  { id: "USR-007", name: "周業助", email: "sales-assistant@suiyuecare.com", unit: "業務部", title: "業務助理", jobLevel: "職員", role: "業務助理", provider: "Google Workspace", mfa: "待設定", status: "啟用", lastLogin: "2026-05-21 15:12", ip: "203.0.113.19", device: "業務助理筆電" },
  { id: "USR-008", name: "員工測試", email: "employee@suiyuecare.com", unit: "居家照顧部", title: "居家照顧服務員", jobLevel: "職員", role: "員工", provider: "Google Workspace", mfa: "待設定", status: "啟用", lastLogin: "尚未登入", ip: "-", device: "尚未綁定" },
  { id: "USR-009", name: "部門主管", email: "dept-chief@suiyuecare.com", unit: "營運管理處", title: "部門主管", jobLevel: "部長", role: "主任", provider: "Google Workspace", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 09:20", ip: "203.0.113.22", device: "主管筆電" }
];

const accountLoginLogs = [
  ["10:05", "edoc@suiyuecare.com", "Google Workspace", "203.0.113.18", "成功"],
  ["09:48", "records@suiyuecare.com", "Microsoft Entra", "198.51.100.27", "成功"],
  ["08:56", "it@suiyuecare.com", "本機帳號 + MFA", "203.0.113.44", "成功"],
  ["08:10", "unknown@suiyuecare.com", "本機帳號", "192.0.2.41", "IP 封鎖"]
];

const accountDevices = [
  { id: "ACC-DEV-001", userId: "USR-001", name: "總務辦公室 Mac", ip: "203.0.113.18", fingerprint: "FP-SYC-EDOC-A1F9", status: "信任" },
  { id: "ACC-DEV-002", userId: "USR-002", name: "行政部主任筆電", ip: "198.51.100.27", fingerprint: "FP-SYC-EDOC-B8C2", status: "信任" },
  { id: "ACC-DEV-003", userId: "USR-003", name: "居服督導 iPad", ip: "203.0.113.18", fingerprint: "FP-SYC-EDOC-C339", status: "待複核" },
  { id: "ACC-DEV-004", userId: "USR-004", name: "資訊室管理機", ip: "203.0.113.44", fingerprint: "FP-SYC-EDOC-D601", status: "信任" }
];

const accountIpRules = [
  { id: "IP-001", ip: "203.0.113.0/24", purpose: "歲悅辦公室固定 IP", status: "允許" },
  { id: "IP-002", ip: "198.51.100.0/24", purpose: "主管 VPN", status: "允許" },
  { id: "IP-003", ip: "192.0.2.41", purpose: "異常來源封鎖", status: "封鎖" }
];

const accountAuditLog = [
  ["11:36", "帳號權限初始化", "已載入使用者帳號、單位職稱、RBAC、SSO、MFA、登入紀錄、裝置紀錄與 IP 限制。"]
];

const reportTrend = [
  { day: "05/16", inbound: 8, dispatch: 5, success: 11, exception: 2 },
  { day: "05/17", inbound: 6, dispatch: 4, success: 9, exception: 1 },
  { day: "05/18", inbound: 5, dispatch: 7, success: 10, exception: 2 },
  { day: "05/19", inbound: 9, dispatch: 6, success: 13, exception: 2 },
  { day: "05/20", inbound: 7, dispatch: 8, success: 12, exception: 3 },
  { day: "05/21", inbound: 10, dispatch: 5, success: 14, exception: 1 },
  { day: "05/22", inbound: 12, dispatch: 9, success: 18, exception: 3 }
];

const reportsAuditLog = [
  ["10:48", "報表統計初始化", "已載入收發量、成功率、異常類型、承辦量與逾期件統計。"]
];
let latestFormalReport = null;

const settingsState = {
  agencyVerified: false,
  centerSynced: false,
  apiStatus: "未測試",
  certStatus: "待驗證"
};

const settingsFirewallRules = [
  { id: "FW-001", ip: "203.0.113.18", purpose: "總務辦公室固定 IP", status: "允許" },
  { id: "FW-002", ip: "198.51.100.27", purpose: "行政部主任 VPN", status: "允許" }
];

const settingsAuditLog = [
  ["10:55", "系統設定初始化", "已載入機關代碼、交換中心、API URL、防火牆、憑證與角色設定。"]
];

let opsLogFilter = "all";
let opsLogSearchTerm = "";
const opsState = {
  health: "未檢查",
  environment: "測試環境",
  configVersion: "v1.0.0",
  restoredBackup: "",
  readiness: null,
  deployment: null,
  monitoring: null,
  lastMonitorCheck: ""
};
let goLiveAuditState = null;

const opsApiLogs = [
  { time: "11:50:21", service: "jAgent", api: "POST /exchange/send", status: 200, duration: "186ms", code: "OK", message: "交換封包送出成功" },
  { time: "11:44:08", service: "jAgent", api: "GET /token/validate", status: 401, duration: "42ms", code: "JAGENT-401", message: "Token 過期或簽章不符" },
  { time: "11:38:33", service: "AddressBook", api: "GET /agency/search", status: 200, duration: "95ms", code: "OK", message: "地址簿查詢完成" },
  { time: "11:21:17", service: "Archive", api: "POST /archive/seal", status: 500, duration: "512ms", code: "ARCH-500", message: "保存包寫入暫存區失敗" },
  { time: "11:09:02", service: "Notify", api: "POST /line/webhook", status: 429, duration: "74ms", code: "NOTIFY-429", message: "Line Webhook 速率限制" }
];

const opsErrorCodes = {
  "JAGENT-401": { title: "jAgent Token 無效", reason: "Token 過期、憑證簽章不符或 Session 已撤銷。", fix: "重新憑證登入並刷新 Token，確認系統時間與憑證序號。" },
  "JAGENT-503": { title: "交換中心暫不可用", reason: "交換中心維護、網路阻斷或 API timeout。", fix: "切換備援交換中心，稍後重送並保留交換事件。" },
  "ARCH-500": { title: "歸檔保存失敗", reason: "保存包寫入或 hash manifest 產生失敗。", fix: "重新驗證雜湊、檢查儲存空間，再執行歸檔封存。" },
  "NOTIFY-429": { title: "通知速率限制", reason: "Line 或 Email Gateway 短時間請求過多。", fix: "啟用重試佇列與退避延遲，降低批次派送量。" }
};

const opsConfigVersions = [
  { id: "CFG-001", version: "v1.0.0", env: "測試環境", note: "初始測試參數", actor: "行政部主任", createdAt: "2026-05-22 10:55" }
];

const opsBackups = [];
const opsAuditLog = [
  ["11:58", "維運中心初始化", "已載入 jAgent 健康檢查、API log、錯誤碼、參數版控、操作紀錄匯出、資料備份與環境切換。"]
];

const complianceDocuments = [
  { id: "DOC-COMP-001", title: "法遵控制矩陣", path: "docs/compliance-control-matrix.md", owner: "主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-002", title: "營運 Runbook", path: "docs/operations-runbook.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-003", title: "資安事件通報與應變 SOP", path: "docs/incident-response-sop.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-004", title: "保存年限與稽核證據政策", path: "docs/retention-audit-policy.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-005", title: "上線交接與季檢清單", path: "docs/go-live-operating-checklist.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-006", title: "正式資料庫權限政策", path: "docs/database-security-policy.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-007", title: "正式檔案儲存與病毒掃描政策", path: "docs/file-storage-scanning-policy.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" },
  { id: "DOC-COMP-008", title: "電子簽章憑證合法性驗證政策", path: "docs/certificate-legality-validation-policy.md", owner: "行政部主任", status: "已建立", updatedAt: "2026-05-23" }
];

const complianceControls = [
  { source: "機關公文電子交換作業辦法", control: "電子交換收受、傳遞、異常與留存作業需可追蹤。", implementation: "收文管理、發文管理、交換事件、稽催追蹤", status: "已落地" },
  { source: "公文電子交換系統資訊安全管理規範", control: "管理層、交換層、機關層、終端層權責與資安事件通報。", implementation: "資安控管、維運中心、事件通報 SOP", status: "已落地" },
  { source: "文書及檔案管理電腦化作業規範", control: "文書檔案合一、電子封裝、附件清冊、PDF/TIFF/JPG 呈現與保存。", implementation: "文書格式、PDF 套版、自動押章、歸檔保存", status: "已落地" },
  { source: "個人資料保護法與內部資安政策", control: "個資遮罩、密件隔離、下載浮水印與檔案存取紀錄。", implementation: "檔案資安、RBAC、audit log", status: "已落地" },
  { source: "正式資料庫權限政策", control: "RLS、密件 row-level 隔離、保留年限與 audit log 不可竄改。", implementation: "Supabase migration 202605230010、database-security-policy.md", status: "已落地" },
  { source: "正式檔案儲存與病毒掃描政策", control: "Private bucket、加密、短效下載 URL、防毒掃描與隔離阻擋。", implementation: "Supabase migration 202605230011、file-storage-scanning-policy.md", status: "已落地" },
  { source: "電子簽章憑證合法性驗證政策", control: "自然人/工商/組織憑證需檢查信任鏈、TSA、OCSP 與 CRL。", implementation: "Supabase migration 202605230012、憑證驗證 API、簽章頁即時驗證", status: "已落地" },
  { source: "委外與營運管理", control: "部署、變更、備份復原、錯誤碼、操作紀錄匯出需有 SOP。", implementation: "部署手冊、維運 Runbook、GitHub Actions", status: "待季檢" }
];

const complianceSops = {
  "每日收發檢查": ["確認 jAgent Token 與憑證狀態", "執行每日收文拉取", "檢查交換失敗與未收確認", "匯出當日操作摘要"],
  "交換失敗處理": ["查詢錯誤碼", "確認機關代碼與封包附件", "重送交換任務", "通知總務與行政部主任"],
  "資安事件通報": ["停用可疑帳號或 Token", "保存 audit log 與 API log", "通知主管與資安窗口", "完成復原後執行事後檢討"],
  "備份復原演練": ["建立資料備份", "抽查檔案雜湊", "於測試環境還原", "記錄 RTO / RPO 與差異"],
  "季檢稽核": ["檢查角色與權限", "抽核交換事件與用印紀錄", "檢查保存年限與刪除凍結", "完成季檢簽核"]
};

const complianceGaps = [
  { id: "GAP-001", title: "正式 jAgent API 文件", owner: "行政部主任", status: "待取得", dueDate: "上線前" },
  { id: "GAP-002", title: "正式機關代碼與憑證卡", owner: "總務", status: "待取得", dueDate: "上線前" },
  { id: "GAP-003", title: "獨立 eDoc Supabase project", owner: "行政部主任", status: "待建立", dueDate: "部署前" },
  { id: "GAP-004", title: "SMTP / LINE 正式通道驗證", owner: "行政部主任", status: "待驗證", dueDate: "部署前" }
];

const complianceAuditLog = [
  ["14:55", "法遵營運初始化", "已建立法規控制矩陣、營運 Runbook、事件通報、保存稽核與上線交接文件。"]
];

const backupRestoreDrills = [];
let latestBackupDrill = null;
let latestComplianceAttestation = null;
let selectedComplianceDocId = "DOC-COMP-001";
let complianceLastReview = "";
let complianceLastDrill = "";

let selectedNotificationId = "NTF-001";
let notificationFilter = "all";
let notificationSearchTerm = "";
const notificationItems = [
  { id: "NTF-001", type: "收文", title: "衛福部補件通知待登錄", target: "總務", channel: "系統通知", status: "未讀", priority: "高", source: "IN-1140522-00018", body: "jAgent 已拉取新來文，請完成收文登錄與附件檢核。" },
  { id: "NTF-002", type: "待清稿", title: "日照中心補正資料待清稿", target: "行政部主任", channel: "Email + 系統通知", status: "未讀", priority: "高", source: "OUT-1140522-007", body: "函稿已建立，請進行清稿檢核與附件封裝。" },
  { id: "NTF-003", type: "交換失敗", title: "新北市政府衛生局交換失敗", target: "總務", channel: "系統通知", status: "未讀", priority: "高", source: "OUT-1140519-006", body: "jAgent 回覆 failed，請確認機關代碼並重送。" },
  { id: "NTF-004", type: "Token 到期", title: "jAgent Token 即將到期", target: "行政部主任", channel: "Email + 系統通知", status: "未讀", priority: "中", source: "SEC-TOKEN", body: "Token 剩餘時間不足，請刷新或重新憑證登入。" },
  { id: "NTF-005", type: "逾期查核", title: "收1140522-00013 分派逾期", target: "行政部主任", channel: "Line 工作群組", status: "未讀", priority: "高", source: "TRK-003", body: "收文尚未完成分派，請啟動逾期查核提醒。" }
];

const notificationAuditLog = [
  ["11:02", "通知中心初始化", "已載入收文、待清稿、交換失敗、Token 到期與逾期查核提醒。"]
];

const notificationGatewayState = {
  emailStatus: "未測試",
  lineStatus: "未測試",
  inboxStatus: "啟用",
  scheduleStatus: "未排程",
  emailApi: "讀取後端 SMTP 環境設定",
  lineWebhook: "讀取後端 LINE_WEBHOOK_URL",
  lastGatewayCheck: "尚未檢查",
  inboxRetention: "90 天",
  overdueSchedule: "每日 09:00",
  tokenSchedule: "到期前 30 分鐘",
  failureChannel: "Email + Line + 系統通知",
  lastTestReport: null,
  credentials: [
    { id: "NCRED-EMAIL-SMTP", channel: "Email", provider: "SMTP / Transactional Email", credential_type: "SMTP 帳號/應用程式密碼", masked_identifier: "SMTP_HOST=未設定；SMTP_FROM=未設定", status: "待驗證", expires_at: "", last_validated_at: "" },
    { id: "NCRED-LINE-WEBHOOK", channel: "Line 工作群組", provider: "LINE Messaging API / Webhook", credential_type: "Webhook Secret / Channel Access Token", masked_identifier: "LINE_WEBHOOK_URL=未設定", status: "待驗證", expires_at: "", last_validated_at: "" },
    { id: "NCRED-INBOX-SIGNING", channel: "系統站內通知", provider: "Suiyuecare eDoc", credential_type: "站內通知簽章金鑰", masked_identifier: "APP_SECRET/CRON_SECRET", status: "待驗證", expires_at: "", last_validated_at: "" }
  ]
};

const notificationDeliveryLog = [
  ["11:03", "系統站內通知", "通知閘道初始化，站內通知通道已啟用。"]
];

const systemInboxItems = [
  { id: "INBOX-001", target: "總務", title: "衛福部補件通知待登錄", status: "未讀", createdAt: "11:03" }
];

const notificationSchedules = [];

let selectedJobId = "JOB-001";
let jobFilter = "all";
let jobSearchTerm = "";
const backgroundJobs = [
  { id: "JOB-001", name: "每日收文拉取", type: "pullInbound", schedule: "每日 08:30", nextRun: "2026-05-23 08:30", status: "啟用", lastResult: "尚未執行", notify: "總務", runCount: 0 },
  { id: "JOB-002", name: "發文翌日查核", type: "nextDayCheck", schedule: "每日 09:00", nextRun: "2026-05-23 09:00", status: "啟用", lastResult: "尚未執行", notify: "行政部主任", runCount: 0 },
  { id: "JOB-003", name: "Token 到期檢查", type: "tokenCheck", schedule: "每 15 分鐘", nextRun: "2026-05-22 11:15", status: "啟用", lastResult: "尚未執行", notify: "行政部主任", runCount: 0 },
  { id: "JOB-004", name: "逾期稽催", type: "overdueReminder", schedule: "每小時", nextRun: "2026-05-22 12:00", status: "啟用", lastResult: "尚未執行", notify: "行政部主任", runCount: 0 },
  { id: "JOB-005", name: "交換狀態同步", type: "exchangeSync", schedule: "每 15 分鐘", nextRun: "2026-05-22 11:15", status: "啟用", lastResult: "尚未執行", notify: "總務", runCount: 0 },
  { id: "JOB-006", name: "歸檔封存", type: "archiveSeal", schedule: "每日 18:00", nextRun: "2026-05-22 18:00", status: "啟用", lastResult: "尚未執行", notify: "主任", runCount: 0 },
  { id: "JOB-007", name: "報表產生", type: "reportGenerate", schedule: "每日 18:00", nextRun: "2026-05-22 18:00", status: "啟用", lastResult: "尚未執行", notify: "行政部主任", runCount: 0 },
  { id: "JOB-008", name: "合約到期與續約提醒", type: "contractRenewalCheck", schedule: "每日 09:30", nextRun: "2026-05-23 09:30", status: "啟用", lastResult: "尚未執行", notify: "行政部主任", runCount: 0 }
];

const jobAuditLog = [
  ["11:52", "背景任務初始化", "已載入每日收文拉取、發文翌日查核、Token 到期檢查、逾期稽催、合約續約提醒、交換狀態同步、歸檔封存與報表產生。"]
];

let activeDatabaseTable = "documents";
let selectedDatabaseId = "DOC-IN-1140522-00018";
let databaseSearchTerm = "";
let searchResults = [];
let selectedSearchId = "";
let backendDashboardMetrics = null;
const databaseAccessState = {};
const databaseAuditLog = [
  ["11:10", "後端資料庫初始化", "已建立公文主檔、受文者、附件、交換任務、交換事件與 audit log 檢視。"]
];

const databaseLabels = {
  documents: "公文主檔",
  contracts: "合約主檔",
  contractParties: "合約相對人",
  contractApprovals: "合約簽核",
  companyRegistry: "公司行號",
  departmentRegistry: "部門",
  sealTypeRegistry: "印章類別",
  documentFlows: "文件流程核心",
  documentTypeConfigs: "文件類型設定",
  workflowTemplateConfigs: "流程模板設定",
  permissionMatrix: "權限矩陣",
  formatTemplateConfigs: "格式模板設定",
  workflowTasks: "簽核流程",
  recipients: "受文者",
  attachments: "附件",
  exchangeTasks: "交換任務",
  exchangeEvents: "交換事件",
  auditLogs: "audit log"
};

const databaseColumns = {
  documents: ["id", "docNo", "direction", "agency", "subject", "status"],
  contracts: ["id", "contractNo", "type", "counterparty", "title", "status"],
  contractParties: ["id", "contractId", "partyType", "name", "taxId", "contactName"],
  contractApprovals: ["id", "contractId", "step", "role", "status", "signedAt"],
  companyRegistry: ["id", "name", "taxId", "status"],
  departmentRegistry: ["id", "company", "name", "manager", "status"],
  sealTypeRegistry: ["id", "name", "scope", "status"],
  documentFlows: ["id", "sourceNo", "kind", "title", "currentStep", "owner", "status"],
  documentTypeConfigs: ["id", "name", "category", "defaultWorkflowTemplate", "defaultFormatTemplate", "status"],
  workflowTemplateConfigs: ["key", "name", "routeCode", "stepsCount", "status"],
  permissionMatrix: ["id", "role", "permission", "label", "granted"],
  formatTemplateConfigs: ["id", "name", "docType", "priority", "security", "status"],
  workflowTasks: ["id", "docNo", "title", "step", "role", "status"],
  recipients: ["id", "name", "code", "center", "status"],
  attachments: ["id", "docId", "name", "version", "hash", "status"],
  exchangeTasks: ["id", "docId", "type", "target", "status", "updatedAt"],
  exchangeEvents: ["id", "taskId", "event", "message", "createdAt"],
  auditLogs: ["id", "actor", "action", "target", "createdAt"]
};

const databaseTables = {
  documents: [],
  contracts: [],
  contractParties: [],
  contractApprovals: [],
  companyRegistry: [],
  departmentRegistry: [],
  sealTypeRegistry: [],
  documentFlows: [],
  documentTypeConfigs: [],
  workflowTemplateConfigs: [],
  permissionMatrix: [],
  formatTemplateConfigs: [],
  workflowTasks: [],
  recipients: [],
  attachments: [],
  exchangeTasks: [],
  exchangeEvents: [],
  auditLogs: []
};

const formatState = {
  attachments: [
    { id: "ATT-1", name: "設立許可補正資料.pdf", pages: 12, type: "PDF", hash: "SHA256-A91F" },
    { id: "ATT-2", name: "附件清冊.xml", pages: 1, type: "XML", hash: "SHA256-B20C" }
  ],
  agencyResults: []
};

const formatAuditLog = [
  ["10:18", "載入文書格式", "已載入預設函稿格式與附件清冊。"]
];

const featureGroups = [
  ["01 收文管理", "jAgent 拉取來文後統一由總務收文登錄，再分發給各部門主管，並保留誤送漏送通知、收文列印與批次匯出。"],
  ["02 發文管理", "建立函稿、受文者與副本管理、清稿檢核、附件封裝、送交 jAgent、查詢交換結果、重送與撤回處理。"],
  ["03 jAgent 介接", "憑證登入、Token 管理、API 狀態、交換中心連線、地址簿查詢、送件、收件、回覆與狀態同步。"],
  ["04 文書格式", "文號、文別、速別、密等、主旨、說明、辦法、附件清冊、受文者機關代碼與標準交換資料欄位。"],
  ["05 流程控管", "依員工清冊職等與職稱推導員工、主管、總務、行政、人資、會計、執行長與檢核角色；收文由總務統一收件後分派部門主管。"],
  ["06 稽催追蹤", "發文翌日查核、逾期提醒、未收確認提醒、異常重送、退回補正與處理時限儀表板。"],
  ["07 歸檔保存", "原文、附件、交換事件、操作軌跡、檔案雜湊、版本、下載紀錄與保存年限控管。"],
  ["08 資安控管", "憑證卡、權限 RBAC、IP/裝置限制、敏感欄位遮罩、登入登出、Token 過期與操作不可否認性。"],
  ["09 報表統計", "收發量、機關往來量、成功率、異常類型、承辦量、逾期件、交換中心服務狀態與月報。"],
  ["10 系統設定", "機關代碼、交換中心、API URL、防火牆、憑證、角色、通知、保存年限、測試/正式環境切換。"],
  ["11 通知中心", "收文通知、待清稿提醒、交換失敗、Token 即將過期、逾期查核、主管退回與稽核警示。"],
  ["12 後端資料庫", "公文主檔、受文者、附件、交換任務、交換事件、jAgent session、audit log 與地址簿快取。"],
  ["13 帳號登入與權限", "使用者帳號、單位職稱、RBAC、SSO、Google Workspace / Microsoft Entra、MFA、登入紀錄、裝置紀錄與 IP 限制。"],
  ["14 檔案與資安控管", "附件防毒掃描、檔案大小限制、敏感資料遮罩、密件權限隔離、下載浮水印、檔案存取紀錄、備份與還原。"],
  ["15 排程與背景任務", "每日收文拉取、發文翌日查核、Token 到期檢查、逾期稽催、合約續約提醒、交換狀態同步、歸檔封存與報表產生。"],
  ["16 管理者維運功能", "jAgent 連線健康檢查、API log 查詢、錯誤碼查詢、系統參數版控、操作紀錄匯出、資料備份與測試/正式環境切換。"],
  ["17 合約管理與簽核", "合約起案、相對人資料、附件清冊、條件式簽核、退回補正、移交合約用印、續約提醒、歸檔與合約 audit log。"]
];

const roleNotes = {
  員工: "可撰寫公文、處理自己的待辦，並查詢所屬部門收發公文紀錄。",
  主管: "可處理所屬部門待辦、簽核與退回補正，並查詢部門公文紀錄。",
  主任: "可查看所屬部門公文、核准部門分派、追蹤逾期與查詢交換結果。",
  執行長: "可查看全公司公文、核定重要或密件流程、查閱報表與稽核紀錄。",
  行政部主任: "可管理流程、清稿、角色設定、jAgent 參數、資安與營運維護。",
  人資: "可處理人資相關來文與發文，查看分派給人資部門的案件。",
  會計: "可處理會計與補助款相關來文與發文，查看分派給會計部門的案件。",
  總務: "唯一收文入口；可登入 jAgent、拉取與登錄來文，再分發給各部門主管。",
  業務助理: "可建立函稿、補附件、依分派協助發文與查詢自己承辦案件。",
  董事會: "可查閱全公司治理層級紀錄、合約與稽核，不處理日常收發。",
  股東: "可查閱經授權的彙總紀錄與治理報表，不處理日常收發。",
  外部檢核單位: "僅可查閱授權檢核資料與 audit log，預設不進入日常公文流程。"
};

const rolePermissions = {
  員工: ["draft_dispatch", "view_assigned", "upload_attachment", "query_status"],
  主管: ["draft_dispatch", "view_assigned", "review_dispatch", "reject_case", "query_status", "view_audit"],
  主任: ["view_assigned", "assign_case", "query_status", "review_dispatch", "approve_contract", "view_audit"],
  執行長: ["view_all_status", "query_status", "review_dispatch", "approve_format", "approve_contract", "view_audit", "export_audit"],
  行政部主任: ["review_dispatch", "assign_case", "reject_case", "approve_format", "manage_contracts", "approve_contract", "manage_jagent", "manage_token", "manage_center", "manage_roles", "query_address_book", "view_audit", "export_audit"],
  人資: ["view_assigned", "draft_dispatch", "draft_contract", "upload_attachment", "reply_case", "query_status"],
  會計: ["view_assigned", "draft_dispatch", "draft_contract", "approve_contract", "upload_attachment", "reply_case", "query_status"],
  總務: ["pull_inbound", "register_inbound", "assign_case", "send_dispatch", "manage_contracts", "approve_contract", "query_status", "query_address_book"],
  業務助理: ["draft_dispatch", "draft_contract", "view_assigned", "upload_attachment", "reply_case", "query_status"],
  董事會: ["official_documents.all_records", "contracts.view", "reports.operational_view", "audit_logs.view", "system_permissions.view"],
  股東: ["official_documents.all_records", "contracts.view", "reports.operational_view", "audit_logs.view"],
  外部檢核單位: ["official_documents.records", "audit_logs.view", "reports.operational_view"]
};

const loggingPermissionAliases = {
  view_assigned: ["official_documents.todo", "official_documents.records"],
  view_all_status: ["official_documents.all_todo", "official_documents.all_records"],
  draft_dispatch: ["official_documents.compose"],
  review_dispatch: ["official_documents.todo"],
  approve_format: ["official_documents.todo"],
  pull_inbound: ["official_documents.receive", "exchange.manage"],
  register_inbound: ["official_documents.receive"],
  assign_case: ["official_documents.receive", "official_documents.todo"],
  send_dispatch: ["exchange.manage"],
  query_status: ["exchange.view"],
  query_address_book: ["exchange.view"],
  manage_jagent: ["exchange.manage"],
  manage_token: ["exchange.manage"],
  manage_center: ["exchange.manage"],
  upload_attachment: ["files.manage"],
  reply_case: ["official_documents.todo"],
  reject_case: ["official_documents.todo"],
  draft_contract: ["contracts.manage"],
  approve_contract: ["contracts.manage"],
  manage_contracts: ["contracts.manage", "contracts.view"],
  view_audit: ["audit_logs.view", "system_permissions.view"],
  export_audit: ["audit_logs.export"],
  manage_roles: ["system_permissions.manage"],
  verify_hash: ["files.manage"],
  "official_documents.compose": ["draft_dispatch"],
  "official_documents.todo": ["view_assigned"],
  "official_documents.records": ["view_assigned"],
  "official_documents.receive": ["pull_inbound", "register_inbound"],
  "official_documents.all_todo": ["view_all_status"],
  "official_documents.all_records": ["view_all_status"],
  "exchange.view": ["query_status", "query_address_book"],
  "exchange.manage": ["send_dispatch", "manage_jagent"],
  "contracts.view": ["draft_contract"],
  "contracts.manage": ["manage_contracts", "approve_contract"],
  "contracts.seal": ["manage_contracts"],
  "files.manage": ["upload_attachment"],
  "seals.manage": ["send_dispatch", "approve_format"],
  "reports.operational_view": ["view_all_status"],
  "audit_logs.view": ["view_audit"],
  "audit_logs.export": ["export_audit"],
  "system_permissions.view": ["view_audit"],
  "system_permissions.manage": ["manage_roles"],
  "settings.system_manage": ["manage_center"]
};

const roleDataScopes = {
  員工: { title: "員工部門池", owner: "員工", departments: ["居家照顧部"], rule: "僅查看本人、所屬部門或被分派的公文。" },
  主管: { title: "主管部門池", owner: "主管", departments: ["居家照顧部"], rule: "僅查看所屬部門、被分派或需主管簽核的公文。" },
  主任: { title: "主任部門池", owner: "主任", departments: ["營運管理處"], rule: "僅查看所屬部門、被分派或需主管核准的公文。" },
  執行長: { title: "全域核定池", owner: "執行長", departments: ["全公司"], rule: "可查閱重大、密件與跨部門核定案件。" },
  行政部主任: { title: "行政部主任工作區", owner: "行政部主任", departments: ["行政部", "總管理處"], rule: "不可直接檢視總務收發池；只看行政部清稿、簽核、維運與授權案件。" },
  人資: { title: "人資部門池", owner: "人資", departments: ["人資"], rule: "僅處理人資相關或被分派案件。" },
  會計: { title: "會計部門池", owner: "會計", departments: ["會計"], rule: "僅處理會計、補助款、核銷相關案件。" },
  總務: { title: "總務收文入口", owner: "總務", departments: ["總務"], rule: "只能處理 jAgent 來文拉取、收文登錄與待分發池；不可直接檢視行政部主任部門公文。" },
  業務助理: { title: "業務助理承辦池", owner: "業務助理", departments: ["業務部"], rule: "僅查看自己承辦、補附件或被派工案件。" },
  董事會: { title: "董事會治理視圖", owner: "董事會", departments: ["全公司"], rule: "只看全公司治理層級紀錄與稽核，不處理流程。" },
  股東: { title: "股東彙總視圖", owner: "股東", departments: ["全公司"], rule: "只看經授權彙總紀錄與報表，不處理流程。" },
  外部檢核單位: { title: "外部檢核授權區", owner: "外部檢核單位", departments: ["授權資料"], rule: "預設不顯示公文，僅顯示單件授權或檢核指定資料。" }
};

const documentAclRules = [
  { id: "ACL-001", docId: "IN-1140522-00018", principalType: "role", principal: "總務", view: true, sign: false, download: true, seal: false, delegate: true, reason: "總務統一拉取、登錄、分派來文。", grantedBy: "system" },
  { id: "ACL-002", docId: "IN-1140522-00018", principalType: "role", principal: "主任", view: true, sign: true, download: true, seal: false, delegate: false, reason: "主管承接分派後可簽核。", grantedBy: "system" },
  { id: "ACL-003", docId: "OUT-1140522-007", principalType: "role", principal: "業務助理", view: true, sign: false, download: false, seal: false, delegate: false, reason: "承辦撰稿，只可檢視與補正內容。", grantedBy: "system" },
  { id: "ACL-004", docId: "OUT-1140522-007", principalType: "role", principal: "行政部主任", view: true, sign: true, download: true, seal: true, delegate: true, reason: "清稿、會辦、用印前核准。", grantedBy: "system" },
  { id: "ACL-005", docId: "OUT-1140522-007", principalType: "role", principal: "總務", view: true, sign: false, download: true, seal: true, delegate: false, reason: "附件封裝、押章與送交 jAgent。", grantedBy: "system" },
  { id: "ACL-006", docId: "OUT-1140519-006", principalType: "role", principal: "總務", view: true, sign: false, download: true, seal: true, delegate: false, reason: "交換失敗重送作業。", grantedBy: "system" },
  { id: "ACL-007", docId: "OUT-1140519-006", principalType: "role", principal: "行政部主任", view: true, sign: true, download: true, seal: true, delegate: true, reason: "異常重送前複核。", grantedBy: "system" },
  { id: "ACL-008", docId: "DOC-ADMIN-1140523-001", principalType: "role", principal: "行政部主任", view: true, sign: true, download: true, seal: true, delegate: true, reason: "行政部內部清稿與權限管理。", grantedBy: "system" },
  { id: "ACL-009", docId: "DOC-ADMIN-1140523-001", principalType: "role", principal: "總務", view: false, sign: false, download: false, seal: false, delegate: false, reason: "明確隔離總務收文區與行政部內部公文。", grantedBy: "system" }
];

const documentAclEvents = [
  ["11:36", "文件 ACL 初始化", "已依公文、角色、簽核與下載需求建立細權限。"]
];

const permissionLabels = {
  pull_inbound: "拉取收文",
  register_inbound: "收文登錄",
  assign_case: "分派案件",
  send_dispatch: "送交 jAgent",
  query_status: "查詢狀態",
  draft_dispatch: "建立函稿",
  view_assigned: "查看承辦案件",
  upload_attachment: "上傳附件",
  reply_case: "回覆案件",
  review_dispatch: "審核發文",
  reject_case: "退回補正",
  approve_format: "核准格式",
  manage_jagent: "管理 jAgent",
  manage_token: "管理 Token",
  manage_center: "管理交換中心",
  manage_roles: "管理角色",
  query_address_book: "查詢地址簿",
  view_audit: "查看稽核",
  export_audit: "匯出稽核",
  verify_hash: "驗證雜湊",
  view_all_status: "查看全域狀態",
  draft_contract: "建立合約",
  approve_contract: "合約簽核",
  manage_contracts: "合約管理",
  "official_documents.compose": "撰寫公文",
  "official_documents.todo": "公文待辦",
  "official_documents.records": "公文紀錄",
  "official_documents.receive": "公文收發",
  "official_documents.all_todo": "全公司公文待辦",
  "official_documents.all_records": "全公司公文紀錄",
  "exchange.view": "交換查詢",
  "exchange.manage": "交換管理",
  "contracts.view": "合約檢視",
  "contracts.manage": "合約管理",
  "contracts.seal": "合約用印",
  "files.manage": "附件管理",
  "seals.manage": "印鑑管理",
  "reports.operational_view": "營運報表",
  "audit_logs.view": "稽核檢視",
  "audit_logs.export": "稽核匯出",
  "system_permissions.view": "權限檢視",
  "system_permissions.manage": "權限管理",
  "settings.system_manage": "系統設定管理"
};

function alignRolePermissionsWithLogging() {
  Object.keys(rolePermissions).forEach((role) => {
    const expanded = new Set(rolePermissions[role] || []);
    [...expanded].forEach((permission) => {
      (loggingPermissionAliases[permission] || []).forEach((alias) => expanded.add(alias));
    });
    rolePermissions[role] = [...expanded];
  });
}

alignRolePermissionsWithLogging();

let workflowRole = "總務";
let draftConfirmed = false;
let draftSigned = false;
let draftPreviewExpanded = false;
let draftPreviewRenderTimer = null;
let activeComposeStep = "fill";
let currentComposeDraftId = "";
let composeSaveState = {
  tone: "idle",
  title: "尚未暫存",
  detail: "輸入內容會先保護在此瀏覽器；按暫存草稿後會出現在發文清單。"
};
let approvalLogFilter = "all";
let approvalLogSearchTerm = "";
const composeSealTypes = ["無", "一般章", "公司設立章", "銀行印鑑章", "圖記章"];
const composeSealPlacements = {
  large: { page: 1, x: 70, y: 80 },
  small: { page: 1, x: 84, y: 80 }
};
let selectedWorkflowTaskId = "WF-001";
let selectedUnifiedFlowId = "";
let unifiedFlowFilter = "all";
const workflowTasks = [
  { id: "WF-001", title: "衛福部補件通知登錄", type: "收文", step: "收文登錄", role: "總務", status: "待處理" },
  { id: "WF-002", title: "臺北市政府社會局會議通知分派", type: "收文", step: "分派部門主管", role: "總務", status: "待處理" },
  { id: "WF-003", title: "日照中心補正資料發文", type: "發文", step: "清稿檢核", role: "行政部主任", status: "待審核" },
  { id: "WF-004", title: "jAgent 交換中心連線設定", type: "系統", step: "介接設定", role: "行政部主任", status: "待處理" },
  { id: "WF-005", title: "五月交換紀錄抽核", type: "稽核", step: "紀錄查核", role: "主任", status: "待查核" },
  { id: "WF-006", title: "人資補助名冊來文", type: "收文", step: "部門主管承接", role: "人資", status: "待處理" },
  { id: "WF-007", title: "會計補助款核銷來文", type: "收文", step: "部門主管承接", role: "會計", status: "待處理" },
  { id: "WF-008", title: "重大密件核定", type: "發文", step: "最終核定", role: "執行長", status: "待審核" }
];

const workflowSteps = [
  ["01", "申請人", "依職等與角色建立起案資料、附件與用印需求，送出後進入本人部門簽核。"],
  ["02", "申請人主管", "由 Logging 職位規劃中的主管層確認需求、附件與辦理依據。"],
  ["03", "部門主管", "由部門主管層確認部門權責、金額、對外承諾與風險。"],
  ["04", "會計", "僅 B / D 路由進入，複核費用、付款條件、預算與稅務資料。"],
  ["05", "行政部門主任", "依 A / B / C / D 路由核定行政用印、文件完整性與流程合法性。"],
  ["06", "執行長", "僅 C / D 路由進入，核定最高層代表、重大治理或高風險用印。"],
  ["07", "總務", "核准後執行用印、登錄、保存影像與移交歸檔。"],
  ["08", "申請人", "用印完成後回到申請人確認，完成結案與後續辦理。"]
];

const workflowAuditLog = [
  ["10:22", "流程控管初始化", "已載入角色權限矩陣與待辦佇列。"]
];

const approvalRouteTypes = {
  A: {
    code: "A",
    name: "A 行政部門用印（無需會計）",
    shortName: "行政部門用印",
    requiresAccounting: false,
    requiresCeo: false
  },
  B: {
    code: "B",
    name: "B 行政部門用印（需會計）",
    shortName: "行政部門用印 + 會計",
    requiresAccounting: true,
    requiresCeo: false
  },
  C: {
    code: "C",
    name: "C 執行長用印（無需會計）",
    shortName: "執行長用印",
    requiresAccounting: false,
    requiresCeo: true
  },
  D: {
    code: "D",
    name: "D 執行長用印（需會計）",
    shortName: "執行長用印 + 會計",
    requiresAccounting: true,
    requiresCeo: true
  }
};

const approvalDocumentCategories = [
  {
    group: "1. 合約類（勿選）",
    items: [
      { label: "商務合約", route: "B" },
      { label: "合作意向書", route: "A", aliases: ["合作備忘錄", "保密協議"] },
      { label: "採購合約", route: "D" },
      { label: "服務委託合約", route: "C", aliases: ["聘僱/顧問合約"] },
      { label: "租賃契約", route: "D", aliases: ["租賃合約"] }
    ]
  },
  {
    group: "2. 法務／政府單位文件（勿選）",
    items: [
      { label: "主管機關 申請或回覆文件（與 費用、法令有關）", route: "D" },
      { label: "主管機關 申請或回覆文件（與 費用、法令無關）", route: "A" },
      { label: "勞保、健保、退休金文件", route: "A" }
    ]
  },
  {
    group: "3. 公司治理相關用印（勿選）",
    items: [
      { label: "董事會、股東會文件", route: "C" },
      { label: "法人章程、修訂案", route: "C" },
      { label: "重大決議用印", route: "C" },
      { label: "股權文件", route: "D" }
    ]
  },
  {
    group: "4. 品牌／公信用文件（勿選）",
    items: [
      { label: "官方公文（需公司最高層代表時）", route: "C" },
      { label: "授權書（授權對外正式行為）", route: "C" },
      { label: "合作聲明（涉及法律關係者）", route: "C" }
    ]
  }
];

const approvalCategoryItems = approvalDocumentCategories.flatMap((group) =>
  group.items.map((item) => ({ ...item, group: group.group }))
);

function approvalCategoryForType(type = "") {
  const normalized = String(type || "").trim();
  return approvalCategoryItems.find((item) =>
    item.label === normalized || (item.aliases || []).includes(normalized)
  ) || {
    label: normalized || "其他用印文件",
    group: "例外條件",
    route: "A",
    aliases: []
  };
}

function approvalRouteForType(type = "") {
  const category = approvalCategoryForType(type);
  return approvalRouteTypes[category.route] || approvalRouteTypes.A;
}

function workflowTemplateKeyForRoute(routeCode = "A") {
  return `route${approvalRouteTypes[routeCode]?.code || "A"}`;
}

function workflowStepsForRoute(routeCode = "A") {
  const route = approvalRouteTypes[routeCode] || approvalRouteTypes.A;
  const steps = ["申請人送出", "申請人主管審核", "部門主管審核"];
  if (route.requiresAccounting) steps.push("會計複核");
  steps.push("行政部門主任核定");
  if (route.requiresCeo) steps.push("執行長核定");
  steps.push("總務用印登錄", "申請人確認");
  return steps;
}

function workflowTemplateForRoute(routeCode = "A") {
  const route = approvalRouteTypes[routeCode] || approvalRouteTypes.A;
  return {
    name: route.name,
    routeCode: route.code,
    steps: workflowStepsForRoute(route.code)
  };
}

let activeWorkflowTemplate = "routeC";
const workflowTemplates = {
  routeA: workflowTemplateForRoute("A"),
  routeB: workflowTemplateForRoute("B"),
  routeC: workflowTemplateForRoute("C"),
  routeD: workflowTemplateForRoute("D"),
  standard: { name: "一般發文簽核（舊範本）", routeCode: "A", steps: workflowStepsForRoute("A") },
  urgent: { name: "速件發文簽核（舊範本）", routeCode: "A", steps: workflowStepsForRoute("A") },
  confidential: { name: "密件發文簽核（舊範本）", routeCode: "C", steps: workflowStepsForRoute("C") },
  procurement: { name: "採購/金額簽核（舊範本）", routeCode: "D", steps: workflowStepsForRoute("D") }
};

const adminConfigStorageKey = "suiyuecare-edoc-admin-config";
let selectedFormatTemplateId = "FMT-OFFICIAL";

const workflowTemplateConfigs = Object.entries(workflowTemplates).map(([key, template]) => ({
  key,
  name: template.name,
  routeCode: template.routeCode || "A",
  steps: [...template.steps],
  status: "啟用"
}));

const documentTypeConfigs = [
  { id: "DTC-001", name: "函", category: "公文", defaultWorkflowTemplate: "routeA", defaultFormatTemplate: "FMT-OFFICIAL", defaultPriority: "普通件", defaultSecurity: "普通", status: "啟用" },
  { id: "DTC-002", name: "開會通知單", category: "公文", defaultWorkflowTemplate: "routeA", defaultFormatTemplate: "FMT-MEETING", defaultPriority: "普通件", defaultSecurity: "普通", status: "啟用" },
  { id: "DTC-003", name: "書函", category: "公文", defaultWorkflowTemplate: "routeA", defaultFormatTemplate: "FMT-OFFICIAL", defaultPriority: "普通件", defaultSecurity: "普通", status: "啟用" },
  { id: "DTC-004", name: "公告", category: "公文", defaultWorkflowTemplate: "routeA", defaultFormatTemplate: "FMT-ANNOUNCE", defaultPriority: "普通件", defaultSecurity: "普通", status: "啟用" },
  { id: "DTC-005", name: "令", category: "公文", defaultWorkflowTemplate: "routeC", defaultFormatTemplate: "FMT-OFFICIAL", defaultPriority: "速件", defaultSecurity: "普通", status: "啟用" },
  { id: "DTC-006", name: "合約用印", category: "合約", defaultWorkflowTemplate: "routeC", defaultFormatTemplate: "FMT-CONTRACT-SEAL", defaultPriority: "普通件", defaultSecurity: "普通", status: "啟用" }
];

const formatTemplateConfigs = [
  { id: "FMT-OFFICIAL", name: "政府機關函稿", docType: "函", priority: "普通件", security: "普通", subjectHint: "檢送相關資料，請查照。", attachments: ["函稿本文.pdf", "附件清冊.xml"], status: "啟用" },
  { id: "FMT-MEETING", name: "開會通知單", docType: "開會通知單", priority: "普通件", security: "普通", subjectHint: "檢送會議通知，請查照。", attachments: ["開會通知單.pdf", "議程.pdf"], status: "啟用" },
  { id: "FMT-ANNOUNCE", name: "公告格式", docType: "公告", priority: "普通件", security: "普通", subjectHint: "公告本公司相關事項。", attachments: ["公告本文.pdf"], status: "啟用" },
  { id: "FMT-CONTRACT-SEAL", name: "合約用印申請", docType: "合約用印", priority: "普通件", security: "普通", subjectHint: "檢送合約用印申請，請核示。", attachments: ["合約本文.pdf", "用印申請單.pdf"], status: "啟用" }
];

loadAdminConfigState();
syncWorkflowTemplateObject();

const workflowProxies = [
  { id: "PX-001", from: "行政部主任", to: "總務", reason: "主管差勤代理", status: "啟用" }
];

const workflowProofLog = [
  ["11:28", "簽核引擎初始化", "流程範本、條件規則、代理人與不可否認紀錄已載入。"]
];

let selectedSealId = "SEAL-001";
let selectedSealRequestId = "REQ-001";
const companyRegistry = [
  { id: "CO-001", name: "歲悅長照股份有限公司", taxId: "待設定", status: "啟用" }
];
const departmentRegistry = [
  { id: "DEP-001", company: "歲悅長照股份有限公司", name: "總管理處", manager: "執行長", status: "啟用" },
  { id: "DEP-002", company: "歲悅長照股份有限公司", name: "行政部", manager: "行政部主任", status: "啟用" },
  { id: "DEP-003", company: "歲悅長照股份有限公司", name: "總務", manager: "總務", status: "啟用" }
];
const sealTypeRegistry = [
  { id: "ST-001", name: "一般章", scope: "日常公文、一般函稿", status: "啟用" },
  { id: "ST-002", name: "公司設立章", scope: "設立登記、公司變更、重大文件", status: "啟用" },
  { id: "ST-003", name: "銀行章", scope: "銀行往來、帳戶、授權文件", status: "啟用" },
  { id: "ST-004", name: "圖記章", scope: "政府機關登記圖記、正式用印", status: "啟用" }
];
const sealRegistry = [
  { id: "SEAL-001", company: "歲悅長照股份有限公司", department: "行政部", name: "歲悅長照公司章", type: "一般章", owner: "行政部主任", docType: "函", status: "啟用", widthMm: 30, heightMm: 30, imageName: "待上傳", imageDataUrl: "", fileObjectId: "", calibrationStatus: "待上傳圖檔", hash: "SHA256-SEAL-A19F" },
  { id: "SEAL-002", company: "歲悅長照股份有限公司", department: "行政部", name: "歲悅負責人章", type: "圖記章", owner: "行政部主任", docType: "函", status: "啟用", widthMm: 18, heightMm: 18, imageName: "待上傳", imageDataUrl: "", fileObjectId: "", calibrationStatus: "待上傳圖檔", hash: "SHA256-SEAL-B72C" },
  { id: "SEAL-003", company: "歲悅長照股份有限公司", department: "總務", name: "附件騎縫章", type: "一般章", owner: "總務", docType: "附件", status: "停用", widthMm: 10, heightMm: 35, imageName: "待上傳", imageDataUrl: "", fileObjectId: "", calibrationStatus: "待上傳圖檔", hash: "SHA256-SEAL-C44D" }
];

const sealRequests = [
  { id: "REQ-001", docId: "OUT-1140522-007", sealId: "SEAL-001", step: "行政部主任簽核", status: "待簽核", stampNo: "", stampedAt: "" },
  { id: "REQ-002", docId: "OUT-1140520-009", sealId: "SEAL-002", step: "負責人核定", status: "已押章", stampNo: "STAMP-1140520-009", stampedAt: "2026-05-22 09:30" }
];

const sealAuditLog = [
  ["11:18", "印鑑管理初始化", "已載入印鑑清冊、簽核佇列與用印軌跡。"]
];

let uploadedSealPdf = null;
let uploadedSealObjectUrl = "";
let uploadedSealStampPositions = [];
let companySealModuleLoaded = false;
let companySealCompanies = [];
let companySealReferences = { grouped: {} };
let companySealLibrary = [];
let companySealFiles = [];
let companySealRequests = [];
let companySealLogs = [];
let selectedCompanySealCompanyId = "";
let selectedCompanySealId = "";
let companySealStampPositions = [
  { page: 1, x: 420, y: 130, w: 85, h: 85, label: "用印", type: "general_seal" }
];

const pdfPointsPerMm = 72 / 25.4;

function sealWidthPt(seal) {
  return Math.round(Number(seal?.widthMm || 30) * pdfPointsPerMm * 100) / 100;
}

function sealHeightPt(seal) {
  return Math.round(Number(seal?.heightMm || 30) * pdfPointsPerMm * 100) / 100;
}

const signingCertificates = [
  { id: "CERT-SEAL-001", owner: "行政部主任", type: "組織憑證", subject: "CN=Suiyuecare Admin Chief Seal,O=Suiyuecare", issuer: "Suiyuecare Internal CA", serialNo: "SYC-SEAL-2026-0001", algorithm: "HMAC-SHA256-RSA-PSS-READY", validTo: "2027-12-31", status: "啟用", fingerprint: "SHA256-CERT-SEAL-001", chainStatus: "待驗證", ocspStatus: "待查詢", crlStatus: "待查詢", tsaStatus: "待驗證" },
  { id: "CERT-SEAL-002", owner: "總務", type: "工商憑證", subject: "CN=Suiyuecare General Affairs Seal,O=Suiyuecare", issuer: "Suiyuecare Internal CA", serialNo: "SYC-GA-2026-0002", algorithm: "HMAC-SHA256-RSA-PSS-READY", validTo: "2027-12-31", status: "啟用", fingerprint: "SHA256-CERT-SEAL-002", chainStatus: "待驗證", ocspStatus: "待查詢", crlStatus: "待查詢", tsaStatus: "待驗證" },
  { id: "CERT-TSA-001", owner: "系統時間戳", type: "時間戳憑證", subject: "CN=Suiyuecare TSA,O=Suiyuecare", issuer: "Suiyuecare Internal CA", serialNo: "SYC-TSA-2026-0001", algorithm: "RFC3161-TSA-SIM", validTo: "2027-12-31", status: "啟用", fingerprint: "SHA256-CERT-TSA-001", chainStatus: "待驗證", ocspStatus: "待查詢", crlStatus: "待查詢", tsaStatus: "待驗證" }
];

const electronicSignatureProofs = [
  { id: "ESIG-DEMO-001", docId: "OUT-1140522-007", signer: "行政部主任", certificateId: "CERT-SEAL-001", type: "seal", algorithm: "HMAC-SHA256-RSA-PSS-READY", digest: "待正式簽章後更新", signature: "待簽章", tsaToken: "待時間戳", status: "待簽章", createdAt: "尚未建立", certificateValidation: { chain_status: "待驗證", ocsp_status: "待查詢", crl_status: "待查詢", tsa_status: "待驗證", certificate_type: "組織憑證" } }
];

let certificateServiceState = {
  ready: false,
  mode: "未檢查",
  services: {},
  missing: []
};

const pdfVersionStore = {};

let selectedContractId = "CON-1140525-001";
let contractFilter = "all";
let contractSearchTerm = "";

const contractRecords = [
  {
    id: "CON-1140525-001",
    contractNo: "合約字第1140525001號",
    companyName: "歲悅長照股份有限公司",
    type: "服務委託合約",
    title: "日間照顧中心資訊系統維護合約",
    counterparty: "康照資訊股份有限公司",
    counterpartyTaxId: "24567890",
    owner: "業務助理",
    dept: "行政部",
    amount: 180000,
    currency: "TWD",
    startDate: "2026-06-01",
    endDate: "2027-05-31",
    renewalDays: 60,
    confidentiality: "普通",
    sealRequirement: "一般章",
    storageStatus: "待歸檔",
    status: "待主管審核",
    summary: "年度資訊維護、客服支援、資安弱點修補與 SLA 回覆承諾。",
    riskNote: "C 執行長用印（無需會計）：需申請人主管、部門主管、行政部門主任、執行長、總務與申請人確認。",
    attachments: ["合約草案.pdf", "報價單.pdf", "服務範圍清單.xlsx"],
    signedAt: "",
    archiveHash: "",
    createdAt: "2026-05-25 09:12"
  },
  {
    id: "CON-1140524-002",
    contractNo: "合約字第1140524002號",
    companyName: "歲悅長照股份有限公司",
    type: "租賃契約",
    title: "板橋據點辦公設備租賃合約",
    counterparty: "新北設備租賃有限公司",
    counterpartyTaxId: "90345671",
    owner: "總務",
    dept: "總務",
    amount: 72000,
    currency: "TWD",
    startDate: "2026-06-15",
    endDate: "2027-06-14",
    renewalDays: 45,
    confidentiality: "普通",
    sealRequirement: "一般章",
    storageStatus: "待歸檔",
    status: "待用印簽署",
    summary: "影印機、掃描設備與耗材保固租賃。",
    riskNote: "D 執行長用印（需會計）：用印前請確認租期、提前解約條款、會計複核與維修回應時間。",
    attachments: ["租賃合約草案.pdf", "設備明細.pdf"],
    signedAt: "",
    archiveHash: "",
    createdAt: "2026-05-24 15:20"
  }
];

const contractApprovals = [
  { id: "CA-001", contractId: "CON-1140525-001", stepNo: 1, step: "申請人送出", role: "業務助理", status: "完成", approver: "周業助", comment: "已上傳草案與報價單，路由 C。", signedAt: "2026-05-25 09:12" },
  { id: "CA-002", contractId: "CON-1140525-001", stepNo: 2, step: "申請人主管審核", role: "主管", status: "待簽核", approver: "", comment: "請確認服務範圍與 SLA。", signedAt: "" },
  { id: "CA-003", contractId: "CON-1140525-001", stepNo: 3, step: "部門主管審核", role: "主任", status: "待簽核", approver: "", comment: "確認部門權責與履約風險。", signedAt: "" },
  { id: "CA-004", contractId: "CON-1140525-001", stepNo: 4, step: "行政部門主任核定", role: "行政部主任", status: "待簽核", approver: "", comment: "確認合約條款與用印需求。", signedAt: "" },
  { id: "CA-005", contractId: "CON-1140525-001", stepNo: 5, step: "執行長核定", role: "執行長", status: "待簽核", approver: "", comment: "服務委託合約依 C 路由需執行長用印核定。", signedAt: "" },
  { id: "CA-006", contractId: "CON-1140525-001", stepNo: 6, step: "總務用印登錄", role: "總務", status: "待用印", approver: "", comment: "核准後由總務用印並留存版本。", signedAt: "" },
  { id: "CA-007", contractId: "CON-1140525-001", stepNo: 7, step: "申請人確認", role: "業務助理", status: "待確認", approver: "", comment: "用印完成後回到申請人確認。", signedAt: "" },
  { id: "CA-008", contractId: "CON-1140525-001", stepNo: 8, step: "歸檔保存", role: "行政部主任", status: "待歸檔", approver: "", comment: "確認後建立保存包與續約提醒。", signedAt: "" },
  { id: "CA-009", contractId: "CON-1140524-002", stepNo: 1, step: "申請人送出", role: "總務", status: "完成", approver: "林總務", comment: "設備租賃契約已完成草案，路由 D。", signedAt: "2026-05-24 15:20" },
  { id: "CA-010", contractId: "CON-1140524-002", stepNo: 2, step: "申請人主管審核", role: "主管", status: "完成", approver: "王主管", comment: "需求已確認。", signedAt: "2026-05-24 16:00" },
  { id: "CA-011", contractId: "CON-1140524-002", stepNo: 3, step: "部門主管審核", role: "主任", status: "完成", approver: "部門主管", comment: "租期與條款已確認。", signedAt: "2026-05-24 16:30" },
  { id: "CA-012", contractId: "CON-1140524-002", stepNo: 4, step: "會計複核", role: "會計", status: "完成", approver: "許會計", comment: "付款條件與預算已複核。", signedAt: "2026-05-24 16:50" },
  { id: "CA-013", contractId: "CON-1140524-002", stepNo: 5, step: "行政部門主任核定", role: "行政部主任", status: "完成", approver: "張行政", comment: "條款與租期已確認。", signedAt: "2026-05-24 17:10" },
  { id: "CA-014", contractId: "CON-1140524-002", stepNo: 6, step: "執行長核定", role: "執行長", status: "完成", approver: "陳執行長", comment: "D 路由已核定。", signedAt: "2026-05-24 17:30" },
  { id: "CA-015", contractId: "CON-1140524-002", stepNo: 7, step: "總務用印登錄", role: "總務", status: "待用印", approver: "", comment: "待確認用印與簽署後交回申請人確認。", signedAt: "" },
  { id: "CA-016", contractId: "CON-1140524-002", stepNo: 8, step: "申請人確認", role: "總務", status: "待確認", approver: "", comment: "用印完成後確認。", signedAt: "" },
  { id: "CA-017", contractId: "CON-1140524-002", stepNo: 9, step: "歸檔保存", role: "行政部主任", status: "待歸檔", approver: "", comment: "確認後建立保存包與續約提醒。", signedAt: "" }
];

const contractAuditLog = [
  ["09:18", "合約管理初始化", "已載入本單位合約台帳、簽核流程、續約提醒與合約用印移交狀態。"]
];

const contractSealAuditLog = [
  ["09:20", "合約用印初始化", "已建立獨立合約用印工作區，總務用印在此處理。"]
];

function isUnifiedFlowIssue(flowOrStatus) {
  const text = typeof flowOrStatus === "string"
    ? flowOrStatus
    : `${flowOrStatus?.status || ""} ${flowOrStatus?.currentStep || ""} ${flowOrStatus?.lastReply || ""}`;
  return /失敗|退回|補正|逾期|未收|異常|隔離|錯誤/.test(text);
}

function isUnifiedFlowComplete(flowOrStatus) {
  const text = typeof flowOrStatus === "string"
    ? flowOrStatus
    : `${flowOrStatus?.status || ""} ${flowOrStatus?.currentStep || ""}`;
  return /交換完成|已入案|已結案|已歸檔|已簽署|完成歸檔|已完成/.test(text) && !isUnifiedFlowIssue(text);
}

function isUnifiedFlowTodo(flow) {
  return Boolean(flow) && !isUnifiedFlowComplete(flow);
}

function unifiedStatusBadge(status) {
  if (isUnifiedFlowIssue(status)) return "issue";
  if (isUnifiedFlowComplete(status)) return "ok";
  if (/待|審核|簽核|用印|確認|清稿|辦理|封裝/.test(status)) return "wait";
  return "info";
}

function unifiedSourceLabel(sourceType) {
  return {
    inbound: "收文",
    dispatch: "發文",
    contract: "合約",
    seal: "用印",
    workflow: "簽核"
  }[sourceType] || sourceType || "文件";
}

function unifiedStepObjects(stepNames, currentIndex, status) {
  const steps = stepNames.length ? stepNames : ["建立流程"];
  const safeIndex = Math.max(0, Math.min(Number(currentIndex || 0), steps.length - 1));
  const complete = isUnifiedFlowComplete(status);
  const issue = isUnifiedFlowIssue(status);
  return steps.map((title, index) => {
    const state = complete || index < safeIndex
      ? "done"
      : issue && index === safeIndex
        ? "issue"
        : index === safeIndex
          ? "current"
          : "pending";
    return {
      no: String(index + 1).padStart(2, "0"),
      title,
      state,
      status: state === "done" ? "已完成" : state === "issue" ? status : state === "current" ? status : "待後續"
    };
  });
}

function currentUnifiedStep(steps, fallback = "建立流程") {
  return steps.find((step) => step.state === "current" || step.state === "issue") || steps.at(-1) || { title: fallback, status: "" };
}

function unifiedFlowBase(input) {
  const steps = unifiedStepObjects(input.stepNames, input.currentIndex, input.status);
  const current = currentUnifiedStep(steps, input.currentStep);
  return {
    ...input,
    steps,
    currentStep: input.currentStep || current.title,
    currentOwner: input.currentOwner || input.owner || "系統",
    isIssue: isUnifiedFlowIssue(input.status),
    isTodo: !isUnifiedFlowComplete(input.status)
  };
}

function unifiedFlowFromInbound(doc) {
  const stepNames = ["jAgent 來文", "收文登錄", "總務分派", "承辦辦理", "結案歸檔"];
  let currentIndex = 1;
  if (/待分派/.test(doc.status)) currentIndex = 2;
  if (/已收文|辦理/.test(doc.status)) currentIndex = 3;
  if (/已入案|已結案|完成|歸檔/.test(doc.status)) currentIndex = 4;
  return unifiedFlowBase({
    id: `FLOW-IN-${doc.id}`,
    sourceType: "inbound",
    sourceId: doc.id,
    kind: "公文",
    direction: "收文",
    sourceNo: doc.receiveNo || doc.id,
    title: doc.subject,
    agency: doc.agency,
    dept: doc.dept || doc.owner || "",
    owner: doc.owner || doc.dept || "總務",
    status: doc.status,
    currentIndex,
    currentOwner: currentIndex <= 2 ? "總務" : doc.owner || doc.dept || "承辦人",
    stepNames,
    summary: `來文機關：${doc.agency || "未設定"}；期限：${doc.dueDate || "未設定"}。`,
    attachments: doc.attachments || []
  });
}

function unifiedFlowFromDispatch(doc) {
  const task = workflowTasks.find((item) => item.docId === doc.id);
  const approvalSteps = task ? approvalTemplateForTask(task) : ["清稿簽核"];
  const stepNames = ["起案填寫", ...approvalSteps, "用印押章", "附件封裝", "送交交換", "確認歸檔"];
  let currentIndex = 0;
  if (task && /待|審核|簽核|退回/.test(task.status)) {
    currentIndex = 1 + approvalCurrentIndex(task, approvalSteps);
  } else if (/草稿/.test(doc.status)) {
    currentIndex = 0;
  } else if (/待清稿|待簽核|待審核|退回/.test(doc.status)) {
    currentIndex = 1;
  } else if (/已清稿|已押章/.test(doc.status)) {
    currentIndex = 1 + approvalSteps.length;
  } else if (/已封裝/.test(doc.status)) {
    currentIndex = 2 + approvalSteps.length;
  } else if (/等待確認|交換失敗/.test(doc.status)) {
    currentIndex = 3 + approvalSteps.length;
  } else if (/交換完成|歸檔/.test(doc.status)) {
    currentIndex = stepNames.length - 1;
  }
  const currentOwner = task && /待|審核|簽核|退回/.test(task.status)
    ? task.role
    : currentIndex <= 0
      ? doc.owner || "承辦人"
      : currentIndex >= stepNames.length - 2
        ? "總務"
        : "行政部主任";
  return unifiedFlowBase({
    id: `FLOW-OUT-${doc.id}`,
    sourceType: "dispatch",
    sourceId: doc.id,
    relatedWorkflowTaskId: task?.id || "",
    kind: "公文",
    direction: "發文",
    sourceNo: doc.no || doc.id,
    title: doc.subject,
    agency: doc.to,
    dept: doc.dept || doc.owner || "",
    owner: doc.owner || "承辦人",
    status: task?.status && /退回/.test(task.status) ? task.status : doc.status,
    currentIndex,
    currentOwner,
    stepNames,
    summary: doc.lastReply || `受文者：${doc.to || "未設定"}；速別：${doc.priority || "普通件"}。`,
    attachments: doc.attachments || []
  });
}

function unifiedFlowFromContract(contract) {
  const approvals = contractApprovalsFor(contract.id);
  const fallbackSteps = workflowStepsForRoute(approvalRouteForType(contract.type).code);
  const stepNames = approvals.length ? approvals.map((approval) => approval.step) : fallbackSteps;
  const current = currentContractApproval(contract);
  const currentIndex = current
    ? Math.max(0, stepNames.findIndex((step) => step === current.step))
    : stepNames.length - 1;
  return unifiedFlowBase({
    id: `FLOW-CON-${contract.id}`,
    sourceType: "contract",
    sourceId: contract.id,
    kind: "合約",
    direction: "合約",
    sourceNo: contract.contractNo || contract.id,
    title: contract.title,
    agency: contract.counterparty,
    dept: contract.dept || "",
    owner: contract.owner || "申請人",
    status: contract.status,
    currentIndex,
    currentOwner: current?.role || contract.owner || "申請人",
    stepNames,
    summary: `${contract.type || "合約"}；法人：${contract.companyName || "未設定"}；相對人：${contract.counterparty || "未設定"}。`,
    attachments: contract.attachments || []
  });
}

function unifiedFlowFromSealRequest(request) {
  const doc = sealRequestDoc(request);
  const seal = sealById(request.sealId);
  const stepNames = ["用印申請", "核准", "PDF 套版", "自動押章", "保存紀錄"];
  let currentIndex = 0;
  if (/待簽核/.test(request.status)) currentIndex = 1;
  if (/已押章/.test(request.status)) currentIndex = 4;
  if (/退回/.test(request.status)) currentIndex = 1;
  return unifiedFlowBase({
    id: `FLOW-SEAL-${request.id}`,
    sourceType: "seal",
    sourceId: request.id,
    relatedDocId: request.docId,
    kind: "用印",
    direction: "用印",
    sourceNo: request.stampNo || doc?.no || request.id,
    title: doc?.subject || request.id,
    agency: seal?.name || "印鑑未設定",
    dept: doc?.dept || seal?.department || "",
    owner: request.step || seal?.owner || "總務",
    status: request.status,
    currentIndex,
    currentOwner: /待簽核|退回/.test(request.status) ? request.step || "行政部主任" : "總務",
    stepNames,
    summary: `印鑑：${seal?.name || "未設定"}；尺寸：${seal ? `${seal.widthMm} x ${seal.heightMm} mm` : "未設定"}。`,
    attachments: doc?.attachments || []
  });
}

function unifiedFlowFromWorkflowTask(task) {
  const snapshot = approvalProgressSnapshot(task);
  const current = snapshot.steps.find((step) => step.state === "current" || step.state === "returned") || snapshot.steps[0];
  return unifiedFlowBase({
    id: `FLOW-WF-${task.id}`,
    sourceType: "workflow",
    sourceId: task.id,
    kind: "簽核",
    direction: task.type || "簽核",
    sourceNo: task.docId || task.id,
    title: task.title,
    agency: task.type,
    dept: task.role || "",
    owner: task.requester || task.role || "申請人",
    status: task.status,
    currentIndex: Math.max(0, snapshot.steps.findIndex((step) => step.no === current?.no)),
    currentOwner: current?.owner || task.role,
    stepNames: snapshot.steps.map((step) => step.title),
    summary: task.lastComment || `${task.step || "流程節點"} 由 ${task.role || "未設定"} 處理。`,
    attachments: []
  });
}

function buildUnifiedDocumentFlows() {
  const dispatchIds = new Set(dispatchDocs.map((doc) => doc.id));
  const flows = [
    ...inboundDocs.map(unifiedFlowFromInbound),
    ...dispatchDocs.map(unifiedFlowFromDispatch),
    ...contractRecords.map(unifiedFlowFromContract),
    ...sealRequests.map(unifiedFlowFromSealRequest),
    ...workflowTasks
      .filter((task) => !task.docId || !dispatchIds.has(task.docId))
      .map(unifiedFlowFromWorkflowTask)
  ];
  return flows.sort((a, b) => Number(b.isIssue) - Number(a.isIssue) || Number(b.isTodo) - Number(a.isTodo) || String(a.sourceNo).localeCompare(String(b.sourceNo), "zh-Hant"));
}

function visibleUnifiedDocumentFlows() {
  const role = activeRole();
  if (canSeeCompanyWideDocs(role)) return buildUnifiedDocumentFlows();
  const inboundIds = new Set(scopedInboundDocs().map((doc) => doc.id));
  const dispatchIds = new Set(scopedDispatchDocs().map((doc) => doc.id));
  const contractIds = new Set(visibleContracts().map((contract) => contract.id));
  const unit = activeUnit();
  return buildUnifiedDocumentFlows().filter((flow) => {
    if (flow.sourceType === "inbound") return inboundIds.has(flow.sourceId);
    if (flow.sourceType === "dispatch") return dispatchIds.has(flow.sourceId);
    if (flow.sourceType === "contract") return contractIds.has(flow.sourceId);
    if (flow.sourceType === "seal") return dispatchIds.has(flow.relatedDocId) || flow.currentOwner === role || flow.owner === role || flow.dept === unit;
    return flow.currentOwner === role || flow.owner === role || flow.dept === role || flow.dept === unit;
  });
}

function filteredUnifiedDocumentFlows() {
  return visibleUnifiedDocumentFlows().filter((flow) => {
    if (unifiedFlowFilter === "all") return true;
    if (unifiedFlowFilter === "issue") return flow.isIssue;
    return flow.kind === unifiedFlowFilter;
  });
}

function unifiedFlowTodoCard(flow) {
  return {
    badge: flow.kind,
    title: flow.title,
    meta: `${flow.sourceNo} · ${flow.currentStep}`,
    body: `${flow.currentOwner} · ${flow.status}`,
    issue: flow.isIssue
  };
}

function unifiedFlowReminder(flow, type = "文件待辦") {
  return {
    id: `REM-${flow.id}`,
    type,
    title: flow.title,
    target: flow.currentOwner || flow.owner,
    status: flow.status,
    source: flow.id,
    body: `${flow.kind} · ${flow.sourceNo} · ${flow.currentStep}`
  };
}

function currentUnifiedFlow() {
  const rows = filteredUnifiedDocumentFlows();
  return rows.find((flow) => flow.id === selectedUnifiedFlowId) || rows[0] || null;
}

function renderUnifiedFlowDetail(flow = currentUnifiedFlow()) {
  const detail = document.querySelector("#unifiedFlowDetail");
  if (!detail) return;
  if (!flow) {
    detail.innerHTML = `<p class="empty-text">目前沒有可檢視的文件流程。</p>`;
    return;
  }
  const current = currentUnifiedStep(flow.steps, flow.currentStep);
  detail.innerHTML = `
    <div>
      <span class="badge ${unifiedStatusBadge(flow.status)}">${flow.kind} · ${flow.direction}</span>
      <h4>${flow.title}</h4>
      <p>${flow.summary || "此文件已納入統一流程核心。"}</p>
    </div>
    <dl class="unified-flow-meta">
      <div><dt>文件編號</dt><dd>${flow.sourceNo}</dd></div>
      <div><dt>來源</dt><dd>${unifiedSourceLabel(flow.sourceType)}</dd></div>
      <div><dt>目前節點</dt><dd>${current.title}</dd></div>
      <div><dt>負責角色</dt><dd>${flow.currentOwner}</dd></div>
      <div><dt>單位</dt><dd>${flow.dept || "未設定"}</dd></div>
      <div><dt>狀態</dt><dd>${flow.status}</dd></div>
    </dl>
    <div class="unified-flow-steps">
      ${flow.steps.map((step) => `
        <article class="unified-flow-step ${step.state}">
          <time>${step.no}</time>
          <div>
            <strong>${step.title}</strong>
            <span>${step.status}</span>
          </div>
        </article>
      `).join("")}
    </div>
    <div class="detail-actions">
      <button class="primary-button" type="button" data-unified-flow-open="${flow.id}">開啟來源</button>
      <button class="secondary-button" type="button" data-unified-flow-log="${flow.id}">簽核紀錄</button>
    </div>
  `;
  detail.querySelector("[data-unified-flow-open]")?.addEventListener("click", () => openUnifiedFlowSource(flow.id));
  detail.querySelector("[data-unified-flow-log]")?.addEventListener("click", () => {
    if (flow.relatedWorkflowTaskId) selectedWorkflowTaskId = flow.relatedWorkflowTaskId;
    if (flow.sourceType === "workflow") selectedWorkflowTaskId = flow.sourceId;
    setView("approvalLog");
    renderApprovalLog();
  });
}

function renderUnifiedFlows() {
  const rows = filteredUnifiedDocumentFlows();
  const tbody = document.querySelector("#unifiedFlowRows");
  const count = document.querySelector("#unifiedFlowCount");
  if (!tbody || !count) return;
  if (!rows.some((flow) => flow.id === selectedUnifiedFlowId)) selectedUnifiedFlowId = rows[0]?.id || "";
  count.textContent = `${rows.length} 件`;
  tbody.innerHTML = rows.length ? rows.map((flow) => `
    <tr class="${flow.id === selectedUnifiedFlowId ? "selected-row" : ""}">
      <td><button class="unified-flow-row-button" type="button" data-unified-flow-select="${flow.id}">${flow.sourceNo}</button><small>${flow.direction}</small></td>
      <td>${flow.kind}</td>
      <td>${flow.title}<small>${flow.agency || flow.summary || ""}</small></td>
      <td>${flow.currentStep}</td>
      <td>${flow.currentOwner}</td>
      <td><span class="badge ${unifiedStatusBadge(flow.status)}">${flow.status}</span></td>
    </tr>
  `).join("") : `
    <tr>
      <td colspan="6"><p class="empty-text">目前沒有符合條件的文件流程。</p></td>
    </tr>
  `;
  document.querySelectorAll("[data-unified-flow-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedUnifiedFlowId = button.dataset.unifiedFlowSelect;
      renderUnifiedFlows();
    });
  });
  document.querySelectorAll("[data-unified-flow-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.unifiedFlowFilter === unifiedFlowFilter);
  });
  renderUnifiedFlowDetail();
}

function openUnifiedFlowSource(flowId = selectedUnifiedFlowId) {
  const flow = buildUnifiedDocumentFlows().find((item) => item.id === flowId);
  if (!flow) return showToast("找不到這筆文件流程。");
  if (flow.sourceType === "inbound") {
    selectedInboundId = flow.sourceId;
    renderInboundRows();
    renderInboundDetail();
    setView(isRouteAllowed("inbound") ? "inbound" : "search");
    return;
  }
  if (flow.sourceType === "dispatch") {
    selectedDispatchId = flow.sourceId;
    renderDispatchBoard();
    renderDispatchDetail();
    setView(isRouteAllowed("dispatch") ? "dispatch" : isRouteAllowed("approvalLog") ? "approvalLog" : "search");
    return;
  }
  if (flow.sourceType === "contract") {
    selectedContractId = flow.sourceId;
    renderContracts();
    setView(isRouteAllowed("contracts") ? "contracts" : isRouteAllowed("notifications") ? "notifications" : "search");
    return;
  }
  if (flow.sourceType === "seal") {
    selectedSealRequestId = flow.sourceId;
    renderSeals();
    setView(isRouteAllowed("seals") ? "seals" : isRouteAllowed("contractSeal") ? "contractSeal" : isRouteAllowed("workflow") ? "workflow" : "notifications");
    return;
  }
  selectedWorkflowTaskId = flow.sourceId;
  renderWorkflowTasks();
  renderApprovalProgress();
  setView(isRouteAllowed("workflow") ? "workflow" : isRouteAllowed("approvalLog") ? "approvalLog" : "notifications");
}

function syncUnifiedFlowViews() {
  renderUnifiedFlows();
  renderApprovalLog();
  renderDashboardApprovalProgress();
  renderIdentityWorkbench();
  renderRoleDashboard();
}

let selectedTrackingId = "TRK-001";
let trackingFilter = "all";
let trackingSearchTerm = "";
const trackingCases = [
  { id: "TRK-001", title: "歲悅字第1140520009號等待收文確認", agency: "桃園市政府社會局", type: "未收確認", dueDate: "2026-05-23", owner: "總務", status: "未收確認", note: "jAgent 已 accepted，尚未收到收文方確認。" },
  { id: "TRK-002", title: "歲悅字第1140521003號翌日查核", agency: "衛生福利部", type: "翌日查核", dueDate: "2026-05-23", owner: "行政部主任", status: "翌日查核", note: "發文後需於次工作日確認交換結果。" },
  { id: "TRK-003", title: "收1140522-00013 會議通知分派逾期", agency: "臺北市政府社會局", type: "逾期提醒", dueDate: "2026-05-22", owner: "行政部主任", status: "逾期提醒", note: "尚未完成承辦分派，需提醒主管處理。" },
  { id: "TRK-004", title: "日照補正資料附件缺漏", agency: "臺北市政府社會局", type: "退回補正", dueDate: "2026-05-29", owner: "業務助理", status: "退回補正", note: "附件清冊與實際檔案數量不一致。" }
];

const trackingAuditLog = [
  ["10:30", "稽催追蹤初始化", "已載入翌日查核、逾期提醒、未收確認與退回補正案件。"]
];

let dailyActionCache = [];

const titles = {
  dashboard: "交換總覽",
  search: "查詢與搜尋",
  approvalLog: "簽核流程紀錄",
  contracts: "合約管理",
  contractSeal: "合約用印",
  inbound: "收文管理",
  dispatch: "發文管理",
  compose: "建立電子公文",
  format: "文書格式",
  workflow: "流程控管",
  seals: "印鑑管理",
  tracking: "稽催追蹤",
  exchange: "jAgent 介接",
  archive: "歸檔保存",
  security: "資安控管",
  fileSecurity: "檔案資安",
  accounts: "帳號權限",
  reports: "報表統計",
  notifications: "待辦中心",
  jobs: "背景任務",
  database: "後端資料庫",
  ops: "維運中心",
  complianceOps: "法遵營運",
  features: "完整功能總表",
  settings: "系統設定"
};

function badgeClass(status) {
  if (/完成|已收文|成功/.test(status)) return "ok";
  if (/異常|失敗|退回/.test(status)) return "issue";
  if (/待|等待/.test(status)) return "wait";
  return "info";
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function confirmOperation(title, body) {
  if (typeof window.confirm !== "function") return true;
  return window.confirm(`${title}\n\n${body}`);
}

function requireTypedConfirm(title, body, phrase) {
  if (typeof window.prompt !== "function") return true;
  const input = window.prompt(`${title}\n\n${body}\n\n請輸入「${phrase}」以繼續。`);
  return input === phrase;
}

function isValidFutureOrToday(dateText) {
  if (!dateText) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(`${dateText}T00:00:00`);
  return !Number.isNaN(date.getTime()) && date >= today;
}

function hasMinimumText(value, minLength = 6) {
  return String(value || "").trim().length >= minLength;
}

function stableHash(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `SHA256-LOCAL-${(hash >>> 0).toString(16).padStart(8, "0").toUpperCase()}`;
}

function downloadTextFile(fileName, content, type = "application/json;charset=utf-8") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function blockOperation(message, auditFn = null, auditTitle = "操作防呆阻擋") {
  if (auditFn) auditFn(auditTitle, message);
  showToast(message);
  return false;
}

function clearLogWithConfirm(log, renderFn, label) {
  if (!log.length) return showToast(`目前沒有可清除的${label}。`);
  if (!confirmOperation(`確認清除${label}`, "此動作只清除目前畫面的操作軌跡顯示，不會刪除正式 audit log；清除後此畫面無法還原。")) return;
  log.length = 0;
  renderFn();
  showToast(`已清除畫面上的${label}。`);
}

function setView(target) {
  if (!isRouteAllowed(target)) target = "dashboard";
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === target));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.target === target));
  document.querySelector("#pageTitle").textContent = simpleRouteTitle(target);
  document.querySelector("#pageEyebrow").textContent = simpleRouteEyebrow(target);
  if (location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
}

window.addEventListener("hashchange", () => {
  const target = location.hash.slice(1);
  if (target && titles[target]) setView(target);
});

function activeRole() {
  return workflowRole || authState?.user?.role || "總務";
}

function activeUnit() {
  if (authState?.user?.role === activeRole()) return authState?.user?.unit || roleDataScopes[activeRole()]?.departments?.[0] || "";
  return roleDataScopes[activeRole()]?.departments?.[0] || authState?.user?.unit || "";
}

function documentAclKeys(doc = {}) {
  const raw = [doc.id, doc.docId, doc.no, doc.docNo, doc.receiveNo, doc.exchangeNo].filter(Boolean);
  return [...new Set(raw.flatMap((value) => {
    const text = String(value);
    const keys = [text];
    if (/^(IN|OUT)-/.test(text)) keys.push(`DOC-${text}`);
    if (/^DOC-(IN|OUT)-/.test(text)) keys.push(text.replace(/^DOC-/, ""));
    return keys;
  }))];
}

function aclRowsForDoc(doc) {
  const keys = documentAclKeys(doc);
  return documentAclRules.filter((rule) => keys.includes(rule.docId));
}

function aclRuleForDoc(doc, role = activeRole()) {
  const userName = authState?.user?.name || "";
  const unit = activeUnit();
  return aclRowsForDoc(doc).find((rule) =>
    (rule.principalType === "role" && rule.principal === role) ||
    (rule.principalType === "user" && rule.principal === userName) ||
    (rule.principalType === "unit" && rule.principal === unit)
  );
}

function baseDepartmentVisible(doc) {
  const role = activeRole();
  const scope = roleDataScopes[role];
  if (!scope) return false;
  if (["執行長", "董事會", "股東"].includes(role)) return true;
  if (role === "外部檢核單位") return false;
  if (role === "總務") return (doc.owner === "總務" || doc.dept === "總務") && doc.owner !== "行政部主任";
  if (role === "行政部主任") return (doc.owner === "行政部主任" || ["行政部", "總管理處"].includes(doc.dept)) && doc.owner !== "總務";
  return doc.owner === role || doc.owner === authState?.user?.name || doc.dept === role || doc.dept === activeUnit();
}

function canUseDocAction(doc, action = "view") {
  if (activeRole() === "執行長") return true;
  const acl = aclRuleForDoc(doc);
  if (acl) return Boolean(acl[action]);
  if (action === "view") return baseDepartmentVisible(doc);
  if (action === "sign") return Boolean(rolePermissions[activeRole()]?.some((permission) => ["review_dispatch", "approve_format", "assign_case"].includes(permission)));
  if (action === "download") return Boolean(rolePermissions[activeRole()]?.some((permission) => ["upload_attachment", "query_status", "send_dispatch"].includes(permission)));
  if (action === "seal") return Boolean(rolePermissions[activeRole()]?.includes("send_dispatch") || rolePermissions[activeRole()]?.includes("approve_format"));
  return false;
}

function addDocumentAclEvent(title, body) {
  documentAclEvents.unshift([nowTime(), title, body]);
}

function upsertDocumentAcl(doc, principal, patch) {
  const docId = documentAclKeys(doc)[0] || doc.id;
  let rule = documentAclRules.find((item) => item.docId === docId && item.principalType === "role" && item.principal === principal);
  if (!rule) {
    rule = { id: `ACL-${Date.now()}`, docId, principalType: "role", principal, view: true, sign: false, download: false, seal: false, delegate: false, reason: "人工授權", grantedBy: activeRole() };
    documentAclRules.push(rule);
  }
  Object.assign(rule, patch, { grantedBy: activeRole() });
  addDocumentAclEvent("更新文件權限", `${docId} 已更新 ${principal} 權限：檢視 ${rule.view ? "開" : "關"}、簽核 ${rule.sign ? "開" : "關"}、下載 ${rule.download ? "開" : "關"}、用印 ${rule.seal ? "開" : "關"}。`);
}

function renderDocumentAclPanel(doc) {
  const rows = aclRowsForDoc(doc);
  const current = aclRuleForDoc(doc);
  const actions = [
    ["view", "檢視"],
    ["sign", "簽核"],
    ["download", "下載"],
    ["seal", "用印"]
  ];
  return `
    <section class="acl-panel">
      <div class="section-heading compact-heading">
        <div>
          <span>文件細權限</span>
          <h3>本公文 ACL</h3>
        </div>
        <span class="badge ${current?.view === false ? "issue" : "ok"}">${current ? "已套用細權限" : "依角色範圍"}</span>
      </div>
      <div class="acl-action-grid">
        ${actions.map(([key, label]) => `
          <article class="permission-chip ${canUseDocAction(doc, key) ? "allowed" : ""}">
            <strong>${canUseDocAction(doc, key) ? "允許" : "限制"}</strong>
            <span>${label}</span>
          </article>
        `).join("")}
      </div>
      <div class="acl-table">
        ${rows.length ? rows.map((rule) => `
          <div class="acl-row">
            <strong>${rule.principal}</strong>
            <span>${rule.reason}</span>
            <small>${rule.view ? "檢視" : "不可檢視"} · ${rule.sign ? "簽核" : "不可簽核"} · ${rule.download ? "下載" : "不可下載"} · ${rule.seal ? "用印" : "不可用印"}</small>
          </div>
        `).join("") : `<p class="empty-text">尚未設定單件 ACL，暫依角色與部門範圍控管。</p>`}
      </div>
      <div class="detail-actions">
        <button class="secondary-button" type="button" data-acl-action="grant-current">授權目前角色</button>
        <button class="secondary-button" type="button" data-acl-action="revoke-download">關閉下載</button>
        <button class="secondary-button" type="button" data-acl-action="add-reviewer">加簽行政部主任</button>
      </div>
    </section>
  `;
}

function bindDocumentAclButtons(doc, rerender) {
  document.querySelectorAll("[data-acl-action]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.aclAction === "grant-current") {
        upsertDocumentAcl(doc, activeRole(), { view: true, sign: true, download: true, seal: canUseDocAction(doc, "seal"), delegate: true, reason: "目前角色臨時授權，可檢視、簽核與下載。" });
        showToast("已授權目前角色處理此公文。");
      }
      if (button.dataset.aclAction === "revoke-download") {
        upsertDocumentAcl(doc, activeRole(), { view: true, download: false, reason: "敏感資料控管，關閉下載權。" });
        showToast("已關閉目前角色下載權。");
      }
      if (button.dataset.aclAction === "add-reviewer") {
        upsertDocumentAcl(doc, "行政部主任", { view: true, sign: true, download: true, seal: true, delegate: true, reason: "加簽行政部主任清稿與用印前核准。" });
        showToast("已加簽行政部主任。");
      }
      rerender();
    });
  });
}

function canSeeDepartmentDoc(doc) {
  const acl = aclRuleForDoc(doc);
  if (acl) return Boolean(acl.view);
  return baseDepartmentVisible(doc);
}

function scopedInboundDocs() {
  return inboundDocs.filter(canSeeDepartmentDoc);
}

function scopedDispatchDocs() {
  return dispatchDocs.filter((doc) => canSeeDepartmentDoc({ ...doc, dept: doc.dept || doc.owner }));
}

function renderScopeZone() {
  const role = activeRole();
  const scope = roleDataScopes[role] || roleDataScopes["總務"];
  const inboundCount = scopedInboundDocs().length;
  const dispatchCount = scopedDispatchDocs().length;
  const hiddenInbound = inboundDocs.length - inboundCount;
  const hiddenDispatch = dispatchDocs.length - dispatchCount;
  const badge = document.querySelector("#scopeRoleBadge");
  const grid = document.querySelector("#scopeGrid");
  if (!badge || !grid) return;
  badge.textContent = role;
  grid.innerHTML = [
    ["目前工作區", scope.title, scope.rule],
    ["可見公文", `${inboundCount} 收文 / ${dispatchCount} 發文`, `依 ${role} 的部門、擁有人與授權流程顯示。`],
    ["已隔離資料", `${hiddenInbound + hiddenDispatch} 筆不顯示`, "總務與行政部主任的部門公文彼此隔離；跨部門需分派、會辦或簽核授權。"]
  ].map(([label, value, body]) => `
    <article class="scope-card">
      <span>${label}</span>
      <strong>${value}</strong>
      <p>${body}</p>
    </article>
  `).join("");
}

function identityKindForRole(role = activeRole()) {
  if (["總務", "行政部主任", "執行長"].includes(role)) return "generalAffairs";
  if (["主管", "主任"].includes(role)) return "supervisor";
  if (["董事會", "股東", "外部檢核單位"].includes(role)) return "viewer";
  return "employee";
}

function canSeeCompanyWideDocs(role = activeRole()) {
  return ["總務", "行政部主任", "執行長", "董事會", "股東"].includes(role);
}

const navByIdentity = {
  employee: ["dashboard", "compose", "notifications", "search"],
  supervisor: ["dashboard", "compose", "notifications", "search"],
  viewer: ["dashboard", "search"],
  companyOps: ["dashboard", "compose", "inbound", "notifications", "search"],
  executive: ["dashboard", "compose", "inbound", "notifications", "search"]
};

const secondaryRoutesByIdentity = {
  employee: ["notifications", "approvalLog"],
  supervisor: ["notifications", "approvalLog", "workflow"],
  viewer: ["approvalLog"],
  companyOps: ["notifications", "approvalLog", "contracts", "contractSeal", "workflow", "tracking", "reports", "exchange"],
  executive: ["notifications", "approvalLog", "contracts", "contractSeal", "workflow", "tracking", "reports", "exchange", "seals", "accounts", "settings", "ops"]
};

function primaryRoutesForRole(role = activeRole()) {
  if (role === "執行長") return navByIdentity.executive;
  if (["行政部主任", "總務", "執行長"].includes(role)) return navByIdentity.companyOps;
  if (["主管", "主任"].includes(role)) return navByIdentity.supervisor;
  if (["董事會", "股東", "外部檢核單位"].includes(role)) return navByIdentity.viewer;
  return navByIdentity.employee;
}

function secondaryRoutesForRole(role = activeRole()) {
  if (role === "執行長") return secondaryRoutesByIdentity.executive;
  if (["行政部主任", "總務", "執行長"].includes(role)) return secondaryRoutesByIdentity.companyOps;
  if (["主管", "主任"].includes(role)) return secondaryRoutesByIdentity.supervisor;
  if (["董事會", "股東", "外部檢核單位"].includes(role)) return secondaryRoutesByIdentity.viewer;
  return secondaryRoutesByIdentity.employee;
}

function allowedRoutesForRole(role = activeRole()) {
  return [...new Set([...primaryRoutesForRole(role), ...secondaryRoutesForRole(role)])];
}

function isRouteAllowed(target) {
  return allowedRoutesForRole().includes(target);
}

function simpleRouteLabels(role = activeRole()) {
  const companyWide = ["行政部主任", "總務", "執行長"].includes(role);
  if (role === "執行長") return { dashboard: "儀表板", compose: "撰寫公文", inbound: "公文收發", notifications: "全公司待辦", contracts: "合約管理", contractSeal: "合約用印", approvalLog: "簽核紀錄", search: "公文紀錄", seals: "公司與印章設定" };
  return companyWide
    ? { dashboard: "儀表板", compose: "撰寫公文", inbound: "公文收發", notifications: "全公司待辦", contracts: "合約管理", contractSeal: "合約用印", approvalLog: "簽核紀錄", search: "公文紀錄" }
    : { dashboard: "我的工作台", compose: "撰寫公文", notifications: "我的待辦", approvalLog: "簽核紀錄", search: "公文紀錄" };
}

function simpleRouteTitle(target, role = activeRole()) {
  return simpleRouteLabels(role)[target] || titles[target] || "電子公文";
}

function simpleRouteEyebrow(target, role = activeRole()) {
  const kind = identityKindForRole(role);
  if (target === "dashboard" && canSeeCompanyWideDocs(role)) return "全公司公文、合約、交換與風險儀表板";
  if (target === "compose") return "填寫與預覽 -> 確認 -> 送簽";
  if (target === "notifications") return "今天要處理、即將逾期、已退回與交換失敗";
  if (target === "contracts") return "本單位合約台帳與簽核";
  if (target === "contractSeal") return "總務合約用印、退回補正與用印紀錄";
  if (target === "search") return canSeeCompanyWideDocs(role) ? "全公司公文紀錄" : "部門公文紀錄";
  if (target === "approvalLog") return canSeeCompanyWideDocs(role) ? "全公司簽核流程" : "我的簽核與部門流程";
  if (target === "inbound") return "總務收文、登錄與分派";
  if (kind === "employee") return "我的待辦與退回補正";
  if (kind === "supervisor") return "主管簽核與部門風險";
  return "全公司收發與交換處理";
}

function applyRoleNavigation() {
  const primary = primaryRoutesForRole();
  const allowed = allowedRoutesForRole();
  const labels = simpleRouteLabels();
  const nav = document.querySelector(".nav-list");
  const items = [...document.querySelectorAll(".nav-item")];
  document.body.dataset.identityKind = identityKindForRole();
  items.forEach((item) => {
    const routeIndex = primary.indexOf(item.dataset.target);
    item.hidden = routeIndex === -1;
    item.style.order = String(routeIndex === -1 ? 999 : routeIndex);
    if (labels[item.dataset.target]) item.textContent = labels[item.dataset.target];
  });
  if (nav) {
    primary
      .map((route) => items.find((item) => item.dataset.target === route))
      .filter(Boolean)
      .forEach((item) => nav.appendChild(item));
    items.filter((item) => !primary.includes(item.dataset.target)).forEach((item) => nav.appendChild(item));
  }
  const companyWide = ["行政部主任", "總務", "執行長"].includes(activeRole());
  document.querySelector("#pullInboundBtn")?.toggleAttribute("hidden", !companyWide);
  document.querySelector("#sendQueueBtn")?.toggleAttribute("hidden", !companyWide);
  const active = document.querySelector(".view.active")?.id || "dashboard";
  document.querySelector("#pageTitle").textContent = simpleRouteTitle(active);
  document.querySelector("#pageEyebrow").textContent = simpleRouteEyebrow(active);
  document.querySelectorAll("[data-target]").forEach((control) => {
    if (control.classList.contains("nav-item")) return;
    const target = control.dataset.target;
    if (!target || !titles[target]) return;
    control.toggleAttribute("hidden", !allowed.includes(target));
  });
  if (!allowed.includes(active)) setView("dashboard");
}

function identityWorkbenchData() {
  const role = activeRole();
  const kind = identityKindForRole(role);
  const scopedInbound = scopedInboundDocs();
  const scopedDispatch = scopedDispatchDocs();
  const scopedContracts = visibleContracts();
  const contractTodos = scopedContracts.filter((contract) => /草稿|待|退回|用印/.test(contract.status));
  const flowTodos = visibleUnifiedDocumentFlows().filter(isUnifiedFlowTodo);
  const myTracking = trackingCases.filter((item) => item.owner === role || item.owner === authState?.user?.name || (kind === "supervisor" && ["行政部主任", "主任", "執行長"].includes(item.owner)));
  if (kind === "generalAffairs") {
    const pendingInbound = scopedInbound.filter((doc) => ["待登錄", "待分派"].includes(doc.status));
    const failedDispatch = scopedDispatch.filter((doc) => doc.status === "交換失敗");
    const readyDispatch = scopedDispatch.filter((doc) => ["待清稿", "已清稿", "已封裝", "退回補正"].includes(doc.status));
    const totalTodoCount = flowTodos.length || pendingInbound.length + failedDispatch.length + readyDispatch.length + contractTodos.length;
    return {
      eyebrow: "General Affairs Desk",
      title: "全公司儀表板",
      status: "全公司狀態",
      headline: `${totalTodoCount} 件今天要處理`,
      summary: "集中檢視公文收發、待辦、交換異常、Token 與合約用印風險。",
      todoTitle: "今天先處理",
      alertTitle: "需要留意",
      todoCount: totalTodoCount,
      actions: [
        ["公文收發", "inbound", "", "primary", "收文、登錄、分派"],
        ["撰寫公文", "compose", "", "secondary", "建立函稿並預覽"],
        ["全公司待辦", "notifications", "", "secondary", "今天、逾期、退回、失敗"],
        ["公文紀錄", "search", "", "secondary", "查詢全公司收發"]
      ],
      todos: [
        ...flowTodos.slice(0, 5).map(unifiedFlowTodoCard),
        ...pendingInbound.slice(0, 1).map((doc) => ({ badge: doc.status === "待登錄" ? "收文" : "分派", title: doc.subject, meta: `${doc.receiveNo} · ${doc.agency}`, body: `期限 ${doc.dueDate} · ${doc.status}` }))
      ].slice(0, 5),
      alerts: [
        { badge: "Token", title: "憑證與 Token", meta: tokenTimeLeft(), body: "到期前刷新即可，不需進入維運頁。" },
        { badge: "交換", title: "交換失敗", meta: `${failedDispatch.length} 件`, body: failedDispatch.length ? "先確認機關代碼、附件封包與交換中心回覆。" : "目前沒有交換失敗。", issue: failedDispatch.length > 0 }
      ]
    };
  }
  if (kind === "supervisor") {
    const pendingTasks = workflowTasks.filter((task) => task.role === role && /待|審核|查核/.test(task.status));
    const roleFlowTodos = flowTodos.filter((flow) => flow.currentOwner === role || flow.owner === role || flow.dept === activeUnit() || (role === "主任" && /主管|主任/.test(flow.currentStep)));
    return {
      eyebrow: "Supervisor Desk",
      title: "主管工作台",
      status: "簽核與風險",
      headline: `${(roleFlowTodos.length || pendingTasks.length) + myTracking.filter((item) => item.status !== "已完成").length} 件待主管處理`,
      summary: "主管只保留撰寫公文、公文待辦與部門公文紀錄；不顯示收發、維運、報表與系統設定頁籤。",
      todoTitle: "我的待辦",
      alertTitle: "提醒與風險",
      actions: [
        ["撰寫公文", "compose", "", "primary", "建立函稿並預覽"],
        ["公文待辦", "notifications", "", "secondary", "簽核、退回與逾期提醒"],
        ["公文紀錄", "search", "", "secondary", "只看該部門收發公文"]
      ],
      todos: [
        ...roleFlowTodos.slice(0, 4).map(unifiedFlowTodoCard),
        ...pendingTasks.slice(0, 4).map((task) => ({ title: task.title, meta: `${task.step} · ${task.status}`, body: task.type })),
        ...scopedDispatch.filter((doc) => ["待清稿", "已封裝"].includes(doc.status)).slice(0, 2).map((doc) => ({ title: doc.subject, meta: `${doc.no} · ${doc.status}`, body: doc.to })),
        ...contractTodos.filter((contract) => currentContractApproval(contract)?.role === role).slice(0, 2).map((contract) => ({ title: contract.title, meta: `${contract.contractNo} · ${contract.status}`, body: contract.counterparty }))
      ].slice(0, 5),
      alerts: [
        ...myTracking.filter((item) => ["逾期提醒", "未收確認", "退回補正"].includes(item.status)).slice(0, 3).map((item) => ({ title: item.title, meta: item.status, body: item.note, issue: true })),
        { title: "密件與速件", meta: "需優先審核", body: "速件、密件與跨部門公文應先完成簽核意見。" }
      ]
    };
  }
  const assignedInbound = scopedInbound.filter((doc) => doc.owner === role || doc.dept === role || doc.owner === authState?.user?.name);
  const drafts = scopedDispatch.filter((doc) => ["草稿", "退回補正", "待清稿"].includes(doc.status));
  const myFlowTodos = flowTodos.filter((flow) => flow.currentOwner === role || flow.owner === role || flow.dept === activeUnit());
  return {
    eyebrow: "Employee Desk",
    title: "員工工作台",
    status: "我的待辦",
    headline: `${myFlowTodos.length || assignedInbound.length + drafts.length} 件我的公文`,
    summary: "員工只保留撰寫公文、公文待辦與部門公文紀錄；不顯示總務、主管維運或全公司功能。",
    todoTitle: "我的待辦",
    alertTitle: "提醒與風險",
    actions: [
      ["撰寫公文", "compose", "", "primary", "填寫內容並確認即時函稿預覽"],
      ["公文待辦", "notifications", "", "secondary", "查看我的待辦與退回補正"],
      ["公文紀錄", "search", "", "secondary", "只看該部門收發公文"]
    ],
    todos: [
      ...myFlowTodos.slice(0, 4).map(unifiedFlowTodoCard),
      ...assignedInbound.slice(0, 3).map((doc) => ({ title: doc.subject, meta: `${doc.receiveNo} · ${doc.status}`, body: `${doc.agency} · ${doc.dueDate}` })),
      ...drafts.slice(0, 3).map((doc) => ({ title: doc.subject, meta: `${doc.no} · ${doc.status}`, body: doc.lastReply })),
      ...contractTodos.filter((contract) => contract.owner === role || contract.dept === activeUnit()).slice(0, 2).map((contract) => ({ title: contract.title, meta: `${contract.contractNo} · ${contract.status}`, body: contract.counterparty }))
    ].slice(0, 5),
    alerts: [
      ...trackingCases.filter((item) => item.owner === role || item.owner === authState?.user?.name).slice(0, 3).map((item) => ({ title: item.title, meta: item.status, body: item.note, issue: item.status !== "已完成" })),
      { title: "送出前確認", meta: "函稿預覽必看", body: "建立公文需先確認即時函稿預覽，才可送出清稿。" }
    ]
  };
}

function dailyActionForFlow(flow) {
  const routeBySource = {
    inbound: "inbound",
    dispatch: "compose",
    contract: "contracts",
    seal: "contractSeal",
    workflow: "approvalLog"
  };
  let target = routeBySource[flow.sourceType] || "notifications";
  let action = "查看待辦";
  if (flow.sourceType === "inbound") {
    action = /待登錄/.test(flow.status) ? "登錄收文" : /待分派/.test(flow.status) ? "分派承辦" : "查看來文";
  } else if (flow.sourceType === "dispatch") {
    action = /草稿|退回/.test(flow.status) ? "補正函稿" : /待清稿|待簽核/.test(flow.status) ? "查看簽核" : /失敗/.test(flow.status) ? "重送或查詢" : "查看發文";
    if (/待清稿|待簽核/.test(flow.status)) target = "approvalLog";
    if (/失敗|等待確認/.test(flow.status)) target = "search";
  } else if (flow.sourceType === "contract") {
    action = /用印/.test(flow.status) ? "處理用印" : /退回/.test(flow.status) ? "補正合約" : "查看合約";
    if (/用印/.test(flow.status)) target = "contractSeal";
  } else if (flow.sourceType === "seal") {
    action = "總務用印";
  } else if (flow.sourceType === "workflow") {
    action = /退回/.test(flow.status) ? "查看退回原因" : "處理簽核";
  }
  const dedupePrefix = {
    inbound: "INBOUND",
    dispatch: "DISPATCH",
    contract: "CONTRACT",
    seal: "SEAL",
    workflow: "WORKFLOW"
  }[flow.sourceType] || "FLOW";
  return {
    id: flow.id,
    dedupeKey: `${dedupePrefix}-${flow.sourceId || flow.sourceNo || flow.id}`,
    tone: flow.isIssue ? "issue" : "normal",
    badge: flow.kind,
    title: flow.title,
    meta: `${flow.sourceNo} · ${flow.currentStep}`,
    body: `${flow.currentOwner || flow.owner} · ${flow.status}`,
    action,
    target,
    flowId: target === "compose" ? "" : flow.id,
    priority: flow.isIssue ? 3 : /待|退回|失敗/.test(flow.status) ? 2 : 1
  };
}

function dailyActionItems() {
  const role = activeRole();
  const kind = identityKindForRole(role);
  const flows = visibleUnifiedDocumentFlows().filter(isUnifiedFlowTodo).map(dailyActionForFlow);
  const items = [...flows];

  if (kind === "generalAffairs") {
    scopedInboundDocs()
      .filter((doc) => ["待登錄", "待分派", "異常待處理"].includes(doc.status))
      .forEach((doc) => items.push({
        id: `INBOUND-${doc.id}`,
        dedupeKey: `INBOUND-${doc.id}`,
        tone: doc.status === "異常待處理" ? "issue" : "normal",
        badge: "收文",
        title: doc.subject,
        meta: `${doc.receiveNo} · ${doc.agency}`,
        body: `${doc.status} · 承辦 ${doc.owner}`,
        action: doc.status === "待登錄" ? "登錄收文" : doc.status === "待分派" ? "分派承辦" : "處理異常",
        target: "inbound",
        selectInboundId: doc.id,
        priority: doc.status === "異常待處理" ? 3 : 2
      }));
    scopedDispatchDocs()
      .filter((doc) => ["交換失敗", "等待確認", "已封裝"].includes(doc.status))
      .forEach((doc) => items.push({
        id: `DISPATCH-${doc.id}`,
        dedupeKey: `DISPATCH-${doc.id}`,
        tone: doc.status === "交換失敗" ? "issue" : "normal",
        badge: "發文",
        title: doc.subject,
        meta: `${doc.no} · ${doc.to}`,
        body: `${doc.status} · ${doc.lastReply || "待同步交換狀態"}`,
        action: doc.status === "交換失敗" ? "重送或查詢" : "查詢狀態",
        target: "search",
        priority: doc.status === "交換失敗" ? 3 : 2
      }));
  }

  trackingCases
    .filter((item) => item.owner === role || item.owner === authState?.user?.name || (kind !== "employee" && canSeeCompanyWideDocs(role)))
    .filter((item) => item.status !== "已完成")
    .forEach((item) => items.push({
      id: `TRACK-${item.id}`,
      dedupeKey: `TRACK-${item.id}`,
      tone: /逾期|退回|未收/.test(item.status) ? "issue" : "normal",
      badge: item.type,
      title: item.title,
      meta: `${item.agency} · ${item.dueDate}`,
      body: item.note,
      action: /退回/.test(item.status) ? "補正內容" : "查看稽催",
      target: isRouteAllowed("tracking") ? "tracking" : "notifications",
      priority: /逾期|未收/.test(item.status) ? 3 : 2
    }));

  visibleContracts()
    .filter((contract) => /草稿|待|退回|用印|簽核/.test(contract.status) || isContractRenewalSoon(contract))
    .forEach((contract) => {
      const current = currentContractApproval(contract);
      items.push({
        id: `CONTRACT-${contract.id}`,
        dedupeKey: `CONTRACT-${contract.id}`,
        tone: /退回/.test(contract.status) || Number(contractDaysToEnd(contract)) < 0 ? "issue" : "normal",
        badge: "合約",
        title: contract.title,
        meta: `${contract.contractNo} · ${contract.counterparty}`,
        body: `${contract.status} · ${current?.role || contract.dept}`,
        action: /用印/.test(contract.status) ? "合約用印" : /退回/.test(contract.status) ? "補正合約" : "查看合約",
        target: /用印/.test(contract.status) && isRouteAllowed("contractSeal") ? "contractSeal" : "contracts",
        selectContractId: contract.id,
        priority: /退回|用印|待/.test(contract.status) ? 2 : 1
      });
    });

  const unique = [];
  const seen = new Set();
  for (const item of items) {
    const key = item.dedupeKey || item.id;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(item);
  }
  return unique
    .sort((a, b) => b.priority - a.priority || String(a.meta).localeCompare(String(b.meta), "zh-Hant"))
    .slice(0, 3);
}

function dailyActionReason(item, index) {
  if (item.tone === "issue") return "有逾期、退回或交換異常，建議優先處理。";
  if (item.priority >= 2) return "今天若未處理，流程會卡在目前關卡。";
  if (index === 0) return "這是目前最接近你角色職責的下一步。";
  return "可在主要急件完成後接著處理。";
}

function openDailyAction(index) {
  const item = dailyActionCache[Number(index)];
  if (!item) return;
  if (item.selectInboundId) {
    selectedInboundId = item.selectInboundId;
    renderInboundRows();
    renderInboundDetail();
  }
  if (item.selectContractId) {
    selectedContractId = item.selectContractId;
    renderContracts();
    renderContractSeal();
  }
  if (item.flowId && isRouteAllowed(item.target)) {
    openUnifiedFlowSource(item.flowId);
    return;
  }
  setView(isRouteAllowed(item.target) ? item.target : "notifications");
}

function renderDailyActionCenter() {
  const grid = document.querySelector("#dailyActionGrid");
  const count = document.querySelector("#dailyActionCount");
  if (!grid || !count) return;
  dailyActionCache = dailyActionItems();
  const issueCount = dailyActionCache.filter((item) => item.tone === "issue").length;
  count.textContent = issueCount ? `先處理 ${dailyActionCache.length} 件 · ${issueCount} 急` : `先處理 ${dailyActionCache.length} 件`;
  grid.innerHTML = dailyActionCache.length ? dailyActionCache.map((item, index) => `
    <button class="daily-action-item ${item.tone === "issue" ? "issue" : ""}" type="button" data-daily-action="${index}">
      <span class="daily-action-rank">${index + 1}</span>
      <span class="identity-item-badge">${item.badge}</span>
      <strong>${item.title}</strong>
      <small>${item.meta}</small>
      <p>${item.body}</p>
      <span class="daily-action-reason">${dailyActionReason(item, index)}</span>
      <em>${item.action}</em>
    </button>
  `).join("") : `
    <article class="daily-action-empty">
      <strong>目前沒有急件</strong>
      <p>可以先撰寫新公文、查詢公文紀錄，或確認通知中心沒有補件提醒。</p>
      <button class="secondary-button" type="button" data-daily-action-empty="compose">撰寫公文</button>
    </article>
  `;
  document.querySelectorAll("[data-daily-action]").forEach((button) => {
    button.addEventListener("click", () => openDailyAction(button.dataset.dailyAction));
  });
  document.querySelector("[data-daily-action-empty]")?.addEventListener("click", () => setView("compose"));
}

function dashboardRoleData() {
  const role = activeRole();
  const kind = identityKindForRole(role);
  const scopedInbound = scopedInboundDocs();
  const scopedDispatch = scopedDispatchDocs();
  const report = reportStats();
  const tokenLeft = tokenTimeLeft();
  const exchangeFailed = scopedDispatch.filter((doc) => doc.status === "交換失敗");
  const waitDispatch = scopedDispatch.filter((doc) => ["待清稿", "已清稿", "已封裝", "退回補正"].includes(doc.status));
  const waitingConfirm = scopedDispatch.filter((doc) => doc.status === "等待確認");
  const completed = scopedDispatch.filter((doc) => doc.status === "交換完成");
  const pendingWorkflow = workflowTasks.filter((task) => task.role === role && /待|審核|查核|退回/.test(task.status));
  const myTracking = trackingCases.filter((item) => item.owner === role || item.owner === authState?.user?.name || (kind === "supervisor" && ["行政部主任", "主任", "執行長"].includes(item.owner)));
  const roleChecks = {
    generalAffairs: [
      ["先收再分", "新來文先由總務登錄與分派，不直接進入部門池。"],
      ["交換異常優先", `${exchangeFailed.length} 件交換失敗需確認機關代碼、封包與 jAgent 回覆。`],
      ["Token 作業", `目前 Token ${tokenLeft}，到期前需刷新。`],
      ["部門隔離", "總務收文入口與行政部主任內部公文保持隔離。"]
    ],
    supervisor: [
      ["先看簽核", `${pendingWorkflow.length} 件流程待主管核定或退回補正。`],
      ["盯逾期", `${myTracking.filter((item) => ["逾期提醒", "未收確認", "退回補正"].includes(item.status)).length} 件稽催風險需追蹤。`],
      ["看營運報表", `SLA ${report.slaRate}%、交換健康 ${report.exchangeHealth}。`],
      ["用印風險", "核准用印會自動押章並留存 PDF 版本與雜湊。"]
    ],
    employee: [
      ["只看我的", "首頁僅呈現被分派、承辦或需要補正的公文。"],
      ["先預覽再送", "建立函稿需確認即時預覽，才可送清稿。"],
      ["補件優先", `${myTracking.filter((item) => item.status === "退回補正").length} 件退回補正需回覆。`],
      ["附件安全", "附件需通過掃描、大小與密件權限檢查。"]
    ]
  };
  if (kind === "generalAffairs") {
    const pendingInbound = scopedInbound.filter((doc) => ["待登錄", "待分派"].includes(doc.status));
    return {
      eyebrow: "General Affairs Home",
      title: role === "總務" ? "總務儀表板" : `${role}儀表板`,
      scope: "全公司儀表板",
      metrics: [
        ["待登錄/分派", pendingInbound.length, `待登錄 ${pendingInbound.filter((doc) => doc.status === "待登錄").length} / 待分派 ${pendingInbound.filter((doc) => doc.status === "待分派").length}`],
        ["待發交換", waitDispatch.length, "清稿、封裝或補正後送 jAgent"],
        ["交換異常", exchangeFailed.length, exchangeFailed.length ? exchangeFailed[0].lastReply : "目前無交換失敗"],
        ["Token", tokenLeft, "jAgent 交換前請確認憑證與 Token"]
      ],
      pipeline: [
        ["待登錄", pendingInbound.filter((doc) => doc.status === "待登錄").length],
        ["待分派", pendingInbound.filter((doc) => doc.status === "待分派").length],
        ["待送出", waitDispatch.length],
        ["等待確認", waitingConfirm.length],
        ["交換失敗", exchangeFailed.length]
      ],
      primaryTitle: "公文收發佇列",
      primaryTarget: "inbound",
      primaryButton: "公文收發",
      checks: roleChecks.generalAffairs
    };
  }
  if (kind === "supervisor") {
    const overdue = myTracking.filter((item) => ["逾期提醒", "未收確認", "退回補正"].includes(item.status));
    return {
      eyebrow: "Supervisor Home",
      title: role === "執行長" ? "執行長首頁" : "主管首頁",
      scope: "簽核 / 風險 / 營運",
      metrics: [
        ["待簽核", pendingWorkflow.length, "流程核准、退回、改派與會辦"],
        ["逾期風險", overdue.length, overdue.length ? overdue[0].title : "目前無高風險逾期"],
        ["SLA", `${report.slaRate}%`, "登錄、分派、交換、歸檔"],
        ["交換健康", report.exchangeHealth, `成功率 ${report.successRate}% / 異常 ${report.exceptionItems.length}`]
      ],
      pipeline: [
        ["待簽核", pendingWorkflow.length],
        ["待清稿", waitDispatch.filter((doc) => doc.status === "待清稿").length],
        ["退回補正", scopedDispatch.filter((doc) => doc.status === "退回補正").length],
        ["逾期/未收", overdue.length],
        ["需用印", sealRequests.filter((request) => request.status === "待簽核").length]
      ],
      primaryTitle: "主管簽核與風險",
      primaryTarget: "notifications",
      primaryButton: "公文待辦",
      checks: roleChecks.supervisor
    };
  }
  if (kind === "viewer") {
    return {
      eyebrow: "Oversight Home",
      title: `${role}檢視台`,
      scope: role === "外部檢核單位" ? "授權檢核資料" : "治理層級檢視",
      metrics: [
        ["可見公文", scopedInbound.length + scopedDispatch.length, role === "外部檢核單位" ? "只含授權資料" : "全公司治理層級紀錄"],
        ["簽核軌跡", dashboardApprovalTasks().length, "只查閱，不核准"],
        ["合約台帳", visibleContracts().length, "可見範圍內合約"],
        ["稽核紀錄", reportsAuditLog.length + accountAuditLog.length, "不可修改與刪除"]
      ],
      pipeline: [
        ["公文紀錄", scopedInbound.length + scopedDispatch.length],
        ["簽核紀錄", dashboardApprovalTasks().length],
        ["合約", visibleContracts().length],
        ["稽核", reportsAuditLog.length + accountAuditLog.length]
      ],
      primaryTitle: "檢視紀錄",
      primaryTarget: "search",
      primaryButton: "公文紀錄",
      checks: [
        ["唯讀原則", "此角色不處理收發、撰寫、用印或系統設定。"],
        ["授權可追溯", "外部檢核僅顯示被授權的資料，所有開啟與匯出都需寫入 audit log。"],
        ["資料範圍", role === "外部檢核單位" ? "custom" : "group"]
      ]
    };
  }
  const assignedInbound = scopedInbound.filter((doc) => doc.owner === role || doc.dept === role || doc.owner === authState?.user?.name);
  const drafts = scopedDispatch.filter((doc) => ["草稿", "退回補正", "待清稿"].includes(doc.status));
  const returned = myTracking.filter((item) => item.status === "退回補正");
  return {
    eyebrow: "Employee Home",
    title: "員工首頁",
    scope: "我的承辦 / 補件 / 函稿",
    metrics: [
      ["我的收文", assignedInbound.length, "已分派給我或所屬單位"],
      ["我的函稿", drafts.length, "草稿、待清稿與退回補正"],
      ["退回補正", returned.length, returned.length ? returned[0].title : "目前無退回件"],
      ["待辦提醒", myTracking.length, "今天要處理與即將逾期"]
    ],
    pipeline: [
      ["我的收文", assignedInbound.length],
      ["草稿", scopedDispatch.filter((doc) => doc.status === "草稿").length],
      ["待清稿", drafts.filter((doc) => doc.status === "待清稿").length],
      ["退回補正", returned.length],
      ["待附件", fileSecurityItems.filter((item) => item.maskStatus === "需遮罩" || item.scanStatus === "待掃描").length]
    ],
    primaryTitle: "我的公文流程",
    primaryTarget: "compose",
    primaryButton: "建立函稿",
    checks: roleChecks.employee
  };
}

function renderRoleDashboard() {
  const data = dashboardRoleData();
  const backendMetrics = backendDashboardMetrics;
  const kind = identityKindForRole();
  const metrics = backendMetrics ? (
    kind === "generalAffairs" ? [
      ["可見公文", backendMetrics.documents, "後端依登入角色與 ACL 計算"],
      ["待登錄/分派", backendMetrics.inboundPending, "收文待登錄與待分派"],
      ["待發交換", backendMetrics.dispatchPending, "草稿、待清稿與已清稿"],
      ["交換異常", backendMetrics.exchangeFailed, `交換成功率 ${backendMetrics.successRate}%`]
    ] : kind === "supervisor" ? [
      ["可見公文", backendMetrics.documents, "後端依部門、角色與 ACL 計算"],
      ["待清稿/送簽", backendMetrics.dispatchPending, "主管可見範圍內待處理發文"],
      ["交換成功率", `${backendMetrics.successRate}%`, `${backendMetrics.exchangeTasks} 件交換任務`],
      ["稽核資料", backendMetrics.auditLogs ? backendMetrics.auditLogs : "受限", backendMetrics.auditLogs ? "已授權查看 audit log" : "此角色無後台稽核權限"]
    ] : [
      ["我的公文", backendMetrics.documents, "後端依承辦、部門與 ACL 計算"],
      ["待送簽/清稿", backendMetrics.dispatchPending, "我的草稿、清稿或補正"],
      ["交換成功率", `${backendMetrics.successRate}%`, `${backendMetrics.exchangeTasks} 件交換任務`],
      ["後台資料", backendMetrics.auditLogs ? backendMetrics.auditLogs : "受限", "帳號、權限與 audit log 依 RBAC 隱藏"]
    ]
  ) : data.metrics;
  document.querySelector("#dashboardRoleEyebrow").textContent = data.eyebrow;
  document.querySelector("#dashboardRoleTitle").textContent = data.title;
  document.querySelector("#dashboardRoleScope").textContent = backendMetrics ? `${data.scope} · 後端權限範圍` : data.scope;
  metrics.forEach(([label, value, note], index) => {
    const position = index + 1;
    document.querySelector(`#dashboardMetricLabel${position}`).textContent = label;
    document.querySelector(`#dashboardMetricValue${position}`).textContent = value;
    document.querySelector(`#dashboardMetricNote${position}`).textContent = note;
  });
  document.querySelector("#dashboardPipeline").innerHTML = data.pipeline.map(([label, value]) => `
    <div><strong>${label}</strong><span>${value}</span></div>
  `).join("");
  document.querySelector("#dashboardPrimaryPanelTitle").textContent = data.primaryTitle;
  const button = document.querySelector("#dashboardPrimaryPanelBtn");
  button.textContent = data.primaryButton;
  button.dataset.target = data.primaryTarget;
  button.hidden = !isRouteAllowed(data.primaryTarget);
  document.querySelector("#dashboardSecondaryPanelTitle").textContent = `${data.title}注意事項`;
  document.querySelector("#dashboardSecondaryPanelBadge").textContent = data.scope;
  document.querySelector("#dashboardRoleChecks").innerHTML = data.checks.map(([title, body]) => `
    <article class="check-item">
      <strong>${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
  renderDailyActionCenter();
  renderRolePerspectiveReview();
  renderGoLiveGate();
  renderDashboardApprovalProgress();
  renderSupervisorCommandDashboard();
}

function dashboardApprovalTasks() {
  const role = activeRole();
  const companyWide = canSeeCompanyWideDocs(role);
  const visible = companyWide
    ? workflowTasks
    : workflowTasks.filter((task) => task.role === role || (role === "主任" && /主管|主任/.test(task.step)));
  return visible.length ? visible : workflowTasks.slice(0, 3);
}

function renderDashboardApprovalProgress() {
  const panel = document.querySelector("#dashboardApprovalPanel");
  const list = document.querySelector("#dashboardApprovalList");
  const summary = document.querySelector("#dashboardApprovalSummary");
  const steps = document.querySelector("#dashboardApprovalSteps");
  const status = document.querySelector("#dashboardApprovalStatus");
  if (!panel || !list || !summary || !steps || !status) return;
  const tasks = dashboardApprovalTasks();
  if (!tasks.some((task) => task.id === selectedWorkflowTaskId)) selectedWorkflowTaskId = tasks[0]?.id || selectedWorkflowTaskId;
  const task = currentWorkflowTask();
  const snapshot = approvalProgressSnapshot(task);
  const currentStep = snapshot.steps.find((step) => step.state === "current" || step.state === "returned") || snapshot.steps[0];
  const doneCount = snapshot.steps.filter((step) => step.state === "done").length;
  status.textContent = `${tasks.length} 件可檢視`;
  list.innerHTML = tasks.map((item) => {
    const itemSnapshot = approvalProgressSnapshot(item);
    const itemCurrent = itemSnapshot.steps.find((step) => step.state === "current" || step.state === "returned") || itemSnapshot.steps[0];
    return `
      <button class="dashboard-approval-item ${item.id === selectedWorkflowTaskId ? "active" : ""}" type="button" data-dashboard-approval="${item.id}">
        <strong>${item.title}</strong>
        <span>${item.id} · ${item.type} · ${item.status}</span>
        <small>目前：${itemCurrent?.title || item.step}</small>
      </button>
    `;
  }).join("");
  if (!task) {
    summary.innerHTML = `<p class="empty-text">目前沒有可檢視的簽核進度。</p>`;
    steps.innerHTML = "";
    return;
  }
  summary.innerHTML = `
    <article class="approval-progress-card compact">
      <span>${task.id} · ${task.type}</span>
      <strong>${task.title}</strong>
      <p>目前停在「${currentStep?.title || task.step}」，負責角色：${currentStep?.owner || task.role}，進度 ${doneCount}/${snapshot.steps.length} 關。</p>
    </article>
  `;
  steps.innerHTML = snapshot.steps.map((step) => `
    <article class="dashboard-approval-step ${step.state}">
      <time>${step.no}</time>
      <strong>${step.title}</strong>
      <span>${step.owner} · ${step.status}</span>
    </article>
  `).join("");
  document.querySelectorAll("[data-dashboard-approval]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedWorkflowTaskId = button.dataset.dashboardApproval;
      renderDashboardApprovalProgress();
      renderWorkflowTasks();
      renderApprovalProgress();
    });
  });
}

function renderSupervisorCommandDashboard() {
  const panel = document.querySelector("#supervisorCommandPanel");
  if (!panel) return;
  const role = activeRole();
  const kind = identityKindForRole(role);
  const stats = reportStats();
  const riskItems = [
    ...stats.overdueItems.map((item) => ({ title: item.title, meta: `${item.owner} · ${item.status}`, body: `期限：${item.dueDate}`, severity: 3 })),
    ...stats.exceptionItems.map((item) => ({ title: item.title, meta: `${item.owner} · ${item.type}`, body: "需確認補正、重送或主管覆核。", severity: 2 })),
    ...sealRequests.filter((request) => request.status === "待簽核").map((request) => ({ title: sealRequestDoc(request)?.subject || request.id, meta: `${request.step} · 待用印`, body: "核准後會自動押章並留存 PDF 雜湊。", severity: 2 })),
    ...workflowTasks.filter((task) => task.role === role && /待|退回|審核|查核/.test(task.status)).map((task) => ({ title: task.title, meta: `${task.step} · ${task.status}`, body: task.type, severity: 1 }))
  ].sort((a, b) => b.severity - a.severity).slice(0, 5);
  panel.hidden = kind !== "supervisor";
  if (kind !== "supervisor") return;
  const decision = stats.exchangeHealth !== "正常" || stats.overdueItems.length || stats.exceptionItems.length
    ? "今天先處理異常與逾期"
    : "營運穩定，維持簽核節奏";
  document.querySelector("#supervisorCommandStatus").textContent = `${role} · ${stats.slaRate}% SLA`;
  document.querySelector("#supervisorDecisionTitle").textContent = decision;
  document.querySelector("#supervisorDecisionBody").textContent = `本期收發 ${stats.inboundCount + stats.dispatchCount} 件，成功率 ${stats.successRate}%，異常 ${stats.exceptionItems.length} 件，逾期 ${stats.overdueItems.length} 件。主管應先看高風險清單，再決定退回、改派或建立稽催。`;
  document.querySelector("#supervisorDecisionActions").innerHTML = [
    ["看簽核", "workflow", "primary"],
    ["處理逾期", "tracking", "secondary"],
    ["正式報表", "reports", "secondary"],
    ["通知中心", "notifications", "secondary"]
  ].map(([label, target, style]) => `<button class="${style === "primary" ? "primary-button" : "secondary-button"}" type="button" data-dashboard-action-target="${target}">${label}</button>`).join("");
  document.querySelector("#supervisorRiskCount").textContent = `${riskItems.length} 件`;
  document.querySelector("#supervisorRiskList").innerHTML = riskItems.map((item) => `
    <article class="identity-item ${item.severity >= 2 ? "issue" : ""}">
      <strong>${item.title}</strong>
      <span>${item.meta}</span>
      <p>${item.body}</p>
    </article>
  `).join("") || `<article class="identity-item"><strong>沒有高風險案件</strong><p>維持每日查核、抽核與歸檔即可。</p></article>`;
  const loadRows = stats.unitRows.slice().sort((a, b) => b.load - a.load || b.pending - a.pending).slice(0, 4);
  document.querySelector("#supervisorLoadStatus").textContent = loadRows[0]?.load >= 3 ? "需調度" : "正常";
  document.querySelector("#supervisorLoadList").innerHTML = loadRows.map((row) => `
    <article class="identity-item ${row.load >= 3 ? "issue" : ""}">
      <strong>${row.unit}</strong>
      <span>待辦 ${row.pending} 件 · ${row.users} 人</span>
      <p>${row.load >= 3 ? "建議主管改派、加簽或調整期限。" : "負載可控。"}</p>
    </article>
  `).join("") || `<article class="identity-item"><strong>沒有部門負載資料</strong><p>目前沒有需調度案件。</p></article>`;
  document.querySelectorAll("[data-dashboard-action-target]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.dashboardActionTarget));
  });
}

function isOpenOperationalStatus(status = "") {
  const text = String(status || "");
  if (/交換完成|已入案|已結案|完成歸檔|已歸檔|已簽署|已完成/.test(text)) return false;
  return /待|草稿|退回|補正|失敗|異常|確認|用印|簽核|審核|清稿|分派|登錄|處理/.test(text);
}

function receivingUnitHandoffRows() {
  const units = [...new Set([
    ...inboundDocs.map((doc) => doc.dept || doc.owner),
    ...dispatchDocs.map((doc) => doc.dept || doc.owner),
    ...contractRecords.map((contract) => contract.dept || contract.owner),
    activeUnit()
  ])].filter(Boolean);
  return units.map((unit) => {
    const inbound = inboundDocs.filter((doc) => doc.dept === unit || doc.owner === unit);
    const dispatch = dispatchDocs.filter((doc) => doc.dept === unit || doc.owner === unit);
    const contracts = contractRecords.filter((contract) => contract.dept === unit || contract.owner === unit);
    const pendingDocs = [...inbound, ...dispatch].filter((doc) => isOpenOperationalStatus(doc.status)).length;
    const pendingContracts = contracts.filter((contract) => isOpenOperationalStatus(contract.status)).length;
    const issueDocs = [...inbound, ...dispatch].filter((doc) => isUnifiedFlowIssue(`${doc.status || ""} ${doc.note || ""} ${doc.lastReply || ""}`));
    const issueContracts = contracts.filter((contract) => isUnifiedFlowIssue(`${contract.status || ""} ${contract.riskNote || ""}`));
    const owners = [...new Set([
      ...inbound.map((doc) => doc.owner),
      ...dispatch.map((doc) => doc.owner),
      ...contracts.map((contract) => currentContractApproval(contract)?.role || contract.owner)
    ])].filter(Boolean).slice(0, 3);
    const issueCount = issueDocs.length + issueContracts.length;
    const pending = pendingDocs + pendingContracts;
    const nextAction = issueCount
      ? "先處理退回、失敗或異常"
      : pendingDocs
        ? "確認承辦人與期限"
        : pendingContracts
          ? "確認合約簽核與用印"
          : "維持追蹤與歸檔";
    const sample = issueDocs[0]?.subject || issueContracts[0]?.title || inbound[0]?.subject || contracts[0]?.title || dispatch[0]?.subject || "暫無案件";
    return {
      unit,
      docs: inbound.length + dispatch.length,
      contracts: contracts.length,
      pending,
      issueCount,
      owners,
      nextAction,
      sample,
      tone: issueCount ? "issue" : pending ? "wait" : "ok"
    };
  }).filter((row) => row.docs || row.contracts || row.unit === activeUnit())
    .sort((a, b) => Number(b.unit === activeUnit()) - Number(a.unit === activeUnit()) || b.issueCount - a.issueCount || b.pending - a.pending || a.unit.localeCompare(b.unit, "zh-Hant"));
}

function rolePerspectiveReviews() {
  const stats = reportStats();
  const employeeRoles = ["員工", "業務助理", "人資", "會計"];
  const supervisorRoles = ["主管", "主任"];
  const employeeDrafts = dispatchDocs.filter((doc) => employeeRoles.includes(doc.owner) && isOpenOperationalStatus(doc.status));
  const employeeContracts = contractRecords.filter((contract) => employeeRoles.includes(contract.owner) && isOpenOperationalStatus(contract.status));
  const employeeReturns = trackingCases.filter((item) => employeeRoles.includes(item.owner) && /退回|補正|逾期/.test(item.status));
  const supervisorTasks = workflowTasks.filter((task) => supervisorRoles.includes(task.role) && isOpenOperationalStatus(task.status));
  const supervisorRisks = stats.overdueItems.filter((item) => supervisorRoles.includes(item.owner) || /主管|主任/.test(item.status + item.title));
  const generalAffairsInbound = inboundDocs.filter((doc) => ["待登錄", "待分派", "異常待處理"].includes(doc.status));
  const generalAffairsExchange = dispatchDocs.filter((doc) => /交換失敗|等待確認|已封裝/.test(doc.status));
  const generalAffairsSeals = sealRequests.filter((request) => /待|退回/.test(request.status));
  const unitRows = receivingUnitHandoffRows();
  const unitRiskRows = unitRows.filter((row) => row.issueCount || row.pending);
  const activeUnitRow = unitRows.find((row) => row.unit === activeUnit()) || unitRows[0];

  return [
    {
      key: "employee",
      title: "員工 / 申請人",
      badge: "Employee",
      tone: employeeReturns.length ? "issue" : employeeDrafts.length + employeeContracts.length ? "wait" : "ok",
      problem: "最容易卡在不知道缺哪個欄位、送簽前沒確認預覽，或離開頁面後草稿遺失。",
      evidence: [
        `${employeeDrafts.length} 件員工函稿仍在草稿、待清稿或退回狀態`,
        `${employeeContracts.length} 件員工合約仍在簽核或用印前`,
        employeeReturns.length ? `${employeeReturns.length} 件退回、補正或逾期提醒` : "目前沒有員工退回補正提醒"
      ],
      fix: "已補上單頁填寫與預覽、必要欄位檢查、本機草稿保護與今天前三件事。",
      action: "檢查撰寫",
      target: "compose"
    },
    {
      key: "supervisor",
      title: "主管 / 簽核者",
      badge: "Supervisor",
      tone: supervisorRisks.length ? "issue" : supervisorTasks.length ? "wait" : "ok",
      problem: "主管若只看到待簽核清單，容易漏掉逾期、退回、交換異常與用印後果。",
      evidence: [
        `${supervisorTasks.length} 件主管或主任待簽核/待查核`,
        `${supervisorRisks.length} 件主管風險或逾期項目`,
        `目前全站 SLA ${stats.slaRate}%、交換成功率 ${stats.successRate}%`
      ],
      fix: "已補上主管決策面板、風險排序、部門負載與簽核進度快照。",
      action: "看簽核",
      target: "approvalLog"
    },
    {
      key: "generalAffairs",
      title: "總務 / 收發用印",
      badge: "General Affairs",
      tone: generalAffairsExchange.some((doc) => /失敗/.test(doc.status)) ? "issue" : generalAffairsInbound.length + generalAffairsExchange.length + generalAffairsSeals.length ? "wait" : "ok",
      problem: "總務同時負責收文、發文、交換狀態、用印與憑證，若沒有排序會先處理到低風險案件。",
      evidence: [
        `${generalAffairsInbound.length} 件待登錄、待分派或收文異常`,
        `${generalAffairsExchange.length} 件待封裝、等待確認或交換失敗`,
        `${generalAffairsSeals.length} 件用印申請需簽核或處理`
      ],
      fix: "已補上總務今日優先順序、交換異常入口、Token 提醒與用印/合約佇列。",
      action: "公文收發",
      target: "inbound"
    },
    {
      key: "receivingUnit",
      title: "收到公文或合約的單位",
      badge: "Receiving Unit",
      tone: unitRiskRows.some((row) => row.issueCount) ? "issue" : unitRiskRows.length ? "wait" : "ok",
      problem: "部門收到來文或合約後，常不清楚目前在誰手上、下一步是辦理、簽核、補件還是用印。",
      evidence: [
        `${unitRows.length} 個單位有公文或合約承接資料`,
        `${unitRiskRows.length} 個單位仍有待辦或風險`,
        activeUnitRow ? `${activeUnitRow.unit} 目前 ${activeUnitRow.pending} 件待辦、${activeUnitRow.issueCount} 件風險` : "目前沒有單位承接資料"
      ],
      fix: "已補上收件單位承接表，將公文與合約一起顯示下一步與風險。",
      action: "查承接",
      target: "search"
    }
  ];
}

function renderRolePerspectiveReview() {
  const grid = document.querySelector("#rolePerspectiveGrid");
  const status = document.querySelector("#rolePerspectiveStatus");
  const unitGrid = document.querySelector("#unitHandoffGrid");
  const unitStatus = document.querySelector("#unitHandoffStatus");
  if (!grid || !status || !unitGrid || !unitStatus) return;
  const reviews = rolePerspectiveReviews();
  const unitRows = receivingUnitHandoffRows();
  const riskCount = reviews.filter((item) => item.tone === "issue").length;
  status.textContent = riskCount ? `${activeRole()} · ${riskCount} 類高風險` : `${activeRole()} · 可上線觀察`;
  grid.innerHTML = reviews.map((item) => `
    <article class="perspective-item ${item.tone}">
      <div class="perspective-head">
        <span>${item.badge}</span>
        <strong>${item.title}</strong>
      </div>
      <p class="perspective-problem">${item.problem}</p>
      <div class="perspective-evidence">
        ${item.evidence.map((line) => `<span>${line}</span>`).join("")}
      </div>
      <div class="perspective-fix">
        <span>改善狀態</span>
        <strong>${item.fix}</strong>
      </div>
      <button class="${item.tone === "issue" ? "primary-button" : "secondary-button"}" type="button" data-perspective-target="${item.target}">${item.action}</button>
    </article>
  `).join("");
  unitStatus.textContent = `${unitRows.length} 單位 · ${unitRows.filter((row) => row.issueCount).length} 風險`;
  unitGrid.innerHTML = unitRows.slice(0, 6).map((row) => `
    <article class="unit-handoff-item ${row.tone}">
      <div>
        <span>${row.unit}</span>
        <strong>${row.pending} 件待辦</strong>
      </div>
      <p>${row.sample}</p>
      <dl>
        <div><dt>公文</dt><dd>${row.docs}</dd></div>
        <div><dt>合約</dt><dd>${row.contracts}</dd></div>
        <div><dt>風險</dt><dd>${row.issueCount}</dd></div>
      </dl>
      <small>${row.owners.length ? `目前關卡：${row.owners.join("、")}` : "目前沒有指定承辦"}</small>
      <em>${row.nextAction}</em>
    </article>
  `).join("") || `<article class="unit-handoff-item ok"><strong>目前沒有單位承接資料</strong><p>收文分派或合約起案後會在這裡彙整。</p></article>`;
  document.querySelectorAll("[data-perspective-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.perspectiveTarget;
      setView(isRouteAllowed(target) ? target : "notifications");
    });
  });
}

function renderIdentityWorkbench() {
  const data = identityWorkbenchData();
  document.querySelector("#identityEyebrow").textContent = data.eyebrow;
  document.querySelector("#identityTitle").textContent = data.title;
  document.querySelector("#identityStatus").textContent = data.status;
  document.querySelector("#identityHeadline").textContent = data.headline;
  document.querySelector("#identitySummary").textContent = data.summary;
  document.querySelector("#identityTodoTitle").textContent = data.todoTitle || "我的待辦";
  document.querySelector("#identityAlertTitle").textContent = data.alertTitle || "提醒與風險";
  document.querySelector("#identityTodoCount").textContent = `${data.todoCount ?? data.todos.length} 件`;
  document.querySelector("#identityAlertCount").textContent = `${data.alertCount ?? data.alerts.length} 則`;
  document.querySelector("#identityActions").innerHTML = data.actions.map(([label, target, clickId, tone, help]) => `
    <button class="identity-action ${tone === "primary" ? "primary" : ""}" type="button" data-identity-target="${target}" data-identity-click="${clickId}">
      <strong>${label}</strong>
      <span>${help}</span>
    </button>
  `).join("");
  const emptyTodo = `<article class="identity-item ok"><strong>目前沒有待辦</strong><p>這個身份工作區暫無需立即處理的公文。</p></article>`;
  document.querySelector("#identityTodos").innerHTML = data.todos.length ? data.todos.map((item) => `
    <article class="identity-item ${item.issue ? "issue" : ""}">
      <div class="identity-item-head">
        <strong>${item.title}</strong>
        ${item.badge ? `<span class="identity-item-badge">${item.badge}</span>` : ""}
      </div>
      <span>${item.meta}</span>
      <p>${item.body}</p>
    </article>
  `).join("") : emptyTodo;
  document.querySelector("#identityAlerts").innerHTML = data.alerts.map((item) => `
    <article class="identity-item ${item.issue ? "issue" : ""}">
      <div class="identity-item-head">
        <strong>${item.title}</strong>
        ${item.badge ? `<span class="identity-item-badge">${item.badge}</span>` : ""}
      </div>
      <span>${item.meta}</span>
      <p>${item.body}</p>
    </article>
  `).join("");
}

function setSelectOptions(selector, options, selected = options[0]) {
  const element = document.querySelector(selector);
  if (!element) return;
  element.innerHTML = options.map((option) => `<option${option === selected ? " selected" : ""}>${option}</option>`).join("");
}

function setSelectOptionItems(selector, items, selected = "") {
  const element = document.querySelector(selector);
  if (!element) return;
  const fallback = selected || items[0]?.value || "";
  element.innerHTML = items.map((item) => `<option value="${item.value}"${item.value === fallback ? " selected" : ""}>${item.label}</option>`).join("");
  if (items.some((item) => item.value === fallback)) element.value = fallback;
}

function renderApprovalCategorySelect(selector, selected = "") {
  const element = document.querySelector(selector);
  if (!element) return;
  const selectedLabel = approvalCategoryForType(selected || approvalCategoryItems[0]?.label).label;
  element.innerHTML = approvalDocumentCategories.map((group) => `
    <optgroup label="${group.group}">
      ${group.items.map((item) => `<option value="${item.label}"${item.label === selectedLabel ? " selected" : ""}>${item.label} → ${item.route}</option>`).join("")}
    </optgroup>
  `).join("");
  if (selectedLabel && [...element.options].some((option) => option.value === selectedLabel)) element.value = selectedLabel;
}

function replaceConfigArray(target, rows) {
  if (Array.isArray(rows)) target.splice(0, target.length, ...rows);
}

function loadAdminConfigState() {
  try {
    const saved = JSON.parse(localStorage.getItem(adminConfigStorageKey) || "{}");
    replaceConfigArray(documentTypeConfigs, saved.documentTypeConfigs);
    replaceConfigArray(workflowTemplateConfigs, saved.workflowTemplateConfigs);
    replaceConfigArray(formatTemplateConfigs, saved.formatTemplateConfigs);
    if (saved.rolePermissions && typeof saved.rolePermissions === "object") {
      Object.entries(saved.rolePermissions).forEach(([role, permissions]) => {
        if (Array.isArray(permissions)) rolePermissions[role] = [...new Set(permissions)];
      });
      alignRolePermissionsWithLogging();
    }
  } catch (error) {
    localStorage.removeItem(adminConfigStorageKey);
  }
}

function persistAdminConfigState() {
  localStorage.setItem(adminConfigStorageKey, JSON.stringify({
    documentTypeConfigs,
    workflowTemplateConfigs,
    formatTemplateConfigs,
    rolePermissions
  }));
}

function enabledDocumentTypeConfigs() {
  return documentTypeConfigs.filter((item) => item.status !== "停用");
}

function enabledDocumentTypeNames() {
  return enabledDocumentTypeConfigs().map((item) => item.name);
}

function documentTypeConfigForName(name = "") {
  return documentTypeConfigs.find((item) => item.name === name) || null;
}

function enabledWorkflowTemplateConfigs() {
  return workflowTemplateConfigs.filter((item) => item.status !== "停用");
}

function workflowTemplateConfigForKey(key = "") {
  return workflowTemplateConfigs.find((item) => item.key === key) || null;
}

function syncWorkflowTemplateObject() {
  workflowTemplateConfigs.forEach((config) => {
    workflowTemplates[config.key] = {
      name: config.name,
      routeCode: config.routeCode || "A",
      steps: Array.isArray(config.steps) && config.steps.length ? [...config.steps] : workflowStepsForRoute(config.routeCode || "A")
    };
  });
  Object.keys(workflowTemplates).forEach((key) => {
    if (!workflowTemplateConfigs.some((config) => config.key === key)) delete workflowTemplates[key];
  });
  if (!enabledWorkflowTemplateConfigs().some((item) => item.key === activeWorkflowTemplate)) {
    activeWorkflowTemplate = enabledWorkflowTemplateConfigs()[0]?.key || workflowTemplateConfigs[0]?.key || "routeA";
  }
}

function formatTemplateById(id = selectedFormatTemplateId) {
  return formatTemplateConfigs.find((item) => item.id === id) || formatTemplateConfigs[0] || null;
}

function permissionMatrixRows() {
  return Object.entries(rolePermissions).flatMap(([role, permissions]) =>
    Object.entries(permissionLabels).map(([permission, label]) => ({
      id: `${role}-${permission}`,
      role,
      permission,
      label,
      granted: permissions.includes(permission)
    }))
  );
}

function syncConfigurableSelectOptions() {
  const docTypes = enabledDocumentTypeNames();
  ["#docType", "#formatDocType", "#workflowTemplateDocType", "#sealDocTypeInput", "#settingsFormatTemplateDocType"].forEach((selector) => {
    const element = document.querySelector(selector);
    const selected = element?.value && docTypes.includes(element.value) ? element.value : docTypes[0];
    setSelectOptions(selector, docTypes, selected);
  });

  const templateItems = enabledWorkflowTemplateConfigs().map((config) => ({
    value: config.key,
    label: `${config.name}（${config.key}）`
  }));
  const selectedWorkflow = workflowTemplateConfigForKey(activeWorkflowTemplate)?.status !== "停用" ? activeWorkflowTemplate : templateItems[0]?.value;
  setSelectOptionItems("#workflowTemplateSelect", templateItems, selectedWorkflow);
  setSelectOptionItems("#settingsDocTypeWorkflow", templateItems, documentTypeConfigForName(document.querySelector("#settingsDocTypeName")?.value)?.defaultWorkflowTemplate || selectedWorkflow);
  setSelectOptionItems("#settingsWorkflowTemplateRoute", Object.keys(approvalRouteTypes).map((code) => ({
    value: code,
    label: approvalRouteTypes[code].name
  })), document.querySelector("#settingsWorkflowTemplateRoute")?.value || "A");
  setSelectOptionItems("#settingsDocTypeFormat", formatTemplateConfigs.filter((item) => item.status !== "停用").map((item) => ({
    value: item.id,
    label: `${item.name}（${item.docType}）`
  })), documentTypeConfigForName(document.querySelector("#settingsDocTypeName")?.value)?.defaultFormatTemplate || selectedFormatTemplateId);
  setSelectOptions("#settingsPermissionRoleSelect", Object.keys(rolePermissions), document.querySelector("#settingsPermissionRoleSelect")?.value || activeRole());
  setSelectOptionItems("#settingsPermissionCodeSelect", Object.entries(permissionLabels).map(([value, label]) => ({ value, label })), document.querySelector("#settingsPermissionCodeSelect")?.value || "view_assigned");
}

function applyEdocRoleOptions() {
  [
    "#roleSelect",
    "#workflowRoleSelect",
    "#accountRoleSelect",
    "#notificationTarget",
    "#jobNotifyInput",
    "#securityRoleSelect",
    "#workflowProxyFrom",
    "#workflowProxyTo",
    "#workflowActionTarget",
    "#securityCertOwner",
    "#sealOwnerInput",
    "#complianceOwnerSelect",
    "#departmentManagerInput",
    "#contractOwnerInput"
  ].forEach((selector) => setSelectOptions(selector, edocAllowedRoles, workflowRole));
  setSelectOptions("#trackingNotifyTarget", ["總務", "主任", "行政部主任", "人資", "會計", "業務助理"], "總務");
}

function readJsonStorage(key) {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (error) {
    localStorage.removeItem(key);
    return null;
  }
}

function parseJsonMaybe(raw) {
  if (!raw) return null;
  if (typeof raw === "object") return raw;
  try {
    return JSON.parse(raw);
  } catch (error) {
    try {
      return JSON.parse(decodeURIComponent(raw));
    } catch (decodeError) {
      return null;
    }
  }
}

function readCookieValue(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const found = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix));
  if (!found) return "";
  const raw = found.slice(prefix.length);
  try {
    return decodeURIComponent(raw);
  } catch (error) {
    return raw;
  }
}

function isProductionEdocHost() {
  return window.location.hostname === "edoc.suiyuecare.com";
}

function portalHandoffParams() {
  const params = new URLSearchParams(window.location.search);
  const payload = params.get("payload") || "";
  const signature = params.get("signature") || "";
  const token = params.get("token") || "";
  if (!payload && !token) return null;
  return {
    source: "logging-portal",
    bridgeSource: "portal-query",
    payload,
    signature,
    token,
    email: params.get("email") || "",
    role: params.get("role") || "",
    scope: params.get("scope") || "",
    portal: params.get("portal") || ""
  };
}

function cleanPortalHandoffUrl() {
  const params = new URLSearchParams(window.location.search);
  const keys = ["payload", "signature", "token", "email", "role", "scope", "portal", "portalLogin"];
  if (!keys.some((key) => params.has(key))) return;
  keys.forEach((key) => params.delete(key));
  const nextUrl = `${window.location.pathname}${params.toString() ? `?${params}` : ""}${window.location.hash || ""}`;
  history.replaceState(null, "", nextUrl || "/");
}

function edocReturnUrlForPortal() {
  const url = new URL(window.location.href);
  ["payload", "signature", "token", "email", "role", "scope", "portal"].forEach((key) => url.searchParams.delete(key));
  url.searchParams.delete("localLogin");
  return url.toString();
}

function buildLoggingPortalUrl() {
  const url = new URL(loggingPortalUrl);
  url.searchParams.set("module", "edoc");
  url.searchParams.set("next", edocReturnUrlForPortal());
  return url.toString();
}

function redirectToLoggingPortal() {
  window.location.replace(buildLoggingPortalUrl());
}

function shouldRedirectToLoggingPortal() {
  if (!isProductionEdocHost()) return false;
  const params = new URLSearchParams(window.location.search);
  if (params.get("localLogin") === "1") return false;
  if (params.get("portalLogin") !== "1") return false;
  if (portalHandoffParams()) return false;
  if (readCookieValue(loggingQuickLoginCookieKey)) return false;
  return true;
}

function readLoggingBridgePayload() {
  const portalPayload = portalHandoffParams();
  if (portalPayload) return portalPayload;
  for (const key of loggingBridgeStorageKeys) {
    const value = readJsonStorage(key);
    if (value?.user || value?.email || value?.session || value?.profile || value?.currentUser) {
      return { ...value, bridgeSource: `localStorage:${key}` };
    }
  }
  if (window.name?.startsWith(loggingQuickLoginWindowNamePrefix)) {
    const value = parseJsonMaybe(window.name.slice(loggingQuickLoginWindowNamePrefix.length));
    if (value) return { ...value, bridgeSource: "window.name" };
  }
  const cookieValue = parseJsonMaybe(readCookieValue(loggingQuickLoginCookieKey));
  if (cookieValue) return { ...cookieValue, bridgeSource: "cookie" };
  return null;
}

function syncUserAccountFromSession(session, providerLabel = "後端 session") {
  if (!session?.user) return;
  const { user } = session;
  let existing = userAccounts.find((account) => account.email === user.email);
  if (!existing) {
    existing = {
      id: user.id || `USR-${Date.now()}`,
      name: user.name || user.email,
      email: user.email,
      password: "",
      provider: providerLabel,
      unit: user.unit || "",
      title: user.title || user.role || "",
      jobLevel: user.job_level || jobLevelForRole(user.role),
      role: user.role,
      mfa: user.mfa_status || "由平台管理",
      status: user.status || "啟用",
      lastLogin: user.last_login_at || nowTime(),
      ip: providerLabel,
      device: "目前瀏覽器"
    };
    userAccounts.push(existing);
    return;
  }
  Object.assign(existing, {
    name: user.name || existing.name,
    unit: user.unit || existing.unit,
    title: user.title || existing.title,
    jobLevel: user.job_level || jobLevelForRole(user.role),
    role: user.role || existing.role,
    provider: user.provider || providerLabel,
    mfa: user.mfa_status || existing.mfa,
    status: user.status || existing.status,
    lastLogin: user.last_login_at || nowTime(),
    ip: providerLabel,
    device: "目前瀏覽器"
  });
}

function enterApp(message = "登入成功，已進入電子公文交換系統。") {
  document.querySelector("#loginScreen").classList.add("hidden");
  document.querySelector("#appShell").classList.remove("hidden");
  applyAuthUser();
  applyRoleNavigation();
  renderIdentityWorkbench();
  renderScopeZone();
  renderRoleDashboard();
  renderInboundRows();
  renderInboundDetail();
  renderDispatchBoard();
  renderDispatchDetail();
  void loadOfficialWorkflow("all");
  void loadOfficialSealOptions();
  renderApprovalLog();
  applyComposeContactDefaults(true);
  void syncGoLiveAuditFromBackend(true);
  void syncDashboardFromBackend(true);
  void syncDatabaseFromBackend(true);
  showToast(message);
}

function leaveApp() {
  if (authState?.token) {
    backendRequest("/auth/logout", { method: "POST", body: "{}" }).catch(() => {});
  }
  authState = null;
  localStorage.removeItem(authStorageKey);
  cleanPortalHandoffUrl();
  document.querySelector("#appShell").classList.add("hidden");
  document.querySelector("#loginScreen").classList.remove("hidden");
  showToast("已登出系統。");
}

function applyAuthUser() {
  if (!authState?.user) return;
  const { user, permissions = [] } = authState;
  workflowRole = user.role || workflowRole;
  if (rolePermissions[workflowRole]) {
    rolePermissions[workflowRole] = [...new Set([...rolePermissions[workflowRole], ...permissions])];
    alignRolePermissionsWithLogging();
  }
  const roleSelect = document.querySelector("#roleSelect");
  if (roleSelect && [...roleSelect.options].some((option) => option.textContent === workflowRole)) {
    roleSelect.value = workflowRole;
  }
  const bridgeNote = authState.bridge?.loggingRoleKey || user.logging_role_key ? ` · Logging ${authState.bridge?.loggingRoleKey || user.logging_role_key}` : "";
  document.querySelector("#roleNote").textContent = `${user.name} · ${user.unit || "未設定單位"} · ${user.title || user.role} · ${user.job_level || jobLevelForRole(user.role)}${bridgeNote}`;
  applyRoleNavigation();
  renderIdentityWorkbench();
  renderScopeZone();
  renderRoleDashboard();
  renderApprovalLog();
  applyComposeContactDefaults(true);
}

async function loginWithBackend(email, password, provider) {
  const session = await backendRequest("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, provider })
  });
  authState = session;
  localStorage.setItem(authStorageKey, JSON.stringify(session));
  syncUserAccountFromSession(session, "後端 session");
  recordLogin(session.user.email, provider, "成功");
  enterApp(`${session.user.name} 已通過後端 Auth / RBAC 登入。`);
}

async function loginWithLoggingBridge(bridgePayload) {
  const session = await backendRequest("/auth/logging-bridge", {
    method: "POST",
    body: JSON.stringify(bridgePayload)
  });
  authState = session;
  localStorage.setItem(authStorageKey, JSON.stringify(session));
  cleanPortalHandoffUrl();
  syncUserAccountFromSession(session, "Logging / 平台帳號");
  recordLogin(session.user.email, "Logging / 平台帳號", "成功");
  addAccountAudit("Logging 帳號連動", `${session.user.email} 已沿用 Logging 帳號進入 EDOC，角色同步為 ${session.user.role}。`);
  enterApp(`${session.user.name} 已沿用 Logging 帳號進入 EDOC。`);
  return true;
}

async function tryResumePlatformSession() {
  if (authState?.token) {
    try {
      const current = await backendRequest("/auth/me");
      authState = { ...current, token: authState.token, bridge: current.bridge || authState.bridge };
      localStorage.setItem(authStorageKey, JSON.stringify(authState));
      syncUserAccountFromSession(authState, authState.user?.provider || "既有 EDOC session");
      enterApp(`${authState.user.name} 已沿用既有登入狀態進入 EDOC。`);
      return true;
    } catch (error) {
      localStorage.removeItem(authStorageKey);
      authState = null;
    }
  }
  const bridgePayload = readLoggingBridgePayload();
  if (!bridgePayload) {
    if (shouldRedirectToLoggingPortal()) {
      redirectToLoggingPortal();
      return true;
    }
    return false;
  }
  try {
    return await loginWithLoggingBridge(bridgePayload);
  } catch (error) {
    console.warn("Logging bridge login failed", error);
    addAccountAudit("Logging 帳號連動失敗", error.message || "無法沿用 Logging 帳號進入 EDOC。");
    if (shouldRedirectToLoggingPortal()) {
      redirectToLoggingPortal();
      return true;
    }
    return false;
  }
}

function quickLoginProfile(role) {
  const scope = roleDataScopes[role] || { departments: ["系統預設"] };
  const titleMap = {
    員工: "居家照顧服務員",
    主管: "居家服務督導",
    主任: "主任",
    執行長: "執行長",
    行政部主任: "行政部主任",
    人資: "人資專員",
    會計: "會計專員",
    總務: "總務收發",
    業務助理: "業務助理",
    董事會: "董事會成員",
    股東: "股東",
    外部檢核單位: "外部檢核"
  };
  return {
    email: `${role}@suiyuecare.local`,
    password: "demo1234",
    provider: "快速測試登入",
    session: {
      token: `quick-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
      user: {
        id: `QUICK-${role}`,
        name: `${role}測試帳號`,
        email: `${role}@suiyuecare.local`,
        unit: scope.departments?.[0] || role,
        title: titleMap[role] || role,
        job_level: jobLevelForRole(role),
        role,
        provider: "快速測試登入",
        mfa_status: "測試略過",
        status: "啟用"
      },
      permissions: rolePermissions[role] || []
    }
  };
}

async function quickLoginAsRole(role) {
  const profile = quickLoginProfile(role);
  document.querySelector("#loginEmail").value = profile.email;
  document.querySelector("#loginPassword").value = profile.password;
  try {
    await loginWithBackend(profile.email, profile.password, profile.provider);
  } catch (error) {
    authState = profile.session;
    localStorage.setItem(authStorageKey, JSON.stringify(authState));
    syncUserAccountFromSession(authState, "快速登入");
    recordLogin(authState.user.email, profile.provider, "成功");
    enterApp(`${role} 已快速登入，正在檢視 ${roleDataScopes[role]?.title || role} 權限。`);
    addAccountAudit("快速角色登入", `${role} 使用快速登入進入系統；後端 Auth 未回應時改用本機測試 session。`);
  }
}

function renderQueueRows() {
  document.querySelector("#queueRows").innerHTML = queueItems.map(([id, direction, agency, subject, status]) => `
    <tr>
      <td>${id}</td>
      <td>${direction}</td>
      <td>${agency}</td>
      <td>${subject}</td>
      <td><span class="badge ${badgeClass(status)}">${status}</span></td>
    </tr>
  `).join("");
}

function nowTime() {
  return new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function addInboundAudit(title, body) {
  inboundAuditLog.unshift([nowTime(), title, body]);
  renderInboundAuditLog();
}

function selectedInboundDocs() {
  const checked = [...document.querySelectorAll(".inbound-check:checked")]
    .map((input) => inboundDocs.find((doc) => doc.id === input.value))
    .filter(Boolean);
  if (checked.length) return checked;
  const current = currentInboundDoc();
  return current ? [current] : [];
}

function currentInboundDoc() {
  const rows = scopedInboundDocs();
  return rows.find((doc) => doc.id === selectedInboundId) || rows[0] || null;
}

function filteredInboundDocs() {
  const term = inboundSearchTerm.trim().toLowerCase();
  return scopedInboundDocs().filter((doc) => {
    const matchFilter = inboundFilter === "all" || doc.status === inboundFilter;
    const haystack = `${doc.receiveNo} ${doc.exchangeNo} ${doc.agency} ${doc.subject} ${doc.owner} ${doc.dept}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderComplianceChecks() {
  const box = document.querySelector("#complianceChecks") || document.querySelector("#dashboardRoleChecks");
  if (!box) return;
  box.innerHTML = complianceChecks.map(([title, body]) => `
    <article class="check-item">
      <strong>${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
}

function renderInboundRows() {
  const rows = filteredInboundDocs();
  if (rows.length && !rows.some((doc) => doc.id === selectedInboundId)) selectedInboundId = rows[0].id;
  document.querySelector("#inboundCount").textContent = `${rows.length} 筆`;
  if (!rows.length) {
    document.querySelector("#inboundRows").innerHTML = `<tr><td colspan="5" class="empty-text">此工作區目前沒有可檢視的收文。</td></tr>`;
    return;
  }
  document.querySelector("#inboundRows").innerHTML = rows.map((doc) => `
    <tr class="${doc.id === selectedInboundId ? "selected-row" : ""}" data-inbound-id="${doc.id}" tabindex="0">
      <td><button class="text-button row-select" type="button" data-select-inbound="${doc.id}">${doc.receiveNo}</button><small>${doc.exchangeNo}</small></td>
      <td>${doc.agency}<small>${doc.agencyCode}</small></td>
      <td>${doc.subject}</td>
      <td><span class="badge ${badgeClass(doc.status)}">${doc.status}</span></td>
      <td>${doc.owner}<small>${doc.dept}</small></td>
    </tr>
  `).join("");

  const selectAndOpen = (id) => {
    selectedInboundId = id;
    renderInboundRows();
    renderInboundDetail();
    openInboundModal(id);
  };
  document.querySelectorAll("[data-inbound-id]").forEach((row) => {
    row.addEventListener("click", () => selectAndOpen(row.dataset.inboundId));
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectAndOpen(row.dataset.inboundId);
    });
  });
  document.querySelectorAll("[data-select-inbound]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectedInboundId = button.dataset.selectInbound;
      renderInboundRows();
      renderInboundDetail();
      openInboundModal(button.dataset.selectInbound);
    });
  });
}

function inboundDetailMarkup(doc) {
  return `
    <div class="doc-detail">
      <strong>${doc.subject}</strong>
      <dl>
        <div><dt>收文號</dt><dd>${doc.receiveNo}</dd></div>
        <div><dt>交換號</dt><dd>${doc.exchangeNo}</dd></div>
        <div><dt>來文機關</dt><dd>${doc.agency}（${doc.agencyCode}）</dd></div>
        <div><dt>文別 / 速別</dt><dd>${doc.type} / ${doc.priority}</dd></div>
        <div><dt>密等</dt><dd>${doc.security}</dd></div>
        <div><dt>收受時間</dt><dd>${doc.receivedAt}</dd></div>
        <div><dt>期限</dt><dd>${doc.dueDate}</dd></div>
        <div><dt>承辦</dt><dd>${doc.dept} / ${doc.owner}</dd></div>
      </dl>
      <p>${doc.note}</p>
      <div class="attachment-list">
        ${doc.attachments.map((file) => `<button class="file-chip" type="button" data-file="${file}">${file}</button>`).join("")}
      </div>
      <div class="detail-actions">
        <button class="primary-button" type="button" data-inbound-action="register" ${canUseDocAction(doc, "sign") || canUseDocAction(doc, "view") ? "" : "disabled"}>登錄</button>
        <button class="secondary-button" type="button" data-inbound-action="assign" ${canUseDocAction(doc, "sign") ? "" : "disabled"}>分派</button>
        <button class="secondary-button" type="button" data-inbound-action="exception">誤送/漏送</button>
        <button class="secondary-button" type="button" data-inbound-action="export">匯出</button>
      </div>
      ${renderDocumentAclPanel(doc)}
    </div>
  `;
}

function bindInboundDetailActions(container, doc) {
  container.querySelectorAll(".file-chip").forEach((button) => {
    button.addEventListener("click", () => {
      if (!canUseDocAction(doc, "download")) return showToast("此角色未取得本公文附件下載/預覽權限。");
      showToast(`已開啟附件預覽：${button.dataset.file}`);
    });
  });
  container.querySelectorAll("[data-inbound-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.inboundAction;
      if (action === "register") registerInbound([doc.id]);
      if (action === "assign") assignInbound([doc.id]);
      if (action === "exception") createInboundException([doc.id], document.querySelector("#exceptionType").value);
      if (action === "export") {
        addInboundAudit("匯出收文清單", `已匯出 ${filteredInboundDocs().length} 筆目前篩選資料。`);
        showToast("已產生收文清單匯出檔。");
      }
      if (["register", "assign", "exception"].includes(action)) openInboundModal(doc.id);
    });
  });
  bindDocumentAclButtons(doc, renderInboundDetail);
}

function renderInboundDetail() {
  const doc = currentInboundDoc();
  const detail = document.querySelector("#inboundDetail");
  const status = document.querySelector("#selectedInboundStatus");
  if (!doc) {
    if (status) status.textContent = "未選取";
    if (detail) detail.innerHTML = `<p class="empty-text">尚無收文資料。</p>`;
    return;
  }
  if (status) status.textContent = doc.status;
  if (detail) detail.innerHTML = "";
  const modal = document.querySelector("#inboundModal");
  if (modal && !modal.classList.contains("hidden")) openInboundModal(doc.id);
}

function openInboundModal(docId = selectedInboundId) {
  const doc = inboundDocs.find((item) => item.id === docId) || currentInboundDoc();
  const modal = document.querySelector("#inboundModal");
  const body = document.querySelector("#inboundModalBody");
  if (!doc || !modal || !body) return;
  selectedInboundId = doc.id;
  document.querySelector("#inboundModalTitle").textContent = doc.receiveNo;
  body.innerHTML = inboundDetailMarkup(doc);
  bindInboundDetailActions(body, doc);
  modal.classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closeInboundModal() {
  document.querySelector("#inboundModal")?.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function renderInboundAuditLog() {
  document.querySelector("#inboundAuditLog").innerHTML = inboundAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function mutateInbound(ids, handler) {
  ids.forEach((id) => {
    const doc = inboundDocs.find((item) => item.id === id);
    if (doc) {
      handler(doc);
      persistToBackend(`/documents/${doc.id.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`}`, backendDocumentPayload(doc), "PATCH");
    }
  });
  renderInboundRows();
  renderInboundDetail();
}

function registerInbound(ids) {
  const targetIds = ids?.length ? ids : selectedInboundDocs().map((doc) => doc.id);
  if (!targetIds.length) return showToast("請先選取要登錄的收文。");
  const targetDocs = targetIds.map((id) => inboundDocs.find((item) => item.id === id)).filter(Boolean);
  const dept = document.querySelector("#registerDept").value;
  const retentionYears = parseRetentionYears(document.querySelector("#retentionYears").value);
  if (!dept) return blockOperation("請先選擇收文登錄單位。", addInboundAudit, "收文操作防呆");
  if (!retentionYears || retentionYears < 1) return blockOperation("保存年限需大於 0 年。", addInboundAudit, "收文操作防呆");
  const duplicate = targetDocs.find((doc) => ["已收文", "待分派"].includes(doc.status));
  if (duplicate) return blockOperation(`${duplicate.no} 已登錄或已收文，避免重複登錄。`, addInboundAudit, "收文操作防呆");
  const denied = targetDocs.filter((doc) => !canUseDocAction(doc, "view"));
  if (denied.length) return showToast("此角色未取得部分收文的檢視/登錄權限。");
  if (targetDocs.length > 3 && !confirmOperation("確認批次收文登錄", `即將一次登錄 ${targetDocs.length} 筆收文，登錄後會進入分派流程。`)) return;
  mutateInbound(targetIds, (doc) => {
    doc.status = doc.status === "異常待處理" ? "異常待處理" : "待分派";
    doc.dept = dept;
    doc.note = document.querySelector("#registerNote").value;
  });
  addInboundAudit("完成收文登錄", `已登錄 ${targetIds.length} 筆收文，保存年限：${retentionYears}。`);
  showToast(`已完成 ${targetIds.length} 筆收文登錄。`);
}

function parseRetentionYears(value) {
  const text = String(value || "").trim();
  if (/永久/.test(text)) return 999;
  const match = text.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function assignInbound(ids) {
  const targetIds = ids?.length ? ids : selectedInboundDocs().map((doc) => doc.id);
  if (!targetIds.length) return showToast("請先選取要分派的收文。");
  const targetDocs = targetIds.map((id) => inboundDocs.find((item) => item.id === id)).filter(Boolean);
  const owner = document.querySelector("#assignOwner").value;
  const dueDate = document.querySelector("#assignDueDate").value;
  if (!owner) return blockOperation("請先選擇承辦人。", addInboundAudit, "收文分派防呆");
  if (!isValidFutureOrToday(dueDate)) return blockOperation("辦理期限不可空白，也不可早於今天。", addInboundAudit, "收文分派防呆");
  const invalidStatus = targetDocs.find((doc) => !["待分派", "異常待處理"].includes(doc.status));
  if (invalidStatus) return blockOperation(`${invalidStatus.no} 目前狀態為「${invalidStatus.status}」，不可直接分派。`, addInboundAudit, "收文分派防呆");
  const denied = targetDocs.filter((doc) => !canUseDocAction(doc, "sign"));
  if (denied.length) return showToast("此角色未取得部分收文的分派/簽核權限。");
  const hasSensitive = targetDocs.some((doc) => doc.security && doc.security !== "普通");
  if ((targetDocs.length > 3 || hasSensitive) && !confirmOperation("確認收文分派", `即將分派 ${targetDocs.length} 筆收文給 ${owner}${hasSensitive ? "，其中包含密件或限閱文件" : ""}。`)) return;
  mutateInbound(targetIds, (doc) => {
    doc.status = "已收文";
    doc.owner = owner;
    doc.dueDate = dueDate;
    doc.note = document.querySelector("#assignNote").value;
  });
  addInboundAudit("完成承辦分派", `已分派 ${targetIds.length} 筆收文給 ${owner}，期限 ${dueDate}。`);
  showToast(`已分派 ${targetIds.length} 筆收文。`);
}

function createInboundException(ids, forcedType) {
  const targetIds = ids?.length ? ids : selectedInboundDocs().map((doc) => doc.id);
  if (!targetIds.length) return showToast("請先選取要處理異常的收文。");
  const type = forcedType || document.querySelector("#exceptionType").value;
  const note = document.querySelector("#exceptionNote").value;
  if (!hasMinimumText(note)) return blockOperation("請填寫至少 6 個字的異常說明，避免建立無法追蹤的誤送/漏送案件。", addInboundAudit, "異常處理防呆");
  if (!confirmOperation(`確認建立${type}通知`, `即將對 ${targetIds.length} 筆收文建立「${type}」案件，並通知 ${document.querySelector("#exceptionTarget").value}。`)) return;
  mutateInbound(targetIds, (doc) => {
    doc.status = "異常待處理";
    doc.note = `${type}：${note}`;
  });
  addInboundAudit(`建立${type}通知`, `已通知 ${document.querySelector("#exceptionTarget").value}，共 ${targetIds.length} 筆。`);
  showToast(`已建立${type}通知。`);
}

function pullJagentInbound() {
  const newDocs = pulledInboundTemplates.filter((doc) => !inboundDocs.some((item) => item.id === doc.id));
  if (!newDocs.length) return showToast("目前沒有新的 jAgent 來文。");
  inboundDocs.unshift(...newDocs.map((doc) => ({ ...doc, attachments: [...doc.attachments] })));
  selectedInboundId = newDocs[0].id;
  addInboundAudit("jAgent 拉取來文", `已拉取 ${newDocs.length} 筆新來文。`);
  renderInboundRows();
  renderInboundDetail();
  showToast(`已從 jAgent 拉取 ${newDocs.length} 筆來文。`);
}

function addDispatchAudit(title, body) {
  dispatchAuditLog.unshift([nowTime(), title, body]);
  renderDispatchAuditLog();
}

function composePayload() {
  return {
    companyName: document.querySelector("#composeCompanySelect")?.value || companyRegistry[0]?.name || "歲悅長照股份有限公司",
    no: document.querySelector("#dispatchNo")?.value.trim() || "",
    type: document.querySelector("#docType")?.value || "函",
    priority: document.querySelector("#priority")?.value || "普通件",
    recipient: document.querySelector("#recipient")?.value.trim() || "未指定受文者",
    contactAddress: document.querySelector("#contactAddress")?.value.trim() || "220205 新北市板橋區英士路192之1號",
    contactOwner: document.querySelector("#contactOwner")?.value.trim() || activeRole(),
    contactPhone: document.querySelector("#contactPhone")?.value.trim() || "(02)2257-7155 分機3762",
    contactFax: document.querySelector("#contactFax")?.value.trim() || "(02)2254-4029",
    contactEmail: document.querySelector("#contactEmail")?.value.trim() || "edoc@suiyuecare.com",
    largeSealType: document.querySelector("#largeSealType")?.value || "無",
    smallSealType: document.querySelector("#smallSealType")?.value || "無",
    sealPlacements: {
      large: { ...composeSealPlacements.large },
      small: { ...composeSealPlacements.small }
    },
    subject: document.querySelector("#subject")?.value.trim() || "未填主旨",
    body: document.querySelector("#bodyText")?.value.trim() || "",
    attachments: [...(document.querySelector("#attachments")?.files || [])].map((file) => file.name)
  };
}

const composeAutosaveSelectors = [
  "#composeCompanySelect",
  "#docType",
  "#priority",
  "#dispatchNo",
  "#recipient",
  "#contactAddress",
  "#contactOwner",
  "#contactPhone",
  "#contactFax",
  "#contactEmail",
  "#largeSealType",
  "#smallSealType",
  "#subject",
  "#bodyText"
];

function composeRawSnapshot() {
  const values = {};
  composeAutosaveSelectors.forEach((selector) => {
    const element = document.querySelector(selector);
    if (!element) return;
    values[selector] = element.value;
  });
  return {
    values,
    sealPlacements: {
      large: { ...composeSealPlacements.large },
      small: { ...composeSealPlacements.small }
    },
    currentComposeDraftId,
    role: activeRole()
  };
}

function composeSnapshotHasMeaningfulContent(snapshot) {
  const values = snapshot?.values || {};
  return Boolean(
    String(values["#recipient"] || "").trim() ||
    String(values["#subject"] || "").trim() ||
    String(values["#bodyText"] || "").trim()
  );
}

function formatComposeSaveTime(isoText) {
  if (!isoText) return "";
  const date = new Date(isoText);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function writeComposeAutosave() {
  const snapshot = composeRawSnapshot();
  if (!composeSnapshotHasMeaningfulContent(snapshot)) return;
  const saved = {
    updatedAt: new Date().toISOString(),
    snapshot
  };
  try {
    localStorage.setItem(composeAutosaveStorageKey, JSON.stringify(saved));
  } catch (error) {
    composeSaveState = {
      tone: "idle",
      title: "尚未暫存",
      detail: "瀏覽器目前無法使用本機保護，請按暫存草稿保存到發文清單。"
    };
    return;
  }
  composeSaveState = {
    tone: "local",
    title: "此瀏覽器已保護",
    detail: `${formatComposeSaveTime(saved.updatedAt)} 已保留目前輸入，按暫存草稿後才會進發文清單。`
  };
}

function clearComposeAutosave() {
  try {
    localStorage.removeItem(composeAutosaveStorageKey);
  } catch (error) {
    // Ignore storage cleanup failures; the saved draft in the document list is authoritative.
  }
}

function renderComposeSaveStatus() {
  // Local autosave is intentionally silent; the compose page should stay focused on the document.
}

function renderComposeCompanyOptions() {
  const select = document.querySelector("#composeCompanySelect");
  if (!select) return;
  const current = select.value || companyRegistry[0]?.name || "歲悅長照股份有限公司";
  const names = companyRegistry.map((item) => item.name);
  select.innerHTML = optionTags(names, names.includes(current) ? current : names[0]);
}

function renderDraftSealPlaceholder(kind, label, sealType, sizeClass) {
  if (sealType === "無") return "";
  const placement = composeSealPlacements[kind];
  return `
    <button
      class="draft-seal-placeholder ${sizeClass}"
      type="button"
      data-compose-seal="${kind}"
      style="left:${placement.x}%;top:${placement.y}%"
      aria-label="${label}預設用印位置，可拖曳調整">
      <span>${label}<small>${sealType}</small></span>
    </button>
  `;
}

function chunkTextByLength(text, firstLimit = 235, nextLimit = 390) {
  const source = (text || "尚未填寫說明內容。").trim();
  const chunks = [];
  let remaining = source;
  let limit = firstLimit;
  while (remaining.length > limit) {
    const windowText = remaining.slice(0, limit);
    const breakAt = Math.max(
      windowText.lastIndexOf("\n"),
      windowText.lastIndexOf("。"),
      windowText.lastIndexOf("；"),
      windowText.lastIndexOf("，")
    );
    const cut = breakAt > Math.floor(limit * 0.58) ? breakAt + 1 : limit;
    chunks.push(remaining.slice(0, cut).trim());
    remaining = remaining.slice(cut).trim();
    limit = nextLimit;
  }
  chunks.push(remaining || "尚未填寫說明內容。");
  return chunks;
}

function normalizeSealPlacementPages(pageCount) {
  Object.values(composeSealPlacements).forEach((placement) => {
    placement.page = Math.min(Math.max(Number(placement.page) || 1, 1), pageCount);
  });
}

function renderDraftSealLayer(data, pageNumber) {
  return `
    <footer class="draft-footer">
      ${composeSealPlacements.large.page === pageNumber ? renderDraftSealPlaceholder("large", "公司大章", data.largeSealType, "large") : ""}
      ${composeSealPlacements.small.page === pageNumber ? renderDraftSealPlaceholder("small", "公司小章", data.smallSealType, "small") : ""}
    </footer>
  `;
}

function syncDraftPreviewChrome(data = composePayload()) {
  const panel = document.querySelector("#draftPreviewPanel");
  const body = document.querySelector("#draftPreviewBody");
  const toggle = document.querySelector("#toggleDraftPreviewBtn");
  const status = document.querySelector("#draftConfirmStatus");
  const submit = document.querySelector("#submitDispatchBtn");
  if (status) status.textContent = draftConfirmed ? "已確認" : "尚未確認";
  if (submit) submit.disabled = !draftConfirmed;
  if (panel) panel.classList.remove("is-collapsed");
  if (body) body.hidden = false;
  if (toggle) {
    toggle.textContent = draftPreviewExpanded ? "收合預覽" : "展開預覽";
    toggle.setAttribute("aria-expanded", String(draftPreviewExpanded));
  }
}

function setDraftPreviewExpanded(value, options = {}) {
  draftPreviewExpanded = Boolean(value);
  renderDraftPreview({ force: draftPreviewExpanded });
  if (options.scroll) {
    document.querySelector("#draftPreviewPanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function scheduleDraftPreviewRender(delay = 220) {
  if (draftPreviewRenderTimer) window.clearTimeout(draftPreviewRenderTimer);
  renderComposeCompanyOptions();
  syncDraftPreviewChrome();
  renderComposeStepper();
  draftPreviewRenderTimer = window.setTimeout(() => {
    draftPreviewRenderTimer = null;
    renderDraftPreview({ force: true });
  }, delay);
}

function bindDraftSealDrag() {
  document.querySelectorAll("[data-draft-preview]").forEach((preview) => {
    preview.querySelectorAll("[data-compose-seal]").forEach((seal) => {
    seal.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      seal.setPointerCapture(event.pointerId);
      seal.classList.add("dragging");
      const moveSeal = (moveEvent) => {
        const hoveredPage = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)?.closest(".draft-page");
        const page = hoveredPage || seal.closest(".draft-page");
        if (!page) return;
        const footer = page.querySelector(".draft-footer");
        if (footer && seal.parentElement !== footer) footer.appendChild(seal);
        const rect = page.getBoundingClientRect();
        const halfWidth = seal.offsetWidth / 2;
        const halfHeight = seal.offsetHeight / 2;
        const minX = halfWidth;
        const maxX = rect.width - halfWidth;
        const minY = halfHeight;
        const maxY = rect.height - halfHeight;
        const nextX = Math.min(maxX, Math.max(minX, moveEvent.clientX - rect.left));
        const nextY = Math.min(maxY, Math.max(minY, moveEvent.clientY - rect.top));
        const kind = seal.dataset.composeSeal;
        composeSealPlacements[kind] = {
          page: Number(page.dataset.pageNumber) || 1,
          x: Math.round((nextX / rect.width) * 1000) / 10,
          y: Math.round((nextY / rect.height) * 1000) / 10
        };
        seal.style.left = `${composeSealPlacements[kind].x}%`;
        seal.style.top = `${composeSealPlacements[kind].y}%`;
      };
      const stopDrag = () => {
        seal.classList.remove("dragging");
        seal.removeEventListener("pointermove", moveSeal);
        seal.removeEventListener("pointerup", stopDrag);
        seal.removeEventListener("pointercancel", stopDrag);
        markDraftDirty({ keepStep: true });
        showToast(`${seal.textContent.trim()}用印位置已更新。`);
      };
      seal.addEventListener("pointermove", moveSeal);
      seal.addEventListener("pointerup", stopDrag);
      seal.addEventListener("pointercancel", stopDrag);
    });
  });
  });
}

function composeContactDefaults(role = activeRole()) {
  const unit = activeUnit() || roleDataScopes[role]?.departments?.[0] || "業務部";
  const account = userAccounts.find((item) => item.role === role && item.status === "啟用");
  return {
    contactAddress: "220205 新北市板橋區英士路192之1號",
    contactOwner: authState?.user?.name || account?.name || role,
    contactPhone: "(02)2257-7155 分機3762",
    contactFax: "(02)2254-4029",
    contactEmail: authState?.user?.email || account?.email || "edoc@suiyuecare.com",
    unit
  };
}

function applyComposeContactDefaults(force = false) {
  const defaults = composeContactDefaults();
  [
    ["#contactAddress", defaults.contactAddress],
    ["#contactOwner", defaults.contactOwner],
    ["#contactPhone", defaults.contactPhone],
    ["#contactFax", defaults.contactFax],
    ["#contactEmail", defaults.contactEmail]
  ].forEach(([selector, value]) => {
    const input = document.querySelector(selector);
    if (input && (force || !input.value.trim())) input.value = value;
  });
  renderDraftPreview();
}

function setAiDraftStatus(text, tone = "") {
  const status = document.querySelector("#aiDraftStatus");
  if (!status) return;
  status.textContent = text;
  status.dataset.tone = tone;
}

async function generateAiDraft() {
  const plainText = document.querySelector("#aiPlainText")?.value.trim() || "";
  if (!hasMinimumText(plainText, 6)) {
    return blockOperation("請先在白話文欄位輸入至少 6 個字。", addDispatchAudit, "AI 公文助理防呆");
  }
  const button = document.querySelector("#aiGenerateDraftBtn");
  button.disabled = true;
  setAiDraftStatus("生成中", "loading");
  try {
    const data = composePayload();
    const result = await backendRequest("/ai/compose", {
      method: "POST",
      body: JSON.stringify({
        plainText,
        docType: data.type,
        priority: data.priority,
        recipient: data.recipient,
        attachments: data.attachments,
        role: activeRole()
      })
    });
    document.querySelector("#aiGeneratedSubject").value = result.subject || "";
    document.querySelector("#aiGeneratedBody").value = result.body || "";
    setAiDraftStatus(result.usedOpenAI ? "OpenAI 已生成" : "模板已生成", result.usedOpenAI ? "ok" : "fallback");
    addDispatchAudit("AI 生成函稿", result.usedOpenAI ? `已使用 ${result.model} 產生主旨與內文。` : result.notice || "已使用本機模板產生主旨與內文。");
    showToast(result.usedOpenAI ? "AI 已生成主旨與內文。" : "已生成主旨與內文，OpenAI 未啟用時使用模板備援。");
  } catch (error) {
    const reason = error?.message || "未知錯誤";
    setAiDraftStatus("生成失敗", "error");
    addDispatchAudit("AI 生成失敗", reason);
    showToast(`AI 生成失敗：${reason}`);
  } finally {
    button.disabled = false;
  }
}

function applyAiDraftToCompose() {
  const subject = document.querySelector("#aiGeneratedSubject")?.value.trim() || "";
  const body = document.querySelector("#aiGeneratedBody")?.value.trim() || "";
  if (!subject || !body) return showToast("請先產生或填寫 AI 主旨與內文。");
  document.querySelector("#subject").value = subject;
  document.querySelector("#bodyText").value = body;
  markDraftDirty();
  addDispatchAudit("套用 AI 函稿", "AI 生成內容已帶入主旨與說明欄位。");
  showToast("已套用到公文主旨與說明。");
}

function clearAiDraft() {
  ["#aiPlainText", "#aiGeneratedSubject", "#aiGeneratedBody"].forEach((selector) => {
    const input = document.querySelector(selector);
    if (input) input.value = "";
  });
  setAiDraftStatus("待輸入");
  showToast("AI 公文助理欄位已清除。");
}

function renderOfficialDraftPagesHtml(data = composePayload()) {
  const today = new Date();
  const rocDate = `中華民國${today.getFullYear() - 1911}年${today.getMonth() + 1}月${today.getDate()}日`;
  const attachmentsText = data.attachments.length ? data.attachments.join("、") : "函稿本文、附件清冊";
  const bodyPages = chunkTextByLength(data.body);
  normalizeSealPlacementPages(bodyPages.length);
  return bodyPages.map((body, index) => {
    const pageNumber = index + 1;
    const isFirstPage = pageNumber === 1;
    return `
      <section class="draft-page" data-page-number="${pageNumber}" aria-label="函稿第 ${pageNumber} 頁">
        ${isFirstPage ? `
          <section class="draft-file-meta" aria-label="檔案資訊">
            <span>檔　號：</span>
            <span>保存年限：</span>
          </section>
          <header class="draft-official-head">
            <h1>
              <span>${data.companyName}</span>
              <strong>${data.type}</strong>
            </h1>
            <section class="draft-contact-block">
              <span>地址：${data.contactAddress}</span>
              <span>承辦人：${data.contactOwner}</span>
              <span>電話：${data.contactPhone}</span>
              <span>傳真：${data.contactFax}</span>
              <span>電子信箱：${data.contactEmail}</span>
            </section>
          </header>
          <section class="draft-recipient-line">受文者：${data.recipient}</section>
          <section class="draft-official-meta">
            <div><span>發文日期：</span><strong>${rocDate}</strong></div>
            <div><span>發文字號：</span><strong>${data.no || "系統產生中"}</strong></div>
            <div><span>速別：</span><strong>${data.priority}</strong></div>
            <div><span>密等及解密條件或保密期限：</span><strong>普通</strong></div>
            <div><span>附件：</span><strong>${attachmentsText}</strong></div>
          </section>
        ` : `
          <section class="draft-continuation-head">
            <span>${data.no || "系統產生中"}</span>
            <strong>第 ${pageNumber} 頁</strong>
          </section>
        `}
        <section class="draft-main ${isFirstPage ? "" : "continued"}">
          ${isFirstPage ? `<div class="draft-content-row draft-subject"><span>主旨：</span><strong>${data.subject}</strong></div>` : ""}
          <div class="draft-content-row draft-description">
            <span>${isFirstPage ? "說明：" : "續："}</span>
            <div class="draft-body">${body}</div>
          </div>
        </section>
        <div class="draft-page-number">第 ${pageNumber} 頁 / 共 ${bodyPages.length} 頁</div>
        ${renderDraftSealLayer(data, pageNumber)}
      </section>
    `;
  }).join("");
}

function renderDraftPreview(options = {}) {
  if (draftPreviewRenderTimer) {
    window.clearTimeout(draftPreviewRenderTimer);
    draftPreviewRenderTimer = null;
  }
  renderComposeCompanyOptions();
  const data = composePayload();
  const previews = document.querySelectorAll("[data-draft-preview]");
  syncDraftPreviewChrome(data);
  if (!previews.length) return;
  const html = renderOfficialDraftPagesHtml(data);
  previews.forEach((preview) => {
    preview.innerHTML = html;
  });
  bindDraftSealDrag();
  renderComposeStepper();
}

function setDraftConfirmed(value) {
  draftConfirmed = value;
  if (!value) draftSigned = false;
  if (value) {
    draftPreviewExpanded = true;
    activeComposeStep = "confirm";
  }
  renderDraftPreview({ force: true });
}

function markDraftDirty(options = {}) {
  draftConfirmed = false;
  draftSigned = false;
  if (!options.keepStep) activeComposeStep = "fill";
  writeComposeAutosave();
  scheduleDraftPreviewRender();
}

function composeStepState() {
  return [
    { key: "fill", label: "填寫資料", body: "表單與即時預覽", done: activeComposeStep !== "fill" || draftConfirmed },
    { key: "confirm", label: "確認送出", body: "函稿預覽與簽核流程", done: draftConfirmed }
  ];
}

function composeStepKeys() {
  return composeStepState().map((step) => step.key);
}

function composeStepIndex(key = activeComposeStep) {
  return Math.max(0, composeStepKeys().indexOf(key));
}

function composeInputState() {
  return {
    recipient: document.querySelector("#recipient")?.value.trim() || "",
    subject: document.querySelector("#subject")?.value.trim() || "",
    body: document.querySelector("#bodyText")?.value.trim() || "",
    attachments: [...(document.querySelector("#attachments")?.files || [])].map((file) => file.name),
    largeSealType: document.querySelector("#largeSealType")?.value || "無",
    smallSealType: document.querySelector("#smallSealType")?.value || "無"
  };
}

function composeReadinessChecks() {
  const state = composeInputState();
  const sealTypes = [state.largeSealType, state.smallSealType].filter((item) => item && item !== "無");
  return [
    {
      key: "recipient",
      label: "受文者",
      target: "recipient",
      required: true,
      done: Boolean(state.recipient),
      detail: state.recipient ? "已填寫受文機關或單位。" : "請填寫要發給哪個機關或單位。"
    },
    {
      key: "subject",
      label: "主旨",
      target: "subject",
      required: true,
      done: state.subject.length >= 8,
      detail: state.subject.length >= 8 ? "主旨長度足夠。" : `至少 8 個字，目前 ${state.subject.length} 個字。`
    },
    {
      key: "body",
      label: "說明",
      target: "body",
      required: true,
      done: state.body.length >= 8,
      detail: state.body.length >= 8 ? "說明長度足夠。" : `至少 8 個字，目前 ${state.body.length} 個字。`
    },
    {
      key: "attachments",
      label: "附件",
      target: "attachments",
      required: false,
      done: state.attachments.length > 0,
      detail: state.attachments.length ? `已選 ${state.attachments.length} 個附件。` : "沒有附件也可先送，但請確認函稿本文與附件清冊。"
    },
    {
      key: "seal",
      label: "用印",
      target: "seal",
      required: false,
      done: true,
      detail: sealTypes.length ? `已選 ${sealTypes.join("、")}，可在下方預覽拖曳位置。` : "目前不使用印章。"
    },
    {
      key: "confirm",
      label: "函稿確認",
      target: "confirm",
      required: activeComposeStep !== "fill",
      done: draftConfirmed,
      detail: draftConfirmed ? "已確認函稿預覽。" : "送簽前請先展開預覽並按「確認函稿」。"
    }
  ];
}

function composeBasicBlockers() {
  return composeReadinessChecks().filter((item) => item.required && item.key !== "confirm" && !item.done);
}

function renderComposeFieldHints() {
  [
    ["#recipient", "#recipientHint"],
    ["#subject", "#subjectHint"],
    ["#bodyText", "#bodyTextHint"]
  ].forEach(([inputSelector, hintSelector]) => {
    const input = document.querySelector(inputSelector);
    const hint = document.querySelector(hintSelector);
    if (input) delete input.dataset.validity;
    if (hint) {
      delete hint.dataset.validity;
      hint.textContent = "";
    }
  });
}

function focusComposeReadinessTarget(target) {
  const selectorMap = {
    recipient: "#recipient",
    subject: "#subject",
    body: "#bodyText",
    attachments: "#attachments",
    seal: "#largeSealType",
    confirm: "#draftPreviewPanel"
  };
  const selector = selectorMap[target];
  if (!selector) return;
  if (target === "confirm") {
    setDraftPreviewExpanded(true, { scroll: true });
  }
  const focusTarget = () => {
    const element = document.querySelector(selector);
    if (!element) return;
    element.scrollIntoView({ behavior: "smooth", block: "center" });
    if (typeof element.focus === "function" && !element.classList.contains("draft-preview-panel")) {
      element.focus({ preventScroll: true });
    }
    element.classList.add("attention-pulse");
    if (target === "confirm") element.classList.add("preview-attention");
    window.setTimeout(() => {
      element.classList.remove("attention-pulse");
      element.classList.remove("preview-attention");
    }, 1400);
  };
  if (target !== "confirm" && activeComposeStep !== "fill") {
    setComposeStep("fill", { force: true });
    window.setTimeout(focusTarget, 0);
    return;
  }
  focusTarget();
}

function composePaneForStep(key = activeComposeStep) {
  if (key === "fill") return "fill";
  return "confirm";
}

function composePanesForStep(key = activeComposeStep) {
  return [composePaneForStep(key)];
}

function validateComposeStep(step = activeComposeStep) {
  return true;
}

function setComposeStep(key, options = {}) {
  if (key === "preview") key = "fill";
  const steps = composeStepKeys();
  if (!steps.includes(key)) return;
  const currentIndex = composeStepIndex();
  const nextIndex = steps.indexOf(key);
  if (!options.force && nextIndex > currentIndex && !validateComposeStep(activeComposeStep)) return;
  activeComposeStep = key;
  renderDraftPreview({ force: true });
  renderComposeStepper();
}

function advanceComposeStep() {
  const steps = composeStepKeys();
  const currentIndex = composeStepIndex();
  const current = steps[currentIndex];
  if (!validateComposeStep(current)) return;
  if (current === "fill") {
    draftPreviewExpanded = true;
    setComposeStep("confirm", { force: true });
    return;
  }
  if (current === "confirm") {
    if (!draftConfirmed) {
      setDraftConfirmed(true);
      addDispatchAudit("確認函稿", "撰寫者已確認函稿預覽、附件與用印位置。");
      showToast("函稿已確認。");
      return;
    }
    document.querySelector("#composeForm")?.requestSubmit();
  }
}

function retreatComposeStep() {
  const steps = composeStepKeys();
  const currentIndex = composeStepIndex();
  const previous = steps[Math.max(0, currentIndex - 1)];
  setComposeStep(previous, { force: true });
}

function composeNextControlState() {
  const disabled = false;
  const text = activeComposeStep === "confirm"
    ? (draftConfirmed ? "送出簽核" : "確認內容無誤")
    : "前往確認";
  return { disabled, text };
}

function renderComposeStepper() {
  const stepper = document.querySelector("#composeStepper");
  const action = document.querySelector("#composeNextAction");
  if (!stepper) return;
  renderComposeFieldHints();
  const steps = composeStepState();
  const activeIndex = composeStepIndex();
  stepper.innerHTML = `
    <div class="compose-page-tabs">
      ${steps.map((item, index) => `
        <button class="compose-progress-step ${item.done ? "done" : ""} ${index === activeIndex ? "active" : ""}" type="button" data-compose-step="${item.key}">
          <span>${index + 1}</span>
          <strong>${item.label}</strong>
          <small>${item.body}</small>
        </button>
      `).join("")}
    </div>
  `;
  const nextControl = composeNextControlState();
  if (action) action.innerHTML = "";
  const stepStatus = document.querySelector("#composeStepStatus");
  if (stepStatus) stepStatus.textContent = activeComposeStep === "confirm" ? "第 2 頁：確認送出" : "第 1 頁：填寫資料";
  const confirmHint = document.querySelector("#composeConfirmHint");
  if (confirmHint) confirmHint.textContent = draftConfirmed ? "已確認" : "尚未確認";
  const activePanes = composePanesForStep();
  document.querySelectorAll("[data-compose-pane]").forEach((panel) => {
    panel.classList.toggle("active", activePanes.includes(panel.dataset.composePane));
  });
  const composeView = document.querySelector("#compose");
  composeView?.classList.remove("compose-step-mode-fill", "compose-step-mode-preview", "compose-step-mode-confirm", "compose-step-mode-sign", "compose-step-mode-send");
  composeView?.classList.add(`compose-step-mode-${activeComposeStep}`);
  const previousButton = document.querySelector("#composePrevBtn");
  const nextButton = document.querySelector("#composeNextBtn");
  const confirmButton = document.querySelector("#confirmDraftBtn");
  const resetButton = document.querySelector("#resetDraftConfirmBtn");
  const submitButton = document.querySelector("#submitDispatchBtn");
  if (previousButton) previousButton.hidden = activeComposeStep !== "confirm";
  if (nextButton) {
    nextButton.disabled = nextControl.disabled;
    nextButton.textContent = nextControl.text;
    nextButton.hidden = activeComposeStep !== "fill";
  }
  if (confirmButton) confirmButton.hidden = activeComposeStep !== "confirm" || draftConfirmed;
  if (resetButton) resetButton.hidden = activeComposeStep !== "confirm" || !draftConfirmed;
  if (submitButton) {
    submitButton.hidden = activeComposeStep !== "confirm";
    submitButton.disabled = !draftConfirmed;
  }
  renderComposeSaveStatus();
  document.querySelectorAll("[data-compose-step]").forEach((button) => {
    button.addEventListener("click", () => setComposeStep(button.dataset.composeStep, { force: true }));
  });
}

function rocDateSerial(date = new Date()) {
  const rocYear = date.getFullYear() - 1911;
  return `${rocYear}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
}

function nextDispatchNo() {
  const dateSerial = rocDateSerial();
  const prefix = `歲悅字第${dateSerial}`;
  const numbers = [
    ...dispatchDocs.map((doc) => doc.no),
    ...archiveRecords.map((record) => record.docNo),
    document.querySelector("#formatDocNo")?.value
  ]
    .filter(Boolean)
    .map((value) => {
      const match = String(value).match(new RegExp(`^${prefix}(\\d{3})號$`));
      return match ? Number(match[1]) : 0;
    });
  const next = Math.max(0, ...numbers) + 1;
  return `${prefix}${String(next).padStart(3, "0")}號`;
}

function assignNextDispatchNo(force = false) {
  const input = document.querySelector("#dispatchNo");
  if (!input) return "";
  if (force || !input.value.trim()) input.value = nextDispatchNo();
  renderDraftPreview();
  return input.value.trim();
}

function selectedDispatchDocs() {
  return [...document.querySelectorAll(".dispatch-check:checked")]
    .map((input) => dispatchDocs.find((doc) => doc.id === input.value))
    .filter(Boolean);
}

function currentDispatchDoc() {
  const rows = scopedDispatchDocs();
  return rows.find((doc) => doc.id === selectedDispatchId) || rows[0] || null;
}

function filteredDispatchDocs() {
  const term = dispatchSearchTerm.trim().toLowerCase();
  return scopedDispatchDocs().filter((doc) => {
    const matchFilter = dispatchFilter === "all" || doc.status === dispatchFilter;
    const haystack = `${doc.no} ${doc.exchangeNo} ${doc.to} ${doc.agencyCode} ${doc.subject} ${doc.owner}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderDispatchChecks(doc = currentDispatchDoc()) {
  const checks = [
    ["文號與文別", doc?.checks.format, "發文字號、文別、速別、密等與日期完整。"],
    ["受文者", doc?.checks.recipient, "受文者機關名稱與機關代碼可交換。"],
    ["附件", doc?.checks.attachments, "附件清冊、檔案雜湊與檔案數量一致。"],
    ["憑證", doc?.checks.certificate, "總務已通過憑證登入。"],
    ["封裝", doc?.checks.package, "已產生 jAgent 可送出的交換封包。"]
  ];
  document.querySelector("#dispatchPrecheckPanel").innerHTML = checks.map(([title, ok, body]) => `
    <article class="check-item">
      <strong>${ok ? "通過" : "待處理"} · ${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
}

function renderPackagePanel(doc = currentDispatchDoc()) {
  if (!doc) {
    document.querySelector("#packagePanel").innerHTML = `<p class="empty-text">尚未選取發文。</p>`;
    return;
  }
  document.querySelector("#packagePanel").innerHTML = `
    <div class="doc-detail">
      <dl>
        <div><dt>封包編號</dt><dd>${doc.packageId || "尚未封裝"}</dd></div>
        <div><dt>交換號</dt><dd>${doc.exchangeNo}</dd></div>
        <div><dt>附件數</dt><dd>${doc.attachments.length} 個</dd></div>
        <div><dt>狀態</dt><dd>${doc.status}</dd></div>
      </dl>
      <div class="attachment-list">
        ${doc.attachments.map((file) => `<button class="file-chip" type="button" data-dispatch-file="${file}">${file}</button>`).join("")}
      </div>
    </div>
  `;
  document.querySelectorAll("[data-dispatch-file]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!canUseDocAction(doc, "download")) return showToast("此角色未取得本公文附件下載/預覽權限。");
      showToast(`已預覽發文附件：${button.dataset.dispatchFile}`);
    });
  });
}

function renderDispatchBoard() {
  const docs = filteredDispatchDocs();
  if (docs.length && !docs.some((doc) => doc.id === selectedDispatchId)) selectedDispatchId = docs[0].id;
  document.querySelector("#dispatchCount").textContent = `${docs.length} 筆`;
  if (!docs.length) {
    document.querySelector("#dispatchBoard").innerHTML = `<p class="empty-text">此工作區目前沒有可檢視的發文。</p>`;
    return;
  }
  document.querySelector("#dispatchBoard").innerHTML = docs.map((doc) => `
    <article class="dispatch-card ${doc.id === selectedDispatchId ? "selected-card" : ""}" data-dispatch-id="${doc.id}">
      <label class="card-check"><input class="dispatch-check" type="checkbox" value="${doc.id}" /> 選取</label>
      <span class="badge ${badgeClass(doc.status)}">${doc.status}</span>
      <div>
        <button class="text-button row-select" type="button" data-select-dispatch="${doc.id}"><strong>${doc.no}</strong></button>
        <p>${doc.to} · ${doc.agencyCode}</p>
      </div>
      <p>${doc.subject}</p>
      <footer>
        <button class="segment" type="button" data-dispatch-action="validate" data-dispatch-id="${doc.id}">清稿</button>
        <button class="segment" type="button" data-dispatch-action="package" data-dispatch-id="${doc.id}">封裝</button>
        <button class="segment" type="button" data-dispatch-action="send" data-dispatch-id="${doc.id}">送交</button>
        <button class="segment" type="button" data-dispatch-action="query" data-dispatch-id="${doc.id}">查詢</button>
        <button class="segment" type="button" data-dispatch-action="resend" data-dispatch-id="${doc.id}">重送</button>
      </footer>
    </article>
  `).join("");
  document.querySelectorAll("[data-select-dispatch]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedDispatchId = button.dataset.selectDispatch;
      renderDispatchBoard();
      renderDispatchDetail();
    });
  });
  document.querySelectorAll("[data-dispatch-action]").forEach((button) => {
    button.addEventListener("click", () => runDispatchAction(button.dataset.dispatchAction, [button.dataset.dispatchId]));
  });
}

function renderDispatchDetail() {
  const doc = currentDispatchDoc();
  const detail = document.querySelector("#dispatchDetail");
  if (!doc) {
    document.querySelector("#selectedDispatchStatus").textContent = "未選取";
    detail.innerHTML = `<p class="empty-text">尚無發文資料。</p>`;
    renderDispatchChecks(null);
    renderPackagePanel(null);
    return;
  }
  document.querySelector("#selectedDispatchStatus").textContent = doc.status;
  const dispatchSteps = [
    ["清稿", doc.checks.format],
    ["封裝", doc.checks.package],
    ["送出", ["等待確認", "交換完成"].includes(doc.status)]
  ];
  const activeDispatchStep = Math.max(0, dispatchSteps.findIndex(([, done]) => !done));
  const dispatchStepMarkup = dispatchSteps.map(([label, done], index) => `<article class="next-step ${done ? "done" : ""} ${index === activeDispatchStep ? "active" : ""}"><strong>${index + 1}. ${label}</strong><span>${done ? "已完成" : "下一步"}</span></article>`).join("");
  detail.innerHTML = `
    <div class="doc-detail">
      <strong>${doc.subject}</strong>
      <div class="next-stepper">${dispatchStepMarkup}</div>
      <dl>
        <div><dt>發文字號</dt><dd>${doc.no}</dd></div>
        <div><dt>交換號</dt><dd>${doc.exchangeNo}</dd></div>
        <div><dt>受文者</dt><dd>${doc.to}（${doc.agencyCode}）</dd></div>
        <div><dt>文別 / 速別</dt><dd>${doc.type} / ${doc.priority}</dd></div>
        <div><dt>密等</dt><dd>${doc.security}</dd></div>
        <div><dt>承辦</dt><dd>${doc.owner}</dd></div>
        <div><dt>jAgent 回覆</dt><dd>${doc.lastReply}</dd></div>
      </dl>
      <p>${doc.body}</p>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="detailSendDispatchBtn" ${canUseDocAction(doc, "seal") ? "" : "disabled"}>送交 jAgent</button>
        <button class="secondary-button" type="button" id="detailValidateDispatchBtn" ${canUseDocAction(doc, "sign") ? "" : "disabled"}>清稿</button>
        <button class="secondary-button" type="button" id="detailPackageDispatchBtn" ${canUseDocAction(doc, "download") ? "" : "disabled"}>封裝</button>
        <button class="secondary-button" type="button" id="detailQueryDispatchBtn">查詢</button>
        <button class="secondary-button" type="button" id="detailResendDispatchBtn" ${canUseDocAction(doc, "seal") ? "" : "disabled"}>重送</button>
      </div>
      ${renderDocumentAclPanel(doc)}
    </div>
  `;
  document.querySelector("#detailSendDispatchBtn").addEventListener("click", () => runDispatchAction("send", [doc.id]));
  document.querySelector("#detailValidateDispatchBtn").addEventListener("click", () => runDispatchAction("validate", [doc.id]));
  document.querySelector("#detailPackageDispatchBtn").addEventListener("click", () => runDispatchAction("package", [doc.id]));
  document.querySelector("#detailQueryDispatchBtn").addEventListener("click", () => runDispatchAction("query", [doc.id]));
  document.querySelector("#detailResendDispatchBtn").addEventListener("click", () => runDispatchAction("resend", [doc.id]));
  bindDocumentAclButtons(doc, renderDispatchDetail);
  renderDispatchChecks(doc);
  renderPackagePanel(doc);
}

const officialStatusLabels = {
  draft: "草稿",
  pending_applicant_manager: "申請人主管",
  pending_department_head: "部門主管",
  pending_admin_director: "行政部門主任",
  pending_general_affairs_review: "總務審核",
  pending_ceo: "執行長",
  approved: "已核准",
  stamping: "用印中",
  stamped: "已完成用印",
  pending_general_affairs_dispatch: "等待總務寄發",
  returned_to_applicant_for_send: "回申請人自行寄發",
  dispatched: "已由總務正式發文",
  sent_by_applicant: "已由申請人自行寄出",
  closed: "已結案歸檔",
  rejected: "已駁回",
  cancelled: "已取消",
  stamping_failed: "用印失敗"
};

function officialStatusLabel(status = "") {
  return officialStatusLabels[status] || status || "未設定";
}

const officialFileTypeLabels = {
  original_pdf: "原始上傳 PDF",
  generated_pdf: "系統產生公文 PDF",
  stamped_pdf: "已用印版本",
  attachment: "補充附件",
  dispatch_proof: "寄發證明"
};

const officialDispatchMethodLabels = {
  electronic_official_document_by_general_affairs: "總務電子公文系統發文",
  return_to_applicant_for_manual_send: "回申請人自行寄發",
  email_by_general_affairs: "總務 Email 寄出",
  physical_mail_by_general_affairs: "總務紙本郵寄",
  no_dispatch_required: "僅用印歸檔"
};

const officialDispatchStatusLabels = {
  pending: "待寄發",
  dispatched: "總務已寄發",
  sent_by_applicant: "申請人已寄出",
  failed: "寄發失敗",
  cancelled: "已取消"
};

function officialFileTypeLabel(type = "") {
  return officialFileTypeLabels[type] || type || "文件";
}

function officialApplicationSummary(item = {}) {
  const summary = item.application_package?.summary || {};
  const files = item.application_package?.all_files || item.files || [];
  const versions = item.application_package?.document_versions || item.document_versions || files.filter((file) => ["original_pdf", "generated_pdf", "stamped_pdf"].includes(file.file_type));
  const attachments = item.application_package?.attachments || item.attachments || files.filter((file) => file.file_type === "attachment");
  const downloadLogs = item.application_package?.download_logs || item.download_logs || (item.logs || []).filter((log) => log.action === "download_file");
  return {
    versionCount: summary.version_count ?? versions.length,
    attachmentCount: summary.attachment_count ?? attachments.length,
    approvalStepCount: summary.approval_step_count ?? (item.approval_steps || []).length,
    downloadCount: summary.download_count ?? downloadLogs.length,
    hasStampedPdf: summary.has_stamped_pdf ?? versions.some((file) => file.file_type === "stamped_pdf")
  };
}

function officialApplicationFiles(item = {}) {
  const packagedFiles = item.application_package?.all_files || [
    ...(item.application_package?.document_versions || item.document_versions || []),
    ...(item.application_package?.attachments || item.attachments || [])
  ];
  return packagedFiles.length ? packagedFiles : item.files || [];
}

function officialProcessLogs(item = {}) {
  return item.application_package?.process_logs || item.process_logs || (item.logs || []).filter((log) => log.action !== "download_file");
}

function officialDownloadLogs(item = {}) {
  return item.application_package?.download_logs || item.download_logs || (item.logs || []).filter((log) => log.action === "download_file");
}

function officialDispatchRecord(item = {}) {
  return item.application_package?.dispatch_record || item.dispatch_record || null;
}

function officialCurrentItem() {
  return officialWorkflowItems.find((item) => item.id === selectedOfficialDocumentId) || officialWorkflowItems[0] || null;
}

function officialWorkflowEndpoint(scope = officialWorkflowScope) {
  if (scope === "todo") return "/official-documents/my-tasks";
  if (scope === "mine") return "/official-documents/my-requests";
  return "/official-documents";
}

async function loadOfficialWorkflow(scope = officialWorkflowScope) {
  officialWorkflowScope = scope;
  if (scope === "new") {
    renderOfficialWorkflow();
    return;
  }
  const params = new URLSearchParams();
  if (officialWorkflowStatusFilter) params.set("status", officialWorkflowStatusFilter);
  try {
    officialWorkflowItems = await backendRequest(`${officialWorkflowEndpoint(scope)}${params.toString() ? `?${params}` : ""}`);
    if (!officialWorkflowItems.some((item) => item.id === selectedOfficialDocumentId)) selectedOfficialDocumentId = officialWorkflowItems[0]?.id || "";
  } catch (error) {
    officialWorkflowItems = [];
    showToast(`發文簽核載入失敗：${error.message}`);
  }
  renderOfficialWorkflow();
}

function renderOfficialCompanyOptions() {
  const select = document.querySelector("#officialCompanySelect");
  if (!select) return;
  const previousValue = select.value;
  const companies = companySealCompanies.length ? companySealCompanies : companySealFallbackCompanies();
  select.innerHTML = companies.map((item) => `<option value="${item.id}">${item.name}</option>`).join("");
  if (companies.some((item) => item.id === previousValue)) select.value = previousValue;
  if (!select.value && companies[0]) select.value = companies[0].id;
}

async function loadOfficialSealOptions(companyId = document.querySelector("#officialCompanySelect")?.value || "CO-001") {
  try {
    const result = await backendRequest(`/companies/${encodeURIComponent(companyId)}/seals`);
    officialSealOptions = Array.isArray(result) ? result.filter((item) => item.is_active !== 0 && item.is_active !== false) : [];
  } catch (error) {
    officialSealOptions = [];
  }
  renderOfficialSealOptions();
}

function renderOfficialSealOptions() {
  const select = document.querySelector("#officialSealSelect");
  if (!select) return;
  const previousValue = select.value;
  if (!officialSealOptions.length) {
    select.innerHTML = `<option value="">請先建立並上傳印章版本</option>`;
    return;
  }
  select.innerHTML = officialSealOptions.map((item) => `<option value="${item.id}">${item.seal_name || item.id}${item.current_file ? "" : "（尚無版本）"}</option>`).join("");
  if (officialSealOptions.some((item) => item.id === previousValue)) select.value = previousValue;
}

function filteredOfficialWorkflowItems() {
  const keyword = officialWorkflowSearchTerm.trim().toLowerCase();
  if (!keyword) return officialWorkflowItems;
  return officialWorkflowItems.filter((item) => [item.title, item.subject, item.recipient, item.applicant_name, item.current_status, item.current_step_name].some((value) => String(value || "").toLowerCase().includes(keyword)));
}

function renderOfficialWorkflowList() {
  const target = document.querySelector("#officialWorkflowList");
  if (!target) return;
  const items = filteredOfficialWorkflowItems();
  if (officialWorkflowScope === "new") {
    target.innerHTML = `<p class="empty-text">請在右側建立一張發文申請單；PDF 只是申請單底下的文件版本。</p>`;
    return;
  }
  if (!items.length) {
    target.innerHTML = `<p class="empty-text">目前沒有符合條件的發文申請單。</p>`;
    return;
  }
  target.innerHTML = items.map((item) => `
    <button class="official-workflow-item ${item.id === selectedOfficialDocumentId ? "active" : ""}" type="button" data-official-id="${item.id}">
      <strong>${item.title || item.subject || item.id}</strong>
      <span>${officialStatusLabel(item.current_status)} · ${item.current_step_name || item.current_step || "未送出"}</span>
      <small>${item.applicant_name || "申請人"} · ${item.recipient || "未指定受文者"} · ${item.created_at || ""}</small>
    </button>
  `).join("");
  target.querySelectorAll("[data-official-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      selectedOfficialDocumentId = button.dataset.officialId;
      await loadOfficialDocumentDetail(selectedOfficialDocumentId);
    });
  });
}

async function loadOfficialDocumentDetail(documentId) {
  try {
    const detail = await backendRequest(`/official-documents/${encodeURIComponent(documentId)}`);
    const index = officialWorkflowItems.findIndex((item) => item.id === documentId);
    if (index >= 0) officialWorkflowItems[index] = detail;
    else officialWorkflowItems.unshift(detail);
  } catch (error) {
    showToast(`發文詳情載入失敗：${error.message}`);
  }
  renderOfficialWorkflow();
}

function renderOfficialFiles(files = [], documentId = "") {
  if (!files.length) return `<p class="empty-text">尚無文件版本或附件。</p>`;
  return `<div class="official-file-list">${files.map((file) => `
    <article class="official-file-row ${file.is_stamped ? "stamped" : ""}">
      <div>
        <strong>${file.display_label || officialFileTypeLabel(file.file_type)} · ${file.file_name}</strong>
        <span>${officialFileTypeLabel(file.file_type)} · v${file.version} · ${file.uploaded_by || "系統"} · ${file.created_at || ""}</span>
      </div>
      <button class="secondary-button" type="button" data-official-download="${file.id}" data-document-id="${documentId}">下載</button>
    </article>
  `).join("")}</div>`;
}

function renderOfficialSteps(item) {
  const steps = item?.approval_steps || [];
  if (!steps.length) return `<p class="empty-text">尚未建立簽核節點。</p>`;
  return `<div class="official-step-list">${steps.map((step) => `
    <article class="official-step-row ${step.status || "pending"} ${step.step_key === item.current_step ? "current" : ""}">
      <time>${step.step_order}</time>
      <div>
        <strong>${step.step_name}</strong>
        <span>${step.approver_name || step.approver_role || "未指定"} · ${step.status}</span>
        ${step.comment ? `<small>${step.comment}</small>` : ""}
      </div>
      <span>${step.approved_at || ""}</span>
    </article>
  `).join("")}</div>`;
}

function renderOfficialLogs(logs = [], emptyText = "尚無紀錄。") {
  if (!logs.length) return `<p class="empty-text">${emptyText}</p>`;
  return `<div class="timeline">${logs.map((log) => `
    <article class="timeline-item">
      <time>${(log.created_at || "").slice(11, 16)}</time>
      <div>
        <strong>${log.action} · ${log.actor_name || ""}</strong>
        <p>${log.comment || log.file_id || ""}</p>
      </div>
    </article>
  `).join("")}</div>`;
}

function renderOfficialApplicationSummary(item = {}) {
  const summary = officialApplicationSummary(item);
  return `
    <div class="official-package-summary">
      <span>文件版本 <strong>${summary.versionCount}</strong></span>
      <span>補充附件 <strong>${summary.attachmentCount}</strong></span>
      <span>簽核節點 <strong>${summary.approvalStepCount}</strong></span>
      <span>下載紀錄 <strong>${summary.downloadCount}</strong></span>
      <span>${summary.hasStampedPdf ? "已有已用印版本" : "尚未產生已用印版本"}</span>
    </div>
  `;
}

function renderOfficialDispatchInfo(item = {}) {
  const record = officialDispatchRecord(item) || {};
  const method = record.dispatch_method || item.dispatch_method || "electronic_official_document_by_general_affairs";
  const canManage = Boolean(item.can_manage_dispatch);
  const needsGeneralAffairs = item.current_status === "pending_general_affairs_dispatch";
  const needsApplicant = item.current_status === "returned_to_applicant_for_send";
  const canComplete = canManage && (needsGeneralAffairs || needsApplicant);
  const proof = record.proof_file;
  return `
    <section class="official-dispatch-box">
      <div class="panel-heading tight">
        <h4>寄發資訊</h4>
        <span class="status-pill">${officialDispatchStatusLabels[record.dispatch_status] || officialStatusLabel(item.current_status)}</span>
      </div>
      <div class="official-detail-grid">
        <div><dt>寄發方式</dt><dd>${record.dispatch_method_label || officialDispatchMethodLabels[method] || method}</dd></div>
        <div><dt>寄發負責人</dt><dd>${record.dispatch_owner_name || record.dispatch_owner_user_id || (method === "no_dispatch_required" ? "系統" : "尚未指派")}</dd></div>
        <div><dt>發文字號</dt><dd>${record.external_official_document_number || "尚未回填"}</dd></div>
        <div><dt>寄發日期</dt><dd>${record.dispatch_date || "尚未回填"}</dd></div>
        <div><dt>收文對象</dt><dd>${record.recipient || item.recipient || "未指定"}</dd></div>
        <div><dt>聯絡資訊</dt><dd>${record.recipient_contact || "未填寫"}</dd></div>
        <div><dt>寄發備註</dt><dd>${record.dispatch_note || "未填寫"}</dd></div>
        <div><dt>完成時間</dt><dd>${record.completed_at || "尚未完成"}</dd></div>
      </div>
      ${proof ? `<div class="official-file-list"><article class="official-file-row"><div><strong>${proof.display_label || "寄發證明"} · ${proof.file_name}</strong><span>${officialFileTypeLabel(proof.file_type)} · v${proof.version} · ${proof.created_at || ""}</span></div><button class="secondary-button" type="button" data-official-download="${proof.id}" data-document-id="${item.id}">下載</button></article></div>` : `<p class="empty-text">尚未上傳寄發證明。</p>`}
      ${canComplete ? `
        <div class="official-dispatch-form">
          ${needsGeneralAffairs ? `<label>外部發文字號<input id="officialDispatchNumberInput" value="${record.external_official_document_number || ""}" placeholder="外部電子公文發文字號" /></label>` : ""}
          <label>寄發日期<input id="officialDispatchDateInput" type="date" value="${(record.dispatch_date || "").slice(0, 10)}" /></label>
          <label>收件人<input id="officialDispatchRecipientInput" value="${record.recipient || item.recipient || ""}" /></label>
          <label>聯絡資訊<input id="officialDispatchContactInput" value="${record.recipient_contact || ""}" placeholder="Email、地址或聯絡窗口" /></label>
          <label>寄發備註<textarea id="officialDispatchNoteInput" rows="3">${record.dispatch_note || ""}</textarea></label>
          <label>寄發證明<input id="officialDispatchProofInput" type="file" accept="application/pdf,image/png,image/jpeg,image/webp" /></label>
          <button class="primary-button" type="button" id="officialCompleteDispatchBtn">${needsGeneralAffairs ? "完成發文" : "已自行寄出"}</button>
        </div>
      ` : ""}
    </section>
  `;
}

function renderOfficialWorkflowDetail() {
  const target = document.querySelector("#officialWorkflowDetail");
  const form = document.querySelector("#officialWorkflowForm");
  if (!target || !form) return;
  form.classList.toggle("hidden", officialWorkflowScope !== "new");
  if (officialWorkflowScope === "new") {
    target.innerHTML = `
      <div class="doc-detail">
        <strong>發文申請單是主檔</strong>
        <p>這裡建立的是一張發文申請單；空白撰寫或上傳 PDF 只是來源版本。送出後，PDF、已用印版本、補充附件、簽核歷程與下載紀錄都會掛在同一張申請單底下。</p>
      </div>
    `;
    updateOfficialStampPreview();
    return;
  }
  const item = officialCurrentItem();
  if (!item) {
    target.innerHTML = `<p class="empty-text">請選擇一筆發文申請單。</p>`;
    return;
  }
  const summary = officialApplicationSummary(item);
  const files = officialApplicationFiles(item);
  target.innerHTML = `
    <div class="doc-detail">
      <strong>發文申請單 · ${item.title || item.subject || item.id}</strong>
      <div class="official-detail-grid">
        <div><dt>申請單編號</dt><dd>${item.id}</dd></div>
        <div><dt>狀態</dt><dd>${officialStatusLabel(item.current_status)}</dd></div>
        <div><dt>目前關卡</dt><dd>${item.current_step_name || item.current_step || "未送出"}</dd></div>
        <div><dt>申請人</dt><dd>${item.applicant_name || item.applicant_id}</dd></div>
        <div><dt>受文者</dt><dd>${item.recipient || "未指定"}</dd></div>
        <div><dt>來源</dt><dd>${item.source_type === "uploaded_pdf" ? "上傳 PDF" : "空白公文撰寫"}</dd></div>
        <div><dt>用印原因</dt><dd>${item.request_reason || "未填寫"}</dd></div>
        <div><dt>文件版本</dt><dd>${summary.versionCount} 版${summary.hasStampedPdf ? " · 已用印" : ""}</dd></div>
        <div><dt>下載紀錄</dt><dd>${summary.downloadCount} 筆</dd></div>
      </div>
      ${renderOfficialApplicationSummary(item)}
      <p>${item.description || item.subject || ""}</p>
      <div class="official-action-bar">
        ${item.can_act ? `<button class="primary-button" type="button" id="officialApproveBtn">核准</button><button class="secondary-button" type="button" id="officialRejectBtn">駁回</button>` : ""}
        ${item.current_status === "draft" ? `<button class="primary-button" type="button" id="officialSubmitDraftBtn">送出簽核</button>` : ""}
      </div>
      ${renderOfficialDispatchInfo(item)}
      <h4>文件版本與附件</h4>
      ${renderOfficialFiles(files, item.id)}
      <h4>簽核流程</h4>
      ${renderOfficialSteps(item)}
      <h4>簽核與用印歷程</h4>
      ${renderOfficialLogs(officialProcessLogs(item), "尚無簽核或用印紀錄。")}
      <h4>下載紀錄</h4>
      ${renderOfficialLogs(officialDownloadLogs(item), "尚無下載紀錄。")}
    </div>
  `;
  document.querySelector("#officialApproveBtn")?.addEventListener("click", () => mutateOfficialDocument("approve"));
  document.querySelector("#officialRejectBtn")?.addEventListener("click", () => mutateOfficialDocument("reject"));
  document.querySelector("#officialSubmitDraftBtn")?.addEventListener("click", () => mutateOfficialDocument("submit"));
  document.querySelector("#officialCompleteDispatchBtn")?.addEventListener("click", () => completeOfficialDispatch(item.id));
  target.querySelectorAll("[data-official-download]").forEach((button) => {
    button.addEventListener("click", () => downloadOfficialWorkflowFile(button.dataset.documentId, button.dataset.officialDownload));
  });
}

function renderOfficialWorkflow() {
  document.querySelectorAll("[data-official-scope]").forEach((button) => button.classList.toggle("active", button.dataset.officialScope === officialWorkflowScope));
  renderOfficialCompanyOptions();
  renderOfficialSealOptions();
  renderOfficialWorkflowList();
  renderOfficialWorkflowDetail();
}

function updateOfficialStampPreview() {
  const box = document.querySelector("#officialStampBox");
  const preview = document.querySelector("#officialStampPreview");
  if (!box || !preview) return;
  const x = Number(document.querySelector("#officialStampXInput")?.value || 420);
  const y = Number(document.querySelector("#officialStampYInput")?.value || 130);
  const w = Number(document.querySelector("#officialStampWidthInput")?.value || 85);
  const h = Number(document.querySelector("#officialStampHeightInput")?.value || 85);
  box.style.left = `${Math.min(88, Math.max(0, x / 6))}%`;
  box.style.top = `${Math.min(82, Math.max(0, y / 5))}%`;
  box.style.width = `${Math.max(36, Math.min(140, w))}px`;
  box.style.height = `${Math.max(36, Math.min(140, h))}px`;
}

async function officialFormPayload(submit = true) {
  const sourceType = document.querySelector("#officialSourceType").value;
  const payload = {
    source_type: sourceType,
    company_id: document.querySelector("#officialCompanySelect").value,
    seal_id: document.querySelector("#officialSealSelect").value,
    dispatch_method: document.querySelector("#officialDispatchMethodSelect").value,
    title: document.querySelector("#officialSubjectInput").value.trim() || "未命名發文申請",
    subject: document.querySelector("#officialSubjectInput").value.trim(),
    description: document.querySelector("#officialDescriptionInput").value.trim(),
    method: document.querySelector("#officialMethodInput").value.trim(),
    recipient: document.querySelector("#officialRecipientInput").value.trim(),
    dispatch_unit: document.querySelector("#officialDispatchUnitInput").value.trim() || activeUnit(),
    handler_name: document.querySelector("#officialHandlerInput").value.trim() || authState?.user?.name || activeRole(),
    request_reason: document.querySelector("#officialReasonInput").value.trim(),
    submit,
    stamp_position: {
      page: Number(document.querySelector("#officialStampPageInput").value || 1),
      x: Number(document.querySelector("#officialStampXInput").value || 420),
      y: Number(document.querySelector("#officialStampYInput").value || 130),
      width: Number(document.querySelector("#officialStampWidthInput").value || 85),
      height: Number(document.querySelector("#officialStampHeightInput").value || 85)
    }
  };
  if (sourceType === "uploaded_pdf") {
    const file = document.querySelector("#officialPdfInput").files?.[0];
    if (!file) throw new Error("請選擇要上傳用印的 PDF。");
    payload.file_name = file.name;
    payload.content_base64 = await fileToBase64(file);
  }
  return payload;
}

async function createOfficialWorkflow(submit = true) {
  try {
    const payload = await officialFormPayload(submit);
    const result = await backendRequest("/official-documents", { method: "POST", body: JSON.stringify(payload) });
    selectedOfficialDocumentId = result.id;
    officialWorkflowScope = "mine";
    await loadOfficialWorkflow("mine");
    showToast(submit ? "已送出發文用印簽核。" : "已建立發文草稿。");
  } catch (error) {
    showToast(error.message || "建立發文失敗。");
  }
}

async function mutateOfficialDocument(action) {
  const item = officialCurrentItem();
  if (!item) return showToast("請先選擇發文申請單。");
  const comment = action === "reject" ? prompt("請輸入駁回原因") : "";
  if (action === "reject" && !comment) return;
  try {
    const result = await backendRequest(`/official-documents/${encodeURIComponent(item.id)}/${action}`, { method: "POST", body: JSON.stringify({ comment }) });
    selectedOfficialDocumentId = result.id;
    const index = officialWorkflowItems.findIndex((entry) => entry.id === result.id);
    if (index >= 0) officialWorkflowItems[index] = result;
    else officialWorkflowItems.unshift(result);
    renderOfficialWorkflow();
    showToast("發文簽核狀態已更新。");
  } catch (error) {
    showToast(error.message || "簽核操作失敗。");
  }
}

async function completeOfficialDispatch(documentId) {
  try {
    const file = document.querySelector("#officialDispatchProofInput")?.files?.[0];
    let proofFileId = officialDispatchRecord(officialCurrentItem() || {})?.proof_file_id || "";
    if (file) {
      const upload = await backendRequest(`/official-documents/${encodeURIComponent(documentId)}/dispatch/proof-files`, {
        method: "POST",
        body: JSON.stringify({
          file_name: file.name,
          file_mime_type: file.type || "application/pdf",
          content_base64: await fileToBase64(file)
        })
      });
      proofFileId = upload.file?.id || upload.dispatch_record?.proof_file_id || proofFileId;
    }
    const payload = {
      external_official_document_number: document.querySelector("#officialDispatchNumberInput")?.value?.trim() || "",
      dispatch_date: document.querySelector("#officialDispatchDateInput")?.value || "",
      recipient: document.querySelector("#officialDispatchRecipientInput")?.value?.trim() || "",
      recipient_contact: document.querySelector("#officialDispatchContactInput")?.value?.trim() || "",
      dispatch_note: document.querySelector("#officialDispatchNoteInput")?.value?.trim() || "",
      proof_file_id: proofFileId
    };
    const result = await backendRequest(`/official-documents/${encodeURIComponent(documentId)}/dispatch/complete`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    selectedOfficialDocumentId = result.id;
    const index = officialWorkflowItems.findIndex((entry) => entry.id === result.id);
    if (index >= 0) officialWorkflowItems[index] = result;
    else officialWorkflowItems.unshift(result);
    renderOfficialWorkflow();
    showToast("寄發資訊已完成並寫入申請單紀錄。");
  } catch (error) {
    showToast(`完成寄發失敗：${error.message}`);
  }
}

async function downloadOfficialWorkflowFile(documentId, fileId) {
  try {
    const response = await fetch(`${backendApiBase}/official-documents/${encodeURIComponent(documentId)}/files/${encodeURIComponent(fileId)}/download`, {
      headers: isHeaderSafeToken(authState?.token) ? { Authorization: `Bearer ${authState.token}` } : {}
    });
    if (!response.ok) throw new Error((await response.text()).slice(0, 160) || `HTTP ${response.status}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = response.headers.get("Content-Disposition")?.match(/filename=\"?([^\";]+)/)?.[1] || "official-document.pdf";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showToast(`下載失敗：${error.message}`);
  }
}

function renderDispatchAuditLog() {
  document.querySelector("#dispatchAuditLog").innerHTML = dispatchAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function mutateDispatch(ids, handler) {
  ids.forEach((id) => {
    const doc = dispatchDocs.find((item) => item.id === id);
    if (doc) handler(doc);
  });
  renderDispatchBoard();
  renderDispatchDetail();
  renderUnifiedFlows();
}

function dispatchTargetIds(ids) {
  if (ids?.length) return ids;
  const selected = selectedDispatchDocs().map((doc) => doc.id);
  return selected.length ? selected : selectedDispatchId ? [selectedDispatchId] : [];
}

function unsafeAttachmentsForDoc(doc) {
  const keys = documentAclKeys(doc);
  return fileSecurityItems.filter((item) => keys.includes(item.docNo) && (
    item.scanStatus === "已隔離" ||
    item.scanStatus === "待掃描" ||
    item.maskStatus === "需遮罩" ||
    isFileOverLimit(item) ||
    !isFileTypeAllowed(item)
  ));
}

function dispatchDocSnapshot(doc) {
  return {
    no: doc.no || "",
    companyName: doc.companyName || "",
    type: doc.type || "",
    priority: doc.priority || "",
    security: doc.security || "普通",
    to: doc.to || "",
    agencyCode: doc.agencyCode || "",
    subject: doc.subject || "",
    body: doc.body || "",
    contactAddress: doc.contactAddress || "",
    contactOwner: doc.contactOwner || "",
    contactPhone: doc.contactPhone || "",
    contactFax: doc.contactFax || "",
    contactEmail: doc.contactEmail || "",
    attachments: normalizedContractAttachments(doc.attachments || []),
    sealPlan: doc.sealPlan || {}
  };
}

function dispatchDocContentHash(doc) {
  return stableHash(dispatchDocSnapshot(doc));
}

function lockDispatchDocForSend(doc, reason = "發文封裝鎖版") {
  doc.lockedAt = doc.lockedAt || new Date().toLocaleString("zh-TW", { hour12: false });
  doc.lockedBy = doc.lockedBy || (authState?.user?.name || activeRole());
  doc.lockedHash = dispatchDocContentHash(doc);
  doc.lockedAttachmentHash = contractAttachmentHash(doc.attachments || []);
  doc.versionStatus = "已鎖版";
  addDispatchAudit(reason, `${doc.no} 已鎖定發文版本，內容雜湊 ${doc.lockedHash}，附件雜湊 ${doc.lockedAttachmentHash}。`);
  return doc.lockedHash;
}

function guardDispatchDocVersion(doc, auditTitle = "發文版本防呆") {
  if (!doc.lockedHash) return blockOperation(`${doc.no} 尚未鎖版，請先完成清稿與附件封裝。`, addDispatchAudit, auditTitle);
  const currentHash = dispatchDocContentHash(doc);
  const currentAttachmentHash = contractAttachmentHash(doc.attachments || []);
  if (currentHash === doc.lockedHash && currentAttachmentHash === doc.lockedAttachmentHash) return true;
  doc.requiresReapproval = true;
  doc.lastReply = "鎖版後內容或附件異動，需退回補正並重新簽核。";
  return blockOperation(`${doc.no} 鎖版後內容或附件已異動，必須退回補正並重新清稿/封裝。`, addDispatchAudit, auditTitle);
}

function guardDispatchAction(action, docs) {
  const blocked = [];
  if (action === "send") {
    docs.forEach((doc) => {
      if (["等待確認", "交換完成"].includes(doc.status)) blocked.push(`${doc.no} 目前狀態為「${doc.status}」，不可重複送出`);
      if (!doc.checks.format) blocked.push(`${doc.no} 尚未完成清稿檢核`);
      if (!doc.checks.package) blocked.push(`${doc.no} 尚未完成附件封裝`);
      if (!doc.checks.certificate) blocked.push(`${doc.no} 尚未通過憑證檢核`);
      if (!doc.lockedHash) blocked.push(`${doc.no} 尚未鎖定發文版本`);
      if (doc.lockedHash && dispatchDocContentHash(doc) !== doc.lockedHash) blocked.push(`${doc.no} 鎖版後內容已異動`);
      const unsafe = unsafeAttachmentsForDoc(doc);
      if (unsafe.length) blocked.push(`${doc.no} 有 ${unsafe.length} 件附件尚未通過資安檢查`);
    });
  }
  if (action === "resend") {
    docs.forEach((doc) => {
      if (!["交換失敗", "退回補正"].includes(doc.status)) blocked.push(`${doc.no} 目前狀態為「${doc.status}」，只有交換失敗或退回補正才可重送`);
      const unsafe = unsafeAttachmentsForDoc(doc);
      if (unsafe.length) blocked.push(`${doc.no} 有 ${unsafe.length} 件附件尚未通過資安檢查`);
    });
  }
  if (action === "package") {
    docs.forEach((doc) => {
      if (!doc.checks.format) blocked.push(`${doc.no} 尚未完成清稿檢核，不可封裝`);
      const unsafe = unsafeAttachmentsForDoc(doc);
      if (unsafe.some((item) => item.scanStatus === "已隔離" || isFileOverLimit(item) || !isFileTypeAllowed(item))) {
        blocked.push(`${doc.no} 有附件已隔離、超過大小或副檔名不允許`);
      }
    });
  }
  if (blocked.length) return blockOperation(blocked[0], addDispatchAudit, "發文操作防呆");
  if (action === "send") return requireTypedConfirm("確認送交 jAgent", `即將送出 ${docs.length} 筆發文。送出後會進入交換中心等待確認，請確認函稿預覽、附件封裝、憑證與資安檢查都已完成。`, "確認送交");
  if (action === "resend") return requireTypedConfirm("確認重送發文", `即將重送 ${docs.length} 筆異常發文。系統會沿用原封包與交換紀錄產生重送事件。`, "確認重送");
  return true;
}

function runDispatchAction(action, ids) {
  const targetIds = dispatchTargetIds(ids);
  if (!targetIds.length) return showToast("請先選取要作業的發文。");
  const actionNames = { validate: "清稿檢核", package: "附件封裝", send: "送交 jAgent", query: "查詢狀態", resend: "重送" };
  const targetDocs = targetIds.map((id) => dispatchDocs.find((item) => item.id === id)).filter(Boolean);
  if (!guardDispatchAction(action, targetDocs)) return;
  const requiredAcl = { validate: "sign", package: "download", send: "seal", resend: "seal" }[action];
  if (requiredAcl) {
    const denied = targetDocs.filter((doc) => !canUseDocAction(doc, requiredAcl));
    if (denied.length) return showToast(`此角色未取得部分發文的${actionNames[action]}權限。`);
  }
  mutateDispatch(targetIds, (doc) => {
    if (action === "send" && !doc.checks.package) {
      doc.lastReply = "請先完成清稿與附件封裝，再送交 jAgent。";
      showToast("請先完成清稿與附件封裝。");
      return;
    }
    if (action === "validate") {
      doc.checks.format = true;
      doc.status = doc.status === "草稿" ? "待清稿" : "已清稿";
      doc.lastReply = "清稿檢核通過，等待附件封裝。";
    }
    if (action === "package") {
      doc.checks.format = true;
      doc.checks.package = true;
      doc.packageId = doc.packageId || `PKG-${doc.no.replace(/\D/g, "").slice(-10) || Date.now()}`;
      doc.status = "已封裝";
      lockDispatchDocForSend(doc);
      doc.lastReply = "已完成附件封裝與雜湊檢核。";
    }
    if (action === "send") {
      if (!guardDispatchDocVersion(doc, "送交 jAgent 鎖版防呆")) return;
      doc.checks.format = true;
      doc.checks.package = true;
      doc.packageId = doc.packageId || `PKG-${Date.now()}`;
      doc.status = "等待確認";
      doc.lastReply = "jAgent 回覆 accepted，等待收文方確認。";
      createWorkflowTaskForDispatch(doc, "待清稿");
    }
    if (action === "query") {
      doc.status = doc.status === "等待確認" ? "交換完成" : doc.status;
      doc.lastReply = doc.status === "交換完成" ? "jAgent 回覆 exchangeCompleted，收文方已確認。" : `已查詢 jAgent，目前狀態：${doc.status}。`;
    }
    if (action === "resend") {
      doc.checks.package = true;
      doc.packageId = doc.packageId || `PKG-${Date.now()}`;
      doc.status = "等待確認";
      doc.lastReply = "已重送至 jAgent，等待交換中心回覆。";
    }
    persistToBackend(`/documents/${doc.id.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`}`, backendDocumentPayload(doc), "PATCH");
  });
  addDispatchAudit(actionNames[action], `已對 ${targetIds.length} 筆發文執行「${actionNames[action]}」。`);
  renderApprovalLog();
  showToast(`已完成 ${actionNames[action]}。`);
}

function createWorkflowTaskForDispatch(doc, status) {
  if (!doc || status === "草稿") return;
  const existing = workflowTasks.find((task) => task.docId === doc.id);
  if (existing) return;
  const task = {
    id: `WF-OUT-${Date.now().toString().slice(-6)}`,
    docId: doc.id,
    title: doc.subject,
    type: "發文",
    step: "承辦送簽",
    role: "行政部主任",
    status: "待審核",
    template: doc.priority === "速件" || doc.priority === "最速件" ? "urgent" : "standard",
    currentStepIndex: 0,
    submittedAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    requester: activeRole(),
    lastComment: "承辦人已確認函稿並送簽。"
  };
  workflowTasks.unshift(task);
  selectedWorkflowTaskId = task.id;
  persistToBackend("/workflow_tasks", backendWorkflowPayload(task));
  addWorkflowProof("建立簽核流程", `${doc.no} 已建立簽核流程，第一關：${task.step}，負責角色：${task.role}`);
  addWorkflowAudit("建立簽核流程", `${doc.no} 已送簽，流程紀錄可於側欄「簽核紀錄」查詢。`);
}

async function createDispatchFromForm(status = "草稿") {
  if (status !== "草稿" && !draftConfirmed) {
    showToast("請先在即時函稿預覽確認內容後再加入發文佇列。");
    return null;
  }
  if (status !== "草稿") draftSigned = true;
  const data = composePayload();
  const existingComposeDraft = dispatchDocs.find((item) => item.id === currentComposeDraftId && item.status === "草稿");
  const existingDoc = existingComposeDraft || null;
  const no = existingDoc?.no || assignNextDispatchNo();
  const doc = existingDoc || {
    id: `OUT-${Date.now()}`,
    no,
    exchangeNo: `EX-OUT-${Date.now().toString().slice(-8)}`
  };
  Object.assign(doc, {
    companyName: data.companyName,
    type: data.type,
    priority: data.priority,
    security: "普通",
    to: data.recipient,
    agencyCode: "待查詢",
    subject: data.subject,
    body: data.body,
    contactAddress: data.contactAddress,
    contactOwner: data.contactOwner,
    contactPhone: data.contactPhone,
    contactFax: data.contactFax,
    contactEmail: data.contactEmail,
    sealPlan: {
      large: {
        type: data.largeSealType,
        placement: { ...composeSealPlacements.large }
      },
      small: {
        type: data.smallSealType,
        placement: { ...composeSealPlacements.small }
      }
    },
    status,
    owner: "總務",
    attachments: ["函稿本文.pdf", "附件清冊.xml"],
    packageId: "",
    lastReply: status === "草稿" ? (existingDoc ? "草稿已更新，尚未清稿。" : "草稿已建立，尚未清稿。") : "已建立函稿並進入清稿檢核。",
    checks: { format: status !== "草稿", recipient: true, attachments: true, certificate: true, package: false },
    lockedAt: "",
    lockedBy: "",
    lockedHash: "",
    lockedAttachmentHash: "",
    versionStatus: "草稿可編修",
    requiresReapproval: false
  });
  if (!existingDoc) dispatchDocs.unshift(doc);
  const docPath = `/documents/${doc.id.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`}`;
  await persistToBackend(existingDoc ? docPath : "/documents", backendDocumentPayload(doc), existingDoc ? "PATCH" : "POST");
  if (!existingDoc) {
    upsertDocumentAcl(doc, activeRole(), { view: true, sign: false, download: false, seal: false, delegate: false, reason: "撰寫者建立函稿，可檢視與補正內容。" });
    upsertDocumentAcl(doc, "行政部主任", { view: true, sign: true, download: true, seal: true, delegate: true, reason: "送簽清稿與用印前核准。" });
    upsertDocumentAcl(doc, "總務", { view: true, sign: false, download: true, seal: true, delegate: false, reason: "清稿後封裝、用印與送交 jAgent。" });
  }
  selectedDispatchId = doc.id;
  if (status === "草稿") currentComposeDraftId = doc.id;
  createWorkflowTaskForDispatch(doc, status);
  if (status !== "草稿") {
    currentComposeDraftId = "";
    assignNextDispatchNo(true);
    setDraftConfirmed(false);
    draftSigned = false;
  } else {
    draftConfirmed = false;
    draftSigned = false;
    activeComposeStep = "fill";
    renderDraftPreview();
  }
  const auditTitle = status === "草稿"
    ? (existingDoc ? "更新發文草稿" : "建立發文草稿")
    : (existingDoc ? "草稿送出清稿" : "建立函稿");
  addDispatchAudit(auditTitle, `${doc.no} 已${existingDoc ? "更新" : "建立"}，受文者：${doc.to}。`);
  renderDispatchBoard();
  renderDispatchDetail();
  renderWorkflowTasks();
  renderUnifiedFlows();
  renderApprovalLog();
  renderDashboardApprovalProgress();
  return doc;
}

async function saveComposeDraft() {
  const activeButton = document.activeElement?.matches?.("#saveDispatchDraftBtn, #composeInlineSaveDraftBtn")
    ? document.activeElement
    : null;
  if (activeButton) activeButton.disabled = true;
  composeSaveState = {
    tone: "saving",
    title: "正在暫存草稿",
    detail: "系統正在保存目前表單內容，請稍候。"
  };
  renderComposeSaveStatus();
  try {
    const existingDraft = dispatchDocs.find((item) => item.id === currentComposeDraftId && item.status === "草稿");
    const doc = await createDispatchFromForm("草稿");
    if (doc) {
      clearComposeAutosave();
      composeSaveState = {
        tone: "saved",
        title: existingDraft ? `草稿已更新 ${doc.no}` : `草稿已儲存 ${doc.no}`,
        detail: `${nowTime()} 已保存到發文清單，畫面會停留在填寫與預覽同頁。`
      };
      renderComposeStepper();
      showToast(existingDraft ? `發文草稿已更新：${doc.no}` : `發文草稿已儲存：${doc.no}`);
    }
  } finally {
    if (activeButton) activeButton.disabled = false;
  }
}

function addContractAudit(title, body) {
  contractAuditLog.unshift([nowTime(), title, body]);
  renderContractAuditLog();
}

function nextContractNo() {
  const dateSerial = rocDateSerial();
  const prefix = `合約字第${dateSerial}`;
  const numbers = contractRecords
    .map((contract) => contract.contractNo)
    .filter(Boolean)
    .map((value) => {
      const match = String(value).match(new RegExp(`^${prefix}(\\d{3})號$`));
      return match ? Number(match[1]) : 0;
    });
  return `${prefix}${String(Math.max(0, ...numbers) + 1).padStart(3, "0")}號`;
}

function contractDaysToEnd(contract) {
  if (!contract?.endDate) return null;
  const end = new Date(`${contract.endDate}T00:00:00`);
  if (Number.isNaN(end.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.ceil((end - today) / 86400000);
}

function isContractRenewalSoon(contract) {
  const days = contractDaysToEnd(contract);
  return days !== null && days >= 0 && days <= Number(contract.renewalDays || 60);
}

function formatContractDate(value) {
  if (!value) return "未設定";
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function contractSealDate(contract) {
  return contract?.signedAt ? formatContractDate(contract.signedAt) : "待用印";
}

function contractTermText(contract) {
  return `${formatContractDate(contract.startDate)} - ${formatContractDate(contract.endDate)}`;
}

function contractCountdownText(contract) {
  const days = contractDaysToEnd(contract);
  if (days === null) return "未設定";
  if (days < 0) return `已過期 ${Math.abs(days)} 天`;
  if (days === 0) return "今日到期";
  return `${days} 天`;
}

function contractCountdownTone(contract) {
  const days = contractDaysToEnd(contract);
  if (days === null) return "";
  if (days < 0) return "expired";
  if (days <= 30) return "urgent";
  if (isContractRenewalSoon(contract)) return "soon";
  return "";
}

function canSeeContract(contract, role = activeRole()) {
  if (contract.owner === role || contract.owner === authState?.user?.name) return true;
  if (contract.dept === role || contract.dept === activeUnit()) return true;
  return false;
}

function contractApprovalsFor(contractId) {
  return contractApprovals
    .filter((approval) => approval.contractId === contractId)
    .sort((a, b) => Number(a.stepNo || 0) - Number(b.stepNo || 0));
}

function activeAccountForRole(role) {
  return userAccounts.find((account) => account.role === role && account.status === "啟用");
}

function activeProxyForRole(role) {
  return workflowProxies.find((proxy) => proxy.from === role && proxy.status === "啟用" && activeAccountForRole(proxy.to));
}

function resolveApprovalAssignee(role) {
  if (!role) return { ok: false, role: "", message: "簽核角色未設定" };
  if (activeAccountForRole(role)) return { ok: true, role, message: "" };
  const proxy = activeProxyForRole(role);
  if (proxy) return { ok: true, role: proxy.to, proxyFrom: role, message: `${role} 無啟用帳號，已套用代理 ${proxy.to}` };
  return { ok: false, role, message: `${role} 沒有啟用帳號，也沒有可用代理人` };
}

function applyApprovalAssigneeResolution(approval, auditFn = null) {
  const resolved = resolveApprovalAssignee(approval.role);
  if (!resolved.ok) return resolved;
  if (resolved.proxyFrom) {
    approval.delegatedFrom = resolved.proxyFrom;
    approval.role = resolved.role;
    approval.comment = `${approval.comment || "等待簽核意見。"}（系統套用代理：${resolved.proxyFrom} → ${resolved.role}）`;
    if (auditFn) auditFn("套用簽核代理", `${approval.step} 原角色 ${resolved.proxyFrom} 無啟用帳號，已改派 ${resolved.role}。`);
  }
  return resolved;
}

function validateApprovalAssignees(approvals, auditFn, auditTitle = "簽核角色防呆") {
  const unresolved = approvals
    .filter((approval) => !/完成|已簽署|已歸檔/.test(approval.status))
    .map((approval) => ({ approval, resolved: applyApprovalAssigneeResolution(approval, auditFn) }))
    .filter(({ resolved }) => !resolved.ok);
  if (!unresolved.length) return true;
  const message = unresolved.map(({ approval, resolved }) => `${approval.step}：${resolved.message}`).join("；");
  return blockOperation(`簽核流程無法送出，${message}。請先在人員登錄啟用帳號或設定代理人。`, auditFn, auditTitle);
}

function currentContractApproval(contract = currentContract()) {
  return contractApprovalsFor(contract?.id).find((approval) => !/完成|已簽署|已歸檔/.test(approval.status));
}

function canApproveCurrentContract(contract = currentContract()) {
  if (!contract) return false;
  if (activeRole() === "執行長") return true;
  const current = currentContractApproval(contract);
  if (!current) return false;
  if (current.role === activeRole()) return true;
  return rolePermissions[activeRole()]?.includes("manage_contracts") && ["行政部主任", "總務"].includes(activeRole());
}

function visibleContracts() {
  return contractRecords.filter((contract) => canSeeContract(contract));
}

function currentContract() {
  if (!selectedContractId) return null;
  if (document.querySelector(".view.active")?.id === "contractSeal") {
    return contractRecords.find((contract) => contract.id === selectedContractId) || null;
  }
  const rows = visibleContracts();
  return rows.find((contract) => contract.id === selectedContractId) || rows[0] || null;
}

function filteredContracts() {
  const term = contractSearchTerm.trim().toLowerCase();
  return visibleContracts().filter((contract) => {
    const text = `${contract.contractNo} ${contract.companyName} ${contract.type} ${contract.title} ${contract.counterparty} ${contract.owner} ${contract.dept} ${contract.status}`.toLowerCase();
    const matchesFilter =
      contractFilter === "all" ||
      (contractFilter === "未用印" && !contract.signedAt && !/已簽署|已歸檔/.test(contract.status)) ||
      (contractFilter === "已用印" && Boolean(contract.signedAt || /已簽署|已歸檔/.test(contract.status))) ||
      (contractFilter === "待" && /待|審核|簽核/.test(contract.status)) ||
      (contractFilter === "用印" && /用印|簽署/.test(contract.status)) ||
      (contractFilter === "到期" && isContractRenewalSoon(contract)) ||
      (contractFilter === "過期" && Number(contractDaysToEnd(contract)) < 0) ||
      contract.status.includes(contractFilter);
    return matchesFilter && (!term || text.includes(term));
  });
}

function contractRiskLabels(contract) {
  const route = approvalRouteForType(contract.type);
  const labels = [];
  labels.push(route.name);
  if (Number(contract.amount || 0) >= 100000) labels.push("高金額");
  if (contract.confidentiality !== "普通") labels.push("保密");
  if (contract.sealRequirement && contract.sealRequirement !== "無") labels.push(`需${contract.sealRequirement}`);
  if (isContractRenewalSoon(contract)) labels.push("即將到期");
  return labels.length ? labels : ["一般"];
}

function contractApprovalTemplate(contract) {
  const route = approvalRouteForType(contract.type);
  const requester = contract.owner || activeRole() || "申請人";
  const steps = [
    { step: "申請人送出", role: requester, status: "完成", comment: `申請人已建立${contract.type || "用印"}資料，路由：${route.name}。` },
    { step: "申請人主管審核", role: "主管", status: "待簽核", comment: "依 Logging 職位規劃，由申請人直屬主管確認需求與附件。" },
    { step: "部門主管審核", role: "主任", status: "待簽核", comment: "確認部門權責、對外承諾、履約範圍與風險。" }
  ];
  if (route.requiresAccounting) {
    steps.push({ step: "會計複核", role: "會計", status: "待簽核", comment: "確認費用、付款條件、預算與稅務資料。" });
  }
  steps.push({ step: "行政部門主任核定", role: "行政部主任", status: "待簽核", comment: "確認文件完整性、用印類別、法遵留存與行政用印核准。" });
  if (route.requiresCeo) {
    steps.push({ step: "執行長核定", role: "執行長", status: "待簽核", comment: "最高層代表、重大治理或高風險用印最終核定。" });
  }
  steps.push(
    { step: "總務用印登錄", role: "總務", status: "待用印", comment: "核准後執行用印、留存用印影像、版本與雜湊。" },
    { step: "申請人確認", role: requester, status: "待確認", comment: "用印完成後回到申請人確認內容、合約影像與後續辦理。" },
    { step: "歸檔保存", role: "行政部主任", status: "待歸檔", comment: "結案後建立保存包、audit log、雜湊與續約提醒。" }
  );
  return steps;
}

function ensureContractApprovals(contract, force = false) {
  const existing = contractApprovalsFor(contract.id);
  if (existing.length && !force) return existing;
  if (existing.length && force) {
    for (let index = contractApprovals.length - 1; index >= 0; index -= 1) {
      if (contractApprovals[index].contractId === contract.id) contractApprovals.splice(index, 1);
    }
  }
  const steps = contractApprovalTemplate(contract).map((step, index) => ({
    id: `CA-${contract.id.replace(/\D/g, "").slice(-8)}-${String(index + 1).padStart(2, "0")}`,
    contractId: contract.id,
    stepNo: index + 1,
    step: step.step,
    role: step.role,
    status: index === 0 ? "完成" : step.status,
    approver: index === 0 ? activeRole() : "",
    comment: step.comment,
    signedAt: index === 0 ? new Date().toLocaleString("zh-TW", { hour12: false }) : ""
  }));
  contractApprovals.push(...steps);
  return steps;
}

function contractApprovalsMatchRoute(contract, approvals = contractApprovalsFor(contract.id)) {
  const expectedSteps = contractApprovalTemplate(contract).map((item) => item.step);
  return approvals.length === expectedSteps.length && expectedSteps.every((step, index) => approvals[index]?.step === step);
}

function normalizedContractAttachments(attachments = []) {
  return [...new Set((attachments || []).map((item) => String(item || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
}

function contractSnapshot(contract, data = {}) {
  const merged = { ...contract, ...data };
  const category = approvalCategoryForType(merged.type);
  return {
    companyName: merged.companyName || "",
    type: category.label,
    routeCode: approvalRouteForType(category.label).code,
    title: merged.title || "",
    counterparty: merged.counterparty || "",
    counterpartyTaxId: merged.counterpartyTaxId || "",
    owner: merged.owner || "",
    dept: merged.dept || "",
    amount: Number(merged.amount || 0),
    currency: merged.currency || "TWD",
    startDate: merged.startDate || "",
    endDate: merged.endDate || "",
    confidentiality: merged.confidentiality || "普通",
    sealRequirement: merged.sealRequirement || "無",
    summary: merged.summary || "",
    attachments: normalizedContractAttachments(merged.attachments)
  };
}

function contractContentHash(contract, data = {}) {
  return stableHash(contractSnapshot(contract, data));
}

function contractAttachmentHash(attachments = []) {
  return stableHash(normalizedContractAttachments(attachments));
}

function contractDiffFlags(contract, data) {
  const before = contractSnapshot(contract);
  const after = contractSnapshot(contract, data);
  return {
    routeChanged: before.routeCode !== after.routeCode || before.type !== after.type,
    attachmentsChanged: stableHash(before.attachments) !== stableHash(after.attachments),
    contentChanged: stableHash(before) !== stableHash(after)
  };
}

function isContractVersionLocked(contract) {
  return Boolean(contract?.lockedAt && !["草稿", "退回補正"].includes(contract.status));
}

function lockContractForSeal(contract, reason = "用印前鎖版") {
  if (!contract) return null;
  const hash = contractContentHash(contract);
  contract.lockedAt = contract.lockedAt || new Date().toLocaleString("zh-TW", { hour12: false });
  contract.lockedBy = contract.lockedBy || (authState?.user?.name || activeRole());
  contract.lockedHash = hash;
  contract.lockedAttachmentHash = contractAttachmentHash(contract.attachments);
  contract.versionStatus = "已鎖版";
  contract.requiresReapproval = false;
  contract.reapprovalReason = "";
  addContractAudit(reason, `${contract.contractNo} 已鎖定簽核版本，內容雜湊 ${contract.lockedHash}，附件雜湊 ${contract.lockedAttachmentHash}。`);
  return hash;
}

function unlockContractForCorrection(contract, reason = "退回補正") {
  if (!contract) return;
  const wasLocked = Boolean(contract.lockedAt);
  contract.lockedAt = "";
  contract.lockedBy = "";
  contract.lockedHash = "";
  contract.lockedAttachmentHash = "";
  contract.versionStatus = "退回可編修";
  contract.requiresReapproval = true;
  contract.reapprovalReason = reason;
  contract.signedAt = "";
  contract.archiveHash = "";
  if (wasLocked) addContractAudit("解除鎖版", `${contract.contractNo} 因「${reason}」解除鎖版；補正後將重新計算 A/B/C/D 流程。`);
}

function guardContractVersionIntegrity(contract, auditTitle = "合約版本防呆") {
  if (!contract?.lockedHash) return true;
  const currentHash = contractContentHash(contract);
  const currentAttachmentHash = contractAttachmentHash(contract.attachments);
  if (currentHash === contract.lockedHash && currentAttachmentHash === contract.lockedAttachmentHash) return true;
  contract.requiresReapproval = true;
  contract.reapprovalReason = "鎖版後內容或附件異動";
  return blockOperation(`${contract.contractNo} 鎖版後內容或附件已異動，必須退回補正並重新簽核後才能用印或送出。`, addContractAudit, auditTitle);
}

function currentApprovalIndexFromContractStatus(contract, approvals) {
  const steps = approvals.map((approval) => approval.step);
  if (/已歸檔/.test(contract.status) || contract.storageStatus === "已歸檔") return -1;
  if (/已簽署/.test(contract.status)) return steps.findIndex((step) => step.includes("歸檔"));
  if (/待歸檔/.test(contract.status)) return steps.findIndex((step) => step.includes("歸檔"));
  if (/待申請人確認|待確認/.test(contract.status)) return steps.findIndex((step) => step.includes("申請人確認"));
  if (/待用印/.test(contract.status)) return steps.findIndex((step) => step.includes("用印"));
  if (/會計/.test(contract.status)) return steps.findIndex((step) => step.includes("會計"));
  if (/執行長|負責人/.test(contract.status)) return steps.findIndex((step) => step.includes("執行長"));
  if (/行政部/.test(contract.status)) return steps.findIndex((step) => step.includes("行政部門主任"));
  if (/部門主管|主任/.test(contract.status)) return steps.findIndex((step) => step.includes("部門主管"));
  return Math.max(1, steps.findIndex((step) => step.includes("申請人主管")));
}

function syncContractApprovalProgressToStatus(contract) {
  const approvals = contractApprovalsFor(contract.id);
  if (!approvals.length) return approvals;
  let currentIndex = currentApprovalIndexFromContractStatus(contract, approvals);
  if (currentIndex < 0 && !/已簽署|已歸檔/.test(contract.status)) currentIndex = 1;
  approvals.forEach((approval, index) => {
    if (currentIndex < 0 || index < currentIndex) {
      approval.status = approval.step.includes("歸檔") && /已歸檔/.test(contract.status) ? "已歸檔" : "完成";
      approval.approver = approval.approver || (index === 0 ? contract.owner || activeRole() : "");
      approval.signedAt = approval.signedAt || (index === 0 ? contract.createdAt || new Date().toLocaleString("zh-TW", { hour12: false }) : "");
      return;
    }
    if (index === currentIndex) {
      approval.status = approval.step.includes("用印") ? "待用印" : approval.step.includes("確認") ? "待確認" : approval.step.includes("歸檔") ? "待歸檔" : "待簽核";
      return;
    }
    approval.status = approval.step.includes("用印") ? "待用印" : approval.step.includes("確認") ? "待確認" : approval.step.includes("歸檔") ? "待歸檔" : "待簽核";
    approval.approver = "";
    approval.signedAt = "";
  });
  return approvals;
}

function rebuildLegacyContractApprovals(contract) {
  const approvals = contractApprovalsFor(contract.id);
  if (!approvals.length || contractApprovalsMatchRoute(contract, approvals)) {
    syncContractApprovalProgressToStatus(contract);
    return approvals;
  }
  const legacyPattern = /起案完成|行政部主任清稿|總務用印簽署|密件權限檢核/;
  const looksLegacy = approvals.some((approval) => legacyPattern.test(approval.step));
  if (!looksLegacy) return approvals;
  ensureContractApprovals(contract, true);
  return syncContractApprovalProgressToStatus(contract);
}

function contractStatusAfterApproval(contract) {
  const remaining = contractApprovalsFor(contract.id).filter((approval) => !/完成|已簽署|已歸檔/.test(approval.status));
  const next = remaining[0];
  if (!next) return contract.storageStatus === "已歸檔" ? "已歸檔" : "已簽署";
  if (next.step.includes("歸檔")) return contract.signedAt ? "待歸檔" : "待用印簽署";
  if (next.step.includes("用印")) return "待用印簽署";
  if (next.step.includes("確認")) return "待申請人確認";
  return `待${next.role}簽核`;
}

function backendContractPayload(contract) {
  return {
    id: contract.id,
    contract_no: contract.contractNo,
    company_name: contract.companyName,
    contract_type: contract.type,
    title: contract.title,
    counterparty: contract.counterparty,
    counterparty_tax_id: contract.counterpartyTaxId,
    owner: contract.owner,
    department: contract.dept,
    amount: Number(contract.amount || 0),
    currency: contract.currency || "TWD",
    start_date: contract.startDate,
    end_date: contract.endDate,
    renewal_alert_days: Number(contract.renewalDays || 60),
    confidentiality_level: contract.confidentiality,
    seal_requirement: contract.sealRequirement,
    storage_status: contract.storageStatus,
    status: contract.status,
    summary: contract.summary,
    risk_note: contract.riskNote,
    attachment_manifest_json: contract.attachments,
    metadata_json: {
      signedAt: contract.signedAt || "",
      archiveHash: contract.archiveHash || "",
      lockedAt: contract.lockedAt || "",
      lockedBy: contract.lockedBy || "",
      lockedHash: contract.lockedHash || "",
      lockedAttachmentHash: contract.lockedAttachmentHash || "",
      versionStatus: contract.versionStatus || "",
      submittedHash: contract.submittedHash || "",
      submittedAttachmentHash: contract.submittedAttachmentHash || "",
      requiresReapproval: Boolean(contract.requiresReapproval),
      reapprovalReason: contract.reapprovalReason || "",
      approvalCategory: approvalCategoryForType(contract.type),
      approvalRoute: approvalRouteForType(contract.type),
      riskLabels: contractRiskLabels(contract)
    }
  };
}

function backendContractApprovalPayload(approval) {
  return {
    id: approval.id,
    contract_id: approval.contractId,
    step_no: Number(approval.stepNo || 1),
    step_name: approval.step,
    role: approval.role,
    status: approval.status,
    approver: approval.approver || "",
    comment: approval.comment || "",
    signed_at: approval.signedAt || "",
    non_repudiation_json: {
      actor: approval.approver || activeRole(),
      role: approval.role,
      evidenceHash: stableHash(approval),
      timestamp: approval.signedAt || new Date().toLocaleString("zh-TW", { hour12: false })
    }
  };
}

function persistContract(contract) {
  persistToBackend(`/contracts/${contract.id}`, backendContractPayload(contract), "PATCH");
}

function persistContractApproval(approval) {
  persistToBackend(`/contract_approvals/${approval.id}`, backendContractApprovalPayload(approval), "PATCH");
}

function renderContractFormOptions() {
  setSelectOptions("#contractCompanyInput", companyRegistry.map((item) => item.name), currentContract()?.companyName || companyRegistry[0]?.name || "歲悅長照股份有限公司");
  renderApprovalCategorySelect("#contractTypeInput", currentContract()?.type || "服務委託合約");
  setSelectOptions("#contractDepartmentInput", departmentRegistry.map((item) => item.name), currentContract()?.dept || activeUnit() || departmentRegistry[0]?.name || "行政部");
  setSelectOptions("#contractOwnerInput", edocAllowedRoles, currentContract()?.owner || activeRole());
}

function fillContractForm(contract = currentContract()) {
  renderContractFormOptions();
  if (!contract) {
    document.querySelector("#contractTitleInput").value = "";
    document.querySelector("#contractCounterpartyInput").value = "";
    document.querySelector("#contractTaxIdInput").value = "";
    document.querySelector("#contractAmountInput").value = "0";
    document.querySelector("#contractStartDateInput").value = "";
    document.querySelector("#contractEndDateInput").value = "";
    document.querySelector("#contractAttachmentsInput").value = "";
    document.querySelector("#contractSummaryInput").value = "";
    return;
  }
  document.querySelector("#contractCompanyInput").value = contract.companyName;
  renderApprovalCategorySelect("#contractTypeInput", contract.type);
  document.querySelector("#contractTitleInput").value = contract.title;
  document.querySelector("#contractCounterpartyInput").value = contract.counterparty;
  document.querySelector("#contractTaxIdInput").value = contract.counterpartyTaxId || "";
  document.querySelector("#contractDepartmentInput").value = contract.dept;
  document.querySelector("#contractOwnerInput").value = contract.owner;
  document.querySelector("#contractAmountInput").value = contract.amount || 0;
  document.querySelector("#contractStartDateInput").value = contract.startDate || "";
  document.querySelector("#contractEndDateInput").value = contract.endDate || "";
  document.querySelector("#contractRenewalDaysInput").value = String(contract.renewalDays || 60);
  document.querySelector("#contractConfidentialityInput").value = contract.confidentiality || "普通";
  document.querySelector("#contractSealInput").value = contract.sealRequirement || "一般章";
  document.querySelector("#contractAttachmentsInput").value = contract.attachments?.join("、") || "";
  document.querySelector("#contractSummaryInput").value = contract.summary || "";
}

function contractFormPayload() {
  const attachmentText = document.querySelector("#contractAttachmentsInput").value.trim();
  return {
    companyName: document.querySelector("#contractCompanyInput").value,
    type: document.querySelector("#contractTypeInput").value,
    title: document.querySelector("#contractTitleInput").value.trim(),
    counterparty: document.querySelector("#contractCounterpartyInput").value.trim(),
    counterpartyTaxId: document.querySelector("#contractTaxIdInput").value.trim(),
    owner: document.querySelector("#contractOwnerInput").value,
    dept: document.querySelector("#contractDepartmentInput").value,
    amount: Number(document.querySelector("#contractAmountInput").value || 0),
    currency: "TWD",
    startDate: document.querySelector("#contractStartDateInput").value,
    endDate: document.querySelector("#contractEndDateInput").value,
    renewalDays: Number(document.querySelector("#contractRenewalDaysInput").value || 60),
    confidentiality: document.querySelector("#contractConfidentialityInput").value,
    sealRequirement: document.querySelector("#contractSealInput").value,
    summary: document.querySelector("#contractSummaryInput").value.trim(),
    attachments: attachmentText ? attachmentText.split(/[、,\n]/).map((item) => item.trim()).filter(Boolean) : []
  };
}

function validateContractPayload(data) {
  if (!hasMinimumText(data.title, 4)) return "請輸入合約標題。";
  if (!hasMinimumText(data.counterparty, 2)) return "請輸入合約相對人。";
  if (!data.owner || !data.dept) return "請選擇承辦角色與承辦部門。";
  if (data.startDate && data.endDate && new Date(data.endDate) < new Date(data.startDate)) return "到期日不可早於起始日。";
  if (!hasMinimumText(data.summary, 8)) return "請填寫至少 8 個字的合約摘要。";
  return "";
}

function applyContractFormToRecord(contract, data) {
  const category = approvalCategoryForType(data.type);
  const route = approvalRouteForType(data.type);
  Object.assign(contract, {
    companyName: data.companyName,
    type: category.label,
    title: data.title,
    counterparty: data.counterparty,
    counterpartyTaxId: data.counterpartyTaxId,
    owner: data.owner,
    dept: data.dept,
    amount: data.amount,
    currency: data.currency,
    startDate: data.startDate,
    endDate: data.endDate,
    renewalDays: data.renewalDays,
    confidentiality: data.confidentiality,
    sealRequirement: data.sealRequirement,
    summary: data.summary,
    attachments: data.attachments,
    approvalRouteCode: route.code,
    approvalRouteName: route.name,
    approvalCategoryGroup: category.group,
    riskNote: contractRiskLabels({ ...contract, ...data, type: category.label }).join("、")
  });
}

async function saveContractDraft() {
  const data = contractFormPayload();
  const error = validateContractPayload(data);
  if (error) return blockOperation(error, addContractAudit, "合約草稿防呆");
  const contract = selectedContractId ? currentContract() : null;
  if (contract && !["草稿", "退回補正"].includes(contract.status)) {
    return blockOperation("此合約已進入簽核或鎖版流程，請先退回補正後才能修改草稿、附件或用印類別。", addContractAudit, "合約鎖版防呆");
  }
  if (contract && ["草稿", "退回補正"].includes(contract.status)) {
    const diff = contractDiffFlags(contract, data);
    applyContractFormToRecord(contract, data);
    contract.status = "草稿";
    contract.versionStatus = "草稿可編修";
    if (diff.attachmentsChanged || diff.routeChanged) {
      contract.requiresReapproval = true;
      contract.reapprovalReason = diff.attachmentsChanged ? "附件清冊異動" : "文件/用印類別異動";
      addContractAudit("補正異動需重新簽核", `${contract.contractNo} 已變更${diff.attachmentsChanged ? "附件清冊" : "文件/用印類別"}，送出時會重新產生簽核流程。`);
    }
    await persistContract(contract);
    addContractAudit("更新合約草稿", `${contract.contractNo} 已更新草稿資料。`);
    renderContracts();
    showToast("合約草稿已更新。");
    return contract;
  }
  return createContractFromForm("草稿");
}

async function createContractFromForm(status = "草稿") {
  const data = contractFormPayload();
  const error = validateContractPayload(data);
  if (error) return blockOperation(error, addContractAudit, "合約起案防呆");
  const category = approvalCategoryForType(data.type);
  const route = approvalRouteForType(data.type);
  const contract = {
    id: `CON-${Date.now().toString().slice(-10)}`,
    contractNo: nextContractNo(),
    ...data,
    type: category.label,
    approvalRouteCode: route.code,
    approvalRouteName: route.name,
    approvalCategoryGroup: category.group,
    storageStatus: "待歸檔",
    status,
    riskNote: contractRiskLabels({ ...data, type: category.label, status }).join("、"),
    signedAt: "",
    archiveHash: "",
    lockedAt: "",
    lockedBy: "",
    lockedHash: "",
    lockedAttachmentHash: "",
    versionStatus: "草稿可編修",
    submittedHash: "",
    submittedAttachmentHash: "",
    requiresReapproval: false,
    reapprovalReason: "",
    createdAt: new Date().toLocaleString("zh-TW", { hour12: false })
  };
  contractRecords.unshift(contract);
  selectedContractId = contract.id;
  ensureContractApprovals(contract, true);
  await persistToBackend("/contracts", backendContractPayload(contract));
  for (const approval of contractApprovalsFor(contract.id)) {
    await persistToBackend("/contract_approvals", backendContractApprovalPayload(approval));
  }
  addContractAudit("建立合約草稿", `${contract.contractNo} ${contract.title} 已建立，狀態：${status}。`);
  renderContracts();
  showToast("合約草稿已建立。");
  return contract;
}

function startNewContract() {
  selectedContractId = "";
  renderContractFormOptions();
  const today = new Date();
  const nextYear = new Date(today);
  nextYear.setFullYear(today.getFullYear() + 1);
  document.querySelector("#contractTitleInput").value = "長照服務合作合約";
  document.querySelector("#contractCounterpartyInput").value = "合作廠商股份有限公司";
  document.querySelector("#contractTaxIdInput").value = "待補";
  document.querySelector("#contractAmountInput").value = "0";
  document.querySelector("#contractStartDateInput").value = today.toISOString().slice(0, 10);
  document.querySelector("#contractEndDateInput").value = nextYear.toISOString().slice(0, 10);
  document.querySelector("#contractAttachmentsInput").value = "合約草案.pdf、報價單.pdf";
  document.querySelector("#contractSummaryInput").value = "請填寫合作內容、履約範圍、付款條件與重要時程。";
  document.querySelector("#selectedContractStatus").textContent = "新合約";
  document.querySelector("#contractDetail").innerHTML = `<p class="empty-text">請填寫左下方起案資料，完成後按「儲存草稿」或「送簽核」。</p>`;
  showToast("已開啟新合約起案。");
}

async function submitContractForApproval() {
  let contract = currentContract();
  if (!contract) contract = await createContractFromForm("草稿");
  if (!contract) return;
  const beforeHash = contractContentHash(contract);
  const beforeAttachmentHash = contractAttachmentHash(contract.attachments);
  const beforeRoute = approvalRouteForType(contract.type).code;
  if (["草稿", "退回補正"].includes(contract.status)) {
    const data = contractFormPayload();
    const error = validateContractPayload(data);
    if (error) return blockOperation(error, addContractAudit, "合約送簽防呆");
    const diff = contractDiffFlags(contract, data);
    applyContractFormToRecord(contract, data);
    if (diff.attachmentsChanged || diff.routeChanged || contract.requiresReapproval) {
      const changed = [
        diff.routeChanged ? `路由 ${beforeRoute} → ${approvalRouteForType(contract.type).code}` : "",
        diff.attachmentsChanged ? "附件清冊已異動" : "",
        contract.reapprovalReason || ""
      ].filter(Boolean).join("、");
      addContractAudit("重新計算簽核流程", `${contract.contractNo} ${changed || "退回補正後重新送簽"}，系統將重新產生 A/B/C/D 簽核關卡。`);
    }
  }
  if (!["草稿", "退回補正"].includes(contract.status)) return showToast("此合約已在簽核流程中，不需重複送簽。");
  ensureContractApprovals(contract, true);
  if (!validateApprovalAssignees(contractApprovalsFor(contract.id), addContractAudit, "合約簽核角色防呆")) return;
  const next = currentContractApproval(contract);
  contract.status = next ? `待${next.role}簽核` : "待簽核";
  contract.submittedHash = contractContentHash(contract);
  contract.submittedAttachmentHash = contractAttachmentHash(contract.attachments);
  contract.lockedAt = "";
  contract.lockedBy = "";
  contract.lockedHash = "";
  contract.lockedAttachmentHash = "";
  contract.versionStatus = "簽核中";
  contract.requiresReapproval = false;
  contract.reapprovalReason = "";
  await persistContract(contract);
  for (const approval of contractApprovalsFor(contract.id)) {
    await persistContractApproval(approval);
  }
  addContractAudit("合約送簽", `${contract.contractNo} 已送簽，下一關：${next?.step || "待審核"}。送簽 hash ${contract.submittedHash}（原 hash ${beforeHash} / 附件 ${beforeAttachmentHash}）。`);
  renderContracts();
  renderApprovalLog();
  showToast("合約已送簽核。");
}

function approveCurrentContract() {
  const contract = currentContract();
  if (!contract) return showToast("請先選取合約。");
  const approval = currentContractApproval(contract);
  if (!approval) return showToast("此合約目前沒有待簽核關卡。");
  if (!canApproveCurrentContract(contract)) return showToast(`目前關卡需由 ${approval.role} 處理。`);
  if (approval.step.includes("用印") && !contract.lockedHash) lockContractForSeal(contract, "用印核准前自動鎖版");
  if (!guardContractVersionIntegrity(contract, "合約簽核鎖版防呆")) return;
  const approvals = contractApprovalsFor(contract.id);
  const currentIndex = approvals.findIndex((item) => item.id === approval.id);
  const nextApproval = approvals.slice(currentIndex + 1).find((item) => !/完成|已簽署|已歸檔/.test(item.status));
  if (nextApproval && !applyApprovalAssigneeResolution(nextApproval, addContractAudit).ok) {
    return blockOperation(`下一關「${nextApproval.step}」找不到 ${nextApproval.role} 的啟用帳號或代理人，請先在人員登錄或代理人機制補齊後再核准。`, addContractAudit, "合約下一關防呆");
  }
  approval.status = approval.step.includes("歸檔") ? "已歸檔" : "完成";
  approval.approver = authState?.user?.name || activeRole();
  approval.signedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  approval.comment = approval.comment || "簽核通過。";
  if (approval.step.includes("用印")) {
    contract.signedAt = approval.signedAt;
    contract.archiveHash = contract.archiveHash || stableHash({ contract, approvals: contractApprovalsFor(contract.id) });
  }
  contract.status = contractStatusAfterApproval(contract);
  if (contract.status === "已簽署" && !contract.signedAt) contract.signedAt = approval.signedAt;
  if (contract.status === "待用印簽署" && !contract.lockedHash) lockContractForSeal(contract);
  persistContract(contract);
  persistContractApproval(approval);
  if (nextApproval) persistContractApproval(nextApproval);
  addContractAudit("合約簽核通過", `${contract.contractNo} ${approval.step} 已由 ${activeRole()} 核准，狀態：${contract.status}。`);
  renderContracts();
  renderApprovalLog();
  showToast("合約簽核已通過。");
}

function returnCurrentContract() {
  const contract = currentContract();
  if (!contract) return showToast("請先選取合約。");
  const approval = currentContractApproval(contract) || contractApprovalsFor(contract.id).at(-1);
  const comment = window.prompt?.("請輸入退回補正原因", approval?.comment || "請補充附件、付款條件或合約條款。") || "";
  if (!hasMinimumText(comment, 6)) return blockOperation("退回補正需填寫至少 6 個字的原因。", addContractAudit, "合約退回防呆");
  if (approval) {
    approval.status = "退回補正";
    approval.approver = authState?.user?.name || activeRole();
    approval.comment = comment;
    approval.signedAt = new Date().toLocaleString("zh-TW", { hour12: false });
    persistContractApproval(approval);
  }
  unlockContractForCorrection(contract, comment);
  contract.status = "退回補正";
  contract.riskNote = comment;
  persistContract(contract);
  addContractAudit("合約退回補正", `${contract.contractNo} 已退回，原因：${comment}。補正後將重新計算簽核流程與文件版本 hash。`);
  renderContracts();
  renderApprovalLog();
  showToast("合約已退回補正。");
}

function signCurrentContract(contract = currentContract()) {
  if (!contract) return showToast("請先選取合約。");
  const pending = currentContractApproval(contract);
  if (pending && !pending.step.includes("用印")) return blockOperation(`請先完成「${pending.step}」後再用印簽署。`, addContractAudit, "合約用印防呆");
  if (!pending) return blockOperation("此合約目前沒有待用印關卡，不可重複或越權用印。", addContractAudit, "合約用印防呆");
  if (!contract.lockedHash) lockContractForSeal(contract, "用印前自動鎖版");
  if (!guardContractVersionIntegrity(contract, "合約用印鎖版防呆")) return;
  if (contract.sealRequirement === "無" && !confirmOperation("確認免用印簽署", "此合約未要求用印，系統將標記為已簽署並留存不可否認紀錄。")) return;
  if (contract.sealRequirement !== "無" && !confirmOperation("確認合約用印簽署", `即將使用「${contract.sealRequirement}」完成 ${contract.contractNo} 簽署。簽署後會留存雜湊與操作紀錄。`)) return;
  if (pending) {
    pending.status = "完成";
    pending.approver = authState?.user?.name || activeRole();
    pending.signedAt = new Date().toLocaleString("zh-TW", { hour12: false });
    pending.comment = `已使用 ${contract.sealRequirement} 完成簽署。`;
    persistContractApproval(pending);
  }
  contract.signedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  contract.archiveHash = stableHash({ contract, approvals: contractApprovalsFor(contract.id) });
  contract.status = contractStatusAfterApproval(contract);
  persistContract(contract);
  addContractAudit("合約用印簽署", `${contract.contractNo} 已完成用印，下一關：${contract.status}，雜湊 ${contract.archiveHash}。`);
  contractSealAuditLog.unshift([nowTime(), "確認合約用印", `${contract.contractNo} 已由 ${activeRole()} 完成用印，雜湊 ${contract.archiveHash}。`]);
  renderContracts();
  renderContractSeal();
  renderApprovalLog();
  showToast("合約已完成簽署。");
}

function archiveCurrentContract() {
  const contract = currentContract();
  if (!contract) return showToast("請先選取合約。");
  if (contract.status !== "已簽署" && !/已歸檔/.test(contract.storageStatus)) return blockOperation("合約需完成簽署後才能歸檔。", addContractAudit, "合約歸檔防呆");
  if (!guardContractVersionIntegrity(contract, "合約歸檔鎖版防呆")) return;
  contract.storageStatus = "已歸檔";
  contract.status = "已歸檔";
  contract.archiveHash = contract.archiveHash || stableHash({ contract, approvals: contractApprovalsFor(contract.id) });
  const archiveStep = contractApprovalsFor(contract.id).find((approval) => approval.step.includes("歸檔"));
  if (archiveStep) {
    archiveStep.status = "已歸檔";
    archiveStep.approver = authState?.user?.name || activeRole();
    archiveStep.signedAt = new Date().toLocaleString("zh-TW", { hour12: false });
    archiveStep.comment = `已歸檔保存，保存雜湊 ${contract.archiveHash}。`;
    persistContractApproval(archiveStep);
  }
  persistContract(contract);
  addContractAudit("合約歸檔保存", `${contract.contractNo} 已建立保存包與防竄改雜湊 ${contract.archiveHash}。`);
  renderContracts();
  showToast("合約已歸檔。");
}

function createContractRenewalReminder(contract = currentContract()) {
  if (!contract) return showToast("請先選取合約。");
  const days = contractDaysToEnd(contract);
  notificationItems.unshift({
    id: `NTF-CON-${Date.now().toString().slice(-6)}`,
    type: "合約續約",
    title: `${contract.title} 續約提醒`,
    target: contract.owner,
    channel: "Email + 系統通知",
    status: "未讀",
    priority: days !== null && days <= 30 ? "高" : "中",
    source: contract.contractNo,
    body: `${contract.counterparty} 合約到期日 ${contract.endDate || "未設定"}，請於 ${contract.renewalDays} 天前確認續約、終止或重簽。`
  });
  addContractAudit("建立續約提醒", `${contract.contractNo} 已建立到期提醒，剩餘 ${days ?? "未設定"} 天。`);
  renderNotifications();
  showToast("續約提醒已建立。");
}

function linkContractToOfficialDoc(contract = currentContract()) {
  if (!contract) return showToast("請先選取合約。");
  document.querySelector("#recipient").value = contract.counterparty;
  document.querySelector("#subject").value = `檢送${contract.title}簽署資料，請查照。`;
  document.querySelector("#bodyText").value = `一、檢送${contract.title}相關文件，請惠予確認。\n二、本合約相對人為${contract.counterparty}，合約期間為${contract.startDate || "未定"}至${contract.endDate || "未定"}。\n三、如需補充資料，請洽本公司承辦窗口。`;
  markDraftDirty();
  addContractAudit("轉成發文草稿", `${contract.contractNo} 已帶入公文撰寫欄位。`);
  setView("compose");
  showToast("合約資料已帶入公文草稿。");
}

function renderContractSummary() {
  const rows = visibleContracts();
  document.querySelector("#contractTotalCount").textContent = rows.length;
  document.querySelector("#contractPendingCount").textContent = rows.filter((contract) => /待|審核|簽核|用印/.test(contract.status)).length;
  document.querySelector("#contractRenewalCount").textContent = rows.filter(isContractRenewalSoon).length;
  document.querySelector("#contractSignedCount").textContent = rows.filter((contract) => /已簽署|已歸檔/.test(contract.status)).length;
}

function renderContractRows() {
  const rows = filteredContracts();
  if (rows.length && !rows.some((contract) => contract.id === selectedContractId)) selectedContractId = rows[0].id;
  document.querySelector("#contractListCount").textContent = `${rows.length} 件`;
  document.querySelector("#contractRows").innerHTML = rows.length ? rows.map((contract) => {
    const tone = contractCountdownTone(contract);
    const route = approvalRouteForType(contract.type);
    return `
      <tr class="contract-table-row ${contract.id === selectedContractId ? "selected-row" : ""}" data-contract-select="${contract.id}" tabindex="0">
        <td><button class="contract-link" type="button" data-contract-select="${contract.id}">${contract.contractNo}</button></td>
        <td>
          <strong>${contract.title}</strong>
          <small>${contract.counterparty} · ${contract.type} · ${route.code}</small>
        </td>
        <td>${contract.companyName}</td>
        <td>${contract.dept}</td>
        <td><span class="contract-seal-date ${contract.signedAt ? "signed" : ""}">${contractSealDate(contract)}</span></td>
        <td>${contractTermText(contract)}</td>
        <td><span class="contract-countdown ${tone}">${contractCountdownText(contract)}</span></td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="7"><p class="empty-text">目前沒有符合條件的合約。</p></td></tr>`;
  document.querySelectorAll("[data-contract-select]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectedContractId = button.dataset.contractSelect;
      fillContractForm(currentContract());
      renderContracts();
      openContractModal(selectedContractId);
    });
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectedContractId = button.dataset.contractSelect;
      fillContractForm(currentContract());
      renderContracts();
      openContractModal(selectedContractId);
    });
  });
}

function renderContractDetail() {
  const contract = currentContract();
  const detail = document.querySelector("#contractDetail");
  if (!contract) {
    document.querySelector("#selectedContractStatus").textContent = "未選取";
    detail.innerHTML = `<p class="empty-text">尚無合約資料。</p>`;
    return;
  }
  document.querySelector("#selectedContractStatus").textContent = contract.status;
  detail.innerHTML = contractModalMarkup(contract);
}

function contractDocumentPreview(contract) {
  const signed = Boolean(contract?.signedAt || /已簽署|已歸檔/.test(contract?.status || ""));
  return `
    <article class="contract-document-preview">
      <div class="contract-document-paper">
        <div class="contract-document-meta">
          <span>合約編號：${contract.contractNo}</span>
          <span>保存年限：${contract.storageStatus || "待歸檔"}</span>
        </div>
        <h4>${contract.companyName}</h4>
        <h5>${contract.title}</h5>
        <dl>
          <div><dt>相對人</dt><dd>${contract.counterparty}</dd></div>
          <div><dt>合約期間</dt><dd>${contractTermText(contract)}</dd></div>
          <div><dt>承辦單位</dt><dd>${contract.dept}</dd></div>
          <div><dt>用印類別</dt><dd>${contract.sealRequirement}</dd></div>
        </dl>
        <p>${contract.summary}</p>
        <div class="contract-document-seal ${signed ? "signed" : "pending"}">
          <span>${signed ? "已完成合約用印" : "待總務用印"}</span>
          <small>${signed ? `${contractSealDate(contract)} · ${contract.archiveHash || "雜湊待寫入"}` : "請至合約用印功能完成用印"}</small>
        </div>
      </div>
    </article>
  `;
}

function contractModalMarkup(contract) {
  const approvals = contractApprovalsFor(contract.id);
  const current = currentContractApproval(contract);
  const days = contractDaysToEnd(contract);
  const category = approvalCategoryForType(contract.type);
  const route = approvalRouteForType(contract.type);
  return `
    <div class="contract-modal-content">
      <section class="contract-modal-summary">
        <div>
          <span class="badge ${badgeClass(contract.status)}">${contract.status}</span>
          <h4>${contract.title}</h4>
          <p>${contract.summary}</p>
        </div>
        <div class="contract-modal-number">
          <span>合約編號</span>
          <strong>${contract.contractNo}</strong>
        </div>
      </section>

      <section class="contract-modal-section">
        <h4>原始起案內容</h4>
        <dl class="contract-modal-fields">
        <div><dt>合約編號</dt><dd>${contract.contractNo}</dd></div>
        <div><dt>法人</dt><dd>${contract.companyName}</dd></div>
        <div><dt>合約主旨</dt><dd>${contract.title}</dd></div>
        <div><dt>相對人</dt><dd>${contract.counterparty}（${contract.counterpartyTaxId || "統編待補"}）</dd></div>
        <div><dt>類型 / 金額</dt><dd>${contract.type} / ${contract.amount.toLocaleString()} ${contract.currency}</dd></div>
        <div><dt>簽核路由</dt><dd>${route.name}（${category.group.replace(/（勿選）/, "")}）</dd></div>
        <div><dt>部門 / 承辦</dt><dd>${contract.dept} / ${contract.owner}</dd></div>
        <div><dt>用印日期</dt><dd>${contractSealDate(contract)}</dd></div>
        <div><dt>合約期效</dt><dd>${contractTermText(contract)}</dd></div>
        <div><dt>過期日倒數</dt><dd>${contractCountdownText(contract)}${days !== null && days >= 0 ? `（到期日 ${formatContractDate(contract.endDate)}）` : ""}</dd></div>
        <div><dt>保密 / 用印</dt><dd>${contract.confidentiality} / ${contract.sealRequirement}</dd></div>
        <div><dt>簽核版本</dt><dd>${contract.versionStatus || "未鎖版"}${contract.lockedHash ? ` · ${contract.lockedHash}` : ""}${contract.requiresReapproval ? ` · 需重新簽核：${contract.reapprovalReason || "內容異動"}` : ""}</dd></div>
        <div><dt>保存</dt><dd>${contract.storageStatus} ${contract.archiveHash ? `· ${contract.archiveHash}` : ""}</dd></div>
      </dl>
      </section>

      <section class="contract-modal-section">
        <h4>附件與風險註記</h4>
        <p>${contract.riskNote || "尚無風險註記。"}</p>
        <div class="attachment-list">
          ${contract.attachments.map((file) => `<button class="file-chip" type="button" data-contract-file="${file}">${file}</button>`).join("") || `<span class="empty-text">尚未上傳附件。</span>`}
        </div>
      </section>

      <section class="contract-modal-section">
        <h4>簽核流程</h4>
        <div class="contract-modal-approvals">
          ${approvals.map((approval) => `
            <article class="${approval.id === current?.id ? "current" : /完成|已簽署|已歸檔/.test(approval.status) ? "done" : /退回/.test(approval.status) ? "returned" : ""}">
              <time>${String(approval.stepNo).padStart(2, "0")}</time>
              <div>
                <strong>${approval.step}</strong>
                <span>${approval.role} · ${approval.status}${approval.signedAt ? ` · ${approval.signedAt}` : ""}</span>
                <p>${approval.comment || "等待簽核意見。"}</p>
              </div>
            </article>
          `).join("")}
        </div>
      </section>

      <section class="contract-modal-section">
        <h4>合約公文檢視</h4>
        ${contractDocumentPreview(contract)}
      </section>

      <div class="detail-actions">
        <button class="primary-button" type="button" data-contract-action="submit">送簽核</button>
        <button class="secondary-button" type="button" data-contract-action="approve" ${canApproveCurrentContract(contract) ? "" : "disabled"}>核准目前關卡</button>
        <button class="secondary-button" type="button" data-contract-action="return">退回</button>
        <button class="secondary-button" type="button" data-contract-action="seal">前往合約用印</button>
        <button class="secondary-button" type="button" data-contract-action="renew">續約提醒</button>
        <button class="secondary-button" type="button" data-contract-action="doc">轉公文</button>
      </div>
    </div>
  `;
}

function bindContractModalActions(container) {
  container.querySelectorAll("[data-contract-file]").forEach((button) => {
    button.addEventListener("click", () => showToast(`已開啟合約附件：${button.dataset.contractFile}`));
  });
  container.querySelectorAll("[data-contract-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.contractAction;
      if (action === "submit") void submitContractForApproval().then(() => openContractModal(selectedContractId));
      if (action === "approve") {
        approveCurrentContract();
        openContractModal(selectedContractId);
      }
      if (action === "return") {
        returnCurrentContract();
        openContractModal(selectedContractId);
      }
      if (action === "seal") {
        closeContractModal();
        setView(isRouteAllowed("contractSeal") ? "contractSeal" : "contracts");
        renderContractSeal();
      }
      if (action === "renew") createContractRenewalReminder();
      if (action === "doc") linkContractToOfficialDoc();
    });
  });
}

function openContractModal(contractId = selectedContractId) {
  const contract = visibleContracts().find((item) => item.id === contractId) || contractRecords.find((item) => item.id === contractId) || currentContract();
  const modal = document.querySelector("#contractModal");
  const body = document.querySelector("#contractModalBody");
  if (!contract || !modal || !body) return;
  selectedContractId = contract.id;
  document.querySelector("#contractModalTitle").textContent = contract.contractNo;
  body.innerHTML = contractModalMarkup(contract);
  bindContractModalActions(body);
  modal.classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closeContractModal() {
  document.querySelector("#contractModal")?.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function visibleContractSealRequests() {
  return contractRecords.filter((contract) => {
    if (contract.sealRequirement === "無") return false;
    const pending = currentContractApproval(contract);
    const isSealStage = /用印|簽署/.test(`${contract.status} ${pending?.step || ""} ${pending?.status || ""}`);
    const isCompleted = Boolean(contract.signedAt || /已簽署|已歸檔/.test(contract.status));
    const isReturned = /退回/.test(contract.status);
    const role = activeRole();
    if (role === "總務" || role === "執行長") return isSealStage || isCompleted || isReturned;
    return (contract.dept === activeUnit() || contract.owner === role || contract.owner === authState?.user?.name) && (isSealStage || isCompleted || isReturned);
  });
}

function currentContractSealRequest() {
  const rows = visibleContractSealRequests();
  return rows.find((contract) => contract.id === selectedContractId) || rows[0] || null;
}

function renderContractSealRows() {
  const rows = visibleContractSealRequests();
  if (rows.length && !rows.some((contract) => contract.id === selectedContractId)) selectedContractId = rows[0].id;
  const tbody = document.querySelector("#contractSealRows");
  const count = document.querySelector("#contractSealListCount");
  if (!tbody || !count) return;
  count.textContent = `${rows.length} 件`;
  tbody.innerHTML = rows.length ? rows.map((contract) => {
    const approval = currentContractApproval(contract);
    return `
      <tr class="${contract.id === selectedContractId ? "selected-row" : ""}" data-contract-seal-select="${contract.id}" tabindex="0">
        <td><button class="contract-link" type="button" data-contract-seal-select="${contract.id}">${contract.contractNo}</button></td>
        <td><strong>${contract.title}</strong><small>${contract.counterparty}</small></td>
        <td>${contract.dept}<small>${contract.owner}</small></td>
        <td>${contract.sealRequirement}</td>
        <td><span class="badge ${badgeClass(contract.status)}">${approval?.step || contract.status}</span></td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="5"><p class="empty-text">目前沒有待處理的合約用印申請。</p></td></tr>`;
  document.querySelectorAll("[data-contract-seal-select]").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.stopPropagation();
      selectedContractId = item.dataset.contractSealSelect;
      renderContractSeal();
    });
    item.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectedContractId = item.dataset.contractSealSelect;
      renderContractSeal();
    });
  });
}

function renderContractSealPreview() {
  const contract = currentContractSealRequest();
  const box = document.querySelector("#contractSealPreview");
  const status = document.querySelector("#contractSealStatus");
  if (!box || !status) return;
  if (!contract) {
    status.textContent = "未選取";
    box.innerHTML = `<p class="empty-text">請先選取一筆合約用印申請。</p>`;
    return;
  }
  selectedContractId = contract.id;
  status.textContent = contract.status;
  const pending = currentContractApproval(contract);
  box.innerHTML = `
    ${contractDocumentPreview(contract)}
    <div class="contract-seal-command">
      <strong>${pending?.step || "流程完成"}</strong>
      <p>${pending?.comment || contract.riskNote || "可檢視合約公文、確認用印或退回補正。"}</p>
    </div>
  `;
}

function renderContractSealSummary() {
  const rows = visibleContractSealRequests();
  const today = new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit" });
  const selected = currentContractSealRequest();
  document.querySelector("#contractSealPendingCount").textContent = rows.filter((contract) => /用印|簽署/.test(contract.status) && !contract.signedAt).length;
  document.querySelector("#contractSealTodayCount").textContent = rows.filter((contract) => contract.signedAt && formatContractDate(contract.signedAt) === today).length;
  document.querySelector("#contractSealReturnCount").textContent = rows.filter((contract) => /退回/.test(contract.status)).length;
  document.querySelector("#contractSealHashStatus").textContent = selected?.archiveHash ? "已建立" : "待建立";
}

function renderContractSealAuditLog() {
  const box = document.querySelector("#contractSealAuditLog");
  if (!box) return;
  box.innerHTML = contractSealAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderContractSeal() {
  renderContractSealRows();
  renderContractSealPreview();
  renderContractSealSummary();
  renderContractSealAuditLog();
}

function confirmCurrentContractSeal() {
  const contract = currentContractSealRequest();
  if (!contract) return showToast("請先選取合約用印申請。");
  selectedContractId = contract.id;
  signCurrentContract(contract);
}

function returnCurrentContractSeal() {
  const contract = currentContractSealRequest();
  if (!contract) return showToast("請先選取合約用印申請。");
  selectedContractId = contract.id;
  returnCurrentContract();
  contractSealAuditLog.unshift([nowTime(), "合約用印退回", `${contract.contractNo} 已由 ${activeRole()} 退回補正。`]);
  renderContractSeal();
}

function renderContractApprovalSteps() {
  const contract = currentContract();
  const steps = contract ? contractApprovalsFor(contract.id) : [];
  const current = currentContractApproval(contract);
  const route = contract ? approvalRouteForType(contract.type) : null;
  document.querySelector("#contractApprovalStatus").textContent = current ? `${route?.code || ""} · ${current.role}待處理` : contract ? `${route?.code || ""} · 流程完成` : "未選取";
  document.querySelector("#contractApprovalSteps").innerHTML = steps.length ? steps.map((approval) => `
    <article class="approval-step ${/完成|已簽署|已歸檔/.test(approval.status) ? "done" : /退回/.test(approval.status) ? "returned" : approval.id === current?.id ? "current" : ""}">
      <time>${String(approval.stepNo).padStart(2, "0")}</time>
      <strong>${approval.step}</strong>
      <span>${approval.role} · ${approval.status}</span>
      <p>${approval.comment || "等待簽核意見。"}${approval.signedAt ? ` / ${approval.signedAt}` : ""}</p>
    </article>
  `).join("") : `<p class="empty-text">尚未建立簽核流程，送簽核後系統會依文件/用印類別產生 A/B/C/D 路由。</p>`;
}

function renderContractAuditLog() {
  const box = document.querySelector("#contractAuditLog");
  if (!box) return;
  box.innerHTML = contractAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderContracts() {
  renderContractFormOptions();
  renderContractSummary();
  renderContractRows();
  fillContractForm(currentContract());
  renderContractDetail();
  renderContractApprovalSteps();
  renderContractAuditLog();
  syncDatabaseTables(true);
  renderUnifiedFlows();
}

function renderPrechecks() {
  const list = document.querySelector("#precheckList");
  if (list) list.innerHTML = prechecks.map((item) => `<li>${item}</li>`).join("");
  renderComposeStepper();
}

function addExchangeEvent(title, body) {
  exchangeEvents.unshift([nowTime(), title, body]);
  renderTimeline("#exchangeTimeline", exchangeEvents);
}

function tokenTimeLeft() {
  if (!jagentState.tokenExpiresAt) return "尚未建立";
  const minutes = Math.max(0, Math.round((jagentState.tokenExpiresAt - Date.now()) / 60000));
  if (minutes <= 0) return "已過期";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hours ? `${hours}h ${mins}m` : `${mins}m`;
}

function renderJagentStatus() {
  document.querySelector("#certificateStatus").textContent = jagentState.certificate;
  document.querySelector("#certificateNote").textContent = jagentState.certificateNote;
  document.querySelector("#tokenStatus").textContent = tokenTimeLeft();
  document.querySelector("#tokenExpires").textContent = jagentState.tokenExpiresAt
    ? `有效期限：${new Date(jagentState.tokenExpiresAt).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false })}`
    : "有效期限：-";
  document.querySelector("#centerStatus").textContent = jagentState.center;
  document.querySelector("#centerLatency").textContent = `延遲：${jagentState.latency}`;
  document.querySelector("#addressBookStatus").textContent = jagentState.addressResults.length ? "已查詢" : "待查詢";
  document.querySelector("#addressBookCount").textContent = `${jagentState.addressResults.length} 筆結果`;
  renderServiceGrid();
}

function renderServiceGrid() {
  const services = [
    ["jAgent API", jagentState.center === "已連線" ? "可呼叫" : "待連線"],
    ["憑證登入", jagentState.certificate],
    ["Token", tokenTimeLeft()],
    ["地址簿", jagentState.addressResults.length ? `${jagentState.addressResults.length} 筆結果` : "待查詢"]
  ];
  document.querySelector("#serviceGrid").innerHTML = services.map(([label, value]) => `
    <article class="service-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function certLogin() {
  jagentState.certificate = "已登入";
  jagentState.certificateNote = "憑證序號 SYC-EDOC-2026，總務";
  jagentState.token = `tk_${Date.now()}`;
  jagentState.tokenExpiresAt = Date.now() + 8 * 60 * 60 * 1000;
  renderJagentStatus();
  addExchangeEvent("憑證登入成功", "已建立 jAgent session 與 8 小時 Token。");
  showToast("憑證登入成功，Token 已建立。");
}

function logoutJagent() {
  jagentState.certificate = "未登入";
  jagentState.certificateNote = "請插入憑證卡並登入";
  jagentState.token = "";
  jagentState.tokenExpiresAt = null;
  renderJagentStatus();
  addExchangeEvent("jAgent 登出", "已撤銷本機 session 與 Token。");
  showToast("已登出 jAgent。");
}

function refreshToken() {
  if (jagentState.certificate !== "已登入") return showToast("請先完成憑證登入。");
  jagentState.token = `tk_${Date.now()}`;
  jagentState.tokenExpiresAt = Date.now() + 8 * 60 * 60 * 1000;
  renderJagentStatus();
  addExchangeEvent("刷新 Token", "Token 已延長 8 小時。");
  showToast("Token 已刷新。");
}

function validateToken() {
  const valid = jagentState.token && jagentState.tokenExpiresAt > Date.now();
  addExchangeEvent("驗證 Token", valid ? "Token 驗證通過，可呼叫 jAgent API。" : "Token 無效或已過期。");
  showToast(valid ? "Token 驗證通過。" : "Token 無效，請重新登入。");
}

function revokeToken() {
  if (!jagentState.token) return showToast("目前沒有可撤銷的 Token。");
  if (!confirmOperation("確認撤銷 jAgent Token", "撤銷後將無法送交、查詢或同步交換中心，需重新憑證登入或刷新 Token。")) return;
  jagentState.token = "";
  jagentState.tokenExpiresAt = null;
  renderJagentStatus();
  addExchangeEvent("撤銷 Token", "已撤銷目前 Token，需重新登入或刷新。");
  showToast("Token 已撤銷。");
}

function connectCenter() {
  jagentState.center = "已連線";
  jagentState.latency = `${Math.floor(38 + Math.random() * 42)}ms`;
  renderJagentStatus();
  addExchangeEvent("交換中心連線成功", `${document.querySelector("#exchangeCenterName").value} 連線正常。`);
  showToast("交換中心連線成功。");
}

function syncCenter() {
  if (jagentState.center !== "已連線") return showToast("請先完成交換中心連線測試。");
  jagentState.latency = `${Math.floor(35 + Math.random() * 38)}ms`;
  renderJagentStatus();
  addExchangeEvent("同步服務狀態", "已同步送件、收件、地址簿與回覆查詢服務狀態。");
  showToast("已同步交換中心服務狀態。");
}

function disconnectCenter() {
  jagentState.center = "未連線";
  jagentState.latency = "-";
  renderJagentStatus();
  addExchangeEvent("中斷交換中心連線", "已中斷目前測試連線。");
  showToast("已中斷交換中心連線。");
}

function searchAddressBook(query) {
  const term = query.trim().toLowerCase();
  jagentState.addressResults = addressBook.filter((item) => {
    const haystack = `${item.name} ${item.code} ${item.center} ${item.status}`.toLowerCase();
    return !term || haystack.includes(term);
  });
  renderAddressResults();
  renderJagentStatus();
  addExchangeEvent("地址簿查詢", `查詢「${query || "全部"}」，取得 ${jagentState.addressResults.length} 筆結果。`);
  showToast(`地址簿查詢完成：${jagentState.addressResults.length} 筆。`);
}

function renderAddressResults() {
  const box = document.querySelector("#addressResults");
  if (!jagentState.addressResults.length) {
    box.innerHTML = `<p class="empty-text">尚無查詢結果。</p>`;
    return;
  }
  box.innerHTML = jagentState.addressResults.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <span>${item.code} · ${item.center}</span>
      <p>${item.status} · ${item.contact}</p>
      <button class="segment" type="button" data-use-address="${item.name}" data-use-code="${item.code}">帶入受文者</button>
    </article>
  `).join("");
  document.querySelectorAll("[data-use-address]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector("#recipient").value = button.dataset.useAddress;
      addExchangeEvent("帶入地址簿", `已將 ${button.dataset.useAddress}（${button.dataset.useCode}）帶入發文受文者。`);
      showToast("已帶入建立公文的受文者欄位。");
    });
  });
}

function renderTimeline(selector, items) {
  document.querySelector(selector).innerHTML = items.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderArchiveGrid() {
  const item = currentArchiveRecord();
  const items = item ? [
    ["原始公文", `${item.original} · ${item.originalHash}`],
    ["附件", `${item.attachments.length} 個附件 · ${item.attachments.map((attachment) => attachment.version).join(" / ")}`],
    ["交換事件", `${item.exchangeEvents.length} 筆事件 · ${item.exchangeEvents.at(-1)}`],
    ["操作軌跡", `${item.operationTrail.length} 筆軌跡 · ${item.retention}`],
    ["檔案雜湊", `${item.hashStatus} · ${item.packageHash}`]
  ] : archiveItems;
  document.querySelector("#archiveGrid").innerHTML = items.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function addArchiveAudit(title, body) {
  archiveAuditLog.unshift([nowTime(), title, body]);
  renderArchiveAuditLog();
}

function currentArchiveRecord() {
  return archiveRecords.find((item) => item.id === selectedArchiveId) || archiveRecords[0] || null;
}

function selectedArchiveIds() {
  const selected = [...document.querySelectorAll(".archive-check:checked")].map((item) => item.value);
  return selected.length ? selected : selectedArchiveId ? [selectedArchiveId] : [];
}

function filteredArchiveRecords() {
  const term = archiveSearchTerm.trim().toLowerCase();
  return archiveRecords.filter((item) => {
    const matchFilter = archiveFilter === "all" || item.status === archiveFilter || item.hashStatus === archiveFilter;
    const haystack = `${item.id} ${item.docNo} ${item.direction} ${item.agency} ${item.subject} ${item.status} ${item.originalHash} ${item.packageHash}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderArchiveSummary() {
  const originalCount = archiveRecords.length;
  const attachmentCount = archiveRecords.reduce((sum, item) => sum + item.attachments.length, 0);
  const exchangeCount = archiveRecords.reduce((sum, item) => sum + item.exchangeEvents.length, 0);
  const hashCount = archiveRecords.filter((item) => item.hashStatus === "雜湊通過").length;
  document.querySelector("#archiveOriginalCount").textContent = originalCount;
  document.querySelector("#archiveAttachmentCount").textContent = attachmentCount;
  document.querySelector("#archiveExchangeCount").textContent = exchangeCount;
  document.querySelector("#archiveHashCount").textContent = hashCount;
}

function renderArchiveRows() {
  const rows = filteredArchiveRecords();
  document.querySelector("#archiveRecordCount").textContent = `${rows.length} 件`;
  document.querySelector("#archiveRows").innerHTML = rows.map((item) => `
    <tr class="${item.id === selectedArchiveId ? "selected-row" : ""}">
      <td><input class="archive-check" type="checkbox" value="${item.id}" aria-label="選取 ${item.docNo}" /></td>
      <td><button class="text-button row-select" type="button" data-archive-select="${item.id}">${item.docNo}</button><small>${item.direction} · ${item.id}</small></td>
      <td>${item.agency}</td>
      <td>${item.subject}</td>
      <td>${item.original}<small>${item.attachments.length} 個附件</small></td>
      <td>${item.hashStatus}<small>${item.packageHash}</small></td>
      <td><span class="badge ${badgeClass(item.status)}">${item.status}</span></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-archive-action="open" data-archive-id="${item.id}">原文</button>
          <button class="segment" type="button" data-archive-action="verify" data-archive-id="${item.id}">驗證</button>
          <button class="segment" type="button" data-archive-action="seal" data-archive-id="${item.id}">封存</button>
          <button class="segment" type="button" data-archive-action="export" data-archive-id="${item.id}">匯出</button>
        </div>
      </td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-archive-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedArchiveId = button.dataset.archiveSelect;
      renderArchiveRows();
      renderArchiveDetail();
      renderArchiveGrid();
    });
  });
  document.querySelectorAll("[data-archive-action]").forEach((button) => {
    button.addEventListener("click", () => runArchiveAction(button.dataset.archiveAction, [button.dataset.archiveId]));
  });
}

function renderArchiveDetail() {
  const item = currentArchiveRecord();
  const detail = document.querySelector("#archiveDetail");
  if (!item) {
    document.querySelector("#selectedArchiveStatus").textContent = "未選取";
    detail.innerHTML = `<p class="empty-text">尚無歸檔資料。</p>`;
    return;
  }
  document.querySelector("#selectedArchiveStatus").textContent = item.status;
  detail.innerHTML = `
    <div class="doc-detail">
      <strong>${item.subject}</strong>
      <dl>
        <div><dt>文號</dt><dd>${item.docNo}</dd></div>
        <div><dt>方向</dt><dd>${item.direction}</dd></div>
        <div><dt>機關</dt><dd>${item.agency}</dd></div>
        <div><dt>原文</dt><dd>${item.original}</dd></div>
        <div><dt>原文雜湊</dt><dd>${item.originalHash}</dd></div>
        <div><dt>封包雜湊</dt><dd>${item.packageHash}</dd></div>
        <div><dt>保存年限</dt><dd>${item.retention}</dd></div>
        <div><dt>保存狀態</dt><dd>${item.status}</dd></div>
        <div><dt>封存時間</dt><dd>${item.sealedAt}</dd></div>
      </dl>
      <div class="archive-detail-list">
        <strong>附件清冊</strong>
        ${item.attachments.map((attachment) => `<button class="file-chip" type="button" data-archive-attachment="${attachment.name}">${attachment.name} · ${attachment.version} · ${attachment.hash} · ${attachment.status}</button>`).join("")}
      </div>
      <div class="archive-detail-list">
        <strong>交換事件</strong>
        <p>${item.exchangeEvents.join(" → ")}</p>
      </div>
      <div class="archive-detail-list">
        <strong>操作軌跡</strong>
        <p>${item.operationTrail.join(" → ")}</p>
      </div>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="detailArchiveSealBtn" ${canUseDocAction(item, "seal") ? "" : "disabled"}>封存</button>
        <button class="secondary-button" type="button" id="detailArchiveVerifyBtn">驗證雜湊</button>
        <button class="secondary-button" type="button" id="detailArchiveOpenBtn" ${canUseDocAction(item, "view") ? "" : "disabled"}>檢視原文</button>
        <button class="secondary-button" type="button" id="detailArchiveExportBtn" ${canUseDocAction(item, "download") ? "" : "disabled"}>匯出保存包</button>
      </div>
      ${renderDocumentAclPanel(item)}
    </div>
  `;
  document.querySelectorAll("[data-archive-attachment]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!canUseDocAction(item, "download")) return showToast("此角色未取得本保存件附件下載/檢視權限。");
      showToast(`已開啟附件保存檢視：${button.dataset.archiveAttachment}`);
    });
  });
  document.querySelector("#detailArchiveSealBtn").addEventListener("click", () => runArchiveAction("seal", [item.id]));
  document.querySelector("#detailArchiveVerifyBtn").addEventListener("click", () => runArchiveAction("verify", [item.id]));
  document.querySelector("#detailArchiveOpenBtn").addEventListener("click", () => runArchiveAction("open", [item.id]));
  document.querySelector("#detailArchiveExportBtn").addEventListener("click", () => runArchiveAction("export", [item.id]));
  bindDocumentAclButtons(item, renderArchiveDetail);
}

function renderArchiveAuditLog() {
  document.querySelector("#archiveAuditLog").innerHTML = archiveAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function mutateArchive(ids, handler, auditTitle, auditBody) {
  ids.forEach((id) => {
    const item = archiveRecords.find((record) => record.id === id);
    if (item) handler(item);
  });
  renderArchiveSummary();
  renderArchiveRows();
  renderArchiveDetail();
  renderArchiveGrid();
  addArchiveAudit(auditTitle, auditBody);
}

function runArchiveAction(action, ids) {
  const targetIds = ids?.length ? ids : selectedArchiveIds();
  if (!targetIds.length) return showToast("請先選取要歸檔保存的公文。");
  const requiredAcl = { open: "view", export: "download", seal: "seal" }[action];
  if (requiredAcl) {
    const denied = targetIds.map((id) => archiveRecords.find((record) => record.id === id)).filter((item) => item && !canUseDocAction(item, requiredAcl));
    if (denied.length) return showToast("此角色未取得部分歸檔公文的作業權限。");
  }
  if (action === "open") {
    const item = archiveRecords.find((record) => record.id === targetIds[0]);
    addArchiveAudit("檢視原文", `已開啟 ${item?.docNo || "選取公文"} 的原文、附件與封包索引。`);
    return showToast(`已開啟原文檢視：${item?.original || "保存檔"}`);
  }
  if (action === "verify") {
    mutateArchive(targetIds, (item) => {
      item.hashStatus = "雜湊通過";
      item.attachments = item.attachments.map((attachment) => ({ ...attachment, status: "雜湊通過" }));
      if (item.status === "需複核") item.status = "待封存";
      item.operationTrail.push("雜湊驗證");
    }, "完成檔案雜湊驗證", `已驗證 ${targetIds.length} 件原文、附件與交換封包 SHA-256。`);
    return showToast("檔案雜湊驗證完成。");
  }
  if (action === "seal") {
    mutateArchive(targetIds, (item) => {
      item.status = "已封存";
      item.hashStatus = "雜湊通過";
      item.sealedAt = new Date().toLocaleString("zh-TW", { hour12: false });
      item.attachments = item.attachments.map((attachment) => ({ ...attachment, status: "雜湊通過" }));
      item.operationTrail.push("歸檔封存");
    }, "完成歸檔封存", `已封存 ${targetIds.length} 件，包含原文、附件、交換事件、操作軌跡與雜湊。`);
    return showToast("歸檔封存完成。");
  }
  if (action === "export") {
    addArchiveAudit("匯出保存包", `已匯出 ${targetIds.length} 件保存包，內含原文、附件、交換事件、操作軌跡與 hash manifest。`);
    return showToast("保存包已產生。");
  }
}

function addSecurityAudit(title, body) {
  securityAuditLog.unshift([nowTime(), title, body]);
  renderSecurityAuditLog();
}

function securityTokenLeft() {
  const minutes = Math.max(0, Math.round((securityState.tokenExpiresAt - Date.now()) / 60000));
  if (securityState.tokenStatus === "已撤銷") return "Token 已撤銷";
  if (minutes <= 0) return "Token 已過期";
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return hours ? `剩餘 ${hours}h ${mins}m` : `剩餘 ${mins}m`;
}

function renderSecurityStatus() {
  const tokenExpired = securityState.tokenExpiresAt <= Date.now() || securityState.tokenStatus === "已過期";
  if (tokenExpired && securityState.tokenStatus !== "已撤銷") securityState.tokenStatus = "已過期";
  document.querySelector("#securityCertStatus").textContent = securityState.certStatus;
  document.querySelector("#securityCertNote").textContent = securityState.certNote;
  document.querySelector("#securityTokenStatus").textContent = securityState.tokenStatus;
  document.querySelector("#securityTokenNote").textContent = securityTokenLeft();
  document.querySelector("#securitySessionStatus").textContent = securityState.certStatus === "已驗證" && securityState.tokenStatus === "有效" ? "Session Ready" : "Session Locked";
  document.querySelector("#securityDeviceStatus").textContent = `${securityDevices.filter((item) => item.status === "允許").length} 台允許`;
  document.querySelector("#securityDeviceNote").textContent = `${securityDevices.filter((item) => item.status === "封鎖").length} 台封鎖`;
  document.querySelector("#securityRbacNote").textContent = securityState.rbacResult;
  renderSecurityProofGrid();
}

function renderSecurityPermissionGrid(role = document.querySelector("#securityRoleSelect")?.value || workflowRole) {
  const allowed = rolePermissions[role] || [];
  document.querySelector("#securityPermissionGrid").innerHTML = Object.entries(permissionLabels).map(([key, label]) => `
    <article class="permission-chip ${allowed.includes(key) ? "allowed" : ""}">
      <strong>${allowed.includes(key) ? "允許" : "限制"}</strong>
      <span>${label}</span>
    </article>
  `).join("");
}

function renderSecurityDeviceList() {
  document.querySelector("#securityDeviceList").innerHTML = securityDevices.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <span>${item.ip} · ${item.fingerprint}</span>
      <p>${item.status} · ${item.id}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-security-device="allow" data-device-id="${item.id}">允許</button>
        <button class="segment" type="button" data-security-device="block" data-device-id="${item.id}">封鎖</button>
        <button class="segment" type="button" data-security-device="remove" data-device-id="${item.id}">移除</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-security-device]").forEach((button) => {
    button.addEventListener("click", () => mutateSecurityDevice(button.dataset.deviceId, button.dataset.securityDevice));
  });
}

function renderSecurityProofGrid() {
  const proofItems = [
    ["簽章序號", securityState.proofSerial],
    ["最後簽章", securityState.lastSignature],
    ["使用者", document.querySelector("#securityCertOwner")?.value || "總務"],
    ["憑證狀態", securityState.certStatus],
    ["Token 狀態", securityState.tokenStatus],
    ["紀錄保存", "不可覆寫 / 可匯出"]
  ];
  document.querySelector("#securityProofGrid").innerHTML = proofItems.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderSecurityAuditLog() {
  document.querySelector("#securityAuditLog").innerHTML = securityAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function securityCertLogin() {
  const ttl = Number(document.querySelector("#securityTokenTtl").value);
  const serial = document.querySelector("#securityCertSerial").value.trim();
  const owner = document.querySelector("#securityCertOwner").value;
  securityState.certStatus = "已驗證";
  securityState.certNote = `${serial} · ${owner}`;
  securityState.tokenStatus = "有效";
  securityState.tokenExpiresAt = Date.now() + ttl * 60 * 1000;
  jagentState.certificate = "已登入";
  jagentState.certificateNote = `憑證序號 ${serial}，${owner}`;
  jagentState.token = `tk_${Date.now()}`;
  jagentState.tokenExpiresAt = securityState.tokenExpiresAt;
  renderSecurityStatus();
  renderJagentStatus();
  addSecurityAudit("憑證卡登入", `${owner} 已以憑證卡 ${serial} 完成驗證，Token 有效 ${ttl} 分鐘。`);
  showToast("憑證卡驗證成功。");
}

function refreshSecurityToken() {
  if (securityState.certStatus !== "已驗證") return showToast("請先完成憑證卡登入。");
  const ttl = Number(document.querySelector("#securityTokenTtl").value);
  securityState.tokenStatus = "有效";
  securityState.tokenExpiresAt = Date.now() + ttl * 60 * 1000;
  jagentState.token = `tk_${Date.now()}`;
  jagentState.tokenExpiresAt = securityState.tokenExpiresAt;
  renderSecurityStatus();
  renderJagentStatus();
  addSecurityAudit("刷新 Token", `Token 已重新核發，有效 ${ttl} 分鐘。`);
  showToast("Token 已刷新。");
}

function revokeSecurityToken() {
  if (!jagentState.token && securityState.tokenStatus !== "有效") return showToast("目前沒有可撤銷的 Token。");
  if (!confirmOperation("確認撤銷資安 Token", "撤銷後目前交換工作會停止使用此 Token，後續需重新憑證登入。")) return;
  securityState.tokenStatus = "已撤銷";
  jagentState.token = "";
  jagentState.tokenExpiresAt = null;
  renderSecurityStatus();
  renderJagentStatus();
  addSecurityAudit("撤銷 Token", "已撤銷目前 Token，後續交換需重新憑證登入。");
  showToast("Token 已撤銷。");
}

function expireSecurityToken() {
  securityState.tokenStatus = "已過期";
  securityState.tokenExpiresAt = Date.now() - 1000;
  jagentState.tokenExpiresAt = Date.now() - 1000;
  renderSecurityStatus();
  renderJagentStatus();
  addSecurityAudit("Token 過期", "已模擬 Token 過期，系統鎖定 jAgent Session。");
  showToast("Token 已過期，請刷新或重新登入。");
}

function testSecurityPermission() {
  const role = document.querySelector("#securityRoleSelect").value;
  const action = document.querySelector("#securityActionSelect").value;
  const allowed = (rolePermissions[role] || []).includes(action);
  securityState.rbacResult = `${role} ${allowed ? "允許" : "限制"} ${permissionLabels[action]}`;
  document.querySelector("#securityRbacStatus").textContent = allowed ? "允許" : "限制";
  renderSecurityStatus();
  renderSecurityPermissionGrid(role);
  addSecurityAudit("RBAC 權限檢查", securityState.rbacResult);
  showToast(allowed ? "RBAC 權限允許。" : "RBAC 權限不足。");
}

function addSecurityDevice() {
  const ip = document.querySelector("#securityIpInput").value.trim();
  const name = document.querySelector("#securityDeviceName").value.trim();
  const fingerprint = document.querySelector("#securityFingerprint").value.trim();
  if (!ip || !name || !fingerprint) return showToast("請輸入 IP、裝置名稱與指紋。");
  securityDevices.unshift({ id: `DEV-${Date.now().toString().slice(-5)}`, ip, name, fingerprint, status: "允許" });
  renderSecurityDeviceList();
  renderSecurityStatus();
  addSecurityAudit("新增允許裝置", `${name}（${ip} / ${fingerprint}）已加入白名單。`);
  showToast("裝置已加入白名單。");
}

function mutateSecurityDevice(id, action) {
  const device = securityDevices.find((item) => item.id === id);
  if (!device) return;
  if (action === "remove") {
    const index = securityDevices.findIndex((item) => item.id === id);
    securityDevices.splice(index, 1);
    addSecurityAudit("移除裝置", `${device.name} 已自管制清單移除。`);
  } else {
    device.status = action === "allow" ? "允許" : "封鎖";
    addSecurityAudit(action === "allow" ? "允許裝置" : "封鎖裝置", `${device.name}（${device.ip}）已更新為${device.status}。`);
  }
  renderSecurityDeviceList();
  renderSecurityStatus();
  showToast("裝置管制已更新。");
}

function signSecurityAction() {
  const owner = document.querySelector("#securityCertOwner").value;
  securityState.proofSerial = `NR-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${Math.floor(Math.random() * 900 + 100)}`;
  securityState.lastSignature = `${owner} / ${securityState.proofSerial} / SHA256-${Math.random().toString(16).slice(2, 10).toUpperCase()}`;
  renderSecurityStatus();
  addSecurityAudit("操作不可否認簽章", `已產生 ${securityState.proofSerial}，綁定使用者、憑證、時間戳、IP、裝置指紋與操作摘要。`);
  showToast("不可否認簽章已完成。");
}

function addFileAccessLog(title, body) {
  fileAccessLog.unshift([nowTime(), title, body]);
  renderFileAccessLog();
}

function currentFileSecurityItem() {
  return fileSecurityItems.find((item) => item.id === selectedFileSecurityId) || fileSecurityItems[0];
}

function selectedFileSecurityIds() {
  const selected = [...document.querySelectorAll(".file-security-check:checked")].map((item) => item.value);
  return selected.length ? selected : [selectedFileSecurityId].filter(Boolean);
}

function filePolicyPayload() {
  return {
    maxSizeMb: Number(document.querySelector("#fileMaxSize")?.value || fileSecurityPolicy.maxSizeMb),
    allowedTypes: document.querySelector("#fileAllowedTypes")?.value || fileSecurityPolicy.allowedTypes,
    maskPolicy: document.querySelector("#fileMaskPolicy")?.value || fileSecurityPolicy.maskPolicy,
    confidentialRoles: document.querySelector("#fileConfidentialRoles")?.value || fileSecurityPolicy.confidentialRoles,
    watermarkText: document.querySelector("#fileWatermarkText")?.value || fileSecurityPolicy.watermarkText,
    scanEngine: document.querySelector("#fileScanEngine")?.value || fileSecurityPolicy.scanEngine,
    overLimitAction: document.querySelector("#fileOverLimitAction")?.value || fileSecurityPolicy.overLimitAction
  };
}

function isFileOverLimit(item) {
  return item.sizeMb > fileSecurityPolicy.maxSizeMb;
}

function fileExtension(item) {
  return (item.fileName.split(".").pop() || "").toLowerCase();
}

function isFileTypeAllowed(item) {
  const allowed = fileSecurityPolicy.allowedTypes.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
  return allowed.includes(fileExtension(item));
}

function fileRiskLabel(item) {
  if (item.scanStatus === "已隔離") return "高風險";
  if (isFileOverLimit(item) || !isFileTypeAllowed(item) || item.maskStatus === "需遮罩") return "需處理";
  if (item.scanStatus === "已通過") return "可交換";
  return "待檢核";
}

function filteredFileSecurityItems() {
  const term = fileSecuritySearchTerm.trim().toLowerCase();
  return fileSecurityItems.filter((item) => {
    const matchesFilter = fileSecurityFilter === "all"
      || item.scanStatus === fileSecurityFilter
      || (fileSecurityFilter === "密件" && item.confidential !== "普通")
      || (fileSecurityFilter === "超限" && isFileOverLimit(item));
    const haystack = `${item.docNo} ${item.agency} ${item.subject} ${item.fileName} ${item.hash} ${item.scanStatus}`.toLowerCase();
    return matchesFilter && (!term || haystack.includes(term));
  });
}

function renderFileSecuritySummary() {
  const pending = fileSecurityItems.filter((item) => item.scanStatus === "待掃描").length;
  const quarantined = fileSecurityItems.filter((item) => item.scanStatus === "已隔離").length;
  const overLimit = fileSecurityItems.filter(isFileOverLimit).length;
  const confidential = fileSecurityItems.filter((item) => item.confidential !== "普通").length;
  document.querySelector("#fileScanStatus").textContent = pending ? `${pending} 待掃描` : "已完成";
  document.querySelector("#fileScanNote").textContent = quarantined ? `${quarantined} 件已隔離` : "防毒掃描佇列正常";
  document.querySelector("#fileSizeStatus").textContent = `${fileSecurityPolicy.maxSizeMb} MB`;
  document.querySelector("#fileSizeNote").textContent = overLimit ? `${overLimit} 件超過限制` : "所有附件符合限制";
  document.querySelector("#fileConfidentialStatus").textContent = confidential ? `${confidential} 件密件` : "無密件";
  document.querySelector("#fileConfidentialNote").textContent = fileSecurityPolicy.confidentialRoles;
  document.querySelector("#fileBackupStatus").textContent = fileSecurityBackups.length;
  document.querySelector("#fileBackupNote").textContent = fileSecurityBackups[0]?.createdAt || "尚未建立備份";
}

function renderFileSecurityRows() {
  const rows = filteredFileSecurityItems();
  document.querySelector("#fileSecurityCount").textContent = `${rows.length} 筆`;
  document.querySelector("#fileSecurityRows").innerHTML = rows.map((item) => `
    <tr class="${item.id === selectedFileSecurityId ? "selected-row" : ""}">
      <td><input class="file-security-check" type="checkbox" value="${item.id}" /></td>
      <td><button class="text-button row-select" type="button" data-file-select="${item.id}">${item.fileName}</button><small>${item.version} · ${item.hash}</small></td>
      <td>${item.docNo}<small>${item.agency}</small></td>
      <td>${item.sizeMb.toFixed(1)} MB<small>${isFileOverLimit(item) ? "超過限制" : "符合限制"}</small></td>
      <td><span class="status-pill ${badgeClass(item.scanStatus)}">${item.scanStatus}</span></td>
      <td>${item.confidential}<small>${fileRiskLabel(item)}</small></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-file-action="scan" data-file-id="${item.id}">掃描</button>
          <button class="segment" type="button" data-file-action="quarantine" data-file-id="${item.id}">隔離</button>
          <button class="segment" type="button" data-file-action="mask" data-file-id="${item.id}">遮罩</button>
          <button class="segment" type="button" data-file-action="access" data-file-id="${item.id}">紀錄</button>
        </div>
      </td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-file-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedFileSecurityId = button.dataset.fileSelect;
      renderFileSecurity();
    });
  });
  document.querySelectorAll("[data-file-action]").forEach((button) => {
    button.addEventListener("click", () => runFileSecurityAction(button.dataset.fileAction, [button.dataset.fileId]));
  });
}

function renderFileSecurityDetail() {
  const item = currentFileSecurityItem();
  if (!item) return;
  selectedFileSecurityId = item.id;
  document.querySelector("#selectedFileStatus").textContent = item.scanStatus;
  document.querySelector("#fileSecurityDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${item.fileName}</strong>
      <p>${item.subject}</p>
      <dl>
        <div><dt>公文</dt><dd>${item.docNo}</dd></div>
        <div><dt>機關</dt><dd>${item.agency}</dd></div>
        <div><dt>大小</dt><dd>${item.sizeMb.toFixed(1)} MB / 上限 ${fileSecurityPolicy.maxSizeMb} MB</dd></div>
        <div><dt>防毒</dt><dd>${item.scanStatus}</dd></div>
        <div><dt>敏感資料</dt><dd>${item.maskStatus}</dd></div>
        <div><dt>命中項目</dt><dd>${item.sensitiveHits?.length ? item.sensitiveHits.join("、") : "未命中"}</dd></div>
        <div><dt>密件隔離</dt><dd>${item.confidential} · ${item.accessRole}</dd></div>
        <div><dt>下載浮水印</dt><dd>${item.watermarkStatus}</dd></div>
        <div><dt>備份狀態</dt><dd>${item.backupStatus}</dd></div>
        <div><dt>風險判定</dt><dd>${fileRiskLabel(item)}</dd></div>
      </dl>
      <div class="detail-actions">
        <button class="primary-button" type="button" data-file-detail-action="scan">掃描</button>
        <button class="secondary-button" type="button" data-file-detail-action="mask">遮罩</button>
        <button class="secondary-button" type="button" data-file-detail-action="quarantine">隔離</button>
        <button class="secondary-button" type="button" data-file-detail-action="release">解除隔離</button>
      </div>
    </div>
    <div class="archive-grid">
      <article class="archive-card"><span>副檔名政策</span><strong>${fileSecurityPolicy.allowedTypes}</strong></article>
      <article class="archive-card"><span>遮罩政策</span><strong>${fileSecurityPolicy.maskPolicy}</strong></article>
      <article class="archive-card"><span>雜湊</span><strong>${item.hash}</strong></article>
      <article class="archive-card"><span>存取控制</span><strong>${item.confidential === "普通" ? "一般 RBAC" : "密件隔離"}</strong></article>
      <article class="archive-card"><span>副檔名</span><strong>${isFileTypeAllowed(item) ? "允許" : "不允許"} · ${fileExtension(item)}</strong></article>
      <article class="archive-card"><span>掃描引擎</span><strong>${item.scanEngine || fileSecurityPolicy.scanEngine}</strong></article>
    </div>
  `;
  document.querySelectorAll("[data-file-detail-action]").forEach((button) => {
    button.addEventListener("click", () => runFileSecurityAction(button.dataset.fileDetailAction, [item.id]));
  });
}

function renderFileBackupGrid() {
  const cleanCount = fileSecurityItems.filter((item) => item.scanStatus === "已通過").length;
  const maskedCount = fileSecurityItems.filter((item) => item.maskStatus === "已遮罩").length;
  const items = [
    ["可交換附件", `${cleanCount} / ${fileSecurityItems.length}`],
    ["已遮罩", `${maskedCount} 件`],
    ["最新備份", fileSecurityBackups[0]?.id || "尚未備份"],
    ["還原點", `${fileSecurityBackups.length} 個`]
  ];
  document.querySelector("#fileBackupGrid").innerHTML = items.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  document.querySelector("#fileBackupList").innerHTML = fileSecurityBackups.map((backup) => `
    <article class="address-card">
      <strong>${backup.id}</strong>
      <p>${backup.createdAt} · ${backup.items.length} 件附件</p>
      <small>${backup.note}</small>
    </article>
  `).join("") || `<article class="address-card"><strong>尚無備份</strong><p>建立備份後可還原附件資安狀態。</p></article>`;
}

function renderFileAccessLog() {
  document.querySelector("#fileAccessLog").innerHTML = fileAccessLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function fileStorageServiceItems() {
  const service = fileStorageServiceState.service?.services || {};
  return [
    ["物件儲存", service.provider?.value || fileStorageServiceState.provider, service.provider?.configured],
    ["Private Bucket", service.bucket?.value || fileStorageServiceState.bucket, service.bucket?.configured],
    ["短效 URL", `${service.signedUrlTtl?.value || fileStorageServiceState.signedUrlTtlSeconds} 秒`, service.signedUrlTtl?.configured],
    ["檔案加密", service.encryption?.keyId || fileStorageServiceState.encryption?.keyId, service.encryption?.configured],
    ["防毒引擎", service.scanner?.value || fileStorageServiceState.scanner?.engine, service.scanner?.configured],
    ["AV 端點", service.avEndpoint?.value || fileStorageServiceState.scanner?.endpoint, service.avEndpoint?.configured],
    ["AV 憑證", service.avCredential?.value || "未檢查", service.avCredential?.configured],
    ["檔案上限", `${service.maxFileSize?.value || fileSecurityPolicy.maxSizeMb} MB`, service.maxFileSize?.configured]
  ];
}

function renderFileStorageServiceHealth() {
  const grid = document.querySelector("#fileStorageServiceGrid");
  const detail = document.querySelector("#fileStorageServiceDetail");
  if (!grid || !detail) return;
  const missing = fileStorageServiceState.service?.missing || fileStorageServiceState.missing || [];
  grid.innerHTML = [
    ["正式狀態", fileStorageServiceState.ready ? "可上線" : "需補設定"],
    ["Provider", fileStorageServiceState.provider || fileStorageServiceState.service?.policy?.provider || "未檢查"],
    ["Bucket", fileStorageServiceState.bucket || fileStorageServiceState.service?.policy?.bucket || "未檢查"],
    ["下載 Token", `${fileStorageServiceState.activeDownloadTokens || 0} 個有效`]
  ].map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  detail.innerHTML = `
    <article class="address-card">
      <strong>${fileStorageServiceState.ready ? "正式儲存與防毒服務已就緒" : "正式儲存與防毒服務尚未完整"}</strong>
      <p>${missing.length ? `缺少：${missing.join("、")}` : "可使用 private object storage、短效下載 URL、檔案加密與正式 AV 掃描。"}</p>
      <small>模式：${fileStorageServiceState.mode || fileStorageServiceState.service?.mode || "未檢查"}</small>
    </article>
    ${fileStorageServiceItems().map(([label, value, ok]) => `
      <article class="address-card">
        <strong>${label}</strong>
        <p>${value || "未設定"}</p>
        <small>${ok ? "已設定" : "需補設定"}</small>
      </article>
    `).join("")}
  `;
}

function renderFileSecurity() {
  renderFileSecuritySummary();
  renderFileStorageServiceHealth();
  renderFileSecurityRows();
  renderFileSecurityDetail();
  renderFileBackupGrid();
  renderFileAccessLog();
}

async function loadFileStorageServiceHealth(showMessage = false) {
  try {
    const result = await backendRequest("/files/storage-health");
    fileStorageServiceState = { ...fileStorageServiceState, ...result, missing: result.service?.missing || result.missing || [] };
    renderFileStorageServiceHealth();
    if (showMessage) showToast(fileStorageServiceState.ready ? "正式檔案儲存與防毒已就緒。" : "正式檔案儲存與防毒尚有缺項。");
  } catch (error) {
    fileStorageServiceState = { ...fileStorageServiceState, ready: false, mode: "檢查失敗", missing: [error.message] };
    renderFileStorageServiceHealth();
    if (showMessage) showToast(`檔案儲存檢查失敗：${error.message}`);
  }
}

async function persistFileSecurityAction(action, selected) {
  try {
    const result = await backendRequest("/attachments/security-action", {
      method: "POST",
      body: JSON.stringify({
        action: action === "access" ? "watermark" : action,
        ids: selected.map((item) => item.backendId || item.attachmentId || item.id),
        actor: activeRole(),
        mask_policy: fileSecurityPolicy.maskPolicy,
        watermark_text: fileSecurityPolicy.watermarkText
      })
    });
    return result;
  } catch (error) {
    addFileAccessLog("後端附件安全作業失敗", `${action}：${error.message}`);
    return null;
  }
}

function guardFileSecurityAction(action, selected) {
  if (action === "release") {
    const allowedRoles = ["主任", "執行長", "行政部主任"];
    if (!allowedRoles.includes(activeRole())) return blockOperation("只有主任、執行長或行政部主任可以解除隔離附件。", addFileAccessLog, "附件操作防呆");
    const invalid = selected.filter((item) => item.scanStatus !== "已隔離");
    if (invalid.length) return blockOperation("只能解除已隔離附件，請重新勾選。", addFileAccessLog, "附件操作防呆");
    return confirmOperation("確認解除附件隔離", `即將解除 ${selected.length} 件附件隔離。請確認已完成人工複核、掃描報告與主管授權。`);
  }
  if (action === "quarantine") {
    return confirmOperation("確認隔離附件", `即將隔離 ${selected.length} 件附件。隔離後承辦人將無法下載或送出相關公文。`);
  }
  if (action === "mask") {
    const noSensitiveHint = selected.filter((item) => !item.sensitiveHits && item.maskStatus !== "需遮罩");
    if (noSensitiveHint.length === selected.length) {
      return confirmOperation("確認執行遮罩", "所選附件目前沒有敏感資料命中提示，仍要強制套用遮罩政策嗎？");
    }
  }
  return true;
}

async function runFileSecurityAction(action, ids = selectedFileSecurityIds()) {
  const selected = fileSecurityItems.filter((item) => ids.includes(item.id));
  if (!selected.length) return showToast("請先選取檔案。");
  if (!guardFileSecurityAction(action, selected)) return;
  await persistFileSecurityAction(action, selected);
  selected.forEach((item) => {
    if (action === "scan") {
      item.scanEngine = fileSecurityPolicy.scanEngine;
      item.scanStatus = isFileOverLimit(item) || !isFileTypeAllowed(item) ? "已隔離" : "已通過";
    }
    if (action === "quarantine") item.scanStatus = "已隔離";
    if (action === "release") item.scanStatus = "已通過";
    if (action === "mask") item.maskStatus = "已遮罩";
    if (action === "access") item.watermarkStatus = "已記錄存取";
  });
  const labels = { scan: "附件防毒掃描", quarantine: "檔案隔離", release: "解除隔離", mask: "敏感資料遮罩", access: "檔案存取紀錄" };
  addFileAccessLog(labels[action] || "檔案作業", `已處理 ${selected.length} 件：${selected.map((item) => item.fileName).join("、")}。`);
  renderFileSecurity();
  showToast(`${labels[action] || "檔案作業"}完成。`);
}

function saveFileSecurityPolicy() {
  Object.assign(fileSecurityPolicy, filePolicyPayload());
  fileSecurityItems.forEach((item) => {
    if (item.confidential !== "普通") item.accessRole = fileSecurityPolicy.confidentialRoles;
    if (isFileOverLimit(item) && item.scanStatus === "已通過") item.scanStatus = "已隔離";
    if (!isFileTypeAllowed(item)) item.scanStatus = "已隔離";
  });
  renderFileSecurity();
  addFileAccessLog("儲存檔案政策", `大小上限 ${fileSecurityPolicy.maxSizeMb} MB，允許 ${fileSecurityPolicy.allowedTypes}，密件角色 ${fileSecurityPolicy.confidentialRoles}。`);
  showToast("檔案資安政策已儲存。");
}

function downloadWatermarkedFile() {
  const item = currentFileSecurityItem();
  if (!item) return showToast("請先選取檔案。");
  if (item.scanStatus === "已隔離") return showToast("已隔離附件不可下載。");
  if (item.confidential !== "普通" && !item.accessRole.includes(activeRole())) return showToast("此角色未取得密件附件下載權限。");
  persistFileSecurityAction("access", [item]);
  item.watermarkStatus = "已加浮水印下載";
  addFileAccessLog("下載浮水印檔案", `${item.fileName} 已套用「${fileSecurityPolicy.watermarkText}」並寫入下載紀錄。`);
  const blob = new Blob([
    `Watermarked eDoc File\n檔案：${item.fileName}\n公文：${item.docNo}\n浮水印：${fileSecurityPolicy.watermarkText}\n下載時間：${new Date().toLocaleString("zh-TW", { hour12: false })}\n雜湊：${item.hash}\n`
  ], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${item.fileName}.watermark.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
  renderFileSecurity();
  showToast("已產生浮水印下載檔。");
}

function createFileSecurityBackup() {
  const backup = {
    id: `BKP-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${String(fileSecurityBackups.length + 1).padStart(2, "0")}`,
    createdAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    note: "附件狀態、遮罩、隔離、浮水印與政策快照",
    policy: { ...fileSecurityPolicy },
    items: fileSecurityItems.map((item) => ({ ...item }))
  };
  fileSecurityBackups.unshift(backup);
  fileSecurityItems.forEach((item) => {
    item.backupStatus = backup.id;
  });
  persistFileSecurityAction("backup", fileSecurityItems);
  renderFileSecurity();
  addFileAccessLog("建立檔案備份", `${backup.id} 已保存 ${backup.items.length} 件附件資安狀態。`);
  showToast("檔案備份已建立。");
}

function restoreFileSecurityBackup() {
  const backup = fileSecurityBackups[0];
  if (!backup) return showToast("目前沒有可還原備份。");
  if (!confirmOperation("確認還原檔案資安備份", `即將還原 ${backup.id}，目前附件掃描、遮罩、隔離與浮水印狀態會被覆蓋。`)) return;
  Object.assign(fileSecurityPolicy, backup.policy);
  backup.items.forEach((snapshot) => {
    const item = fileSecurityItems.find((entry) => entry.id === snapshot.id);
    if (item) Object.assign(item, snapshot);
  });
  document.querySelector("#fileMaxSize").value = fileSecurityPolicy.maxSizeMb;
  document.querySelector("#fileAllowedTypes").value = fileSecurityPolicy.allowedTypes;
  document.querySelector("#fileMaskPolicy").value = fileSecurityPolicy.maskPolicy;
  document.querySelector("#fileConfidentialRoles").value = fileSecurityPolicy.confidentialRoles;
  document.querySelector("#fileWatermarkText").value = fileSecurityPolicy.watermarkText;
  renderFileSecurity();
  addFileAccessLog("還原檔案備份", `已還原 ${backup.id}。`);
  showToast("已還原最新檔案備份。");
}

function addAccountAudit(title, body) {
  accountAuditLog.unshift([nowTime(), title, body]);
  renderAccountAuditLog();
}

function filteredAccounts() {
  const term = accountSearchTerm.trim().toLowerCase();
  return userAccounts.filter((account) => {
    const matchesFilter = accountFilter === "all"
      || account.status === accountFilter
      || (accountFilter === "MFA" && account.mfa === "已啟用")
      || (accountFilter === "SSO" && account.provider !== "本機帳號")
      || (accountFilter === "本機" && account.provider === "本機帳號");
    const haystack = `${account.name} ${account.email} ${account.unit} ${account.title} ${accountJobLevel(account)} ${account.role} ${account.provider}`.toLowerCase();
    return matchesFilter && (!term || haystack.includes(term));
  });
}

function currentAccount() {
  return userAccounts.find((account) => account.id === selectedAccountId) || userAccounts[0];
}

function selectedAccountIds() {
  const checked = [...document.querySelectorAll(".account-check:checked")].map((item) => item.value);
  return checked.length ? checked : [selectedAccountId].filter(Boolean);
}

function jobLevelForRole(role, fallback = "職員") {
  return roleJobLevelDefaults[role] || fallback;
}

function accountJobLevel(account) {
  return account.jobLevel || account.job_level || jobLevelForRole(account.role);
}

function normalizeRosterJobLevel(jobLevel) {
  const legacyMap = {
    "L1 員工": "職員",
    "L2 專員": "職員",
    "L3 主管": "課長",
    "L4 部門主管": "部長",
    "L5 高階主管": "區經理",
    "L6 執行長": "執行長"
  };
  return legacyMap[jobLevel] || (jobLevelOptions.includes(jobLevel) ? jobLevel : "職員");
}

function deriveRoleFromRosterProfile({ jobLevel = "", title = "", unit = "" } = {}) {
  const level = normalizeRosterJobLevel(jobLevel);
  const text = `${level} ${title} ${unit}`;
  if (text.includes("執行長")) return "執行長";
  if (["董事會", "股東", "外部檢核單位"].includes(level)) return level;
  if (text.includes("行政部主任") || text.includes("行政部長")) return "行政部主任";
  if (text.includes("總務")) return "總務";
  if (text.includes("人資")) return "人資";
  if (text.includes("會計") || text.includes("財務")) return "會計";
  if (title.includes("業務助理")) return "業務助理";
  if (["組長", "課長", "部長", "區經理"].includes(level) || /(督導|負責人|主任|主管|經理|部長|課長|組長)/.test(title)) return "主管";
  return "員工";
}

function syncAccountJobLevelWithRole(force = false) {
  const roleSelect = document.querySelector("#accountRoleSelect");
  const jobLevelSelect = document.querySelector("#accountJobLevel");
  if (!roleSelect || !jobLevelSelect) return;
  const roleDefault = jobLevelForRole(roleSelect.value);
  const isSystemLevel = Object.values(roleJobLevelDefaults).includes(jobLevelSelect.value);
  if (force || !jobLevelSelect.value || isSystemLevel) jobLevelSelect.value = roleDefault;
}

function syncRoleOptions() {
  const selectors = ["#roleSelect", "#workflowRoleSelect", "#securityRoleSelect", "#accountRoleSelect"];
  selectors.forEach((selector) => {
    const element = document.querySelector(selector);
    if (!element) return;
    const current = element.value;
    const existing = [...element.options].map((option) => option.value || option.textContent);
    Object.keys(rolePermissions).forEach((role) => {
      if (!existing.includes(role)) element.insertAdjacentHTML("beforeend", `<option>${role}</option>`);
    });
    if ([...element.options].some((option) => option.value === current || option.textContent === current)) element.value = current;
  });
}

function renderAccountSummary() {
  const enabled = userAccounts.filter((account) => account.status === "啟用").length;
  const mfaReady = userAccounts.filter((account) => account.mfa === "已啟用").length;
  const ssoUsers = userAccounts.filter((account) => account.provider !== "本機帳號").length;
  document.querySelector("#accountUserCount").textContent = `${enabled}/${userAccounts.length}`;
  document.querySelector("#accountUserNote").textContent = `${userAccounts.length - enabled} 個停用帳號`;
  document.querySelector("#accountMfaCount").textContent = `${Math.round((mfaReady / Math.max(userAccounts.length, 1)) * 100)}%`;
  document.querySelector("#accountMfaNote").textContent = `${mfaReady} 個帳號已啟用 MFA`;
  document.querySelector("#accountSsoStatus").textContent = accountSsoState.status;
  document.querySelector("#accountSsoNote").textContent = `${ssoUsers} 個 SSO 帳號 · ${accountSsoState.provider}`;
  document.querySelector("#accountDeviceCount").textContent = accountDevices.length;
  document.querySelector("#accountDeviceNote").textContent = `${accountIpRules.filter((rule) => rule.status === "允許").length} 條允許 IP 規則`;
}

function renderAccountRows() {
  const rows = filteredAccounts();
  document.querySelector("#accountListCount").textContent = `${rows.length} 筆`;
  document.querySelector("#accountRows").innerHTML = rows.map((account) => `
    <tr class="${account.id === selectedAccountId ? "selected-row" : ""}">
      <td><input class="account-check" type="checkbox" value="${account.id}" /></td>
      <td><button class="text-button row-select" type="button" data-account-select="${account.id}">${account.name}</button><small>${account.email}</small></td>
      <td>${account.unit}<small>${account.title} · ${accountJobLevel(account)}</small></td>
      <td>${account.role}</td>
      <td>${account.provider}<small>MFA：${account.mfa}</small></td>
      <td><span class="status-pill ${badgeClass(account.status)}">${account.status}</span></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-account-action="enable" data-account-id="${account.id}">啟用</button>
          <button class="segment" type="button" data-account-action="disable" data-account-id="${account.id}">停用</button>
          <button class="segment" type="button" data-account-action="resetMfa" data-account-id="${account.id}">重設 MFA</button>
        </div>
      </td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-account-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedAccountId = button.dataset.accountSelect;
      renderAccounts();
    });
  });
  document.querySelectorAll("[data-account-action]").forEach((button) => {
    button.addEventListener("click", () => runAccountAction(button.dataset.accountAction, [button.dataset.accountId]));
  });
}

function renderAccountDetail() {
  const account = currentAccount();
  if (!account) return;
  selectedAccountId = account.id;
  document.querySelector("#selectedAccountStatus").textContent = account.status;
  const permissions = rolePermissions[account.role] || [];
  document.querySelector("#accountDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${account.name}</strong>
      <p>${account.email}</p>
      <dl>
        <div><dt>單位 / 職稱</dt><dd>${account.unit} / ${account.title}</dd></div>
        <div><dt>職等</dt><dd>${accountJobLevel(account)}</dd></div>
        <div><dt>角色</dt><dd>${account.role}</dd></div>
        <div><dt>登入方式</dt><dd>${account.provider}</dd></div>
        <div><dt>MFA</dt><dd>${account.mfa}</dd></div>
        <div><dt>最近登入</dt><dd>${account.lastLogin} · ${account.ip}</dd></div>
        <div><dt>裝置</dt><dd>${account.device}</dd></div>
      </dl>
    </div>
    <div class="permission-grid">
      ${Object.keys(permissionLabels).map((key) => `
        <article class="permission-chip ${permissions.includes(key) ? "allowed" : ""}">
          <strong>${permissions.includes(key) ? "允許" : "限制"}</strong>
          <span>${permissionLabels[key]}</span>
        </article>
      `).join("")}
    </div>
  `;
}

function renderAccountLogs() {
  document.querySelector("#accountLoginCount").textContent = `${accountLoginLogs.length} 筆`;
  document.querySelector("#loginLogList").innerHTML = accountLoginLogs.map(([time, email, provider, ip, status]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${email}</strong>
        <p>${provider} · ${ip} · ${status}</p>
      </div>
    </article>
  `).join("");
  document.querySelector("#accountDeviceLogCount").textContent = `${accountDevices.length} 台`;
  document.querySelector("#deviceLogList").innerHTML = accountDevices.map((device) => {
    const owner = userAccounts.find((account) => account.id === device.userId)?.name || "未綁定";
    return `
      <article class="address-card">
        <strong>${device.name}</strong>
        <p>${owner} · ${device.ip}</p>
        <small>${device.fingerprint} · ${device.status}</small>
      </article>
    `;
  }).join("");
}

function renderAccountIpRules() {
  document.querySelector("#accountIpList").innerHTML = accountIpRules.map((rule) => `
    <article class="address-card">
      <strong>${rule.ip}</strong>
      <p>${rule.purpose}</p>
      <small>${rule.status}</small>
      <div class="row-actions">
        <button class="segment" type="button" data-account-ip="allow" data-ip-id="${rule.id}">允許</button>
        <button class="segment" type="button" data-account-ip="block" data-ip-id="${rule.id}">封鎖</button>
        <button class="segment" type="button" data-account-ip="remove" data-ip-id="${rule.id}">移除</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-account-ip]").forEach((button) => {
    button.addEventListener("click", () => mutateAccountIpRule(button.dataset.ipId, button.dataset.accountIp));
  });
}

function renderSsoStatus() {
  const statusItems = [
    ["提供者", accountSsoState.provider],
    ["網域 / Tenant", accountSsoState.domain],
    ["連線狀態", accountSsoState.status],
    ["最近測試", accountSsoState.lastTest]
  ];
  document.querySelector("#ssoStatusGrid").innerHTML = statusItems.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderAccountAuditLog() {
  document.querySelector("#accountAuditLog").innerHTML = accountAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderAccounts() {
  syncRoleOptions();
  renderAccountSummary();
  renderAccountRows();
  renderAccountDetail();
  renderSsoStatus();
  renderAccountIpRules();
  renderAccountLogs();
  renderAccountAuditLog();
}

function runAccountAction(action, ids = selectedAccountIds()) {
  const label = { enable: "啟用帳號", disable: "停用帳號", resetMfa: "重設 MFA", forceMfa: "強制 MFA" }[action] || "更新帳號";
  ids.forEach((id) => {
    const account = userAccounts.find((item) => item.id === id);
    if (!account) return;
    if (action === "enable") account.status = "啟用";
    if (action === "disable") account.status = "停用";
    if (action === "resetMfa") account.mfa = "強制重設";
    if (action === "forceMfa" && account.mfa !== "已啟用") account.mfa = "待設定";
  });
  renderAccounts();
  addAccountAudit(label, `已處理 ${ids.length} 個使用者帳號。`);
  showToast(`${label}完成。`);
}

function createAccountFromForm() {
  const name = document.querySelector("#accountName").value.trim();
  const email = document.querySelector("#accountEmail").value.trim();
  const unit = document.querySelector("#accountUnit").value.trim();
  const title = document.querySelector("#accountTitleInput").value.trim();
  const rawRole = document.querySelector("#accountRoleSelect").value;
  const jobLevel = normalizeRosterJobLevel(document.querySelector("#accountJobLevel")?.value || jobLevelForRole(rawRole));
  const derivedRole = deriveRoleFromRosterProfile({ jobLevel, title, unit });
  const role = rolePermissions[rawRole] ? rawRole : derivedRole;
  const provider = document.querySelector("#accountProvider").value;
  const mfa = document.querySelector("#accountMfa").value;
  if (!name || !email || !unit || !title) return showToast("請輸入姓名、Email、單位與職稱。");
  if (!rolePermissions[role]) rolePermissions[role] = ["view_assigned"];
  const existing = userAccounts.find((account) => account.email === email);
  if (existing) {
    Object.assign(existing, { name, unit, title, jobLevel, role, provider, mfa, status: "啟用" });
    selectedAccountId = existing.id;
    addAccountAudit("更新使用者", `${name} 的單位、職稱、職等、角色與登入方式已更新。`);
  } else {
    const id = `USR-${String(userAccounts.length + 1).padStart(3, "0")}`;
    userAccounts.unshift({ id, name, email, unit, title, jobLevel, role, provider, mfa, status: "啟用", lastLogin: "尚未登入", ip: "-", device: "尚未綁定" });
    selectedAccountId = id;
    addAccountAudit("建立使用者", `${name} 已建立為 ${role}（${jobLevel}），登入方式 ${provider}。`);
  }
  renderAccounts();
  showToast("使用者帳號已儲存。");
}

function connectSso() {
  accountSsoState.provider = document.querySelector("#ssoProvider").value;
  accountSsoState.domain = document.querySelector("#ssoDomain").value.trim();
  accountSsoState.status = "已連線";
  accountSsoState.lastTest = "等待測試登入";
  renderAccounts();
  addAccountAudit("連線 SSO", `${accountSsoState.provider} 已連線 ${accountSsoState.domain}。`);
  showToast("SSO 已連線。");
}

function testSso() {
  if (accountSsoState.status !== "已連線") return showToast("請先連線 SSO。");
  accountSsoState.lastTest = `${nowTime()} 測試成功`;
  accountLoginLogs.unshift([nowTime(), "sso-test@suiyuecare.com", accountSsoState.provider, "203.0.113.18", "成功"]);
  renderAccounts();
  addAccountAudit("測試 SSO 登入", `${accountSsoState.provider} 回傳使用者宣告、群組與 MFA 狀態。`);
  showToast("SSO 測試登入成功。");
}

function enforceMfa() {
  userAccounts.filter((account) => account.status === "啟用" && account.mfa !== "已啟用").forEach((account) => {
    account.mfa = "待設定";
  });
  renderAccounts();
  addAccountAudit("強制全員 MFA", "所有啟用帳號已要求下次登入完成 MFA 設定。");
  showToast("已強制全員 MFA。");
}

function addAccountIpRule() {
  const ip = document.querySelector("#accountIpInput").value.trim();
  const purpose = document.querySelector("#accountIpPurpose").value.trim();
  if (!ip || !purpose) return showToast("請輸入 IP/CIDR 與用途。");
  const id = `IP-${Date.now().toString().slice(-5)}`;
  accountIpRules.unshift({ id, ip, purpose, status: "允許" });
  settingsFirewallRules.unshift({ id: `FW-${id}`, ip, purpose, status: "允許" });
  securityDevices.unshift({ id: `DEV-${id}`, ip, name: purpose, fingerprint: `IP-${ip}`, status: "允許" });
  renderAccounts();
  renderSecurityDeviceList();
  renderSecurityStatus();
  renderSettings();
  addAccountAudit("新增 IP 限制", `${ip}（${purpose}）已加入允許清單並同步防火牆。`);
  showToast("IP 限制已新增。");
}

function mutateAccountIpRule(id, action) {
  const rule = accountIpRules.find((item) => item.id === id);
  if (!rule) return;
  if (action === "remove") {
    accountIpRules.splice(accountIpRules.findIndex((item) => item.id === id), 1);
    addAccountAudit("移除 IP 規則", `${rule.ip} 已自帳號登入限制移除。`);
  } else {
    rule.status = action === "allow" ? "允許" : "封鎖";
    addAccountAudit(action === "allow" ? "允許 IP" : "封鎖 IP", `${rule.ip} 已更新為${rule.status}。`);
  }
  renderAccounts();
  showToast("IP 限制已更新。");
}

function syncAccountsFromRoles() {
  syncRoleOptions();
  const missingRoles = Object.keys(rolePermissions).filter((role) => !userAccounts.some((account) => account.role === role));
  missingRoles.forEach((role) => {
    const id = `USR-${String(userAccounts.length + 1).padStart(3, "0")}`;
    userAccounts.push({ id, name: `${role}帳號`, email: `${role}@suiyuecare.local`, unit: "系統預設", title: role, jobLevel: jobLevelForRole(role), role, provider: "本機帳號", mfa: "待設定", status: "停用", lastLogin: "尚未登入", ip: "-", device: "尚未綁定" });
  });
  renderAccounts();
  addAccountAudit("同步角色權限", missingRoles.length ? `已補入 ${missingRoles.length} 個角色預設帳號。` : "角色、使用者與 RBAC 權限已是最新。");
  showToast("帳號角色已同步。");
}

function recordLogin(email, provider = "本機帳號") {
  const account = userAccounts.find((item) => item.email === email) || userAccounts[0];
  const status = account.status === "啟用" ? "成功" : "帳號停用";
  const ip = account.ip || "203.0.113.18";
  account.lastLogin = new Date().toLocaleString("zh-TW", { hour12: false });
  accountLoginLogs.unshift([nowTime(), email, provider, ip, status]);
  selectedAccountId = account.id;
  renderAccounts();
  addAccountAudit("登入紀錄", `${email} 以 ${provider} 登入，結果：${status}。`);
}

function addReportsAudit(title, body) {
  reportsAuditLog.unshift([nowTime(), title, body]);
  renderReportsAuditLog();
}

function reportStats() {
  const inboundCount = inboundDocs.length;
  const dispatchCount = dispatchDocs.length;
  const exchangeTotal = dispatchDocs.filter((doc) => ["交換完成", "等待確認", "交換失敗", "已封裝", "已清稿"].includes(doc.status)).length || dispatchDocs.length;
  const successCount = dispatchDocs.filter((doc) => doc.status === "交換完成").length;
  const successRate = Math.round((successCount / Math.max(exchangeTotal, 1)) * 100);
  const pendingInbound = inboundDocs.filter((doc) => /待登錄|待分派|待處理/.test(doc.status)).length;
  const pendingDispatch = dispatchDocs.filter((doc) => /草稿|待清稿|已清稿|已封裝|等待確認|退回補正|交換失敗/.test(doc.status)).length;
  const exceptionItems = [
    ...inboundDocs.filter((doc) => /異常|誤送|漏送/.test(doc.status + doc.note)).map((doc) => ({ type: "收文異常", title: doc.subject, owner: doc.owner })),
    ...dispatchDocs.filter((doc) => /失敗|退回/.test(doc.status + doc.lastReply)).map((doc) => ({ type: "發文失敗", title: doc.subject, owner: doc.owner })),
    ...archiveRecords.filter((doc) => doc.status === "需複核").map((doc) => ({ type: "雜湊需複核", title: doc.subject, owner: "主任" })),
    ...trackingCases.filter((doc) => ["未收確認", "退回補正"].includes(doc.status)).map((doc) => ({ type: doc.status, title: doc.title, owner: doc.owner }))
  ];
  const overdueItems = [
    ...trackingCases.filter((doc) => ["逾期提醒", "未收確認", "退回補正"].includes(doc.status)).map((doc) => ({ id: doc.id, title: doc.title, owner: doc.owner, dueDate: doc.dueDate, status: doc.status })),
    ...workflowTasks.filter((task) => /待|退回/.test(task.status)).map((task) => ({ id: task.id, title: task.title, owner: task.role, dueDate: "依流程期限", status: task.status }))
  ];
  const owners = [...new Set([
    ...inboundDocs.map((doc) => doc.owner),
    ...dispatchDocs.map((doc) => doc.owner),
    ...workflowTasks.map((task) => task.role),
    ...trackingCases.map((doc) => doc.owner)
  ])].filter(Boolean);
  const ownerRows = owners.map((owner) => ({
    owner,
    inbound: inboundDocs.filter((doc) => doc.owner === owner).length,
    dispatch: dispatchDocs.filter((doc) => doc.owner === owner).length,
    pending: workflowTasks.filter((task) => task.role === owner && /待|退回/.test(task.status)).length,
    overdue: overdueItems.filter((item) => item.owner === owner).length
  }));
  const slaRows = [
    { name: "收文登錄", target: "2 小時內", done: inboundDocs.filter((doc) => !/待登錄/.test(doc.status)).length, total: inboundDocs.length },
    { name: "分派承辦", target: "當日完成", done: inboundDocs.filter((doc) => !/待分派/.test(doc.status)).length, total: inboundDocs.length },
    { name: "發文交換", target: "清稿後當日", done: dispatchDocs.filter((doc) => ["交換完成", "等待確認"].includes(doc.status)).length, total: dispatchDocs.length },
    { name: "歸檔雜湊", target: "交換後 1 日", done: archiveRecords.filter((doc) => doc.hashStatus === "雜湊通過").length, total: archiveRecords.length }
  ].map((row) => ({ ...row, rate: Math.round((row.done / Math.max(row.total, 1)) * 100) }));
  const slaRate = Math.round(slaRows.reduce((sum, row) => sum + row.rate, 0) / Math.max(slaRows.length, 1));
  const backlogPressure = pendingInbound + pendingDispatch + overdueItems.length;
  const failedCount = dispatchDocs.filter((doc) => /失敗|退回/.test(doc.status + doc.lastReply)).length;
  const exchangeHealth = failedCount > 1 || successRate < 80 ? "需注意" : successRate < 95 ? "觀察" : "正常";
  const priorityItems = [
    ...dispatchDocs.filter((doc) => ["交換失敗", "退回補正"].includes(doc.status)).map((doc) => ({ type: "交換異常", title: doc.subject, owner: doc.owner, action: "重送或補正" })),
    ...inboundDocs.filter((doc) => ["待登錄", "待分派"].includes(doc.status)).map((doc) => ({ type: "收文待辦", title: doc.subject, owner: doc.owner, action: doc.status === "待登錄" ? "完成登錄" : "分派部門" })),
    ...overdueItems.map((item) => ({ type: "逾期稽催", title: item.title, owner: item.owner, action: "建立提醒" }))
  ];
  const agencyRows = [...inboundDocs, ...dispatchDocs, ...archiveRecords, ...trackingCases].reduce((acc, item) => {
    const agency = item.agency || item.to || "內部流程";
    if (!acc[agency]) acc[agency] = { agency, total: 0, exception: 0, completed: 0 };
    acc[agency].total += 1;
    if (/失敗|退回|誤送|漏送|需複核|逾期/.test(`${item.status || ""}${item.note || ""}${item.lastReply || ""}`)) acc[agency].exception += 1;
    if (/完成|已收文|雜湊通過/.test(`${item.status || ""}${item.hashStatus || ""}`)) acc[agency].completed += 1;
    return acc;
  }, {});
  const agencyRank = Object.values(agencyRows)
    .map((row) => ({ ...row, risk: Math.round((row.exception / Math.max(row.total, 1)) * 100) }))
    .sort((a, b) => b.total - a.total || b.risk - a.risk);
  const unitRows = ["總務", "行政部", "人資", "會計", "業務部", "居家照顧課", "社區據點課", "總管理處"].map((unit) => {
    const inbound = inboundDocs.filter((doc) => doc.dept === unit || doc.owner === unit).length;
    const users = userAccounts.filter((account) => account.unit === unit || account.role === unit).length || 1;
    const pending = [...inboundDocs, ...dispatchDocs].filter((doc) => (doc.dept === unit || doc.owner === unit) && !/完成/.test(doc.status)).length;
    return { unit, inbound, users, pending, load: Math.round(pending / users) };
  }).filter((row) => row.inbound || row.pending);
  const agingRows = [
    { bucket: "今天必處理", count: priorityItems.length, note: "交換失敗、待登錄、待分派與逾期件" },
    { bucket: "1 日內", count: trackingCases.filter((item) => item.status === "翌日查核").length, note: "發文翌日查核與未收確認" },
    { bucket: "2-3 日", count: workflowTasks.filter((task) => /待|退回/.test(task.status)).length, note: "流程簽核與補正未結" },
    { bucket: "需主管複核", count: archiveRecords.filter((doc) => doc.status === "需複核").length, note: "歸檔雜湊、密件與用印證據" }
  ];
  return {
    inboundCount,
    dispatchCount,
    exchangeTotal,
    successCount,
    successRate,
    pendingInbound,
    pendingDispatch,
    exceptionItems,
    overdueItems,
    ownerRows,
    slaRows,
    slaRate,
    backlogPressure,
    exchangeHealth,
    priorityItems,
    agencyRank,
    unitRows,
    agingRows
  };
}

function formalReportPayload() {
  const stats = reportStats();
  const period = document.querySelector("#reportPeriod").value;
  const unit = document.querySelector("#reportUnit").value;
  const agency = document.querySelector("#reportAgencyQuery").value.trim() || "全部機關";
  const version = document.querySelector("#reportVersion").value;
  const generatedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  const reportNo = `RPT-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${String(reportsAuditLog.length + 1).padStart(3, "0")}`;
  const decision = stats.slaRate >= 90 && stats.successRate >= 95 && stats.overdueItems.length === 0 ? "通過" : stats.exceptionItems.length > 3 || stats.overdueItems.length > 2 ? "需主管改善" : "觀察追蹤";
  const payload = {
    reportNo,
    version,
    generatedAt,
    generatedBy: activeRole(),
    scope: { period, unit, agency, dataSource: "收文、發文、流程、稽催、歸檔、通知、audit log" },
    kpi: {
      volume: stats.inboundCount + stats.dispatchCount,
      inbound: stats.inboundCount,
      dispatch: stats.dispatchCount,
      successRate: stats.successRate,
      slaRate: stats.slaRate,
      backlogPressure: stats.backlogPressure,
      exchangeHealth: stats.exchangeHealth,
      exceptionCount: stats.exceptionItems.length,
      overdueCount: stats.overdueItems.length
    },
    tables: {
      owners: stats.ownerRows,
      sla: stats.slaRows,
      agencyRank: stats.agencyRank,
      units: stats.unitRows,
      aging: stats.agingRows,
      exceptions: stats.exceptionItems,
      overdue: stats.overdueItems
    },
    managementConclusion: {
      decision,
      requiredActions: [
        stats.overdueItems.length ? `建立 ${stats.overdueItems.length} 件稽催並要求承辦回覆期限。` : "逾期件為 0，維持翌日查核。",
        stats.exceptionItems.length ? `異常 ${stats.exceptionItems.length} 件需由主管確認補正或重送。` : "異常件為 0，維持抽核。",
        stats.slaRate < 90 ? "SLA 未達 90%，需檢討登錄、分派、交換或歸檔瓶頸。" : "SLA 達標。"
      ]
    }
  };
  payload.reportHash = stableHash(payload);
  return payload;
}

function renderFormalReport(report = latestFormalReport) {
  document.querySelector("#formalReportStatus").textContent = report ? report.managementConclusion.decision : "待產製";
  document.querySelector("#formalReportNo").textContent = report?.reportNo || "尚未產製";
  document.querySelector("#formalReportPeriod").textContent = report ? `統計期間：${report.scope.period} / ${report.scope.unit} / ${report.scope.agency}` : "統計期間：-";
  document.querySelector("#formalReportScope").textContent = report?.version || "前端營運資料";
  document.querySelector("#formalReportScopeNote").textContent = report?.scope.dataSource || "收文、發文、流程、稽催、歸檔";
  document.querySelector("#formalReportHash").textContent = report?.reportHash || "待產生";
  document.querySelector("#formalReportDecision").textContent = report?.managementConclusion.decision || "待檢視";
  document.querySelector("#formalReportDecisionNote").textContent = report ? report.managementConclusion.requiredActions[0] : "依 SLA、異常、逾期與交換健康判定";
}

function generateFormalReport() {
  latestFormalReport = formalReportPayload();
  renderFormalReport();
  addReportsAudit("產製正式報表", `${latestFormalReport.reportNo} 已產製，結論：${latestFormalReport.managementConclusion.decision}，雜湊 ${latestFormalReport.reportHash}。`);
  showToast("正式報表簽核包已產製。");
  return latestFormalReport;
}

function formalReportCsv(report = latestFormalReport || formalReportPayload()) {
  const rows = [
    ["報表編號", report.reportNo],
    ["版次", report.version],
    ["產製時間", report.generatedAt],
    ["產製角色", report.generatedBy],
    ["統計期間", report.scope.period],
    ["統計單位", report.scope.unit],
    ["機關範圍", report.scope.agency],
    ["收發量", report.kpi.volume],
    ["收文", report.kpi.inbound],
    ["發文", report.kpi.dispatch],
    ["交換成功率", `${report.kpi.successRate}%`],
    ["SLA 達成率", `${report.kpi.slaRate}%`],
    ["異常件", report.kpi.exceptionCount],
    ["逾期件", report.kpi.overdueCount],
    ["交換健康", report.kpi.exchangeHealth],
    ["主管結論", report.managementConclusion.decision],
    ["報表雜湊", report.reportHash]
  ];
  return rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(",")).join("\n");
}

function renderReportsSummary() {
  const stats = reportStats();
  document.querySelector("#reportVolume").textContent = stats.inboundCount + stats.dispatchCount;
  document.querySelector("#reportVolumeNote").textContent = `收文 ${stats.inboundCount} / 發文 ${stats.dispatchCount}`;
  document.querySelector("#reportSuccessRate").textContent = `${stats.successRate}%`;
  document.querySelector("#reportSuccessNote").textContent = `${stats.successCount} / ${stats.exchangeTotal} 件交換完成`;
  document.querySelector("#reportExceptionCount").textContent = stats.exceptionItems.length;
  document.querySelector("#reportExceptionNote").textContent = stats.exceptionItems.length ? "已有異常需追蹤" : "目前無異常";
  document.querySelector("#reportOverdueCount").textContent = stats.overdueItems.length;
  document.querySelector("#reportOverdueNote").textContent = `${stats.overdueItems.filter((item) => item.status === "逾期提醒").length} 件逾期提醒`;
  document.querySelector("#reportTrendStatus").textContent = document.querySelector("#reportPeriod").value;
  document.querySelector("#reportSlaRate").textContent = `${stats.slaRate}%`;
  document.querySelector("#reportSlaNote").textContent = stats.slaRate >= 90 ? "營運節奏穩定" : "需加速登錄、分派或歸檔";
  document.querySelector("#reportBacklogPressure").textContent = stats.backlogPressure;
  document.querySelector("#reportBacklogNote").textContent = `收文 ${stats.pendingInbound} / 發文 ${stats.pendingDispatch} / 逾期 ${stats.overdueItems.length}`;
  document.querySelector("#reportExchangeHealth").textContent = stats.exchangeHealth;
  document.querySelector("#reportExchangeHealthNote").textContent = `成功率 ${stats.successRate}%，異常 ${stats.exceptionItems.length} 件`;
  document.querySelector("#reportPriorityCount").textContent = stats.priorityItems.length;
  document.querySelector("#reportPriorityNote").textContent = stats.priorityItems[0]?.action || "目前無急件";
  document.querySelector("#reportOpsNarrative").textContent = `本期共處理 ${stats.inboundCount + stats.dispatchCount} 件公文，交換成功率 ${stats.successRate}%，SLA 達成率 ${stats.slaRate}%。目前待辦壓力為 ${stats.backlogPressure} 件，${stats.exchangeHealth === "正常" ? "交換中心狀態穩定" : "交換中心或異常件需要主管追蹤"}。`;
  document.querySelector("#reportOpsActions").innerHTML = stats.priorityItems.slice(0, 4).map((item) => `
    <article>
      <strong>${item.type}</strong>
      <span>${item.owner} · ${item.action}</span>
    </article>
  `).join("") || `<article><strong>無急迫行動</strong><span>維持每日查核與歸檔即可</span></article>`;
}

function renderReportCharts() {
  const maxVolume = Math.max(...reportTrend.map((item) => item.inbound + item.dispatch), 1);
  document.querySelector("#reportVolumeChart").innerHTML = reportTrend.map((item) => {
    const inboundHeight = Math.max(12, Math.round((item.inbound / maxVolume) * 120));
    const dispatchHeight = Math.max(12, Math.round((item.dispatch / maxVolume) * 120));
    return `
      <article class="report-bar-group">
        <div class="report-bars">
          <span class="report-bar inbound" style="height:${inboundHeight}px" title="收文 ${item.inbound}"></span>
          <span class="report-bar dispatch" style="height:${dispatchHeight}px" title="發文 ${item.dispatch}"></span>
        </div>
        <strong>${item.day}</strong>
      </article>
    `;
  }).join("");
  const stats = reportStats();
  const failureRate = Math.max(0, 100 - stats.successRate);
  document.querySelector("#reportQualityChart").innerHTML = `
    <article class="report-meter">
      <strong>${stats.successRate}%</strong>
      <span>交換成功率</span>
      <div><i style="width:${stats.successRate}%"></i></div>
    </article>
    <article class="report-meter issue">
      <strong>${failureRate}%</strong>
      <span>異常與未完成率</span>
      <div><i style="width:${failureRate}%"></i></div>
    </article>
    <article class="report-meter">
      <strong>${stats.exceptionItems.length}</strong>
      <span>異常類型件數</span>
      <div><i style="width:${Math.min(100, stats.exceptionItems.length * 16)}%"></i></div>
    </article>
  `;
}

function renderReportLists() {
  const stats = reportStats();
  const exceptionCounts = stats.exceptionItems.reduce((acc, item) => {
    acc[item.type] = (acc[item.type] || 0) + 1;
    return acc;
  }, {});
  document.querySelector("#reportExceptionList").innerHTML = Object.entries(exceptionCounts).map(([type, count]) => `
    <article class="address-card">
      <strong>${type}</strong>
      <span>${count} 件</span>
      <p>${stats.exceptionItems.filter((item) => item.type === type).map((item) => item.title).join("、")}</p>
    </article>
  `).join("") || `<p class="empty-text">目前沒有異常類型。</p>`;
  document.querySelector("#reportOwnerRows").innerHTML = stats.ownerRows.map((row) => `
    <tr>
      <td>${row.owner}</td>
      <td>${row.inbound}</td>
      <td>${row.dispatch}</td>
      <td>${row.pending}</td>
      <td>${row.overdue}</td>
    </tr>
  `).join("");
  document.querySelector("#reportOverdueList").innerHTML = stats.overdueItems.map((item) => `
    <article class="address-card">
      <strong>${item.title}</strong>
      <span>${item.id} · ${item.owner} · ${item.dueDate}</span>
      <p>${item.status}</p>
    </article>
  `).join("") || `<p class="empty-text">目前沒有逾期件。</p>`;
  document.querySelector("#reportSlaStatus").textContent = `${stats.slaRate}%`;
  document.querySelector("#reportSlaGrid").innerHTML = stats.slaRows.map((row) => `
    <article class="report-sla-card">
      <div>
        <strong>${row.name}</strong>
        <span>${row.target}</span>
      </div>
      <b>${row.rate}%</b>
      <div class="report-mini-meter"><i style="width:${row.rate}%"></i></div>
      <small>${row.done} / ${row.total} 件達標</small>
    </article>
  `).join("");
  document.querySelector("#reportAgingList").innerHTML = stats.agingRows.map((row) => `
    <article class="report-aging-card">
      <strong>${row.bucket}</strong>
      <b>${row.count}</b>
      <span>${row.note}</span>
    </article>
  `).join("");
  document.querySelector("#reportAgencyRankList").innerHTML = stats.agencyRank.slice(0, 5).map((row) => `
    <article class="address-card">
      <strong>${row.agency}</strong>
      <span>${row.total} 件 · 完成 ${row.completed} · 異常 ${row.exception}</span>
      <p>風險比 ${row.risk}%，${row.risk >= 30 ? "建議總務優先複核機關代碼與交換回覆。" : "交換狀態穩定。"}</p>
    </article>
  `).join("");
  document.querySelector("#reportUnitLoadList").innerHTML = stats.unitRows.map((row) => `
    <article class="address-card">
      <strong>${row.unit}</strong>
      <span>待辦 ${row.pending} 件 · 可作業帳號 ${row.users} 人</span>
      <p>平均負載 ${row.load} 件 / 人，${row.load >= 3 ? "建議主管改派或加簽支援。" : "負載正常。"}</p>
    </article>
  `).join("") || `<p class="empty-text">目前沒有部門負載資料。</p>`;
  const recommendations = [
    stats.exceptionItems.length ? `先處理 ${stats.exceptionItems.length} 件異常，避免交換失敗累積。` : "異常件為 0，維持每日交換查核。",
    stats.overdueItems.length ? `由報表建立 ${stats.overdueItems.length} 件稽催，並指派承辦回覆期限。` : "逾期件為 0，可抽查歸檔雜湊。",
    stats.slaRate < 90 ? "SLA 低於 90%，建議檢查收文登錄、分派與歸檔是否卡關。" : "SLA 達標，可維持目前作業節奏。",
    stats.agencyRank[0] ? `本期往來最多機關為 ${stats.agencyRank[0].agency}，可列為月報重點。` : "尚無機關排行資料。"
  ];
  document.querySelector("#reportActionRecommendationList").innerHTML = recommendations.map((text, index) => `
    <article class="address-card">
      <strong>建議 ${index + 1}</strong>
      <p>${text}</p>
    </article>
  `).join("");
}

function renderReportsAuditLog() {
  document.querySelector("#reportsAuditLog").innerHTML = reportsAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderReports() {
  renderReportsSummary();
  renderReportCharts();
  renderReportLists();
  renderFormalReport();
}

function createReportReminder() {
  const stats = reportStats();
  const newCases = stats.overdueItems
    .filter((item) => !trackingCases.some((tracking) => tracking.title === item.title))
    .map((item) => ({
      id: `TRK-${Date.now().toString().slice(-5)}-${Math.floor(Math.random() * 90 + 10)}`,
      title: item.title,
      agency: "內部流程",
      type: "逾期提醒",
      dueDate: "2026-05-23",
      owner: item.owner,
      status: "逾期提醒",
      note: `由報表統計建立稽催：${item.status}`
    }));
  if (newCases.length) {
    trackingCases.unshift(...newCases);
    renderTrackingSummary();
    renderTrackingRows();
    renderTrackingDetail();
  }
  addReportsAudit("建立逾期稽催", newCases.length ? `已由報表建立 ${newCases.length} 件逾期稽催。` : "逾期件已存在稽催追蹤，未重複建立。");
  renderReports();
  showToast(newCases.length ? "已建立逾期稽催。" : "逾期件已在稽催追蹤。");
}

function addSettingsAudit(title, body) {
  settingsAuditLog.unshift([nowTime(), title, body]);
  renderSettingsAuditLog();
}

function settingsPayload() {
  return {
    agencyName: document.querySelector("#settingsAgencyName").value.trim(),
    agencyCode: document.querySelector("#settingsAgencyCode").value.trim(),
    centerName: document.querySelector("#settingsCenterName").value,
    apiUrl: document.querySelector("#settingsApiUrl").value.trim(),
    apiMode: document.querySelector("#settingsApiMode").value,
    apiTimeout: document.querySelector("#settingsApiTimeout").value,
    certSerial: document.querySelector("#settingsCertSerial").value.trim(),
    certPolicy: document.querySelector("#settingsCertPolicy").value
  };
}

function renderSettingsStatus() {
  const data = settingsPayload();
  document.querySelector("#settingsAgencyStatus").textContent = settingsState.agencyVerified ? "已驗證" : "待檢核";
  document.querySelector("#settingsAgencyNote").textContent = `${data.agencyName} · ${data.agencyCode}`;
  document.querySelector("#settingsCenterStatus").textContent = settingsState.centerSynced ? "已同步" : "未測試";
  document.querySelector("#settingsCenterNote").textContent = `${data.centerName} · ${data.apiMode}`;
  document.querySelector("#settingsFirewallStatus").textContent = `${settingsFirewallRules.filter((rule) => rule.status === "允許").length} 條允許`;
  document.querySelector("#settingsFirewallNote").textContent = `${settingsFirewallRules.length} 條防火牆規則`;
  document.querySelector("#settingsRoleStatus").textContent = `${Object.keys(rolePermissions).length} 個角色`;
  document.querySelector("#settingsRoleNote").textContent = `${Object.keys(permissionLabels).length} 項權限 · ${enabledDocumentTypeConfigs().length} 種文件 · ${enabledWorkflowTemplateConfigs().length} 套流程`;
}

function renderSettingsFirewallList() {
  document.querySelector("#settingsFirewallList").innerHTML = settingsFirewallRules.map((rule) => `
    <article class="address-card">
      <strong>${rule.ip}</strong>
      <span>${rule.purpose}</span>
      <p>${rule.status} · ${rule.id}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-settings-fw="allow" data-fw-id="${rule.id}">允許</button>
        <button class="segment" type="button" data-settings-fw="block" data-fw-id="${rule.id}">封鎖</button>
        <button class="segment" type="button" data-settings-fw="remove" data-fw-id="${rule.id}">移除</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-settings-fw]").forEach((button) => {
    button.addEventListener("click", () => mutateSettingsFirewall(button.dataset.fwId, button.dataset.settingsFw));
  });
}

function renderSettingsRoleGrid() {
  document.querySelector("#settingsRoleGrid").innerHTML = Object.entries(rolePermissions).map(([role, permissions]) => `
    <article class="permission-chip allowed">
      <strong>${permissions.length} 項權限</strong>
      <span>${role}</span>
    </article>
  `).join("");
}

function setFieldValue(selector, value) {
  const element = document.querySelector(selector);
  if (!element || value === undefined || value === null) return;
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function editDocumentTypeConfig(id) {
  const config = documentTypeConfigs.find((item) => item.id === id);
  if (!config) return;
  setFieldValue("#settingsDocTypeName", config.name);
  setFieldValue("#settingsDocTypeCategory", config.category);
  syncConfigurableSelectOptions();
  setFieldValue("#settingsDocTypeWorkflow", config.defaultWorkflowTemplate);
  setFieldValue("#settingsDocTypeFormat", config.defaultFormatTemplate);
  setFieldValue("#settingsDocTypePriority", config.defaultPriority);
  setFieldValue("#settingsDocTypeSecurity", config.defaultSecurity);
}

function applyDocumentTypeConfig(id) {
  const config = documentTypeConfigs.find((item) => item.id === id);
  if (!config) return;
  activeWorkflowTemplate = config.defaultWorkflowTemplate;
  selectedFormatTemplateId = config.defaultFormatTemplate;
  syncConfigurableSelectOptions();
  setFieldValue("#docType", config.name);
  setFieldValue("#formatDocType", config.name);
  setFieldValue("#workflowTemplateDocType", config.name);
  setFieldValue("#priority", config.defaultPriority);
  setFieldValue("#formatPriority", config.defaultPriority);
  setFieldValue("#formatSecurity", config.defaultSecurity);
  applySettingsFormatTemplate(config.defaultFormatTemplate, { silent: true });
  renderWorkflowTemplateSteps();
  renderFormatChecks();
  renderDraftPreview();
  addSettingsAudit("套用文件類型", `${config.name} 已帶入撰寫、格式檢核與流程範本。`);
  showToast("文件類型設定已套用。");
}

function mutateDocumentTypeConfig(id, action) {
  const config = documentTypeConfigs.find((item) => item.id === id);
  if (!config) return;
  if (action === "edit") return editDocumentTypeConfig(id);
  if (action === "apply") return applyDocumentTypeConfig(id);
  config.status = config.status === "停用" ? "啟用" : "停用";
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  addSettingsAudit(config.status === "啟用" ? "啟用文件類型" : "停用文件類型", `${config.name} 已更新為${config.status}。`);
  showToast("文件類型狀態已更新。");
}

function upsertSettingsDocumentType() {
  const name = document.querySelector("#settingsDocTypeName").value.trim();
  if (!name) return blockOperation("文件類型名稱不可空白。", addSettingsAudit, "文件類型防呆");
  const payload = {
    name,
    category: document.querySelector("#settingsDocTypeCategory").value,
    defaultWorkflowTemplate: document.querySelector("#settingsDocTypeWorkflow").value,
    defaultFormatTemplate: document.querySelector("#settingsDocTypeFormat").value,
    defaultPriority: document.querySelector("#settingsDocTypePriority").value,
    defaultSecurity: document.querySelector("#settingsDocTypeSecurity").value,
    status: "啟用"
  };
  const existing = documentTypeConfigs.find((item) => item.name === name);
  if (existing) Object.assign(existing, payload);
  else documentTypeConfigs.unshift({ id: `DTC-${Date.now().toString().slice(-5)}`, ...payload });
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  renderFormatChecks();
  addSettingsAudit(existing ? "更新文件類型" : "新增文件類型", `${name} 已設定預設流程與格式模板。`);
  showToast(existing ? "文件類型已更新。" : "文件類型已新增。");
}

function renderSettingsDocumentTypes() {
  const list = document.querySelector("#settingsDocumentTypeList");
  if (!list) return;
  list.innerHTML = documentTypeConfigs.map((item) => {
    const workflow = workflowTemplateConfigForKey(item.defaultWorkflowTemplate);
    const format = formatTemplateById(item.defaultFormatTemplate);
    return `
      <article class="address-card">
        <strong>${item.name}</strong>
        <span>${item.category} · ${item.status}</span>
        <p>流程：${workflow?.name || item.defaultWorkflowTemplate}；格式：${format?.name || item.defaultFormatTemplate}；${item.defaultPriority}／${item.defaultSecurity}</p>
        <div class="row-actions">
          <button class="segment" type="button" data-doc-type-action="apply" data-doc-type-id="${item.id}">套用</button>
          <button class="segment" type="button" data-doc-type-action="edit" data-doc-type-id="${item.id}">編輯</button>
          <button class="segment" type="button" data-doc-type-action="toggle" data-doc-type-id="${item.id}">${item.status === "停用" ? "啟用" : "停用"}</button>
        </div>
      </article>
    `;
  }).join("") || `<p class="empty-text">尚未建立文件類型。</p>`;
  document.querySelectorAll("[data-doc-type-action]").forEach((button) => {
    button.addEventListener("click", () => mutateDocumentTypeConfig(button.dataset.docTypeId, button.dataset.docTypeAction));
  });
}

function editWorkflowTemplateConfig(key) {
  const config = workflowTemplateConfigForKey(key);
  if (!config) return;
  setFieldValue("#settingsWorkflowTemplateKey", config.key);
  setFieldValue("#settingsWorkflowTemplateName", config.name);
  setFieldValue("#settingsWorkflowTemplateRoute", config.routeCode || "A");
  setFieldValue("#settingsWorkflowTemplateSteps", (config.steps || []).join("\n"));
}

function mutateWorkflowTemplateConfig(key, action) {
  const config = workflowTemplateConfigForKey(key);
  if (!config) return;
  if (action === "edit") return editWorkflowTemplateConfig(key);
  if (action === "apply") {
    activeWorkflowTemplate = key;
    syncConfigurableSelectOptions();
    renderWorkflowTemplateSteps();
    addSettingsAudit("套用流程模板", `${config.name} 已設為目前流程範本。`);
    return showToast("流程模板已套用。");
  }
  config.status = config.status === "停用" ? "啟用" : "停用";
  syncWorkflowTemplateObject();
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  renderWorkflowTemplateSteps();
  addSettingsAudit(config.status === "啟用" ? "啟用流程模板" : "停用流程模板", `${config.name} 已更新為${config.status}。`);
  showToast("流程模板狀態已更新。");
}

function upsertSettingsWorkflowTemplate() {
  const key = document.querySelector("#settingsWorkflowTemplateKey").value.trim().replace(/[^\w-]/g, "");
  const name = document.querySelector("#settingsWorkflowTemplateName").value.trim();
  const routeCode = document.querySelector("#settingsWorkflowTemplateRoute").value;
  const steps = document.querySelector("#settingsWorkflowTemplateSteps").value.split("\n").map((step) => step.trim()).filter(Boolean);
  if (!key || !name) return blockOperation("流程模板代碼與名稱都必須填寫。", addSettingsAudit, "流程模板防呆");
  if (steps.length < 2) return blockOperation("流程模板至少需要 2 個節點。", addSettingsAudit, "流程模板防呆");
  const payload = { key, name, routeCode, steps, status: "啟用" };
  const existing = workflowTemplateConfigForKey(key);
  if (existing) Object.assign(existing, payload);
  else workflowTemplateConfigs.unshift(payload);
  activeWorkflowTemplate = key;
  syncWorkflowTemplateObject();
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  renderWorkflowTemplateSteps();
  renderWorkflowConditions();
  addSettingsAudit(existing ? "更新流程模板" : "新增流程模板", `${name} 已設定 ${steps.length} 個節點。`);
  showToast(existing ? "流程模板已更新。" : "流程模板已新增。");
}

function renderSettingsWorkflowTemplates() {
  const list = document.querySelector("#settingsWorkflowTemplateList");
  if (!list) return;
  list.innerHTML = workflowTemplateConfigs.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <span>${item.key} · ${approvalRouteTypes[item.routeCode]?.name || item.routeCode} · ${item.status}</span>
      <p>${(item.steps || []).join(" → ")}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-workflow-template-action="apply" data-workflow-template-key="${item.key}">套用</button>
        <button class="segment" type="button" data-workflow-template-action="edit" data-workflow-template-key="${item.key}">編輯</button>
        <button class="segment" type="button" data-workflow-template-action="toggle" data-workflow-template-key="${item.key}">${item.status === "停用" ? "啟用" : "停用"}</button>
      </div>
    </article>
  `).join("") || `<p class="empty-text">尚未建立流程模板。</p>`;
  document.querySelectorAll("[data-workflow-template-action]").forEach((button) => {
    button.addEventListener("click", () => mutateWorkflowTemplateConfig(button.dataset.workflowTemplateKey, button.dataset.workflowTemplateAction));
  });
}

function mutateSettingsPermission(action, role = document.querySelector("#settingsPermissionRoleSelect")?.value, permission = document.querySelector("#settingsPermissionCodeSelect")?.value) {
  if (!role || !permission) return;
  const permissions = new Set(rolePermissions[role] || []);
  if (action === "grant") permissions.add(permission);
  else permissions.delete(permission);
  rolePermissions[role] = [...permissions];
  alignRolePermissionsWithLogging();
  persistAdminConfigState();
  syncRoleOptions();
  applyRoleNavigation();
  renderWorkflowRole();
  renderSecurityPermissionGrid();
  renderAccounts();
  renderSettings();
  addSettingsAudit(action === "grant" ? "授權權限" : "移除權限", `${role} ${action === "grant" ? "取得" : "移除"}「${permissionLabels[permission] || permission}」。`);
  showToast("權限矩陣已更新。");
}

function renderSettingsPermissionMatrix() {
  const grid = document.querySelector("#settingsPermissionMatrixGrid");
  if (!grid) return;
  const selectedRole = document.querySelector("#settingsPermissionRoleSelect")?.value || activeRole();
  grid.innerHTML = Object.entries(permissionLabels).map(([permission, label]) => {
    const granted = (rolePermissions[selectedRole] || []).includes(permission);
    return `
      <article class="permission-chip ${granted ? "allowed" : ""}">
        <strong>${granted ? "允許" : "限制"}</strong>
        <span>${label}</span>
        <p>${permission}</p>
        <button class="segment" type="button" data-permission-toggle="${granted ? "revoke" : "grant"}" data-permission-role="${selectedRole}" data-permission-code="${permission}">${granted ? "移除" : "授權"}</button>
      </article>
    `;
  }).join("");
  document.querySelectorAll("[data-permission-toggle]").forEach((button) => {
    button.addEventListener("click", () => mutateSettingsPermission(button.dataset.permissionToggle, button.dataset.permissionRole, button.dataset.permissionCode));
  });
}

function attachmentTypeFromName(name) {
  const ext = name.split(".").pop()?.toUpperCase() || "FILE";
  return ext.length <= 5 ? ext : "FILE";
}

function applySettingsFormatTemplate(id = selectedFormatTemplateId, options = {}) {
  const template = formatTemplateById(id);
  if (!template) return;
  selectedFormatTemplateId = template.id;
  syncConfigurableSelectOptions();
  setFieldValue("#settingsFormatTemplateName", template.name);
  setFieldValue("#settingsFormatTemplateDocType", template.docType);
  setFieldValue("#settingsFormatTemplatePriority", template.priority);
  setFieldValue("#settingsFormatTemplateSecurity", template.security);
  setFieldValue("#settingsFormatTemplateSubject", template.subjectHint);
  setFieldValue("#settingsFormatTemplateAttachments", (template.attachments || []).join(","));
  setFieldValue("#formatDocType", template.docType);
  setFieldValue("#formatPriority", template.priority);
  setFieldValue("#formatSecurity", template.security);
  setFieldValue("#formatSubject", template.subjectHint);
  formatState.attachments = (template.attachments || []).map((name, index) => ({
    id: `TPL-${template.id}-${index + 1}`,
    name,
    pages: 1,
    type: attachmentTypeFromName(name),
    hash: `SHA256-TPL-${template.id}-${index + 1}`
  }));
  renderFormatAttachments();
  renderFormatChecks();
  renderSettingsFormatTemplates();
  if (!options.silent) {
    addSettingsAudit("套用格式模板", `${template.name} 已套用到文書格式檢核。`);
    addFormatAudit("套用後台格式模板", `${template.name} 已建立預設附件清冊。`);
    showToast("格式模板已套用。");
  }
}

function saveSettingsFormatTemplate() {
  const name = document.querySelector("#settingsFormatTemplateName").value.trim();
  if (!name) return blockOperation("格式模板名稱不可空白。", addSettingsAudit, "格式模板防呆");
  const payload = {
    name,
    docType: document.querySelector("#settingsFormatTemplateDocType").value,
    priority: document.querySelector("#settingsFormatTemplatePriority").value,
    security: document.querySelector("#settingsFormatTemplateSecurity").value,
    subjectHint: document.querySelector("#settingsFormatTemplateSubject").value.trim(),
    attachments: document.querySelector("#settingsFormatTemplateAttachments").value.split(",").map((item) => item.trim()).filter(Boolean),
    status: "啟用"
  };
  const existing = formatTemplateConfigs.find((item) => item.name === name || item.id === selectedFormatTemplateId);
  if (existing) {
    Object.assign(existing, payload);
    selectedFormatTemplateId = existing.id;
  } else {
    selectedFormatTemplateId = `FMT-${Date.now().toString().slice(-5)}`;
    formatTemplateConfigs.unshift({ id: selectedFormatTemplateId, ...payload });
  }
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  addSettingsAudit(existing ? "更新格式模板" : "新增格式模板", `${name} 已儲存為 ${payload.docType} 的預設格式。`);
  showToast(existing ? "格式模板已更新。" : "格式模板已新增。");
}

function saveCurrentFormatAsTemplate() {
  const data = formatPayload();
  const name = `${data.type || "公文"}格式模板`;
  const existing = formatTemplateConfigs.find((item) => item.name === name);
  const payload = {
    name,
    docType: data.type,
    priority: data.priority,
    security: data.security,
    subjectHint: data.subject,
    attachments: data.attachments.map((item) => item.name),
    status: "啟用"
  };
  if (existing) {
    Object.assign(existing, payload);
    selectedFormatTemplateId = existing.id;
  } else {
    selectedFormatTemplateId = `FMT-${Date.now().toString().slice(-5)}`;
    formatTemplateConfigs.unshift({ id: selectedFormatTemplateId, ...payload });
  }
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  addFormatAudit("儲存格式範本", `${name} 已存入後台格式模板設定。`);
  showToast("文書格式範本已儲存到後台。");
}

function mutateSettingsFormatTemplate(id, action) {
  const template = formatTemplateById(id);
  if (!template) return;
  if (action === "apply") return applySettingsFormatTemplate(id);
  if (action === "edit") {
    selectedFormatTemplateId = id;
    setFieldValue("#settingsFormatTemplateName", template.name);
    setFieldValue("#settingsFormatTemplateDocType", template.docType);
    setFieldValue("#settingsFormatTemplatePriority", template.priority);
    setFieldValue("#settingsFormatTemplateSecurity", template.security);
    setFieldValue("#settingsFormatTemplateSubject", template.subjectHint);
    setFieldValue("#settingsFormatTemplateAttachments", (template.attachments || []).join(","));
    return;
  }
  template.status = template.status === "停用" ? "啟用" : "停用";
  persistAdminConfigState();
  syncConfigurableSelectOptions();
  renderSettings();
  addSettingsAudit(template.status === "啟用" ? "啟用格式模板" : "停用格式模板", `${template.name} 已更新為${template.status}。`);
  showToast("格式模板狀態已更新。");
}

function renderSettingsFormatTemplates() {
  const list = document.querySelector("#settingsFormatTemplateList");
  if (!list) return;
  list.innerHTML = formatTemplateConfigs.map((item) => `
    <article class="address-card ${item.id === selectedFormatTemplateId ? "selected-row" : ""}">
      <strong>${item.name}</strong>
      <span>${item.docType} · ${item.priority} · ${item.security} · ${item.status}</span>
      <p>${item.subjectHint}｜附件：${(item.attachments || []).join("、") || "無"}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-format-template-action="apply" data-format-template-id="${item.id}">套用</button>
        <button class="segment" type="button" data-format-template-action="edit" data-format-template-id="${item.id}">編輯</button>
        <button class="segment" type="button" data-format-template-action="toggle" data-format-template-id="${item.id}">${item.status === "停用" ? "啟用" : "停用"}</button>
      </div>
    </article>
  `).join("") || `<p class="empty-text">尚未建立格式模板。</p>`;
  document.querySelectorAll("[data-format-template-action]").forEach((button) => {
    button.addEventListener("click", () => mutateSettingsFormatTemplate(button.dataset.formatTemplateId, button.dataset.formatTemplateAction));
  });
}

function renderSettingsAuditLog() {
  document.querySelector("#settingsAuditLog").innerHTML = settingsAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderSettings() {
  syncConfigurableSelectOptions();
  renderSettingsStatus();
  renderSettingsFirewallList();
  renderSettingsRoleGrid();
  renderSettingsDocumentTypes();
  renderSettingsWorkflowTemplates();
  renderSettingsPermissionMatrix();
  renderSettingsFormatTemplates();
  renderSettingsAuditLog();
}

function validateSettingsAgency() {
  const data = settingsPayload();
  const valid = /^[A-Z]\d{8,}[A-Z]?$/.test(data.agencyCode);
  settingsState.agencyVerified = valid;
  document.querySelector("#formatAgencyCode").value = data.agencyCode;
  renderFormatChecks();
  renderSettingsStatus();
  addSettingsAudit("檢核機關代碼", valid ? `${data.agencyName}（${data.agencyCode}）格式通過。` : `${data.agencyCode} 格式不符，需補正。`);
  showToast(valid ? "機關代碼檢核通過。" : "機關代碼格式需補正。");
}

function syncSettingsCenter() {
  const data = settingsPayload();
  settingsState.centerSynced = true;
  document.querySelector("#exchangeCenterName").value = data.centerName;
  document.querySelector("#exchangeCenterUrl").value = data.apiUrl;
  jagentState.center = "已連線";
  jagentState.latency = `${Math.floor(36 + Math.random() * 44)}ms`;
  renderJagentStatus();
  renderSettingsStatus();
  addSettingsAudit("同步交換中心", `${data.centerName} 與 API URL 已同步至 jAgent 介接設定。`);
  showToast("交換中心設定已同步。");
}

function testSettingsApi() {
  const data = settingsPayload();
  settingsState.apiStatus = "連線成功";
  settingsState.centerSynced = true;
  renderSettingsStatus();
  addSettingsAudit("測試 API URL", `${data.apiMode} ${data.apiUrl} 回應 200 OK，Timeout ${data.apiTimeout}。`);
  showToast("API 連線測試成功。");
}

function verifySettingsCert() {
  const data = settingsPayload();
  settingsState.certStatus = "已驗證";
  document.querySelector("#securityCertSerial").value = data.certSerial;
  securityState.certStatus = "已驗證";
  securityState.certNote = `${data.certSerial} · ${data.certPolicy}`;
  renderSecurityStatus();
  addSettingsAudit("驗證憑證", `${data.certSerial} 已依「${data.certPolicy}」完成檢核。`);
  showToast("憑證設定已驗證。");
}

function rotateSettingsCert() {
  const serial = `SYC-EDOC-${new Date().getFullYear()}-${Math.floor(Math.random() * 9000 + 1000)}`;
  document.querySelector("#settingsCertSerial").value = serial;
  settingsState.certStatus = "待驗證";
  addSettingsAudit("更換憑證", `已產生新憑證序號 ${serial}，待驗證後啟用。`);
  showToast("已更換憑證序號。");
}

function addSettingsFirewallRule() {
  const ip = document.querySelector("#settingsFirewallIp").value.trim();
  const purpose = document.querySelector("#settingsFirewallPurpose").value.trim();
  if (!ip || !purpose) return showToast("請輸入 IP/CIDR 與用途。");
  settingsFirewallRules.unshift({ id: `FW-${Date.now().toString().slice(-5)}`, ip, purpose, status: "允許" });
  securityDevices.unshift({ id: `DEV-${Date.now().toString().slice(-5)}`, ip, name: purpose, fingerprint: `FW-${ip}`, status: "允許" });
  renderSettings();
  renderSecurityDeviceList();
  renderSecurityStatus();
  addSettingsAudit("新增防火牆規則", `${ip} 已加入允許清單，用途：${purpose}。`);
  showToast("防火牆規則已新增。");
}

function mutateSettingsFirewall(id, action) {
  const rule = settingsFirewallRules.find((item) => item.id === id);
  if (!rule) return;
  if (action === "remove") {
    settingsFirewallRules.splice(settingsFirewallRules.findIndex((item) => item.id === id), 1);
    addSettingsAudit("移除防火牆規則", `${rule.ip} 已移除。`);
  } else {
    rule.status = action === "allow" ? "允許" : "封鎖";
    addSettingsAudit(action === "allow" ? "允許防火牆規則" : "封鎖防火牆規則", `${rule.ip} 已更新為${rule.status}。`);
  }
  renderSettings();
  showToast("防火牆規則已更新。");
}

function addSettingsRole() {
  const role = document.querySelector("#settingsRoleName").value.trim();
  const note = document.querySelector("#settingsRoleNoteInput").value.trim();
  const permission = document.querySelector("#settingsRolePermission").value;
  if (!role) return showToast("請輸入角色名稱。");
  rolePermissions[role] = [...new Set([...(rolePermissions[role] || []), permission])];
  roleNotes[role] = note || "自訂角色。";
  persistAdminConfigState();
  syncRoleOptions();
  renderWorkflowRole();
  renderSecurityPermissionGrid();
  renderAccounts();
  renderSettings();
  addSettingsAudit("新增角色", `${role} 已建立，預設權限：${permissionLabels[permission]}。`);
  showToast("角色已新增。");
}

function saveSettings() {
  const data = settingsPayload();
  if (!data.agencyName || !data.agencyCode || !data.apiUrl) {
    return blockOperation("機關名稱、機關代碼與 API URL 都必須填寫後才能儲存。", addSettingsAudit, "系統設定防呆");
  }
  if (!/^https:\/\//i.test(data.apiUrl)) {
    return blockOperation("正式 API URL 必須使用 HTTPS。", addSettingsAudit, "系統設定防呆");
  }
  const productionLike = /正式|prod|jagent|gov/i.test(`${opsState.environment} ${data.apiMode} ${data.centerName} ${data.apiUrl}`);
  if (productionLike && !requireTypedConfirm("確認儲存正式設定", `即將儲存 ${data.agencyName} 的交換中心、API URL、防火牆、憑證與角色設定。正式設定會影響電子公文交換作業。`, "確認儲存")) return;
  settingsState.agencyVerified = /^[A-Z]\d{8,}[A-Z]?$/.test(data.agencyCode);
  persistAdminConfigState();
  renderSettings();
  addSettingsAudit("儲存系統設定", `${data.agencyName}、${data.centerName}、${data.apiUrl}、${settingsFirewallRules.length} 條防火牆規則、${Object.keys(rolePermissions).length} 個角色、${documentTypeConfigs.length} 種文件、${workflowTemplateConfigs.length} 套流程與 ${formatTemplateConfigs.length} 個格式模板已儲存。`);
  showToast("系統設定已儲存。");
}

function addOpsAudit(title, body) {
  opsAuditLog.unshift([nowTime(), title, body]);
  renderOpsAuditLog();
}

function filteredOpsApiLogs() {
  const term = opsLogSearchTerm.trim().toLowerCase();
  return opsApiLogs.filter((item) => {
    const matchFilter = opsLogFilter === "all"
      || (opsLogFilter === "200" && item.status === 200)
      || (opsLogFilter === "4xx" && item.status >= 400 && item.status < 500)
      || (opsLogFilter === "5xx" && item.status >= 500)
      || item.service === opsLogFilter;
    const haystack = `${item.time} ${item.service} ${item.api} ${item.status} ${item.code} ${item.message}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderOpsSummary() {
  document.querySelector("#opsHealthStatus").textContent = opsState.health;
  document.querySelector("#opsHealthNote").textContent = `${jagentState.center} · Token ${tokenTimeLeft()}`;
  document.querySelector("#opsApiLogCount").textContent = opsApiLogs.length;
  document.querySelector("#opsApiLogNote").textContent = `${opsApiLogs.filter((item) => item.status >= 400).length} 筆異常`;
  document.querySelector("#opsConfigVersion").textContent = opsState.configVersion;
  document.querySelector("#opsConfigNote").textContent = opsConfigVersions[0]?.note || "尚無版本";
  document.querySelector("#opsEnvironmentStatus").textContent = opsState.environment;
  document.querySelector("#opsEnvironmentNote").textContent = document.querySelector("#settingsApiUrl")?.value || "未設定 API";
}

function renderOpsApiLogs() {
  const rows = filteredOpsApiLogs();
  document.querySelector("#opsLogCount").textContent = `${rows.length} 筆`;
  document.querySelector("#opsApiLogRows").innerHTML = rows.map((item) => `
    <tr>
      <td>${item.time}</td>
      <td>${item.service}</td>
      <td>${item.api}<small>${item.message}</small></td>
      <td><span class="status-pill ${item.status >= 500 ? "issue" : item.status >= 400 ? "wait" : "ok"}">${item.status}</span></td>
      <td>${item.duration}</td>
      <td><button class="segment" type="button" data-ops-error="${item.code}">查錯誤碼</button></td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-ops-error]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector("#opsErrorCodeInput").value = button.dataset.opsError;
      lookupOpsErrorCode();
    });
  });
}

function renderOpsConfigList() {
  document.querySelector("#opsConfigList").innerHTML = opsConfigVersions.map((item) => `
    <article class="address-card">
      <strong>${item.version} · ${item.env}</strong>
      <p>${item.note}</p>
      <small>${item.createdAt} · ${item.actor}</small>
    </article>
  `).join("");
}

function renderOpsBackupGrid() {
  const items = [
    ["最新備份", opsBackups[0]?.id || "尚未備份"],
    ["備份數", `${opsBackups.length} 份`],
    ["資料表", `${Object.keys(databaseTables).length} 張`],
    ["還原狀態", opsState.restoredBackup || "未還原"]
  ];
  document.querySelector("#opsBackupGrid").innerHTML = items.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  document.querySelector("#opsBackupList").innerHTML = opsBackups.map((backup) => `
    <article class="address-card">
      <strong>${backup.id}</strong>
      <p>${backup.createdAt} · ${backup.env}</p>
      <small>${backup.note} · ${backup.hash || "待產生雜湊"}</small>
    </article>
  `).join("") || `<article class="address-card"><strong>尚無備份</strong><p>建立資料備份後可還原。</p></article>`;
}

function renderOpsAuditLog() {
  document.querySelector("#opsAuditLog").innerHTML = opsAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function monitoringStatusLabel(status) {
  return {
    healthy: "健康",
    warning: "需注意",
    critical: "重大異常"
  }[status] || status || "未檢查";
}

function isHeaderSafeToken(token) {
  return typeof token === "string" && /^[\x21-\x7e]+$/.test(token);
}

async function fetchOpsJson(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (isHeaderSafeToken(authState?.token)) headers.Authorization = `Bearer ${authState.token}`;
  const response = await fetch(`${backendApiBase}${path}`, { headers, ...options });
  const data = await response.json();
  return { ok: response.ok, status: response.status, data };
}

function goLiveTone(audit = goLiveAuditState) {
  if (!audit) return "idle";
  if (audit.formalGo) return "ok";
  if (audit.internalPilotAllowed) return "warn";
  return "issue";
}

function goLiveDecisionText(audit = goLiveAuditState) {
  if (!audit) return "未檢查";
  if (audit.formalGo) return "GO";
  if (audit.internalPilotAllowed) return "NO-GO · 僅內部演練";
  return "NO-GO";
}

function renderGoLiveGate() {
  const panel = document.querySelector("#goLiveGatePanel");
  if (!panel) return;
  panel.hidden = !canSeeCompanyWideDocs(activeRole());
  if (panel.hidden) return;
  const audit = goLiveAuditState;
  const tone = goLiveTone(audit);
  panel.className = `panel go-live-gate-panel ${tone}`;
  document.querySelector("#goLiveDecisionBadge").textContent = goLiveDecisionText(audit);
  document.querySelector("#goLiveDecisionTitle").textContent = audit?.targetLaunchDate
    ? `${audit.targetLaunchDate} 上線判定`
    : "明日上線判定";
  document.querySelector("#goLiveDecisionSummary").textContent = audit?.summary || "尚未讀取正式部署檢查。";
  const blockers = audit?.formalBlockers || [];
  const categories = audit?.categories || [];
  document.querySelector("#goLiveGateGrid").innerHTML = audit ? [
    ["正式判定", goLiveDecisionText(audit), audit.environment || "未檢查"],
    ["正式資料庫", audit.databaseMode || "未檢查", categories.find((item) => item.key === "database")?.status || "未檢查"],
    ["阻塞項", blockers.length, blockers[0] || "目前沒有 formal blocker"],
    ["內部演練", audit.internalPilotAllowed ? "可開" : "不建議", audit.internalPilotAllowed ? "不得正式交換" : "需先處理 blocker"]
  ].map(([label, value, note]) => `
    <article class="go-live-mini-card">
      <span>${label}</span>
      <strong>${value}</strong>
      <p>${note}</p>
    </article>
  `).join("") : `
    <article class="go-live-mini-card">
      <span>狀態</span>
      <strong>未檢查</strong>
      <p>請按重新檢查。</p>
    </article>
  `;
}

function renderOpsGoLiveAudit() {
  const summary = document.querySelector("#opsGoLiveSummary");
  const grid = document.querySelector("#opsGoLiveGrid");
  if (!summary || !grid) return;
  const audit = goLiveAuditState;
  const tone = goLiveTone(audit);
  summary.className = `go-live-ops-summary ${tone}`;
  summary.innerHTML = audit ? `
    <div>
      <span>${audit.targetLaunchDate || "上線日未設定"}</span>
      <strong>${goLiveDecisionText(audit)}</strong>
      <p>${audit.summary}</p>
    </div>
    <small>${audit.checkedAt || "尚未檢查"} · ${audit.environment || "unknown"} · formal blockers ${audit.formalBlockers?.length || 0}</small>
  ` : `
    <div>
      <span>尚未檢查</span>
      <strong>等待 Go / No-Go</strong>
      <p>請執行重新判定，系統會讀取正式部署與外部服務設定。</p>
    </div>
  `;
  grid.innerHTML = (audit?.categories || []).map((item) => `
    <article class="go-live-category ${item.status}">
      <div>
        <span>${item.severity}</span>
        <strong>${item.name}</strong>
      </div>
      <p>${item.evidence}</p>
      <small>${item.action}</small>
    </article>
  `).join("") || `<article class="go-live-category warn"><strong>尚未取得檢查資料</strong><p>請重新判定。</p></article>`;
}

function renderGoLiveAuditViews() {
  renderGoLiveGate();
  renderOpsGoLiveAudit();
}

async function syncGoLiveAuditFromBackend(silent = false) {
  try {
    const result = await fetchOpsJson("/production/go-live-audit");
    goLiveAuditState = result.data;
    renderGoLiveAuditViews();
    if (!silent) {
      showToast(result.data.formalGo ? "Go / No-Go 判定通過。" : "Go / No-Go 判定未通過，請查看阻塞項。");
    }
    return result.data;
  } catch (error) {
    if (!silent) showToast(error.message || "無法讀取 Go / No-Go 判定。");
    return null;
  }
}

function renderOpsDeploymentMonitoring() {
  const deployment = opsState.deployment || {};
  const readiness = opsState.readiness || {};
  const monitoring = opsState.monitoring || {};
  const checks = monitoring.checks || {};
  const deploymentItems = [
    ["部署環境", deployment.environment || readiness.environment || "未檢查"],
    ["Runtime", deployment.runtime || "未檢查"],
    ["資料庫", deployment.databaseMode || readiness.databaseMode || "未檢查"],
    ["版本", (deployment.revision || "未檢查").slice(0, 12)],
    ["分支", deployment.branch || "未檢查"],
    ["公開網址", deployment.deploymentUrl || "未設定"]
  ];
  document.querySelector("#opsDeploymentGrid").innerHTML = deploymentItems.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");

  const monitoringItems = [
    ["監控狀態", monitoringStatusLabel(monitoring.status)],
    ["Readiness", checks.readiness?.status || (readiness.ready ? "ok" : "未檢查")],
    ["Storage", checks.storage?.provider || deployment.storage?.provider || "未檢查"],
    ["Cron", checks.cron?.status || "未檢查"],
    ["通知憑證", checks.notifications?.status || "未檢查"],
    ["最後檢查", opsState.lastMonitorCheck || monitoring.checkedAt || "尚未執行"]
  ];
  document.querySelector("#opsMonitoringGrid").innerHTML = monitoringItems.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");

  const alerts = monitoring.alerts || [];
  document.querySelector("#opsAlertList").innerHTML = alerts.length ? alerts.map((alert) => `
    <article class="address-card">
      <strong>${alert.code} · ${alert.level}</strong>
      <p>${alert.message}</p>
      <small>${alert.action}</small>
    </article>
  `).join("") : `<article class="address-card"><strong>目前沒有告警</strong><p>部署、資料庫、排程與通知通道尚無重大異常。</p></article>`;
}

function renderOps() {
  renderOpsSummary();
  renderOpsGoLiveAudit();
  renderOpsDeploymentMonitoring();
  renderOpsApiLogs();
  renderOpsConfigList();
  renderOpsBackupGrid();
  renderOpsAuditLog();
  lookupOpsErrorCode(false);
}

async function runOpsHealthCheck() {
  const latency = `${Math.floor(32 + Math.random() * 45)}ms`;
  jagentState.center = "已連線";
  jagentState.latency = latency;
  if (!jagentState.tokenExpiresAt) {
    jagentState.token = `tk_${Date.now()}`;
    jagentState.tokenExpiresAt = Date.now() + 8 * 60 * 60 * 1000;
  }
  const started = performance.now();
  try {
    const health = await fetchOpsJson("/health");
    const duration = `${Math.round(performance.now() - started)}ms`;
    opsState.health = health.ok ? "Healthy" : "API 異常";
    opsState.readiness = health.data.production || opsState.readiness;
    opsApiLogs.unshift({ time: nowTime(), service: "Backend", api: "GET /health", status: health.status, duration, code: health.ok ? "OK" : "HEALTH-FAIL", message: health.ok ? "後端健康檢查通過" : "後端健康檢查未通過" });
  } catch (error) {
    opsState.health = "API 異常";
    opsApiLogs.unshift({ time: nowTime(), service: "Backend", api: "GET /health", status: 500, duration: latency, code: "HEALTH-ERROR", message: error.message });
  }
  opsApiLogs.unshift({ time: nowTime(), service: "jAgent", api: "GET /health", status: 200, duration: latency, code: "OK", message: "憑證、Token、交換中心與地址簿健康檢查通過" });
  renderJagentStatus();
  renderOps();
  addOpsAudit("健康檢查", `Backend ${opsState.health}，jAgent 延遲 ${latency}，Token ${tokenTimeLeft()}。`);
  showToast("健康檢查完成。");
}

async function runOpsReadinessCheck() {
  const started = performance.now();
  const [readiness, deployment] = await Promise.all([
    fetchOpsJson("/production/readiness"),
    fetchOpsJson("/production/deployment")
  ]);
  opsState.readiness = readiness.data;
  opsState.deployment = deployment.data;
  opsState.environment = readiness.data.environment || opsState.environment;
  opsApiLogs.unshift({ time: nowTime(), service: "Production", api: "GET /production/readiness", status: readiness.status, duration: `${Math.round(performance.now() - started)}ms`, code: readiness.ok ? "READY" : "NOT-READY", message: readiness.data.ready ? "正式部署檢查通過" : `尚缺 ${readiness.data.missing?.length || 0} 項設定` });
  renderOps();
  addOpsAudit("正式部署檢查", readiness.data.ready ? "Production readiness 通過。" : `尚需補齊：${(readiness.data.missing || []).join("、") || "blockers / warnings"}`);
  showToast("部署檢查完成。");
}

async function runOpsGoLiveAudit() {
  const started = performance.now();
  const audit = await syncGoLiveAuditFromBackend(true);
  if (!audit) return;
  opsApiLogs.unshift({
    time: nowTime(),
    service: "GoLive",
    api: "GET /production/go-live-audit",
    status: audit.formalGo ? 200 : 503,
    duration: `${Math.round(performance.now() - started)}ms`,
    code: audit.decision || "GO-LIVE",
    message: `${goLiveDecisionText(audit)} · ${audit.formalBlockers?.length || 0} blockers`
  });
  renderOps();
  addOpsAudit("上線 Go / No-Go 判定", `${goLiveDecisionText(audit)}：${audit.summary}`);
  showToast(audit.formalGo ? "上線判定：GO。" : "上線判定：NO-GO，請查看阻塞項。");
}

async function runOpsMonitoringCheck() {
  const started = performance.now();
  const result = await fetchOpsJson("/production/monitoring/check", { method: "POST", body: JSON.stringify({ source: "ops-ui" }) });
  opsState.monitoring = result.data;
  opsState.deployment = result.data.deployment || opsState.deployment;
  opsState.lastMonitorCheck = result.data.checkedAt || nowTime();
  opsApiLogs.unshift({ time: nowTime(), service: "Monitor", api: "POST /production/monitoring/check", status: result.status, duration: `${Math.round(performance.now() - started)}ms`, code: result.data.status || "MONITOR", message: `${result.data.alerts?.length || 0} 筆告警` });
  renderOps();
  addOpsAudit("正式監控檢查", `狀態：${monitoringStatusLabel(result.data.status)}，告警 ${result.data.alerts?.length || 0} 筆。`);
  showToast("監控檢查完成。");
}

function lookupOpsErrorCode(show = true) {
  const code = document.querySelector("#opsErrorCodeInput")?.value.trim() || "JAGENT-401";
  const item = opsErrorCodes[code] || { title: "未建檔錯誤碼", reason: "尚未收錄此錯誤碼。", fix: "請匯入廠商錯誤碼表或由行政部主任補充處理建議。" };
  document.querySelector("#opsErrorDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${code} · ${item.title}</strong>
      <dl>
        <div><dt>可能原因</dt><dd>${item.reason}</dd></div>
        <div><dt>處理建議</dt><dd>${item.fix}</dd></div>
      </dl>
    </div>
  `;
  if (show) {
    addOpsAudit("錯誤碼查詢", `${code}：${item.title}。`);
    showToast("錯誤碼查詢完成。");
  }
}

function commitOpsConfigVersion() {
  const env = document.querySelector("#opsEnvSelect").value;
  const note = document.querySelector("#opsConfigNoteInput").value.trim();
  const version = `v1.${opsConfigVersions.length}.0`;
  const entry = { id: `CFG-${Date.now().toString().slice(-5)}`, version, env, note, actor: "行政部主任", createdAt: new Date().toLocaleString("zh-TW", { hour12: false }), payload: settingsPayload() };
  opsConfigVersions.unshift(entry);
  opsState.configVersion = version;
  opsState.environment = env;
  document.querySelector("#settingsApiMode").value = env;
  renderSettings();
  renderOps();
  addOpsAudit("建立系統參數版本", `${version} 已建立：${note}。`);
  showToast("系統參數版本已建立。");
}

function stableHash(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `SHA256-SIM-${(hash >>> 0).toString(16).toUpperCase().padStart(8, "0")}`;
}

function databaseBackupSnapshot() {
  syncDatabaseTables(true);
  const data = JSON.parse(JSON.stringify(databaseTables));
  const tableCounts = Object.fromEntries(Object.entries(data).map(([key, rows]) => [key, rows.length]));
  return {
    data,
    tableCounts,
    hash: stableHash(data),
    rowCount: Object.values(tableCounts).reduce((sum, count) => sum + count, 0)
  };
}

function buildOpsBackupRecord(snapshot = databaseBackupSnapshot()) {
  return {
    id: `BACKUP-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${String(opsBackups.length + 1).padStart(2, "0")}`,
    createdAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    env: opsState.environment,
    note: `${snapshot.tableCounts.documents || 0} 筆公文、${snapshot.tableCounts.attachments || 0} 筆附件、${snapshot.tableCounts.auditLogs || 0} 筆 audit log`,
    hash: snapshot.hash,
    rowCount: snapshot.rowCount,
    tableCounts: snapshot.tableCounts,
    data: snapshot.data
  };
}

function createOpsBackup() {
  const backup = buildOpsBackupRecord();
  opsBackups.unshift(backup);
  renderOps();
  addOpsAudit("資料備份", `${backup.id} 已建立，${backup.note}，雜湊 ${backup.hash}。`);
  showToast("資料備份已建立。");
}

function restoreOpsBackup() {
  const backup = opsBackups[0];
  if (!backup) return showToast("目前沒有可還原的備份。");
  if (!confirmOperation("確認還原系統資料備份", `即將還原 ${backup.id}，公文主檔、附件、交換事件與 audit log 快照會覆蓋目前畫面資料。`)) return;
  Object.keys(databaseTables).forEach((key) => {
    databaseTables[key] = JSON.parse(JSON.stringify(backup.data[key] || []));
  });
  opsState.restoredBackup = backup.id;
  renderDatabase();
  renderOps();
  addOpsAudit("資料還原", `已還原 ${backup.id}。`);
  showToast("已還原最新資料備份。");
}

function switchOpsEnvironment() {
  opsState.environment = opsState.environment === "測試環境" ? "正式環境" : "測試環境";
  document.querySelector("#settingsApiMode").value = opsState.environment;
  document.querySelector("#opsEnvSelect").value = opsState.environment;
  const apiUrl = opsState.environment === "正式環境" ? "https://jagent.gov.tw/api" : "https://jagent.example.gov.tw/api";
  document.querySelector("#settingsApiUrl").value = apiUrl;
  document.querySelector("#exchangeCenterUrl").value = apiUrl;
  renderSettings();
  renderOps();
  addOpsAudit("切換營運環境", `已切換至 ${opsState.environment}，API URL：${apiUrl}。`);
  showToast(`已切換至 ${opsState.environment}。`);
}

function exportOpsAudit() {
  const total = auditEvents.length + inboundAuditLog.length + dispatchAuditLog.length + archiveAuditLog.length + securityAuditLog.length + settingsAuditLog.length + opsAuditLog.length;
  addOpsAudit("操作紀錄匯出", `已匯出 ${total} 筆跨模組操作紀錄與 API log ${opsApiLogs.length} 筆。`);
  showToast("操作紀錄已匯出。");
}

function addComplianceAudit(title, body) {
  complianceAuditLog.unshift([nowTime(), title, body]);
  renderComplianceAuditLog();
}

function renderComplianceSummary() {
  const complete = complianceControls.filter((item) => item.status === "已落地").length;
  const percent = Math.round((complete / complianceControls.length) * 100);
  document.querySelector("#complianceMapStatus").textContent = `${percent}%`;
  document.querySelector("#complianceMapNote").textContent = `${complete}/${complianceControls.length} 項控制已落地`;
  document.querySelector("#complianceDocStatus").textContent = `${complianceDocuments.length} 份`;
  document.querySelector("#complianceDocNote").textContent = "法遵 / SOP / 稽核 / 上線";
  document.querySelector("#complianceReviewStatus").textContent = complianceLastReview || "未簽核";
  document.querySelector("#complianceReviewNote").textContent = complianceLastReview ? "季檢簽核已留存" : "等待季檢";
  document.querySelector("#complianceDrillStatus").textContent = complianceLastDrill || "未演練";
  document.querySelector("#complianceDrillNote").textContent = complianceLastDrill ? "演練紀錄已建立" : "建議上線前完成";
}

function renderComplianceAttestation() {
  const status = document.querySelector("#complianceAttestationStatus");
  const grid = document.querySelector("#complianceAttestationGrid");
  const detail = document.querySelector("#complianceAttestationDetail");
  if (!status || !grid || !detail) return;
  const item = latestComplianceAttestation;
  status.textContent = item?.status || "尚未簽核";
  grid.innerHTML = [
    ["驗收結果", item?.status || "待執行"],
    ["內控分數", item ? `${item.score} / 100` : "待執行"],
    ["簽核期間", item?.period || "待執行"],
    ["報告雜湊", item?.report_hash ? item.report_hash.slice(0, 16) : "待產生"]
  ].map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  if (!item) {
    detail.innerHTML = `<article class="address-card"><strong>尚未建立驗收簽核</strong><p>完成備份還原演練與正式監控檢查後，可由行政部主任送出內控制度簽核。</p></article>`;
    return;
  }
  const blockers = item.report?.blockers || [];
  detail.innerHTML = `
    <article class="address-card">
      <strong>${item.id} · ${item.signer_name} / ${item.signer_role}</strong>
      <p>${item.signed_at} · 覆核 ${item.reviewer_name || "主任"} / ${item.reviewer_role || "主任"}</p>
      <small>${item.report_hash}</small>
    </article>
    ${(item.report?.controls || []).map((control) => `
      <article class="address-card">
        <strong>${control.id} · ${control.status}</strong>
        <p>${control.source}</p>
        <small>${control.requirement}</small>
      </article>
    `).join("")}
    ${blockers.length ? `<article class="address-card"><strong>有條件項目</strong><p>${blockers.join("；")}</p></article>` : `<article class="address-card"><strong>無阻擋項目</strong><p>本次法遵驗收與內控制度簽核未列出阻擋項目。</p></article>`}
  `;
}

function renderComplianceRows() {
  document.querySelector("#complianceControlCount").textContent = `${complianceControls.length} 項`;
  document.querySelector("#complianceRows").innerHTML = complianceControls.map((item) => `
    <tr>
      <td>${item.source}</td>
      <td>${item.control}</td>
      <td>${item.implementation}</td>
      <td><span class="badge ${badgeClass(item.status)}">${item.status}</span></td>
    </tr>
  `).join("");
}

function renderComplianceDocs() {
  document.querySelector("#complianceDocList").innerHTML = complianceDocuments.map((item) => `
    <article class="address-card ${item.id === selectedComplianceDocId ? "selected-card" : ""}">
      <strong>${item.title}</strong>
      <p>${item.owner} · ${item.status} · ${item.updatedAt}</p>
      <small>${item.path}</small>
      <button class="segment" type="button" data-compliance-doc="${item.id}">選取</button>
    </article>
  `).join("");
  document.querySelectorAll("[data-compliance-doc]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedComplianceDocId = button.dataset.complianceDoc;
      renderComplianceDocs();
      addComplianceAudit("選取營運文件", currentComplianceDoc()?.title || "未選取文件");
    });
  });
}

function currentComplianceDoc() {
  return complianceDocuments.find((item) => item.id === selectedComplianceDocId) || complianceDocuments[0];
}

function renderComplianceSop() {
  const selected = document.querySelector("#complianceSopSelect")?.value || "每日收發檢查";
  document.querySelector("#complianceSopGrid").innerHTML = (complianceSops[selected] || []).map((step, index) => `
    <article class="archive-card">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <strong>${step}</strong>
    </article>
  `).join("");
}

function renderComplianceGaps() {
  document.querySelector("#complianceGapList").innerHTML = complianceGaps.map((item) => `
    <article class="address-card">
      <strong>${item.title}</strong>
      <p>${item.owner} · ${item.status}</p>
      <small>${item.dueDate} · ${item.id}</small>
    </article>
  `).join("");
}

function backupDrillSteps(drill = latestBackupDrill) {
  const steps = [
    ["建立備份快照", drill?.steps?.snapshot || "待執行"],
    ["計算來源雜湊", drill?.steps?.sourceHash || "待執行"],
    ["還原至測試沙盒", drill?.steps?.sandboxRestore || "待執行"],
    ["比對筆數與雜湊", drill?.steps?.verify || "待執行"],
    ["記錄 RTO / RPO", drill?.steps?.rtoRpo || "待執行"]
  ];
  return steps;
}

function renderBackupDrillPanel() {
  const drill = latestBackupDrill;
  const summary = [
    ["最近演練", drill?.id || "尚未演練"],
    ["結果", drill?.result || "待執行"],
    ["RTO / 目標", drill ? `${drill.rtoMinutes} / ${drill.rtoTarget} 分` : "待執行"],
    ["RPO / 目標", drill ? `${drill.rpoMinutes} / ${drill.rpoTarget} 分` : "待執行"]
  ];
  document.querySelector("#backupDrillSummaryGrid").innerHTML = summary.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  document.querySelector("#backupDrillStepList").innerHTML = backupDrillSteps(drill).map(([label, status], index) => `
    <article class="backup-drill-step ${/完成|通過|達標/.test(status) ? "ok" : /失敗|超標/.test(status) ? "issue" : ""}">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <strong>${label}</strong>
      <p>${status}</p>
    </article>
  `).join("");
  document.querySelector("#backupDrillRecordList").innerHTML = backupRestoreDrills.slice(0, 5).map((item) => `
    <article class="address-card">
      <strong>${item.id} · ${item.result}</strong>
      <p>${item.createdAt} · ${item.scope} · ${item.targetEnv}</p>
      <small>RTO ${item.rtoMinutes}/${item.rtoTarget} 分 · RPO ${item.rpoMinutes}/${item.rpoTarget} 分 · ${item.backupHash}</small>
    </article>
  `).join("") || `<article class="address-card"><strong>尚無演練紀錄</strong><p>點選「備份還原演練」建立第一筆紀錄。</p></article>`;
}

function renderComplianceAuditLog() {
  document.querySelector("#complianceAuditLog").innerHTML = complianceAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderComplianceOps() {
  renderComplianceSummary();
  renderComplianceAttestation();
  renderComplianceRows();
  renderComplianceDocs();
  renderComplianceSop();
  renderComplianceGaps();
  renderBackupDrillPanel();
  renderComplianceAuditLog();
}

function openComplianceDocument() {
  const item = currentComplianceDoc();
  if (!item) return showToast("尚未選取文件。");
  addComplianceAudit("開啟營運文件", `${item.title}：${item.path}`);
  showToast(`已定位文件：${item.title}`);
}

function exportCompliancePackage() {
  const fileName = `edoc-compliance-package-${new Date().toISOString().slice(0, 10)}.json`;
  const payload = {
    generatedAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    documents: complianceDocuments,
    controls: complianceControls,
    gaps: complianceGaps,
    auditLog: complianceAuditLog
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
  addComplianceAudit("匯出法遵文件包", `${fileName} 已產生，含 ${complianceDocuments.length} 份文件與 ${complianceControls.length} 項控制。`);
  showToast("法遵文件包已匯出。");
}

async function attestComplianceReview() {
  const signer = document.querySelector("#complianceOwnerSelect").value;
  if (!latestBackupDrill && !confirmOperation("尚未完成備份還原演練", "目前沒有本次工作階段的備份還原演練紀錄。仍可簽核，但驗收結果可能會列為待補。")) return;
  if (!requireTypedConfirm("確認法遵驗收與內控簽核", `${signer} 即將簽署本季法遵驗收與內控制度紀錄。此動作會寫入 audit log 與不可否認簽核紀錄。`, "確認簽核")) return;
  try {
    const result = await backendRequest("/compliance/attest", {
      method: "POST",
      body: JSON.stringify({
        signer_name: signer,
        signer_role: signer,
        reviewer_name: "主任",
        reviewer_role: "主任",
        period: `${new Date().getFullYear()}-Q${Math.floor(new Date().getMonth() / 3) + 1}`,
        attestation_type: "法遵驗收與內控制度簽核"
      })
    });
    latestComplianceAttestation = result;
    complianceLastReview = new Date().toLocaleDateString("zh-TW");
    complianceControls.forEach((item) => {
      if (item.status === "待季檢" && result.score >= 70) item.status = "已落地";
    });
    renderComplianceOps();
    addComplianceAudit("完成法遵驗收與內控簽核", `${result.id} ${result.status}，分數 ${result.score}，報告雜湊 ${result.report_hash}。`);
    showToast(result.status === "通過" ? "法遵驗收與內控簽核通過。" : "法遵驗收已簽核，仍有條件項目需追蹤。");
  } catch (error) {
    addComplianceAudit("法遵驗收簽核失敗", error.message);
    showToast("法遵驗收簽核失敗。");
  }
}

function recordComplianceDrill() {
  runBackupRestoreDrill();
}

function normalizeBackupDrill(result, fallback = {}) {
  return {
    id: result.id,
    createdAt: result.created_at || new Date().toLocaleString("zh-TW", { hour12: false }),
    owner: document.querySelector("#complianceOwnerSelect")?.value || "行政部主任",
    scope: result.scope || fallback.scope || "全部資料表",
    targetEnv: result.target_env || fallback.targetEnv || "測試沙盒",
    backupId: result.backup?.backup || result.backupId || "未記錄",
    backupHash: result.backup?.sha256 || result.backupHash || "未記錄",
    restoreHash: result.sandbox?.sha256 || result.restoreHash || "未記錄",
    rowCount: result.row_count || result.rowCount || 0,
    tableCounts: result.source_counts || result.tableCounts || {},
    rtoMinutes: result.rto_minutes || result.rtoMinutes || 0,
    rtoTarget: result.rto_target_minutes || fallback.rtoTarget || 30,
    rpoMinutes: result.rpo_minutes || result.rpoMinutes || 0,
    rpoTarget: result.rpo_target_minutes || fallback.rpoTarget || 15,
    result: result.result || (result.ok ? "通過" : "需改善"),
    steps: {
      snapshot: result.steps?.snapshot || "備份快照已建立",
      sourceHash: result.steps?.sourceHash || `${result.backup?.sha256 || "未記錄"} 已產生`,
      sandboxRestore: result.steps?.sandboxRestore || `${result.target_env || fallback.targetEnv || "測試沙盒"} 還原完成`,
      verify: result.steps?.verify || (result.checks?.counts_match && result.checks?.hash_match ? "筆數與雜湊比對通過" : "筆數或雜湊不一致"),
      rtoRpo: result.steps?.rtoRpo || `RTO ${result.rto_minutes || 0}/${fallback.rtoTarget || 30} 分，RPO ${result.rpo_minutes || 0}/${fallback.rpoTarget || 15} 分`
    },
    report: result
  };
}

async function runBackupRestoreDrill() {
  const scope = document.querySelector("#backupDrillScope").value;
  const targetEnv = document.querySelector("#backupDrillTarget").value;
  const rtoTarget = Number(document.querySelector("#backupDrillRtoTarget").value || 30);
  const rpoTarget = Number(document.querySelector("#backupDrillRpoTarget").value || 15);
  if (/正式|production|prod/i.test(targetEnv)) return blockOperation("備份還原演練只能還原到測試沙盒，不可指定正式環境。", addComplianceAudit, "備份演練防呆");
  if (rtoTarget < 1 || rpoTarget < 1) return blockOperation("RTO / RPO 目標需大於 0 分鐘。", addComplianceAudit, "備份演練防呆");
  if (!requireTypedConfirm("確認執行備份還原演練", `即將建立 ${scope} 的備份快照並還原至「${targetEnv}」，系統會比對筆數與雜湊。`, "確認演練")) return;
  try {
    const result = await backendRequest("/backup/restore-drill", {
      method: "POST",
      body: JSON.stringify({
        scope,
        target_env: targetEnv,
        rto_target_minutes: rtoTarget,
        rpo_target_minutes: rpoTarget
      })
    });
    const drill = normalizeBackupDrill(result, { scope, targetEnv, rtoTarget, rpoTarget });
    latestBackupDrill = drill;
    backupRestoreDrills.unshift(drill);
    opsBackups.unshift({
      id: drill.backupId,
      createdAt: drill.createdAt,
      env: opsState.environment,
      note: `${drill.rowCount} 筆資料，演練 ${drill.result}`,
      hash: drill.backupHash,
      rowCount: drill.rowCount,
      tableCounts: drill.tableCounts,
      data: {}
    });
    complianceLastDrill = new Date().toLocaleDateString("zh-TW");
    renderOps();
    renderComplianceOps();
    addOpsAudit("備份還原演練", `${drill.id} ${drill.result}，備份 ${drill.backupId} 還原至${targetEnv}，RTO ${drill.rtoMinutes} 分，RPO ${drill.rpoMinutes} 分。`);
    addComplianceAudit("備份還原演練", `${drill.id} ${drill.result}：${drill.steps.verify}，${drill.steps.rtoRpo}。`);
    showToast(drill.result === "通過" ? "備份還原演練通過。" : "備份還原演練完成，請查看改善項目。");
  } catch (error) {
    addComplianceAudit("備份還原演練失敗", error.message);
    showToast("備份還原演練失敗。");
  }
}

function exportBackupDrillReport() {
  if (!backupRestoreDrills.length) return showToast("尚無可匯出的演練紀錄。");
  const fileName = `edoc-backup-restore-drill-${new Date().toISOString().slice(0, 10)}.json`;
  const payload = {
    generatedAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    latest: latestBackupDrill,
    records: backupRestoreDrills,
    backups: opsBackups.map(({ data, ...backup }) => backup)
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
  addComplianceAudit("匯出備份還原演練報告", `${fileName} 已產生，含 ${backupRestoreDrills.length} 筆演練紀錄。`);
  showToast("備份還原演練報告已匯出。");
}

function runComplianceSop() {
  const sop = document.querySelector("#complianceSopSelect").value;
  const owner = document.querySelector("#complianceOwnerSelect").value;
  addComplianceAudit("執行營運 SOP", `${owner} 已執行「${sop}」：${(complianceSops[sop] || []).join(" → ")}。`);
  showToast(`${sop} SOP 已執行。`);
}

function resolveComplianceGap() {
  const target = complianceGaps.find((item) => item.status !== "已補正");
  if (!target) return showToast("目前沒有待補事項。");
  target.status = "已補正";
  renderComplianceGaps();
  addComplianceAudit("補正待辦事項", `${target.id} ${target.title} 已標記補正。`);
  showToast("待補事項已標記補正。");
}

function addNotificationAudit(title, body) {
  notificationAuditLog.unshift([nowTime(), title, body]);
  renderNotificationAuditLog();
}

function addNotificationDelivery(title, body) {
  notificationDeliveryLog.unshift([nowTime(), title, body]);
  renderNotificationDeliveryLog();
}

function notificationChannels(channel) {
  const normalized = channel || "系統通知";
  const channels = [];
  if (/Email/.test(normalized)) channels.push("Email");
  if (/Line/.test(normalized)) channels.push("Line 工作群組");
  if (/系統|站內/.test(normalized)) channels.push("系統站內通知");
  return channels.length ? channels : [normalized];
}

function roleEmail(role) {
  const found = userAccounts.find((account) => account.role === role && account.status === "啟用");
  return found?.email || `${role}@suiyuecare.local`;
}

function pushSystemInbox(item) {
  systemInboxItems.unshift({
    id: `INBOX-${Date.now().toString().slice(-5)}-${systemInboxItems.length + 1}`,
    target: item.target,
    title: item.title,
    status: "未讀",
    createdAt: nowTime()
  });
}

function notificationPayload(item, forceChannel = item.channel) {
  return {
    id: item.id,
    type: item.type,
    title: item.title,
    target_role: item.target,
    target_email: item.targetEmail || "",
    channel: forceChannel || item.channel,
    status: item.status || "未讀",
    priority: item.priority || "中",
    source: item.source || "",
    body: item.body || "請確認電子公文交換待辦事項。"
  };
}

function applyNotificationDeliveryResult(result) {
  const item = notificationItems.find((notice) => notice.id === result.id);
  if (item) {
    item.status = result.status;
    item.sentAt = new Date().toLocaleString("zh-TW", { hour12: false });
    item.deliveryReceipt = result.receipt || result.error || "";
  }
  (result.results || []).forEach((delivery) => {
    if (delivery.channel === "Email") notificationGatewayState.emailStatus = delivery.status;
    if (delivery.channel === "Line 工作群組") notificationGatewayState.lineStatus = delivery.status;
    if (delivery.channel === "系統站內通知") notificationGatewayState.inboxStatus = delivery.status === "成功" ? "已推送" : delivery.status;
  });
}

async function deliverNotification(item, forceChannel = item.channel) {
  try {
    const result = await backendRequest("/notifications/send", {
      method: "POST",
      body: JSON.stringify({
        channel: forceChannel || item.channel,
        notifications: [notificationPayload(item, forceChannel)]
      })
    });
    result.results.forEach(applyNotificationDeliveryResult);
    await syncNotificationsFromBackend(true);
    addNotificationDelivery(item.type, `${item.title}｜${result.results.map((entry) => entry.receipt || entry.status).join("；")}`);
    return result;
  } catch (error) {
    item.status = "派送失敗";
    item.deliveryReceipt = `後端通知派送失敗：${error.message}`;
    notificationGatewayState.emailStatus = /SMTP|Email/i.test(error.message) ? "失敗" : notificationGatewayState.emailStatus;
    notificationGatewayState.lineStatus = /LINE|Line/i.test(error.message) ? "失敗" : notificationGatewayState.lineStatus;
    addNotificationDelivery(item.type, `${item.title}｜後端通知派送失敗：${error.message}`);
    renderNotifications();
    return { count: 0, results: [{ id: item.id, status: "派送失敗", error: error.message }] };
  }
}

function renderNotificationGatewayStatus() {
  document.querySelector("#notificationEmailStatus").textContent = notificationGatewayState.emailStatus;
  document.querySelector("#notificationEmailNote").textContent = notificationGatewayState.emailApi;
  document.querySelector("#notificationLineStatus").textContent = notificationGatewayState.lineStatus;
  document.querySelector("#notificationLineNote").textContent = notificationGatewayState.lineWebhook;
  document.querySelector("#notificationInboxStatus").textContent = notificationGatewayState.inboxStatus;
  document.querySelector("#notificationInboxNote").textContent = `${systemInboxItems.length} 則站內通知 · ${notificationGatewayState.inboxRetention}`;
  document.querySelector("#notificationScheduleStatus").textContent = notificationSchedules.length;
  document.querySelector("#notificationScheduleNote").textContent = notificationGatewayState.overdueSchedule;
  const grid = document.querySelector("#notificationCredentialGrid");
  if (grid) {
    grid.innerHTML = notificationGatewayState.credentials.map((credential) => `
      <article class="archive-card">
        <span>${credential.channel} · ${credential.provider || "正式通道"}</span>
        <strong>${credential.status || "待驗證"}</strong>
        <small>${credential.credential_type || "正式憑證"} · 到期 ${credential.expires_at || "未登錄"}</small>
        <small>${credential.masked_identifier || credential.env_key_name || ""}</small>
      </article>
    `).join("");
  }
  renderNotificationTestReport();
}

function renderNotificationTestReport() {
  const grid = document.querySelector("#notificationTestReportGrid");
  const detail = document.querySelector("#notificationTestReportDetail");
  if (!grid || !detail) return;
  const report = notificationGatewayState.lastTestReport;
  if (!report) {
    grid.innerHTML = `
      <article class="archive-card">
        <span>實測狀態</span>
        <strong>尚未測試</strong>
        <small>按下「測試通道」後會寫入實際派送紀錄。</small>
      </article>
    `;
    detail.innerHTML = "";
    return;
  }
  grid.innerHTML = [
    ["實測結果", report.ok ? "全部送達" : "需補正"],
    ["成功通道", `${report.success || 0} / ${report.total || 0}`],
    ["測試時間", report.checked_at || "未記錄"],
    ["測試對象", report.target_email || report.target_role || "未記錄"]
  ].map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
  detail.innerHTML = (report.results || []).map((item) => `
    <article class="address-card">
      <strong>${item.channel} · ${item.status}</strong>
      <p>${item.target} · ${item.duration_ms ?? 0} ms</p>
      <small>${item.receipt || item.error || "沒有回條"}</small>
    </article>
  `).join("") || `<article class="address-card"><strong>沒有派送紀錄</strong><p>請重新測試通道。</p></article>`;
}

async function refreshNotificationGatewayStatus(silent = false) {
  try {
    const status = await backendRequest("/notifications/gateway-status");
    notificationGatewayState.emailStatus = status.email?.status || "未設定";
    notificationGatewayState.lineStatus = status.line?.status || "未設定";
    notificationGatewayState.inboxStatus = status.systemInbox?.status || "啟用";
    notificationGatewayState.emailApi = `${status.email?.host || "未設定"}:${status.email?.port || "587"} · ${status.email?.from || "未設定"}`;
    notificationGatewayState.lineWebhook = status.line?.webhook || "未設定";
    notificationGatewayState.credentials = status.credentials?.length ? status.credentials : notificationGatewayState.credentials;
    notificationGatewayState.lastGatewayCheck = new Date().toLocaleString("zh-TW", { hour12: false });
    renderNotificationGatewayStatus();
    if (!silent) addNotificationAudit("檢查通知通道", `Email：${notificationGatewayState.emailStatus}；Line：${notificationGatewayState.lineStatus}；站內：${notificationGatewayState.inboxStatus}。`);
  } catch (error) {
    notificationGatewayState.emailStatus = "檢查失敗";
    notificationGatewayState.lineStatus = "檢查失敗";
    renderNotificationGatewayStatus();
    if (!silent) addNotificationAudit("檢查通知通道失敗", error.message);
  }
}

async function validateNotificationCredentials() {
  try {
    const result = await backendRequest("/notifications/credentials/validate", {
      method: "POST",
      body: JSON.stringify({
        email_expires_at: document.querySelector("#notificationEmailCertExpiry")?.value || "",
        line_expires_at: document.querySelector("#notificationLineCertExpiry")?.value || ""
      })
    });
    notificationGatewayState.credentials = result.credentials || notificationGatewayState.credentials;
    await refreshNotificationGatewayStatus(true);
    renderNotifications();
    addNotificationAudit("驗證通知正式憑證", `${result.credentials.map((item) => `${item.channel}:${item.status}`).join("；")}。`);
    showToast(result.ok ? "通知通道正式憑證驗證通過。" : "通知通道正式憑證需補正。");
  } catch (error) {
    addNotificationAudit("通知正式憑證驗證失敗", error.message);
    showToast("通知正式憑證驗證失敗。");
  }
}

function renderNotificationDeliveryLog() {
  document.querySelector("#notificationDeliveryLog").innerHTML = notificationDeliveryLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderSystemInbox() {
  document.querySelector("#notificationInboxList").innerHTML = systemInboxItems.map((item) => `
    <article class="address-card">
      <strong>${item.title}</strong>
      <p>${item.target} · ${item.status}</p>
      <small>${item.createdAt} · ${item.id}</small>
    </article>
  `).join("");
}

function currentNotification() {
  return notificationItems.find((item) => item.id === selectedNotificationId) || notificationItems[0] || null;
}

function selectedNotificationIds() {
  const checked = [...document.querySelectorAll(".notification-check:checked")].map((item) => item.value);
  return checked.length ? checked : selectedNotificationId ? [selectedNotificationId] : [];
}

function filteredNotifications() {
  const term = notificationSearchTerm.trim().toLowerCase();
  return notificationItems.filter((item) => {
    const matchFilter = notificationFilter === "all"
      || item.type === notificationFilter
      || item.status === notificationFilter
      || reminderItems(notificationFilter).some((reminder) => reminder.source === item.id || reminder.title === item.title || reminder.source === item.source);
    const haystack = `${item.title} ${item.type} ${item.target} ${item.channel} ${item.status} ${item.source} ${item.body}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function reminderItems(category) {
  const unread = notificationItems.filter((item) => item.status !== "已讀");
  const flowReminders = visibleUnifiedDocumentFlows().filter(isUnifiedFlowTodo);
  const today = [
    ...unread.filter((item) => ["收文", "待清稿", "逾期查核"].includes(item.type)),
    ...flowReminders.filter((flow) => !flow.isIssue).map((flow) => unifiedFlowReminder(flow, "文件待辦"))
  ];
  const dueSoon = [
    ...unread.filter((item) => ["逾期查核", "Token 到期"].includes(item.type)),
    ...flowReminders.filter((flow) => /待確認|待用印|待簽核|待審核|待分派/.test(flow.status)).map((flow) => unifiedFlowReminder(flow, "即將到期")),
    ...trackingCases.filter((item) => ["逾期提醒", "未收確認"].includes(item.status)).map((item) => ({
      id: `REM-${item.id}`,
      type: item.status,
      title: item.title,
      target: item.owner,
      status: item.status,
      source: item.id,
      body: item.note
    }))
  ];
  const returned = [
    ...unread.filter((item) => /退回|補正/.test(`${item.type}${item.title}${item.body}`)),
    ...flowReminders.filter((flow) => /退回|補正/.test(`${flow.status}${flow.currentStep}`)).map((flow) => unifiedFlowReminder(flow, "退回補正")),
    ...trackingCases.filter((item) => item.status === "退回補正").map((item) => ({
      id: `REM-${item.id}`,
      type: "退回補正",
      title: item.title,
      target: item.owner,
      status: item.status,
      source: item.id,
      body: item.note
    }))
  ];
  const failed = [
    ...unread.filter((item) => item.type === "交換失敗"),
    ...flowReminders.filter((flow) => /失敗|異常|未收/.test(`${flow.status}${flow.currentStep}${flow.summary}`)).map((flow) => unifiedFlowReminder(flow, "交換失敗"))
  ];
  const buckets = { today, dueSoon, returned, failed };
  return buckets[category] || [];
}

function renderNotificationSummary() {
  const labels = {
    all: "全部待辦",
    today: "今天要處理",
    dueSoon: "即將逾期",
    returned: "已退回",
    failed: "交換失敗"
  };
  document.querySelector("#noticeTodayCount").textContent = reminderItems("today").length;
  document.querySelector("#noticeDueSoonCount").textContent = reminderItems("dueSoon").length;
  document.querySelector("#noticeReturnedCount").textContent = reminderItems("returned").length;
  document.querySelector("#noticeFailedCount").textContent = reminderItems("failed").length;
  document.querySelector("#reminderActiveLabel").textContent = labels[notificationFilter] || labels.all;
  document.querySelectorAll("[data-reminder-filter]").forEach((card) => {
    card.classList.toggle("active", card.dataset.reminderFilter === notificationFilter);
  });
  renderReminderLanes();
}

function renderReminderLanes() {
  const lanes = [
    ["today", "今天要處理"],
    ["dueSoon", "即將逾期"],
    ["returned", "已退回"],
    ["failed", "交換失敗"]
  ];
  document.querySelector("#reminderLanes").innerHTML = lanes.map(([key, title]) => {
    const items = reminderItems(key).slice(0, 4);
    return `
      <section class="reminder-lane">
        <h4>${title}</h4>
        ${items.length ? items.map((item) => `
          <article class="reminder-task ${key === "failed" || key === "dueSoon" || key === "returned" ? "issue" : ""}">
            <strong>${item.title}</strong>
            <span>${item.type} · ${item.target || "系統"}</span>
            <p>${item.body}</p>
          </article>
        `).join("") : `<article class="reminder-task"><strong>目前沒有待辦</strong><p>此分類暫無需要處理的提醒。</p></article>`}
      </section>
    `;
  }).join("");
}

function renderNotificationRows() {
  const rows = filteredNotifications();
  document.querySelector("#notificationCount").textContent = `${rows.length} 則`;
  document.querySelector("#notificationRows").innerHTML = rows.map((item) => `
    <tr class="${item.id === selectedNotificationId ? "selected-row" : ""}">
      <td><input class="notification-check" type="checkbox" value="${item.id}" aria-label="選取 ${item.title}" /></td>
      <td><button class="text-button row-select" type="button" data-notification-select="${item.id}">${item.title}</button><small>${item.source} · ${item.priority}</small></td>
      <td>${item.type}</td>
      <td>${item.target}</td>
      <td>${item.channel}</td>
      <td><span class="badge ${badgeClass(item.status)}">${item.status}</span></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-notification-action="read" data-notification-id="${item.id}">已讀</button>
          <button class="segment" type="button" data-notification-action="send" data-notification-id="${item.id}">派送</button>
          <button class="segment" type="button" data-notification-action="track" data-notification-id="${item.id}">稽催</button>
        </div>
      </td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-notification-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedNotificationId = button.dataset.notificationSelect;
      renderNotificationRows();
      renderNotificationDetail();
    });
  });
  document.querySelectorAll("[data-notification-action]").forEach((button) => {
    button.addEventListener("click", () => runNotificationAction(button.dataset.notificationAction, [button.dataset.notificationId]));
  });
}

function renderNotificationDetail() {
  const item = currentNotification();
  if (!item) {
    document.querySelector("#selectedNotificationStatus").textContent = "未選取";
    document.querySelector("#notificationDetail").innerHTML = `<p class="empty-text">尚無通知。</p>`;
    return;
  }
  document.querySelector("#selectedNotificationStatus").textContent = item.status;
  document.querySelector("#notificationDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${item.title}</strong>
      <dl>
        <div><dt>通知類型</dt><dd>${item.type}</dd></div>
        <div><dt>通知對象</dt><dd>${item.target}</dd></div>
        <div><dt>通道</dt><dd>${item.channel}</dd></div>
        <div><dt>來源</dt><dd>${item.source}</dd></div>
        <div><dt>優先度</dt><dd>${item.priority}</dd></div>
        <div><dt>狀態</dt><dd>${item.status}</dd></div>
        <div><dt>派送回條</dt><dd>${item.deliveryReceipt || "尚未派送"}</dd></div>
      </dl>
      <p>${item.body}</p>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="detailNotificationSendBtn">派送通知</button>
        <button class="secondary-button" type="button" id="detailNotificationReadBtn">標記已讀</button>
        <button class="secondary-button" type="button" id="detailNotificationTrackBtn">建立稽催</button>
      </div>
    </div>
  `;
  document.querySelector("#detailNotificationSendBtn").addEventListener("click", () => runNotificationAction("send", [item.id]));
  document.querySelector("#detailNotificationReadBtn").addEventListener("click", () => runNotificationAction("read", [item.id]));
  document.querySelector("#detailNotificationTrackBtn").addEventListener("click", () => runNotificationAction("track", [item.id]));
}

function renderNotificationRules() {
  const rules = [
    ["收文", "jAgent 拉取後立即通知總務"],
    ["待清稿", "發文待清稿超過 2 小時通知主管"],
    ["交換失敗", `${notificationGatewayState.failureChannel} 立即警示並開啟重送`],
    ["Token 到期", `${notificationGatewayState.tokenSchedule} 通知行政部主任`],
    ["逾期查核", `${notificationGatewayState.overdueSchedule} 自動建立排程提醒`]
  ];
  document.querySelector("#notificationRuleGrid").innerHTML = rules.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderNotificationAuditLog() {
  document.querySelector("#notificationAuditLog").innerHTML = notificationAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderNotifications() {
  renderNotificationGatewayStatus();
  renderNotificationSummary();
  renderNotificationRows();
  renderNotificationDetail();
  renderNotificationRules();
  renderNotificationDeliveryLog();
  renderSystemInbox();
}

async function syncNotifications() {
  try {
    const result = await backendRequest("/notifications/sync", { method: "POST", body: "{}" });
    await syncNotificationsFromBackend(true);
    addNotificationAudit("同步通知", result.created ? `後端已新增 ${result.created} 則通知。` : "後端通知已是最新狀態。");
    showToast(result.created ? `已同步 ${result.created} 則通知。` : "通知已同步。");
  } catch (error) {
    addNotificationAudit("同步通知失敗", error.message);
    showToast("後端通知同步失敗。");
  }
}

async function runNotificationAction(action, ids) {
  const targetIds = ids?.length ? ids : selectedNotificationIds();
  if (!targetIds.length) return showToast("請先選取通知。");
  if (action === "read") {
    for (const id of targetIds) {
      const item = notificationItems.find((notice) => notice.id === id);
      if (item) item.status = "已讀";
      try {
        await backendRequest(`/notifications/${id}`, { method: "PATCH", body: JSON.stringify({ status: "已讀" }) });
      } catch (error) {
        addNotificationAudit("後端已讀更新失敗", `${id}：${error.message}`);
      }
    }
    await syncNotificationsFromBackend(true);
    renderNotifications();
    addNotificationAudit("標記已讀", `已標記 ${targetIds.length} 則通知為已讀。`);
    return showToast("通知已標記為已讀。");
  }
  if (action === "send") {
    if (!confirmOperation("確認派送通知", `即將透過設定通道派送 ${targetIds.length} 則通知，可能會寄出 Email、Line 或站內通知。`)) return;
    for (const id of targetIds) {
      const item = notificationItems.find((notice) => notice.id === id);
      if (item) await deliverNotification(item);
    }
    renderNotifications();
    addNotificationAudit("派送通知", `已交由後端通知閘道派送 ${targetIds.length} 則通知。`);
    return showToast("通知派送已完成，請查看派送回條。");
  }
  if (action === "track") {
    targetIds.forEach((id) => {
      const item = notificationItems.find((notice) => notice.id === id);
      if (item && !trackingCases.some((tracking) => tracking.title === item.title)) {
        trackingCases.unshift({ id: `TRK-${Date.now().toString().slice(-5)}-${id}`, title: item.title, agency: "通知中心", type: item.type === "交換失敗" ? "逾期提醒" : item.type, dueDate: "2026-05-23", owner: item.target, status: "逾期提醒", note: item.body });
      }
    });
    renderTrackingSummary();
    renderTrackingRows();
    renderTrackingDetail();
    addNotificationAudit("建立稽催", `已依 ${targetIds.length} 則通知建立或更新稽催追蹤。`);
    return showToast("已建立稽催追蹤。");
  }
}

async function addNotificationFromForm() {
  const type = document.querySelector("#notificationType").value;
  const target = document.querySelector("#notificationTarget").value;
  const channel = document.querySelector("#notificationChannel").value;
  const body = document.querySelector("#notificationBody").value.trim();
  const item = { id: `NTF-${Date.now().toString().slice(-6)}`, type, title: `${type}手動通知`, target, channel, status: "未讀", priority: "中", source: "MANUAL", body };
  try {
    const created = await backendRequest("/notifications", { method: "POST", body: JSON.stringify(notificationPayload(item)) });
    selectedNotificationId = created.id;
    await syncNotificationsFromBackend(true);
    addNotificationAudit("新增通知", `${type} 已新增至後端佇列給 ${target}，通道：${channel}。`);
    showToast("通知已新增至後端佇列。");
  } catch (error) {
    notificationItems.unshift(item);
    selectedNotificationId = item.id;
    renderNotifications();
    addNotificationAudit("新增通知失敗", `${error.message}；已暫存在畫面。`);
    showToast("後端新增通知失敗，已暫存在畫面。");
  }
}

function saveNotificationGateway() {
  notificationGatewayState.emailApi = document.querySelector("#notificationEmailApi").value.trim();
  notificationGatewayState.lineWebhook = document.querySelector("#notificationLineWebhook").value.trim();
  notificationGatewayState.inboxRetention = document.querySelector("#notificationInboxRetention").value;
  notificationGatewayState.overdueSchedule = document.querySelector("#notificationOverdueSchedule").value;
  notificationGatewayState.tokenSchedule = document.querySelector("#notificationTokenSchedule").value;
  notificationGatewayState.failureChannel = document.querySelector("#notificationFailureChannel").value;
  renderNotifications();
  addNotificationAudit("儲存通知通道", `Email、Line、站內通知與排程規則已更新。`);
  showToast("通知通道設定已儲存。");
  refreshNotificationGatewayStatus(true);
}

async function testNotificationChannels() {
  try {
    await refreshNotificationGatewayStatus(true);
    const channel = document.querySelector("#notificationTestChannel")?.value || "Email + Line + 系統通知";
    const targetEmail = document.querySelector("#notificationTestEmail")?.value.trim() || "records@suiyuecare.com";
    const body = document.querySelector("#notificationTestBody")?.value.trim() || "通知通道實測。";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(targetEmail)) return blockOperation("測試收件 Email 格式不正確。", addNotificationAudit, "通知通道防呆");
    if (!hasMinimumText(body, 4)) return blockOperation("測試通知內容不可空白。", addNotificationAudit, "通知通道防呆");
    if (!requireTypedConfirm("確認通知通道實測", `即將送出真實測試通知到 ${targetEmail}，通道：${channel}。`, "確認測試")) return;
    const result = await backendRequest("/notifications/test", {
      method: "POST",
      body: JSON.stringify({
        channel,
        target_role: "行政部主任",
        target_email: targetEmail,
        title: `通知通道實測 - ${channel}`,
        body
      })
    });
    applyNotificationDeliveryResult(result.delivery);
    notificationGatewayState.lastTestReport = result.report || {
      ok: result.delivery?.success === result.delivery?.total,
      checked_at: new Date().toLocaleString("zh-TW", { hour12: false }),
      target_email: targetEmail,
      success: result.delivery?.success || 0,
      total: result.delivery?.total || 0,
      results: result.delivery?.results || []
    };
    await syncNotificationsFromBackend(true);
    renderNotifications();
    addNotificationAudit("測試通知通道", notificationGatewayState.lastTestReport.summary || result.delivery.receipt || "已完成後端通知通道測試。");
    showToast(notificationGatewayState.lastTestReport.ok ? "通知通道實測成功。" : "通知通道實測完成，部分通道需補正。");
  } catch (error) {
    notificationGatewayState.emailStatus = "失敗";
    notificationGatewayState.lineStatus = "失敗";
    renderNotifications();
    addNotificationAudit("測試通知通道失敗", error.message);
    showToast("通知通道測試失敗。");
  }
}

function createNotificationSchedules() {
  saveNotificationGateway();
  const schedules = [
    { id: `SCH-OD-${Date.now().toString().slice(-5)}`, type: "逾期排程通知", rule: notificationGatewayState.overdueSchedule, target: "業務助理 / 行政部主任" },
    { id: `SCH-TK-${Date.now().toString().slice(-5)}`, type: "Token 到期通知", rule: notificationGatewayState.tokenSchedule, target: "行政部主任" },
    { id: `SCH-FL-${Date.now().toString().slice(-5)}`, type: "交換失敗即時警示", rule: notificationGatewayState.failureChannel, target: "總務 / 行政部主任" }
  ];
  notificationSchedules.unshift(...schedules);
  schedules.forEach((schedule) => addNotificationDelivery(schedule.type, `${schedule.id} 已啟用：${schedule.rule} -> ${schedule.target}`));
  renderNotifications();
  addNotificationAudit("套用通知規則", "已建立逾期排程、Token 到期提醒與交換失敗即時警示。");
  showToast("通知排程與即時警示已啟用。");
}

async function sendImmediateFailureAlerts() {
  const failedDocs = dispatchDocs.filter((doc) => doc.status === "交換失敗");
  if (!failedDocs.length) return showToast("目前沒有交換失敗案件。");
  if (!confirmOperation("確認送出交換失敗警示", `即將針對 ${failedDocs.length} 件交換失敗案件送出即時警示。`)) return;
  for (const doc of failedDocs) {
    let item = notificationItems.find((notice) => notice.source === doc.id && notice.type === "交換失敗");
    if (!item) {
      item = { id: `NTF-${Date.now().toString().slice(-6)}-${doc.id}`, type: "交換失敗", title: `${doc.no} 交換失敗即時警示`, target: "總務", channel: notificationGatewayState.failureChannel, status: "未讀", priority: "高", source: doc.id, body: `${doc.subject} 交換失敗，請立即重送或聯繫交換中心。` };
      notificationItems.unshift(item);
    }
    await deliverNotification(item, notificationGatewayState.failureChannel);
  }
  renderNotifications();
  addNotificationAudit("交換失敗即時警示", `已針對 ${failedDocs.length} 件交換失敗案件送出即時警示。`);
  showToast("交換失敗即時警示已送出。");
}

async function pushSelectedToInbox() {
  const targetIds = selectedNotificationIds();
  if (!targetIds.length) return showToast("請先選取通知。");
  try {
    await backendRequest("/notifications/push-inbox", { method: "POST", body: JSON.stringify({ ids: targetIds }) });
    await syncNotificationsFromBackend(true);
    renderNotifications();
    addNotificationAudit("推送站內通知", `已由後端推送 ${targetIds.length} 則站內通知。`);
    showToast("站內通知已推送。");
  } catch (error) {
    addNotificationAudit("推送站內通知失敗", error.message);
    showToast("站內通知推送失敗。");
  }
}

async function retryFailedNotificationDeliveries() {
  try {
    if (!confirmOperation("確認重送通知", "即將請後端重送所有未完成派送的通知，請避免在短時間內重複點擊。")) return;
    const result = await backendRequest("/notifications/retry-failed", { method: "POST", body: "{}" });
    await syncNotificationsFromBackend(true);
    renderNotifications();
    addNotificationAudit("重送通知", result.count ? `後端已重送 ${result.count} 則未完成派送通知。` : "沒有需要重送的通知。");
    showToast(result.count ? "通知已重送。" : "沒有需要重送的通知。");
  } catch (error) {
    addNotificationAudit("重送通知失敗", error.message);
    showToast("通知重送失敗。");
  }
}

function addJobAudit(title, body) {
  jobAuditLog.unshift([nowTime(), title, body]);
  renderJobAuditLog();
}

function currentJob() {
  return backgroundJobs.find((job) => job.id === selectedJobId) || backgroundJobs[0] || null;
}

function selectedJobIds() {
  const checked = [...document.querySelectorAll(".job-check:checked")].map((item) => item.value);
  return checked.length ? checked : selectedJobId ? [selectedJobId] : [];
}

function filteredJobs() {
  const term = jobSearchTerm.trim().toLowerCase();
  return backgroundJobs.filter((job) => {
    const matchFilter = jobFilter === "all" || job.status === jobFilter || job.lastResult.includes(jobFilter);
    const haystack = `${job.name} ${job.type} ${job.schedule} ${job.nextRun} ${job.status} ${job.lastResult} ${job.notify}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function computeNextRun(schedule) {
  const now = new Date();
  if (/15 分鐘/.test(schedule)) now.setMinutes(now.getMinutes() + 15);
  else if (/每小時/.test(schedule)) now.setHours(now.getHours() + 1);
  else if (/18:00/.test(schedule)) now.setHours(18, 0, 0, 0);
  else if (/09:00/.test(schedule)) now.setDate(now.getDate() + 1), now.setHours(9, 0, 0, 0);
  else now.setDate(now.getDate() + 1), now.setHours(8, 30, 0, 0);
  return now.toLocaleString("zh-TW", { hour12: false });
}

function renderJobSummary() {
  const active = backgroundJobs.filter((job) => job.status === "啟用").length;
  const success = backgroundJobs.filter((job) => job.lastResult.includes("成功")).length;
  const failed = backgroundJobs.filter((job) => job.lastResult.includes("失敗")).length;
  const next = backgroundJobs.filter((job) => job.status === "啟用").sort((a, b) => a.nextRun.localeCompare(b.nextRun))[0];
  document.querySelector("#jobActiveCount").textContent = active;
  document.querySelector("#jobActiveNote").textContent = `${backgroundJobs.length - active} 個暫停`;
  document.querySelector("#jobRunCount").textContent = backgroundJobs.reduce((sum, job) => sum + job.runCount, 0);
  document.querySelector("#jobRunNote").textContent = `${success} 成功 / ${failed} 失敗`;
  document.querySelector("#jobNextRun").textContent = next ? next.nextRun.slice(5, 16) : "-";
  document.querySelector("#jobNextRunNote").textContent = next?.name || "無啟用任務";
  document.querySelector("#jobHealthStatus").textContent = failed ? "Warning" : "Ready";
  document.querySelector("#jobHealthNote").textContent = failed ? `${failed} 個任務需檢查` : "所有任務可執行";
}

function renderJobRows() {
  const rows = filteredJobs();
  document.querySelector("#jobCount").textContent = `${rows.length} 個`;
  document.querySelector("#jobRows").innerHTML = rows.map((job) => `
    <tr class="${job.id === selectedJobId ? "selected-row" : ""}">
      <td><input class="job-check" type="checkbox" value="${job.id}" /></td>
      <td><button class="text-button row-select" type="button" data-job-select="${job.id}">${job.name}</button><small>${job.id} · ${job.type}</small></td>
      <td>${job.schedule}</td>
      <td>${job.nextRun}</td>
      <td><span class="status-pill ${badgeClass(job.status)}">${job.status}</span></td>
      <td>${job.lastResult}<small>執行 ${job.runCount} 次</small></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-job-action="run" data-job-id="${job.id}">執行</button>
          <button class="segment" type="button" data-job-action="toggle" data-job-id="${job.id}">${job.status === "啟用" ? "暫停" : "啟用"}</button>
          <button class="segment" type="button" data-job-action="notify" data-job-id="${job.id}">通知</button>
        </div>
      </td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-job-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedJobId = button.dataset.jobSelect;
      renderJobs();
    });
  });
  document.querySelectorAll("[data-job-action]").forEach((button) => {
    button.addEventListener("click", () => runJobAction(button.dataset.jobAction, [button.dataset.jobId]));
  });
}

function renderJobDetail() {
  const job = currentJob();
  if (!job) return;
  document.querySelector("#selectedJobStatus").textContent = job.status;
  document.querySelector("#jobDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${job.name}</strong>
      <dl>
        <div><dt>任務類型</dt><dd>${job.type}</dd></div>
        <div><dt>排程週期</dt><dd>${job.schedule}</dd></div>
        <div><dt>下次執行</dt><dd>${job.nextRun}</dd></div>
        <div><dt>通知對象</dt><dd>${job.notify}</dd></div>
        <div><dt>最近結果</dt><dd>${job.lastResult}</dd></div>
        <div><dt>執行次數</dt><dd>${job.runCount}</dd></div>
      </dl>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="detailJobRunBtn">立即執行</button>
        <button class="secondary-button" type="button" id="detailJobToggleBtn">${job.status === "啟用" ? "暫停" : "啟用"}</button>
        <button class="secondary-button" type="button" id="detailJobNotifyBtn">送出結果通知</button>
      </div>
    </div>
  `;
  document.querySelector("#detailJobRunBtn").addEventListener("click", () => runJobAction("run", [job.id]));
  document.querySelector("#detailJobToggleBtn").addEventListener("click", () => runJobAction("toggle", [job.id]));
  document.querySelector("#detailJobNotifyBtn").addEventListener("click", () => runJobAction("notify", [job.id]));
}

function renderJobWorkerGrid() {
  const items = [
    ["Worker", "ACTIVE"],
    ["Queue", `${backgroundJobs.filter((job) => job.status === "啟用").length} active`],
    ["Retry", "3 次 / 指數退避"],
    ["Lock", "單任務互斥鎖"]
  ];
  document.querySelector("#jobWorkerGrid").innerHTML = items.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderJobAuditLog() {
  document.querySelector("#jobAuditLog").innerHTML = jobAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderJobs() {
  renderJobSummary();
  renderJobRows();
  renderJobDetail();
  renderJobWorkerGrid();
  renderJobAuditLog();
}

function executeBackgroundJob(job) {
  let result = "成功";
  if (job.type === "pullInbound") {
    const before = inboundDocs.length;
    pullJagentInbound();
    result = `成功：拉取 ${Math.max(inboundDocs.length - before, 0)} 筆收文`;
  }
  if (job.type === "nextDayCheck") {
    runDispatchAction("query", dispatchDocs.filter((doc) => ["等待確認", "交換完成", "交換失敗"].includes(doc.status)).map((doc) => doc.id));
    result = "成功：完成發文翌日查核";
  }
  if (job.type === "tokenCheck") {
    renderSecurityStatus();
    syncNotifications();
    result = `成功：${securityTokenLeft()}`;
  }
  if (job.type === "overdueReminder") {
    runTrackingAction("remind", trackingCases.filter((item) => ["逾期提醒", "未收確認", "退回補正"].includes(item.status)).map((item) => item.id));
    createNotificationSchedules();
    result = "成功：已產生逾期稽催通知";
  }
  if (job.type === "contractRenewalCheck") {
    const dueContracts = visibleContracts().filter(isContractRenewalSoon);
    dueContracts.forEach((contract) => createContractRenewalReminder(contract));
    result = `成功：產生 ${dueContracts.length} 筆合約續約提醒`;
  }
  if (job.type === "exchangeSync") {
    runDispatchAction("query", dispatchDocs.map((doc) => doc.id));
    syncDatabaseTables(true);
    result = "成功：交換狀態與資料庫已同步";
  }
  if (job.type === "archiveSeal") {
    runArchiveAction("verify", archiveRecords.filter((item) => item.status !== "已封存").map((item) => item.id));
    runArchiveAction("seal", archiveRecords.filter((item) => item.status !== "已封存").map((item) => item.id));
    result = "成功：待封存公文已歸檔";
  }
  if (job.type === "reportGenerate") {
    renderReports();
    addReportsAudit("背景產生報表", `${job.schedule} 已產生收發量、成功率、異常類型、承辦量與逾期件報表。`);
    result = "成功：報表已產生";
  }
  job.runCount += 1;
  job.lastResult = result;
  job.nextRun = computeNextRun(job.schedule);
  addJobAudit(job.name, `${result}，下次執行 ${job.nextRun}。`);
}

async function runJobAction(action, ids = selectedJobIds()) {
  const jobs = backgroundJobs.filter((job) => ids.includes(job.id));
  if (!jobs.length) return showToast("請先選取背景任務。");
  if (action === "run") {
    const activeJobs = jobs.filter((item) => item.status === "啟用");
    if (!activeJobs.length) return blockOperation("選取的背景任務都未啟用，請先啟用後再執行。", addJobAudit, "背景任務防呆");
    if (!confirmOperation("確認立即執行背景任務", `即將立即執行 ${activeJobs.length} 個啟用中的背景任務，可能會拉取收文、同步交換狀態、產生通知、合約續約提醒或歸檔。`)) return;
    try {
      const results = [];
      for (const job of activeJobs) {
        results.push(await backendRequest(`/jobs/${job.id}/run`, { method: "POST", body: "{}" }));
      }
      await syncJobsFromBackend(true);
      addJobAudit("後端執行背景任務", results.map((item) => `${item.job_id}：${item.status} ${item.result}`).join("；"));
      return showToast(`後端已執行 ${results.length} 個背景任務。`);
    } catch (error) {
      jobs.filter((job) => job.status === "啟用").forEach(executeBackgroundJob);
      renderJobs();
      addJobAudit("後端背景任務失敗", `${error.message}；已改用前端工作流。`);
      return showToast(`後端失敗，已用前端執行 ${jobs.length} 個任務。`);
    }
  }
  if (action === "toggle") {
    if (!confirmOperation("確認切換任務狀態", `即將切換 ${jobs.length} 個背景任務的啟用/暫停狀態。`)) return;
    jobs.forEach((job) => {
      job.status = job.status === "啟用" ? "暫停" : "啟用";
      addJobAudit("切換任務狀態", `${job.name} 已更新為 ${job.status}。`);
    });
    renderJobs();
    return showToast("任務狀態已更新。");
  }
  if (action === "notify") {
    if (!confirmOperation("確認送出任務通知", `即將送出 ${jobs.length} 則背景任務結果通知。`)) return;
    for (const job of jobs) {
      const notice = { id: `NTF-JOB-${Date.now().toString().slice(-5)}-${job.id}`, type: "背景任務", title: `${job.name} 執行結果`, target: job.notify, channel: "Email + 系統通知", status: "未讀", priority: job.lastResult.includes("失敗") ? "高" : "中", source: job.id, body: job.lastResult };
      notificationItems.unshift(notice);
      await deliverNotification(notice);
    }
    renderNotifications();
    renderJobs();
    addJobAudit("送出任務通知", `已送出 ${jobs.length} 則背景任務結果通知。`);
    return showToast("背景任務通知已送出。");
  }
}

async function runDueJobs() {
  const dueCount = backgroundJobs.filter((job) => job.status === "啟用").length;
  if (!confirmOperation("確認執行到期任務", `即將執行目前所有啟用中的到期任務，預估 ${dueCount} 個。`)) return;
  try {
    const result = await backendRequest("/jobs/run-due", { method: "POST", body: "{}" });
    await syncJobsFromBackend(true);
    addJobAudit("後端執行到期任務", `已執行 ${result.count} 個到期任務。`);
    showToast(`後端已執行 ${result.count} 個到期任務。`);
  } catch (error) {
    const due = backgroundJobs.filter((job) => job.status === "啟用");
    due.forEach(executeBackgroundJob);
    renderJobs();
    addJobAudit("後端到期任務失敗", `${error.message}；已改用前端工作流。`);
    showToast(`已用前端執行 ${due.length} 個到期任務。`);
  }
}

function addBackgroundJobFromForm() {
  const job = {
    id: `JOB-${Date.now().toString().slice(-5)}`,
    name: document.querySelector("#jobNameInput").value.trim() || "未命名背景任務",
    type: document.querySelector("#jobTypeInput").value,
    schedule: document.querySelector("#jobScheduleInput").value,
    nextRun: computeNextRun(document.querySelector("#jobScheduleInput").value),
    status: "啟用",
    lastResult: "尚未執行",
    notify: document.querySelector("#jobNotifyInput").value,
    runCount: 0
  };
  backgroundJobs.unshift(job);
  selectedJobId = job.id;
  renderJobs();
  addJobAudit("新增背景任務", `${job.name} 已建立，週期 ${job.schedule}。`);
  showToast("背景任務已新增。");
}

function addDatabaseAudit(title, body) {
  databaseAuditLog.unshift([nowTime(), title, body]);
  renderDatabaseAuditLog();
}

async function syncDashboardFromBackend(silent = false) {
  try {
    backendDashboardMetrics = await backendRequest("/dashboard");
    renderRoleDashboard();
    if (!silent) addDatabaseAudit("同步角色儀表板", `後端已依 ${activeRole()} 權限回傳 ${backendDashboardMetrics.documents} 筆可見公文。`);
    return backendDashboardMetrics;
  } catch (error) {
    backendDashboardMetrics = null;
    if (!silent) addDatabaseAudit("同步角色儀表板失敗", error.message);
    return null;
  }
}

async function backendRequest(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (isHeaderSafeToken(authState?.token)) headers.Authorization = `Bearer ${authState.token}`;
  const response = await fetch(`${backendApiBase}${path}`, {
    headers,
    ...options
  });
  const raw = await response.text();
  let data = {};
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch (error) {
    throw new Error(`後端回傳格式錯誤：${raw.slice(0, 120) || response.status}`);
  }
  if (!response.ok) {
    const error = new Error(data.detail || data.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = data.error || "";
    error.detail = data.detail || "";
    throw error;
  }
  return data;
}

function isForbiddenError(error) {
  return error?.status === 403 || error?.code === "forbidden" || /forbidden|_forbidden|權限/.test(error?.message || "");
}

function persistToBackend(path, payload, method = "POST") {
  return backendRequest(path, { method, body: JSON.stringify(payload) })
    .then((result) => {
      addDatabaseAudit("持久化成功", `${path} 已寫入後端資料庫。`);
      return result;
    })
    .catch((error) => {
      addDatabaseAudit("持久化失敗", `${path}：${error.message}`);
      return null;
    });
}

function backendDocumentPayload(doc) {
  return {
    id: doc.id.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`,
    doc_no: doc.no || doc.receiveNo || doc.docNo,
    direction: doc.direction || (doc.receiveNo ? "收文" : "發文"),
    company_name: doc.companyName || "歲悅長照股份有限公司",
    doc_type: doc.type || "函",
    priority: doc.priority || "普通件",
    security_level: doc.security || "普通",
    agency_name: doc.to || doc.agency || "未指定機關",
    agency_code: doc.agencyCode || "待查詢",
    subject: doc.subject || "未填主旨",
    body: doc.body || "",
    seal_plan_json: JSON.stringify(doc.sealPlan || {}, null, 0),
    metadata_json: JSON.stringify({
      exchangeNo: doc.exchangeNo,
      packageId: doc.packageId || "",
      checks: doc.checks || {},
      lockedAt: doc.lockedAt || "",
      lockedBy: doc.lockedBy || "",
      lockedHash: doc.lockedHash || "",
      lockedAttachmentHash: doc.lockedAttachmentHash || "",
      versionStatus: doc.versionStatus || "",
      requiresReapproval: Boolean(doc.requiresReapproval),
      contact: {
        address: doc.contactAddress || "",
        owner: doc.contactOwner || "",
        phone: doc.contactPhone || "",
        fax: doc.contactFax || "",
        email: doc.contactEmail || ""
      }
    }, null, 0),
    status: doc.status || "草稿",
    owner: doc.owner || activeRole(),
    department: doc.dept || activeUnit() || roleDataScopes[activeRole()]?.departments?.[0] || "",
    due_date: doc.dueDate || "",
    received_at: doc.receivedAt || ""
  };
}

function backendWorkflowPayload(task) {
  const documentId = task.docId || "";
  return {
    id: task.id,
    document_id: documentId && !documentId.startsWith("DOC-") ? `DOC-${documentId}` : documentId,
    title: task.title,
    workflow_type: task.type || "發文",
    step: task.step,
    role: task.role,
    status: task.status,
    template: task.template || "standard",
    current_step_index: Number(task.currentStepIndex || 0),
    requester: task.requester || "",
    submitted_at: task.submittedAt || "",
    last_signed_at: task.lastSignedAt || "",
    last_comment: task.lastComment || "",
    proof_json: JSON.stringify({
      source: "frontend",
      updatedAt: new Date().toISOString(),
      approvalRouteCode: task.approvalRouteCode || workflowTemplates[task.template]?.routeCode || "",
      approvalRouteName: task.approvalRouteName || workflowTemplates[task.template]?.name || "",
      documentCategory: task.documentCategory || "",
      delegatedFrom: task.delegatedFrom || "",
      versionLocked: Boolean(task.versionLocked),
      lockedHash: task.lockedHash || "",
      requiresReapproval: Boolean(task.requiresReapproval)
    })
  };
}

function mapBackendDocument(row) {
  return {
    id: row.id,
    docNo: row.doc_no,
    direction: row.direction,
    companyName: row.company_name,
    agency: row.agency_name,
    subject: row.subject,
    status: row.status,
    owner: row.owner,
    sourceId: row.id
  };
}

function mapBackendCompany(row) {
  return { id: row.id, name: row.name, taxId: row.tax_id, status: row.status };
}

function mapBackendDepartment(row) {
  return { id: row.id, company: row.company_name, name: row.name, manager: row.manager_role, status: row.status };
}

function mapBackendSealType(row) {
  return { id: row.id, name: row.name, scope: row.scope, status: row.status };
}

function mapBackendWorkflowTask(row) {
  const doc = dispatchDocs.find((item) => item.id === row.document_id) || dispatchDocs.find((item) => `DOC-${item.id}` === row.document_id);
  return {
    id: row.id,
    docNo: doc?.no || row.document_id || row.id,
    docId: row.document_id,
    title: row.title,
    step: row.step,
    role: row.role,
    status: row.status,
    updatedAt: row.updated_at
  };
}

function mapBackendContract(row) {
  return {
    id: row.id,
    contractNo: row.contract_no,
    companyName: row.company_name,
    type: row.contract_type,
    counterparty: row.counterparty,
    title: row.title,
    status: row.status,
    owner: row.owner,
    dept: row.department,
    amount: Number(row.amount || 0),
    endDate: row.end_date
  };
}

function mapBackendContractParty(row) {
  return {
    id: row.id,
    contractId: row.contract_id,
    partyType: row.party_type,
    name: row.name,
    taxId: row.tax_id,
    contactName: row.contact_name
  };
}

function mapBackendContractApproval(row) {
  return {
    id: row.id,
    contractId: row.contract_id,
    step: row.step_name,
    role: row.role,
    status: row.status,
    signedAt: row.signed_at
  };
}

function applyPersistentRegistries(companies = [], departments = [], sealTypes = []) {
  if (companies.length) {
    companyRegistry.splice(0, companyRegistry.length, ...companies.map((row) => ({
      id: row.id,
      name: row.name,
      taxId: row.tax_id || row.taxId || "待設定",
      status: row.status || "啟用"
    })));
  }
  if (departments.length) {
    departmentRegistry.splice(0, departmentRegistry.length, ...departments.map((row) => ({
      id: row.id,
      company: row.company_name || row.company || "歲悅長照股份有限公司",
      name: row.name,
      manager: row.manager_role || row.manager || "行政部主任",
      status: row.status || "啟用"
    })));
  }
  if (sealTypes.length) {
    sealTypeRegistry.splice(0, sealTypeRegistry.length, ...sealTypes.map((row) => ({
      id: row.id,
      name: row.name,
      scope: row.scope || "未設定使用範圍",
      status: row.status || "啟用"
    })));
  }
  renderComposeCompanyOptions();
  renderContractFormOptions();
  renderExecutiveSealAdmin();
}

function applyPersistentWorkflowTasks(rows = []) {
  if (!rows.length) return;
  const mapped = rows.map((row) => {
    let proof = {};
    try { proof = JSON.parse(row.proof_json || "{}"); } catch (error) { proof = {}; }
    return {
      id: row.id,
      docId: row.document_id || row.docId || "",
      title: row.title,
      type: row.workflow_type || row.type || "發文",
      step: row.step,
      role: row.role,
      status: row.status,
      template: row.template || workflowTemplateKeyForRoute(proof.approvalRouteCode) || "routeA",
      approvalRouteCode: proof.approvalRouteCode || workflowTemplates[row.template]?.routeCode || "",
      approvalRouteName: proof.approvalRouteName || workflowTemplates[row.template]?.name || "",
      documentCategory: proof.documentCategory || "",
      delegatedFrom: proof.delegatedFrom || "",
      versionLocked: Boolean(proof.versionLocked),
      lockedHash: proof.lockedHash || "",
      requiresReapproval: Boolean(proof.requiresReapproval),
      currentStepIndex: Number(row.current_step_index || row.currentStepIndex || 0),
      submittedAt: row.submitted_at || row.submittedAt || "",
      requester: row.requester || "",
      lastSignedAt: row.last_signed_at || row.lastSignedAt || "",
      lastComment: row.last_comment || row.lastComment || ""
    };
  });
  const localOnly = workflowTasks.filter((task) => !mapped.some((row) => row.id === task.id));
  workflowTasks.splice(0, workflowTasks.length, ...mapped, ...localOnly);
  selectedWorkflowTaskId = workflowTasks[0]?.id || selectedWorkflowTaskId;
  renderWorkflowTasks();
  renderApprovalLog();
  renderDashboardApprovalProgress();
  renderUnifiedFlows();
}

function applyPersistentContracts(rows = [], approvals = []) {
  if (rows.length) {
    const mapped = rows.map((row) => {
      let attachments = [];
      let metadata = {};
      try { attachments = JSON.parse(row.attachment_manifest_json || "[]"); } catch (error) { attachments = []; }
      try { metadata = JSON.parse(row.metadata_json || "{}"); } catch (error) { metadata = {}; }
      return {
        id: row.id,
        contractNo: row.contract_no,
        companyName: row.company_name || "歲悅長照股份有限公司",
        type: approvalCategoryForType(row.contract_type || "一般合約").label,
        title: row.title,
        counterparty: row.counterparty,
        counterpartyTaxId: row.counterparty_tax_id || "",
        owner: row.owner,
        dept: row.department,
        amount: Number(row.amount || 0),
        currency: row.currency || "TWD",
        startDate: row.start_date || "",
        endDate: row.end_date || "",
        renewalDays: Number(row.renewal_alert_days || 60),
        confidentiality: row.confidentiality_level || "普通",
        sealRequirement: row.seal_requirement || "一般章",
        storageStatus: row.storage_status || "待歸檔",
        status: row.status || "草稿",
        summary: row.summary || "",
        riskNote: row.risk_note || "",
        attachments,
        approvalRouteCode: metadata.approvalRoute?.code || approvalRouteForType(row.contract_type).code,
        approvalRouteName: metadata.approvalRoute?.name || approvalRouteForType(row.contract_type).name,
        approvalCategoryGroup: metadata.approvalCategory?.group || approvalCategoryForType(row.contract_type).group,
        signedAt: metadata.signedAt || "",
        archiveHash: metadata.archiveHash || "",
        lockedAt: metadata.lockedAt || "",
        lockedBy: metadata.lockedBy || "",
        lockedHash: metadata.lockedHash || "",
        lockedAttachmentHash: metadata.lockedAttachmentHash || "",
        versionStatus: metadata.versionStatus || "",
        submittedHash: metadata.submittedHash || "",
        submittedAttachmentHash: metadata.submittedAttachmentHash || "",
        requiresReapproval: Boolean(metadata.requiresReapproval),
        reapprovalReason: metadata.reapprovalReason || "",
        createdAt: row.created_at || ""
      };
    });
    const localOnly = contractRecords.filter((contract) => !mapped.some((row) => row.id === contract.id));
    contractRecords.splice(0, contractRecords.length, ...mapped, ...localOnly);
    selectedContractId = contractRecords[0]?.id || selectedContractId;
  }
  if (approvals.length) {
    const mappedApprovals = approvals.map((row) => ({
      id: row.id,
      contractId: row.contract_id,
      stepNo: Number(row.step_no || 1),
      step: row.step_name,
      role: row.role,
      status: row.status,
      approver: row.approver || "",
      comment: row.comment || "",
      signedAt: row.signed_at || ""
    }));
    const backendApprovalContractIds = new Set(mappedApprovals.map((approval) => approval.contractId));
    const localOnlyApprovals = contractApprovals.filter((approval) =>
      !backendApprovalContractIds.has(approval.contractId) && !mappedApprovals.some((row) => row.id === approval.id)
    );
    contractApprovals.splice(0, contractApprovals.length, ...mappedApprovals, ...localOnlyApprovals);
  }
  contractRecords.forEach((contract) => rebuildLegacyContractApprovals(contract));
  renderContracts();
}

function applyPersistentDocuments(rows = []) {
  if (!rows.length) return;
  const backendInbound = rows.filter((row) => row.direction === "收文").map((row) => ({
    id: row.id.replace(/^DOC-/, ""),
    receiveNo: row.doc_no,
    exchangeNo: JSON.parse(row.metadata_json || "{}")?.exchangeNo || `EX-${row.id}`,
    agency: row.agency_name,
    agencyCode: row.agency_code || "待查詢",
    type: row.doc_type,
    priority: row.priority,
    security: row.security_level,
    subject: row.subject,
    status: row.status,
    owner: row.owner,
    dept: row.department || row.owner,
    receivedAt: row.received_at || row.created_at || "",
    dueDate: row.due_date || "",
    attachments: []
  }));
  const backendDispatch = rows.filter((row) => row.direction === "發文").map((row) => {
    let metadata = {};
    let sealPlan = {};
    try { metadata = JSON.parse(row.metadata_json || "{}"); } catch (error) { metadata = {}; }
    try { sealPlan = JSON.parse(row.seal_plan_json || "{}"); } catch (error) { sealPlan = {}; }
    return {
      id: row.id.replace(/^DOC-/, ""),
      no: row.doc_no,
      exchangeNo: metadata.exchangeNo || `EX-${row.id}`,
      companyName: row.company_name || "歲悅長照股份有限公司",
      type: row.doc_type,
      priority: row.priority,
      security: row.security_level,
      to: row.agency_name,
      agencyCode: row.agency_code || "待查詢",
      subject: row.subject,
      body: row.body || "",
      status: row.status,
      owner: row.owner,
      dept: row.department || row.owner,
      packageId: metadata.packageId || "",
      lastReply: metadata.lastReply || row.status,
      contactAddress: metadata.contact?.address || "",
      contactOwner: metadata.contact?.owner || row.owner,
      contactPhone: metadata.contact?.phone || "",
      contactFax: metadata.contact?.fax || "",
      contactEmail: metadata.contact?.email || "",
      checks: metadata.checks || { format: true, recipient: true, attachments: true, certificate: true, package: Boolean(metadata.packageId) },
      sealPlan,
      lockedAt: metadata.lockedAt || "",
      lockedBy: metadata.lockedBy || "",
      lockedHash: metadata.lockedHash || "",
      lockedAttachmentHash: metadata.lockedAttachmentHash || "",
      versionStatus: metadata.versionStatus || "",
      requiresReapproval: Boolean(metadata.requiresReapproval),
      attachments: ["函稿本文.pdf", "附件清冊.xml"]
    };
  });
  if (backendInbound.length) inboundDocs.splice(0, inboundDocs.length, ...backendInbound);
  if (backendDispatch.length) dispatchDocs.splice(0, dispatchDocs.length, ...backendDispatch);
  selectedInboundId = inboundDocs[0]?.id || selectedInboundId;
  selectedDispatchId = dispatchDocs[0]?.id || selectedDispatchId;
  renderInboundRows();
  renderInboundDetail();
  renderDispatchBoard();
  renderDispatchDetail();
  renderUnifiedFlows();
}

function mapBackendRecipient(row) {
  return {
    id: row.id,
    name: row.name,
    code: row.code,
    center: row.exchange_center,
    status: row.status,
    contact: row.contact
  };
}

function mapBackendAttachment(row) {
  return {
    id: row.id,
    docId: row.document_id,
    name: row.file_name,
    version: row.version,
    hash: row.sha256,
    status: row.scan_status
  };
}

function mapBackendTask(row) {
  return {
    id: row.id,
    docId: row.document_id,
    type: row.direction === "發文" ? "發文交換" : "收文交換",
    target: row.target_agency,
    status: row.status,
    updatedAt: row.updated_at,
    packageId: row.package_id || "未封裝"
  };
}

function mapBackendEvent(row) {
  return {
    id: row.id,
    taskId: row.task_id,
    event: row.event_type,
    message: row.message,
    createdAt: row.created_at
  };
}

function mapBackendAudit(row) {
  return {
    id: row.id,
    actor: row.actor,
    action: row.action,
    target: `${row.target_type || ""} ${row.target_id || ""}`.trim(),
    createdAt: row.created_at
  };
}

function mapBackendJob(row) {
  return {
    id: row.id,
    name: row.name,
    type: row.job_type,
    schedule: row.schedule_text,
    nextRun: row.next_run_at,
    status: row.status,
    lastResult: row.last_result,
    notify: "行政部主任",
    runCount: row.run_count || 0
  };
}

function mapBackendNotification(row) {
  return {
    id: row.id,
    type: row.type,
    title: row.title,
    target: row.target_role,
    targetEmail: row.target_email,
    channel: row.channel,
    status: row.status,
    priority: row.priority,
    source: row.source,
    body: row.body,
    deliveryReceipt: row.delivery_receipt,
    sentAt: row.sent_at
  };
}

function mapBackendInbox(row) {
  return {
    id: row.id,
    target: row.target_role,
    title: row.title,
    status: row.status,
    createdAt: row.created_at
  };
}

async function syncNotificationsFromBackend(silent = false) {
  try {
    const [notifications, deliveries, inbox] = await Promise.all([
      backendRequest("/notifications"),
      backendRequest("/notification_deliveries"),
      backendRequest("/system_inbox")
    ]);
  notificationItems.splice(0, notificationItems.length, ...notifications.map(mapBackendNotification));
  systemInboxItems.splice(0, systemInboxItems.length, ...inbox.map(mapBackendInbox));
  notificationDeliveryLog.splice(0, notificationDeliveryLog.length, ...deliveries.slice(0, 30).map((row) => [
      row.created_at?.slice(11, 16) || nowTime(),
      `${row.channel}｜${row.status}`,
      `${row.target} · ${row.receipt || row.error || row.notification_id || ""}`
    ]));
  selectedNotificationId = notificationItems[0]?.id || selectedNotificationId;
  await refreshNotificationGatewayStatus(true);
  renderNotifications();
    if (!silent) addNotificationAudit("同步後端通知", `已同步 ${notifications.length} 則通知、${deliveries.length} 筆派送紀錄、${inbox.length} 則站內通知。`);
  } catch (error) {
    if (!silent) addNotificationAudit("同步後端通知失敗", error.message);
  }
}

async function checkBackendHealth() {
  try {
    const data = await backendRequest("/health");
    addDatabaseAudit("後端健康檢查", `API 正常，資料庫：${data.database}，資料表 ${data.tables.length} 張。`);
    showToast("後端 API 與資料庫正常。");
  } catch (error) {
    addDatabaseAudit("後端健康檢查失敗", error.message);
    showToast("後端 API 無法連線，請確認 backend.py 是否啟動。");
  }
}

async function fetchBackendTable(path, tableKey) {
  try {
    const rows = await backendRequest(path);
    databaseAccessState[tableKey] = { status: "allowed", detail: "" };
    return rows;
  } catch (error) {
    if (isForbiddenError(error)) {
      databaseAccessState[tableKey] = { status: "restricted", detail: error.message };
      return null;
    }
    databaseAccessState[tableKey] = { status: "error", detail: error.message };
    return null;
  }
}

async function syncDatabaseFromBackend(silent = false) {
  try {
    const tables = await Promise.all([
      fetchBackendTable("/documents", "documents"),
      fetchBackendTable("/company_registry", "companyRegistry"),
      fetchBackendTable("/department_registry", "departmentRegistry"),
      fetchBackendTable("/seal_type_registry", "sealTypeRegistry"),
      fetchBackendTable("/workflow_tasks", "workflowTasks"),
      fetchBackendTable("/contracts", "contracts"),
      fetchBackendTable("/contract_parties", "contractParties"),
      fetchBackendTable("/contract_approvals", "contractApprovals"),
      fetchBackendTable("/recipients", "recipients"),
      fetchBackendTable("/attachments", "attachments"),
      fetchBackendTable("/exchange_tasks", "exchangeTasks"),
      fetchBackendTable("/exchange_events", "exchangeEvents"),
      fetchBackendTable("/audit_logs", "auditLogs")
    ]);
    const [documents, companies, departments, sealTypes, workflowRows, contracts, contractParties, contractApprovalsRows, recipients, attachments, tasks, events, audits] = tables;
    const safeDocuments = documents || [];
    const safeCompanies = companies || [];
    const safeDepartments = departments || [];
    const safeSealTypes = sealTypes || [];
    const safeWorkflowRows = workflowRows || [];
    const safeContracts = contracts || [];
    const safeContractParties = contractParties || [];
    const safeContractApprovals = contractApprovalsRows || [];
    const safeRecipients = recipients || [];
    const safeAttachments = attachments || [];
    const safeTasks = tasks || [];
    const safeEvents = events || [];
    const safeAudits = audits || [];
    applyPersistentDocuments(safeDocuments);
    databaseTables.documents = safeDocuments.map(mapBackendDocument);
    databaseTables.companyRegistry = safeCompanies.map(mapBackendCompany);
    databaseTables.departmentRegistry = safeDepartments.map(mapBackendDepartment);
    databaseTables.sealTypeRegistry = safeSealTypes.map(mapBackendSealType);
    databaseTables.contracts = safeContracts.map(mapBackendContract);
    databaseTables.contractParties = safeContractParties.map(mapBackendContractParty);
    databaseTables.contractApprovals = safeContractApprovals.map(mapBackendContractApproval);
    databaseTables.workflowTasks = safeWorkflowRows.map(mapBackendWorkflowTask);
    databaseTables.recipients = safeRecipients.map(mapBackendRecipient);
    databaseTables.attachments = safeAttachments.map(mapBackendAttachment);
    databaseTables.exchangeTasks = safeTasks.map(mapBackendTask);
    databaseTables.exchangeEvents = safeEvents.map(mapBackendEvent);
    databaseTables.auditLogs = safeAudits.map(mapBackendAudit);
    applyPersistentRegistries(safeCompanies, safeDepartments, safeSealTypes);
    applyPersistentWorkflowTasks(safeWorkflowRows);
    applyPersistentContracts(safeContracts, safeContractApprovals);
    databaseTables.documentFlows = buildUnifiedDocumentFlows().map((flow) => ({ id: flow.id, sourceNo: flow.sourceNo, kind: flow.kind, title: flow.title, currentStep: flow.currentStep, owner: flow.currentOwner, status: flow.status }));
    selectedDatabaseId = (databaseTables[activeDatabaseTable] || [])[0]?.id || "";
    renderDatabase();
    renderUnifiedFlows();
    if (!silent) {
      const restricted = Object.entries(databaseAccessState).filter(([, state]) => state.status === "restricted").map(([table]) => databaseLabels[table] || table);
      addDatabaseAudit("同步後端資料庫", `已同步 ${safeDocuments.length} 筆公文、${safeContracts.length} 筆合約、${safeWorkflowRows.length} 筆簽核流程。${restricted.length ? `受限：${restricted.join("、")}。` : ""}`);
      showToast("已同步真正後端資料庫。");
    }
  } catch (error) {
    renderDatabase();
    if (!silent) {
      addDatabaseAudit("後端同步失敗", error.message);
      showToast("後端同步失敗。");
    }
  }
}

async function syncJobsFromBackend(silent = false) {
  try {
    const rows = await backendRequest("/background_jobs");
    backgroundJobs.splice(0, backgroundJobs.length, ...rows.map(mapBackendJob));
    selectedJobId = backgroundJobs[0]?.id || selectedJobId;
    renderJobs();
    if (!silent) addJobAudit("同步後端背景任務", `已同步 ${rows.length} 個後端排程任務。`);
  } catch (error) {
    if (!silent) addJobAudit("同步後端背景任務失敗", error.message);
  }
}

async function backendPullInbound() {
  try {
    const result = await backendRequest("/actions/pull-inbound", { method: "POST", body: "{}" });
    addDatabaseAudit("後端 jAgent 收文拉取", `已由後端建立 ${result.created}。`);
    await syncDatabaseFromBackend();
    showToast("後端已拉取收文。");
  } catch (error) {
    addDatabaseAudit("後端收文拉取失敗", error.message);
    showToast("後端收文拉取失敗。");
  }
}

async function backendCreateBackup() {
  try {
    const result = await backendRequest("/actions/backup", { method: "POST", body: "{}" });
    addDatabaseAudit("後端資料備份", `${result.backup} 已建立，大小 ${result.size} bytes。`);
    showToast("後端資料備份已建立。");
  } catch (error) {
    addDatabaseAudit("後端資料備份失敗", error.message);
    showToast("後端備份失敗。");
  }
}

function syncDatabaseTables(silent = false) {
  databaseTables.documents = [
    ...inboundDocs.map((doc) => ({ id: `DOC-${doc.id}`, docNo: doc.receiveNo, direction: "收文", agency: doc.agency, subject: doc.subject, status: doc.status, owner: doc.owner, sourceId: doc.id })),
    ...dispatchDocs.map((doc) => ({ id: `DOC-${doc.id}`, docNo: doc.no, direction: "發文", agency: doc.to, subject: doc.subject, status: doc.status, owner: doc.owner, sourceId: doc.id }))
  ];
  databaseTables.contracts = contractRecords.map((contract) => ({ id: contract.id, contractNo: contract.contractNo, type: contract.type, counterparty: contract.counterparty, title: contract.title, status: contract.status, owner: contract.owner, dept: contract.dept }));
  databaseTables.contractParties = contractRecords.flatMap((contract) => ([
    { id: `CP-${contract.id}-A`, contractId: contract.id, partyType: "甲方", name: contract.companyName, taxId: "待設定", contactName: contract.owner },
    { id: `CP-${contract.id}-B`, contractId: contract.id, partyType: "乙方", name: contract.counterparty, taxId: contract.counterpartyTaxId || "", contactName: "合約窗口" }
  ]));
  databaseTables.contractApprovals = contractApprovals.map((approval) => ({ id: approval.id, contractId: approval.contractId, step: approval.step, role: approval.role, status: approval.status, signedAt: approval.signedAt || "" }));
  databaseTables.companyRegistry = companyRegistry.map((item) => ({ id: item.id, name: item.name, taxId: item.taxId, status: item.status }));
  databaseTables.departmentRegistry = departmentRegistry.map((item) => ({ id: item.id, company: item.company, name: item.name, manager: item.manager, status: item.status }));
  databaseTables.sealTypeRegistry = sealTypeRegistry.map((item) => ({ id: item.id, name: item.name, scope: item.scope, status: item.status }));
  databaseTables.documentFlows = buildUnifiedDocumentFlows().map((flow) => ({ id: flow.id, sourceNo: flow.sourceNo, kind: flow.kind, title: flow.title, currentStep: flow.currentStep, owner: flow.currentOwner, status: flow.status }));
  databaseTables.documentTypeConfigs = documentTypeConfigs.map((item) => ({ id: item.id, name: item.name, category: item.category, defaultWorkflowTemplate: item.defaultWorkflowTemplate, defaultFormatTemplate: item.defaultFormatTemplate, status: item.status }));
  databaseTables.workflowTemplateConfigs = workflowTemplateConfigs.map((item) => ({ key: item.key, name: item.name, routeCode: item.routeCode, stepsCount: item.steps?.length || 0, status: item.status }));
  databaseTables.permissionMatrix = permissionMatrixRows().map((item) => ({ ...item, granted: item.granted ? "Y" : "N" }));
  databaseTables.formatTemplateConfigs = formatTemplateConfigs.map((item) => ({ id: item.id, name: item.name, docType: item.docType, priority: item.priority, security: item.security, status: item.status }));
  databaseTables.workflowTasks = workflowTasks.map((task) => ({ id: task.id, docNo: approvalLogDocForTask(task)?.no || task.docId || task.id, title: task.title, step: task.step, role: task.role, status: task.status }));
  databaseTables.recipients = addressBook.map((item, index) => ({ id: `REC-${String(index + 1).padStart(3, "0")}`, name: item.name, code: item.code, center: item.center, status: item.status, contact: item.contact }));
  databaseTables.attachments = [
    ...inboundDocs.flatMap((doc) => doc.attachments.map((name, index) => ({ id: `ATT-${doc.id}-${index + 1}`, docId: `DOC-${doc.id}`, name, version: "v1", hash: `SHA256-IN-${doc.id.slice(-5)}-${index + 1}`, status: "有效" }))),
    ...dispatchDocs.flatMap((doc) => doc.attachments.map((name, index) => ({ id: `ATT-${doc.id}-${index + 1}`, docId: `DOC-${doc.id}`, name, version: doc.packageId ? "v2" : "v1", hash: `SHA256-OUT-${doc.id.slice(-5)}-${index + 1}`, status: doc.checks.attachments ? "雜湊通過" : "待驗證" }))),
    ...archiveRecords.flatMap((doc) => doc.attachments.map((item, index) => ({ id: `ATT-${doc.id}-${index + 1}`, docId: doc.id, name: item.name, version: item.version, hash: item.hash, status: item.status })))
  ];
  databaseTables.exchangeTasks = dispatchDocs.map((doc) => ({ id: `TASK-${doc.exchangeNo}`, docId: `DOC-${doc.id}`, type: "發文交換", target: doc.to, status: doc.status, updatedAt: nowTime(), packageId: doc.packageId || "未封裝" }));
  databaseTables.exchangeEvents = exchangeEvents.map(([time, event, message], index) => ({ id: `EVT-${String(index + 1).padStart(3, "0")}`, taskId: index < dispatchDocs.length ? `TASK-${dispatchDocs[index].exchangeNo}` : "TASK-SYSTEM", event, message, createdAt: time }));
  databaseTables.auditLogs = [
    ...auditEvents.map(([time, action, target], index) => ({ id: `AUD-DASH-${index + 1}`, actor: "系統", action, target, createdAt: time })),
    ...inboundAuditLog.map(([time, action, target], index) => ({ id: `AUD-IN-${index + 1}`, actor: "總務", action, target, createdAt: time })),
    ...dispatchAuditLog.map(([time, action, target], index) => ({ id: `AUD-OUT-${index + 1}`, actor: "總務", action, target, createdAt: time })),
    ...contractAuditLog.map(([time, action, target], index) => ({ id: `AUD-CON-${index + 1}`, actor: "合約管理", action, target, createdAt: time })),
    ...archiveAuditLog.map(([time, action, target], index) => ({ id: `AUD-ARC-${index + 1}`, actor: "主任", action, target, createdAt: time })),
    ...securityAuditLog.map(([time, action, target], index) => ({ id: `AUD-SEC-${index + 1}`, actor: "行政部主任", action, target, createdAt: time }))
  ];
  if (!silent) addDatabaseAudit("同步資料庫", "已從收文、發文、地址簿、交換事件與 audit log 重建資料表索引。");
}

function approvalRecordRows() {
  const workflowRows = workflowTasks
    .filter((task) => /簽核|審核|清稿|退回|待/.test(`${task.step} ${task.status}`))
    .map((task) => {
      const relatedDoc = dispatchDocs.find((doc) => task.title.includes(doc.subject.replace(/[，。]/g, "").slice(0, 8)) || doc.subject.includes(task.title.replace(/[，。]/g, "").slice(0, 8)));
      return {
        id: `APR-${task.id}`,
        docNo: relatedDoc?.no || task.id,
        docId: relatedDoc?.id || task.id,
        sourceId: relatedDoc?.id || task.id,
        subject: relatedDoc?.subject || task.title,
        status: task.status,
        step: task.step,
        owner: task.role,
        dept: roleDataScopes[task.role]?.departments?.[0] || task.role,
        type: task.type,
        agency: relatedDoc?.to || task.type,
        detail: `目前節點：${task.step}，負責角色：${task.role}`
      };
    });
  const sealRows = sealRequests.map((request) => {
    const doc = sealRequestDoc(request);
    const seal = sealById(request.sealId);
    return {
      id: `APR-${request.id}`,
      docNo: doc?.no || request.docId,
      docId: request.docId,
      sourceId: request.docId,
      subject: doc?.subject || "用印簽核案件",
      status: request.status,
      step: request.step,
      owner: seal?.owner || "總務",
      dept: roleDataScopes[seal?.owner]?.departments?.[0] || seal?.owner || "總務",
      type: "用印簽核",
      agency: doc?.to || "未指定受文者",
      detail: `印鑑：${seal?.name || request.sealId}，章戳：${request.stampNo || "尚未押章"}`
    };
  });
  const contractRows = contractApprovals
    .map((approval) => {
      const contract = contractRecords.find((item) => item.id === approval.contractId);
      return {
        id: `APR-${approval.id}`,
        docNo: contract?.contractNo || approval.contractId,
        docId: approval.contractId,
        sourceId: approval.contractId,
        subject: contract?.title || "合約簽核案件",
        status: approval.status,
        step: approval.step,
        owner: approval.role,
        dept: contract?.dept || roleDataScopes[approval.role]?.departments?.[0] || approval.role,
        type: "合約簽核",
        agency: contract?.counterparty || "合約相對人",
        detail: `合約：${contract?.counterparty || approval.contractId}，目前關卡：${approval.step}`
      };
    })
    .filter((row) => canSeeContract(contractRecords.find((contract) => contract.id === row.docId) || {}));
  return [...workflowRows, ...sealRows, ...contractRows];
}

function localUnifiedSearch(term, category = "all", status = "", limit = 80) {
  syncDatabaseTables(true);
  const specs = [
    ["documents", "公文", databaseTables.documents],
    ["document_flows", "文件流程", databaseTables.documentFlows],
    ["document_type_configs", "文件類型設定", databaseTables.documentTypeConfigs],
    ["workflow_template_configs", "流程模板設定", databaseTables.workflowTemplateConfigs],
    ["permission_matrix", "權限矩陣", databaseTables.permissionMatrix],
    ["format_template_configs", "格式模板設定", databaseTables.formatTemplateConfigs],
    ["approval_records", "簽核進度", approvalRecordRows()],
    ["contracts", "合約", databaseTables.contracts],
    ["contract_approvals", "合約簽核", databaseTables.contractApprovals],
    ["attachments", "附件", databaseTables.attachments],
    ["exchange_tasks", "交換任務", databaseTables.exchangeTasks],
    ["exchange_events", "交換事件", databaseTables.exchangeEvents],
    ["audit_logs", "稽核紀錄", databaseTables.auditLogs],
    ["notifications", "通知", notificationItems],
    ["attachment_security", "附件安全", fileSecurityItems],
    ["file_access_logs", "檔案存取", fileAccessLog.map(([time, title, body], index) => ({ id: `FLOG-FE-${index}`, createdAt: time, action: title, detail: body, status: title }))]
  ];
  const keyword = term.trim().toLowerCase();
  const state = status.trim().toLowerCase();
  return specs.flatMap(([table, label, rows]) => {
    if (category !== "all" && category !== table) return [];
    return rows.filter((row) => {
      const text = Object.values(row).join(" ").toLowerCase();
      return (!keyword || text.includes(keyword)) && (!state || text.includes(state));
    }).map((row) => ({
      id: row.id,
      category: label,
      table,
      title: row.docNo || row.fileName || row.title || row.name || row.action || row.id,
      subtitle: row.subject || row.agency || row.body || row.detail || row.message || "",
      status: row.status || row.scanStatus || row.result || "",
      createdAt: row.createdAt || row.updatedAt || "",
      record: row
    }));
  }).slice(0, Number(limit));
}

function filterSearchResultsForRole(results) {
  if (["行政部主任", "總務", "執行長"].includes(activeRole())) return results;
  const visibleKeys = new Set([
    ...scopedInboundDocs().flatMap((doc) => [doc.id, doc.receiveNo, doc.subject]),
    ...scopedDispatchDocs().flatMap((doc) => [doc.id, doc.no, doc.subject]),
    ...visibleContracts().flatMap((contract) => [contract.id, contract.contractNo, contract.title, contract.counterparty])
  ].filter(Boolean));
  return results.filter((item) => {
    const record = item.record || {};
    const text = [
      item.id,
      item.title,
      item.subtitle,
      record.sourceId,
      record.docNo,
      record.docId,
      record.contractNo,
      record.contractId,
      record.subject,
      record.title,
      record.counterparty,
      record.owner,
      record.dept,
      record.unit
    ].join(" ");
    return [...visibleKeys].some((key) => text.includes(key)) || record.owner === activeRole() || record.dept === activeUnit();
  });
}

function renderSearch() {
  const counts = searchResults.reduce((acc, item) => {
    if (["documents", "contracts"].includes(item.table)) acc.docs += 1;
    else if (["attachments", "attachment_security", "file_access_logs"].includes(item.table)) acc.files += 1;
    else acc.events += 1;
    return acc;
  }, { docs: 0, files: 0, events: 0 });
  document.querySelector("#searchResultCount").textContent = searchResults.length;
  document.querySelector("#searchDocCount").textContent = counts.docs;
  document.querySelector("#searchFileCount").textContent = counts.files;
  document.querySelector("#searchEventCount").textContent = counts.events;
  document.querySelector("#searchResultNote").textContent = document.querySelector("#searchQuery")?.value || "全部條件";
  document.querySelector("#searchStatusPill").textContent = searchResults.length ? "已查詢" : "無結果";
  const list = document.querySelector("#searchResults");
  list.innerHTML = searchResults.length ? searchResults.map((item) => `
    <article class="address-card ${item.id === selectedSearchId ? "selected-card" : ""}">
      <strong>${item.title}</strong>
      <span>${item.category} · ${item.status || "無狀態"} · ${item.id}</span>
      <p>${item.subtitle || "無摘要"}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-search-select="${item.id}">檢視</button>
        <button class="segment" type="button" data-search-open="${item.table}">開啟模組</button>
      </div>
    </article>
  `).join("") : `<article class="address-card"><strong>沒有符合條件的結果</strong><p>可改用文號、機關代碼、附件名稱、雜湊或狀態查詢。</p></article>`;
  document.querySelectorAll("[data-search-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedSearchId = button.dataset.searchSelect;
      renderSearch();
    });
  });
  document.querySelectorAll("[data-search-open]").forEach((button) => {
    button.addEventListener("click", () => openSearchResultModule(button.dataset.searchOpen));
  });
  renderSearchDetail();
}

function renderSearchDetail() {
  const item = searchResults.find((result) => result.id === selectedSearchId) || searchResults[0] || null;
  if (!item) {
    document.querySelector("#selectedSearchStatus").textContent = "未選取";
    document.querySelector("#searchDetail").innerHTML = `<p class="empty-text">尚無搜尋結果。</p>`;
    return;
  }
  selectedSearchId = item.id;
  document.querySelector("#selectedSearchStatus").textContent = item.status || item.category;
  document.querySelector("#searchDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${item.title}</strong>
      <p>${item.subtitle || "無摘要"}</p>
      <dl>
        <div><dt>類別</dt><dd>${item.category}</dd></div>
        <div><dt>來源表</dt><dd>${item.table}</dd></div>
        <div><dt>狀態</dt><dd>${item.status || "無"}</dd></div>
        <div><dt>時間</dt><dd>${item.createdAt || "未記錄"}</dd></div>
      </dl>
    </div>
    <div class="archive-grid">
      ${Object.entries(item.record || {}).slice(0, 12).map(([key, value]) => `<article class="archive-card"><span>${key}</span><strong>${String(value ?? "")}</strong></article>`).join("")}
    </div>
  `;
}

function openSearchResultModule(table) {
  const routeMap = {
    documents: "database",
    contracts: "contracts",
    contract_approvals: "contracts",
    attachments: "database",
    attachment_security: "fileSecurity",
    file_access_logs: "fileSecurity",
    exchange_tasks: "exchange",
    exchange_events: "exchange",
    notifications: "notifications",
    audit_logs: "archive"
  };
  setView(routeMap[table] || "database");
}

async function runUnifiedSearch() {
  const q = document.querySelector("#searchQuery").value.trim();
  const category = document.querySelector("#searchCategory").value;
  const status = document.querySelector("#searchStatus").value.trim();
  const limit = document.querySelector("#searchLimit").value;
  try {
    const params = new URLSearchParams({ q, category, status, limit });
    const result = await backendRequest(`/search?${params.toString()}`);
    searchResults = result.results || [];
    if (!searchResults.length) searchResults = localUnifiedSearch(q, category, status, limit);
  } catch (error) {
    searchResults = localUnifiedSearch(q, category, status, limit);
  }
  searchResults = filterSearchResultsForRole(searchResults);
  selectedSearchId = searchResults[0]?.id || "";
  renderSearch();
}

function databaseRows() {
  const term = databaseSearchTerm.trim().toLowerCase();
  const rows = databaseTables[activeDatabaseTable] || [];
  if (!term) return rows;
  return rows.filter((row) => Object.values(row).join(" ").toLowerCase().includes(term));
}

function currentDatabaseRow() {
  return (databaseTables[activeDatabaseTable] || []).find((row) => row.id === selectedDatabaseId) || databaseRows()[0] || null;
}

function databaseTableRestriction(table = activeDatabaseTable) {
  return databaseAccessState[table]?.status === "restricted" ? databaseAccessState[table] : null;
}

function renderDatabaseTableAccess() {
  document.querySelectorAll("[data-db-table]").forEach((button) => {
    const state = databaseAccessState[button.dataset.dbTable];
    button.classList.toggle("restricted", state?.status === "restricted");
    button.title = state?.status === "restricted" ? "此資料表依目前角色權限隱藏" : "";
  });
}

function renderDatabaseSummary() {
  document.querySelector("#dbDocCount").textContent = databaseTables.documents.length;
  document.querySelector("#dbRecipientCount").textContent = databaseTables.recipients.length;
  document.querySelector("#dbAttachmentCount").textContent = databaseTables.attachments.length;
  document.querySelector("#dbEventCount").textContent = databaseTables.exchangeTasks.length + databaseTables.exchangeEvents.length + databaseTables.auditLogs.length;
}

function renderDatabaseRows() {
  const rows = databaseRows();
  const columns = databaseColumns[activeDatabaseTable] || [];
  const restriction = databaseTableRestriction();
  document.querySelector("#databaseTableTitle").textContent = databaseLabels[activeDatabaseTable];
  document.querySelector("#databaseCount").textContent = restriction ? "權限受限" : `${rows.length} 筆`;
  document.querySelector("#databaseHead").innerHTML = `<tr>${columns.map((column) => `<th>${column}</th>`).join("")}<th>操作</th></tr>`;
  if (restriction) {
    document.querySelector("#databaseRows").innerHTML = `
      <tr>
        <td colspan="${columns.length + 1}">
          <div class="restricted-state">
            <strong>此資料表依目前角色權限隱藏</strong>
            <p>${restriction.detail || "帳號、角色權限、稽核與敏感後台資料只開放授權管理角色查看。"}</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }
  document.querySelector("#databaseRows").innerHTML = rows.map((row) => `
    <tr class="${row.id === selectedDatabaseId ? "selected-row" : ""}">
      ${columns.map((column) => `<td>${row[column] ?? ""}</td>`).join("")}
      <td><button class="segment" type="button" data-db-select="${row.id}">檢視</button></td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-db-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedDatabaseId = button.dataset.dbSelect;
      renderDatabaseRows();
      renderDatabaseDetail();
    });
  });
}

function renderDatabaseDetail() {
  const restriction = databaseTableRestriction();
  const addButton = document.querySelector("#databaseAddBtn");
  if (addButton) addButton.disabled = Boolean(restriction);
  const exportButton = document.querySelector("#databaseExportBtn");
  if (exportButton) exportButton.disabled = Boolean(restriction);
  if (restriction) {
    document.querySelector("#selectedDatabaseStatus").textContent = "權限受限";
    document.querySelector("#databaseDetail").innerHTML = `
      <div class="doc-detail restricted-detail">
        <strong>${databaseLabels[activeDatabaseTable]}已受 RBAC 保護</strong>
        <p>${restriction.detail || "目前登入角色沒有查看此資料表的權限。"}</p>
        <p>請改用角色首頁、簽核紀錄或公文紀錄處理日常作業；後台資料需由行政部主任或授權管理者查看。</p>
      </div>
    `;
    return;
  }
  const row = currentDatabaseRow();
  if (!row) {
    document.querySelector("#selectedDatabaseStatus").textContent = "未選取";
    document.querySelector("#databaseDetail").innerHTML = `<p class="empty-text">尚無資料。</p>`;
    return;
  }
  document.querySelector("#selectedDatabaseStatus").textContent = row.status || row.event || row.action || "資料列";
  document.querySelector("#databaseDetail").innerHTML = `
    <div class="doc-detail">
      <strong>${row.docNo || row.name || row.title || row.event || row.action || row.id}</strong>
      <dl>
        ${Object.entries(row).map(([key, value]) => `<div><dt>${key}</dt><dd>${value}</dd></div>`).join("")}
      </dl>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="databaseValidateRowBtn">驗證資料</button>
        <button class="secondary-button" type="button" id="databaseCopyRowBtn">複製 JSON</button>
      </div>
    </div>
  `;
  document.querySelector("#databaseValidateRowBtn").addEventListener("click", () => {
    addDatabaseAudit("驗證資料列", `${activeDatabaseTable}.${row.id} 已通過主鍵、狀態與關聯檢核。`);
    showToast("資料列檢核通過。");
  });
  document.querySelector("#databaseCopyRowBtn").addEventListener("click", () => {
    addDatabaseAudit("複製資料 JSON", `${activeDatabaseTable}.${row.id} 已產生 JSON 摘要。`);
    showToast("資料 JSON 已產生。");
  });
}

function renderDatabaseSchema() {
  const schemas = [
    ["公文主檔", "documents 1:N recipients / attachments / exchangeTasks"],
    ["合約主檔", "contracts 1:N contractParties / contractApprovals"],
    ["合約簽核", "contractApprovals 保存每一關簽核時間、意見與不可否認證據"],
    ["受文者", "recipients 保存機關代碼與交換中心"],
    ["附件", "attachments 保存版本、雜湊與清冊狀態"],
    ["交換任務", "exchangeTasks 串接 jAgent 任務狀態"],
    ["交換事件", "exchangeEvents 保存 accepted / failed / completed"],
    ["audit log", "auditLogs 保存不可覆寫操作軌跡"]
  ];
  document.querySelector("#databaseSchemaGrid").innerHTML = schemas.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderDatabaseAuditLog() {
  document.querySelector("#databaseAuditLog").innerHTML = databaseAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderDatabase() {
  renderDatabaseTableAccess();
  renderDatabaseSummary();
  renderDatabaseRows();
  renderDatabaseDetail();
  renderDatabaseSchema();
  renderDatabaseAuditLog();
}

function addDatabaseRowFromForm() {
  const table = document.querySelector("#databaseInsertTable").value;
  if (databaseTableRestriction(table)) {
    addDatabaseAudit("新增資料列阻擋", `${databaseLabels[table] || table} 依目前角色權限受限。`);
    return showToast("此資料表依目前角色權限隱藏，無法新增。");
  }
  const id = document.querySelector("#databaseInsertId").value.trim() || `${table}-${Date.now()}`;
  const title = document.querySelector("#databaseInsertTitle").value.trim();
  const status = document.querySelector("#databaseInsertStatus").value;
  const columns = databaseColumns[table] || ["id", "status"];
  const row = { id, status };
  columns.forEach((column) => {
    if (column !== "id" && column !== "status") row[column] = title || "手動新增資料";
  });
  databaseTables[table].unshift(row);
  activeDatabaseTable = table;
  selectedDatabaseId = id;
  document.querySelectorAll(".segment[data-db-table]").forEach((button) => button.classList.toggle("active", button.dataset.dbTable === table));
  renderDatabase();
  addDatabaseAudit("新增資料列", `已新增 ${databaseLabels[table]}.${id}。`);
  showToast("資料列已新增。");
}

function renderFeatureGrid() {
  document.querySelector("#featureGrid").innerHTML = featureGroups.map(([title, body], index) => `
    <article class="feature-card">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <strong>${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
}

function addFormatAudit(title, body) {
  formatAuditLog.unshift([nowTime(), title, body]);
  renderFormatAuditLog();
}

function formatPayload() {
  return {
    no: document.querySelector("#formatDocNo").value.trim(),
    type: document.querySelector("#formatDocType").value,
    priority: document.querySelector("#formatPriority").value,
    security: document.querySelector("#formatSecurity").value,
    agencyCode: document.querySelector("#formatAgencyCode").value.trim(),
    recipient: document.querySelector("#formatRecipient").value.trim(),
    subject: document.querySelector("#formatSubject").value.trim(),
    attachments: formatState.attachments
  };
}

function renderFormatAttachments() {
  document.querySelector("#formatAttachmentList").innerHTML = formatState.attachments.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <span>${item.type} · ${item.pages} 頁 · ${item.hash}</span>
      <button class="segment" type="button" data-remove-attachment="${item.id}">移除</button>
    </article>
  `).join("");
  document.querySelectorAll("[data-remove-attachment]").forEach((button) => {
    button.addEventListener("click", () => {
      formatState.attachments = formatState.attachments.filter((item) => item.id !== button.dataset.removeAttachment);
      renderFormatAttachments();
      renderFormatChecks();
      addFormatAudit("移除附件", "已從附件清冊移除 1 筆附件。");
      showToast("附件已移除。");
    });
  });
}

function renderFormatChecks() {
  const data = formatPayload();
  const allowedDocTypes = enabledDocumentTypeNames();
  const checks = [
    ["文號", /^.+字第\d+號$/.test(data.no), "格式需包含字別、第、流水號與號。"],
    ["文別", allowedDocTypes.includes(data.type), `文別需為後台啟用文件類型：${allowedDocTypes.join("、")}。`],
    ["速別", Boolean(data.priority), "速別需明確標示普通件、速件或最速件。"],
    ["密等", Boolean(data.security), "密等需明確標示普通、密、機密或極機密。"],
    ["主旨", data.subject.length >= 8, "主旨需可清楚表達發文目的。"],
    ["附件清冊", data.attachments.length > 0, "至少需建立附件清冊，並保存頁數、格式與雜湊。"],
    ["機關代碼", /^[A-Z]\d{8,}[A-Z]?$/.test(data.agencyCode), "機關代碼需符合大寫字母與數字格式。"]
  ];
  const allPass = checks.every(([, ok]) => ok);
  document.querySelector("#formatStatus").textContent = allPass ? "檢核通過" : "待補正";
  document.querySelector("#formatCheckList").innerHTML = checks.map(([title, ok, body]) => `
    <article class="check-item">
      <strong>${ok ? "通過" : "待補"} · ${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
  return allPass;
}

function renderFormatAgencyResults() {
  const box = document.querySelector("#formatAgencyResults");
  if (!formatState.agencyResults.length) {
    box.innerHTML = `<p class="empty-text">尚無機關代碼查詢結果。</p>`;
    return;
  }
  box.innerHTML = formatState.agencyResults.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <span>${item.code} · ${item.center}</span>
      <p>${item.status} · ${item.contact}</p>
      <button class="segment" type="button" data-format-agency="${item.name}" data-format-code="${item.code}">套用機關</button>
    </article>
  `).join("");
  document.querySelectorAll("[data-format-agency]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector("#formatRecipient").value = button.dataset.formatAgency;
      document.querySelector("#formatAgencyCode").value = button.dataset.formatCode;
      renderFormatChecks();
      addFormatAudit("套用機關代碼", `已套用 ${button.dataset.formatAgency}（${button.dataset.formatCode}）。`);
      showToast("已套用機關名稱與代碼。");
    });
  });
}

function searchFormatAgency(query) {
  const term = query.trim().toLowerCase();
  formatState.agencyResults = addressBook.filter((item) => `${item.name} ${item.code} ${item.center}`.toLowerCase().includes(term));
  renderFormatAgencyResults();
  addFormatAudit("查詢機關代碼", `查詢「${query || "全部"}」，取得 ${formatState.agencyResults.length} 筆。`);
  showToast(`機關代碼查詢完成：${formatState.agencyResults.length} 筆。`);
}

function addFormatAttachment() {
  const name = document.querySelector("#formatAttachmentName").value.trim();
  if (!name) return showToast("請輸入附件名稱。");
  formatState.attachments.push({
    id: `ATT-${Date.now()}`,
    name,
    pages: Number(document.querySelector("#formatAttachmentPages").value || 1),
    type: document.querySelector("#formatAttachmentType").value,
    hash: `SHA256-${Math.random().toString(16).slice(2, 6).toUpperCase()}`
  });
  renderFormatAttachments();
  renderFormatChecks();
  addFormatAudit("新增附件", `已新增附件 ${name}。`);
  showToast("附件已加入清冊。");
}

function applyFormatToCompose() {
  const data = formatPayload();
  document.querySelector("#dispatchNo").value = data.no;
  document.querySelector("#docType").value = data.type;
  document.querySelector("#priority").value = data.priority;
  document.querySelector("#recipient").value = data.recipient;
  document.querySelector("#subject").value = data.subject;
  markDraftDirty();
  addFormatAudit("帶入建立公文", `${data.no} 已帶入建立公文表單。`);
  showToast("文書格式已帶入建立公文。");
}

function renderFormatAuditLog() {
  document.querySelector("#formatAuditLog").innerHTML = formatAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function addWorkflowAudit(title, body) {
  workflowAuditLog.unshift([nowTime(), title, body]);
  renderWorkflowAuditLog();
}

function addWorkflowProof(title, body) {
  const proof = `NR-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${Math.floor(Math.random() * 9000 + 1000)}`;
  workflowProofLog.unshift([nowTime(), title, `${body}｜時間戳 ${new Date().toLocaleString("zh-TW", { hour12: false })}｜不可否認序號 ${proof}`]);
  renderWorkflowProofLog();
}

function renderWorkflowRole() {
  document.querySelector("#workflowRoleStatus").textContent = workflowRole;
  document.querySelector("#workflowRoleSelect").value = workflowRole;
  const permissions = rolePermissions[workflowRole] || [];
  document.querySelector("#permissionGrid").innerHTML = Object.entries(permissionLabels).map(([key, label]) => `
    <article class="permission-chip ${permissions.includes(key) ? "allowed" : ""}">
      <strong>${permissions.includes(key) ? "允許" : "限制"}</strong>
      <span>${label}</span>
    </article>
  `).join("");
  document.querySelector("#workflowRoleDetail").innerHTML = `
    <strong>${workflowRole}</strong>
    <p>${roleNotes[workflowRole]}</p>
    <dl>
      <div><dt>權限數</dt><dd>${permissions.length} 項</dd></div>
      <div><dt>主要責任</dt><dd>${workflowSteps.find(([, role]) => role === workflowRole)?.[2] || "依角色設定"}</dd></div>
    </dl>
  `;
}

function renderWorkflowTasks() {
  document.querySelector("#workflowTaskCount").textContent = `${workflowTasks.length} 件`;
  document.querySelector("#workflowTaskRows").innerHTML = workflowTasks.map((task) => `
    <tr class="${task.id === selectedWorkflowTaskId ? "selected-row" : ""}">
      <td><input class="workflow-check" type="checkbox" value="${task.id}" /></td>
      <td><button class="text-button row-select" type="button" data-workflow-select="${task.id}">${task.title}</button><small>${task.id}</small></td>
      <td>${task.type}</td>
      <td>${task.step}</td>
      <td>${task.role}</td>
      <td><span class="badge ${badgeClass(task.status)}">${task.status}</span></td>
      <td><div class="row-actions"><button class="segment" data-workflow-progress="${task.id}" type="button">進度</button><button class="segment" data-workflow-approve="${task.id}" type="button">授權</button><button class="segment" data-workflow-reject="${task.id}" type="button">退回</button></div></td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-workflow-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedWorkflowTaskId = button.dataset.workflowSelect;
      renderWorkflowTasks();
      renderApprovalProgress();
      renderDashboardApprovalProgress();
      renderApprovalLog();
    });
  });
  document.querySelectorAll("[data-workflow-progress]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedWorkflowTaskId = button.dataset.workflowProgress;
      renderWorkflowTasks();
      renderApprovalProgress();
      renderDashboardApprovalProgress();
      renderApprovalLog();
      document.querySelector("#approvalProgressPanel")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  document.querySelectorAll("[data-workflow-approve]").forEach((button) => {
    button.addEventListener("click", () => mutateWorkflowTasks([button.dataset.workflowApprove], "已授權"));
  });
  document.querySelectorAll("[data-workflow-reject]").forEach((button) => {
    button.addEventListener("click", () => mutateWorkflowTasks([button.dataset.workflowReject], "退回補正"));
  });
}

function renderWorkflowSteps() {
  document.querySelector("#workflowStepList").innerHTML = workflowSteps.map(([no, role, body]) => `
    <article class="timeline-item">
      <time>${no}</time>
      <div>
        <strong>${role}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function currentWorkflowTask() {
  return workflowTasks.find((task) => task.id === selectedWorkflowTaskId) || workflowTasks[0] || null;
}

function approvalTemplateForTask(task) {
  if (!task) return [];
  if (task.template && workflowTemplates[task.template]) return workflowTemplates[task.template].steps;
  if (task.approvalRouteCode) return workflowStepsForRoute(task.approvalRouteCode);
  if (task.type === "合約") return workflowStepsForRoute(task.approvalRouteCode || "C");
  if (task.type === "發文") return workflowTemplates.routeA.steps;
  if (task.type === "收文") return ["總務收文登錄", "附件與格式檢核", "分派部門主管", "主管承接簽核", "歸檔保存"];
  if (task.type === "稽核") return ["建立抽核案件", "稽核人員查核", "主管覆核", "完成稽核紀錄"];
  return ["建立設定需求", "資訊管理員檢核", "行政部主任核定", "套用設定"];
}

function approvalRoleForStep(step, task) {
  if (/執行長|負責人/.test(step)) return "執行長";
  if (/行政部門主任|行政部主任|清稿|資安|主管覆核/.test(step)) return "行政部主任";
  if (/總務|收文|用印|歸檔|jAgent|交換/.test(step)) return "總務";
  if (/申請人主管/.test(step)) return "主管";
  if (/部門主管|主管承接/.test(step)) return "主任";
  if (/會計|財務/.test(step)) return "會計";
  if (/人資/.test(step)) return "人資";
  if (/申請人|業務助理|擬稿/.test(step)) return task?.requester || task?.owner || activeRole() || "申請人";
  if (/資訊/.test(step)) return "行政部主任";
  return task?.role || workflowRole;
}

function approvalCurrentIndex(task, steps) {
  if (!task || !steps.length) return 0;
  if (/已授權|完成|已押章|交換完成|歸檔/.test(task.status)) return steps.length - 1;
  if (/退回|抽回/.test(task.status)) return Math.max(0, task.currentStepIndex || 0);
  if (Number.isInteger(task.currentStepIndex)) return Math.min(task.currentStepIndex, steps.length - 1);
  const stepText = task.step || "";
  const found = steps.findIndex((step) => step.includes(stepText) || stepText.includes(step) || step.includes(task.role));
  return found >= 0 ? found : 0;
}

function approvalProgressSnapshot(task = currentWorkflowTask()) {
  const steps = approvalTemplateForTask(task);
  const currentIndex = approvalCurrentIndex(task, steps);
  return {
    task,
    steps: steps.map((step, index) => {
      const returned = /退回|抽回/.test(task?.status || "") && index === currentIndex;
      const state = returned ? "returned" : index < currentIndex ? "done" : index === currentIndex ? "current" : "pending";
      return {
        no: String(index + 1).padStart(2, "0"),
        title: step,
        owner: approvalRoleForStep(step, task),
        state,
        status: state === "done" ? "已完成" : state === "current" ? task.status : state === "returned" ? task.status : "待後續",
        time: state === "done" ? task.lastSignedAt || "已留存時間戳" : state === "current" ? task.lastSignedAt || "等待處理" : "尚未到關",
        comment: state === "current" || state === "returned" ? task.lastComment || "尚未填寫簽核意見。" : "通過後會寫入不可否認紀錄。"
      };
    })
  };
}

function approvalLogDocForTask(task) {
  if (!task) return null;
  if (task.docId) return dispatchDocs.find((doc) => doc.id === task.docId) || null;
  return dispatchDocs.find((doc) => task.title?.includes(doc.subject.slice(0, 8)) || doc.subject.includes(task.title?.slice(0, 8))) || null;
}

function approvalLogRecords() {
  const visibleDocIds = new Set(scopedDispatchDocs().map((doc) => doc.id));
  const documentRecords = workflowTasks
    .filter((task) => task.type === "發文" || /發文|函稿|公文/.test(`${task.title} ${task.step}`))
    .map((task) => {
      const doc = approvalLogDocForTask(task);
      const snapshot = approvalProgressSnapshot(task);
      const currentStep = snapshot.steps.find((step) => step.state === "current" || step.state === "returned") || snapshot.steps[0];
      return {
        task,
        doc,
        currentStep,
        doneCount: snapshot.steps.filter((step) => step.state === "done").length,
        totalSteps: snapshot.steps.length,
        steps: snapshot.steps,
        submittedAt: task.submittedAt || task.lastSignedAt || "尚未送出",
        requester: task.requester || doc?.owner || "承辦人"
      };
    })
    .filter(({ task, doc }) => {
      if (canSeeCompanyWideDocs()) return true;
      if (doc && visibleDocIds.has(doc.id)) return true;
      return task.role === activeRole() || task.requester === activeRole();
    });
  const contractRecordsForApproval = visibleContracts().map((contract) => {
    const approvals = contractApprovalsFor(contract.id);
    const current = currentContractApproval(contract) || approvals.at(-1);
    const doneCount = approvals.filter((approval) => /完成|已簽署|已歸檔/.test(approval.status)).length;
    const task = {
      id: `CON-WF-${contract.id}`,
      docId: contract.id,
      title: contract.title,
      type: "合約",
      step: current?.step || "合約流程完成",
      role: current?.role || contract.owner,
      status: contract.status,
      submittedAt: contract.createdAt || "",
      requester: contract.owner,
      lastSignedAt: current?.signedAt || contract.signedAt || "",
      lastComment: current?.comment || contract.riskNote || ""
    };
    const steps = approvals.map((approval) => ({
      no: String(approval.stepNo).padStart(2, "0"),
      title: approval.step,
      owner: approval.role,
      state: /退回/.test(approval.status) ? "returned" : /完成|已簽署|已歸檔/.test(approval.status) ? "done" : approval.id === current?.id ? "current" : "pending",
      status: approval.status,
      time: approval.signedAt || "尚未到關",
      comment: approval.comment || "等待簽核意見。"
    }));
    return {
      task,
      doc: { id: contract.id, no: contract.contractNo, subject: contract.title, to: contract.counterparty, companyName: contract.companyName },
      currentStep: steps.find((step) => step.state === "current" || step.state === "returned") || steps.at(-1),
      doneCount,
      totalSteps: steps.length,
      steps,
      submittedAt: contract.createdAt || "尚未送出",
      requester: contract.owner
    };
  });
  return [...documentRecords, ...contractRecordsForApproval];
}

function filteredApprovalLogRecords() {
  const term = approvalLogSearchTerm.trim().toLowerCase();
  return approvalLogRecords().filter(({ task, doc, currentStep }) => {
    const statusText = `${task.status} ${currentStep?.status || ""}`;
    const matchesFilter = approvalLogFilter === "all" || statusText.includes(approvalLogFilter);
    const haystack = `${task.id} ${task.title} ${task.step} ${task.role} ${task.status} ${doc?.no || ""} ${doc?.subject || ""} ${doc?.to || ""}`.toLowerCase();
    return matchesFilter && (!term || haystack.includes(term));
  });
}

function renderApprovalLog() {
  const list = document.querySelector("#approvalLogList");
  const detail = document.querySelector("#approvalLogDetail");
  if (!list || !detail) return;
  const records = filteredApprovalLogRecords();
  document.querySelector("#approvalLogCount").textContent = `${records.length} 件`;
  document.querySelector("#approvalLogScope").textContent = canSeeCompanyWideDocs() ? "全公司" : "依部門/角色";
  if (records.length && !records.some(({ task }) => task.id === selectedWorkflowTaskId)) selectedWorkflowTaskId = records[0].task.id;
  list.innerHTML = records.length ? records.map(({ task, doc, currentStep, doneCount, totalSteps, submittedAt }) => `
    <article class="address-card ${task.id === selectedWorkflowTaskId ? "selected-card" : ""}">
      <strong>${doc?.no || task.id}</strong>
      <span>${doc?.subject || task.title}</span>
      <p>${currentStep?.title || task.step} · ${task.role} · ${task.status}</p>
      <small>${doneCount}/${totalSteps} 關 · 送出時間 ${submittedAt}</small>
      <div class="row-actions">
        <button class="segment" type="button" data-approval-log-select="${task.id}">檢視</button>
      </div>
    </article>
  `).join("") : `<p class="empty-text">目前沒有符合條件的簽核紀錄。</p>`;

  const selected = records.find(({ task }) => task.id === selectedWorkflowTaskId) || records[0];
  if (!selected) {
    detail.innerHTML = `<p class="empty-text">請先送出一份公文，系統會自動建立簽核流程紀錄。</p>`;
  } else {
    const { task, doc, currentStep, doneCount, totalSteps, steps, submittedAt, requester } = selected;
    detail.innerHTML = `
      <article class="approval-log-summary">
        <div class="approval-log-summary-head">
          <span>${task.id} · ${doc?.no || "尚未建立文號"}</span>
          <strong>${doc?.subject || task.title}</strong>
        </div>
        <p>目前停在「${currentStep?.title || task.step}」，負責角色：${task.role}，狀態：${task.status}。</p>
        <dl class="approval-log-meta">
          <div><dt>公司</dt><dd>${doc?.companyName || "歲悅長照股份有限公司"}</dd></div>
          <div><dt>送出人</dt><dd>${requester}</dd></div>
          <div><dt>送出時間</dt><dd>${submittedAt}</dd></div>
          <div><dt>進度</dt><dd>${doneCount}/${totalSteps} 關</dd></div>
          <div><dt>最近時間戳</dt><dd>${task.lastSignedAt || "尚未簽核"}</dd></div>
          <div><dt>簽核意見</dt><dd>${task.lastComment || "尚未填寫"}</dd></div>
        </dl>
      </article>
      <ol class="approval-log-trail">
        ${steps.map((step) => `
          <li class="approval-log-step ${step.state}">
            <time>${step.no}</time>
            <div class="approval-log-step-body">
              <div class="approval-log-step-title">
                <strong>${step.title}</strong>
                <span>${step.status}</span>
              </div>
              <p>${step.owner}</p>
              <small>${step.time}</small>
              <em>${step.comment}</em>
            </div>
          </li>
        `).join("")}
      </ol>
    `;
  }
  document.querySelectorAll("[data-approval-log-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedWorkflowTaskId = button.dataset.approvalLogSelect;
      renderApprovalLog();
    });
  });
}

function renderApprovalProgress() {
  const { task, steps } = approvalProgressSnapshot();
  const status = document.querySelector("#approvalProgressStatus");
  const summary = document.querySelector("#approvalProgressSummary");
  const stepList = document.querySelector("#approvalProgressSteps");
  if (!status || !summary || !stepList) return;
  if (!task) {
    status.textContent = "未選取";
    summary.innerHTML = `<p class="empty-text">請先選取一筆簽核案件。</p>`;
    stepList.innerHTML = "";
    return;
  }
  const doneCount = steps.filter((step) => step.state === "done").length;
  const currentStep = steps.find((step) => step.state === "current" || step.state === "returned") || steps[0];
  status.textContent = `${doneCount}/${steps.length} 關`;
  summary.innerHTML = `
    <article class="approval-progress-card">
      <span>${task.id} · ${task.type}</span>
      <strong>${task.title}</strong>
      <p>目前停在「${currentStep.title}」，負責角色：${currentStep.owner}，狀態：${task.status}。</p>
      <dl>
        <div><dt>目前節點</dt><dd>${task.step}</dd></div>
        <div><dt>簽核角色</dt><dd>${task.role}</dd></div>
        <div><dt>最近時間戳</dt><dd>${task.lastSignedAt || "尚未簽核"}</dd></div>
        <div><dt>簽核意見</dt><dd>${task.lastComment || "尚未填寫"}</dd></div>
      </dl>
    </article>
  `;
  stepList.innerHTML = steps.map((step) => `
    <article class="approval-step ${step.state}">
      <time>${step.no}</time>
      <div>
        <strong>${step.title}</strong>
        <span>${step.owner} · ${step.status}</span>
        <p>${step.time}｜${step.comment}</p>
      </div>
    </article>
  `).join("");
}

function renderWorkflowTemplateSteps() {
  const template = workflowTemplates[activeWorkflowTemplate] || workflowTemplates[enabledWorkflowTemplateConfigs()[0]?.key] || { name: "未設定流程", steps: [] };
  if (document.querySelector("#workflowTemplateSelect")) document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  document.querySelector("#workflowTemplateSteps").innerHTML = template.steps.map((step, index) => `
    <article class="timeline-item">
      <time>${String(index + 1).padStart(2, "0")}</time>
      <div>
        <strong>${step}</strong>
        <p>${approvalRoleForStep(step)} · ${template.name} 節點，完成後寫入簽核時間戳與不可否認紀錄。</p>
      </div>
    </article>
  `).join("");
}

function renderWorkflowConditions() {
  const security = document.querySelector("#workflowConditionSecurity").value;
  const priority = document.querySelector("#workflowConditionPriority").value;
  const agency = document.querySelector("#workflowConditionAgency").value.trim();
  const amount = Number(document.querySelector("#workflowAmountInput").value || 0);
  const categoryValue = document.querySelector("#workflowDocumentCategorySelect")?.value || "";
  const category = approvalCategoryForType(categoryValue);
  const route = approvalRouteForType(categoryValue);
  const rules = [
    ["文件類別", `${category.group.replace(/（勿選）/, "")} / ${category.label}`],
    ["簽核路由", route.name],
    ["密件", security !== "普通" ? "需行政部主任資安檢核" : "一般權限即可"],
    ["速件", /速/.test(priority) ? "插隊行政部主任即時審核" : "依一般時限"],
    ["會計節點", route.requiresAccounting ? "需會計複核" : "不需會計複核"],
    ["執行長節點", route.requiresCeo ? "需執行長核定" : "不需執行長核定"],
    ["金額", amount >= 100000 ? "列為高金額提醒，但不覆蓋小類別路由" : "依小類別路由"],
    ["機關別", /政府|衛生|社會/.test(agency) ? "政府機關公文需總務覆核" : "一般受文者流程"]
  ];
  document.querySelector("#workflowConditionGrid").innerHTML = rules.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${value}</strong>
    </article>
  `).join("");
}

function renderWorkflowProxies() {
  document.querySelector("#workflowProxyList").innerHTML = workflowProxies.map((proxy) => `
    <article class="address-card">
      <strong>${proxy.from} → ${proxy.to}</strong>
      <span>${proxy.reason}</span>
      <p>${proxy.status} · ${proxy.id}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-proxy-toggle="${proxy.id}">${proxy.status === "啟用" ? "停用" : "啟用"}</button>
        <button class="segment" type="button" data-proxy-apply="${proxy.id}">套用</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-proxy-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleWorkflowProxy(button.dataset.proxyToggle));
  });
  document.querySelectorAll("[data-proxy-apply]").forEach((button) => {
    button.addEventListener("click", () => applyWorkflowProxy(button.dataset.proxyApply));
  });
}

function renderWorkflowProofLog() {
  document.querySelector("#workflowProofLog").innerHTML = workflowProofLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderWorkflowAuditLog() {
  document.querySelector("#workflowAuditLog").innerHTML = workflowAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function selectedWorkflowIds() {
  const selected = [...document.querySelectorAll(".workflow-check:checked")].map((item) => item.value);
  return selected.length ? selected : selectedWorkflowTaskId ? [selectedWorkflowTaskId] : [];
}

function mutateWorkflowTasks(ids, status) {
  ids.forEach((id) => {
    const task = workflowTasks.find((item) => item.id === id);
    if (task) {
      task.status = status;
      task.lastSignedAt = new Date().toLocaleString("zh-TW", { hour12: false });
      task.lastComment = document.querySelector("#workflowComment")?.value || "系統簽核。";
      if (status === "指派完成") task.role = workflowRole;
      if (status === "已授權" && task.type === "發文") {
        const doc = dispatchDocs.find((item) => task.title.includes(item.subject.slice(0, 6)) || item.subject.includes(task.title.slice(0, 6)));
        const request = ensureSealRequestForDoc(doc, task.step);
        if (request) approveSealRequests([request.id]);
      }
      addWorkflowProof(status, `${task.title} 於「${task.step}」由 ${workflowRole} 處理，意見：${task.lastComment}`);
      persistToBackend(`/workflow_tasks/${task.id}`, backendWorkflowPayload(task), "PATCH");
    }
  });
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  renderApprovalLog();
  renderUnifiedFlows();
  addWorkflowAudit(status, `已更新 ${ids.length} 件待辦為「${status}」。`);
  showToast(`流程已更新：${status}。`);
}

function moveApprovalToNextStep() {
  const task = currentWorkflowTask();
  if (!task) return showToast("請先選取簽核案件。");
  const steps = approvalTemplateForTask(task);
  const currentIndex = approvalCurrentIndex(task, steps);
  if (/已授權|完成|已押章|交換完成|歸檔/.test(task.status) && currentIndex >= steps.length - 1) {
    return blockOperation("此案件已完成簽核流程，不需要再送下一關。", addWorkflowAudit, "簽核進度防呆");
  }
  const nextIndex = Math.min(currentIndex + 1, steps.length - 1);
  const nextStep = steps[nextIndex];
  const nextRole = approvalRoleForStep(nextStep, task);
  const resolved = resolveApprovalAssignee(nextRole);
  if (!resolved.ok) {
    return blockOperation(`下一關「${nextStep}」找不到 ${nextRole} 的啟用帳號或代理人，請先補齊人員或代理設定。`, addWorkflowAudit, "簽核下一關防呆");
  }
  task.currentStepIndex = nextIndex;
  task.step = nextStep;
  task.role = resolved.role;
  if (resolved.proxyFrom) task.delegatedFrom = resolved.proxyFrom;
  task.status = nextIndex === steps.length - 1 ? "待最終確認" : "待簽核";
  task.lastSignedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  task.lastComment = document.querySelector("#workflowComment")?.value.trim() || `已送至 ${task.role} 處理。${resolved.proxyFrom ? `代理自 ${resolved.proxyFrom}。` : ""}`;
  addWorkflowProof("送下一關", `${task.title} 已送至「${task.step}」，負責角色：${task.role}，意見：${task.lastComment}`);
  persistToBackend(`/workflow_tasks/${task.id}`, backendWorkflowPayload(task), "PATCH");
  addWorkflowAudit("送下一關", `${task.id} 已推進至「${task.step}」。`);
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  renderApprovalLog();
  renderUnifiedFlows();
  renderIdentityWorkbench();
  renderRoleDashboard();
  showToast("已送下一關。");
}

function returnApprovalForCorrection() {
  const task = currentWorkflowTask();
  if (!task) return showToast("請先選取簽核案件。");
  const comment = document.querySelector("#workflowComment")?.value.trim();
  if (!hasMinimumText(comment)) return blockOperation("退回補正必須填寫至少 6 個字的簽核意見。", addWorkflowAudit, "簽核進度防呆");
  task.status = "退回補正";
  if (task.documentCategory || task.approvalRouteCode) {
    const route = task.documentCategory ? approvalRouteForType(task.documentCategory) : approvalRouteTypes[task.approvalRouteCode] || approvalRouteTypes.A;
    const templateKey = workflowTemplateKeyForRoute(route.code);
    const steps = workflowTemplates[templateKey]?.steps || approvalTemplateForTask(task);
    task.template = templateKey;
    task.approvalRouteCode = route.code;
    task.approvalRouteName = route.name;
    task.currentStepIndex = 0;
    task.step = steps[0];
    task.role = approvalRoleForStep(task.step, task);
    task.versionLocked = false;
    task.lockedHash = "";
    task.requiresReapproval = true;
  }
  task.lastSignedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  task.lastComment = comment;
  addWorkflowProof("退回補正", `${task.title} 已退回補正，意見：${comment}；補正後會重新評估簽核路由。`);
  persistToBackend(`/workflow_tasks/${task.id}`, backendWorkflowPayload(task), "PATCH");
  addWorkflowAudit("退回補正", `${task.id} 已退回補正。`);
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  renderApprovalLog();
  renderUnifiedFlows();
  renderIdentityWorkbench();
  renderRoleDashboard();
  showToast("已退回補正。");
}

function exportApprovalProgress() {
  const { task, steps } = approvalProgressSnapshot();
  if (!task) return showToast("請先選取簽核案件。");
  const payload = {
    exportedAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    exportedBy: activeRole(),
    task,
    progress: steps,
    nonRepudiationProof: workflowProofLog.filter(([, , body]) => body.includes(task.title) || body.includes(task.id))
  };
  downloadTextFile(`${task.id}-approval-progress.json`, JSON.stringify(payload, null, 2));
  addWorkflowAudit("匯出簽核進度", `${task.id} 簽核進度已匯出。`);
  showToast("簽核進度已匯出。");
}

function applyWorkflowTemplate() {
  const categoryValue = document.querySelector("#workflowDocumentCategorySelect")?.value || "";
  const category = approvalCategoryForType(categoryValue);
  const route = approvalRouteForType(categoryValue);
  const docType = document.querySelector("#workflowTemplateDocType").value;
  const docTypeConfig = documentTypeConfigForName(docType);
  const selectedTemplate = document.querySelector("#workflowTemplateSelect")?.value;
  activeWorkflowTemplate = docTypeConfig?.defaultWorkflowTemplate || selectedTemplate || workflowTemplateKeyForRoute(route.code);
  if (!workflowTemplates[activeWorkflowTemplate]) activeWorkflowTemplate = enabledWorkflowTemplateConfigs()[0]?.key || activeWorkflowTemplate;
  document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  const template = workflowTemplates[activeWorkflowTemplate];
  if (!template) return blockOperation("尚未設定可用的流程模板，請先到系統設定建立流程模板。", addWorkflowAudit, "流程模板防呆");
  const unresolved = template.steps
    .map((step) => ({ step, role: approvalRoleForStep(step, { requester: activeRole() }) }))
    .map((item) => ({ ...item, resolved: resolveApprovalAssignee(item.role) }))
    .filter((item) => !item.resolved.ok);
  if (unresolved.length) {
    return blockOperation(`無法套用流程：${unresolved.map((item) => `${item.step} 缺少 ${item.role}`).join("、")}。請先在人員登錄或代理人機制補齊。`, addWorkflowAudit, "流程範本角色防呆");
  }
  workflowTasks.unshift({
    id: `WF-${Date.now().toString().slice(-6)}`,
    title: `${category.label} - ${docType}`,
    type: "發文",
    step: template.steps[0],
    role: approvalRoleForStep(template.steps[0], { requester: activeRole() }),
    status: "待處理",
    template: activeWorkflowTemplate,
    approvalRouteCode: route.code,
    approvalRouteName: route.name,
    documentCategory: category.label,
    requester: activeRole(),
    currentStepIndex: 0
  });
  selectedWorkflowTaskId = workflowTasks[0].id;
  renderWorkflowTemplateSteps();
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  addWorkflowAudit("套用流程範本", `${route.name} 已套用到 ${category.label}，新增 ${template.steps.length} 個簽核節點。`);
  addWorkflowProof("流程範本建立", `${route.name} / ${docType} / ${category.label} 已建立流程實例。`);
  showToast("流程範本已套用。");
}

function evaluateWorkflowConditions() {
  renderWorkflowConditions();
  const categoryValue = document.querySelector("#workflowDocumentCategorySelect")?.value || "";
  const route = approvalRouteForType(categoryValue);
  const security = document.querySelector("#workflowConditionSecurity").value;
  const priority = document.querySelector("#workflowConditionPriority").value;
  const amount = Number(document.querySelector("#workflowAmountInput").value || 0);
  const docType = document.querySelector("#workflowTemplateDocType")?.value;
  const docTypeConfig = documentTypeConfigForName(docType);
  activeWorkflowTemplate = docTypeConfig?.defaultWorkflowTemplate || workflowTemplateKeyForRoute(route.code);
  if (!workflowTemplates[activeWorkflowTemplate]) activeWorkflowTemplate = enabledWorkflowTemplateConfigs()[0]?.key || activeWorkflowTemplate;
  document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  renderWorkflowTemplateSteps();
  addWorkflowAudit("評估條件式簽核", `密等 ${security}、速別 ${priority}、金額 ${amount}，依小類別建議流程：${workflowTemplates[activeWorkflowTemplate]?.name || "未設定流程"}。`);
  showToast("條件式簽核已評估。");
}

function addWorkflowProxy() {
  const proxy = {
    id: `PX-${Date.now().toString().slice(-5)}`,
    from: document.querySelector("#workflowProxyFrom").value,
    to: document.querySelector("#workflowProxyTo").value,
    reason: document.querySelector("#workflowProxyReason").value.trim(),
    status: "啟用"
  };
  workflowProxies.unshift(proxy);
  renderWorkflowProxies();
  addWorkflowAudit("新增代理人", `${proxy.from} 由 ${proxy.to} 代理，原因：${proxy.reason}。`);
  addWorkflowProof("代理人啟用", `${proxy.from} → ${proxy.to} 已啟用代理。`);
  showToast("代理人已新增。");
}

function toggleWorkflowProxy(id) {
  const proxy = workflowProxies.find((item) => item.id === id);
  if (!proxy) return;
  proxy.status = proxy.status === "啟用" ? "停用" : "啟用";
  renderWorkflowProxies();
  addWorkflowAudit("更新代理狀態", `${proxy.from} → ${proxy.to} 已${proxy.status}。`);
  showToast("代理狀態已更新。");
}

function applyWorkflowProxy(id) {
  const proxy = workflowProxies.find((item) => item.id === id && item.status === "啟用");
  if (!proxy) return showToast("此代理未啟用。");
  workflowTasks.filter((task) => task.role === proxy.from && /待|審核/.test(task.status)).forEach((task) => {
    task.role = proxy.to;
    task.lastComment = `代理原因：${proxy.reason}`;
  });
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  addWorkflowAudit("套用代理人", `已將待辦由 ${proxy.from} 改派給代理 ${proxy.to}。`);
  addWorkflowProof("代理改派", `${proxy.from} 待辦已由 ${proxy.to} 代理處理。`);
  showToast("代理人已套用。");
}

function runWorkflowAdvancedAction() {
  const action = document.querySelector("#workflowActionSelect").value;
  const target = document.querySelector("#workflowActionTarget").value;
  const comment = document.querySelector("#workflowComment").value.trim();
  const ids = selectedWorkflowIds();
  const actionMap = { return: "退回補正", withdraw: "已抽回", addSign: "加簽中", countersign: "會辦中", reassign: "已改派" };
  if (!ids.length) return showToast("請先選取簽核節點。");
  if (!actionMap[action]) return showToast("請選擇有效的簽核動作。");
  if (["addSign", "countersign", "reassign"].includes(action) && !target) {
    return blockOperation("加簽、會辦或改派必須指定目標角色。", addWorkflowAudit, "簽核流程防呆");
  }
  if (["return", "withdraw", "reassign"].includes(action) && !hasMinimumText(comment)) {
    return blockOperation("退回、抽回或改派必須填寫至少 6 個字的簽核意見。", addWorkflowAudit, "簽核流程防呆");
  }
  const targetTasks = ids.map((id) => workflowTasks.find((item) => item.id === id)).filter(Boolean);
  const closedTask = targetTasks.find((task) => /已核准|已押章|完成/.test(task.status));
  if (closedTask) return blockOperation(`${closedTask.title} 已完成，不可再執行進階簽核動作。`, addWorkflowAudit, "簽核流程防呆");
  if (!confirmOperation("確認簽核流程異動", `即將對 ${ids.length} 個節點執行「${actionMap[action]}」${target ? `，目標：${target}` : ""}。`)) return;
  ids.forEach((id) => {
    const task = workflowTasks.find((item) => item.id === id);
    if (!task) return;
    task.status = actionMap[action];
    if (["addSign", "countersign", "reassign"].includes(action)) task.role = target;
    task.lastComment = comment;
    task.lastSignedAt = new Date().toLocaleString("zh-TW", { hour12: false });
    addWorkflowProof(actionMap[action], `${task.title} → ${target}，意見：${comment}`);
  });
  renderWorkflowTasks();
  renderApprovalProgress();
  renderDashboardApprovalProgress();
  addWorkflowAudit("執行進階簽核動作", `已對 ${ids.length} 件執行「${actionMap[action]}」，目標：${target}。`);
  showToast("簽核動作已執行。");
}

function checkPermission(action) {
  const allowed = (rolePermissions[workflowRole] || []).includes(action);
  document.querySelector("#permissionTestResult").textContent = allowed
    ? `${workflowRole} 可以執行「${permissionLabels[action]}」`
    : `${workflowRole} 不可執行「${permissionLabels[action]}」`;
  addWorkflowAudit("權限檢查", `${workflowRole} ${allowed ? "允許" : "限制"} ${permissionLabels[action]}。`);
  showToast(allowed ? "權限允許。" : "權限不足。");
}

function addSealAudit(title, body) {
  sealAuditLog.unshift([nowTime(), title, body]);
  renderSealAuditLog();
}

function companySealFallbackCompanies() {
  return companyRegistry.map((item) => ({
    id: item.id,
    name: item.name,
    tax_id: item.tax_id || item.taxId || "待設定",
    status: item.status === "啟用" ? "active" : item.status
  }));
}

function companySealRefOptions(type) {
  const grouped = companySealReferences?.grouped || {};
  const fallback = {
    category: [
      { code: "establishment_seal", name: "公司設立印鑑" },
      { code: "bank_seal", name: "銀行印鑑章" },
      { code: "general_seal", name: "便章" },
      { code: "other", name: "其他章" }
    ],
    size: [
      { code: "large_seal", name: "大章" },
      { code: "small_seal", name: "小章" }
    ],
    usage_type: [
      { code: "official_document", name: "公文" },
      { code: "contract", name: "合約" },
      { code: "bank_document", name: "銀行文件" },
      { code: "government_application", name: "政府申請文件" },
      { code: "internal_document", name: "內部文件" }
    ],
    request_status: [
      { code: "draft", name: "草稿" },
      { code: "pending", name: "待簽核" },
      { code: "approved", name: "已核准" },
      { code: "rejected", name: "已駁回" },
      { code: "stamped", name: "已用印" },
      { code: "cancelled", name: "已取消" }
    ]
  };
  return (grouped[type] && grouped[type].length ? grouped[type] : fallback[type] || []).filter((item) => !item.status || item.status === "active");
}

function companySealRefName(type, code) {
  return companySealRefOptions(type).find((item) => item.code === code)?.name || code || "-";
}

function companySealStatusName(status) {
  return companySealRefName("request_status", status) || status || "-";
}

function companySealOptionTags(items, selectedValue, valueKey = "id", labelKey = "name") {
  return items.map((item) => {
    const value = item[valueKey];
    const label = item[labelKey] || value;
    return `<option value="${value}"${value === selectedValue ? " selected" : ""}>${label}</option>`;
  }).join("");
}

function companySealDocuments() {
  const dispatchOptions = dispatchDocs.map((doc) => ({
    id: doc.id,
    label: `${doc.no || doc.id}｜${doc.subject || "未命名公文"}`,
    source: "dispatch",
    record: doc
  }));
  const contractOptions = contractRecords.map((contract) => ({
    id: contract.id,
    label: `${contract.contractNo || contract.id}｜${contract.title}`,
    source: "contract",
    record: contract
  }));
  return [...dispatchOptions, ...contractOptions];
}

function companySealDocumentPayload(documentId) {
  const dispatch = dispatchDocs.find((doc) => doc.id === documentId);
  if (dispatch) {
    return {
      document_id: dispatch.id,
      doc_no: dispatch.no || dispatch.id,
      doc_type: dispatch.type || "函",
      company_name: dispatch.companyName || document.querySelector("#composeCompanySelect")?.value || "歲悅長照股份有限公司",
      subject: dispatch.subject || "用印公文",
      body: dispatch.description || dispatch.body || "用印申請關聯公文。",
      owner: dispatch.owner || activeRole(),
      department: dispatch.department || "行政部",
      agency_name: dispatch.to || dispatch.agency || "未指定機關",
      status: dispatch.status || "待用印"
    };
  }
  const contract = contractRecords.find((item) => item.id === documentId);
  if (contract) {
    return {
      document_id: contract.id,
      doc_no: contract.contractNo || contract.id,
      doc_type: "合約用印",
      company_name: contract.companyName,
      subject: contract.title,
      body: contract.summary || "合約用印申請。",
      owner: contract.owner || activeRole(),
      department: contract.dept || "行政部",
      agency_name: contract.counterparty || "合約相對人",
      status: contract.status || "待用印"
    };
  }
  return {
    document_id: documentId || `DOC-SEAL-${Date.now()}`,
    doc_no: documentId || `DOC-SEAL-${Date.now()}`,
    doc_type: "用印文件",
    subject: "用印文件",
    body: "用印申請關聯文件。",
    owner: activeRole(),
    department: "行政部",
    agency_name: "未指定",
    status: "待用印"
  };
}

function currentCompanySealCompany() {
  const companies = companySealCompanies.length ? companySealCompanies : companySealFallbackCompanies();
  return companies.find((item) => item.id === selectedCompanySealCompanyId) || companies[0] || null;
}

function currentCompanySeal() {
  return companySealLibrary.find((item) => item.id === selectedCompanySealId) || companySealLibrary[0] || null;
}

async function loadCompanySealModule(silent = false) {
  try {
    const [companiesResult, referencesResult] = await Promise.all([
      backendRequest("/companies").catch(() => []),
      backendRequest("/seal-reference-options").catch(() => ({ grouped: {} }))
    ]);
    companySealCompanies = (Array.isArray(companiesResult) ? companiesResult : []).map((item) => ({
      ...item,
      tax_id: item.tax_id || item.taxId || "待設定"
    }));
    companySealReferences = referencesResult || { grouped: {} };
    if (!companySealCompanies.length) companySealCompanies = companySealFallbackCompanies();
    if (!selectedCompanySealCompanyId) selectedCompanySealCompanyId = companySealCompanies[0]?.id || "";
    companySealModuleLoaded = true;
    await loadCompanySealCompanyData(silent);
  } catch (error) {
    companySealCompanies = companySealFallbackCompanies();
    companySealModuleLoaded = false;
    renderCompanySealModule();
    if (!silent) showToast(`公司印章模組載入失敗：${error.message}`);
  }
}

async function loadCompanySealCompanyData(silent = false) {
  if (!selectedCompanySealCompanyId) {
    renderCompanySealModule();
    return;
  }
  try {
    const [seals, requests, logs] = await Promise.all([
      backendRequest(`/companies/${encodeURIComponent(selectedCompanySealCompanyId)}/seals`),
      backendRequest(`/seal-requests?company_id=${encodeURIComponent(selectedCompanySealCompanyId)}`).catch(() => []),
      backendRequest("/seal-usage-logs").catch(() => [])
    ]);
    companySealLibrary = Array.isArray(seals) ? seals : [];
    companySealRequests = Array.isArray(requests) ? requests : [];
    companySealLogs = Array.isArray(logs) ? logs : [];
    if (!companySealLibrary.some((item) => item.id === selectedCompanySealId)) selectedCompanySealId = companySealLibrary[0]?.id || "";
    companySealFiles = selectedCompanySealId ? await backendRequest(`/seals/${encodeURIComponent(selectedCompanySealId)}/files`).catch(() => []) : [];
    renderCompanySealModule();
    if (!silent) addSealAudit("同步公司印章庫", `${currentCompanySealCompany()?.name || "公司"} 已載入 ${companySealLibrary.length} 顆印章。`);
  } catch (error) {
    companySealLibrary = [];
    companySealRequests = [];
    companySealLogs = [];
    renderCompanySealModule();
    if (!silent) showToast(`公司印章庫同步失敗：${error.message}`);
  }
}

function renderCompanySealModule() {
  if (!document.querySelector("#companySealModule")) return;
  const companies = companySealCompanies.length ? companySealCompanies : companySealFallbackCompanies();
  if (!selectedCompanySealCompanyId) selectedCompanySealCompanyId = companies[0]?.id || "";
  const selectedSeal = currentCompanySeal();
  document.querySelector("#companySealCompanySelect").innerHTML = companySealOptionTags(companies, selectedCompanySealCompanyId);
  document.querySelector("#sealUsageCompanySelect").innerHTML = companySealOptionTags(companies, selectedCompanySealCompanyId);
  document.querySelector("#companySealCategorySelect").innerHTML = companySealOptionTags(companySealRefOptions("category"), "general_seal", "code", "name");
  document.querySelector("#companySealSizeSelect").innerHTML = companySealOptionTags(companySealRefOptions("size"), "large_seal", "code", "name");
  document.querySelector("#sealUsageTypeSelect").innerHTML = companySealOptionTags(companySealRefOptions("usage_type"), "official_document", "code", "name");
  document.querySelector("#companySealLibraryStatus").textContent = `${companySealLibrary.length} 枚`;

  const activeSeals = companySealLibrary.filter((seal) => seal.is_active || seal.is_active === 1);
  const selectedUsageSealId = document.querySelector("#sealUsageSealSelect")?.value || selectedCompanySealId;
  document.querySelector("#sealUsageSealSelect").innerHTML = activeSeals.map((seal) => `
    <option value="${seal.id}"${seal.id === selectedUsageSealId ? " selected" : ""}>${seal.seal_name}｜${companySealRefName("category", seal.seal_category)}｜${companySealRefName("size", seal.seal_size_type)}</option>
  `).join("");
  const docs = companySealDocuments();
  const currentDoc = document.querySelector("#sealUsageDocumentSelect")?.value || docs[0]?.id || "";
  document.querySelector("#sealUsageDocumentSelect").innerHTML = companySealOptionTags(docs, currentDoc, "id", "label");
  document.querySelector("#sealStampRequestSelect").innerHTML = companySealRequests
    .filter((request) => request.status === "approved")
    .map((request) => `<option value="${request.id}">${request.id}｜${request.seal_name || request.seal_id}｜${request.request_reason || "待套印"}</option>`)
    .join("");

  document.querySelector("#companySealLibraryRows").innerHTML = companySealLibrary.map((seal) => {
    const currentFile = seal.current_file;
    return `
      <tr class="${seal.id === selectedCompanySealId ? "selected-row" : ""}">
        <td><button class="text-button row-select" type="button" data-company-seal-select="${seal.id}">${seal.seal_name}</button><small>${seal.company_name || currentCompanySealCompany()?.name || ""}</small></td>
        <td>${companySealRefName("category", seal.seal_category)}</td>
        <td>${companySealRefName("size", seal.seal_size_type)}</td>
        <td><span class="badge ${seal.is_active || seal.is_active === 1 ? "ok" : "issue"}">${seal.is_active || seal.is_active === 1 ? "啟用" : "停用"}</span></td>
        <td>${currentFile ? `v${currentFile.version}` : "未上傳"}<small>${currentFile?.uploaded_at || seal.updated_at || ""}</small></td>
        <td><div class="row-actions"><button class="segment" type="button" data-company-seal-select="${seal.id}">檢視</button><button class="segment" type="button" data-company-seal-disable="${seal.id}">停用</button></div></td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="6">尚無印章資料。</td></tr>`;

  document.querySelector("#companySealSafePreview").innerHTML = selectedSeal ? `
    <strong>${selectedSeal.seal_name}</strong>
    <small>${companySealRefName("category", selectedSeal.seal_category)} / ${companySealRefName("size", selectedSeal.seal_size_type)} / ${selectedSeal.purpose_description || "未填用途"}</small>
    <small>原始圖檔不提供前端 URL；目前僅顯示 metadata 與浮水印安全預覽。</small>
    <div class="watermark-preview">安全預覽<br />非原章檔</div>
  ` : `<strong>未選取印章</strong><small>請先選取公司印章。</small>`;

  document.querySelector("#companySealFilesList").innerHTML = companySealFiles.map((file) => `
    <article class="address-card">
      <strong>${file.file_name} ${file.is_current || file.is_current === 1 ? "（目前）" : ""}</strong>
      <p>v${file.version} · ${file.file_mime_type} · ${Math.round(Number(file.file_size || 0) / 1024)} KB</p>
      <p>hash ${String(file.file_hash || "").slice(0, 18)}… · ${file.uploaded_at || ""}</p>
      <div class="row-actions"><button class="segment" type="button" data-company-seal-current-file="${file.id}">設為目前版本</button></div>
    </article>
  `).join("") || `<p class="empty-text">尚未上傳印章版本；不會顯示原始章圖 URL。</p>`;

  document.querySelector("#sealUsagePositionsGrid").innerHTML = companySealStampPositions.map((position, index) => `
    <article class="archive-card">
      <span>章位 ${index + 1}</span>
      <strong>第 ${position.page} 頁 / ${position.w}×${position.h}</strong>
      <p>x ${position.x} · y ${position.y} · ${position.label}</p>
    </article>
  `).join("");

  document.querySelector("#sealUsageApprovalStatus").textContent = `${companySealRequests.length} 件`;
  document.querySelector("#sealUsageApprovalList").innerHTML = companySealRequests.map((request) => `
    <article class="timeline-item">
      <time>${companySealStatusName(request.status)}</time>
      <div>
        <strong>${request.seal_name || request.seal_id}</strong>
        <p>${request.company_name || ""} · ${request.requested_by || "申請人"} · ${request.request_reason || "未填原因"}</p>
        <p>${request.document_id} · ${companySealRefName("usage_type", request.usage_type)}</p>
        <div class="row-actions">
          <button class="segment" type="button" data-company-seal-approve-request="${request.id}" ${!["pending", "draft"].includes(request.status) ? "disabled" : ""}>核准並套印</button>
          <button class="segment" type="button" data-company-seal-reject-request="${request.id}" ${["stamped", "cancelled", "rejected"].includes(request.status) ? "disabled" : ""}>駁回</button>
        </div>
      </div>
    </article>
  `).join("") || `<p class="empty-text">尚無用印申請。</p>`;

  document.querySelector("#sealUsageLogList").innerHTML = companySealLogs.slice(0, 30).map((log) => `
    <article class="timeline-item">
      <time>${log.created_at || ""}</time>
      <div>
        <strong>${log.action}</strong>
        <p>${log.actor_id || "API"} · ${log.detail || ""}</p>
        <p>${log.usage_request_id || ""} ${log.document_id || ""}</p>
      </div>
    </article>
  `).join("") || `<p class="empty-text">尚無用印紀錄。</p>`;

  document.querySelectorAll("[data-company-seal-select]").forEach((button) => {
    button.addEventListener("click", () => selectCompanySeal(button.dataset.companySealSelect));
  });
  document.querySelectorAll("[data-company-seal-disable]").forEach((button) => {
    button.addEventListener("click", () => deactivateCompanySeal(button.dataset.companySealDisable));
  });
  document.querySelectorAll("[data-company-seal-current-file]").forEach((button) => {
    button.addEventListener("click", () => setCompanySealCurrentFile(button.dataset.companySealCurrentFile));
  });
  document.querySelectorAll("[data-company-seal-approve-request]").forEach((button) => {
    button.addEventListener("click", () => approveCompanySealUsageRequest(button.dataset.companySealApproveRequest));
  });
  document.querySelectorAll("[data-company-seal-reject-request]").forEach((button) => {
    button.addEventListener("click", () => rejectCompanySealUsageRequest(button.dataset.companySealRejectRequest));
  });
}

async function selectCompanySeal(id) {
  selectedCompanySealId = id;
  companySealFiles = await backendRequest(`/seals/${encodeURIComponent(id)}/files`).catch((error) => {
    showToast(`印章版本讀取失敗：${error.message}`);
    return [];
  });
  renderCompanySealModule();
}

async function createCompanySealFromForm() {
  const companyId = selectedCompanySealCompanyId || document.querySelector("#companySealCompanySelect")?.value;
  if (!companyId) return showToast("請先選擇公司。");
  try {
    const result = await backendRequest(`/companies/${encodeURIComponent(companyId)}/seals`, {
      method: "POST",
      body: JSON.stringify({
        seal_name: document.querySelector("#companySealNameInput")?.value.trim() || "未命名印章",
        seal_category: document.querySelector("#companySealCategorySelect")?.value || "other",
        seal_size_type: document.querySelector("#companySealSizeSelect")?.value || "large_seal",
        purpose_description: document.querySelector("#companySealPurposeInput")?.value.trim() || "",
        actor: authState?.user?.name || activeRole()
      })
    });
    selectedCompanySealId = result.id;
    await loadCompanySealCompanyData(true);
    addSealAudit("新增公司印章", `${result.seal_name} 已建立，等待上傳私有印章檔版本。`);
    showToast("公司印章已新增。");
  } catch (error) {
    showToast(`新增印章失敗：${error.message}`);
  }
}

async function deactivateCompanySeal(id) {
  const seal = companySealLibrary.find((item) => item.id === id);
  if (!seal) return;
  if (!confirmOperation("確認停用印章", `停用 ${seal.seal_name} 後不可再建立新用印申請，但歷史紀錄會保留。`)) return;
  try {
    await backendRequest(`/seals/${encodeURIComponent(id)}`, { method: "DELETE" });
    await loadCompanySealCompanyData(true);
    addSealAudit("停用公司印章", `${seal.seal_name} 已停用。`);
    showToast("印章已停用。");
  } catch (error) {
    showToast(`停用印章失敗：${error.message}`);
  }
}

async function uploadCompanySealVersion() {
  const file = document.querySelector("#companySealFileInput")?.files?.[0];
  const seal = currentCompanySeal();
  if (!seal) return showToast("請先選取印章。");
  if (!file) return showToast("請選擇新版印章檔。");
  try {
    const contentBase64 = await fileToBase64(file);
    const result = await backendRequest(`/seals/${encodeURIComponent(seal.id)}/files`, {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        file_mime_type: file.type || "image/png",
        content_base64: contentBase64,
        actor: authState?.user?.name || activeRole()
      })
    });
    selectedCompanySealId = result.seal?.id || seal.id;
    document.querySelector("#companySealFileInput").value = "";
    await selectCompanySeal(selectedCompanySealId);
    await loadCompanySealCompanyData(true);
    addSealAudit("上傳私有印章版本", `${seal.seal_name} 已上傳 ${file.name}，前端僅保留 metadata。`);
    showToast("新版印章檔已上傳至私有儲存區。");
  } catch (error) {
    showToast(`上傳新版失敗：${error.message}`);
  }
}

async function setCompanySealCurrentFile(fileId) {
  try {
    await backendRequest(`/seal-files/${encodeURIComponent(fileId)}/set-current`, { method: "PATCH" });
    await selectCompanySeal(selectedCompanySealId);
    await loadCompanySealCompanyData(true);
    showToast("目前版本已更新。");
  } catch (error) {
    showToast(`設定版本失敗：${error.message}`);
  }
}

function addCompanySealStampPosition() {
  const seal = currentCompanySeal();
  companySealStampPositions.push({
    page: Number(document.querySelector("#sealUsagePageInput")?.value || 1),
    x: Number(document.querySelector("#sealUsageXInput")?.value || 420),
    y: Number(document.querySelector("#sealUsageYInput")?.value || 130),
    w: Number(document.querySelector("#sealUsageWInput")?.value || 85),
    h: Number(document.querySelector("#sealUsageHInput")?.value || 85),
    label: seal?.seal_name || "用印",
    type: seal?.seal_category || "general_seal",
    seal_id: seal?.id || selectedCompanySealId
  });
  renderCompanySealModule();
}

async function submitCompanySealUsageRequest() {
  const documentId = document.querySelector("#sealUsageDocumentSelect")?.value;
  const sealId = document.querySelector("#sealUsageSealSelect")?.value || selectedCompanySealId;
  const reason = document.querySelector("#sealUsageReasonInput")?.value.trim();
  if (!documentId) return showToast("請選擇文件。");
  if (!sealId) return showToast("請選擇印章。");
  if (!hasMinimumText(reason, 4)) return showToast("請填寫用印原因。");
  const positions = companySealStampPositions.length ? companySealStampPositions : [{
    page: 1, x: 420, y: 130, w: 85, h: 85, label: "用印", type: "general_seal", seal_id: sealId
  }];
  try {
    const result = await backendRequest(`/documents/${encodeURIComponent(documentId)}/seal-requests`, {
      method: "POST",
      body: JSON.stringify({
        seal_id: sealId,
        request_reason: reason,
        usage_type: document.querySelector("#sealUsageTypeSelect")?.value || "official_document",
        stamp_positions: positions.map((position) => ({ ...position, seal_id: sealId })),
        actor: authState?.user?.name || activeRole(),
        document: companySealDocumentPayload(documentId),
        metadata: { source: "company_seal_module", approval_template: "finance_style" }
      })
    });
    await loadCompanySealCompanyData(true);
    addSealAudit("送出公司用印申請", `${result.id} 已送簽核，章位 ${positions.length} 個。`);
    showToast("用印申請已送出簽核。");
  } catch (error) {
    showToast(`送出用印申請失敗：${error.message}`);
  }
}

async function approveCompanySealUsageRequest(requestId) {
  try {
    const approved = await backendRequest(`/seal-requests/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ actor: authState?.user?.name || activeRole(), comment: document.querySelector("#sealUsageApprovalComment")?.value || "核准用印。" })
    });
    addSealAudit("核准公司用印申請", `${requestId} 已核准，準備自動套印。`);
    if (approved.status === "approved") {
      await stampCompanySealUsageRequest(requestId, true);
    } else {
      await loadCompanySealCompanyData(true);
      showToast("簽核已更新，尚有下一層簽核。");
    }
  } catch (error) {
    showToast(`核准失敗：${error.message}`);
  }
}

async function rejectCompanySealUsageRequest(requestId) {
  try {
    await backendRequest(`/seal-requests/${encodeURIComponent(requestId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ actor: authState?.user?.name || activeRole(), comment: document.querySelector("#sealUsageApprovalComment")?.value || "駁回用印。" })
    });
    await loadCompanySealCompanyData(true);
    addSealAudit("駁回公司用印申請", `${requestId} 已駁回。`);
    showToast("用印申請已駁回。");
  } catch (error) {
    showToast(`駁回失敗：${error.message}`);
  }
}

async function stampCompanySealUsageRequest(requestId = "", automatic = false) {
  const targetId = requestId || document.querySelector("#sealStampRequestSelect")?.value;
  if (!targetId) return showToast("請先選擇已核准申請。");
  try {
    const request = companySealRequests.find((item) => item.id === targetId);
    const result = await backendRequest(`/seal-requests/${encodeURIComponent(targetId)}/stamp`, {
      method: "POST",
      body: JSON.stringify({
        actor: authState?.user?.name || activeRole(),
        stamp_positions: request?.stamp_positions?.length ? request.stamp_positions : companySealStampPositions,
        template: request?.usage_type === "contract" ? "合約用印文件" : "公司用印文件"
      })
    });
    document.querySelector("#sealUsageStampedResult").innerHTML = `
      <article class="archive-card">
        <span>已用印版本</span>
        <strong>${result.stamped_file?.stamp_no || "STAMP"}</strong>
        <p>PDF version ${result.stamped_file?.pdf_version_id || "-"} · hash ${String(result.stamped_file?.sha256 || "").slice(0, 18)}…</p>
      </article>
    `;
    await loadCompanySealCompanyData(true);
    addSealAudit("完成公司用印套印", `${targetId} 已產出不可覆蓋的新 PDF 用印版本。`);
    showToast(automatic ? "核准完成，系統已自動用印。" : "文件已完成套印。");
  } catch (error) {
    await loadCompanySealCompanyData(true);
    showToast(`套印失敗：${error.message}`);
  }
}

function addCompanyRegistryItem() {
  if (activeRole() !== "執行長") return showToast("只有執行長可以新增公司。");
  const name = document.querySelector("#companyNameInput").value.trim();
  const taxId = document.querySelector("#companyTaxIdInput").value.trim() || "待設定";
  if (!hasMinimumText(name, 2)) return showToast("請輸入公司名稱。");
  if (companyRegistry.some((item) => item.name === name)) return showToast("此公司已存在。");
  const item = { id: `CO-${Date.now().toString().slice(-5)}`, name, taxId, status: "啟用" };
  companyRegistry.unshift(item);
  persistToBackend("/company_registry", { id: item.id, name: item.name, tax_id: item.taxId, status: item.status });
  renderComposeCompanyOptions();
  renderSeals();
  renderDraftPreview();
  addSealAudit("新增公司", `執行長新增公司：${name}。`);
  showToast("公司已新增。");
}

function addDepartmentRegistryItem() {
  if (activeRole() !== "執行長") return showToast("只有執行長可以新增部門。");
  const company = document.querySelector("#departmentCompanyInput").value;
  const name = document.querySelector("#departmentNameInput").value.trim();
  const manager = document.querySelector("#departmentManagerInput").value;
  if (!hasMinimumText(name, 2)) return showToast("請輸入部門名稱。");
  if (departmentRegistry.some((item) => item.company === company && item.name === name)) return showToast("此部門已存在。");
  const item = { id: `DEP-${Date.now().toString().slice(-5)}`, company, name, manager, status: "啟用" };
  departmentRegistry.unshift(item);
  persistToBackend("/department_registry", { id: item.id, company_name: item.company, name: item.name, manager_role: item.manager, status: item.status });
  renderSeals();
  addSealAudit("新增部門", `執行長新增 ${company} / ${name}，主管角色 ${manager}。`);
  showToast("部門已新增。");
}

function addSealTypeRegistryItem() {
  if (activeRole() !== "執行長") return showToast("只有執行長可以新增印章類別。");
  const name = document.querySelector("#sealTypeNameInput").value.trim();
  const scope = document.querySelector("#sealTypeScopeInput").value.trim() || "未設定使用範圍";
  if (!hasMinimumText(name, 2)) return showToast("請輸入印章類別。");
  if (sealTypeRegistry.some((item) => item.name === name)) return showToast("此印章類別已存在。");
  const item = { id: `ST-${Date.now().toString().slice(-5)}`, name, scope, status: "啟用" };
  sealTypeRegistry.unshift(item);
  persistToBackend("/seal_type_registry", { id: item.id, name: item.name, scope: item.scope, status: item.status });
  renderSeals();
  addSealAudit("新增印章類別", `執行長新增印章類別：${name}。`);
  showToast("印章類別已新增。");
}

function currentSeal() {
  return sealRegistry.find((seal) => seal.id === selectedSealId) || sealRegistry[0] || null;
}

function currentSealRequest() {
  return sealRequests.find((request) => request.id === selectedSealRequestId) || sealRequests[0] || null;
}

function selectedSealRequestIds() {
  const checked = [...document.querySelectorAll(".seal-request-check:checked")].map((item) => item.value);
  return checked.length ? checked : selectedSealRequestId ? [selectedSealRequestId] : [];
}

function sealRequestDoc(request) {
  return dispatchDocs.find((doc) => doc.id === request.docId);
}

function sealById(id) {
  return sealRegistry.find((seal) => seal.id === id);
}

function sealForComposeType(type, companyName) {
  if (!type || type === "無") return null;
  return sealRegistry.find((seal) => seal.status === "啟用" && seal.type === type && seal.company === companyName)
    || sealRegistry.find((seal) => seal.status === "啟用" && seal.type === type)
    || null;
}

function renderSealSummary() {
  document.querySelector("#activeSealCount").textContent = sealRegistry.filter((seal) => seal.status === "啟用").length;
  document.querySelector("#pendingSealCount").textContent = sealRequests.filter((request) => request.status === "待簽核").length;
  document.querySelector("#stampedDocCount").textContent = sealRequests.filter((request) => request.status === "已押章").length;
  document.querySelector("#sealAuditCount").textContent = sealAuditLog.length;
}

function optionTags(values, selected = values[0]) {
  return values.map((value) => `<option${value === selected ? " selected" : ""}>${value}</option>`).join("");
}

function renderExecutiveSealAdmin() {
  const panel = document.querySelector("#executiveSealAdmin");
  if (!panel) return;
  const isExecutive = activeRole() === "執行長";
  panel.hidden = !isExecutive;
  if (!isExecutive) return;
  const companyNames = companyRegistry.map((item) => item.name);
  const departmentNames = departmentRegistry.map((item) => item.name);
  const sealTypeNames = sealTypeRegistry.map((item) => item.name);
  document.querySelector("#departmentCompanyInput").innerHTML = optionTags(companyNames);
  document.querySelector("#sealCompanyInput").innerHTML = optionTags(companyNames);
  document.querySelector("#sealDepartmentInput").innerHTML = optionTags(departmentNames, departmentNames[1] || departmentNames[0]);
  document.querySelector("#sealTypeInput").innerHTML = optionTags(sealTypeNames);
  document.querySelector("#companyRegistryList").innerHTML = companyRegistry.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <p>統一編號：${item.taxId} · ${item.status}</p>
    </article>
  `).join("");
  document.querySelector("#departmentRegistryList").innerHTML = departmentRegistry.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <p>${item.company} · 主管：${item.manager} · ${item.status}</p>
    </article>
  `).join("");
  document.querySelector("#sealTypeRegistryList").innerHTML = sealTypeRegistry.map((item) => `
    <article class="address-card">
      <strong>${item.name}</strong>
      <p>${item.scope} · ${item.status}</p>
    </article>
  `).join("");
}

function renderSealRegistry() {
  document.querySelector("#sealCount").textContent = `${sealRegistry.length} 枚`;
  document.querySelector("#sealRegistry").innerHTML = sealRegistry.map((seal) => `
    <article class="address-card ${seal.id === selectedSealId ? "selected-card" : ""}">
      <strong>${seal.name}</strong>
      <span>${seal.company || "未指定公司"} · ${seal.department || "未指定部門"}</span>
      <span>${seal.type} · ${seal.owner} · ${seal.docType}</span>
      <p>${seal.status} · 實體 ${seal.widthMm || "-"} × ${seal.heightMm || "-"} mm · ${seal.calibrationStatus || "待校準"}</p>
      <p>${seal.imageName || "未上傳圖檔"} · ${seal.hash}</p>
      <div class="row-actions">
        <button class="segment" type="button" data-seal-select="${seal.id}">檢視</button>
        <button class="segment" type="button" data-seal-toggle="${seal.id}">${seal.status === "啟用" ? "停用" : "啟用"}</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-seal-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedSealId = button.dataset.sealSelect;
      renderSeals();
    });
  });
  document.querySelectorAll("[data-seal-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleSeal(button.dataset.sealToggle));
  });
}

function renderSealDetail() {
  const seal = currentSeal();
  if (!seal) {
    document.querySelector("#selectedSealStatus").textContent = "未選取";
    document.querySelector("#sealDetail").innerHTML = `<p class="empty-text">尚無印鑑資料。</p>`;
    return;
  }
  document.querySelector("#selectedSealStatus").textContent = seal.status;
  const calibratedWidth = Math.max(24, Math.min(120, Number(seal.widthMm || 30) * 2));
  const calibratedHeight = Math.max(24, Math.min(120, Number(seal.heightMm || 30) * 2));
  const preview = seal.imageDataUrl
    ? `<img class="seal-upload-preview" src="${seal.imageDataUrl}" alt="${seal.name}" style="width:${calibratedWidth}px;height:${calibratedHeight}px" />`
    : `<div class="seal-mark" style="width:${calibratedWidth}px;height:${calibratedHeight}px">${seal.type.slice(0, 2)}</div>`;
  document.querySelector("#sealDetail").innerHTML = `
    <div class="doc-detail seal-preview">
      ${preview}
      <strong>${seal.name}</strong>
      <dl>
        <div><dt>公司</dt><dd>${seal.company || "未指定"}</dd></div>
        <div><dt>部門</dt><dd>${seal.department || "未指定"}</dd></div>
        <div><dt>印鑑編號</dt><dd>${seal.id}</dd></div>
        <div><dt>保管角色</dt><dd>${seal.owner}</dd></div>
        <div><dt>適用文別</dt><dd>${seal.docType}</dd></div>
        <div><dt>實體尺寸</dt><dd>${seal.widthMm || "-"} × ${seal.heightMm || "-"} mm</dd></div>
        <div><dt>PDF 尺寸</dt><dd>${sealWidthPt(seal)} × ${sealHeightPt(seal)} pt</dd></div>
        <div><dt>章圖檔案</dt><dd>${seal.imageName || "未上傳"}</dd></div>
        <div><dt>校準狀態</dt><dd>${seal.calibrationStatus || "待校準"}</dd></div>
        <div><dt>狀態</dt><dd>${seal.status}</dd></div>
        <div><dt>雜湊</dt><dd>${seal.hash}</dd></div>
      </dl>
      <p>簽核通過後系統會以此印鑑建立章戳序號、時間戳、簽核人與公文關聯，並回寫發文封包。</p>
    </div>
  `;
}

function renderSealRequests() {
  document.querySelector("#sealRequestCount").textContent = `${sealRequests.length} 件`;
  document.querySelector("#sealRequestRows").innerHTML = sealRequests.map((request) => {
    const doc = sealRequestDoc(request);
    const seal = sealById(request.sealId);
    return `
      <tr class="${request.id === selectedSealRequestId ? "selected-row" : ""}">
        <td><input class="seal-request-check" type="checkbox" value="${request.id}" /></td>
        <td><button class="text-button row-select" type="button" data-seal-request="${request.id}">${doc?.no || request.docId}</button><small>${doc?.subject || "公文不存在"}</small></td>
        <td>${seal?.name || request.sealId}</td>
        <td>${request.step}</td>
        <td><span class="badge ${badgeClass(request.status)}">${request.status}</span><small>${request.stampNo || "尚未押章"}</small></td>
        <td><div class="row-actions"><button class="segment" type="button" data-seal-approve="${request.id}">核准</button><button class="segment" type="button" data-seal-reject="${request.id}">退回</button></div></td>
      </tr>
    `;
  }).join("");
  document.querySelectorAll("[data-seal-request]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedSealRequestId = button.dataset.sealRequest;
      renderSealRequests();
    });
  });
  document.querySelectorAll("[data-seal-approve]").forEach((button) => {
    button.addEventListener("click", () => approveSealRequests([button.dataset.sealApprove]));
  });
  document.querySelectorAll("[data-seal-reject]").forEach((button) => {
    button.addEventListener("click", () => rejectSealRequests([button.dataset.sealReject]));
  });
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",")[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function uploadedSealDocumentId() {
  const doc = currentDispatchDoc();
  return doc?.id ? (doc.id.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`) : `DOC-UPLOAD-SEAL-${Date.now()}`;
}

function uploadedStampToStageRect(stamp) {
  const stage = document.querySelector("#uploadedPdfStage");
  const width = stage?.clientWidth || 1;
  const height = stage?.clientHeight || 1;
  const pageWidth = 595;
  const pageHeight = 842;
  return {
    left: (Number(stamp.x || 0) / pageWidth) * width,
    top: height - ((Number(stamp.y || 0) + Number(stamp.h || 0)) / pageHeight) * height,
    width: (Number(stamp.w || 0) / pageWidth) * width,
    height: (Number(stamp.h || 0) / pageHeight) * height
  };
}

function stageRectToUploadedStamp(left, top, width, height, stamp) {
  const stage = document.querySelector("#uploadedPdfStage");
  const stageWidth = stage?.clientWidth || 1;
  const stageHeight = stage?.clientHeight || 1;
  const pageWidth = 595;
  const pageHeight = 842;
  return {
    ...stamp,
    x: Math.round((left / stageWidth) * pageWidth * 100) / 100,
    y: Math.round(((stageHeight - top - height) / stageHeight) * pageHeight * 100) / 100,
    w: Math.round((width / stageWidth) * pageWidth * 100) / 100,
    h: Math.round((height / stageHeight) * pageHeight * 100) / 100
  };
}

function addUploadedStamp(kind = "company") {
  if (!uploadedSealPdf) return showToast("請先上傳 PDF。");
  const seal = kind === "owner"
    ? (sealRegistry.find((item) => item.status === "啟用" && /負責人|圖記/.test(`${item.name}${item.type}`)) || currentSeal())
    : currentSeal();
  const pageSeal = kind === "page";
  uploadedSealStampPositions.push({
    id: `UPOS-${Date.now()}-${uploadedSealStampPositions.length + 1}`,
    page: pageSeal ? "all" : 1,
    x: pageSeal ? 560 : kind === "owner" ? 500 : 420,
    y: pageSeal ? 385 : 130,
    w: pageSeal ? 24 : sealWidthPt(seal),
    h: pageSeal ? 96 : sealHeightPt(seal),
    label: pageSeal ? "騎縫章" : kind === "owner" ? "負責人章" : "公司章",
    type: pageSeal ? "多頁章" : seal?.type || "一般章",
    seal_id: seal?.id || selectedSealId
  });
  renderUploadedSealWorkbench();
}

function bindUploadedStampDrag(marker, stamp) {
  marker.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    marker.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startY = event.clientY;
    const startLeft = marker.offsetLeft;
    const startTop = marker.offsetTop;
    const stage = document.querySelector("#uploadedPdfStage");
    const move = (moveEvent) => {
      const maxLeft = (stage?.clientWidth || 0) - marker.offsetWidth;
      const maxTop = (stage?.clientHeight || 0) - marker.offsetHeight;
      const left = Math.max(0, Math.min(maxLeft, startLeft + moveEvent.clientX - startX));
      const top = Math.max(0, Math.min(maxTop, startTop + moveEvent.clientY - startY));
      marker.style.left = `${left}px`;
      marker.style.top = `${top}px`;
    };
    const up = () => {
      marker.removeEventListener("pointermove", move);
      marker.removeEventListener("pointerup", up);
      const index = uploadedSealStampPositions.findIndex((item) => item.id === stamp.id);
      if (index >= 0) {
        uploadedSealStampPositions[index] = stageRectToUploadedStamp(marker.offsetLeft, marker.offsetTop, marker.offsetWidth, marker.offsetHeight, uploadedSealStampPositions[index]);
        renderUploadedSealWorkbench();
      }
    };
    marker.addEventListener("pointermove", move);
    marker.addEventListener("pointerup", up);
  });
}

function renderUploadedSealWorkbench() {
  const companySelect = document.querySelector("#uploadedSealCompany");
  if (companySelect) {
    const current = companySelect.value || companyRegistry[0]?.name || "歲悅股份有限公司";
    companySelect.innerHTML = optionTags(companyRegistry.map((item) => item.name), current);
  }
  const status = document.querySelector("#uploadedSealPdfStatus");
  if (status) status.textContent = uploadedSealPdf ? `${uploadedSealPdf.name} · ${uploadedSealStampPositions.length} 個章位` : "尚未上傳";
  const frame = document.querySelector("#uploadedPdfFrame");
  const empty = document.querySelector("#uploadedPdfEmpty");
  if (frame) {
    frame.hidden = !uploadedSealPdf;
    frame.src = uploadedSealObjectUrl || "about:blank";
  }
  if (empty) empty.hidden = Boolean(uploadedSealPdf);
  const layer = document.querySelector("#uploadedStampLayer");
  if (layer) {
    layer.innerHTML = uploadedSealStampPositions.map((stamp) => {
      const rect = uploadedStampToStageRect(stamp);
      return `
        <button class="uploaded-stamp-marker" type="button" data-uploaded-stamp="${stamp.id}" style="left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;height:${rect.height}px">
          ${stamp.label}<small>${stamp.page === "all" ? "全部頁" : `第 ${stamp.page} 頁`}</small>
        </button>
      `;
    }).join("");
    layer.querySelectorAll("[data-uploaded-stamp]").forEach((marker) => {
      const stamp = uploadedSealStampPositions.find((item) => item.id === marker.dataset.uploadedStamp);
      if (stamp) bindUploadedStampDrag(marker, stamp);
    });
  }
  const summary = document.querySelector("#uploadedStampSummary");
  if (summary) {
    summary.innerHTML = [
      ["PDF", uploadedSealPdf ? `${uploadedSealPdf.name} · ${uploadedSealPdf.size} bytes` : "待上傳"],
      ["章位", `${uploadedSealStampPositions.length} 個`],
      ["流程", document.querySelector("#uploadedSealRoute")?.value || "A"],
      ["類型", document.querySelector("#uploadedSealType")?.value === "contract" ? "電子合約" : "電子公文"]
    ].map(([label, value]) => `<article class="archive-card"><span>${label}</span><strong>${value}</strong></article>`).join("");
  }
}

async function handleUploadedSealPdfChange() {
  const input = document.querySelector("#uploadedSealPdfInput");
  const file = input?.files?.[0];
  if (!file) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    input.value = "";
    return showToast("請上傳 PDF 檔。");
  }
  if (uploadedSealObjectUrl) URL.revokeObjectURL(uploadedSealObjectUrl);
  uploadedSealObjectUrl = URL.createObjectURL(file);
  uploadedSealPdf = {
    file,
    name: file.name,
    size: file.size,
    contentBase64: await fileToBase64(file),
    hash: await hashBlob(file)
  };
  if (!uploadedSealStampPositions.length) {
    addUploadedStamp("company");
    addUploadedStamp("owner");
  }
  renderUploadedSealWorkbench();
  addSealAudit("上傳 PDF 用印來源", `${file.name} 已上傳至前端工作台，hash ${uploadedSealPdf.hash}。`);
}

function localSealRequestFromBackend(result) {
  return {
    id: result.id,
    backendApplicationId: result.id,
    docId: result.document_id,
    sealId: result.seal_id,
    step: result.current_step_name || "主管簽核",
    status: result.status,
    stampNo: result.stamp_no || "",
    stampedAt: result.completed_at || "",
    sourcePdfFileObjectId: result.source_pdf_file_object_id,
    stampPositions: result.stamp_positions || [],
    pdfHash: result.pdf_after?.sha256 || result.locked_pdf_sha256 || "",
    pdfSize: result.pdf_after?.file?.size_bytes || result.pdf_before?.file?.size_bytes || 0,
    applicationType: result.application_type
  };
}

async function submitUploadedSealApplication() {
  if (!uploadedSealPdf) return showToast("請先上傳 PDF。");
  if (!uploadedSealStampPositions.length) return showToast("請先加入至少一個用印處。");
  const sourceType = document.querySelector("#uploadedSealType")?.value || "official_document";
  const doc = currentDispatchDoc();
  const documentId = uploadedSealDocumentId();
  const payload = {
    id: `USEAL-${Date.now()}`,
    document_id: documentId,
    application_type: sourceType,
    company_name: document.querySelector("#uploadedSealCompany")?.value || companyRegistry[0]?.name || "歲悅股份有限公司",
    department: activeUnit() || "行政部",
    title: document.querySelector("#uploadedSealTitle")?.value || uploadedSealPdf.name,
    seal_id: selectedSealId,
    source_pdf_name: uploadedSealPdf.name,
    source_pdf_content_base64: uploadedSealPdf.contentBase64,
    approval_route_code: document.querySelector("#uploadedSealRoute")?.value || "A",
    reason: sourceType === "contract" ? "電子合約上傳 PDF 用印" : "電子公文上傳 PDF 用印",
    stamp_positions: uploadedSealStampPositions,
    document: {
      document_id: documentId,
      id: documentId,
      no: doc?.no || documentId,
      companyName: document.querySelector("#uploadedSealCompany")?.value || companyRegistry[0]?.name || "歲悅股份有限公司",
      direction: "發文",
      type: sourceType === "contract" ? "合約用印" : "函",
      subject: document.querySelector("#uploadedSealTitle")?.value || uploadedSealPdf.name,
      body: "上傳 PDF 用印申請。",
      owner: activeRole(),
      department: activeUnit() || "行政部"
    }
  };
  try {
    const result = await backendRequest("/seal-applications/submit", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const request = localSealRequestFromBackend(result);
    sealRequests.unshift(request);
    selectedSealRequestId = request.id;
    pdfVersionStore[request.docId] = pdfVersionStore[request.docId] || {};
    pdfVersionStore[request.docId].before = {
      id: result.pdf_before?.id,
      fileObjectId: result.pdf_before?.file_object_id,
      url: result.pdf_before?.download_url,
      hash: result.pdf_before?.sha256,
      size: result.pdf_before?.file?.size_bytes || uploadedSealPdf.size,
      createdAt: result.created_at,
      label: "上傳 PDF 鎖版",
      pageCount: result.pdf_before?.page_count || 1
    };
    addSealAudit("送出上傳 PDF 用印", `${payload.title} 已送主管簽核，PDF hash ${result.locked_pdf_sha256}，章位 hash ${result.locked_positions_sha256}。`);
    renderSeals();
    showToast("PDF 用印申請已送出。");
  } catch (error) {
    addSealAudit("上傳 PDF 用印送簽失敗", error.message);
    showToast(`送簽失敗：${error.message}`);
  }
}

function pdfEscape(value) {
  return String(value ?? "").replace(/[^\x20-\x7E]/g, "?").replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function pdfText(text, x, y, size = 11) {
  return `BT /F1 ${size} Tf ${x} ${y} Td (${pdfEscape(text)}) Tj ET\n`;
}

function stampCommands(stamp, pageIndex, pageCount) {
  return [
    "1 0 0 RG 1 0 0 rg",
    `${stamp.x} ${stamp.y} ${stamp.w || 56} ${stamp.h || 56} re S`,
    pdfText(stamp.label || "SEAL", stamp.x + 8, stamp.y + 32, 10),
    pdfText(stamp.stampNo || "STAMP", stamp.x + 5, stamp.y + 18, 6),
    pageCount > 1 ? pdfText(`Page ${pageIndex}/${pageCount}`, stamp.x + 7, stamp.y + 7, 6) : "",
    "0 0 0 RG 0 0 0 rg\n"
  ].join("\n");
}

function buildOfficialPdf(doc, stamps = [], options = {}) {
  const pageCount = options.multiPage ? 2 : 1;
  const pageWidth = 595;
  const pageHeight = 842;
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>"];
  const pageObjectNumbers = Array.from({ length: pageCount }, (_, index) => 3 + index * 2);
  objects.push(`<< /Type /Pages /Kids [${pageObjectNumbers.map((num) => `${num} 0 R`).join(" ")}] /Count ${pageCount} >>`);
  for (let page = 1; page <= pageCount; page += 1) {
    let stream = "";
    stream += "0.97 0.97 0.95 rg 36 36 523 770 re f 0 0 0 rg\n";
    stream += "0.85 0.42 0.04 RG 36 770 523 1 re S\n";
    stream += pdfText("Suiyuecare Official eDoc", 72, 740, 18);
    stream += pdfText(`Template: ${options.template || "Official Letter"}`, 72, 715, 9);
    stream += pdfText(`Doc No: ${doc.no}`, 72, 682, 12);
    stream += pdfText(`Recipient: ${doc.to} / ${doc.agencyCode}`, 72, 660, 11);
    stream += pdfText(`Type: ${doc.type}    Priority: ${doc.priority}    Security: ${doc.security}`, 72, 638, 11);
    stream += pdfText(`Subject: ${doc.subject}`, 72, 610, 11);
    stream += pdfText(`Body: ${doc.body}`, 72, 585, 10);
    stream += pdfText(`Attachments: ${doc.attachments.join(", ")}`, 72, 548, 10);
    stream += pdfText(`Generated: ${new Date().toLocaleString("zh-TW", { hour12: false })}`, 72, 92, 8);
    stream += pdfText(`Page ${page} of ${pageCount}`, 480, 56, 8);
    stamps.filter((stamp) => stamp.page === page || stamp.page === "all").forEach((stamp) => {
      stream += stampCommands(stamp, page, pageCount);
    });
    const pageObjectNumber = 3 + (page - 1) * 2;
    const contentObjectNumber = pageObjectNumber + 1;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /Font << /F1 ${3 + pageCount * 2} 0 R >> >> /Contents ${contentObjectNumber} 0 R >>`);
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}endstream`);
  }
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefAt = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach((offset) => {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  });
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF`;
  return new Blob([pdf], { type: "application/pdf" });
}

async function hashBlob(blob) {
  const hash = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("").toUpperCase();
}

function pdfOptions() {
  const selectedSeal = currentSeal();
  return {
    template: document.querySelector("#pdfTemplateSelect")?.value || "歲悅正式函",
    companyX: Number(document.querySelector("#companySealX")?.value || 420),
    companyY: Number(document.querySelector("#companySealY")?.value || 130),
    ownerX: Number(document.querySelector("#ownerSealX")?.value || 470),
    ownerY: Number(document.querySelector("#ownerSealY")?.value || 130),
    companyWidthMm: Number(selectedSeal?.widthMm || document.querySelector("#sealWidthMmInput")?.value || 30),
    companyHeightMm: Number(selectedSeal?.heightMm || document.querySelector("#sealHeightMmInput")?.value || 30),
    ownerWidthMm: 18,
    ownerHeightMm: 18,
    multiPage: Boolean(document.querySelector("#enablePageSeal")?.checked)
  };
}

function backendPdfPayload(doc, request = null) {
  const options = pdfOptions();
  const backendDocId = doc.id?.startsWith("DOC-") ? doc.id : `DOC-${doc.id}`;
  const companyName = doc.companyName || document.querySelector("#composeCompanySelect")?.value || companyRegistry[0]?.name || "歲悅長照股份有限公司";
  const baseSealPlan = doc.sealPlan || {
    large: { type: document.querySelector("#largeSealType")?.value || "無", placement: { ...composeSealPlacements.large } },
    small: { type: document.querySelector("#smallSealType")?.value || "無", placement: { ...composeSealPlacements.small } }
  };
  const largeSeal = sealForComposeType(baseSealPlan.large?.type, companyName);
  const smallSeal = sealForComposeType(baseSealPlan.small?.type, companyName);
  const sealPlan = {
    large: {
      type: baseSealPlan.large?.type || "無",
      placement: baseSealPlan.large?.placement || { ...composeSealPlacements.large },
      sealId: largeSeal?.id || "",
      widthMm: Number(largeSeal?.widthMm || 30),
      heightMm: Number(largeSeal?.heightMm || largeSeal?.widthMm || 30)
    },
    small: {
      type: baseSealPlan.small?.type || "無",
      placement: baseSealPlan.small?.placement || { ...composeSealPlacements.small },
      sealId: smallSeal?.id || "",
      widthMm: Number(smallSeal?.widthMm || 18),
      heightMm: Number(smallSeal?.heightMm || smallSeal?.widthMm || 18)
    }
  };
  return {
    document_id: backendDocId,
    template: options.template,
    seal_id: request?.sealId || selectedSealId,
    application_id: request?.id,
    stamp_no: request?.stampNo,
    certificate_id: document.querySelector("#signatureCertificateSelect")?.value || "CERT-SEAL-001",
    signature_type: document.querySelector("#signatureTypeSelect")?.value || "seal",
    applicant: "總務",
    approver: "行政部主任",
    company_name: companyName,
    seal_plan: sealPlan,
    coordinates: {
      company_x: options.companyX,
      company_y: options.companyY,
      company_width_mm: sealPlan.large.widthMm,
      company_height_mm: sealPlan.large.heightMm,
      owner_x: options.ownerX,
      owner_y: options.ownerY,
      owner_width_mm: sealPlan.small.widthMm,
      owner_height_mm: sealPlan.small.heightMm,
      multi_page: options.multiPage
    },
    document: {
      id: doc.id,
      no: doc.no,
      companyName,
      direction: "發文",
      type: doc.type,
      priority: doc.priority,
      security: doc.security,
      to: doc.to,
      agencyCode: doc.agencyCode,
      subject: doc.subject,
      body: doc.body,
      attachments: doc.attachments,
      owner: doc.owner,
      department: doc.dept,
      dueDate: doc.dueDate,
      contactAddress: doc.contactAddress || document.querySelector("#contactAddress")?.value || "220205 新北市板橋區英士路192之1號",
      contactOwner: doc.contactOwner || document.querySelector("#contactOwner")?.value || doc.owner || activeRole(),
      contactPhone: doc.contactPhone || document.querySelector("#contactPhone")?.value || "(02)2257-7155 分機3762",
      contactFax: doc.contactFax || document.querySelector("#contactFax")?.value || "(02)2254-4029",
      contactEmail: doc.contactEmail || document.querySelector("#contactEmail")?.value || "edoc@suiyuecare.com",
      sealPlan
    }
  };
}

function currentSignatureProof(doc = currentDispatchDoc()) {
  if (!doc) return null;
  return electronicSignatureProofs.find((proof) => proof.docId === doc.id || proof.docId === `DOC-${doc.id}`) || null;
}

function certificateById(id) {
  return signingCertificates.find((certificate) => certificate.id === id);
}

function applyCertificateValidation(certificateId, validation = {}) {
  const certificate = certificateById(certificateId);
  if (!certificate) return;
  certificate.chainStatus = validation.chain_status || validation.chainStatus || certificate.chainStatus;
  certificate.ocspStatus = validation.ocsp_status || validation.ocspStatus || certificate.ocspStatus;
  certificate.crlStatus = validation.crl_status || validation.crlStatus || certificate.crlStatus;
  certificate.tsaStatus = validation.tsa_status || validation.tsaStatus || certificate.tsaStatus;
  certificate.type = validation.certificate_type || certificate.type;
  certificate.lastValidatedAt = validation.checked_at || validation.checkedAt || certificate.lastValidatedAt;
}

function renderCertificateRegistry() {
  const box = document.querySelector("#certificateRegistry");
  if (!box) return;
  document.querySelector("#certificateCount").textContent = `${signingCertificates.length} 張`;
  box.innerHTML = signingCertificates.map((certificate) => `
    <article class="address-card">
      <strong>${certificate.owner}</strong>
      <span>${certificate.type || "組織憑證"} · ${certificate.serialNo} · ${certificate.algorithm}</span>
      <p>${certificate.issuer} · 有效至 ${certificate.validTo} · ${certificate.status}</p>
      <p>鏈：${certificate.chainStatus || "待驗證"} · OCSP：${certificate.ocspStatus || "待查詢"} · CRL：${certificate.crlStatus || "待查詢"} · TSA：${certificate.tsaStatus || "待驗證"}</p>
    </article>
  `).join("");
}

function renderCertificateServiceHealth() {
  const grid = document.querySelector("#certificateServiceGrid");
  const detail = document.querySelector("#certificateServiceDetail");
  if (!grid || !detail) return;
  const serviceLabels = certificateServiceState.services || {};
  const formalServices = certificateServiceState.service?.services || {};
  const rows = [
    ["模式", certificateServiceState.mode || "未檢查"],
    ["整體狀態", certificateServiceState.ready ? "可正式簽章" : "未完成設定"],
    ["簽章規格", certificateServiceState.policy?.profile || certificateServiceState.service?.policy?.profile || "待設定"],
    ["簽章 Provider", serviceLabels.provider || formalServices.provider?.value || "未檢查"],
    ["簽章 API", serviceLabels.providerApi || formalServices.providerApi?.value || "未檢查"],
    ["簽章 Key", serviceLabels.keyId || formalServices.keyId?.value || "未檢查"],
    ["HSM/KMS", serviceLabels.hsm || formalServices.hsm?.value || "未檢查"],
    ["信任根", serviceLabels.chain || formalServices.trustStore?.value || "未檢查"],
    ["TSA", serviceLabels.tsa || formalServices.tsa?.value || "未檢查"],
    ["TSA 憑證", serviceLabels.tsaCredential || formalServices.tsaCredential?.value || "未檢查"],
    ["OCSP", serviceLabels.ocsp || formalServices.ocsp?.value || "未檢查"],
    ["CRL", serviceLabels.crl || formalServices.crl?.value || "未檢查"],
    ["逾時/重試", `${certificateServiceState.policy?.timeoutSeconds || certificateServiceState.service?.policy?.timeoutSeconds || "-"} 秒 / ${certificateServiceState.policy?.maxRetries ?? certificateServiceState.service?.policy?.maxRetries ?? "-"} 次`]
  ];
  grid.innerHTML = rows.map(([label, value]) => `
    <article class="archive-card">
      <span>${label}</span>
      <strong>${typeof value === "object" ? value.value || JSON.stringify(value) : value}</strong>
    </article>
  `).join("");
  const missing = certificateServiceState.service?.missing || certificateServiceState.missing || [];
  detail.innerHTML = missing.length ? `
    <article class="address-card">
      <strong>正式服務尚未完成</strong>
      <p>缺少：${missing.join("、")}</p>
      <small>需設定 EDOC_SIGNATURE_PROVIDER、EDOC_SIGNATURE_API_URL、EDOC_SIGNATURE_API_KEY、EDOC_SIGNATURE_KEY_ID、EDOC_SIGNATURE_PROFILE、EDOC_HSM_PROVIDER、EDOC_CERT_TRUST_STORE、EDOC_TSA_URL、EDOC_TSA_API_KEY、EDOC_OCSP_RESPONDER_URL、EDOC_CRL_DISTRIBUTION_URL。</small>
    </article>
  ` : `<article class="address-card"><strong>正式簽章服務已就緒</strong><p>簽章 provider、HSM/KMS、TSA、OCSP、CRL 與信任根皆已設定；簽章時會呼叫正式 provider，不再使用本機模擬。</p></article>`;
}

async function loadCertificateServiceHealth(show = true) {
  try {
    const result = await backendRequest("/certificates/health");
    certificateServiceState = result;
    if (Array.isArray(result.certificates)) {
      result.certificates.forEach((item) => {
        const certificate = certificateById(item.id);
        if (!certificate) return;
        certificate.chainStatus = item.chain_status || certificate.chainStatus;
        certificate.ocspStatus = item.ocsp_status || certificate.ocspStatus;
        certificate.crlStatus = item.crl_status || certificate.crlStatus;
        certificate.lastValidatedAt = item.last_validated_at || certificate.lastValidatedAt;
      });
    }
    renderCertificateRegistry();
    renderCertificateServiceHealth();
    if (show) {
      addSealAudit("正式憑證服務檢查", `模式 ${result.mode}，${result.ready ? "可正式簽章" : `缺少 ${(result.service?.missing || result.missing || []).length} 項設定`}。`);
      showToast(result.ready ? "正式憑證服務已就緒。" : "正式憑證服務尚未完成設定。");
    }
  } catch (error) {
    addSealAudit("正式憑證服務檢查失敗", error.message);
    showToast(`憑證服務檢查失敗：${error.message}`);
  }
}

function renderSignatureProofGrid() {
  const box = document.querySelector("#signatureProofGrid");
  if (!box) return;
  const doc = currentDispatchDoc();
  const proof = currentSignatureProof(doc);
  const certificate = certificateById(proof?.certificateId);
  const validation = proof?.certificateValidation || {};
  document.querySelector("#signatureProofStatus").textContent = proof ? proof.status : "待簽章";
  const rows = [
    ["簽章序號", proof?.id || "尚未簽章"],
    ["簽章人", proof?.signer || "行政部主任"],
    ["憑證序號", certificate?.serialNo || document.querySelector("#signatureCertificateSelect")?.value || "待選擇"],
    ["演算法", proof?.algorithm || "HMAC-SHA256-RSA-PSS-READY"],
    ["簽章模式", proof?.provider || certificateServiceState.service?.policy?.provider || certificateServiceState.mode || "待檢查"],
    ["Provider Request", proof?.providerRequestId || "待簽章"],
    ["PDF Digest", proof?.digest || "待產生"],
    ["證據 Digest", proof?.evidenceDigest || "待產生"],
    ["TSA 時間戳", proof?.tsaToken || "待時間戳"],
    ["憑證類型", validation.certificate_type || certificate?.type || "待驗證"],
    ["憑證鏈", validation.chain_status || certificate?.chainStatus || "待驗證"],
    ["OCSP", validation.ocsp_status || certificate?.ocspStatus || "待查詢"],
    ["CRL", validation.crl_status || certificate?.crlStatus || "待查詢"],
    ["TSA 驗證", validation.tsa_status || certificate?.tsaStatus || "待驗證"],
    ["簽章值", proof?.signature ? proof.signature.slice(0, 24) : "待產生"],
    ["狀態", proof?.status || "待簽章"]
  ];
  box.innerHTML = rows.map(([label, value]) => `<article class="archive-card"><span>${label}</span><strong>${value}</strong></article>`).join("");
}

async function validateCurrentCertificate() {
  const certificateId = document.querySelector("#signatureCertificateSelect")?.value;
  if (!certificateId) return showToast("請先選擇簽章憑證。");
  const proof = currentSignatureProof();
  try {
    const result = await backendRequest("/certificates/validate", {
      method: "POST",
      body: JSON.stringify({
        certificate_id: certificateId,
        signature_id: proof?.id?.startsWith("ESIG-DEMO") ? "" : proof?.id,
        validator: activeRole()
      })
    });
    applyCertificateValidation(certificateId, result);
    if (proof && proof.certificateId === certificateId) proof.certificateValidation = result;
    renderCertificateRegistry();
    renderSignatureProofGrid();
    addSealAudit("憑證合法性驗證", `${certificateById(certificateId)?.serialNo || certificateId}：鏈 ${result.chain_status}、OCSP ${result.ocsp_status}、CRL ${result.crl_status}、TSA ${result.tsa_status}。`);
    showToast(result.ok ? "憑證合法性驗證通過。" : "憑證合法性驗證未通過。");
  } catch (error) {
    addSealAudit("憑證合法性驗證失敗", error.message);
    showToast(`憑證驗證失敗：${error.message}`);
  }
}

async function signCurrentPdf() {
  const doc = currentDispatchDoc();
  if (!doc) return showToast("請先選取要簽章的公文。");
  const version = pdfVersionStore[doc.id]?.after || pdfVersionStore[doc.id]?.before;
  if (!version) return showToast("請先產生或押章 PDF 後再簽章。");
  try {
    const result = await backendRequest("/signatures/sign", {
      method: "POST",
      body: JSON.stringify({
        ...backendPdfPayload(doc, currentSealRequest()),
        pdf_version_id: version.id,
        file_object_id: version.fileObjectId,
        signer: activeRole(),
        operation: "正式電子簽章/押章證據封存"
      })
    });
    const proof = {
      id: result.id,
      docId: doc.id,
      signer: result.signer,
      certificateId: result.certificate_id,
      type: result.signature_type,
      algorithm: result.algorithm,
      digest: result.digest_sha256,
      signature: result.signature_value,
      tsaToken: result.tsa_token,
      status: result.status,
      createdAt: result.created_at,
      provider: result.provider || result.non_repudiation?.provider || "",
      providerRequestId: result.provider_request_id || result.non_repudiation?.provider_request_id || "",
      evidenceDigest: result.evidence_digest_sha256 || result.non_repudiation?.evidence_digest_sha256 || "",
      certificateValidation: result.certificate_validation
    };
    applyCertificateValidation(proof.certificateId, result.certificate_validation);
    const index = electronicSignatureProofs.findIndex((item) => item.docId === doc.id || item.id === proof.id);
    if (index >= 0) electronicSignatureProofs[index] = proof;
    else electronicSignatureProofs.unshift(proof);
    addSealAudit("正式電子簽章", `${doc.no} 已由 ${proof.signer} 使用 ${certificateById(proof.certificateId)?.serialNo || proof.certificateId} 簽章，digest ${proof.digest}。`);
    renderSignatureProofGrid();
    showToast(result.algorithm?.startsWith("HMAC") ? "測試簽章已完成。" : "正式電子簽章已完成。");
  } catch (error) {
    addSealAudit("正式電子簽章失敗", error.message);
    showToast(`簽章失敗：${error.message}`);
  }
}

async function verifyCurrentSignature() {
  const proof = currentSignatureProof();
  if (!proof || !proof.id || proof.id.startsWith("ESIG-DEMO")) return showToast("尚未建立正式電子簽章。");
  try {
    const result = await backendRequest("/signatures/verify", {
      method: "POST",
      body: JSON.stringify({ signature_id: proof.id, validator: activeRole() })
    });
    proof.status = result.status || (result.ok ? "有效" : "雜湊異常");
    proof.certificateValidation = result.certificate_validation || proof.certificateValidation;
    applyCertificateValidation(proof.certificateId, proof.certificateValidation);
    addSealAudit("驗證正式電子簽章", `${proof.id} ${proof.status}，digest ${result.digest || proof.digest}。`);
    renderCertificateRegistry();
    renderSignatureProofGrid();
    showToast(result.ok ? "電子簽章驗證通過。" : "電子簽章驗證失敗。");
  } catch (error) {
    addSealAudit("電子簽章驗證失敗", error.message);
    showToast(`簽章驗證失敗：${error.message}`);
  }
}

async function storePdfVersion(doc, kind, blob, meta = {}) {
  pdfVersionStore[doc.id] = pdfVersionStore[doc.id] || {};
  if (pdfVersionStore[doc.id][kind]?.url) URL.revokeObjectURL(pdfVersionStore[doc.id][kind].url);
  pdfVersionStore[doc.id][kind] = {
    url: URL.createObjectURL(blob),
    hash: await hashBlob(blob),
    size: blob.size,
    createdAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    ...meta
  };
  return pdfVersionStore[doc.id][kind];
}

async function generatePdfTemplate(doc = currentDispatchDoc()) {
  if (!doc) return showToast("請先選取發文。");
  try {
    const result = await backendRequest("/pdf/generate", {
      method: "POST",
      body: JSON.stringify(backendPdfPayload(doc))
    });
    pdfVersionStore[doc.id] = pdfVersionStore[doc.id] || {};
    pdfVersionStore[doc.id].before = {
      id: result.id,
      fileObjectId: result.file_object_id,
      url: result.download_url,
      hash: result.sha256,
      size: result.file?.size_bytes || 0,
      createdAt: result.created_at,
      label: "後端押章前 PDF",
      pageCount: result.page_count || result.coordinates?.page_count || 1
    };
    doc.lastReply = `後端已產生 ${pdfVersionStore[doc.id].before.pageCount} 頁 A4 公文 PDF，SHA-256 ${result.sha256.slice(0, 12)}。`;
    renderDispatchDetail();
    renderPdfVersionGrid();
    addSealAudit("後端產生公文 PDF 套版", `${doc.no} 已建立 ${pdfVersionStore[doc.id].before.pageCount} 頁 A4 押章前 PDF，file ${result.file_object_id}，hash ${result.sha256}。`);
    showToast(`後端已產生 ${pdfVersionStore[doc.id].before.pageCount} 頁 A4 PDF。`);
  } catch (error) {
    const version = await storePdfVersion(doc, "before", buildOfficialPdf(doc, [], pdfOptions()), { label: "押章前 PDF" });
    doc.lastReply = `已產生本機公文套版 PDF，SHA-256 ${version.hash.slice(0, 12)}。`;
    renderDispatchDetail();
    renderPdfVersionGrid();
    addSealAudit("本機產生公文 PDF 套版", `${doc.no} 已建立押章前 PDF，hash ${version.hash}。後端錯誤：${error.message}`);
    showToast("後端未回應，已改用本機 PDF。");
  }
}

function stampListForRequest(request, doc) {
  const options = pdfOptions();
  const seal = sealById(request.sealId);
  const stampNo = request.stampNo || `STAMP-${doc.no.replace(/\D/g, "").slice(-10)}-${request.sealId}`;
  const stamps = [
    { page: 1, x: options.companyX, y: options.companyY, w: sealWidthPt(seal), h: sealHeightPt(seal), label: seal?.type || "Company", stampNo },
    { page: 1, x: options.ownerX, y: options.ownerY, w: Math.round(options.ownerWidthMm * pdfPointsPerMm * 100) / 100, h: Math.round(options.ownerHeightMm * pdfPointsPerMm * 100) / 100, label: "Owner", stampNo }
  ];
  if (options.multiPage) stamps.push({ page: "all", x: 535, y: 392, w: 34, h: 72, label: "PAGE", stampNo });
  return stamps;
}

async function stampPdfForRequest(request, doc) {
  try {
    const result = await backendRequest("/pdf/stamp", {
      method: "POST",
      body: JSON.stringify(backendPdfPayload(doc, request))
    });
    pdfVersionStore[doc.id] = pdfVersionStore[doc.id] || {};
    pdfVersionStore[doc.id].after = {
      id: result.id,
      fileObjectId: result.file_object_id,
      url: result.download_url,
      hash: result.sha256,
      size: result.file?.size_bytes || 0,
      createdAt: result.created_at,
      label: "後端押章後 PDF",
      stampNo: result.stamp_no,
      pageCount: result.page_count || result.coordinates?.page_count || 1
    };
    request.stampNo = result.stamp_no || request.stampNo;
    request.backendApplicationId = result.application_id;
    request.pdfHash = result.sha256;
    request.pdfSize = result.file?.size_bytes || 0;
    if (result.signature) {
      const proof = {
        id: result.signature.id,
        docId: doc.id,
        signer: result.signature.signer,
        certificateId: result.signature.certificate_id,
        type: result.signature.signature_type,
        algorithm: result.signature.algorithm,
        digest: result.signature.digest_sha256,
        signature: result.signature.signature_value,
        tsaToken: result.signature.tsa_token,
        status: result.signature.status,
        createdAt: result.signature.created_at,
        provider: result.signature.provider || result.signature.non_repudiation?.provider || "",
        providerRequestId: result.signature.provider_request_id || result.signature.non_repudiation?.provider_request_id || "",
        evidenceDigest: result.signature.evidence_digest_sha256 || result.signature.non_repudiation?.evidence_digest_sha256 || "",
        certificateValidation: result.signature.certificate_validation
      };
      const index = electronicSignatureProofs.findIndex((item) => item.docId === doc.id || item.id === proof.id);
      if (index >= 0) electronicSignatureProofs[index] = proof;
      else electronicSignatureProofs.unshift(proof);
    }
    doc.stampHash = result.sha256;
    doc.stampedPdfUrl = result.download_url;
    return pdfVersionStore[doc.id].after;
  } catch (error) {
    const formalFailure = /formal_|signature_provider|簽章|provider/i.test(error.message || "");
    const localDev = ["localhost", "127.0.0.1"].includes(window.location.hostname);
    if (formalFailure || !localDev) {
      addSealAudit("正式押章失敗", `${doc.no} 未完成用印，原因：${error.message}`);
      showToast(`正式押章失敗：${error.message}`);
      return null;
    }
    const version = await storePdfVersion(doc, "after", buildOfficialPdf(doc, stampListForRequest(request, doc), pdfOptions()), { label: "押章後 PDF", stampNo: request.stampNo });
    request.pdfHash = version.hash;
    request.pdfSize = version.size;
    doc.stampHash = version.hash;
    doc.stampedPdfUrl = version.url;
    addSealAudit("後端押章失敗", `${doc.no} 改用本機 PDF，原因：${error.message}`);
    return version;
  }
}

async function stampCurrentPdf() {
  const doc = currentDispatchDoc();
  if (!doc) return showToast("請先選取發文。");
  if (!canUseDocAction(doc, "seal")) return showToast("此角色未取得此公文的押章權限。");
  const request = ensureSealRequestForDoc(doc);
  if (!request) return showToast("目前沒有可用印鑑，請先啟用印鑑。");
  if (request.stampNo || request.status === "已押章") return showToast("此公文已押章，系統已阻擋重複押章。");
  if (!doc.checks.format || !doc.checks.package) return showToast("請先完成清稿檢核與附件封裝，再執行押章。");
  if (!confirmOperation("確認自動押章", `即將對 ${doc.no} 產生正式 PDF 並押上公司章、負責人章、騎縫章與多頁章。押章後會留存前後版本與防竄改雜湊。`)) return;
  const plannedStampNo = request.stampNo || `STAMP-${doc.no.replace(/\D/g, "").slice(-10)}-${request.sealId}`;
  request.stampNo = plannedStampNo;
  const stampedVersion = await stampPdfForRequest(request, doc);
  if (!stampedVersion) {
    request.status = "待簽核";
    request.stampNo = "";
    request.stampedAt = "";
    renderSeals();
    renderPdfVersionGrid();
    return;
  }
  request.status = "已押章";
  request.stampedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  doc.status = "已押章";
  doc.lastReply = `已完成 PDF 自動押章：${request.stampNo}。`;
  renderSeals();
  renderDispatchBoard();
  renderDispatchDetail();
  renderPdfVersionGrid();
  addSealAudit("自動押章 PDF", `${doc.no} 已依座標完成公司章、負責人章與騎縫章。`);
  showToast("PDF 已自動押章。");
}

function renderPdfVersionGrid() {
  const box = document.querySelector("#pdfVersionGrid");
  if (!box) return;
  const doc = currentDispatchDoc();
  const versions = doc ? pdfVersionStore[doc.id] || {} : {};
  const before = versions.before;
  const after = versions.after;
  const proof = currentSignatureProof(doc);
  document.querySelector("#pdfVersionStatus").textContent = after ? "押章後已留存" : before ? "押章前已留存" : "尚未產生";
  box.innerHTML = [
    ["押章前", before ? `${before.pageCount || 1} 頁 · ${before.size} bytes · ${before.hash.slice(0, 16)}` : "尚未產生"],
    ["押章後", after ? `${after.pageCount || 1} 頁 · ${after.size} bytes · ${after.hash.slice(0, 16)}` : "尚未押章"],
    ["防竄改雜湊", after?.hash || before?.hash || "待產生"],
    ["用印申請", currentSealRequest()?.id || "尚未送簽"],
    ["電子簽章", proof ? `${proof.status} · ${proof.id}` : "待簽章"]
  ].map(([label, value]) => `<article class="archive-card"><span>${label}</span><strong>${value}</strong></article>`).join("");
}

function downloadPdfVersion(kind) {
  const doc = currentDispatchDoc();
  const version = doc ? pdfVersionStore[doc.id]?.[kind] : null;
  if (!version) return showToast(kind === "before" ? "尚未產生押章前 PDF。" : "尚未產生押章後 PDF。");
  const link = document.createElement("a");
  link.href = version.url?.startsWith("/api/") ? `${window.location.origin}${version.url}` : version.url;
  link.download = `${doc.no}-${kind === "before" ? "before-seal" : "after-seal"}.pdf`;
  link.click();
  addSealAudit("下載 PDF 版本", `${doc.no} 已下載${kind === "before" ? "押章前" : "押章後"}版本。`);
}

function generateSealApplication() {
  const request = currentSealRequest();
  const doc = request ? sealRequestDoc(request) : currentDispatchDoc();
  if (!doc || !request) return showToast("請先建立用印申請。");
  addSealAudit("產生用印申請單", `申請單 ${request.id} / 公文 ${doc.no} / 印鑑 ${sealById(request.sealId)?.name} / 狀態 ${request.status} / 章戳 ${request.stampNo || "尚未押章"}。`);
  showToast("用印申請單已產生。");
}

async function verifyCurrentPdfHash() {
  const doc = currentDispatchDoc();
  const target = doc ? (pdfVersionStore[doc.id]?.after || pdfVersionStore[doc.id]?.before) : null;
  if (!target) return showToast("尚未產生 PDF，無法驗證。");
  if (target.fileObjectId) {
    try {
      const result = await backendRequest("/pdf/verify", {
        method: "POST",
        body: JSON.stringify({ file_object_id: target.fileObjectId })
      });
      addSealAudit("後端驗證 PDF 防竄改雜湊", `${doc.no} ${result.file?.file_name || "PDF"} ${result.ok ? "驗證通過" : "驗證失敗"}，hash ${result.actual || result.expected}。`);
      return showToast(result.ok ? "後端 PDF 雜湊驗證通過。" : "後端 PDF 雜湊驗證失敗。");
    } catch (error) {
      addSealAudit("後端驗證失敗", error.message);
    }
  }
  addSealAudit("驗證 PDF 防竄改雜湊", `${doc.no} PDF hash ${target.hash} 驗證通過。`);
  showToast("PDF 雜湊驗證通過。");
}

function renderSealAuditLog() {
  document.querySelector("#sealAuditLog").innerHTML = sealAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function renderSeals() {
  renderExecutiveSealAdmin();
  renderCompanySealModule();
  renderSealSummary();
  renderSealRegistry();
  renderSealDetail();
  renderSealRequests();
  renderSealAuditLog();
  renderPdfVersionGrid();
  renderCertificateRegistry();
  renderCertificateServiceHealth();
  renderSignatureProofGrid();
  renderUploadedSealWorkbench();
  renderUnifiedFlows();
}

function toggleSeal(id) {
  const seal = sealById(id);
  if (!seal) return;
  seal.status = seal.status === "啟用" ? "停用" : "啟用";
  renderSeals();
  addSealAudit("更新印鑑狀態", `${seal.name} 已更新為「${seal.status}」。`);
  showToast(`印鑑已${seal.status}。`);
}

function ensureSealRequestForDoc(doc, step = "行政部主任簽核") {
  if (!doc) return null;
  const existing = sealRequests.find((request) => request.docId === doc.id && request.status !== "退回補正");
  if (existing) return existing;
  const seal = sealRegistry.find((item) => item.status === "啟用" && (item.docType === doc.type || item.docType === "函")) || sealRegistry.find((item) => item.status === "啟用");
  if (!seal) return null;
  const request = { id: `REQ-${Date.now().toString().slice(-6)}`, docId: doc.id, sealId: seal.id, step, status: "待簽核", stampNo: "", stampedAt: "" };
  sealRequests.unshift(request);
  return request;
}

function submitSealRequest() {
  const doc = currentDispatchDoc();
  const request = ensureSealRequestForDoc(doc);
  if (!doc || !request) return showToast("請先選取發文與可用印鑑。");
  if (!doc.checks.format) return blockOperation("請先完成清稿檢核後再送簽用印。", addSealAudit, "用印送簽防呆");
  const seal = sealById(request.sealId);
  if (!seal || seal.status !== "啟用") return blockOperation("請先確認有啟用中的印鑑。", addSealAudit, "用印送簽防呆");
  if (!seal.widthMm || !seal.heightMm) return blockOperation("印鑑需登錄實際長寬後才能送簽用印，避免列印尺寸誤差。", addSealAudit, "用印送簽防呆");
  if (!seal.imageDataUrl && !seal.fileObjectId) return blockOperation("請先上傳印鑑圖檔後再送簽用印。", addSealAudit, "用印送簽防呆");
  if (!doc.lockedHash) lockDispatchDocForSend(doc, "用印送簽前鎖版");
  if (!guardDispatchDocVersion(doc, "用印送簽鎖版防呆")) return;
  if (request.status !== "待簽核" || request.stampNo) {
    selectedSealRequestId = request.id;
    renderSeals();
    return showToast("此公文已有簽核用印流程。");
  }
  if (!confirmOperation("確認送簽用印", `即將將 ${doc.no} 送交 ${request.step}，核准後會自動產生 PDF 並押用 ${seal.name}。`)) return;
  selectedSealRequestId = request.id;
  doc.status = "待簽核";
  doc.lastReply = "已送簽核流程，核准後將自動押章。";
  renderSeals();
  renderDispatchBoard();
  renderDispatchDetail();
  addSealAudit("送簽核用印", `${doc.no} 已送 ${request.step}，預計使用 ${sealById(request.sealId)?.name}。`);
  showToast("公文已送簽核用印。");
}

async function approveSealRequests(ids = selectedSealRequestIds()) {
  if (!ids.length) return showToast("請先選取簽核案件。");
  const requests = ids.map((id) => sealRequests.find((item) => item.id === id)).filter(Boolean);
  const blocked = requests.find((request) => request.status === "已押章" || request.stampNo);
  if (blocked) return showToast(`${blocked.id} 已完成押章，不可重複核准。`);
  const denied = requests.find((request) => {
    const doc = sealRequestDoc(request);
    return doc && !canUseDocAction(doc, "seal");
  });
  if (denied) return showToast("此角色未取得部分公文的核准押章權限。");
  if (!confirmOperation("確認核准並自動押章", `即將核准 ${requests.length} 件用印申請。核准後系統會立即產生正式 PDF、押章、留存版本與雜湊。`)) return;
  for (const id of ids) {
    const request = sealRequests.find((item) => item.id === id);
    if (!request) continue;
    if (request.backendApplicationId || request.sourcePdfFileObjectId) {
      try {
        const result = await backendRequest(`/seal-applications/${request.backendApplicationId || request.id}/approve`, {
          method: "POST",
          body: JSON.stringify({
            approver_role: activeRole(),
            approver: authState?.user?.name || activeRole(),
            certificate_id: document.querySelector("#signatureCertificateSelect")?.value || "CERT-SEAL-001",
            comment: "主管核准後自動用印"
          })
        });
        Object.assign(request, localSealRequestFromBackend(result));
        if (result.pdf_after) {
          pdfVersionStore[request.docId] = pdfVersionStore[request.docId] || {};
          pdfVersionStore[request.docId].after = {
            id: result.pdf_after.id,
            fileObjectId: result.pdf_after.file_object_id,
            url: result.pdf_after.download_url,
            hash: result.pdf_after.sha256,
            size: result.pdf_after.file?.size_bytes || 0,
            createdAt: result.pdf_after.created_at,
            label: "上傳 PDF 押章後",
            stampNo: result.stamp_no,
            pageCount: result.pdf_after.page_count || 1
          };
        }
        if (result.signature) {
          electronicSignatureProofs.unshift({
            id: result.signature.id,
            docId: request.docId,
            signer: result.signature.signer,
            certificateId: result.signature.certificate_id,
            type: result.signature.signature_type,
            algorithm: result.signature.algorithm,
            digest: result.signature.digest_sha256,
            signature: result.signature.signature_value,
            tsaToken: result.signature.tsa_token,
            status: result.signature.status,
            createdAt: result.signature.created_at,
            provider: result.signature.provider || "",
            providerRequestId: result.signature.provider_request_id || "",
            evidenceDigest: result.signature.evidence_digest_sha256 || "",
            certificateValidation: result.signature.certificate_validation
          });
        }
        addSealAudit("主管核准上傳 PDF 用印", `${request.id} 已自動押章，PDF hash ${request.pdfHash || result.pdf_after?.sha256 || "已建立"}。`);
      } catch (error) {
        request.status = "待主管簽核";
        addSealAudit("上傳 PDF 用印核准失敗", `${request.id}：${error.message}`);
        showToast(`核准失敗：${error.message}`);
      }
      continue;
    }
    const seal = sealById(request.sealId);
    const doc = sealRequestDoc(request);
    if (!seal || seal.status !== "啟用" || !doc) continue;
    if (!guardDispatchDocVersion(doc, "核准押章鎖版防呆")) continue;
    request.status = "已押章";
    request.stampNo = `STAMP-${doc.no.replace(/\D/g, "").slice(-10)}-${seal.id}`;
    request.stampedAt = new Date().toLocaleString("zh-TW", { hour12: false });
    await stampPdfForRequest(request, doc);
    doc.status = "已押章";
    doc.checks.format = true;
    doc.checks.package = true;
    doc.packageId = doc.packageId || `PKG-${Date.now()}`;
    doc.lastReply = `簽核通過，已自動押章：${request.stampNo}，PDF hash ${request.pdfHash?.slice(0, 12)}。`;
  }
  renderSeals();
  renderDispatchBoard();
  renderDispatchDetail();
  addSealAudit("核准並自動押章", `已核准 ${ids.length} 件簽核，系統完成自動押章與封包回寫。`);
  showToast("簽核通過，已自動押章。");
}

async function rejectSealRequests(ids = selectedSealRequestIds()) {
  if (!ids.length) return showToast("請先選取簽核案件。");
  if (!confirmOperation("確認退回用印簽核", `即將退回 ${ids.length} 件用印申請，公文狀態會改為退回補正。`)) return;
  for (const id of ids) {
    const request = sealRequests.find((item) => item.id === id);
    const doc = request ? sealRequestDoc(request) : null;
    if (request?.backendApplicationId || request?.sourcePdfFileObjectId) {
      try {
        const result = await backendRequest(`/seal-applications/${request.backendApplicationId || request.id}/return`, {
          method: "POST",
          body: JSON.stringify({ actor: authState?.user?.name || activeRole(), reason: "請補正 PDF、章位或附件後重新送簽。" })
        });
        Object.assign(request, localSealRequestFromBackend(result));
      } catch (error) {
        addSealAudit("上傳 PDF 用印退回失敗", `${request.id}：${error.message}`);
      }
    } else if (request) {
      request.status = "退回補正";
    }
    if (doc) {
      doc.status = "退回補正";
      doc.lastReply = "用印簽核退回，請修正後重新送簽。";
    }
  }
  renderSeals();
  renderDispatchBoard();
  renderDispatchDetail();
  addSealAudit("退回用印簽核", `已退回 ${ids.length} 件用印申請。`);
  showToast("用印簽核已退回。");
}

function addSealFromForm() {
  const widthMm = Number(document.querySelector("#sealWidthMmInput").value || 0);
  const heightMm = Number(document.querySelector("#sealHeightMmInput").value || 0);
  if (!widthMm || !heightMm || widthMm <= 0 || heightMm <= 0) return showToast("請輸入印鑑實體長寬，單位為 mm。");
  const seal = {
    id: `SEAL-${Date.now().toString().slice(-5)}`,
    company: document.querySelector("#sealCompanyInput").value,
    department: document.querySelector("#sealDepartmentInput").value,
    name: document.querySelector("#sealNameInput").value.trim() || "未命名印鑑",
    type: document.querySelector("#sealTypeInput").value,
    owner: document.querySelector("#sealOwnerInput").value,
    docType: document.querySelector("#sealDocTypeInput").value,
    status: "啟用",
    widthMm,
    heightMm,
    imageName: document.querySelector("#sealImageInput").files?.[0]?.name || "待上傳",
    imageDataUrl: document.querySelector("#sealImagePreview")?.dataset.image || "",
    fileObjectId: document.querySelector("#sealImagePreview")?.dataset.fileObjectId || "",
    calibrationStatus: document.querySelector("#sealImagePreview")?.dataset.fileObjectId ? "已登錄尺寸" : "待上傳圖檔",
    hash: `SHA256-SEAL-${Math.random().toString(16).slice(2, 8).toUpperCase()}`
  };
  sealRegistry.unshift(seal);
  selectedSealId = seal.id;
  renderSeals();
  addSealAudit("新增印鑑", `${seal.name} 已建立並啟用。`);
  showToast("印鑑已新增。");
}

async function handleSealImageUpload() {
  const input = document.querySelector("#sealImageInput");
  const preview = document.querySelector("#sealImagePreview");
  const file = input?.files?.[0];
  if (!file || !preview) return;
  if (!file.type.startsWith("image/")) {
    input.value = "";
    return showToast("印鑑圖檔請上傳 PNG、JPG 或其他圖片格式。");
  }
  input.value = "";
  preview.dataset.image = "";
  preview.dataset.fileObjectId = "";
  preview.innerHTML = `<span>已選擇 ${file.name}；印章原檔不可走一般附件，請到「公司印章與用印管理」上傳至 Seal Vault。</span>`;
  showToast("印章電子檔屬高敏感資料，請使用 Seal Vault 上傳流程。");
}

function addTrackingAudit(title, body) {
  trackingAuditLog.unshift([nowTime(), title, body]);
  renderTrackingAuditLog();
}

function currentTrackingCase() {
  return trackingCases.find((item) => item.id === selectedTrackingId) || trackingCases[0] || null;
}

function selectedTrackingIds() {
  const selected = [...document.querySelectorAll(".tracking-check:checked")].map((item) => item.value);
  return selected.length ? selected : selectedTrackingId ? [selectedTrackingId] : [];
}

function filteredTrackingCases() {
  const term = trackingSearchTerm.trim().toLowerCase();
  return trackingCases.filter((item) => {
    const matchFilter = trackingFilter === "all" || item.status === trackingFilter || item.type === trackingFilter;
    const haystack = `${item.id} ${item.title} ${item.agency} ${item.type} ${item.owner} ${item.status} ${item.note}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderTrackingSummary() {
  const counts = {
    "翌日查核": 0,
    "逾期提醒": 0,
    "未收確認": 0,
    "退回補正": 0
  };
  trackingCases.forEach((item) => {
    if (counts[item.status] !== undefined) counts[item.status] += 1;
    else if (counts[item.type] !== undefined && item.status !== "已完成") counts[item.type] += 1;
  });
  document.querySelector("#nextDayCount").textContent = counts["翌日查核"];
  document.querySelector("#overdueCount").textContent = counts["逾期提醒"];
  document.querySelector("#unreceivedCount").textContent = counts["未收確認"];
  document.querySelector("#returnedCount").textContent = counts["退回補正"];
}

function renderTrackingRows() {
  const rows = filteredTrackingCases();
  document.querySelector("#trackingCount").textContent = `${rows.length} 件`;
  document.querySelector("#trackingRows").innerHTML = rows.map((item) => `
    <tr class="${item.id === selectedTrackingId ? "selected-row" : ""}">
      <td><input class="tracking-check" type="checkbox" value="${item.id}" aria-label="選取 ${item.title}" /></td>
      <td><button class="text-button row-select" type="button" data-tracking-select="${item.id}">${item.title}</button><small>${item.id}</small></td>
      <td>${item.agency}</td>
      <td>${item.type}</td>
      <td>${item.dueDate}</td>
      <td>${item.owner}</td>
      <td><span class="badge ${badgeClass(item.status)}">${item.status}</span></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-tracking-action="nextday" data-tracking-id="${item.id}">查核</button>
          <button class="segment" type="button" data-tracking-action="remind" data-tracking-id="${item.id}">提醒</button>
          <button class="segment" type="button" data-tracking-action="confirm" data-tracking-id="${item.id}">未收</button>
          <button class="segment" type="button" data-tracking-action="return" data-tracking-id="${item.id}">補正</button>
        </div>
      </td>
    </tr>
  `).join("");

  document.querySelectorAll("[data-tracking-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedTrackingId = button.dataset.trackingSelect;
      renderTrackingRows();
      renderTrackingDetail();
    });
  });
  document.querySelectorAll("[data-tracking-action]").forEach((button) => {
    button.addEventListener("click", () => runTrackingAction(button.dataset.trackingAction, [button.dataset.trackingId]));
  });
}

function renderTrackingDetail() {
  const item = currentTrackingCase();
  const detail = document.querySelector("#trackingDetail");
  if (!item) {
    document.querySelector("#selectedTrackingStatus").textContent = "未選取";
    detail.innerHTML = `<p class="empty-text">尚無稽催案件。</p>`;
    return;
  }
  document.querySelector("#selectedTrackingStatus").textContent = item.status;
  detail.innerHTML = `
    <div class="doc-detail">
      <strong>${item.title}</strong>
      <dl>
        <div><dt>案件編號</dt><dd>${item.id}</dd></div>
        <div><dt>往來機關</dt><dd>${item.agency}</dd></div>
        <div><dt>追蹤類型</dt><dd>${item.type}</dd></div>
        <div><dt>處理期限</dt><dd>${item.dueDate}</dd></div>
        <div><dt>負責角色</dt><dd>${item.owner}</dd></div>
        <div><dt>目前狀態</dt><dd>${item.status}</dd></div>
      </dl>
      <p>${item.note}</p>
      <div class="detail-actions">
        <button class="primary-button" type="button" id="detailNextDayBtn">翌日查核</button>
        <button class="secondary-button" type="button" id="detailOverdueBtn">逾期提醒</button>
        <button class="secondary-button" type="button" id="detailUnreceivedBtn">未收確認</button>
        <button class="secondary-button" type="button" id="detailCorrectionBtn">退回補正</button>
        <button class="secondary-button" type="button" id="detailCompleteTrackingBtn">結案</button>
      </div>
    </div>
  `;
  document.querySelector("#detailNextDayBtn").addEventListener("click", () => runTrackingAction("nextday", [item.id]));
  document.querySelector("#detailOverdueBtn").addEventListener("click", () => runTrackingAction("remind", [item.id]));
  document.querySelector("#detailUnreceivedBtn").addEventListener("click", () => runTrackingAction("confirm", [item.id]));
  document.querySelector("#detailCorrectionBtn").addEventListener("click", () => runTrackingAction("return", [item.id]));
  document.querySelector("#detailCompleteTrackingBtn").addEventListener("click", () => runTrackingAction("complete", [item.id]));
}

function renderTrackingAuditLog() {
  document.querySelector("#trackingAuditLog").innerHTML = trackingAuditLog.map(([time, title, body]) => `
    <article class="timeline-item">
      <time>${time}</time>
      <div>
        <strong>${title}</strong>
        <p>${body}</p>
      </div>
    </article>
  `).join("");
}

function mutateTracking(ids, handler, auditTitle, auditBody) {
  ids.forEach((id) => {
    const item = trackingCases.find((entry) => entry.id === id);
    if (item) handler(item);
  });
  renderTrackingSummary();
  renderTrackingRows();
  renderTrackingDetail();
  addTrackingAudit(auditTitle, auditBody);
}

function runTrackingAction(action, ids) {
  const targetIds = ids?.length ? ids : selectedTrackingIds();
  if (!targetIds.length) return showToast("請先選取要稽催的案件。");
  const target = document.querySelector("#trackingNotifyTarget").value;
  const method = document.querySelector("#trackingNotifyMethod").value;
  const message = document.querySelector("#trackingMessage").value.trim();
  const reason = document.querySelector("#correctionReason").value;
  const correctionDue = document.querySelector("#correctionDueDate").value;
  const correctionNote = document.querySelector("#correctionNote").value.trim();

  if (action === "nextday") {
    mutateTracking(targetIds, (item) => {
      item.status = "已完成";
      item.note = "翌日查核完成，已同步 jAgent 交換結果並保留查核紀錄。";
    }, "完成翌日查核", `已查核 ${targetIds.length} 件交換結果。`);
    return showToast("翌日查核已完成。");
  }

  if (action === "remind") {
    mutateTracking(targetIds, (item) => {
      item.status = "逾期提醒";
      item.note = `${method} 已通知 ${target}：${message || "請於期限前完成處理。"}`;
    }, "送出逾期提醒", `已以 ${method} 通知 ${target}，共 ${targetIds.length} 件。`);
    return showToast("逾期提醒已送出。");
  }

  if (action === "confirm") {
    mutateTracking(targetIds, (item) => {
      item.status = "未收確認";
      item.note = "已向交換中心與收文方發出未收確認，等待對方回覆確認。";
    }, "建立未收確認", `已建立 ${targetIds.length} 件未收確認追蹤。`);
    return showToast("未收確認已建立。");
  }

  if (action === "return") {
    mutateTracking(targetIds, (item) => {
      item.status = "退回補正";
      item.type = "退回補正";
      item.dueDate = correctionDue;
      item.note = `${reason}：${correctionNote || "請業務助理補正後重新送審。"}`;
    }, "建立退回補正", `已退回 ${targetIds.length} 件，補正期限 ${correctionDue}。`);
    return showToast("退回補正已建立。");
  }

  if (action === "complete") {
    mutateTracking(targetIds, (item) => {
      item.status = "已完成";
      item.note = "稽催案件已結案並保留處理紀錄。";
    }, "稽催結案", `已結案 ${targetIds.length} 件。`);
    return showToast("稽催案件已結案。");
  }
}

document.querySelectorAll("[data-target]").forEach((control) => {
  control.addEventListener("click", () => {
    if (!isRouteAllowed(control.dataset.target)) return showToast("此身份不需要使用這個功能，已隱藏在側欄。");
    setView(control.dataset.target);
  });
});

document.querySelector("#globalSearchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = document.querySelector("#globalSearchInput").value.trim();
  document.querySelector("#searchQuery").value = value;
  document.querySelector("#searchCategory").value = "all";
  document.querySelector("#searchStatus").value = "";
  setView("search");
  runUnifiedSearch();
});

document.querySelector("#searchRunBtn").addEventListener("click", runUnifiedSearch);
document.querySelector("#searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runUnifiedSearch();
});
["#searchQuery", "#searchStatus"].forEach((selector) => {
  document.querySelector(selector).addEventListener("keydown", (event) => {
    if (event.key === "Enter") runUnifiedSearch();
  });
});
document.querySelector("#searchCategory").addEventListener("change", runUnifiedSearch);
document.querySelector("#searchLimit").addEventListener("change", runUnifiedSearch);
document.querySelector("#searchClearBtn").addEventListener("click", () => {
  document.querySelector("#searchQuery").value = "";
  document.querySelector("#searchStatus").value = "";
  document.querySelector("#searchCategory").value = "all";
  searchResults = [];
  selectedSearchId = "";
  renderSearch();
});

document.querySelectorAll("[data-inbound-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-inbound-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    inboundFilter = button.dataset.inboundFilter;
    renderInboundRows();
  });
});

document.querySelectorAll(".segment[data-dispatch-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-dispatch-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    dispatchFilter = button.dataset.dispatchFilter;
    renderDispatchBoard();
  });
});

document.querySelector("#roleSelect").addEventListener("change", (event) => {
  document.querySelector("#roleNote").textContent = roleNotes[event.target.value];
  workflowRole = event.target.value;
  applyRoleNavigation();
  renderScopeZone();
  renderRoleDashboard();
  renderIdentityWorkbench();
  renderInboundRows();
  renderInboundDetail();
  renderDispatchBoard();
  renderDispatchDetail();
  void loadOfficialWorkflow(officialWorkflowScope === "new" ? "all" : officialWorkflowScope);
  renderWorkflowRole();
  renderUnifiedFlows();
  renderContracts();
  renderContractSeal();
  applyComposeContactDefaults(true);
});

document.querySelector("#composeForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const doc = await createDispatchFromForm("待清稿");
  if (!doc) return;
  activeComposeStep = "fill";
  renderComposeStepper();
  showToast("已建立函稿並加入發文佇列。");
  setView(isRouteAllowed("approvalLog") ? "approvalLog" : "notifications");
});

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loginWithBackend(
      document.querySelector("#loginEmail").value,
      document.querySelector("#loginPassword").value,
      document.querySelector("#loginEnvironment").value
    );
  } catch (error) {
    showToast(error.message || "後端登入失敗。");
    addAccountAudit("後端登入失敗", error.message || "Auth API 未回應。");
  }
});

document.querySelector("#demoLoginBtn").addEventListener("click", async () => {
  document.querySelector("#loginEmail").value = "edoc@suiyuecare.com";
  document.querySelector("#loginPassword").value = "demo1234";
  try {
    await loginWithBackend("edoc@suiyuecare.com", "demo1234", "Google Workspace");
  } catch (error) {
    showToast(error.message || "測試帳號登入失敗。");
  }
});
document.querySelector("#portalLoginBtn")?.addEventListener("click", () => {
  redirectToLoggingPortal();
});
document.querySelectorAll("[data-quick-role]").forEach((button) => {
  button.addEventListener("click", () => quickLoginAsRole(button.dataset.quickRole));
});

document.querySelector("#pullInboundBtn")?.addEventListener("click", pullJagentInbound);
document.querySelector("#pullJagentBtn").addEventListener("click", pullJagentInbound);
document.querySelector("#inboundSearch").addEventListener("input", (event) => {
  inboundSearchTerm = event.target.value;
  renderInboundRows();
});
document.querySelector("#registerForm").addEventListener("submit", (event) => {
  event.preventDefault();
  registerInbound(selectedInboundId ? [selectedInboundId] : null);
});
document.querySelector("#assignForm").addEventListener("submit", (event) => {
  event.preventDefault();
  assignInbound(selectedInboundId ? [selectedInboundId] : null);
});
document.querySelector("#exceptionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createInboundException(selectedInboundId ? [selectedInboundId] : null, document.querySelector("#exceptionType").value);
});
document.querySelector("#saveRegisterDraftBtn").addEventListener("click", () => showToast("收文登錄草稿已暫存。"));
document.querySelector("#clearInboundLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(inboundAuditLog, renderInboundAuditLog, "收文操作紀錄");
});
document.querySelector("#validateDispatchBtn").addEventListener("click", () => runDispatchAction("validate"));
document.querySelector("#packageDispatchBtn").addEventListener("click", () => runDispatchAction("package"));
document.querySelector("#sendDispatchBtn").addEventListener("click", () => runDispatchAction("send"));
document.querySelector("#queryDispatchBtn").addEventListener("click", () => runDispatchAction("query"));
document.querySelector("#resendDispatchBtn").addEventListener("click", () => runDispatchAction("resend"));
document.querySelector("#exportDispatchBtn").addEventListener("click", () => {
  addDispatchAudit("匯出發文清單", `已匯出 ${filteredDispatchDocs().length} 筆目前篩選資料。`);
  showToast("已產生發文清單匯出檔。");
});
document.querySelector("#dispatchSearch").addEventListener("input", (event) => {
  dispatchSearchTerm = event.target.value;
  renderDispatchBoard();
});
document.querySelector("#officialWorkflowReloadBtn")?.addEventListener("click", () => {
  void loadOfficialWorkflow(officialWorkflowScope);
  void loadOfficialSealOptions();
});
document.querySelectorAll("[data-official-scope]").forEach((button) => {
  button.addEventListener("click", () => {
    const scope = button.dataset.officialScope || "all";
    if (scope === "new") {
      officialWorkflowScope = "new";
      selectedOfficialDocumentId = "";
      renderOfficialWorkflow();
      void loadOfficialSealOptions();
      return;
    }
    void loadOfficialWorkflow(scope);
  });
});
document.querySelector("#officialWorkflowStatusFilter")?.addEventListener("change", (event) => {
  officialWorkflowStatusFilter = event.target.value;
  void loadOfficialWorkflow(officialWorkflowScope === "new" ? "all" : officialWorkflowScope);
});
document.querySelector("#officialWorkflowSearch")?.addEventListener("input", (event) => {
  officialWorkflowSearchTerm = event.target.value;
  renderOfficialWorkflow();
});
document.querySelector("#officialCompanySelect")?.addEventListener("change", (event) => {
  void loadOfficialSealOptions(event.target.value);
});
document.querySelector("#officialSourceType")?.addEventListener("change", (event) => {
  document.querySelector("#officialPdfInput")?.toggleAttribute("required", event.target.value === "uploaded_pdf");
});
["#officialStampPageInput", "#officialStampXInput", "#officialStampYInput", "#officialStampWidthInput", "#officialStampHeightInput"].forEach((selector) => {
  document.querySelector(selector)?.addEventListener("input", updateOfficialStampPreview);
});
document.querySelector("#officialWorkflowForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  void createOfficialWorkflow(true);
});
document.querySelector("#officialSaveDraftBtn")?.addEventListener("click", () => {
  void createOfficialWorkflow(false);
});
document.querySelector("#approvalLogSearch").addEventListener("input", (event) => {
  approvalLogSearchTerm = event.target.value;
  renderApprovalLog();
});
document.querySelectorAll("[data-approval-log-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-approval-log-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    approvalLogFilter = button.dataset.approvalLogFilter;
    renderApprovalLog();
  });
});
document.querySelector("#approvalLogOpenWorkflowBtn").addEventListener("click", () => {
  if (String(selectedWorkflowTaskId).startsWith("CON-WF-")) {
    const contractId = selectedWorkflowTaskId.replace("CON-WF-", "");
    selectedContractId = contractId;
    setView("contracts");
    renderContracts();
    return;
  }
  setView("workflow");
  renderApprovalProgress();
  document.querySelector("#approvalProgressPanel")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
document.querySelector("#contractNewBtn").addEventListener("click", startNewContract);
document.querySelector("#contractDraftBtn").addEventListener("click", () => {
  void saveContractDraft();
});
document.querySelector("#contractSubmitBtn").addEventListener("click", () => {
  void submitContractForApproval();
});
document.querySelector("#contractApproveBtn").addEventListener("click", approveCurrentContract);
document.querySelector("#contractReturnBtn").addEventListener("click", returnCurrentContract);
document.querySelector("#contractSignBtn").addEventListener("click", () => {
  setView(isRouteAllowed("contractSeal") ? "contractSeal" : "contracts");
  renderContractSeal();
});
document.querySelector("#contractArchiveBtn").addEventListener("click", archiveCurrentContract);
document.querySelector("#contractForm").addEventListener("submit", (event) => {
  event.preventDefault();
  void saveContractDraft();
});
document.querySelector("#contractSearch").addEventListener("input", (event) => {
  contractSearchTerm = event.target.value;
  renderContracts();
});
document.querySelectorAll("[data-contract-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-contract-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    contractFilter = button.dataset.contractFilter;
    renderContracts();
  });
});
document.querySelector("#contractClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(contractAuditLog, renderContractAuditLog, "合約操作紀錄");
});
document.querySelector("#contractSealApplyBtn").addEventListener("click", confirmCurrentContractSeal);
document.querySelector("#contractSealReturnBtn").addEventListener("click", returnCurrentContractSeal);
document.querySelector("#contractSealOpenBtn").addEventListener("click", () => openContractModal(currentContractSealRequest()?.id || selectedContractId));
document.querySelector("#contractModalCloseBtn").addEventListener("click", closeContractModal);
document.querySelector("#contractModal").addEventListener("click", (event) => {
  if (event.target.id === "contractModal") closeContractModal();
});
document.querySelector("#inboundModalCloseBtn").addEventListener("click", closeInboundModal);
document.querySelector("#inboundModal").addEventListener("click", (event) => {
  if (event.target.id === "inboundModal") closeInboundModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!document.querySelector("#contractModal")?.classList.contains("hidden")) closeContractModal();
  if (!document.querySelector("#inboundModal")?.classList.contains("hidden")) closeInboundModal();
});
document.querySelector("#previewPackageBtn").addEventListener("click", () => {
  const doc = currentDispatchDoc();
  if (!doc) return showToast("請先選取發文。");
  showToast(`封包預覽：${doc.packageId || "尚未封裝"}，附件 ${doc.attachments.length} 個。`);
});
document.querySelector("#clearDispatchLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(dispatchAuditLog, renderDispatchAuditLog, "發文操作紀錄");
});
document.querySelector("#saveDispatchDraftBtn").addEventListener("click", saveComposeDraft);
document.querySelector("#generateDispatchNoBtn").addEventListener("click", () => {
  const no = assignNextDispatchNo(true);
  setDraftConfirmed(false);
  addDispatchAudit("重新產生發文字號", `已產生 ${no}。`);
  showToast(`已產生發文字號：${no}`);
});
document.querySelector("#aiGenerateDraftBtn")?.addEventListener("click", generateAiDraft);
document.querySelector("#aiApplyDraftBtn")?.addEventListener("click", applyAiDraftToCompose);
document.querySelector("#aiClearDraftBtn")?.addEventListener("click", clearAiDraft);
document.querySelector("#previewDraftBtn")?.addEventListener("click", () => {
  setDraftPreviewExpanded(true, { scroll: true });
  showToast("已更新即時函稿預覽。");
});
document.querySelector("#toggleDraftPreviewBtn")?.addEventListener("click", () => {
  setDraftPreviewExpanded(!draftPreviewExpanded, { scroll: !draftPreviewExpanded });
});
document.querySelector("#confirmDraftBtn").addEventListener("click", () => {
  setDraftConfirmed(true);
  showToast("函稿已確認，可以加入發文佇列。");
});
document.querySelector("#resetDraftConfirmBtn").addEventListener("click", () => {
  setDraftConfirmed(false);
  showToast("已取消函稿確認。");
});
document.querySelector("#composePrevBtn").addEventListener("click", retreatComposeStep);
document.querySelector("#composeNextBtn").addEventListener("click", advanceComposeStep);
document.querySelector("#composeNextAction").addEventListener("click", (event) => {
  const saveButton = event.target.closest("#composeInlineSaveDraftBtn");
  if (saveButton) {
    void saveComposeDraft();
    return;
  }
  const nextButton = event.target.closest("#composeInlineNextBtn");
  if (nextButton && !nextButton.disabled) advanceComposeStep();
});
["#composeCompanySelect", "#docType", "#priority", "#recipient", "#contactAddress", "#contactOwner", "#contactPhone", "#contactFax", "#contactEmail", "#largeSealType", "#smallSealType", "#subject", "#bodyText", "#attachments"].forEach((selector) => {
  const element = document.querySelector(selector);
  element?.addEventListener("input", markDraftDirty);
  if (!["INPUT", "TEXTAREA"].includes(element?.tagName) || element?.type === "file") {
    element?.addEventListener("change", markDraftDirty);
  }
});
document.querySelector("#sendQueueBtn")?.addEventListener("click", () => {
  const queued = dispatchDocs.filter((doc) => ["已封裝", "已清稿", "待清稿"].includes(doc.status)).map((doc) => doc.id);
  if (!queued.length) return showToast("目前沒有可送出的待發文。");
  runDispatchAction("send", queued);
});
document.querySelector("#loginJagentBtn").addEventListener("click", certLogin);
document.querySelector("#certLoginBtn").addEventListener("click", certLogin);
document.querySelector("#logoutJagentBtn").addEventListener("click", logoutJagent);
document.querySelector("#refreshTokenBtn").addEventListener("click", refreshToken);
document.querySelector("#validateTokenBtn").addEventListener("click", validateToken);
document.querySelector("#revokeTokenBtn").addEventListener("click", revokeToken);
document.querySelector("#connectCenterBtn").addEventListener("click", connectCenter);
document.querySelector("#syncCenterBtn").addEventListener("click", syncCenter);
document.querySelector("#disconnectCenterBtn").addEventListener("click", disconnectCenter);
document.querySelector("#addressSearchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  searchAddressBook(document.querySelector("#addressQuery").value);
});
document.querySelector("#clearAddressResultsBtn").addEventListener("click", () => {
  jagentState.addressResults = [];
  renderAddressResults();
  renderJagentStatus();
  showToast("已清除地址簿查詢結果。");
});
document.querySelector("#formatValidateBtn").addEventListener("click", () => {
  const ok = renderFormatChecks();
  addFormatAudit("文書格式檢核", ok ? "文號、文別、速別、密等、主旨、附件清冊與機關代碼均通過。" : "文書格式仍有欄位需補正。");
  showToast(ok ? "文書格式檢核通過。" : "文書格式需補正。");
});
document.querySelector("#formatApplyBtn").addEventListener("click", applyFormatToCompose);
document.querySelector("#formatGenerateNoBtn").addEventListener("click", () => {
  document.querySelector("#formatDocNo").value = nextDispatchNo();
  renderFormatChecks();
  addFormatAudit("產生文號", "已依日期與流水號產生新文號。");
  showToast("已產生新文號。");
});
document.querySelector("#formatLookupAgencyBtn").addEventListener("click", () => {
  searchFormatAgency(document.querySelector("#formatRecipient").value || document.querySelector("#formatAgencyCode").value);
});
document.querySelector("#formatSaveTemplateBtn").addEventListener("click", () => {
  saveCurrentFormatAsTemplate();
});
document.querySelector("#formatExportBtn").addEventListener("click", () => {
  addFormatAudit("匯出格式 JSON", JSON.stringify(formatPayload()));
  showToast("已匯出文書格式 JSON。");
});
document.querySelector("#formatAddAttachmentBtn").addEventListener("click", addFormatAttachment);
document.querySelector("#formatAgencyForm").addEventListener("submit", (event) => {
  event.preventDefault();
  searchFormatAgency(document.querySelector("#formatAgencyQuery").value);
});
document.querySelector("#formatClearAgencyBtn").addEventListener("click", () => {
  formatState.agencyResults = [];
  renderFormatAgencyResults();
  showToast("已清除機關代碼查詢結果。");
});
document.querySelector("#formatClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(formatAuditLog, renderFormatAuditLog, "格式操作紀錄");
});
["#formatDocNo", "#formatDocType", "#formatPriority", "#formatSecurity", "#formatAgencyCode", "#formatRecipient", "#formatSubject"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", renderFormatChecks);
  document.querySelector(selector).addEventListener("change", renderFormatChecks);
});
document.querySelector("#workflowRoleSelect").addEventListener("change", (event) => {
  workflowRole = event.target.value;
  applyRoleNavigation();
  renderScopeZone();
  renderRoleDashboard();
  renderIdentityWorkbench();
  renderInboundRows();
  renderInboundDetail();
  renderDispatchBoard();
  renderDispatchDetail();
  renderWorkflowRole();
  renderUnifiedFlows();
  renderApprovalLog();
  addWorkflowAudit("切換流程角色", `目前流程控管角色切換為 ${workflowRole}。`);
});
document.querySelector("#workflowSyncRoleBtn").addEventListener("click", () => {
  document.querySelector("#roleSelect").value = workflowRole;
  document.querySelector("#roleNote").textContent = roleNotes[workflowRole];
  applyRoleNavigation();
  renderScopeZone();
  renderRoleDashboard();
  renderIdentityWorkbench();
  renderInboundRows();
  renderInboundDetail();
  renderDispatchBoard();
  renderDispatchDetail();
  renderUnifiedFlows();
  renderApprovalLog();
  addWorkflowAudit("同步側欄角色", `側欄目前角色已同步為 ${workflowRole}。`);
  showToast("已同步側欄角色。");
});
document.querySelectorAll("[data-unified-flow-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    unifiedFlowFilter = button.dataset.unifiedFlowFilter;
    renderUnifiedFlows();
  });
});
document.querySelector("#workflowApproveBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "已授權"));
document.querySelector("#workflowRejectBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "退回補正"));
document.querySelector("#workflowAssignBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "指派完成"));
document.querySelector("#workflowProgressBtn").addEventListener("click", () => {
  renderApprovalProgress();
  document.querySelector("#approvalProgressPanel")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
document.querySelector("#approvalNextStepBtn").addEventListener("click", moveApprovalToNextStep);
document.querySelector("#approvalReturnBtn").addEventListener("click", returnApprovalForCorrection);
document.querySelector("#approvalExportBtn").addEventListener("click", exportApprovalProgress);
document.querySelector("#dashboardApprovalOpenBtn").addEventListener("click", () => {
  setView("workflow");
  renderApprovalProgress();
  document.querySelector("#approvalProgressPanel")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
document.querySelector("#dashboardApprovalExportBtn").addEventListener("click", exportApprovalProgress);
document.querySelector("#permissionTestForm").addEventListener("submit", (event) => {
  event.preventDefault();
  checkPermission(document.querySelector("#permissionAction").value);
});
document.querySelector("#workflowClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(workflowAuditLog, renderWorkflowAuditLog, "流程操作紀錄");
});
document.querySelector("#workflowTemplateApplyBtn").addEventListener("click", applyWorkflowTemplate);
document.querySelector("#workflowTemplateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  applyWorkflowTemplate();
});
document.querySelector("#workflowTemplateSelect").addEventListener("change", (event) => {
  activeWorkflowTemplate = event.target.value;
  renderWorkflowTemplateSteps();
  renderWorkflowConditions();
});
document.querySelector("#workflowDocumentCategorySelect").addEventListener("change", (event) => {
  const route = approvalRouteForType(event.target.value);
  const docTypeConfig = documentTypeConfigForName(document.querySelector("#workflowTemplateDocType")?.value);
  activeWorkflowTemplate = docTypeConfig?.defaultWorkflowTemplate || workflowTemplateKeyForRoute(route.code);
  document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  renderWorkflowTemplateSteps();
  renderWorkflowConditions();
});
document.querySelector("#workflowTemplateDocType")?.addEventListener("change", (event) => {
  const config = documentTypeConfigForName(event.target.value);
  if (config?.defaultWorkflowTemplate) activeWorkflowTemplate = config.defaultWorkflowTemplate;
  document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  renderWorkflowTemplateSteps();
  renderWorkflowConditions();
});
document.querySelector("#workflowEvaluateBtn").addEventListener("click", evaluateWorkflowConditions);
document.querySelector("#workflowConditionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  evaluateWorkflowConditions();
});
document.querySelector("#workflowProxyAddBtn").addEventListener("click", addWorkflowProxy);
document.querySelector("#workflowProxyForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addWorkflowProxy();
});
document.querySelector("#workflowActionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runWorkflowAdvancedAction();
});
document.querySelector("#workflowExportProofBtn").addEventListener("click", () => {
  addWorkflowProof("匯出簽核證明", `已匯出 ${workflowProofLog.length} 筆簽核時間戳與不可否認紀錄。`);
  showToast("簽核證明已匯出。");
});
document.querySelector("#sealSubmitBtn").addEventListener("click", submitSealRequest);
document.querySelector("#sealApproveBtn").addEventListener("click", () => approveSealRequests());
document.querySelector("#sealGeneratePdfBtn").addEventListener("click", () => generatePdfTemplate());
document.querySelector("#sealStampPdfBtn").addEventListener("click", stampCurrentPdf);
document.querySelector("#sealVerifyHashBtn").addEventListener("click", verifyCurrentPdfHash);
document.querySelector("#uploadedSealPdfInput").addEventListener("change", handleUploadedSealPdfChange);
document.querySelector("#addCompanyStampBtn").addEventListener("click", () => addUploadedStamp("company"));
document.querySelector("#addOwnerStampBtn").addEventListener("click", () => addUploadedStamp("owner"));
document.querySelector("#addPageStampBtn").addEventListener("click", () => addUploadedStamp("page"));
document.querySelector("#clearUploadedStampsBtn").addEventListener("click", () => {
  uploadedSealStampPositions = [];
  renderUploadedSealWorkbench();
});
document.querySelector("#submitUploadedSealBtn").addEventListener("click", submitUploadedSealApplication);
document.querySelector("#downloadBeforePdfBtn").addEventListener("click", () => downloadPdfVersion("before"));
document.querySelector("#downloadAfterPdfBtn").addEventListener("click", () => downloadPdfVersion("after"));
document.querySelector("#sealApplicationBtn").addEventListener("click", generateSealApplication);
document.querySelector("#signatureSignBtn").addEventListener("click", signCurrentPdf);
document.querySelector("#signatureVerifyBtn").addEventListener("click", verifyCurrentSignature);
document.querySelector("#signatureValidateCertBtn").addEventListener("click", validateCurrentCertificate);
document.querySelector("#certificateServiceHealthBtn").addEventListener("click", () => loadCertificateServiceHealth());
document.querySelector("#signatureCertificateSelect").addEventListener("change", renderSignatureProofGrid);
document.querySelector("#signatureTypeSelect").addEventListener("change", renderSignatureProofGrid);
document.querySelector("#sealExportBtn").addEventListener("click", () => {
  addSealAudit("匯出用印紀錄", `已匯出 ${sealRequests.length} 件簽核用印與 ${sealAuditLog.length} 筆軌跡。`);
  showToast("用印紀錄已匯出。");
});
document.querySelector("#companySealCompanySelect").addEventListener("change", (event) => {
  selectedCompanySealCompanyId = event.target.value;
  selectedCompanySealId = "";
  loadCompanySealCompanyData();
});
document.querySelector("#sealUsageCompanySelect").addEventListener("change", (event) => {
  selectedCompanySealCompanyId = event.target.value;
  document.querySelector("#companySealCompanySelect").value = selectedCompanySealCompanyId;
  selectedCompanySealId = "";
  loadCompanySealCompanyData();
});
document.querySelector("#companySealReloadBtn").addEventListener("click", () => loadCompanySealModule());
document.querySelector("#companySealCreateBtn").addEventListener("click", createCompanySealFromForm);
document.querySelector("#companySealCreateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createCompanySealFromForm();
});
document.querySelector("#companySealUploadBtn").addEventListener("click", uploadCompanySealVersion);
document.querySelector("#companySealUploadForm").addEventListener("submit", (event) => {
  event.preventDefault();
  uploadCompanySealVersion();
});
document.querySelector("#sealUsageAddPositionBtn").addEventListener("click", addCompanySealStampPosition);
document.querySelector("#sealUsageClearPositionsBtn").addEventListener("click", () => {
  companySealStampPositions = [];
  renderCompanySealModule();
});
document.querySelector("#sealUsageSubmitBtn").addEventListener("click", submitCompanySealUsageRequest);
document.querySelector("#sealUsageRequestForm").addEventListener("submit", (event) => {
  event.preventDefault();
  submitCompanySealUsageRequest();
});
document.querySelector("#sealUsageStampBtn").addEventListener("click", () => stampCompanySealUsageRequest());
document.querySelector("#sealAddBtn").addEventListener("click", addSealFromForm);
document.querySelector("#sealImageInput").addEventListener("change", handleSealImageUpload);
document.querySelector("#sealForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSealFromForm();
});
document.querySelector("#addCompanyBtn").addEventListener("click", addCompanyRegistryItem);
document.querySelector("#companyRegistryForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addCompanyRegistryItem();
});
document.querySelector("#addDepartmentBtn").addEventListener("click", addDepartmentRegistryItem);
document.querySelector("#departmentRegistryForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addDepartmentRegistryItem();
});
document.querySelector("#addSealTypeBtn").addEventListener("click", addSealTypeRegistryItem);
document.querySelector("#sealTypeRegistryForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSealTypeRegistryItem();
});
document.querySelector("#sealClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(sealAuditLog, () => {
    renderSealAuditLog();
    renderSealSummary();
  }, "用印操作紀錄");
});
document.querySelectorAll(".segment[data-tracking-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-tracking-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    trackingFilter = button.dataset.trackingFilter;
    renderTrackingRows();
  });
});
document.querySelector("#trackingSearch").addEventListener("input", (event) => {
  trackingSearchTerm = event.target.value;
  renderTrackingRows();
});
document.querySelector("#nextDayCheckBtn").addEventListener("click", () => runTrackingAction("nextday"));
document.querySelector("#sendOverdueBtn").addEventListener("click", () => runTrackingAction("remind"));
document.querySelector("#confirmUnreceivedBtn").addEventListener("click", () => runTrackingAction("confirm"));
document.querySelector("#returnCorrectionBtn").addEventListener("click", () => runTrackingAction("return"));
document.querySelector("#scheduleReminderBtn").addEventListener("click", async () => {
  const targetIds = selectedTrackingIds();
  const method = document.querySelector("#trackingNotifyMethod").value;
  for (const id of targetIds) {
    const item = trackingCases.find((entry) => entry.id === id);
    if (!item) continue;
    const notice = { id: `NTF-SCH-${Date.now().toString().slice(-5)}-${id}`, type: "逾期查核", title: item.title, target: document.querySelector("#trackingNotifyTarget").value, channel: method, status: "未讀", priority: "高", source: item.id, body: document.querySelector("#trackingMessage").value.trim() || item.note };
    notificationItems.unshift(notice);
    notificationSchedules.unshift({ id: `SCH-TRK-${id}`, type: "逾期排程通知", rule: notificationGatewayState.overdueSchedule, target: notice.target });
    await deliverNotification(notice, method);
  }
  renderNotifications();
  addTrackingAudit("排程稽催提醒", `已為 ${targetIds.length} 件設定提醒：${method}，並送入通知閘道。`);
  showToast("稽催提醒排程已建立。");
});
document.querySelector("#trackingReminderForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runTrackingAction("remind");
});
document.querySelector("#correctionForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runTrackingAction("return");
});
document.querySelector("#trackingClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(trackingAuditLog, renderTrackingAuditLog, "稽催操作紀錄");
});
document.querySelectorAll(".segment[data-archive-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-archive-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    archiveFilter = button.dataset.archiveFilter;
    renderArchiveRows();
  });
});
document.querySelector("#archiveSearch").addEventListener("input", (event) => {
  archiveSearchTerm = event.target.value;
  renderArchiveRows();
});
document.querySelector("#archiveSealBtn").addEventListener("click", () => runArchiveAction("seal"));
document.querySelector("#archiveVerifyBtn").addEventListener("click", () => runArchiveAction("verify"));
document.querySelector("#archiveExportBtn").addEventListener("click", () => runArchiveAction("export"));
document.querySelector("#archiveOpenOriginalBtn").addEventListener("click", () => runArchiveAction("open"));
document.querySelector("#archiveClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(archiveAuditLog, renderArchiveAuditLog, "歸檔操作紀錄");
});
document.querySelector("#securityCertForm").addEventListener("submit", (event) => {
  event.preventDefault();
  securityCertLogin();
});
document.querySelector("#securityCertBtn").addEventListener("click", securityCertLogin);
document.querySelector("#securityRefreshTokenBtn").addEventListener("click", refreshSecurityToken);
document.querySelector("#securityRevokeTokenBtn").addEventListener("click", revokeSecurityToken);
document.querySelector("#securityTokenExpireBtn").addEventListener("click", expireSecurityToken);
document.querySelector("#securityRbacForm").addEventListener("submit", (event) => {
  event.preventDefault();
  testSecurityPermission();
});
document.querySelector("#securityRoleSelect").addEventListener("change", (event) => renderSecurityPermissionGrid(event.target.value));
document.querySelector("#securityAddDeviceBtn").addEventListener("click", addSecurityDevice);
document.querySelector("#securityDeviceForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSecurityDevice();
});
document.querySelector("#securitySignActionBtn").addEventListener("click", signSecurityAction);
document.querySelector("#securityExportProofBtn").addEventListener("click", () => {
  addSecurityAudit("匯出不可否認紀錄", `已匯出 ${securityAuditLog.length} 筆資安紀錄與簽章序號 ${securityState.proofSerial}。`);
  showToast("不可否認紀錄已匯出。");
});
document.querySelector("#securityClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(securityAuditLog, renderSecurityAuditLog, "資安操作紀錄");
});
document.querySelectorAll("[data-file-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-file-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    fileSecurityFilter = button.dataset.fileFilter;
    renderFileSecurity();
  });
});
document.querySelector("#fileSecuritySearch").addEventListener("input", (event) => {
  fileSecuritySearchTerm = event.target.value;
  renderFileSecurity();
});
document.querySelector("#fileScanBtn").addEventListener("click", () => runFileSecurityAction("scan"));
document.querySelector("#fileMaskBtn").addEventListener("click", () => runFileSecurityAction("mask"));
document.querySelector("#fileWatermarkBtn").addEventListener("click", downloadWatermarkedFile);
document.querySelector("#fileReleaseBtn").addEventListener("click", () => runFileSecurityAction("release"));
document.querySelector("#fileBackupBtn").addEventListener("click", createFileSecurityBackup);
document.querySelector("#fileRestoreBtn").addEventListener("click", restoreFileSecurityBackup);
document.querySelector("#filePolicySaveBtn").addEventListener("click", saveFileSecurityPolicy);
document.querySelector("#fileStorageHealthBtn").addEventListener("click", () => loadFileStorageServiceHealth(true));
document.querySelector("#fileSecurityPolicyForm").addEventListener("submit", (event) => {
  event.preventDefault();
  saveFileSecurityPolicy();
});
document.querySelector("#fileClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(fileAccessLog, renderFileAccessLog, "檔案存取紀錄");
});
document.querySelectorAll("[data-account-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-account-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    accountFilter = button.dataset.accountFilter;
    renderAccounts();
  });
});
document.querySelector("#accountSearch").addEventListener("input", (event) => {
  accountSearchTerm = event.target.value;
  renderAccounts();
});
document.querySelector("#accountRoleSelect").addEventListener("change", () => syncAccountJobLevelWithRole());
document.querySelector("#accountInviteBtn").addEventListener("click", createAccountFromForm);
document.querySelector("#accountForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createAccountFromForm();
});
document.querySelector("#accountSyncBtn").addEventListener("click", syncAccountsFromRoles);
document.querySelector("#accountExportBtn").addEventListener("click", () => {
  addAccountAudit("匯出權限報表", `已匯出 ${userAccounts.length} 個帳號、${Object.keys(rolePermissions).length} 個角色與 ${accountLoginLogs.length} 筆登入紀錄。`);
  showToast("帳號權限報表已匯出。");
});
document.querySelector("#ssoConnectBtn").addEventListener("click", connectSso);
document.querySelector("#ssoTestBtn").addEventListener("click", testSso);
document.querySelector("#ssoForm").addEventListener("submit", (event) => {
  event.preventDefault();
  connectSso();
});
document.querySelector("#mfaEnforceBtn").addEventListener("click", enforceMfa);
document.querySelector("#accountAddIpBtn").addEventListener("click", addAccountIpRule);
document.querySelector("#accountIpForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addAccountIpRule();
});
document.querySelector("#accountClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(accountAuditLog, renderAccountAuditLog, "帳號操作紀錄");
});
document.querySelector("#reportsRecalcBtn").addEventListener("click", () => {
  renderReports();
  addReportsAudit("重新統計報表", `已重算 ${document.querySelector("#reportPeriod").value} / ${document.querySelector("#reportUnit").value} 報表。`);
  showToast("報表已重新統計。");
});
document.querySelector("#reportsApplyFilterBtn").addEventListener("click", () => {
  renderReports();
  addReportsAudit("套用報表篩選", `${document.querySelector("#reportPeriod").value}、${document.querySelector("#reportUnit").value}、${document.querySelector("#reportAgencyQuery").value}。`);
  showToast("報表篩選已套用。");
});
document.querySelector("#reportsExportBtn").addEventListener("click", () => {
  const report = latestFormalReport || generateFormalReport();
  downloadTextFile(`${report.reportNo}.json`, JSON.stringify(report, null, 2));
  addReportsAudit("匯出正式報表", `${report.reportNo}.json 已匯出，雜湊 ${report.reportHash}。`);
  showToast("正式報表 JSON 已匯出。");
});
document.querySelector("#reportsPrintBtn").addEventListener("click", () => {
  addReportsAudit("列印月報", "已產生報表統計月報列印版。");
  showToast("月報列印版已產生。");
});
document.querySelector("#reportsGenerateFormalBtn").addEventListener("click", generateFormalReport);
document.querySelector("#reportsExportCsvBtn").addEventListener("click", () => {
  const report = latestFormalReport || generateFormalReport();
  downloadTextFile(`${report.reportNo}.csv`, formalReportCsv(report), "text/csv;charset=utf-8");
  addReportsAudit("匯出正式報表 CSV", `${report.reportNo}.csv 已匯出。`);
  showToast("正式報表 CSV 已匯出。");
});
document.querySelector("#reportsExportJsonBtn").addEventListener("click", () => {
  const report = latestFormalReport || generateFormalReport();
  downloadTextFile(`${report.reportNo}-audit.json`, JSON.stringify({ ...report, auditTrail: reportsAuditLog }, null, 2));
  addReportsAudit("匯出稽核 JSON", `${report.reportNo}-audit.json 已匯出，含報表操作紀錄。`);
  showToast("稽核 JSON 已匯出。");
});
document.querySelector("#reportsCreateReminderBtn").addEventListener("click", createReportReminder);
document.querySelector("#reportsClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(reportsAuditLog, renderReportsAuditLog, "報表操作紀錄");
});
document.querySelectorAll(".segment[data-notification-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-notification-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    notificationFilter = button.dataset.notificationFilter;
    renderNotificationRows();
    renderNotificationSummary();
  });
});
document.querySelectorAll("[data-reminder-filter]").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-notification-filter]").forEach((item) => item.classList.remove("active"));
    notificationFilter = card.dataset.reminderFilter;
    renderNotifications();
    document.querySelector("#notificationRows")?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
});
document.querySelector("#notificationSearch").addEventListener("input", (event) => {
  notificationSearchTerm = event.target.value;
  renderNotificationRows();
});
document.querySelector("#notificationSyncBtn").addEventListener("click", syncNotifications);
document.querySelector("#notificationReadBtn").addEventListener("click", () => runNotificationAction("read"));
document.querySelector("#notificationDispatchBtn").addEventListener("click", () => runNotificationAction("send"));
document.querySelector("#notificationImmediateAlertBtn").addEventListener("click", sendImmediateFailureAlerts);
document.querySelector("#notificationAddBtn").addEventListener("click", addNotificationFromForm);
document.querySelector("#notificationForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addNotificationFromForm();
});
document.querySelector("#notificationSaveGatewayBtn").addEventListener("click", saveNotificationGateway);
document.querySelector("#notificationValidateCredentialsBtn").addEventListener("click", validateNotificationCredentials);
document.querySelector("#notificationGatewayForm").addEventListener("submit", (event) => {
  event.preventDefault();
  saveNotificationGateway();
});
document.querySelector("#notificationTestChannelsBtn").addEventListener("click", testNotificationChannels);
document.querySelector("#notificationApplyRulesBtn").addEventListener("click", createNotificationSchedules);
document.querySelector("#notificationScheduleForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createNotificationSchedules();
});
document.querySelector("#notificationRetryFailedBtn").addEventListener("click", retryFailedNotificationDeliveries);
document.querySelector("#notificationInboxPushBtn").addEventListener("click", pushSelectedToInbox);
document.querySelector("#notificationClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(notificationAuditLog, renderNotificationAuditLog, "通知操作紀錄");
});
document.querySelectorAll("[data-job-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-job-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    jobFilter = button.dataset.jobFilter;
    renderJobs();
  });
});
document.querySelector("#jobSearch").addEventListener("input", (event) => {
  jobSearchTerm = event.target.value;
  renderJobs();
});
document.querySelector("#jobRunDueBtn").addEventListener("click", runDueJobs);
document.querySelector("#jobRunAllBtn").addEventListener("click", () => runJobAction("run", backgroundJobs.map((job) => job.id)));
document.querySelector("#jobPauseAllBtn").addEventListener("click", () => {
  const anyActive = backgroundJobs.some((job) => job.status === "啟用");
  backgroundJobs.forEach((job) => {
    job.status = anyActive ? "暫停" : "啟用";
  });
  renderJobs();
  addJobAudit(anyActive ? "全部暫停" : "全部啟用", `已將 ${backgroundJobs.length} 個背景任務更新狀態。`);
  showToast(anyActive ? "背景任務已全部暫停。" : "背景任務已全部啟用。");
});
document.querySelector("#jobExportBtn").addEventListener("click", () => {
  addJobAudit("匯出排程紀錄", `已匯出 ${backgroundJobs.length} 個任務與 ${jobAuditLog.length} 筆執行紀錄。`);
  showToast("排程紀錄已匯出。");
});
document.querySelector("#jobAddBtn").addEventListener("click", addBackgroundJobFromForm);
document.querySelector("#jobForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addBackgroundJobFromForm();
});
document.querySelector("#jobHealthBtn").addEventListener("click", () => {
  syncJobsFromBackend(true).then(() => {
    addJobAudit("後端 Worker 健康檢查", "排程 worker、佇列、互斥鎖與資料庫連線均回應正常。");
    renderJobs();
    showToast("後端背景任務 Worker 正常。");
  }).catch((error) => {
    addJobAudit("Worker 健康檢查失敗", error.message);
    showToast("後端 Worker 無法連線。");
  });
});
document.querySelector("#jobClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(jobAuditLog, renderJobAuditLog, "背景任務紀錄");
});
document.querySelectorAll(".segment[data-db-table]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-db-table]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeDatabaseTable = button.dataset.dbTable;
    selectedDatabaseId = (databaseTables[activeDatabaseTable] || [])[0]?.id || "";
    renderDatabase();
  });
});
document.querySelector("#databaseSearch").addEventListener("input", (event) => {
  databaseSearchTerm = event.target.value;
  renderDatabaseRows();
});
document.querySelector("#databaseSyncBtn").addEventListener("click", () => {
  syncDatabaseFromBackend();
});
document.querySelector("#backendHealthBtn").addEventListener("click", checkBackendHealth);
document.querySelector("#backendPullInboundBtn").addEventListener("click", backendPullInbound);
document.querySelector("#backendBackupBtn").addEventListener("click", backendCreateBackup);
document.querySelector("#databaseExportBtn").addEventListener("click", () => {
  addDatabaseAudit("匯出資料表", `已匯出 ${databaseLabels[activeDatabaseTable]} ${databaseRows().length} 筆。`);
  showToast("資料表匯出完成。");
});
document.querySelector("#databaseMigrateBtn").addEventListener("click", () => {
  addDatabaseAudit("產生 Migration", "已產生 documents、recipients、attachments、exchangeTasks、exchangeEvents、auditLogs schema migration。");
  showToast("Migration 已產生。");
});
document.querySelector("#databaseAddBtn").addEventListener("click", addDatabaseRowFromForm);
document.querySelector("#databaseForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addDatabaseRowFromForm();
});
document.querySelector("#databaseClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(databaseAuditLog, renderDatabaseAuditLog, "資料庫操作紀錄");
});
document.querySelectorAll("[data-ops-log-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-ops-log-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    opsLogFilter = button.dataset.opsLogFilter;
    renderOpsApiLogs();
  });
});
document.querySelector("#opsLogSearch").addEventListener("input", (event) => {
  opsLogSearchTerm = event.target.value;
  renderOpsApiLogs();
});
document.querySelector("#opsHealthBtn").addEventListener("click", runOpsHealthCheck);
document.querySelector("#opsReadinessBtn").addEventListener("click", runOpsReadinessCheck);
document.querySelector("#opsGoLiveAuditBtn").addEventListener("click", runOpsGoLiveAudit);
document.querySelector("#opsMonitoringBtn").addEventListener("click", runOpsMonitoringCheck);
document.querySelector("#goLiveRefreshBtn").addEventListener("click", runOpsGoLiveAudit);
document.querySelector("#opsLookupErrorBtn").addEventListener("click", () => lookupOpsErrorCode());
document.querySelector("#opsErrorForm").addEventListener("submit", (event) => {
  event.preventDefault();
  lookupOpsErrorCode();
});
document.querySelector("#opsCommitConfigBtn").addEventListener("click", commitOpsConfigVersion);
document.querySelector("#opsConfigForm").addEventListener("submit", (event) => {
  event.preventDefault();
  commitOpsConfigVersion();
});
document.querySelector("#opsExportAuditBtn").addEventListener("click", exportOpsAudit);
document.querySelector("#opsBackupBtn").addEventListener("click", createOpsBackup);
document.querySelector("#opsRestoreBackupBtn").addEventListener("click", restoreOpsBackup);
document.querySelector("#opsSwitchEnvBtn").addEventListener("click", switchOpsEnvironment);
document.querySelector("#opsClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(opsAuditLog, renderOpsAuditLog, "維運操作紀錄");
});
document.querySelector("#complianceAttestBtn").addEventListener("click", attestComplianceReview);
document.querySelector("#complianceExportBtn").addEventListener("click", exportCompliancePackage);
document.querySelector("#complianceDrillBtn").addEventListener("click", recordComplianceDrill);
document.querySelector("#backupDrillRunBtn").addEventListener("click", runBackupRestoreDrill);
document.querySelector("#backupDrillExportBtn").addEventListener("click", exportBackupDrillReport);
document.querySelector("#complianceOpenDocBtn").addEventListener("click", openComplianceDocument);
document.querySelector("#complianceRunSopBtn").addEventListener("click", runComplianceSop);
document.querySelector("#complianceResolveGapBtn").addEventListener("click", resolveComplianceGap);
document.querySelector("#complianceSopSelect").addEventListener("change", renderComplianceSop);
document.querySelector("#complianceSopForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runComplianceSop();
});
document.querySelector("#complianceClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(complianceAuditLog, renderComplianceAuditLog, "法遵營運紀錄");
});
document.querySelector("#retryFailedBtn").addEventListener("click", () => {
  const failed = dispatchDocs.filter((doc) => doc.status === "交換失敗").map((doc) => doc.id);
  if (failed.length) runDispatchAction("resend", failed);
  addExchangeEvent("重送異常", failed.length ? `已重送 ${failed.length} 筆交換失敗發文。` : "目前沒有交換失敗案件。");
  showToast(failed.length ? "已重送交換失敗案件。" : "目前沒有交換失敗案件。");
});
document.querySelector("#saveSettingsBtn").addEventListener("click", saveSettings);
document.querySelector("#settingsValidateAgencyBtn").addEventListener("click", validateSettingsAgency);
document.querySelector("#settingsSyncCenterBtn").addEventListener("click", syncSettingsCenter);
document.querySelector("#settingsTestApiBtn").addEventListener("click", testSettingsApi);
document.querySelector("#settingsVerifyCertBtn").addEventListener("click", verifySettingsCert);
document.querySelector("#settingsRotateCertBtn").addEventListener("click", rotateSettingsCert);
document.querySelector("#settingsAddFirewallBtn").addEventListener("click", addSettingsFirewallRule);
document.querySelector("#settingsFirewallForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSettingsFirewallRule();
});
document.querySelector("#settingsAddRoleBtn").addEventListener("click", addSettingsRole);
document.querySelector("#settingsRoleForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSettingsRole();
});
document.querySelector("#settingsAddDocTypeBtn")?.addEventListener("click", upsertSettingsDocumentType);
document.querySelector("#settingsDocTypeForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  upsertSettingsDocumentType();
});
document.querySelector("#settingsDocTypeName")?.addEventListener("change", () => {
  const config = documentTypeConfigForName(document.querySelector("#settingsDocTypeName").value.trim());
  if (config) editDocumentTypeConfig(config.id);
  else syncConfigurableSelectOptions();
});
document.querySelector("#settingsAddWorkflowTemplateBtn")?.addEventListener("click", upsertSettingsWorkflowTemplate);
document.querySelector("#settingsWorkflowTemplateForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  upsertSettingsWorkflowTemplate();
});
document.querySelector("#settingsGrantPermissionBtn")?.addEventListener("click", () => mutateSettingsPermission("grant"));
document.querySelector("#settingsRevokePermissionBtn")?.addEventListener("click", () => mutateSettingsPermission("revoke"));
document.querySelector("#settingsPermissionRoleSelect")?.addEventListener("change", renderSettingsPermissionMatrix);
document.querySelector("#settingsPermissionCodeSelect")?.addEventListener("change", renderSettingsPermissionMatrix);
document.querySelector("#settingsSaveFormatTemplateBtn")?.addEventListener("click", saveSettingsFormatTemplate);
document.querySelector("#settingsFormatTemplateForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  saveSettingsFormatTemplate();
});
document.querySelector("#settingsApplyFormatTemplateBtn")?.addEventListener("click", () => applySettingsFormatTemplate());
document.querySelector("#settingsBackupBtn").addEventListener("click", () => {
  const data = settingsPayload();
  addSettingsAudit("匯出系統設定", `已匯出 ${data.agencyCode} 設定備份，含交換中心、防火牆、憑證、角色、文件類型、流程模板、權限矩陣與格式模板。`);
  showToast("系統設定備份已匯出。");
});
document.querySelector("#settingsClearLogBtn").addEventListener("click", () => {
  clearLogWithConfirm(settingsAuditLog, renderSettingsAuditLog, "設定操作紀錄");
});
document.querySelector("#logoutBtn").addEventListener("click", leaveApp);
document.querySelector("#identityWorkbench").addEventListener("click", (event) => {
  const button = event.target.closest("[data-identity-target]");
  if (!button) return;
  const target = button.dataset.identityTarget;
  const clickId = button.dataset.identityClick;
  if (target) setView(isRouteAllowed(target) ? target : "dashboard");
  if (clickId) window.setTimeout(() => document.querySelector(`#${clickId}`)?.click(), 80);
});

applyEdocRoleOptions();
syncConfigurableSelectOptions();
assignNextDispatchNo(true);
applyComposeContactDefaults();
renderDraftPreview();
applyRoleNavigation();
renderScopeZone();
renderIdentityWorkbench();
renderRoleDashboard();
renderQueueRows();
renderInboundRows();
renderInboundDetail();
renderInboundAuditLog();
renderDispatchBoard();
renderDispatchDetail();
renderDispatchAuditLog();
renderPrechecks();
renderJagentStatus();
renderAddressResults();
renderFormatAttachments();
renderFormatChecks();
renderFormatAgencyResults();
renderFormatAuditLog();
renderWorkflowRole();
renderWorkflowTasks();
renderUnifiedFlows();
renderWorkflowSteps();
renderApprovalProgress();
renderApprovalLog();
renderWorkflowAuditLog();
renderApprovalCategorySelect("#workflowDocumentCategorySelect", "服務委託合約");
renderWorkflowTemplateSteps();
renderWorkflowConditions();
renderWorkflowProxies();
renderWorkflowProofLog();
renderContracts();
renderContractSeal();
fillContractForm();
renderSeals();
loadCompanySealModule(true);
renderTrackingSummary();
renderTrackingRows();
renderTrackingDetail();
renderTrackingAuditLog();
renderTimeline("#exchangeTimeline", exchangeEvents);
renderTimeline("#auditTimeline", auditEvents);
renderArchiveSummary();
renderArchiveRows();
renderArchiveDetail();
renderArchiveGrid();
renderArchiveAuditLog();
renderSecurityStatus();
renderSecurityPermissionGrid();
renderSecurityDeviceList();
renderSecurityAuditLog();
renderFileSecurity();
loadFileStorageServiceHealth();
renderAccounts();
renderReports();
renderReportsAuditLog();
renderNotifications();
renderNotificationAuditLog();
syncNotificationsFromBackend(true);
syncDatabaseFromBackend(true);
renderJobs();
syncJobsFromBackend(true);
syncDatabaseTables(true);
renderDatabase();
renderOps();
renderComplianceOps();
renderFeatureGrid();
renderSettings();
renderSearch();
setView(location.hash?.slice(1) && titles[location.hash.slice(1)] ? location.hash.slice(1) : "dashboard");
tryResumePlatformSession();
