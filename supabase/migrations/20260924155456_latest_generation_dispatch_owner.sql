-- Preserve each deployed function's current authorization, lock, and output
-- guards. Narrow only its GA lookup to the latest immutable workflow generation.
do $latest_dispatch_generation$
declare
  v_signature text;
  v_definition text;
  v_old text := $old$and step.step_key = 'general_affairs_review'
       and step.status = 'approved'$old$;
  v_new text := $new$and step.step_key = 'general_affairs_review'
       and step.workflow_generation = (
         select max(current_generation.workflow_generation)
         from public.official_document_approval_steps current_generation
         where current_generation.document_id = v_document.id
       )
       and step.status = 'approved'$new$;
begin
  foreach v_signature in array array[
    'public.edoc_create_official_document_dispatch_record(text,text)',
    'public.edoc_complete_official_document_stamp(text,text,text,text)'
  ] loop
    v_definition := pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(v_signature));
    if v_definition is null then
      raise exception 'official_dispatch_generation_rpc_missing: %',v_signature;
    end if;
    if pg_catalog.strpos(v_definition,v_new)>0 then
      continue;
    end if;
    if pg_catalog.length(v_definition)-pg_catalog.length(pg_catalog.replace(v_definition,v_old,'')) <> pg_catalog.length(v_old) then
      raise exception 'official_dispatch_generation_rpc_source_drift: %',v_signature;
    end if;
    execute pg_catalog.replace(v_definition,v_old,v_new);
  end loop;
end $latest_dispatch_generation$;
