# DevScore

DevScore is an evidence-driven job-readiness scoring system for software engineering
candidates. It compares claimed skills on a resume with verifiable evidence mined
from a candidate's GitHub activity and other sources to produce a Job Readiness Score
for recruiters.

Key capabilities

- Compare resume-claimed skills with GitHub-derived evidence
- Role-based access (Student, Recruiter, Admin)
- OAuth sign-in (Google/GitHub) and GitHub account linking for evidence mining
- Resume upload + parsing microservice (CV parser)

Repository layout

- client/ — React (Vite) frontend
- server/ — Node.js + Express backend and API
- cv_parser/ — Python microservice for resume parsing and skill extraction
- server/supabase/schema.sql — Supabase/Postgres schema

Prerequisites

- Node.js (16+ recommended)
- npm (or yarn)
- Python 3.9+ (for the CV parser)
- A Supabase project (or Postgres instance) for data storage

Environment configuration

- Backend env example: `server/.env.example` — copy to `server/.env` and fill values.
- Frontend env: `client/.env` (if you need to override `VITE_*` variables).

Quick start

1. Start Supabase (or point to your hosted project) and apply the SQL schema located at `server/supabase/schema.sql`.

2. Backend (API)

```bash
cd server
cp .env.example .env
# edit .env and set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, JWT_SECRET, OAuth creds
npm install
npm run dev
# API defaults to http://localhost:5000
```

3. Frontend (web app)

```bash
cd client
npm install
npm run dev
# Frontend defaults to http://localhost:5173
```

4. CV parser (optional)

```bash
cd cv_parser
python -m venv .venv
source .venv/Scripts/activate    # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
# Parser defaults to http://localhost:5001
```

Notes and tips

- Keep `SUPABASE_SERVICE_ROLE_KEY` and other server secrets server-side only.
- OAuth callback URLs are configured in `server/.env.example`.
- The backend exposes routes under `/api/*` and serves JSON for the client app.

Where to look next

- Frontend entry: `client/src/main.jsx` and `client/src/pages`
- Backend entry: `server/src/app.js` and `server/src/routes`
- CV parser code: `cv_parser/`

License & authors

This project was developed by Team Script Fusion for an academic final-year project.
See the repository contributors for details.
