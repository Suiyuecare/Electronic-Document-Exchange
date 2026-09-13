#!/usr/bin/env node
/* Execute the unchanged production TUS client against loopback Storage only.
 * Credentials arrive on stdin and are never printed. The only adaptation is
 * an origin map: the production client still validates a Cloud-shaped URL,
 * while every network request is hard-bound to the isolated CI origin.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const VIRTUAL_ORIGIN = 'https://editor-ci.storage.supabase.co';
const PREFIX = '/storage/v1/upload/resumable/sign';

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const local = new URL(input.localOrigin);
  if (local.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(local.hostname)
      || local.pathname !== '/' || local.search || local.hash) {
    throw new Error('loopback_origin_required');
  }
  const actualEndpoint = new URL(input.intent.upload_url);
  if (actualEndpoint.origin !== local.origin || actualEndpoint.pathname !== PREFIX) {
    throw new Error('loopback_signed_endpoint_required');
  }
  const source = fs.readFileSync(path.resolve(__dirname, '../../app.js'), 'utf8');
  const start = source.indexOf('function tusMetadataValue(');
  const end = source.indexOf('function editorUploadFailureCode(', start);
  if (start < 0 || end <= start) throw new Error('production_client_not_found');
  const trace = [];
  let interrupted = false;
  let invalidKeyRejected = false;
  const mappedFetch = async (target, options = {}) => {
    const remote = new URL(target);
    if (remote.origin !== VIRTUAL_ORIGIN
        || !(remote.pathname === PREFIX || remote.pathname.startsWith(`${PREFIX}/`))) {
      throw new Error('non_loopback_transport_rejected');
    }
    const headers = new Headers(options.headers);
    if (headers.has('Authorization') || headers.has('x-upsert')) {
      throw new Error('unexpected_privileged_upload_header');
    }
    const method = options.method || 'GET';
    if (!['POST', 'PATCH', 'HEAD'].includes(method)) throw new Error('unexpected_method');
    const response = await fetch(`${local.origin}${remote.pathname}${remote.search}`, {
      ...options, redirect: 'error',
    });
    trace.push({ method, status: response.status });
    if (!response.ok) {
      const body = await response.clone().text();
      invalidKeyRejected ||= /invalid.?key/i.test(body);
    }
    if (input.interruptAfterFirstPatch && method === 'PATCH' && response.ok && !interrupted) {
      interrupted = true;
      await response.arrayBuffer();
      throw new TypeError('synthetic_connection_lost_after_remote_commit');
    }
    const location = response.headers.get('Location');
    if (!location) return response;
    const resolved = new URL(location, local.origin);
    if (resolved.origin !== local.origin || !resolved.pathname.startsWith(`${PREFIX}/`)) {
      throw new Error('non_loopback_storage_location_rejected');
    }
    const mappedHeaders = new Headers(response.headers);
    mappedHeaders.set('Location', `${VIRTUAL_ORIGIN}${resolved.pathname}${resolved.search}`);
    return new Response(response.body, { status: response.status, headers: mappedHeaders });
  };
  const context = vm.createContext({
    URL, TextEncoder, btoa, atob, Blob, File, Headers, Response,
    fetch: mappedFetch,
    window: { location: { href: `${VIRTUAL_ORIGIN}/` }, setTimeout },
    assertEditorUploadCurrent: () => {},
  });
  vm.runInContext(source.slice(start, end), context, { timeout: 5000 });
  const file = new File([Buffer.from(input.dataBase64, 'base64')], input.fileName, {
    type: input.mimeType,
  });
  const progress = [];
  let result;
  try {
    const uploaded = await context.performTusUpload(file, {
      ...input.intent, upload_url: `${VIRTUAL_ORIGIN}${PREFIX}`,
    }, value => progress.push(value));
    result = { ok: true, offset: uploaded.offset };
  } catch (error) {
    result = {
      ok: false,
      code: /^editor_[a-z0-9_]+$/.test(error.code || '') ? error.code : 'client_failed',
      status: Number(error.status) || 0,
    };
  }
  process.stdout.write(JSON.stringify({
    ...result, trace, invalidKeyRejected, interrupted,
    fileNamePreserved: file.name === input.fileName,
    progressComplete: progress.at(-1) === 1,
    actualProductionClient: true,
    transport: 'node_fetch_loopback_origin_map',
  }));
}

main().catch(() => {
  process.stdout.write(JSON.stringify({ ok: false, code: 'isolated_client_runner_failed' }));
  process.exitCode = 1;
});
