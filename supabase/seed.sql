insert into public.documents (
  id, doc_no, direction, doc_type, priority, security_level, agency_name, agency_code,
  subject, body, status, owner, department, due_date, received_at
) values
('DOC-IN-1140522-00018', '收1140522-00018', '收文', '函', '速件', '普通', '衛生福利部', 'A21000000I', '長照服務品質稽核資料補件通知', 'jAgent 已拉取，待登錄收文號與附件完整性。', '待登錄', '總收發', '總管理處', '2026-05-29', '2026-05-22 09:42'),
('DOC-OUT-1140522-007', '歲悅字第1140522007號', '發文', '函', '速件', '普通', '臺北市政府社會局', 'A63000000J', '檢送本公司日間照顧中心設立許可補正資料，請查照。', '依貴局通知辦理，檢附補正資料、附件清冊及相關證明文件。', '待清稿', '總收發', '總管理處', '2026-05-29', null),
('DOC-OUT-1140519-006', '歲悅字第1140519006號', '發文', '函', '速件', '普通', '新北市政府衛生局', 'A65000000I', '補送居家服務品質改善計畫。', '補送改善計畫附件，請惠予備查。', '交換失敗', '總收發', '居家照顧課', '2026-05-24', null)
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

insert into public.exchange_tasks (id, document_id, direction, target_agency, status, package_id, retry_count, next_check_at) values
('TASK-001', 'DOC-OUT-1140522-007', '發文', '臺北市政府社會局', '待清稿', null, 0, '2026-05-23 09:00'),
('TASK-002', 'DOC-OUT-1140519-006', '發文', '新北市政府衛生局', '交換失敗', 'PKG-1140519-006', 1, '2026-05-23 09:00')
on conflict (id) do nothing;

insert into public.audit_logs (id, actor, action, target_type, target_id, detail) values
('AUD-SEED-001', '系統', 'Supabase seed', 'database', 'seed', '已建立 eDoc 後端初始資料')
on conflict (id) do nothing;
