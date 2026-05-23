insert into public.documents (
  id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
  subject, body, status, owner, department, due_date, received_at
) values
('DOC-IN-1140522-00018', '收1140522-00018', '收文', '函', '速件', '普通', '衛生福利部', 'A21000000I', '長照服務品質稽核資料補件通知', 'jAgent 已拉取，待登錄收文號與附件完整性。', '待登錄', '總務', '總管理處', '2026-05-29', '2026-05-22 09:42'),
('DOC-OUT-1140522-007', '歲悅字第1140522007號', '發文', '函', '速件', '普通', '臺北市政府社會局', 'A63000000J', '檢送本公司日間照顧中心設立許可補正資料，請查照。', '依貴局通知辦理，檢附補正資料、附件清冊及相關證明文件。', '待清稿', '總務', '總管理處', '2026-05-29', null),
('DOC-OUT-1140519-006', '歲悅字第1140519006號', '發文', '函', '速件', '普通', '新北市政府衛生局', 'A65000000I', '補送居家服務品質改善計畫。', '補送改善計畫附件，請惠予備查。', '交換失敗', '總務', '居家照顧課', '2026-05-24', null)
on conflict (id) do nothing;

insert into public.recipients (id, name, code, exchange_center, status, contact) values
('REC-001', '臺北市政府社會局', 'A63000000J', 'G2B2C 統合交換中心', '可交換', '文書收發窗口'),
('REC-002', '臺北市政府衛生局', 'A63000000I', 'G2B2C 統合交換中心', '可交換', '衛生局收發'),
('REC-003', '新北市政府衛生局', 'A65000000I', '北區交換中心', '可交換', '公文交換窗口'),
('REC-004', '衛生福利部', 'A21000000I', 'G2B2C 統合交換中心', '可交換', '部本部總收文')
on conflict (id) do nothing;

insert into public.attachments (id, document_id, file_name, version, mime_type, size_bytes, sha256, scan_status, storage_key) values
('ATT-001', 'DOC-IN-1140522-00018', '稽核補件通知.pdf', 'v1', 'application/pdf', 838860, 'SHA256-C8202AF1', '待掃描', 'inbound/1140522/稽核補件通知.pdf'),
('ATT-002', 'DOC-IN-1140522-00018', '附件清冊.xml', 'v1', 'application/xml', 4096, 'SHA256-AD997210', '待掃描', 'inbound/1140522/附件清冊.xml'),
('ATT-003', 'DOC-OUT-1140522-007', '設立許可補正資料.pdf', 'v2', 'application/pdf', 19496960, 'SHA256-4D91FA33', '雜湊通過', 'outbound/1140522/設立許可補正資料.pdf')
on conflict (id) do nothing;

insert into public.attachment_security (
  id, attachment_id, document_id, file_name, file_ext, size_bytes, max_size_bytes,
  scan_status, scan_engine, scan_signature, mask_status, sensitive_hits_json,
  confidential_level, allowed_roles, watermark_status, quarantine_reason, backup_id
) values
('ASEC-ATT-001', 'ATT-001', 'DOC-IN-1140522-00018', '稽核補件通知.pdf', 'pdf', 838860, 52428800, '待掃描', 'ClamAV-compatible', 'SIG-SEED-001', '需遮罩', '["身分證","電話"]', '密', '行政部主任,主任,執行長', '未下載', '', ''),
('ASEC-ATT-002', 'ATT-002', 'DOC-IN-1140522-00018', '附件清冊.xml', 'xml', 4096, 52428800, '待掃描', 'ClamAV-compatible', 'SIG-SEED-002', '未遮罩', '[]', '普通', '一般角色', '未下載', '', ''),
('ASEC-ATT-003', 'ATT-003', 'DOC-OUT-1140522-007', '設立許可補正資料.pdf', 'pdf', 19496960, 52428800, '已通過', 'ClamAV-compatible', 'SIG-SEED-003', '未遮罩', '[]', '普通', '一般角色', '未下載', '', '')
on conflict (id) do nothing;

insert into public.exchange_tasks (id, document_id, direction, target_agency, status, package_id, retry_count, next_check_at) values
('TASK-001', 'DOC-OUT-1140522-007', '發文', '臺北市政府社會局', '待清稿', null, 0, '2026-05-23 09:00'),
('TASK-002', 'DOC-OUT-1140519-006', '發文', '新北市政府衛生局', '交換失敗', 'PKG-1140519-006', 1, '2026-05-23 09:00')
on conflict (id) do nothing;

insert into public.audit_logs (id, actor, action, target_type, target_id, detail) values
('AUD-SEED-001', '系統', 'Supabase seed', 'database', 'seed', '已建立 eDoc 後端初始資料')
on conflict (id) do nothing;

insert into public.roles (id, name, description, data_scope, status) values
('ROLE-DIRECTOR', '主任', '承接所屬部門公文、核准部門分派與追蹤處理時限。', 'department', '啟用'),
('ROLE-CEO', '執行長', '核定重大、密件或跨部門高風險公文並查閱全域報表。', 'all', '啟用'),
('ROLE-ADMIN-CHIEF', '行政部主任', '管理流程、清稿、角色、jAgent 參數、資安與營運維護。', 'all', '啟用'),
('ROLE-HR', '人資', '處理人資相關來文、發文與附件補正。', 'department', '啟用'),
('ROLE-ACCOUNTING', '會計', '處理會計、補助款、核銷相關來文與發文。', 'department', '啟用'),
('ROLE-GA', '總務', '唯一收文入口；拉取、登錄來文後分發給各部門主管。', 'all', '啟用'),
('ROLE-SALES-ASSISTANT', '業務助理', '建立函稿、補附件、協助發文與查詢被分派案件。', 'assigned', '啟用')
on conflict (id) do update set name = excluded.name, description = excluded.description, data_scope = excluded.data_scope, status = excluded.status;

insert into public.permissions (id, code, name, category, description) values
('PERM-INBOUND', 'inbound.manage', '收文管理', '公文', '拉取、登錄、分派與誤送漏送處理。'),
('PERM-DISPATCH', 'dispatch.manage', '發文管理', '公文', '建立函稿、清稿、封裝、送交與重送。'),
('PERM-JAGENT', 'jagent.manage', 'jAgent 介接', '系統', '憑證登入、Token、交換中心與地址簿。'),
('PERM-WORKFLOW', 'workflow.approve', '簽核流程', '流程', '簽核、退回、抽回、加簽、會辦與改派。'),
('PERM-SEAL', 'seal.apply', '自動用印', '印鑑', 'PDF 套版、押章與用印紀錄。'),
('PERM-AUDIT', 'audit.view', '稽核查閱', '稽核', 'Audit log、交換事件與不可否認紀錄。'),
('PERM-SECURITY', 'security.manage', '資安管理', '資安', 'RBAC、IP/裝置限制、MFA 與 Token 過期。'),
('PERM-REPORT', 'reports.view', '報表統計', '報表', '收發量、成功率、異常、承辦量與逾期件。'),
('PERM-SETTINGS', 'settings.manage', '系統設定', '系統', '機關代碼、API URL、防火牆、憑證與角色。')
on conflict (id) do nothing;

insert into public.role_permissions (role_id, permission_id) values
('ROLE-DIRECTOR', 'PERM-INBOUND'), ('ROLE-DIRECTOR', 'PERM-DISPATCH'), ('ROLE-DIRECTOR', 'PERM-WORKFLOW'), ('ROLE-DIRECTOR', 'PERM-REPORT'),
('ROLE-CEO', 'PERM-INBOUND'), ('ROLE-CEO', 'PERM-DISPATCH'), ('ROLE-CEO', 'PERM-WORKFLOW'), ('ROLE-CEO', 'PERM-AUDIT'), ('ROLE-CEO', 'PERM-REPORT'),
('ROLE-ADMIN-CHIEF', 'PERM-INBOUND'), ('ROLE-ADMIN-CHIEF', 'PERM-DISPATCH'), ('ROLE-ADMIN-CHIEF', 'PERM-JAGENT'), ('ROLE-ADMIN-CHIEF', 'PERM-WORKFLOW'), ('ROLE-ADMIN-CHIEF', 'PERM-SEAL'), ('ROLE-ADMIN-CHIEF', 'PERM-AUDIT'), ('ROLE-ADMIN-CHIEF', 'PERM-SECURITY'), ('ROLE-ADMIN-CHIEF', 'PERM-REPORT'), ('ROLE-ADMIN-CHIEF', 'PERM-SETTINGS'),
('ROLE-HR', 'PERM-INBOUND'), ('ROLE-HR', 'PERM-DISPATCH'), ('ROLE-HR', 'PERM-WORKFLOW'), ('ROLE-HR', 'PERM-REPORT'),
('ROLE-ACCOUNTING', 'PERM-INBOUND'), ('ROLE-ACCOUNTING', 'PERM-DISPATCH'), ('ROLE-ACCOUNTING', 'PERM-WORKFLOW'), ('ROLE-ACCOUNTING', 'PERM-REPORT'),
('ROLE-GA', 'PERM-INBOUND'), ('ROLE-GA', 'PERM-DISPATCH'), ('ROLE-GA', 'PERM-JAGENT'), ('ROLE-GA', 'PERM-WORKFLOW'), ('ROLE-GA', 'PERM-REPORT'),
('ROLE-SALES-ASSISTANT', 'PERM-DISPATCH'), ('ROLE-SALES-ASSISTANT', 'PERM-WORKFLOW'), ('ROLE-SALES-ASSISTANT', 'PERM-REPORT')
on conflict (role_id, permission_id) do nothing;

insert into public.users (id, name, email, password_hash, unit, title, role, provider, mfa_status, status) values
('USR-001', '林總務', 'edoc@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '總管理處', '總務', '總務', 'Google Workspace', '已啟用', '啟用'),
('USR-002', '張行政', 'records@suiyuecare.com', 'pbkdf2_sha256$84869515ca7759d72177dce8d4c2ca68$3baecf2b36ff55f0e19b92604f77bd030f88ec36c15e2c10e12ef9b815063262', '行政部', '行政部主任', '行政部主任', 'Microsoft Entra', '已啟用', '啟用'),
('USR-003', '王主任', 'director@suiyuecare.com', 'pbkdf2_sha256$8be7da483b04cbf4e06adf98fd4f287c$79e7c06ee0f8032a4b3f8c816f8638a81d0d6f213a7f7c4363d819722e0fe800', '營運管理處', '主任', '主任', 'Google Workspace', '已啟用', '啟用'),
('USR-004', '陳執行長', 'ceo@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '經營管理', '執行長', '執行長', 'Google Workspace', '已啟用', '啟用'),
('USR-005', '何人資', 'hr@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '人資', '人資', '人資', 'Microsoft Entra', '已啟用', '啟用'),
('USR-006', '許會計', 'accounting@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '會計', '會計', '會計', 'Microsoft Entra', '已啟用', '啟用'),
('USR-007', '周業助', 'sales-assistant@suiyuecare.com', 'pbkdf2_sha256$622057556f08af8493df12e74ad7983b$017349cb0c360d23daa17e3baeb64776915f73758a1845d064d5211a356745b7', '業務部', '業務助理', '業務助理', 'Google Workspace', '待設定', '啟用')
on conflict (id) do update set name = excluded.name, unit = excluded.unit, title = excluded.title, role = excluded.role, provider = excluded.provider, mfa_status = excluded.mfa_status, status = excluded.status;

insert into public.trusted_devices (id, user_id, name, ip, fingerprint, status, last_seen_at) values
('ACC-DEV-001', 'USR-001', '總務辦公室 Mac', '203.0.113.18', 'FP-SYC-EDOC-A1F9', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-002', 'USR-002', '行政部主任筆電', '198.51.100.27', 'FP-SYC-EDOC-B8C2', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-003', 'USR-003', '主任辦公室 Mac', '203.0.113.18', 'FP-SYC-EDOC-C339', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-004', 'USR-004', '執行長筆電', '203.0.113.44', 'FP-SYC-EDOC-D601', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-005', 'USR-005', '人資筆電', '198.51.100.27', 'FP-SYC-EDOC-HR01', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-006', 'USR-006', '會計筆電', '198.51.100.28', 'FP-SYC-EDOC-ACC1', '信任', to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
('ACC-DEV-007', 'USR-007', '業務助理筆電', '203.0.113.19', 'FP-SYC-EDOC-SA01', '待複核', to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
on conflict (id) do nothing;

insert into public.ip_allowlist (id, cidr, purpose, status) values
('IP-001', '203.0.113.0/24', '歲悅辦公室與 VPN', '啟用')
on conflict (id) do nothing;

insert into public.sso_providers (id, provider, domain, status, require_mfa) values
('SSO-GOOGLE', 'Google Workspace', 'suiyuecare.com', '待設定', true),
('SSO-MICROSOFT', 'Microsoft Entra', 'suiyuecare.com', '待設定', true)
on conflict (id) do nothing;

insert into public.seal_applications (
  id, document_id, seal_id, applicant, approver, status, reason, stamp_no
) values
('USEAL-SEED-001', 'DOC-OUT-1140522-007', 'SEAL-001', '總務', '行政部主任', '待簽核', '日照中心設立許可補正資料發文用印', null)
on conflict (id) do nothing;

insert into public.document_acl (
  id, document_id, principal_type, principal_id, can_view, can_sign, can_download,
  can_seal, can_delegate, reason, granted_by
) values
('ACL-001', 'DOC-IN-1140522-00018', 'role', '總務', true, false, true, false, true, '總務統一收文、登錄與分派。', 'system'),
('ACL-002', 'DOC-IN-1140522-00018', 'role', '主任', true, true, true, false, false, '分派後由部門主管承接與簽核。', 'system'),
('ACL-003', 'DOC-OUT-1140522-007', 'role', '業務助理', true, false, false, false, false, '承辦撰稿，只能檢視與補正內容。', 'system'),
('ACL-004', 'DOC-OUT-1140522-007', 'role', '行政部主任', true, true, true, true, true, '清稿、會辦、用印前核准。', 'system'),
('ACL-005', 'DOC-OUT-1140522-007', 'role', '總務', true, false, true, true, false, '封裝、用印與送交 jAgent。', 'system'),
('ACL-006', 'DOC-ADMIN-1140523-001', 'role', '行政部主任', true, true, true, true, true, '行政部門內部清稿與維運公文。', 'system'),
('ACL-007', 'DOC-ADMIN-1140523-001', 'role', '總務', false, false, false, false, false, '明確隔離總務收文池與行政部內部公文。', 'system')
on conflict (id) do nothing;

insert into public.document_acl_events (id, document_id, actor, action, detail) values
('ACLEVT-001', 'DOC-IN-1140522-00018', 'system', '建立文件 ACL', '總務可登錄下載；主任可檢視簽核。'),
('ACLEVT-002', 'DOC-OUT-1140522-007', 'system', '建立文件 ACL', '業務助理、行政部主任、總務依流程分權。'),
('ACLEVT-003', 'DOC-ADMIN-1140523-001', 'system', '建立隔離 ACL', '行政部主任公文對總務明確關閉。')
on conflict (id) do nothing;

insert into public.signing_certificates (
  id, owner, subject, issuer, serial_no, algorithm, valid_from, valid_to, status, fingerprint_sha256
) values
('CERT-SEAL-001', '行政部主任', 'CN=Suiyuecare Admin Chief Seal,O=Suiyuecare', 'Suiyuecare Internal CA', 'SYC-SEAL-2026-0001', 'HMAC-SHA256-RSA-PSS-READY', '2026-01-01', '2027-12-31', '啟用', 'SHA256-CERT-SEAL-001'),
('CERT-SEAL-002', '總務', 'CN=Suiyuecare General Affairs Seal,O=Suiyuecare', 'Suiyuecare Internal CA', 'SYC-GA-2026-0002', 'HMAC-SHA256-RSA-PSS-READY', '2026-01-01', '2027-12-31', '啟用', 'SHA256-CERT-SEAL-002'),
('CERT-TSA-001', '系統時間戳', 'CN=Suiyuecare TSA,O=Suiyuecare', 'Suiyuecare Internal CA', 'SYC-TSA-2026-0001', 'RFC3161-TSA-SIM', '2026-01-01', '2027-12-31', '啟用', 'SHA256-CERT-TSA-001')
on conflict (id) do nothing;

insert into public.background_jobs (id, name, job_type, schedule_text, status, last_result, next_run_at, run_count) values
('JOB-001', '每日收文拉取', 'pullInbound', '每日 08:30', '啟用', '尚未執行', '2026-05-23 08:30', 0),
('JOB-002', '發文翌日查核', 'nextDayCheck', '每日 09:00', '啟用', '尚未執行', '2026-05-23 09:00', 0),
('JOB-003', 'Token 到期檢查', 'tokenCheck', '每 15 分鐘', '啟用', '尚未執行', '2026-05-23 09:15', 0),
('JOB-004', '逾期稽催', 'overdueReminder', '每小時', '啟用', '尚未執行', '2026-05-23 10:00', 0),
('JOB-005', '交換狀態同步', 'exchangeSync', '每 15 分鐘', '啟用', '尚未執行', '2026-05-23 09:15', 0),
('JOB-006', '歸檔封存', 'archiveSeal', '每日 18:00', '啟用', '尚未執行', '2026-05-23 18:00', 0),
('JOB-007', '報表產生', 'reportGenerate', '每日 18:00', '啟用', '尚未執行', '2026-05-23 18:00', 0)
on conflict (id) do nothing;

insert into public.notifications (
  id, type, title, target_role, target_email, channel, status, priority, source, body
) values
('NTF-001', '收文', '衛福部補件通知待登錄', '總務', null, '系統通知', '未讀', '高', 'IN-1140522-00018', 'jAgent 已拉取新來文，請完成收文登錄與附件檢核。'),
('NTF-002', '待清稿', '日照中心補正資料待清稿', '行政部主任', null, 'Email + 系統通知', '未讀', '高', 'OUT-1140522-007', '函稿已建立，請進行清稿檢核與附件封裝。'),
('NTF-003', '交換失敗', '新北市政府衛生局交換失敗', '總務', null, 'Email + Line + 系統通知', '未讀', '高', 'OUT-1140519-006', 'jAgent 回覆 failed，請確認機關代碼並重送。'),
('NTF-004', 'Token 到期', 'jAgent Token 即將到期', '行政部主任', null, 'Email + 系統通知', '未讀', '中', 'SEC-TOKEN', 'Token 剩餘時間不足，請刷新或重新憑證登入。'),
('NTF-005', '逾期查核', '收1140522-00013 分派逾期', '行政部主任', null, 'Line 工作群組', '未讀', '高', 'TRK-003', '收文尚未完成分派，請啟動逾期查核提醒。')
on conflict (id) do nothing;

insert into public.notification_rules (id, type, rule_text, target_role, channel, status) values
('NRULE-001', '收文', 'jAgent 拉取來文後立即通知總務。', '總務', '系統通知', '啟用'),
('NRULE-002', '待清稿', '發文待清稿超過 2 小時通知行政部主任。', '行政部主任', 'Email + 系統通知', '啟用'),
('NRULE-003', '交換失敗', '交換失敗即時發送 Email、LINE 與站內通知。', '總務', 'Email + Line + 系統通知', '啟用'),
('NRULE-004', 'Token 到期', 'Token 到期前 60 分鐘通知行政部主任。', '行政部主任', 'Email + 系統通知', '啟用'),
('NRULE-005', '逾期查核', '每日 09:00 送出逾期查核提醒。', '行政部主任', 'Line 工作群組', '啟用')
on conflict (id) do nothing;
