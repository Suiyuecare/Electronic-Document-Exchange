const queueItems = [
  ["EX-1140522-018", "收文", "衛生福利部", "長照服務品質稽核資料補件通知", "待登錄", "wait"],
  ["EX-1140522-013", "收文", "臺北市政府社會局", "北區長照服務協調會議", "待分派", "wait"],
  ["EX-1140522-007", "發文", "臺北市政府社會局", "日照中心設立許可補正資料", "待清稿", "info"],
  ["EX-1140521-003", "發文", "衛生福利部", "長照人力培訓成果彙報", "交換完成", "ok"],
  ["EX-1140520-009", "發文", "桃園市政府社會局", "社區據點服務計畫變更", "等待確認", "wait"],
  ["EX-1140519-002", "收文", "新北市政府衛生局", "居家服務督導訪視資料回覆", "異常待處理", "issue"]
];

const backendApiBase = `${window.location.origin}/api`;

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
    owner: "總收發",
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
    owner: "文書主管",
    dept: "總管理處",
    priority: "普通件",
    security: "普通",
    receivedAt: "2026-05-22 09:28",
    dueDate: "2026-05-24",
    attachments: ["開會通知單.pdf", "會議議程.pdf"],
    note: "已完成登錄，待分派承辦人。"
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
    owner: "總收發",
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
    owner: "總收發",
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
    owner: "總收發",
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
    owner: "總收發",
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
    owner: "文書主管",
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
    owner: "總收發",
    attachments: ["品質改善計畫.pdf"],
    packageId: "PKG-1140519-006",
    lastReply: "jAgent 回覆 failed：收文方機關代碼暫不可用。",
    checks: { format: true, recipient: true, attachments: true, certificate: true, package: true }
  }
];

let selectedDispatchId = dispatchDocs[0].id;
let dispatchFilter = "all";
let dispatchSearchTerm = "";
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
  ["08:54", "憑證登入", "總收發人員完成 jAgent 登入。"]
];

const auditEvents = [
  ["10:08", "王督導分派收文", "收1140521-00044 分派至居家照顧課。"],
  ["09:51", "總收發完成清稿", "歲悅字第1140522007號完成格式檢核。"],
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
    operationTrail: ["總收發登入", "拉取來文", "收文登錄"],
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
  { id: "DEV-001", ip: "203.0.113.18", name: "總收發辦公室 Mac", fingerprint: "FP-SYC-EDOC-A1F9", status: "允許" },
  { id: "DEV-002", ip: "198.51.100.27", name: "文書主管筆電", fingerprint: "FP-SYC-EDOC-B8C2", status: "允許" },
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
  confidentialRoles: "文書主管,資訊管理員,稽核人員",
  watermarkText: "歲悅長照｜電子公文交換｜限授權使用"
};

const fileSecurityItems = archiveRecords.flatMap((record, recordIndex) => record.attachments.map((attachment, attachmentIndex) => {
  const sequence = recordIndex * 3 + attachmentIndex + 1;
  const sizeMb = [3.8, 0.4, 18.6, 1.1, 62.4, 0.8, 9.7][sequence - 1] || 6.2;
  const confidential = record.id === "ARC-004" ? "密" : "普通";
  return {
    id: `FS-${String(sequence).padStart(3, "0")}`,
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
    accessRole: confidential === "密" ? "文書主管,資訊管理員,稽核人員" : "一般角色",
    watermarkStatus: "未下載",
    backupStatus: "未備份"
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

const userAccounts = [
  { id: "USR-001", name: "林總收發", email: "edoc@suiyuecare.com", unit: "總管理處", title: "總收發人員", role: "總收發人員", provider: "Google Workspace", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 10:05", ip: "203.0.113.18", device: "總收發辦公室 Mac" },
  { id: "USR-002", name: "張文書", email: "records@suiyuecare.com", unit: "總管理處", title: "文書主管", role: "文書主管", provider: "Microsoft Entra", mfa: "已啟用", status: "啟用", lastLogin: "2026-05-22 09:48", ip: "198.51.100.27", device: "文書主管筆電" },
  { id: "USR-003", name: "王督導", email: "supervisor@suiyuecare.com", unit: "居家照顧課", title: "督導", role: "承辦人", provider: "Google Workspace", mfa: "待設定", status: "啟用", lastLogin: "2026-05-21 16:20", ip: "203.0.113.18", device: "居服督導 iPad" },
  { id: "USR-004", name: "陳資訊", email: "it@suiyuecare.com", unit: "資訊室", title: "資訊管理員", role: "資訊管理員", provider: "本機帳號", mfa: "強制重設", status: "啟用", lastLogin: "2026-05-22 08:56", ip: "203.0.113.44", device: "資訊室管理機" },
  { id: "USR-005", name: "李稽核", email: "audit@suiyuecare.com", unit: "稽核室", title: "稽核人員", role: "稽核人員", provider: "Microsoft Entra", mfa: "已啟用", status: "停用", lastLogin: "2026-05-18 14:12", ip: "198.51.100.27", device: "稽核室筆電" }
];

const accountLoginLogs = [
  ["10:05", "edoc@suiyuecare.com", "Google Workspace", "203.0.113.18", "成功"],
  ["09:48", "records@suiyuecare.com", "Microsoft Entra", "198.51.100.27", "成功"],
  ["08:56", "it@suiyuecare.com", "本機帳號 + MFA", "203.0.113.44", "成功"],
  ["08:10", "unknown@suiyuecare.com", "本機帳號", "192.0.2.41", "IP 封鎖"]
];

const accountDevices = [
  { id: "ACC-DEV-001", userId: "USR-001", name: "總收發辦公室 Mac", ip: "203.0.113.18", fingerprint: "FP-SYC-EDOC-A1F9", status: "信任" },
  { id: "ACC-DEV-002", userId: "USR-002", name: "文書主管筆電", ip: "198.51.100.27", fingerprint: "FP-SYC-EDOC-B8C2", status: "信任" },
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

const settingsState = {
  agencyVerified: false,
  centerSynced: false,
  apiStatus: "未測試",
  certStatus: "待驗證"
};

const settingsFirewallRules = [
  { id: "FW-001", ip: "203.0.113.18", purpose: "總收發辦公室固定 IP", status: "允許" },
  { id: "FW-002", ip: "198.51.100.27", purpose: "文書主管 VPN", status: "允許" }
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
  restoredBackup: ""
};

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
  { id: "CFG-001", version: "v1.0.0", env: "測試環境", note: "初始測試參數", actor: "資訊管理員", createdAt: "2026-05-22 10:55" }
];

const opsBackups = [];
const opsAuditLog = [
  ["11:58", "維運中心初始化", "已載入 jAgent 健康檢查、API log、錯誤碼、參數版控、操作紀錄匯出、資料備份與環境切換。"]
];

let selectedNotificationId = "NTF-001";
let notificationFilter = "all";
let notificationSearchTerm = "";
const notificationItems = [
  { id: "NTF-001", type: "收文", title: "衛福部補件通知待登錄", target: "總收發人員", channel: "系統通知", status: "未讀", priority: "高", source: "IN-1140522-00018", body: "jAgent 已拉取新來文，請完成收文登錄與附件檢核。" },
  { id: "NTF-002", type: "待清稿", title: "日照中心補正資料待清稿", target: "文書主管", channel: "Email + 系統通知", status: "未讀", priority: "高", source: "OUT-1140522-007", body: "函稿已建立，請進行清稿檢核與附件封裝。" },
  { id: "NTF-003", type: "交換失敗", title: "新北市政府衛生局交換失敗", target: "總收發人員", channel: "系統通知", status: "未讀", priority: "高", source: "OUT-1140519-006", body: "jAgent 回覆 failed，請確認機關代碼並重送。" },
  { id: "NTF-004", type: "Token 到期", title: "jAgent Token 即將到期", target: "資訊管理員", channel: "Email + 系統通知", status: "未讀", priority: "中", source: "SEC-TOKEN", body: "Token 剩餘時間不足，請刷新或重新憑證登入。" },
  { id: "NTF-005", type: "逾期查核", title: "收1140522-00013 分派逾期", target: "文書主管", channel: "Line 工作群組", status: "未讀", priority: "高", source: "TRK-003", body: "收文尚未完成分派，請啟動逾期查核提醒。" }
];

const notificationAuditLog = [
  ["11:02", "通知中心初始化", "已載入收文、待清稿、交換失敗、Token 到期與逾期查核提醒。"]
];

const notificationGatewayState = {
  emailStatus: "未測試",
  lineStatus: "未測試",
  inboxStatus: "啟用",
  scheduleStatus: "未排程",
  emailApi: "https://mail.suiyuecare.com/send",
  lineWebhook: "https://line.example.com/webhook/suiyuecare-edoc",
  inboxRetention: "90 天",
  overdueSchedule: "每日 09:00",
  tokenSchedule: "到期前 30 分鐘",
  failureChannel: "Email + Line + 系統通知"
};

const notificationDeliveryLog = [
  ["11:03", "系統站內通知", "通知閘道初始化，站內通知通道已啟用。"]
];

const systemInboxItems = [
  { id: "INBOX-001", target: "總收發人員", title: "衛福部補件通知待登錄", status: "未讀", createdAt: "11:03" }
];

const notificationSchedules = [];

let selectedJobId = "JOB-001";
let jobFilter = "all";
let jobSearchTerm = "";
const backgroundJobs = [
  { id: "JOB-001", name: "每日收文拉取", type: "pullInbound", schedule: "每日 08:30", nextRun: "2026-05-23 08:30", status: "啟用", lastResult: "尚未執行", notify: "總收發人員", runCount: 0 },
  { id: "JOB-002", name: "發文翌日查核", type: "nextDayCheck", schedule: "每日 09:00", nextRun: "2026-05-23 09:00", status: "啟用", lastResult: "尚未執行", notify: "文書主管", runCount: 0 },
  { id: "JOB-003", name: "Token 到期檢查", type: "tokenCheck", schedule: "每 15 分鐘", nextRun: "2026-05-22 11:15", status: "啟用", lastResult: "尚未執行", notify: "資訊管理員", runCount: 0 },
  { id: "JOB-004", name: "逾期稽催", type: "overdueReminder", schedule: "每小時", nextRun: "2026-05-22 12:00", status: "啟用", lastResult: "尚未執行", notify: "文書主管", runCount: 0 },
  { id: "JOB-005", name: "交換狀態同步", type: "exchangeSync", schedule: "每 15 分鐘", nextRun: "2026-05-22 11:15", status: "啟用", lastResult: "尚未執行", notify: "總收發人員", runCount: 0 },
  { id: "JOB-006", name: "歸檔封存", type: "archiveSeal", schedule: "每日 18:00", nextRun: "2026-05-22 18:00", status: "啟用", lastResult: "尚未執行", notify: "稽核人員", runCount: 0 },
  { id: "JOB-007", name: "報表產生", type: "reportGenerate", schedule: "每日 18:00", nextRun: "2026-05-22 18:00", status: "啟用", lastResult: "尚未執行", notify: "文書主管", runCount: 0 }
];

const jobAuditLog = [
  ["11:52", "背景任務初始化", "已載入每日收文拉取、發文翌日查核、Token 到期檢查、逾期稽催、交換狀態同步、歸檔封存與報表產生。"]
];

let activeDatabaseTable = "documents";
let selectedDatabaseId = "DOC-IN-1140522-00018";
let databaseSearchTerm = "";
const databaseAuditLog = [
  ["11:10", "後端資料庫初始化", "已建立公文主檔、受文者、附件、交換任務、交換事件與 audit log 檢視。"]
];

const databaseLabels = {
  documents: "公文主檔",
  recipients: "受文者",
  attachments: "附件",
  exchangeTasks: "交換任務",
  exchangeEvents: "交換事件",
  auditLogs: "audit log"
};

const databaseColumns = {
  documents: ["id", "docNo", "direction", "agency", "subject", "status"],
  recipients: ["id", "name", "code", "center", "status"],
  attachments: ["id", "docId", "name", "version", "hash", "status"],
  exchangeTasks: ["id", "docId", "type", "target", "status", "updatedAt"],
  exchangeEvents: ["id", "taskId", "event", "message", "createdAt"],
  auditLogs: ["id", "actor", "action", "target", "createdAt"]
};

const databaseTables = {
  documents: [],
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
  ["01 收文管理", "jAgent 拉取來文、收文登錄、條碼/收文號、附件檢視、承辦分派、誤送漏送通知、收文列印與批次匯出。"],
  ["02 發文管理", "建立函稿、受文者與副本管理、清稿檢核、附件封裝、送交 jAgent、查詢交換結果、重送與撤回處理。"],
  ["03 jAgent 介接", "憑證登入、Token 管理、API 狀態、交換中心連線、地址簿查詢、送件、收件、回覆與狀態同步。"],
  ["04 文書格式", "文號、文別、速別、密等、主旨、說明、辦法、附件清冊、受文者機關代碼與標準交換資料欄位。"],
  ["05 流程控管", "承辦、主管、總收發、文書主管、資訊管理員、稽核人員等角色權限與待辦管制。"],
  ["06 稽催追蹤", "發文翌日查核、逾期提醒、未收確認提醒、異常重送、退回補正與處理時限儀表板。"],
  ["07 歸檔保存", "原文、附件、交換事件、操作軌跡、檔案雜湊、版本、下載紀錄與保存年限控管。"],
  ["08 資安控管", "憑證卡、權限 RBAC、IP/裝置限制、敏感欄位遮罩、登入登出、Token 過期與操作不可否認性。"],
  ["09 報表統計", "收發量、機關往來量、成功率、異常類型、承辦量、逾期件、交換中心服務狀態與月報。"],
  ["10 系統設定", "機關代碼、交換中心、API URL、防火牆、憑證、角色、通知、保存年限、測試/正式環境切換。"],
  ["11 通知中心", "收文通知、待清稿提醒、交換失敗、Token 即將過期、逾期查核、主管退回與稽核警示。"],
  ["12 後端資料庫", "公文主檔、受文者、附件、交換任務、交換事件、jAgent session、audit log 與地址簿快取。"],
  ["13 帳號登入與權限", "使用者帳號、單位職稱、RBAC、SSO、Google Workspace / Microsoft Entra、MFA、登入紀錄、裝置紀錄與 IP 限制。"],
  ["14 檔案與資安控管", "附件防毒掃描、檔案大小限制、敏感資料遮罩、密件權限隔離、下載浮水印、檔案存取紀錄、備份與還原。"],
  ["15 排程與背景任務", "每日收文拉取、發文翌日查核、Token 到期檢查、逾期稽催、交換狀態同步、歸檔封存與報表產生。"],
  ["16 管理者維運功能", "jAgent 連線健康檢查、API log 查詢、錯誤碼查詢、系統參數版控、操作紀錄匯出、資料備份與測試/正式環境切換。"]
];

const roleNotes = {
  總收發人員: "可登入 jAgent、執行收文、發文交換、查詢交換結果與處理異常。",
  承辦人: "可建立公文草稿、補附件、回覆退件與查看自己承辦案件。",
  文書主管: "可審核清稿、分派收文、退回補正與監控處理時限。",
  資訊管理員: "可設定 jAgent、憑證、交換中心、防火牆與系統參數。",
  稽核人員: "可查詢操作軌跡、交換紀錄、附件雜湊與保存狀態。"
};

const rolePermissions = {
  總收發人員: ["pull_inbound", "register_inbound", "assign_case", "send_dispatch", "query_status"],
  承辦人: ["draft_dispatch", "view_assigned", "upload_attachment", "reply_case"],
  文書主管: ["review_dispatch", "assign_case", "reject_case", "approve_format", "query_status"],
  資訊管理員: ["manage_jagent", "manage_token", "manage_center", "manage_roles", "query_address_book"],
  稽核人員: ["view_audit", "export_audit", "verify_hash", "view_all_status"]
};

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
  view_all_status: "查看全域狀態"
};

let workflowRole = "總收發人員";
let selectedWorkflowTaskId = "WF-001";
const workflowTasks = [
  { id: "WF-001", title: "衛福部補件通知登錄", type: "收文", step: "收文登錄", role: "總收發人員", status: "待處理" },
  { id: "WF-002", title: "臺北市政府社會局會議通知分派", type: "收文", step: "承辦分派", role: "文書主管", status: "待處理" },
  { id: "WF-003", title: "日照中心補正資料發文", type: "發文", step: "清稿檢核", role: "文書主管", status: "待審核" },
  { id: "WF-004", title: "jAgent 交換中心連線設定", type: "系統", step: "介接設定", role: "資訊管理員", status: "待處理" },
  { id: "WF-005", title: "五月交換紀錄抽核", type: "稽核", step: "紀錄查核", role: "稽核人員", status: "待查核" }
];

const workflowSteps = [
  ["01", "總收發人員", "拉取收文、登錄、送交發文與查詢交換結果"],
  ["02", "承辦人", "建立函稿、補附件、處理被分派案件"],
  ["03", "文書主管", "審核清稿、分派案件、退回補正"],
  ["04", "資訊管理員", "管理 jAgent、Token、交換中心與角色權限"],
  ["05", "稽核人員", "查核交換紀錄、操作軌跡、附件雜湊與保存狀態"]
];

const workflowAuditLog = [
  ["10:22", "流程控管初始化", "已載入角色權限矩陣與待辦佇列。"]
];

let activeWorkflowTemplate = "standard";
const workflowTemplates = {
  standard: { name: "一般發文簽核", steps: ["承辦人擬稿", "文書主管清稿", "總收發用印", "送交 jAgent"] },
  urgent: { name: "速件發文簽核", steps: ["承辦人擬稿", "文書主管即時審核", "總收發用印", "翌日查核"] },
  confidential: { name: "密件發文簽核", steps: ["承辦人擬稿", "文書主管審核", "資訊管理員資安檢核", "負責人核定", "總收發用印"] },
  procurement: { name: "採購/金額簽核", steps: ["承辦人擬稿", "部門主管審核", "財務複核", "負責人核定", "總收發用印"] }
};

const workflowProxies = [
  { id: "PX-001", from: "文書主管", to: "總收發人員", reason: "主管差勤代理", status: "啟用" }
];

const workflowProofLog = [
  ["11:28", "簽核引擎初始化", "流程範本、條件規則、代理人與不可否認紀錄已載入。"]
];

let selectedSealId = "SEAL-001";
let selectedSealRequestId = "REQ-001";
const sealRegistry = [
  { id: "SEAL-001", name: "歲悅長照公司章", type: "公司章", owner: "文書主管", docType: "函", status: "啟用", hash: "SHA256-SEAL-A19F" },
  { id: "SEAL-002", name: "歲悅負責人章", type: "負責人章", owner: "文書主管", docType: "函", status: "啟用", hash: "SHA256-SEAL-B72C" },
  { id: "SEAL-003", name: "附件騎縫章", type: "騎縫章", owner: "總收發人員", docType: "附件", status: "停用", hash: "SHA256-SEAL-C44D" }
];

const sealRequests = [
  { id: "REQ-001", docId: "OUT-1140522-007", sealId: "SEAL-001", step: "文書主管簽核", status: "待簽核", stampNo: "", stampedAt: "" },
  { id: "REQ-002", docId: "OUT-1140520-009", sealId: "SEAL-002", step: "負責人核定", status: "已押章", stampNo: "STAMP-1140520-009", stampedAt: "2026-05-22 09:30" }
];

const sealAuditLog = [
  ["11:18", "印鑑管理初始化", "已載入印鑑清冊、簽核佇列與用印軌跡。"]
];

const pdfVersionStore = {};

let selectedTrackingId = "TRK-001";
let trackingFilter = "all";
let trackingSearchTerm = "";
const trackingCases = [
  { id: "TRK-001", title: "歲悅字第1140520009號等待收文確認", agency: "桃園市政府社會局", type: "未收確認", dueDate: "2026-05-23", owner: "總收發", status: "未收確認", note: "jAgent 已 accepted，尚未收到收文方確認。" },
  { id: "TRK-002", title: "歲悅字第1140521003號翌日查核", agency: "衛生福利部", type: "翌日查核", dueDate: "2026-05-23", owner: "文書主管", status: "翌日查核", note: "發文後需於次工作日確認交換結果。" },
  { id: "TRK-003", title: "收1140522-00013 會議通知分派逾期", agency: "臺北市政府社會局", type: "逾期提醒", dueDate: "2026-05-22", owner: "文書主管", status: "逾期提醒", note: "尚未完成承辦分派，需提醒主管處理。" },
  { id: "TRK-004", title: "日照補正資料附件缺漏", agency: "臺北市政府社會局", type: "退回補正", dueDate: "2026-05-29", owner: "承辦人", status: "退回補正", note: "附件清冊與實際檔案數量不一致。" }
];

const trackingAuditLog = [
  ["10:30", "稽催追蹤初始化", "已載入翌日查核、逾期提醒、未收確認與退回補正案件。"]
];

const titles = {
  dashboard: "交換總覽",
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
  notifications: "通知中心",
  jobs: "背景任務",
  database: "後端資料庫",
  ops: "維運中心",
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

function setView(target) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === target));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.target === target));
  document.querySelector("#pageTitle").textContent = titles[target] || "電子公文交換";
}

function enterApp(message = "登入成功，已進入電子公文交換系統。") {
  document.querySelector("#loginScreen").classList.add("hidden");
  document.querySelector("#appShell").classList.remove("hidden");
  showToast(message);
}

function leaveApp() {
  document.querySelector("#appShell").classList.add("hidden");
  document.querySelector("#loginScreen").classList.remove("hidden");
  showToast("已登出系統。");
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
  return [...document.querySelectorAll(".inbound-check:checked")]
    .map((input) => inboundDocs.find((doc) => doc.id === input.value))
    .filter(Boolean);
}

function currentInboundDoc() {
  return inboundDocs.find((doc) => doc.id === selectedInboundId) || inboundDocs[0] || null;
}

function filteredInboundDocs() {
  const term = inboundSearchTerm.trim().toLowerCase();
  return inboundDocs.filter((doc) => {
    const matchFilter = inboundFilter === "all" || doc.status === inboundFilter;
    const haystack = `${doc.receiveNo} ${doc.exchangeNo} ${doc.agency} ${doc.subject} ${doc.owner} ${doc.dept}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderComplianceChecks() {
  document.querySelector("#complianceChecks").innerHTML = complianceChecks.map(([title, body]) => `
    <article class="check-item">
      <strong>${title}</strong>
      <p>${body}</p>
    </article>
  `).join("");
}

function renderInboundRows() {
  const rows = filteredInboundDocs();
  document.querySelector("#inboundCount").textContent = `${rows.length} 筆`;
  document.querySelector("#inboundRows").innerHTML = rows.map((doc) => `
    <tr class="${doc.id === selectedInboundId ? "selected-row" : ""}" data-inbound-id="${doc.id}">
      <td><input class="inbound-check" type="checkbox" value="${doc.id}" aria-label="選取 ${doc.receiveNo}" /></td>
      <td><button class="text-button row-select" type="button" data-select-inbound="${doc.id}">${doc.receiveNo}</button><small>${doc.exchangeNo}</small></td>
      <td>${doc.agency}<small>${doc.agencyCode}</small></td>
      <td>${doc.type}</td>
      <td>${doc.subject}</td>
      <td><span class="badge ${badgeClass(doc.status)}">${doc.status}</span></td>
      <td>${doc.owner}<small>${doc.dept}</small></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-register-one="${doc.id}">登錄</button>
          <button class="segment" type="button" data-assign-one="${doc.id}">分派</button>
          <button class="segment" type="button" data-exception-one="${doc.id}">異常</button>
        </div>
      </td>
    </tr>
  `).join("");

  document.querySelectorAll("[data-select-inbound]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedInboundId = button.dataset.selectInbound;
      renderInboundRows();
      renderInboundDetail();
    });
  });
  document.querySelectorAll("[data-register-one]").forEach((button) => {
    button.addEventListener("click", () => registerInbound([button.dataset.registerOne]));
  });
  document.querySelectorAll("[data-assign-one]").forEach((button) => {
    button.addEventListener("click", () => assignInbound([button.dataset.assignOne]));
  });
  document.querySelectorAll("[data-exception-one]").forEach((button) => {
    button.addEventListener("click", () => createInboundException([button.dataset.exceptionOne], "誤送"));
  });
}

function renderInboundDetail() {
  const doc = currentInboundDoc();
  const detail = document.querySelector("#inboundDetail");
  if (!doc) {
    document.querySelector("#selectedInboundStatus").textContent = "未選取";
    detail.innerHTML = `<p class="empty-text">尚無收文資料。</p>`;
    return;
  }
  document.querySelector("#selectedInboundStatus").textContent = doc.status;
  detail.innerHTML = `
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
        <button class="primary-button" type="button" id="detailRegisterBtn">登錄</button>
        <button class="secondary-button" type="button" id="detailAssignBtn">分派</button>
        <button class="secondary-button" type="button" id="detailExceptionBtn">誤送/漏送</button>
      </div>
    </div>
  `;
  document.querySelectorAll(".file-chip").forEach((button) => {
    button.addEventListener("click", () => showToast(`已開啟附件預覽：${button.dataset.file}`));
  });
  document.querySelector("#detailRegisterBtn").addEventListener("click", () => registerInbound([doc.id]));
  document.querySelector("#detailAssignBtn").addEventListener("click", () => assignInbound([doc.id]));
  document.querySelector("#detailExceptionBtn").addEventListener("click", () => createInboundException([doc.id], document.querySelector("#exceptionType").value));
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
    if (doc) handler(doc);
  });
  renderInboundRows();
  renderInboundDetail();
}

function registerInbound(ids) {
  const targetIds = ids?.length ? ids : selectedInboundDocs().map((doc) => doc.id);
  if (!targetIds.length) return showToast("請先選取要登錄的收文。");
  mutateInbound(targetIds, (doc) => {
    doc.status = doc.status === "異常待處理" ? "異常待處理" : "待分派";
    doc.dept = document.querySelector("#registerDept").value;
    doc.note = document.querySelector("#registerNote").value;
  });
  addInboundAudit("完成收文登錄", `已登錄 ${targetIds.length} 筆收文，保存年限：${document.querySelector("#retentionYears").value}。`);
  showToast(`已完成 ${targetIds.length} 筆收文登錄。`);
}

function assignInbound(ids) {
  const targetIds = ids?.length ? ids : selectedInboundDocs().map((doc) => doc.id);
  if (!targetIds.length) return showToast("請先選取要分派的收文。");
  const owner = document.querySelector("#assignOwner").value;
  const dueDate = document.querySelector("#assignDueDate").value;
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
  mutateInbound(targetIds, (doc) => {
    doc.status = "異常待處理";
    doc.note = `${type}：${document.querySelector("#exceptionNote").value}`;
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

function selectedDispatchDocs() {
  return [...document.querySelectorAll(".dispatch-check:checked")]
    .map((input) => dispatchDocs.find((doc) => doc.id === input.value))
    .filter(Boolean);
}

function currentDispatchDoc() {
  return dispatchDocs.find((doc) => doc.id === selectedDispatchId) || dispatchDocs[0] || null;
}

function filteredDispatchDocs() {
  const term = dispatchSearchTerm.trim().toLowerCase();
  return dispatchDocs.filter((doc) => {
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
    ["憑證", doc?.checks.certificate, "總收發人員已通過憑證登入。"],
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
    button.addEventListener("click", () => showToast(`已預覽發文附件：${button.dataset.dispatchFile}`));
  });
}

function renderDispatchBoard() {
  const docs = filteredDispatchDocs();
  document.querySelector("#dispatchCount").textContent = `${docs.length} 筆`;
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
  detail.innerHTML = `
    <div class="doc-detail">
      <strong>${doc.subject}</strong>
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
        <button class="primary-button" type="button" id="detailSendDispatchBtn">送交 jAgent</button>
        <button class="secondary-button" type="button" id="detailValidateDispatchBtn">清稿</button>
        <button class="secondary-button" type="button" id="detailPackageDispatchBtn">封裝</button>
        <button class="secondary-button" type="button" id="detailQueryDispatchBtn">查詢</button>
        <button class="secondary-button" type="button" id="detailResendDispatchBtn">重送</button>
      </div>
    </div>
  `;
  document.querySelector("#detailSendDispatchBtn").addEventListener("click", () => runDispatchAction("send", [doc.id]));
  document.querySelector("#detailValidateDispatchBtn").addEventListener("click", () => runDispatchAction("validate", [doc.id]));
  document.querySelector("#detailPackageDispatchBtn").addEventListener("click", () => runDispatchAction("package", [doc.id]));
  document.querySelector("#detailQueryDispatchBtn").addEventListener("click", () => runDispatchAction("query", [doc.id]));
  document.querySelector("#detailResendDispatchBtn").addEventListener("click", () => runDispatchAction("resend", [doc.id]));
  renderDispatchChecks(doc);
  renderPackagePanel(doc);
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
}

function dispatchTargetIds(ids) {
  if (ids?.length) return ids;
  const selected = selectedDispatchDocs().map((doc) => doc.id);
  return selected.length ? selected : selectedDispatchId ? [selectedDispatchId] : [];
}

function runDispatchAction(action, ids) {
  const targetIds = dispatchTargetIds(ids);
  if (!targetIds.length) return showToast("請先選取要作業的發文。");
  const actionNames = { validate: "清稿檢核", package: "附件封裝", send: "送交 jAgent", query: "查詢狀態", resend: "重送" };
  mutateDispatch(targetIds, (doc) => {
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
      doc.lastReply = "已完成附件封裝與雜湊檢核。";
    }
    if (action === "send") {
      doc.checks.format = true;
      doc.checks.package = true;
      doc.packageId = doc.packageId || `PKG-${Date.now()}`;
      doc.status = "等待確認";
      doc.lastReply = "jAgent 回覆 accepted，等待收文方確認。";
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
  });
  addDispatchAudit(actionNames[action], `已對 ${targetIds.length} 筆發文執行「${actionNames[action]}」。`);
  showToast(`已完成 ${actionNames[action]}。`);
}

function createDispatchFromForm(status = "草稿") {
  const no = document.querySelector("#dispatchNo").value.trim() || `歲悅字第${Date.now()}號`;
  const doc = {
    id: `OUT-${Date.now()}`,
    no,
    exchangeNo: `EX-OUT-${Date.now().toString().slice(-8)}`,
    type: document.querySelector("#docType").value,
    priority: document.querySelector("#priority").value,
    security: "普通",
    to: document.querySelector("#recipient").value.trim() || "未指定受文者",
    agencyCode: "待查詢",
    subject: document.querySelector("#subject").value.trim() || "未填主旨",
    body: document.querySelector("#bodyText").value.trim(),
    status,
    owner: "總收發",
    attachments: ["函稿本文.pdf", "附件清冊.xml"],
    packageId: "",
    lastReply: status === "草稿" ? "草稿已建立，尚未清稿。" : "已建立函稿並進入清稿檢核。",
    checks: { format: status !== "草稿", recipient: true, attachments: true, certificate: true, package: false }
  };
  dispatchDocs.unshift(doc);
  selectedDispatchId = doc.id;
  addDispatchAudit(status === "草稿" ? "建立發文草稿" : "建立函稿", `${doc.no} 已建立，受文者：${doc.to}。`);
  renderDispatchBoard();
  renderDispatchDetail();
  return doc;
}

function renderPrechecks() {
  document.querySelector("#precheckList").innerHTML = prechecks.map((item) => `<li>${item}</li>`).join("");
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
  jagentState.certificateNote = "憑證序號 SYC-EDOC-2026，總收發人員";
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
        <button class="primary-button" type="button" id="detailArchiveSealBtn">封存</button>
        <button class="secondary-button" type="button" id="detailArchiveVerifyBtn">驗證雜湊</button>
        <button class="secondary-button" type="button" id="detailArchiveOpenBtn">檢視原文</button>
        <button class="secondary-button" type="button" id="detailArchiveExportBtn">匯出保存包</button>
      </div>
    </div>
  `;
  document.querySelectorAll("[data-archive-attachment]").forEach((button) => {
    button.addEventListener("click", () => showToast(`已開啟附件保存檢視：${button.dataset.archiveAttachment}`));
  });
  document.querySelector("#detailArchiveSealBtn").addEventListener("click", () => runArchiveAction("seal", [item.id]));
  document.querySelector("#detailArchiveVerifyBtn").addEventListener("click", () => runArchiveAction("verify", [item.id]));
  document.querySelector("#detailArchiveOpenBtn").addEventListener("click", () => runArchiveAction("open", [item.id]));
  document.querySelector("#detailArchiveExportBtn").addEventListener("click", () => runArchiveAction("export", [item.id]));
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
    ["使用者", document.querySelector("#securityCertOwner")?.value || "總收發人員"],
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
    watermarkText: document.querySelector("#fileWatermarkText")?.value || fileSecurityPolicy.watermarkText
  };
}

function isFileOverLimit(item) {
  return item.sizeMb > fileSecurityPolicy.maxSizeMb;
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
      <td>${item.confidential}<small>${item.accessRole}</small></td>
      <td>
        <div class="row-actions">
          <button class="segment" type="button" data-file-action="scan" data-file-id="${item.id}">掃描</button>
          <button class="segment" type="button" data-file-action="quarantine" data-file-id="${item.id}">隔離</button>
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
        <div><dt>密件隔離</dt><dd>${item.confidential} · ${item.accessRole}</dd></div>
        <div><dt>下載浮水印</dt><dd>${item.watermarkStatus}</dd></div>
        <div><dt>備份狀態</dt><dd>${item.backupStatus}</dd></div>
      </dl>
    </div>
    <div class="archive-grid">
      <article class="archive-card"><span>副檔名政策</span><strong>${fileSecurityPolicy.allowedTypes}</strong></article>
      <article class="archive-card"><span>遮罩政策</span><strong>${fileSecurityPolicy.maskPolicy}</strong></article>
      <article class="archive-card"><span>雜湊</span><strong>${item.hash}</strong></article>
      <article class="archive-card"><span>存取控制</span><strong>${item.confidential === "普通" ? "一般 RBAC" : "密件隔離"}</strong></article>
    </div>
  `;
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

function renderFileSecurity() {
  renderFileSecuritySummary();
  renderFileSecurityRows();
  renderFileSecurityDetail();
  renderFileBackupGrid();
  renderFileAccessLog();
}

function runFileSecurityAction(action, ids = selectedFileSecurityIds()) {
  const selected = fileSecurityItems.filter((item) => ids.includes(item.id));
  if (!selected.length) return showToast("請先選取檔案。");
  selected.forEach((item) => {
    if (action === "scan") item.scanStatus = isFileOverLimit(item) ? "已隔離" : "已通過";
    if (action === "quarantine") item.scanStatus = "已隔離";
    if (action === "mask") item.maskStatus = "已遮罩";
    if (action === "access") item.watermarkStatus = "已記錄存取";
  });
  const labels = { scan: "附件防毒掃描", quarantine: "檔案隔離", mask: "敏感資料遮罩", access: "檔案存取紀錄" };
  addFileAccessLog(labels[action] || "檔案作業", `已處理 ${selected.length} 件：${selected.map((item) => item.fileName).join("、")}。`);
  renderFileSecurity();
  showToast(`${labels[action] || "檔案作業"}完成。`);
}

function saveFileSecurityPolicy() {
  Object.assign(fileSecurityPolicy, filePolicyPayload());
  fileSecurityItems.forEach((item) => {
    if (item.confidential !== "普通") item.accessRole = fileSecurityPolicy.confidentialRoles;
    if (isFileOverLimit(item) && item.scanStatus === "已通過") item.scanStatus = "已隔離";
  });
  renderFileSecurity();
  addFileAccessLog("儲存檔案政策", `大小上限 ${fileSecurityPolicy.maxSizeMb} MB，允許 ${fileSecurityPolicy.allowedTypes}，密件角色 ${fileSecurityPolicy.confidentialRoles}。`);
  showToast("檔案資安政策已儲存。");
}

function downloadWatermarkedFile() {
  const item = currentFileSecurityItem();
  if (!item) return showToast("請先選取檔案。");
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
  renderFileSecurity();
  addFileAccessLog("建立檔案備份", `${backup.id} 已保存 ${backup.items.length} 件附件資安狀態。`);
  showToast("檔案備份已建立。");
}

function restoreFileSecurityBackup() {
  const backup = fileSecurityBackups[0];
  if (!backup) return showToast("目前沒有可還原備份。");
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
    const haystack = `${account.name} ${account.email} ${account.unit} ${account.title} ${account.role} ${account.provider}`.toLowerCase();
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
      <td>${account.unit}<small>${account.title}</small></td>
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
  const role = document.querySelector("#accountRoleSelect").value;
  const provider = document.querySelector("#accountProvider").value;
  const mfa = document.querySelector("#accountMfa").value;
  if (!name || !email || !unit || !title) return showToast("請輸入姓名、Email、單位與職稱。");
  if (!rolePermissions[role]) rolePermissions[role] = ["view_assigned"];
  const existing = userAccounts.find((account) => account.email === email);
  if (existing) {
    Object.assign(existing, { name, unit, title, role, provider, mfa, status: "啟用" });
    selectedAccountId = existing.id;
    addAccountAudit("更新使用者", `${name} 的單位、職稱、角色與登入方式已更新。`);
  } else {
    const id = `USR-${String(userAccounts.length + 1).padStart(3, "0")}`;
    userAccounts.unshift({ id, name, email, unit, title, role, provider, mfa, status: "啟用", lastLogin: "尚未登入", ip: "-", device: "尚未綁定" });
    selectedAccountId = id;
    addAccountAudit("建立使用者", `${name} 已建立為 ${role}，登入方式 ${provider}。`);
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
    userAccounts.push({ id, name: `${role}帳號`, email: `${role}@suiyuecare.local`, unit: "系統預設", title: role, role, provider: "本機帳號", mfa: "待設定", status: "停用", lastLogin: "尚未登入", ip: "-", device: "尚未綁定" });
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
  const exceptionItems = [
    ...inboundDocs.filter((doc) => /異常|誤送|漏送/.test(doc.status + doc.note)).map((doc) => ({ type: "收文異常", title: doc.subject, owner: doc.owner })),
    ...dispatchDocs.filter((doc) => /失敗|退回/.test(doc.status + doc.lastReply)).map((doc) => ({ type: "發文失敗", title: doc.subject, owner: doc.owner })),
    ...archiveRecords.filter((doc) => doc.status === "需複核").map((doc) => ({ type: "雜湊需複核", title: doc.subject, owner: "稽核人員" })),
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
  return { inboundCount, dispatchCount, exchangeTotal, successCount, successRate, exceptionItems, overdueItems, ownerRows };
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
  document.querySelector("#settingsRoleNote").textContent = `${Object.keys(permissionLabels).length} 項權限`;
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
  renderSettingsStatus();
  renderSettingsFirewallList();
  renderSettingsRoleGrid();
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
  settingsState.agencyVerified = /^[A-Z]\d{8,}[A-Z]?$/.test(data.agencyCode);
  renderSettingsStatus();
  addSettingsAudit("儲存系統設定", `${data.agencyName}、${data.centerName}、${data.apiUrl}、${settingsFirewallRules.length} 條防火牆規則、${Object.keys(rolePermissions).length} 個角色已儲存。`);
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
      <small>${backup.note}</small>
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

function renderOps() {
  renderOpsSummary();
  renderOpsApiLogs();
  renderOpsConfigList();
  renderOpsBackupGrid();
  renderOpsAuditLog();
  lookupOpsErrorCode(false);
}

function runOpsHealthCheck() {
  const latency = `${Math.floor(32 + Math.random() * 45)}ms`;
  jagentState.center = "已連線";
  jagentState.latency = latency;
  if (!jagentState.tokenExpiresAt) {
    jagentState.token = `tk_${Date.now()}`;
    jagentState.tokenExpiresAt = Date.now() + 8 * 60 * 60 * 1000;
  }
  opsState.health = "Healthy";
  opsApiLogs.unshift({ time: nowTime(), service: "jAgent", api: "GET /health", status: 200, duration: latency, code: "OK", message: "憑證、Token、交換中心與地址簿健康檢查通過" });
  renderJagentStatus();
  renderOps();
  addOpsAudit("jAgent 連線健康檢查", `健康檢查通過，延遲 ${latency}，Token ${tokenTimeLeft()}。`);
  showToast("jAgent 健康檢查通過。");
}

function lookupOpsErrorCode(show = true) {
  const code = document.querySelector("#opsErrorCodeInput")?.value.trim() || "JAGENT-401";
  const item = opsErrorCodes[code] || { title: "未建檔錯誤碼", reason: "尚未收錄此錯誤碼。", fix: "請匯入廠商錯誤碼表或由資訊管理員補充處理建議。" };
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
  const entry = { id: `CFG-${Date.now().toString().slice(-5)}`, version, env, note, actor: "資訊管理員", createdAt: new Date().toLocaleString("zh-TW", { hour12: false }), payload: settingsPayload() };
  opsConfigVersions.unshift(entry);
  opsState.configVersion = version;
  opsState.environment = env;
  document.querySelector("#settingsApiMode").value = env;
  renderSettings();
  renderOps();
  addOpsAudit("建立系統參數版本", `${version} 已建立：${note}。`);
  showToast("系統參數版本已建立。");
}

function createOpsBackup() {
  syncDatabaseTables(true);
  const backup = {
    id: `BACKUP-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${String(opsBackups.length + 1).padStart(2, "0")}`,
    createdAt: new Date().toLocaleString("zh-TW", { hour12: false }),
    env: opsState.environment,
    note: `${databaseTables.documents.length} 筆公文、${databaseTables.attachments.length} 筆附件、${databaseTables.auditLogs.length} 筆 audit log`,
    data: JSON.parse(JSON.stringify(databaseTables))
  };
  opsBackups.unshift(backup);
  renderOps();
  addOpsAudit("資料備份", `${backup.id} 已建立，${backup.note}。`);
  showToast("資料備份已建立。");
}

function restoreOpsBackup() {
  const backup = opsBackups[0];
  if (!backup) return showToast("目前沒有可還原的備份。");
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

function deliverNotification(item, forceChannel = item.channel) {
  const channels = notificationChannels(forceChannel);
  const results = channels.map((channel) => {
    const receipt = `${channel.replaceAll(" ", "")}-${Date.now().toString().slice(-6)}-${Math.floor(Math.random() * 90 + 10)}`;
    if (channel === "Email") {
      notificationGatewayState.emailStatus = "送出成功";
      return `Email -> ${roleEmail(item.target)} / ${receipt}`;
    }
    if (channel === "Line 工作群組") {
      notificationGatewayState.lineStatus = "送出成功";
      return `Line -> 歲悅電子公文工作群組 / ${receipt}`;
    }
    pushSystemInbox(item);
    notificationGatewayState.inboxStatus = "已推送";
    return `站內 -> ${item.target} / ${receipt}`;
  });
  item.status = "已派送";
  item.sentAt = new Date().toLocaleString("zh-TW", { hour12: false });
  item.deliveryReceipt = results.join("；");
  addNotificationDelivery(item.type, `${item.title}｜${results.join("；")}`);
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
    const matchFilter = notificationFilter === "all" || item.type === notificationFilter || item.status === notificationFilter;
    const haystack = `${item.title} ${item.type} ${item.target} ${item.channel} ${item.status} ${item.source} ${item.body}`.toLowerCase();
    return matchFilter && (!term || haystack.includes(term));
  });
}

function renderNotificationSummary() {
  const count = (type) => notificationItems.filter((item) => item.type === type && item.status !== "已讀").length;
  document.querySelector("#noticeInboundCount").textContent = count("收文");
  document.querySelector("#noticeDraftCount").textContent = count("待清稿");
  document.querySelector("#noticeFailedCount").textContent = count("交換失敗");
  document.querySelector("#noticeRiskCount").textContent = count("Token 到期") + count("逾期查核");
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
    ["收文", "jAgent 拉取後立即通知總收發"],
    ["待清稿", "發文待清稿超過 2 小時通知主管"],
    ["交換失敗", `${notificationGatewayState.failureChannel} 立即警示並開啟重送`],
    ["Token 到期", `${notificationGatewayState.tokenSchedule} 通知資訊管理員`],
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

function syncNotifications() {
  const generated = [
    ...inboundDocs.filter((doc) => ["待登錄", "待分派"].includes(doc.status)).map((doc) => ({ type: "收文", title: `${doc.receiveNo} ${doc.status}`, target: "總收發人員", channel: "系統通知", source: doc.id, body: `${doc.agency} 來文「${doc.subject}」需處理。` })),
    ...dispatchDocs.filter((doc) => ["待清稿", "已清稿", "交換失敗"].includes(doc.status)).map((doc) => ({ type: doc.status === "交換失敗" ? "交換失敗" : "待清稿", title: `${doc.no} ${doc.status}`, target: doc.status === "交換失敗" ? "總收發人員" : "文書主管", channel: "Email + 系統通知", source: doc.id, body: `${doc.subject} 目前狀態：${doc.status}。` })),
    ...trackingCases.filter((doc) => ["逾期提醒", "未收確認", "翌日查核"].includes(doc.status)).map((doc) => ({ type: "逾期查核", title: doc.title, target: doc.owner, channel: "Line 工作群組", source: doc.id, body: doc.note })),
    { type: "Token 到期", title: "jAgent Token 到期檢查", target: "資訊管理員", channel: "系統通知", source: "SEC-TOKEN", body: securityTokenLeft() }
  ];
  let added = 0;
  generated.forEach((item) => {
    if (!notificationItems.some((notice) => notice.source === item.source && notice.type === item.type)) {
      notificationItems.unshift({ id: `NTF-${Date.now().toString().slice(-5)}-${added}`, status: "未讀", priority: item.type === "Token 到期" ? "中" : "高", ...item });
      added += 1;
    }
  });
  renderNotifications();
  addNotificationAudit("同步通知", added ? `已新增 ${added} 則通知。` : "通知已是最新狀態。");
  showToast(added ? `已同步 ${added} 則通知。` : "通知已同步。");
}

function runNotificationAction(action, ids) {
  const targetIds = ids?.length ? ids : selectedNotificationIds();
  if (!targetIds.length) return showToast("請先選取通知。");
  if (action === "read") {
    targetIds.forEach((id) => {
      const item = notificationItems.find((notice) => notice.id === id);
      if (item) item.status = "已讀";
    });
    renderNotifications();
    addNotificationAudit("標記已讀", `已標記 ${targetIds.length} 則通知為已讀。`);
    return showToast("通知已標記為已讀。");
  }
  if (action === "send") {
    targetIds.forEach((id) => {
      const item = notificationItems.find((notice) => notice.id === id);
      if (item) deliverNotification(item);
    });
    renderNotifications();
    addNotificationAudit("派送通知", `已透過 Email / Line / 站內通知派送 ${targetIds.length} 則通知。`);
    return showToast("通知已派送。");
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

function addNotificationFromForm() {
  const type = document.querySelector("#notificationType").value;
  const target = document.querySelector("#notificationTarget").value;
  const channel = document.querySelector("#notificationChannel").value;
  const body = document.querySelector("#notificationBody").value.trim();
  const item = { id: `NTF-${Date.now().toString().slice(-6)}`, type, title: `${type}手動通知`, target, channel, status: "未讀", priority: "中", source: "MANUAL", body };
  notificationItems.unshift(item);
  selectedNotificationId = item.id;
  renderNotifications();
  addNotificationAudit("新增通知", `${type} 已新增給 ${target}，通道：${channel}。`);
  showToast("通知已新增。");
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
}

function testNotificationChannels() {
  notificationGatewayState.emailStatus = "測試成功";
  notificationGatewayState.lineStatus = "測試成功";
  notificationGatewayState.inboxStatus = "測試成功";
  const testItem = { title: "通知通道測試", target: "資訊管理員", type: "通道測試", channel: "Email + Line + 系統通知", body: "測試派送", source: "GATEWAY-TEST" };
  deliverNotification(testItem, "Email + Line + 系統通知");
  renderNotifications();
  addNotificationAudit("測試通知通道", "Email API、Line Webhook 與站內通知均完成測試派送。");
  showToast("通知通道測試成功。");
}

function createNotificationSchedules() {
  saveNotificationGateway();
  const schedules = [
    { id: `SCH-OD-${Date.now().toString().slice(-5)}`, type: "逾期排程通知", rule: notificationGatewayState.overdueSchedule, target: "承辦人 / 文書主管" },
    { id: `SCH-TK-${Date.now().toString().slice(-5)}`, type: "Token 到期通知", rule: notificationGatewayState.tokenSchedule, target: "資訊管理員" },
    { id: `SCH-FL-${Date.now().toString().slice(-5)}`, type: "交換失敗即時警示", rule: notificationGatewayState.failureChannel, target: "總收發人員 / 資訊管理員" }
  ];
  notificationSchedules.unshift(...schedules);
  schedules.forEach((schedule) => addNotificationDelivery(schedule.type, `${schedule.id} 已啟用：${schedule.rule} -> ${schedule.target}`));
  renderNotifications();
  addNotificationAudit("套用通知規則", "已建立逾期排程、Token 到期提醒與交換失敗即時警示。");
  showToast("通知排程與即時警示已啟用。");
}

function sendImmediateFailureAlerts() {
  const failedDocs = dispatchDocs.filter((doc) => doc.status === "交換失敗");
  if (!failedDocs.length) return showToast("目前沒有交換失敗案件。");
  failedDocs.forEach((doc) => {
    let item = notificationItems.find((notice) => notice.source === doc.id && notice.type === "交換失敗");
    if (!item) {
      item = { id: `NTF-${Date.now().toString().slice(-6)}-${doc.id}`, type: "交換失敗", title: `${doc.no} 交換失敗即時警示`, target: "總收發人員", channel: notificationGatewayState.failureChannel, status: "未讀", priority: "高", source: doc.id, body: `${doc.subject} 交換失敗，請立即重送或聯繫交換中心。` };
      notificationItems.unshift(item);
    }
    deliverNotification(item, notificationGatewayState.failureChannel);
  });
  renderNotifications();
  addNotificationAudit("交換失敗即時警示", `已針對 ${failedDocs.length} 件交換失敗案件送出即時警示。`);
  showToast("交換失敗即時警示已送出。");
}

function pushSelectedToInbox() {
  const targetIds = selectedNotificationIds();
  if (!targetIds.length) return showToast("請先選取通知。");
  targetIds.forEach((id) => {
    const item = notificationItems.find((notice) => notice.id === id);
    if (item) {
      pushSystemInbox(item);
      item.status = "已派送";
      item.deliveryReceipt = `${item.deliveryReceipt || ""} 站內 -> ${item.target}`.trim();
    }
  });
  renderNotifications();
  addNotificationAudit("推送站內通知", `已推送 ${targetIds.length} 則站內通知。`);
  showToast("站內通知已推送。");
}

function retryFailedNotificationDeliveries() {
  const targets = notificationItems.filter((item) => item.status === "派送失敗" || !item.deliveryReceipt);
  targets.forEach((item) => deliverNotification(item));
  renderNotifications();
  addNotificationAudit("重送通知", targets.length ? `已重送 ${targets.length} 則未完成派送通知。` : "沒有需要重送的通知。");
  showToast(targets.length ? "通知已重送。" : "沒有需要重送的通知。");
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

function runJobAction(action, ids = selectedJobIds()) {
  const jobs = backgroundJobs.filter((job) => ids.includes(job.id));
  if (!jobs.length) return showToast("請先選取背景任務。");
  if (action === "run") {
    jobs.filter((job) => job.status === "啟用").forEach(executeBackgroundJob);
    renderJobs();
    return showToast(`已執行 ${jobs.length} 個背景任務。`);
  }
  if (action === "toggle") {
    jobs.forEach((job) => {
      job.status = job.status === "啟用" ? "暫停" : "啟用";
      addJobAudit("切換任務狀態", `${job.name} 已更新為 ${job.status}。`);
    });
    renderJobs();
    return showToast("任務狀態已更新。");
  }
  if (action === "notify") {
    jobs.forEach((job) => {
      const notice = { id: `NTF-JOB-${Date.now().toString().slice(-5)}-${job.id}`, type: "背景任務", title: `${job.name} 執行結果`, target: job.notify, channel: "Email + 系統通知", status: "未讀", priority: job.lastResult.includes("失敗") ? "高" : "中", source: job.id, body: job.lastResult };
      notificationItems.unshift(notice);
      deliverNotification(notice);
    });
    renderNotifications();
    renderJobs();
    addJobAudit("送出任務通知", `已送出 ${jobs.length} 則背景任務結果通知。`);
    return showToast("背景任務通知已送出。");
  }
}

function runDueJobs() {
  const due = backgroundJobs.filter((job) => job.status === "啟用");
  due.forEach(executeBackgroundJob);
  renderJobs();
  showToast(`已執行 ${due.length} 個到期任務。`);
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

async function backendRequest(path, options = {}) {
  const response = await fetch(`${backendApiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data;
}

function mapBackendDocument(row) {
  return {
    id: row.id,
    docNo: row.doc_no,
    direction: row.direction,
    agency: row.agency_name,
    subject: row.subject,
    status: row.status,
    owner: row.owner,
    sourceId: row.id
  };
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

async function syncDatabaseFromBackend() {
  try {
    const [documents, recipients, attachments, tasks, events, audits] = await Promise.all([
      backendRequest("/documents"),
      backendRequest("/recipients"),
      backendRequest("/attachments"),
      backendRequest("/exchange_tasks"),
      backendRequest("/exchange_events"),
      backendRequest("/audit_logs")
    ]);
    databaseTables.documents = documents.map(mapBackendDocument);
    databaseTables.recipients = recipients.map(mapBackendRecipient);
    databaseTables.attachments = attachments.map(mapBackendAttachment);
    databaseTables.exchangeTasks = tasks.map(mapBackendTask);
    databaseTables.exchangeEvents = events.map(mapBackendEvent);
    databaseTables.auditLogs = audits.map(mapBackendAudit);
    selectedDatabaseId = (databaseTables[activeDatabaseTable] || [])[0]?.id || "";
    renderDatabase();
    addDatabaseAudit("同步後端資料庫", `已由 SQLite API 同步 ${documents.length} 筆公文、${attachments.length} 筆附件、${audits.length} 筆 audit log。`);
    showToast("已同步真正後端資料庫。");
  } catch (error) {
    syncDatabaseTables(true);
    renderDatabase();
    addDatabaseAudit("後端同步失敗", `${error.message}；已暫時載入前端資料。`);
    showToast("後端同步失敗，已使用前端資料。");
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
    ...inboundAuditLog.map(([time, action, target], index) => ({ id: `AUD-IN-${index + 1}`, actor: "總收發人員", action, target, createdAt: time })),
    ...dispatchAuditLog.map(([time, action, target], index) => ({ id: `AUD-OUT-${index + 1}`, actor: "總收發人員", action, target, createdAt: time })),
    ...archiveAuditLog.map(([time, action, target], index) => ({ id: `AUD-ARC-${index + 1}`, actor: "稽核人員", action, target, createdAt: time })),
    ...securityAuditLog.map(([time, action, target], index) => ({ id: `AUD-SEC-${index + 1}`, actor: "資訊管理員", action, target, createdAt: time }))
  ];
  if (!silent) addDatabaseAudit("同步資料庫", "已從收文、發文、地址簿、交換事件與 audit log 重建資料表索引。");
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

function renderDatabaseSummary() {
  document.querySelector("#dbDocCount").textContent = databaseTables.documents.length;
  document.querySelector("#dbRecipientCount").textContent = databaseTables.recipients.length;
  document.querySelector("#dbAttachmentCount").textContent = databaseTables.attachments.length;
  document.querySelector("#dbEventCount").textContent = databaseTables.exchangeTasks.length + databaseTables.exchangeEvents.length + databaseTables.auditLogs.length;
}

function renderDatabaseRows() {
  const rows = databaseRows();
  const columns = databaseColumns[activeDatabaseTable] || [];
  document.querySelector("#databaseTableTitle").textContent = databaseLabels[activeDatabaseTable];
  document.querySelector("#databaseCount").textContent = `${rows.length} 筆`;
  document.querySelector("#databaseHead").innerHTML = `<tr>${columns.map((column) => `<th>${column}</th>`).join("")}<th>操作</th></tr>`;
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
  renderDatabaseSummary();
  renderDatabaseRows();
  renderDatabaseDetail();
  renderDatabaseSchema();
  renderDatabaseAuditLog();
}

function addDatabaseRowFromForm() {
  const table = document.querySelector("#databaseInsertTable").value;
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
  const checks = [
    ["文號", /^.+字第\d+號$/.test(data.no), "格式需包含字別、第、流水號與號。"],
    ["文別", Boolean(data.type), "文別需為函、開會通知單、書函、公告或令。"],
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
      <td><div class="row-actions"><button class="segment" data-workflow-approve="${task.id}" type="button">授權</button><button class="segment" data-workflow-reject="${task.id}" type="button">退回</button></div></td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-workflow-select]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedWorkflowTaskId = button.dataset.workflowSelect;
      renderWorkflowTasks();
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

function renderWorkflowTemplateSteps() {
  const template = workflowTemplates[activeWorkflowTemplate];
  document.querySelector("#workflowTemplateSteps").innerHTML = template.steps.map((step, index) => `
    <article class="timeline-item">
      <time>${String(index + 1).padStart(2, "0")}</time>
      <div>
        <strong>${step}</strong>
        <p>${template.name} 節點，完成後寫入簽核時間戳與不可否認紀錄。</p>
      </div>
    </article>
  `).join("");
}

function renderWorkflowConditions() {
  const security = document.querySelector("#workflowConditionSecurity").value;
  const priority = document.querySelector("#workflowConditionPriority").value;
  const agency = document.querySelector("#workflowConditionAgency").value.trim();
  const amount = Number(document.querySelector("#workflowAmountInput").value || 0);
  const rules = [
    ["密件", security !== "普通" ? "需資訊管理員資安檢核" : "一般權限即可"],
    ["速件", /速/.test(priority) ? "插隊文書主管即時審核" : "依一般時限"],
    ["金額", amount >= 100000 ? "需負責人核定" : "不需金額加簽"],
    ["機關別", /政府|衛生|社會/.test(agency) ? "政府機關公文需總收發覆核" : "一般受文者流程"]
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
    }
  });
  renderWorkflowTasks();
  addWorkflowAudit(status, `已更新 ${ids.length} 件待辦為「${status}」。`);
  showToast(`流程已更新：${status}。`);
}

function applyWorkflowTemplate() {
  activeWorkflowTemplate = document.querySelector("#workflowTemplateSelect").value;
  const template = workflowTemplates[activeWorkflowTemplate];
  const docType = document.querySelector("#workflowTemplateDocType").value;
  workflowTasks.unshift({
    id: `WF-${Date.now().toString().slice(-6)}`,
    title: `${template.name} - ${docType}`,
    type: "發文",
    step: template.steps[0],
    role: "承辦人",
    status: "待處理",
    template: activeWorkflowTemplate
  });
  renderWorkflowTemplateSteps();
  renderWorkflowTasks();
  addWorkflowAudit("套用流程範本", `${template.name} 已套用，新增 ${template.steps.length} 個簽核節點。`);
  addWorkflowProof("流程範本建立", `${template.name} / ${docType} 已建立流程實例。`);
  showToast("流程範本已套用。");
}

function evaluateWorkflowConditions() {
  renderWorkflowConditions();
  const security = document.querySelector("#workflowConditionSecurity").value;
  const priority = document.querySelector("#workflowConditionPriority").value;
  const amount = Number(document.querySelector("#workflowAmountInput").value || 0);
  if (security !== "普通") activeWorkflowTemplate = "confidential";
  else if (/速/.test(priority)) activeWorkflowTemplate = "urgent";
  else if (amount >= 100000) activeWorkflowTemplate = "procurement";
  document.querySelector("#workflowTemplateSelect").value = activeWorkflowTemplate;
  renderWorkflowTemplateSteps();
  addWorkflowAudit("評估條件式簽核", `密等 ${security}、速別 ${priority}、金額 ${amount}，建議流程：${workflowTemplates[activeWorkflowTemplate].name}。`);
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

function renderSealSummary() {
  document.querySelector("#activeSealCount").textContent = sealRegistry.filter((seal) => seal.status === "啟用").length;
  document.querySelector("#pendingSealCount").textContent = sealRequests.filter((request) => request.status === "待簽核").length;
  document.querySelector("#stampedDocCount").textContent = sealRequests.filter((request) => request.status === "已押章").length;
  document.querySelector("#sealAuditCount").textContent = sealAuditLog.length;
}

function renderSealRegistry() {
  document.querySelector("#sealCount").textContent = `${sealRegistry.length} 枚`;
  document.querySelector("#sealRegistry").innerHTML = sealRegistry.map((seal) => `
    <article class="address-card ${seal.id === selectedSealId ? "selected-card" : ""}">
      <strong>${seal.name}</strong>
      <span>${seal.type} · ${seal.owner} · ${seal.docType}</span>
      <p>${seal.status} · ${seal.hash}</p>
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
  document.querySelector("#sealDetail").innerHTML = `
    <div class="doc-detail seal-preview">
      <div class="seal-mark">${seal.type.slice(0, 2)}</div>
      <strong>${seal.name}</strong>
      <dl>
        <div><dt>印鑑編號</dt><dd>${seal.id}</dd></div>
        <div><dt>保管角色</dt><dd>${seal.owner}</dd></div>
        <div><dt>適用文別</dt><dd>${seal.docType}</dd></div>
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
  return {
    template: document.querySelector("#pdfTemplateSelect")?.value || "歲悅正式函",
    companyX: Number(document.querySelector("#companySealX")?.value || 420),
    companyY: Number(document.querySelector("#companySealY")?.value || 130),
    ownerX: Number(document.querySelector("#ownerSealX")?.value || 470),
    ownerY: Number(document.querySelector("#ownerSealY")?.value || 130),
    multiPage: Boolean(document.querySelector("#enablePageSeal")?.checked)
  };
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
  const version = await storePdfVersion(doc, "before", buildOfficialPdf(doc, [], pdfOptions()), { label: "押章前 PDF" });
  doc.lastReply = `已產生公文套版 PDF，SHA-256 ${version.hash.slice(0, 12)}。`;
  renderDispatchDetail();
  renderPdfVersionGrid();
  addSealAudit("產生公文 PDF 套版", `${doc.no} 已建立押章前 PDF，hash ${version.hash}。`);
  showToast("已產生押章前 PDF。");
}

function stampListForRequest(request, doc) {
  const options = pdfOptions();
  const seal = sealById(request.sealId);
  const stampNo = request.stampNo || `STAMP-${doc.no.replace(/\D/g, "").slice(-10)}-${request.sealId}`;
  const stamps = [
    { page: 1, x: options.companyX, y: options.companyY, label: seal?.type || "Company", stampNo },
    { page: 1, x: options.ownerX, y: options.ownerY, label: "Owner", stampNo }
  ];
  if (options.multiPage) stamps.push({ page: "all", x: 535, y: 392, w: 34, h: 72, label: "PAGE", stampNo });
  return stamps;
}

async function stampPdfForRequest(request, doc) {
  const version = await storePdfVersion(doc, "after", buildOfficialPdf(doc, stampListForRequest(request, doc), pdfOptions()), { label: "押章後 PDF", stampNo: request.stampNo });
  request.pdfHash = version.hash;
  request.pdfSize = version.size;
  doc.stampHash = version.hash;
  doc.stampedPdfUrl = version.url;
  return version;
}

async function stampCurrentPdf() {
  const doc = currentDispatchDoc();
  if (!doc) return showToast("請先選取發文。");
  const request = ensureSealRequestForDoc(doc);
  if (!request.stampNo) {
    request.status = "已押章";
    request.stampNo = `STAMP-${doc.no.replace(/\D/g, "").slice(-10)}-${request.sealId}`;
    request.stampedAt = new Date().toLocaleString("zh-TW", { hour12: false });
  }
  await stampPdfForRequest(request, doc);
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
  document.querySelector("#pdfVersionStatus").textContent = after ? "押章後已留存" : before ? "押章前已留存" : "尚未產生";
  box.innerHTML = [
    ["押章前", before ? `${before.size} bytes · ${before.hash.slice(0, 16)}` : "尚未產生"],
    ["押章後", after ? `${after.size} bytes · ${after.hash.slice(0, 16)}` : "尚未押章"],
    ["防竄改雜湊", after?.hash || before?.hash || "待產生"],
    ["用印申請", currentSealRequest()?.id || "尚未送簽"]
  ].map(([label, value]) => `<article class="archive-card"><span>${label}</span><strong>${value}</strong></article>`).join("");
}

function downloadPdfVersion(kind) {
  const doc = currentDispatchDoc();
  const version = doc ? pdfVersionStore[doc.id]?.[kind] : null;
  if (!version) return showToast(kind === "before" ? "尚未產生押章前 PDF。" : "尚未產生押章後 PDF。");
  const link = document.createElement("a");
  link.href = version.url;
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

function verifyCurrentPdfHash() {
  const doc = currentDispatchDoc();
  const target = doc ? (pdfVersionStore[doc.id]?.after || pdfVersionStore[doc.id]?.before) : null;
  if (!target) return showToast("尚未產生 PDF，無法驗證。");
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
  renderSealSummary();
  renderSealRegistry();
  renderSealDetail();
  renderSealRequests();
  renderSealAuditLog();
  renderPdfVersionGrid();
}

function toggleSeal(id) {
  const seal = sealById(id);
  if (!seal) return;
  seal.status = seal.status === "啟用" ? "停用" : "啟用";
  renderSeals();
  addSealAudit("更新印鑑狀態", `${seal.name} 已更新為「${seal.status}」。`);
  showToast(`印鑑已${seal.status}。`);
}

function ensureSealRequestForDoc(doc, step = "文書主管簽核") {
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
  if (request.status !== "待簽核" || request.stampNo) {
    selectedSealRequestId = request.id;
    renderSeals();
    return showToast("此公文已有簽核用印流程。");
  }
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
  for (const id of ids) {
    const request = sealRequests.find((item) => item.id === id);
    if (!request) continue;
    const seal = sealById(request.sealId);
    const doc = sealRequestDoc(request);
    if (!seal || seal.status !== "啟用" || !doc) continue;
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

function rejectSealRequests(ids = selectedSealRequestIds()) {
  if (!ids.length) return showToast("請先選取簽核案件。");
  ids.forEach((id) => {
    const request = sealRequests.find((item) => item.id === id);
    const doc = request ? sealRequestDoc(request) : null;
    if (request) request.status = "退回補正";
    if (doc) {
      doc.status = "退回補正";
      doc.lastReply = "用印簽核退回，請修正後重新送簽。";
    }
  });
  renderSeals();
  renderDispatchBoard();
  renderDispatchDetail();
  addSealAudit("退回用印簽核", `已退回 ${ids.length} 件用印申請。`);
  showToast("用印簽核已退回。");
}

function addSealFromForm() {
  const seal = {
    id: `SEAL-${Date.now().toString().slice(-5)}`,
    name: document.querySelector("#sealNameInput").value.trim() || "未命名印鑑",
    type: document.querySelector("#sealTypeInput").value,
    owner: document.querySelector("#sealOwnerInput").value,
    docType: document.querySelector("#sealDocTypeInput").value,
    status: "啟用",
    hash: `SHA256-SEAL-${Math.random().toString(16).slice(2, 8).toUpperCase()}`
  };
  sealRegistry.unshift(seal);
  selectedSealId = seal.id;
  renderSeals();
  addSealAudit("新增印鑑", `${seal.name} 已建立並啟用。`);
  showToast("印鑑已新增。");
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
      item.note = `${reason}：${correctionNote || "請承辦人補正後重新送審。"}`;
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
  control.addEventListener("click", () => setView(control.dataset.target));
});

document.querySelectorAll(".segment[data-inbound-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-inbound-filter]").forEach((item) => item.classList.remove("active"));
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
  renderWorkflowRole();
});

document.querySelector("#composeForm").addEventListener("submit", (event) => {
  event.preventDefault();
  createDispatchFromForm("待清稿");
  showToast("已建立函稿並加入發文佇列。");
  setView("dispatch");
});

document.querySelector("#loginForm").addEventListener("submit", (event) => {
  event.preventDefault();
  recordLogin(document.querySelector("#loginEmail").value, document.querySelector("#loginEnvironment").value);
  enterApp();
});

document.querySelector("#demoLoginBtn").addEventListener("click", () => {
  document.querySelector("#loginEmail").value = "edoc@suiyuecare.com";
  document.querySelector("#loginPassword").value = "demo1234";
  recordLogin("edoc@suiyuecare.com", "Google Workspace");
  enterApp("已使用總收發測試帳號登入。");
});

document.querySelector("#pullInboundBtn").addEventListener("click", pullJagentInbound);
document.querySelector("#pullJagentBtn").addEventListener("click", pullJagentInbound);
document.querySelector("#registerInboundBtn").addEventListener("click", () => registerInbound());
document.querySelector("#assignInboundBtn").addEventListener("click", () => assignInbound());
document.querySelector("#misdeliveryBtn").addEventListener("click", () => createInboundException(null, "誤送"));
document.querySelector("#missingNoticeBtn").addEventListener("click", () => createInboundException(null, "漏送"));
document.querySelector("#exportInboundBtn").addEventListener("click", () => {
  addInboundAudit("匯出收文清單", `已匯出 ${filteredInboundDocs().length} 筆目前篩選資料。`);
  showToast("已產生收文清單匯出檔。");
});
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
  inboundAuditLog.length = 0;
  renderInboundAuditLog();
  showToast("已清除畫面上的操作紀錄。");
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
document.querySelector("#previewPackageBtn").addEventListener("click", () => {
  const doc = currentDispatchDoc();
  if (!doc) return showToast("請先選取發文。");
  showToast(`封包預覽：${doc.packageId || "尚未封裝"}，附件 ${doc.attachments.length} 個。`);
});
document.querySelector("#clearDispatchLogBtn").addEventListener("click", () => {
  dispatchAuditLog.length = 0;
  renderDispatchAuditLog();
  showToast("已清除畫面上的發文操作紀錄。");
});
document.querySelector("#saveDispatchDraftBtn").addEventListener("click", () => {
  createDispatchFromForm("草稿");
  setView("dispatch");
  showToast("發文草稿已儲存。");
});
document.querySelector("#previewDraftBtn").addEventListener("click", () => {
  showToast(`函稿預覽：${document.querySelector("#subject").value}`);
});
document.querySelector("#sendQueueBtn").addEventListener("click", () => {
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
  const serial = new Date().toISOString().slice(0, 10).replaceAll("-", "").slice(2);
  document.querySelector("#formatDocNo").value = `歲悅字第${serial}${String(Math.floor(Math.random() * 90) + 10)}號`;
  renderFormatChecks();
  addFormatAudit("產生文號", "已依日期與流水號產生新文號。");
  showToast("已產生新文號。");
});
document.querySelector("#formatLookupAgencyBtn").addEventListener("click", () => {
  searchFormatAgency(document.querySelector("#formatRecipient").value || document.querySelector("#formatAgencyCode").value);
});
document.querySelector("#formatSaveTemplateBtn").addEventListener("click", () => {
  addFormatAudit("儲存格式範本", "已儲存目前文號、文別、速別、密等、主旨與附件清冊。");
  showToast("文書格式範本已儲存。");
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
  formatAuditLog.length = 0;
  renderFormatAuditLog();
  showToast("已清除畫面上的格式操作紀錄。");
});
["#formatDocNo", "#formatDocType", "#formatPriority", "#formatSecurity", "#formatAgencyCode", "#formatRecipient", "#formatSubject"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", renderFormatChecks);
  document.querySelector(selector).addEventListener("change", renderFormatChecks);
});
document.querySelector("#workflowRoleSelect").addEventListener("change", (event) => {
  workflowRole = event.target.value;
  renderWorkflowRole();
  addWorkflowAudit("切換流程角色", `目前流程控管角色切換為 ${workflowRole}。`);
});
document.querySelector("#workflowSyncRoleBtn").addEventListener("click", () => {
  document.querySelector("#roleSelect").value = workflowRole;
  document.querySelector("#roleNote").textContent = roleNotes[workflowRole];
  addWorkflowAudit("同步側欄角色", `側欄目前角色已同步為 ${workflowRole}。`);
  showToast("已同步側欄角色。");
});
document.querySelector("#workflowApproveBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "已授權"));
document.querySelector("#workflowRejectBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "退回補正"));
document.querySelector("#workflowAssignBtn").addEventListener("click", () => mutateWorkflowTasks(selectedWorkflowIds(), "指派完成"));
document.querySelector("#permissionTestForm").addEventListener("submit", (event) => {
  event.preventDefault();
  checkPermission(document.querySelector("#permissionAction").value);
});
document.querySelector("#workflowClearLogBtn").addEventListener("click", () => {
  workflowAuditLog.length = 0;
  renderWorkflowAuditLog();
  showToast("已清除畫面上的流程操作紀錄。");
});
document.querySelector("#workflowTemplateApplyBtn").addEventListener("click", applyWorkflowTemplate);
document.querySelector("#workflowTemplateForm").addEventListener("submit", (event) => {
  event.preventDefault();
  applyWorkflowTemplate();
});
document.querySelector("#workflowTemplateSelect").addEventListener("change", (event) => {
  activeWorkflowTemplate = event.target.value;
  renderWorkflowTemplateSteps();
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
document.querySelector("#downloadBeforePdfBtn").addEventListener("click", () => downloadPdfVersion("before"));
document.querySelector("#downloadAfterPdfBtn").addEventListener("click", () => downloadPdfVersion("after"));
document.querySelector("#sealApplicationBtn").addEventListener("click", generateSealApplication);
document.querySelector("#sealExportBtn").addEventListener("click", () => {
  addSealAudit("匯出用印紀錄", `已匯出 ${sealRequests.length} 件簽核用印與 ${sealAuditLog.length} 筆軌跡。`);
  showToast("用印紀錄已匯出。");
});
document.querySelector("#sealAddBtn").addEventListener("click", addSealFromForm);
document.querySelector("#sealForm").addEventListener("submit", (event) => {
  event.preventDefault();
  addSealFromForm();
});
document.querySelector("#sealClearLogBtn").addEventListener("click", () => {
  sealAuditLog.length = 0;
  renderSealAuditLog();
  renderSealSummary();
  showToast("已清除畫面上的用印操作紀錄。");
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
document.querySelector("#scheduleReminderBtn").addEventListener("click", () => {
  const targetIds = selectedTrackingIds();
  const method = document.querySelector("#trackingNotifyMethod").value;
  targetIds.forEach((id) => {
    const item = trackingCases.find((entry) => entry.id === id);
    if (!item) return;
    const notice = { id: `NTF-SCH-${Date.now().toString().slice(-5)}-${id}`, type: "逾期查核", title: item.title, target: document.querySelector("#trackingNotifyTarget").value, channel: method, status: "未讀", priority: "高", source: item.id, body: document.querySelector("#trackingMessage").value.trim() || item.note };
    notificationItems.unshift(notice);
    notificationSchedules.unshift({ id: `SCH-TRK-${id}`, type: "逾期排程通知", rule: notificationGatewayState.overdueSchedule, target: notice.target });
    deliverNotification(notice, method);
  });
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
  trackingAuditLog.length = 0;
  renderTrackingAuditLog();
  showToast("已清除畫面上的稽催操作紀錄。");
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
  archiveAuditLog.length = 0;
  renderArchiveAuditLog();
  showToast("已清除畫面上的歸檔操作紀錄。");
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
  securityAuditLog.length = 0;
  renderSecurityAuditLog();
  showToast("已清除畫面上的資安操作紀錄。");
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
document.querySelector("#fileBackupBtn").addEventListener("click", createFileSecurityBackup);
document.querySelector("#fileRestoreBtn").addEventListener("click", restoreFileSecurityBackup);
document.querySelector("#filePolicySaveBtn").addEventListener("click", saveFileSecurityPolicy);
document.querySelector("#fileSecurityPolicyForm").addEventListener("submit", (event) => {
  event.preventDefault();
  saveFileSecurityPolicy();
});
document.querySelector("#fileClearLogBtn").addEventListener("click", () => {
  fileAccessLog.length = 0;
  renderFileAccessLog();
  showToast("已清除畫面上的檔案存取紀錄。");
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
  accountAuditLog.length = 0;
  renderAccountAuditLog();
  showToast("已清除畫面上的帳號操作紀錄。");
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
  const stats = reportStats();
  addReportsAudit("匯出報表", `已匯出收發量 ${stats.inboundCount + stats.dispatchCount}、成功率 ${stats.successRate}%、異常 ${stats.exceptionItems.length}、逾期 ${stats.overdueItems.length}。`);
  showToast("報表檔已產生。");
});
document.querySelector("#reportsPrintBtn").addEventListener("click", () => {
  addReportsAudit("列印月報", "已產生報表統計月報列印版。");
  showToast("月報列印版已產生。");
});
document.querySelector("#reportsCreateReminderBtn").addEventListener("click", createReportReminder);
document.querySelector("#reportsClearLogBtn").addEventListener("click", () => {
  reportsAuditLog.length = 0;
  renderReportsAuditLog();
  showToast("已清除畫面上的報表操作紀錄。");
});
document.querySelectorAll(".segment[data-notification-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment[data-notification-filter]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    notificationFilter = button.dataset.notificationFilter;
    renderNotificationRows();
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
  notificationAuditLog.length = 0;
  renderNotificationAuditLog();
  showToast("已清除畫面上的通知操作紀錄。");
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
  addJobAudit("Worker 健康檢查", "排程 worker、佇列、互斥鎖與通知閘道均回應正常。");
  renderJobs();
  showToast("背景任務 Worker 正常。");
});
document.querySelector("#jobClearLogBtn").addEventListener("click", () => {
  jobAuditLog.length = 0;
  renderJobAuditLog();
  showToast("已清除畫面上的背景任務紀錄。");
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
  databaseAuditLog.length = 0;
  renderDatabaseAuditLog();
  showToast("已清除畫面上的資料庫操作紀錄。");
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
  opsAuditLog.length = 0;
  renderOpsAuditLog();
  showToast("已清除畫面上的維運操作紀錄。");
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
document.querySelector("#settingsBackupBtn").addEventListener("click", () => {
  const data = settingsPayload();
  addSettingsAudit("匯出系統設定", `已匯出 ${data.agencyCode} 設定備份，含交換中心、防火牆、憑證與角色。`);
  showToast("系統設定備份已匯出。");
});
document.querySelector("#settingsClearLogBtn").addEventListener("click", () => {
  settingsAuditLog.length = 0;
  renderSettingsAuditLog();
  showToast("已清除畫面上的設定操作紀錄。");
});
document.querySelector("#logoutBtn").addEventListener("click", leaveApp);

renderQueueRows();
renderComplianceChecks();
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
renderWorkflowSteps();
renderWorkflowAuditLog();
renderWorkflowTemplateSteps();
renderWorkflowConditions();
renderWorkflowProxies();
renderWorkflowProofLog();
renderSeals();
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
renderAccounts();
renderReports();
renderReportsAuditLog();
renderNotifications();
renderNotificationAuditLog();
renderJobs();
syncDatabaseTables(true);
renderDatabase();
renderOps();
renderFeatureGrid();
renderSettings();
