"""
Section 6.1's synonym lookup table. The spec calls this a "grow as you test
on real data" list — the 25 real GitHub usernames pulled from the "CV with
GitHub" batch are exactly that data. Keep it flat and lowercase-keyed.
"""

SYNONYMS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "py": "python",
    "reactjs": "react",
    "react.js": "react",
    "nodejs": "node.js",
    "node": "node.js",
    "vuejs": "vue",
    "vue.js": "vue",
    "nextjs": "next.js",
    "expressjs": "express",
    "express.js": "express",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "tailwind": "tailwind css",
    "html5": "html",
    "css3": "css",
    "c sharp": "c#",
    "dotnet": ".net",
    "asp.net": ".net",
    "aws": "amazon web services",
    "gcp": "google cloud platform",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "oop": "object-oriented programming",
    "ci/cd": "continuous integration",
    "restful api": "rest api",
    "restful apis": "rest api",
    "rest apis": "rest api",
}

# Maps a normalized skill name to the manifest dependency names that count
# as direct evidence of it (Tier 1). Extend as you see more real manifests.
DEPENDENCY_MARKERS: dict[str, list[str]] = {
    "react": ["react", "react-dom"],
    "node.js": ["express", "bcryptjs", "jsonwebtoken", "cors"],
    "express": ["express"],
    "flask": ["flask", "flask-sqlalchemy", "flask-cors"],
    "django": ["django", "djangorestframework"],
    "vite": ["vite"],
    "tailwind css": ["tailwindcss", "@tailwindcss/vite"],
    "mongodb": ["mongoose", "pymongo"],
    "mysql": ["mysql-connector-python", "mysql2", "mysql-connector-java"],
    "postgresql": ["pg", "psycopg2", "pg8000"],
    "supabase": ["@supabase/supabase-js", "supabase-py"],
    "firebase": ["firebase", "firebase_core", "firebase-admin"],
    "microsoft azure": ["azure-common", "azure-core", "@azure/identity"],
    "openai gpt": ["openai"],
    "flutter": ["flutter"],
    "vercel": [],  # handled structurally (vercel.json presence), not a dependency
}


def normalize(skill: str) -> str:
    s = skill.strip().lower()
    return SYNONYMS.get(s, s)
