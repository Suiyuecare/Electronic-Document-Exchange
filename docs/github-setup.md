# GitHub Setup

This repository is prepared for GitHub and Vercel production deployment.

## What Is Ready

- Local Git repository on `main`
- GitHub Actions CI at `.github/workflows/ci.yml`
- Pull request template
- Bug and feature issue templates
- CODEOWNERS placeholder
- `.gitignore` excluding local database, backups, env files, and Vercel state

## Create The Remote Repository

The production repository is:

```text
Suiyuecare/Electronic-Document-Exchange
```

Remote URL:

```bash
git remote add origin https://github.com/Suiyuecare/Electronic-Document-Exchange.git
```

Push:

```bash
git push -u origin main
```

## Required Repository Secrets

For future Vercel/Supabase deployment automation, add:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID=prj_iNAxeAFkzDkrwkDFoeOZvJj78L7K
```

Do not commit service role keys or Vercel tokens to the repository.
