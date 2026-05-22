# GitHub Setup

This repository is prepared for GitHub, but the GitHub connector currently has no installed account/repository access in Codex.

## What Is Ready

- Local Git repository on `main`
- GitHub Actions CI at `.github/workflows/ci.yml`
- Pull request template
- Bug and feature issue templates
- CODEOWNERS placeholder
- `.gitignore` excluding local database, backups, env files, and Vercel state

## Create The Remote Repository

After GitHub access is available, create a repository named:

```text
seniorlifepr/module-edoc
```

Then push:

```bash
git remote add origin git@github.com:seniorlifepr/module-edoc.git
git push -u origin main
```

If using HTTPS:

```bash
git remote add origin https://github.com/seniorlifepr/module-edoc.git
git push -u origin main
```

## Required Repository Secrets

For future Vercel/Supabase deployment automation, add:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

Do not commit service role keys or Vercel tokens to the repository.
