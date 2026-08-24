# eDoc private ClamAV scanner

This directory contains the only supported HTTPS antivirus gateway contract.
It is intended for a dedicated Google Cloud Run service and uses the official
`clamav/clamav:1.4` image with preloaded signature databases.

Security properties:

- HTTPS only; request and response bodies are bound to an HMAC-SHA256 envelope.
- The shared secret must be at least 32 bytes and is stored only in deployment
  secrets (`EDOC_AV_SHARED_SECRET` here and `EDOC_AV_API_KEY` in eDoc).
- Requests expire after 60 seconds and nonces are rejected on replay within one
  running instance.
- Large files are pulled from a 60-second Supabase signed URL.  The service
  accepts only exact hosts in `EDOC_AV_ALLOWED_SOURCE_HOSTS`, the HTTPS default
  port, and `/storage/v1/object/sign/` paths; redirects are disabled.
- Expected size and SHA-256 must match the fetched or uploaded bytes before a
  clean result is returned.
- Request bodies, URLs, file names, hashes, secrets and malware signatures are
  never written to application logs.
- Scanner/network/protocol errors fail closed.

Required runtime variables:

```text
EDOC_AV_SHARED_SECRET=<32+ byte secret>
EDOC_AV_ALLOWED_SOURCE_HOSTS=<project-ref>.supabase.co
```

Recommended Cloud Run settings:

```text
region: asia-east1
memory: 2 GiB
cpu: 2
min instances: 1
max instances: 2
concurrency: 4
request timeout: 120 seconds
```

`deploy-cloud-run.sh` applies these settings but deliberately does not create a
GCP project, billing account, or secret.  The Cloud Run network endpoint is
reachable so Vercel can call it, but every scan is rejected until the HMAC
envelope is verified.  Do not reuse this secret for any other system.  After
deployment, run `smoke_test.py` with the eDoc endpoint and secret to verify one
clean fixture, the harmless EICAR antivirus fixture, and the signed response.

Do not deploy until a production GCP project, billing approval and operations
owner exist.  Never put the shared secret, service URL or project identifiers
in Git.
