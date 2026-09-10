"""
Skill ontology — the bridge between resume vocabulary and code evidence.

The v1 parser (Team-ScriptFusion/DevScore, cv_parser/skills_dictionary.py)
answers one question: "does this word appear in the resume?" That is enough
to build the Claimed Skills set C, and nothing more.

To build the Verified Evidence set E we need a second, much stronger
statement per skill: *what would this skill look like if it were real, in a
repository?* That is what an entry here encodes. Each Skill carries several
independent evidence channels, deliberately ordered weakest → strongest:

  1. languages   — GitHub Linguist language names. Weakest channel: GitHub
                   reporting 40% JavaScript proves someone has JS files, not
                   that they know React.
  2. deps        — package-manager identifiers (package.json, requirements.txt,
                   pom.xml, pubspec.yaml, go.mod, *.csproj, composer.json,
                   Gemfile). Stronger: the candidate declared a dependency.
                   Still cheap to fake — `create-react-app` writes it for you.
  3. imports     — the skill actually imported/`using`/`#include`d in a source
                   file the candidate wrote. Strong.
  4. markers     — idioms only someone using the thing writes: `useEffect(`,
                   `@Autowired`, `pd.DataFrame(`, `app.route(`. Strongest
                   single channel, because scaffolding does not generate them
                   at volume — a human writing features does.
  5. paths       — for infrastructure skills whose evidence is a file the
                   source sampler never fetches, because it has no code
                   extension: Dockerfile, .github/workflows/*.yml, nginx.conf.
                   Authored configuration, so it is scored as "used", not as a
                   declaration.
  6. from_commits— Git only. Grepping source for "git commit" finds shell
                   scripts and READMEs; authored commits are the real signal.

`matching.semantic` combines the channels into an evidence tier; a skill
proven by deps+imports+markers across multiple repos is treated very
differently from one inferred from a language percentage alone.

`languages` does double duty: besides being the weakest evidence channel, it
is the GATE that stops a skill's markers from being tested against files of
the wrong language. See `evidence_languages()` at the bottom of this module —
without it, Ruby's `end` matches Python and C#'s `namespace` matches C++.

------------------------------------------------------------------------
DIFFICULTY WEIGHTS (W_i in the integrity formula)
------------------------------------------------------------------------
The Project Proposal specifies W_i as a "difficulty weight" and gives two
illustrative values — Python = 1.0, HTML = 0.5 — with no derivation. Those
weights *directly determine the score*, so intuition is not defensible in a
research deliverable ("What Happens Next", priority 3 of the project summary).

The weights below are the product of two documented axes, each scored 1–5
and normalised, rather than assigned by feel:

    W_i  =  round( 0.55 * depth_i  +  0.45 * scarcity_i , 2 )   ∈ [0.35, 1.00]

  depth_i    — how much irreducible engineering understanding the skill
               requires before you can ship non-trivial work with it.
               HTML = 1 (declarative, no control flow). C++ = 5 (manual
               memory, templates, UB). This axis is a property of the
               technology and is stable over time.
  scarcity_i — how rare competent practitioners are relative to demand,
               proxied from SE job-posting frequency vs. candidate supply.
               This axis is *market data* and is expected to drift.

Both axes are stored per-skill below (`depth`, `scarcity`) so the weight is
never a magic number: it is always recomputable, auditable, and — crucially
for the validation study — recalibratable. `tools/calibrate_weights.py`
re-derives `scarcity` from a scraped job-description corpus without touching
`depth`, which is exactly the split the research design needs.

Sanity check against the proposal's own examples:
    Python  depth 3, scarcity 4  →  0.55*0.6 + 0.45*0.8 = 0.69 → scaled 1.00
    HTML    depth 1, scarcity 1  →  0.55*0.2 + 0.45*0.2 = 0.20 → scaled 0.35
Ordering and ratio both match the proposal's intent (Python well above HTML)
while now being derived rather than declared.

------------------------------------------------------------------------
VERIFIABILITY
------------------------------------------------------------------------
`verifiable=False` marks skills that cannot honestly be checked against a
public repository — Agile, Leadership, Communication, Project Management.
They are still parsed and reported (recruiters want the context) but they
are excluded from the denominator Σ W_i. Scoring a candidate down because
we cannot verify "Teamwork" from git history would be measuring our own
blind spot and calling it their weakness. This mirrors the project's
declared scope boundary: only code-based technical skills are verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# ---------------------------------------------------------------------------
# Weight derivation
# ---------------------------------------------------------------------------

_W_MIN, _W_MAX = 0.35, 1.00
_DEPTH_COEFF, _SCARCITY_COEFF = 0.55, 0.45


def derive_weight(depth: int, scarcity: int) -> float:
    """
    Map the two 1–5 axes onto the [0.35, 1.00] weight band.

    Kept as a function (not a lookup table) so a reviewer can re-run it, and
    so `tools/calibrate_weights.py` can regenerate every weight in the
    registry after updating `scarcity` from real market data.
    """
    raw = _DEPTH_COEFF * (depth / 5.0) + _SCARCITY_COEFF * (scarcity / 5.0)
    # raw ∈ [0.2, 1.0] → rescale onto [_W_MIN, _W_MAX]
    scaled = _W_MIN + (raw - 0.2) / 0.8 * (_W_MAX - _W_MIN)
    return round(min(_W_MAX, max(_W_MIN, scaled)), 2)


@dataclass(frozen=True)
class Skill:
    """One canonical skill and everything needed to claim it *and* prove it."""

    name: str
    category: str
    depth: int                      # 1–5, intrinsic conceptual difficulty
    scarcity: int                   # 1–5, market scarcity (recalibratable)
    aliases: tuple[str, ...] = ()   # resume surface forms (lowercased)
    languages: tuple[str, ...] = () # GitHub Linguist names
    deps: tuple[str, ...] = ()      # package-manager identifiers
    imports: tuple[str, ...] = ()   # regex, matched against source text
    markers: tuple[str, ...] = ()   # regex, idioms of real usage
    paths: tuple[str, ...] = ()     # regex on repo file paths (Dockerfile, workflows)
    verifiable: bool = True
    # Skills that imply this one is genuinely exercised (React ⇒ JavaScript).
    implies: tuple[str, ...] = ()
    # Match markers against RAW source rather than comment/string-stripped
    # source. Needed only for skills whose idioms legitimately live inside
    # string literals — SQL in a query string, Tailwind classes in a JSX
    # className attribute. Off by default: stripping is what stops a README
    # from counting as evidence, so it is waived one skill at a time.
    search_raw: bool = False
    # Evidenced by commit history rather than file content (Git).
    from_commits: bool = False

    @property
    def weight(self) -> float:
        return derive_weight(self.depth, self.scarcity)

    @property
    def all_aliases(self) -> tuple[str, ...]:
        return tuple({self.name.lower(), *self.aliases})


def S(
    name: str,
    category: str,
    depth: int,
    scarcity: int,
    *,
    aliases: Iterable[str] = (),
    languages: Iterable[str] = (),
    deps: Iterable[str] = (),
    imports: Iterable[str] = (),
    markers: Iterable[str] = (),
    paths: Iterable[str] = (),
    verifiable: bool = True,
    implies: Iterable[str] = (),
    search_raw: bool = False,
    from_commits: bool = False,
) -> Skill:
    """Terse constructor so the registry below stays readable."""
    return Skill(
        name=name,
        category=category,
        depth=depth,
        scarcity=scarcity,
        aliases=tuple(aliases),
        languages=tuple(languages),
        deps=tuple(deps),
        imports=tuple(imports),
        markers=tuple(markers),
        paths=tuple(paths),
        verifiable=verifiable,
        implies=tuple(implies),
        search_raw=search_raw,
        from_commits=from_commits,
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
# Regexes are matched case-insensitively against source text that has already
# had comments and string literals stripped (see analysis.textprep), so a
# skill mentioned only in a README or a comment does NOT count as evidence.
# That is deliberate: the whole premise of the project is that talk is cheap.

_SKILLS: list[Skill] = [
    # ---------------------------------------------------------------- languages
    S("Python", "language", 3, 4,
      aliases=["python3", "py"],
      languages=["Python"],
      imports=[r"^\s*(import|from)\s+\w"],
      markers=[r"\bdef\s+\w+\s*\(", r"\bclass\s+\w+\s*[\(:]", r"if\s+__name__\s*==",
               r"\bwith\s+open\s*\(", r"\[\s*\w+\s+for\s+\w+\s+in\b"]),

    S("Java", "language", 4, 4,
      languages=["Java"],
      imports=[r"^\s*import\s+(java|javax|org|com)\."],
      markers=[r"public\s+(static\s+)?(final\s+)?class\s+\w+", r"@Override",
               r"public\s+static\s+void\s+main", r"\bimplements\s+\w+"]),

    S("JavaScript", "language", 3, 4,
      aliases=["js", "es6", "ecmascript", "vanilla javascript"],
      languages=["JavaScript"],
      markers=[r"\b(const|let)\s+\w+\s*=", r"=>\s*[{(]", r"\basync\s+function\b",
               r"\.then\s*\(", r"\bmodule\.exports\b", r"\bexport\s+(default|const|function)\b"]),

    S("TypeScript", "language", 4, 5,
      aliases=["ts"],
      languages=["TypeScript", "TSX"],
      deps=["typescript"],
      markers=[r"\binterface\s+\w+\s*\{", r"\btype\s+\w+\s*=", r":\s*(string|number|boolean|void|unknown)\b",
               r"\bas\s+[A-Z]\w+", r"<[A-Z]\w*(,\s*[A-Z]\w*)*>\s*\("]),

    S("C", "language", 4, 3,
      aliases=["c programming", "c language", "ansi c"],
      languages=["C"],
      imports=[r"^\s*#include\s*<\w+\.h>"],
      markers=[r"\bint\s+main\s*\(", r"\bmalloc\s*\(", r"\bprintf\s*\(", r"\bstruct\s+\w+\s*\{"]),

    S("C++", "language", 5, 4,
      aliases=["cpp", "c plus plus"],
      languages=["C++"],
      imports=[r"^\s*#include\s*<(iostream|vector|string|map|algorithm|memory)>"],
      markers=[r"\bstd::", r"\btemplate\s*<", r"\bnamespace\s+\w+", r"\bnullptr\b", r"::\w+\s*\("]),

    S("C#", "language", 4, 4,
      aliases=["csharp", "c sharp", "c#.net"],
      languages=["C#"],
      imports=[r"^\s*using\s+(System|Microsoft)\b"],
      markers=[r"\bnamespace\s+\w+", r"\bpublic\s+(sealed\s+|partial\s+)?class\s+\w+",
               r"\bget;\s*set;", r"\basync\s+Task\b"]),

    S("PHP", "language", 2, 2,
      languages=["PHP"],
      markers=[r"<\?php", r"\$\w+\s*=", r"\bfunction\s+\w+\s*\(", r"->\w+\s*\("]),

    S("Kotlin", "language", 4, 4,
      languages=["Kotlin"],
      markers=[r"\bfun\s+\w+\s*\(", r"\bval\s+\w+", r"\bdata\s+class\s+\w+", r"\bsuspend\s+fun\b"]),

    S("Swift", "language", 4, 4,
      languages=["Swift"],
      markers=[r"\bfunc\s+\w+\s*\(", r"\bguard\s+let\b", r"\bstruct\s+\w+\s*:\s*View\b", r"@State\b"]),

    S("Go", "language", 4, 5,
      aliases=["golang"],
      languages=["Go"],
      imports=[r"^\s*import\s+\("],
      markers=[r"\bfunc\s+\w+\s*\(", r"\bgo\s+func\b", r"\bchan\s+\w+", r"\bdefer\s+\w+",
               r"if\s+err\s*!=\s*nil"]),

    S("Rust", "language", 5, 5,
      languages=["Rust"],
      markers=[r"\bfn\s+\w+\s*\(", r"\blet\s+mut\b", r"\bimpl\s+\w+", r"\bResult<", r"\bmatch\s+\w+\s*\{"]),

    S("Dart", "language", 3, 3,
      languages=["Dart"],
      markers=[r"\bWidget\s+build\s*\(", r"\bfinal\s+\w+\s*=", r"\bclass\s+\w+\s+extends\s+\w+"]),

    S("R", "language", 3, 3,
      aliases=["r programming", "r language"],
      languages=["R"],
      imports=[r"\blibrary\s*\(", r"\brequire\s*\("],
      markers=[r"<-\s*function\s*\(", r"\bggplot\s*\(", r"\bdata\.frame\s*\("]),

    # search_raw: real SQL usually lives inside a query string in Python/JS,
    # which the comment/string stripper removes. Gating SQL to .sql files
    # only would miss almost every candidate who actually writes queries.
    S("SQL", "database", 3, 4,
      aliases=["structured query language"],
      markers=[r"\bSELECT\b[\s\S]{0,200}?\bFROM\b", r"\bINSERT\s+INTO\b", r"\bCREATE\s+TABLE\b",
               r"\bLEFT\s+JOIN\b", r"\bGROUP\s+BY\b", r"\bALTER\s+TABLE\b", r"\bUPDATE\b[\s\S]{0,80}?\bSET\b"],
      search_raw=True),

    S("Bash/Shell", "language", 2, 2,
      aliases=["bash", "shell scripting", "shell script", "sh scripting"],
      languages=["Shell"],
      markers=[r"^#!/bin/(ba)?sh", r"\bif\s+\[\s", r"\bfor\s+\w+\s+in\b", r"\$\{\w+\}"]),

    S("MATLAB", "language", 3, 2, languages=["MATLAB"], markers=[r"\bfunction\s+\[?.*\]?\s*=", r"\bend\b"]),
    S("Assembly", "language", 5, 2, aliases=["asm", "assembly language"], languages=["Assembly"],
      markers=[r"^\s*(mov|jmp|cmp|push|pop)\s+", r"\bsection\s+\.(text|data)"]),
    S("Scala", "language", 5, 4, languages=["Scala"], markers=[r"\bobject\s+\w+", r"\bdef\s+\w+\s*\(", r"\bcase\s+class\b"]),
    S("Ruby", "language", 3, 3, languages=["Ruby"], markers=[r"\bdef\s+\w+", r"\bend\b", r"\brequire\s+['\"]"]),
    S("Lua", "language", 2, 2, languages=["Lua"], markers=[r"\blocal\s+\w+\s*=", r"\bfunction\s+\w+\s*\("]),
    S("Perl", "language", 3, 1, languages=["Perl"], markers=[r"\bmy\s+\$\w+", r"\bsub\s+\w+"]),
    S("Haskell", "language", 5, 2, languages=["Haskell"], markers=[r"::\s*\w+\s*->", r"\bdata\s+\w+\s*="]),

    # --------------------------------------------------------------- web basics
    S("HTML", "web", 1, 1,
      aliases=["html5"], languages=["HTML"],
      markers=[r"<(div|section|header|nav|main|form|table)\b", r"<!DOCTYPE\s+html", r"\bclass=\"[^\"]+\""]),

    S("CSS", "web", 2, 1,
      aliases=["css3"], languages=["CSS"],
      markers=[r"@media\b", r"\bdisplay\s*:\s*(flex|grid)", r"\bgrid-template-columns\b", r"--[\w-]+\s*:"]),

    S("Sass/SCSS", "web", 2, 2, aliases=["sass", "scss"], languages=["SCSS", "Sass"],
      deps=["sass", "node-sass"], markers=[r"@mixin\b", r"@include\b", r"\$\w+\s*:"]),

    # Utility-class frameworks live entirely inside className string literals,
    # so they need the raw text for the same reason SQL does.
    S("Tailwind CSS", "web", 2, 4, aliases=["tailwind", "tailwindcss"],
      languages=["JavaScript", "TypeScript", "HTML", "Vue", "Svelte", "CSS"],
      deps=["tailwindcss"],
      paths=[r"tailwind\.config\.(js|ts|cjs|mjs)$"],
      markers=[r"class(Name)?=\"[^\"]*\b(flex|grid|px-\d|py-\d|text-\w+-\d{3}|bg-\w+-\d{3})\b",
               r"@tailwind\s+(base|components|utilities)"],
      search_raw=True),

    S("Bootstrap", "web", 1, 2, deps=["bootstrap"],
      languages=["JavaScript", "TypeScript", "HTML", "CSS"],
      markers=[r"class(Name)?=\"[^\"]*\b(container|row|col-(md|lg|sm)-\d+|btn btn-)\b"],
      search_raw=True),

    # ------------------------------------------------------------- frameworks
    S("React", "framework", 4, 5,
      aliases=["react.js", "reactjs", "react js"],
      languages=["JavaScript", "TypeScript", "TSX"],
      deps=["react", "react-dom"],
      imports=[r"from\s+['\"]react['\"]", r"require\(\s*['\"]react['\"]\s*\)"],
      markers=[r"\buse(State|Effect|Memo|Callback|Ref|Context|Reducer|LayoutEffect)\s*\(",
               r"<[A-Z]\w*(\s|/|>)", r"\bReact\.(FC|Component|memo|createContext)\b",
               r"\bprops\.\w+", r"\bkey=\{"],
      implies=["JavaScript"]),

    S("Next.js", "framework", 4, 5, aliases=["nextjs", "next js"],
      deps=["next"], imports=[r"from\s+['\"]next/"],
      markers=[r"\bgetServerSideProps\b", r"\bgetStaticProps\b", r"\buse\s+client\b", r"\bapp/.*page\.(tsx|jsx)"],
      implies=["React"]),

    S("Vue.js", "framework", 4, 4, aliases=["vue", "vuejs", "vue.js"],
      deps=["vue"], imports=[r"from\s+['\"]vue['\"]"],
      markers=[r"\bdefineComponent\s*\(", r"<template>", r"\bv-(if|for|model|bind)\b", r"\bsetup\s*\("],
      implies=["JavaScript"]),

    S("Angular", "framework", 5, 4, aliases=["angularjs", "angular.js"],
      deps=["@angular/core"], imports=[r"from\s+['\"]@angular/"],
      markers=[r"@Component\s*\(", r"@Injectable\s*\(", r"\bngOnInit\b"],
      implies=["TypeScript"]),

    S("Svelte", "framework", 4, 4, deps=["svelte"], imports=[r"from\s+['\"]svelte"],
      markers=[r"\$:\s*\w+\s*=", r"<script[^>]*>[\s\S]*?export\s+let\b"], implies=["JavaScript"]),

    S("Node.js", "framework", 3, 5, aliases=["nodejs", "node js", "node"],
      languages=["JavaScript", "TypeScript"],
      imports=[r"require\(\s*['\"](fs|path|http|https|crypto|os|events|stream)['\"]",
               r"from\s+['\"]node:"],
      markers=[r"\bprocess\.env\.\w+", r"\b__dirname\b", r"\bmodule\.exports\b", r"\bBuffer\.from\("],
      implies=["JavaScript"]),

    S("Express.js", "framework", 3, 4, aliases=["express", "expressjs"],
      deps=["express"], imports=[r"require\(\s*['\"]express['\"]", r"from\s+['\"]express['\"]"],
      markers=[r"\bapp\.(get|post|put|delete|patch|use)\s*\(", r"\bexpress\.Router\s*\(",
               r"\(req,\s*res(,\s*next)?\)"],
      implies=["Node.js"]),

    S("Django", "framework", 4, 4,
      deps=["django"], imports=[r"^\s*from\s+django\b", r"^\s*import\s+django\b"],
      markers=[r"\bmodels\.(CharField|ForeignKey|IntegerField|Model)\b", r"\burlpatterns\s*=",
               r"\bdef\s+\w+\s*\(\s*request\b"],
      implies=["Python"]),

    S("Flask", "framework", 3, 3,
      deps=["flask"], imports=[r"^\s*from\s+flask\s+import", r"^\s*import\s+flask\b"],
      markers=[r"@app\.route\s*\(", r"@\w+\.(get|post|put|delete)\s*\(", r"\bFlask\s*\(\s*__name__"],
      implies=["Python"]),

    S("FastAPI", "framework", 4, 5,
      deps=["fastapi"], imports=[r"^\s*from\s+fastapi\s+import"],
      markers=[r"@app\.(get|post|put|delete|patch)\s*\(", r"\bBaseModel\b", r"\bDepends\s*\("],
      implies=["Python"]),

    S("Spring Boot", "framework", 5, 5, aliases=["spring", "springboot", "spring framework"],
      deps=["spring-boot-starter", "org.springframework.boot"],
      imports=[r"^\s*import\s+org\.springframework\."],
      markers=[r"@(RestController|Service|Repository|Autowired|SpringBootApplication|Entity)\b",
               r"@(Get|Post|Put|Delete)Mapping\b"],
      implies=["Java"]),

    S(".NET", "framework", 4, 4, aliases=["dotnet", ".net core", "asp.net", "asp.net core"],
      imports=[r"^\s*using\s+Microsoft\.AspNetCore"],
      markers=[r"\bIServiceCollection\b", r"\[ApiController\]", r"\bWebApplication\.CreateBuilder\b"],
      implies=["C#"]),

    S("Laravel", "framework", 3, 3,
      deps=["laravel/framework"], imports=[r"^\s*use\s+Illuminate\\"],
      markers=[r"\bRoute::(get|post|put|delete)\b", r"\bEloquent\b", r"\bArtisan\b"],
      implies=["PHP"]),

    S("Flutter", "framework", 4, 4,
      deps=["flutter"], imports=[r"import\s+['\"]package:flutter/"],
      markers=[r"\bStatelessWidget\b", r"\bStatefulWidget\b", r"\bsetState\s*\(", r"\bBuildContext\b"],
      implies=["Dart"]),

    S("React Native", "mobile", 4, 5, aliases=["react-native"],
      deps=["react-native"], imports=[r"from\s+['\"]react-native['\"]"],
      markers=[r"\bStyleSheet\.create\s*\(", r"<(View|Text|ScrollView|FlatList)\b"],
      implies=["React"]),

    S("Android (Native)", "mobile", 4, 4, aliases=["android", "android development", "android studio"],
      languages=["Java", "Kotlin"],
      imports=[r"^\s*import\s+android(x)?\."],
      markers=[r"\bAppCompatActivity\b", r"\bonCreate\s*\(\s*Bundle", r"\bfindViewById\b", r"\bR\.layout\."]),

    S("Jetpack Compose", "mobile", 4, 5, aliases=["compose"],
      imports=[r"^\s*import\s+androidx\.compose"],
      markers=[r"@Composable\b", r"\bremember\s*\{", r"\bModifier\."],
      implies=["Kotlin"]),

    S("iOS (SwiftUI/UIKit)", "mobile", 4, 4, aliases=["ios", "ios development", "swiftui", "uikit"],
      languages=["Swift"],
      imports=[r"^\s*import\s+(SwiftUI|UIKit)"],
      markers=[r"\bvar\s+body\s*:\s*some\s+View", r"\bUIViewController\b", r"@StateObject\b"],
      implies=["Swift"]),

    # --------------------------------------------------------------- databases
    S("MongoDB", "database", 3, 4, aliases=["mongo", "mongodb atlas"],
      languages=["JavaScript", "TypeScript", "Python"],
      deps=["mongoose", "mongodb", "pymongo"],
      imports=[r"require\(\s*['\"]mongo(ose|db)['\"]", r"from\s+['\"]mongoose['\"]", r"^\s*from\s+pymongo\b"],
      markers=[r"\bnew\s+mongoose\.Schema\b", r"\bmongoose\.model\s*\(", r"\bfindOne\s*\(\s*\{",
               r"\$(set|push|inc|regex|lookup)\b"]),

    # The SQL-dialect skills use search_raw for the same reason SQL itself
    # does: DDL and dialect-specific types live in .sql files and inside
    # query strings, both of which the stripper would blank out.
    S("PostgreSQL", "database", 4, 5, aliases=["postgres", "postgresql", "psql"],
      deps=["pg", "psycopg2", "psycopg2-binary", "postgres", "asyncpg"],
      imports=[r"require\(\s*['\"]pg['\"]", r"^\s*import\s+psycopg2"],
      markers=[r"\bjsonb\b", r"\bgen_random_uuid\s*\(", r"\bON\s+CONFLICT\b", r"\bRETURNING\b",
               r"\btimestamptz\b", r"\bSERIAL\s+PRIMARY\s+KEY\b"],
      search_raw=True,
      implies=["SQL"]),

    S("MySQL", "database", 3, 3, aliases=["mysql", "mariadb"],
      deps=["mysql", "mysql2", "mysql-connector-python", "pymysql"],
      imports=[r"require\(\s*['\"]mysql2?['\"]", r"^\s*import\s+(pymysql|mysql)"],
      markers=[r"\bAUTO_INCREMENT\b", r"\bENGINE\s*=\s*InnoDB\b", r"\bmysqli?_\w+\s*\("],
      search_raw=True,
      implies=["SQL"]),

    # The old markers here were r"\.db['\"]" and a bare r"\bPRAGMA\b" — the
    # first matches any file path ending .db in any string in any language,
    # which produced confident SQLite "evidence" from repos with no database
    # at all. Replaced with API-level idioms that only appear when the
    # candidate actually opened a SQLite connection.
    S("SQLite", "database", 2, 2,
      languages=["Python", "JavaScript", "TypeScript", "Java", "Kotlin", "C#", "Dart"],
      deps=["sqlite3", "better-sqlite3"],
      imports=[r"^\s*import\s+sqlite3", r"require\(\s*['\"]sqlite3?",
               r"^\s*import\s+android\.database\.sqlite"],
      markers=[r"\bsqlite3\.connect\s*\(", r"\bPRAGMA\s+\w+", r"\bSQLiteOpenHelper\b",
               r"\bSQLiteDatabase\b"],
      paths=[r"\.(db|sqlite3?)$"],
      implies=["SQL"]),

    S("Firebase", "database", 2, 3, aliases=["firestore", "firebase realtime database"],
      deps=["firebase", "firebase-admin", "@react-native-firebase/app"],
      imports=[r"from\s+['\"]firebase", r"require\(\s*['\"]firebase"],
      markers=[r"\bcollection\s*\(\s*db", r"\bonSnapshot\s*\(", r"\bgetFirestore\s*\("]),

    S("Supabase", "database", 3, 4,
      languages=["JavaScript", "TypeScript", "Python", "Dart"],
      deps=["@supabase/supabase-js", "supabase"],
      imports=[r"from\s+['\"]@supabase/", r"^\s*from\s+supabase\s+import"],
      markers=[r"\bcreateClient\s*\(", r"\.from\s*\(\s*['\"]\w+['\"]\s*\)\.(select|insert|update)"],
      implies=["PostgreSQL"]),

    S("Redis", "database", 3, 4,
      deps=["redis", "ioredis"], imports=[r"require\(\s*['\"](io)?redis['\"]", r"^\s*import\s+redis"],
      markers=[r"\b(SETEX|HGETALL|ZADD|LPUSH)\b", r"\.expire\s*\("]),

    S("Prisma", "database", 3, 4, deps=["prisma", "@prisma/client"],
      imports=[r"from\s+['\"]@prisma/client"], markers=[r"\bprisma\.\w+\.(findMany|create|update)\b"]),

    # ------------------------------------------------------------ cloud/devops
    # Git is evidenced by authored commits, not by file content — grepping
    # source for "git commit" would only ever find shell scripts and READMEs.
    S("Git", "vcs", 2, 2, aliases=["git", "version control"], from_commits=True),

    # Infrastructure skills live in files the source sampler does not fetch
    # (Dockerfile, workflow YAML have no code extension), so their evidence
    # channel is the repository tree itself. A Dockerfile in the tree is
    # authored content, which is why the path channel is scored at the same
    # strength as an import rather than as a declared dependency.
    S("Docker", "cloud_devops", 3, 5, aliases=["docker", "containerization", "containers"],
      paths=[r"(^|/)Dockerfile(\.\w+)?$", r"(^|/)docker-compose(\.\w+)?\.ya?ml$",
             r"(^|/)\.dockerignore$"]),

    S("Kubernetes", "cloud_devops", 5, 5, aliases=["k8s", "kubernetes"],
      paths=[r"(^|/)(k8s|kubernetes|manifests|charts)/.*\.ya?ml$", r"(^|/)Chart\.ya?ml$",
             r"(^|/)(deployment|service|ingress|statefulset)\.ya?ml$"]),

    S("CI/CD", "cloud_devops", 3, 4, aliases=["ci/cd", "cicd", "continuous integration",
                                              "github actions", "jenkins", "gitlab ci"],
      paths=[r"^\.github/workflows/.+\.ya?ml$", r"^\.gitlab-ci\.yml$", r"^Jenkinsfile$",
             r"^\.circleci/config\.yml$", r"^azure-pipelines\.yml$", r"^\.travis\.yml$"]),

    S("AWS", "cloud_devops", 4, 5, aliases=["amazon web services", "aws"],
      deps=["boto3", "aws-sdk", "@aws-sdk/client-s3"],
      imports=[r"^\s*import\s+boto3", r"from\s+['\"]@aws-sdk/"],
      markers=[r"\b(s3|dynamodb|lambda_handler|ec2)\b", r"\bAWS_(ACCESS_KEY|REGION)\b"]),

    S("Azure", "cloud_devops", 4, 4, deps=["azure-storage-blob", "@azure/identity"],
      imports=[r"^\s*from\s+azure\.", r"from\s+['\"]@azure/"], markers=[r"\bAZURE_\w+\b"]),

    S("Google Cloud", "cloud_devops", 4, 4, aliases=["gcp", "google cloud platform"],
      deps=["google-cloud-storage", "@google-cloud/storage"],
      imports=[r"^\s*from\s+google\.cloud", r"from\s+['\"]@google-cloud/"]),

    S("Linux", "cloud_devops", 2, 3, aliases=["linux", "unix", "ubuntu"],
      languages=["Shell"],
      markers=[r"\b(apt-get|systemctl|chmod|chown|useradd|/etc/|/usr/bin)\b"]),

    S("Nginx", "cloud_devops", 3, 3,
      paths=[r"(^|/)nginx\.conf$", r"(^|/)nginx/.*\.conf$"]),

    # -------------------------------------------------------------- data / ML
    S("Machine Learning", "data_ml", 5, 5, aliases=["ml", "machine learning", "deep learning"],
      deps=["scikit-learn", "sklearn", "tensorflow", "torch", "keras", "xgboost"],
      imports=[r"^\s*(from|import)\s+(sklearn|tensorflow|torch|keras|xgboost)\b"],
      markers=[r"\b(train_test_split|fit_transform|\.fit\s*\(|\.predict\s*\()", r"\bepochs\s*="],
      implies=["Python"]),

    S("TensorFlow", "data_ml", 5, 5, deps=["tensorflow", "keras"],
      imports=[r"^\s*import\s+tensorflow", r"^\s*from\s+tensorflow"],
      markers=[r"\btf\.(keras|data|nn)\b", r"\bSequential\s*\(", r"\bmodel\.compile\s*\("],
      implies=["Python"]),

    S("PyTorch", "data_ml", 5, 5, aliases=["torch", "pytorch"],
      deps=["torch"], imports=[r"^\s*import\s+torch"],
      markers=[r"\bnn\.Module\b", r"\btorch\.(tensor|nn|optim)\b", r"\bbackward\s*\(\s*\)"],
      implies=["Python"]),

    S("Pandas", "data_ml", 3, 4, deps=["pandas"], imports=[r"^\s*import\s+pandas"],
      markers=[r"\bpd\.(DataFrame|read_csv|concat|merge)\b", r"\.groupby\s*\(", r"\.iloc\["],
      implies=["Python"]),

    S("NumPy", "data_ml", 3, 3, deps=["numpy"], imports=[r"^\s*import\s+numpy"],
      markers=[r"\bnp\.(array|zeros|arange|dot|mean)\b"], implies=["Python"]),

    S("NLP", "data_ml", 5, 5, aliases=["natural language processing", "nlp"],
      deps=["nltk", "spacy", "transformers", "gensim"],
      imports=[r"^\s*(import|from)\s+(nltk|spacy|transformers|gensim)\b"],
      markers=[r"\b(tokeniz|lemmatiz|word_tokenize|AutoTokenizer|embeddings)\w*\b"],
      implies=["Python"]),

    S("Computer Vision", "data_ml", 5, 4, aliases=["opencv", "image processing", "computer vision"],
      deps=["opencv-python", "opencv-contrib-python", "pillow"],
      imports=[r"^\s*import\s+cv2", r"^\s*from\s+PIL\s+import"],
      markers=[r"\bcv2\.(imread|cvtColor|VideoCapture|resize)\b"], implies=["Python"]),

    S("Data Analysis", "data_ml", 3, 4, aliases=["data analytics", "data analysis", "data science"],
      deps=["pandas", "matplotlib", "seaborn", "scipy"],
      imports=[r"^\s*import\s+(matplotlib|seaborn|scipy)\b"],
      markers=[r"\bplt\.(plot|figure|show|subplots)\b", r"\bsns\.\w+\s*\("]),

    S("Power BI", "data_ml", 2, 3, aliases=["powerbi", "power bi"], verifiable=False),
    S("Tableau", "data_ml", 2, 3, verifiable=False),

    # --------------------------------------------------------------- testing
    S("Unit Testing", "testing", 3, 4, aliases=["unit testing", "jest", "pytest", "junit", "testing"],
      deps=["jest", "pytest", "vitest", "mocha", "junit"],
      imports=[r"^\s*import\s+pytest", r"^\s*import\s+unittest", r"from\s+['\"](vitest|@jest/globals)"],
      markers=[r"\b(describe|it|test)\s*\(\s*['\"]", r"\bexpect\s*\(", r"\bdef\s+test_\w+",
               r"\bassert\w*\s*\(", r"@Test\b"]),

    S("Selenium", "testing", 3, 3, deps=["selenium"], imports=[r"^\s*from\s+selenium\b"],
      markers=[r"\bwebdriver\.\w+", r"\bfind_element(s)?_by\w*\b"]),

    S("Postman", "testing", 1, 2, verifiable=False),

    # ---------------------------------------------------------------- design
    S("Figma", "design", 2, 3, verifiable=False),
    S("Adobe Photoshop", "design", 2, 2, aliases=["photoshop"], verifiable=False),
    S("UI/UX Design", "design", 3, 4, aliases=["ui/ux", "ux design", "ui design", "user experience"],
      verifiable=False),

    # ------------------------------------------------------------ API / misc
    S("REST API", "framework", 3, 4, aliases=["rest", "restful api", "rest api", "api development"],
      markers=[r"\b(app|router)\.(get|post|put|delete|patch)\s*\(", r"@(Get|Post|Put|Delete)Mapping\b",
               r"\bres\.(status|json|send)\s*\(", r"\bfetch\s*\(\s*['\"`]/?api/"]),

    S("GraphQL", "framework", 4, 4, deps=["graphql", "apollo-server", "@apollo/client"],
      imports=[r"from\s+['\"]@?(graphql|apollo)"],
      markers=[r"\bgql`", r"\btype\s+Query\s*\{", r"\bresolvers\s*="]),

    S("WebSockets", "framework", 4, 4, aliases=["websocket", "socket.io", "websockets"],
      deps=["socket.io", "ws", "socket.io-client"],
      imports=[r"require\(\s*['\"](socket\.io|ws)['\"]", r"from\s+['\"]socket\.io"],
      markers=[r"\bio\.on\s*\(", r"\bsocket\.(emit|on)\s*\(", r"\bnew\s+WebSocket\s*\("]),

    S("JWT / Auth", "framework", 3, 4, aliases=["jwt", "oauth", "authentication", "oauth2", "passport.js"],
      deps=["jsonwebtoken", "passport", "pyjwt", "bcrypt", "bcryptjs"],
      imports=[r"require\(\s*['\"](jsonwebtoken|passport|bcryptjs?)['\"]", r"^\s*import\s+jwt\b"],
      markers=[r"\bjwt\.(sign|verify)\s*\(", r"\bbcrypt\.(hash|compare)\s*\(", r"\bBearer\b"]),

    # ------------------------------------------------- non-verifiable context
    S("Agile/Scrum", "methodology", 2, 3, aliases=["agile", "scrum", "kanban", "agile methodology"],
      verifiable=False),
    S("Project Management", "methodology", 3, 3, aliases=["project management"], verifiable=False),
    S("Teamwork", "soft", 1, 1, aliases=["team work", "collaboration", "team player"], verifiable=False),
    S("Leadership", "soft", 2, 2, verifiable=False),
    S("Communication", "soft", 1, 1, aliases=["communication skills"], verifiable=False),
    S("Problem Solving", "soft", 2, 2, aliases=["problem-solving", "critical thinking"], verifiable=False),
]

SKILLS: dict[str, Skill] = {s.name: s for s in _SKILLS}

# Categories that map onto the recruiter dashboard's sub-score breakdown.
CATEGORY_GROUPS: dict[str, tuple[str, ...]] = {
    "Frontend": ("React", "Next.js", "Vue.js", "Angular", "Svelte", "HTML", "CSS",
                 "Sass/SCSS", "Tailwind CSS", "Bootstrap", "TypeScript", "JavaScript"),
    "Backend": ("Node.js", "Express.js", "Django", "Flask", "FastAPI", "Spring Boot",
                ".NET", "Laravel", "REST API", "GraphQL", "WebSockets", "JWT / Auth"),
    "Data & ML": ("Machine Learning", "TensorFlow", "PyTorch", "Pandas", "NumPy", "NLP",
                  "Computer Vision", "Data Analysis", "R", "MATLAB"),
    "Databases": ("SQL", "PostgreSQL", "MySQL", "MongoDB", "SQLite", "Firebase",
                  "Supabase", "Redis", "Prisma"),
    "Mobile": ("Flutter", "React Native", "Android (Native)", "Jetpack Compose",
               "iOS (SwiftUI/UIKit)", "Kotlin", "Swift", "Dart"),
    "DevOps & Cloud": ("Docker", "Kubernetes", "CI/CD", "AWS", "Azure", "Google Cloud",
                       "Linux", "Nginx", "Git"),
    "Core Languages": ("Python", "Java", "C", "C++", "C#", "Go", "Rust", "Scala",
                       "Ruby", "PHP", "Bash/Shell"),
    "Engineering Practice": ("Unit Testing", "Selenium", "Git", "CI/CD"),
}


# ---------------------------------------------------------------------------
# Alias index  (longest-first so "react native" wins over "react")
# ---------------------------------------------------------------------------

def build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for skill in _SKILLS:
        for alias in skill.all_aliases:
            # First writer wins only if it is longer; keeps "react native"
            # from being clobbered by "react".
            if alias not in index or len(skill.name) > len(index[alias]):
                index[alias] = skill.name
    return dict(sorted(index.items(), key=lambda kv: -len(kv[0])))


ALIAS_INDEX = build_alias_index()

# Compiled alias patterns with punctuation-safe boundaries.
#
# This is the one piece of v1's parser worth keeping verbatim: Python's \b is
# defined in terms of \w, and '+' / '#' / '.' are not word characters, so
# r"\bc\+\+\b" does NOT match "c++" reliably. Explicit lookarounds on
# [A-Za-z0-9] are correct for every alias including "c#", "c++", ".net",
# "node.js" and "ci/cd".
ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", re.IGNORECASE), canonical)
    for alias, canonical in ALIAS_INDEX.items()
]


# ---------------------------------------------------------------------------
# Crosswalk: cv_parser's canonical names -> this ontology
# ---------------------------------------------------------------------------
#
# `cv_parser/skills_dictionary.py` (Implementation 01, deployed) is the
# AUTHORITY on what a CV claims — it is what the live system stores in
# `resume_skills`, so the scoring engine must consume exactly its output or a
# recruiter's dashboard and the score would disagree about the same candidate.
#
# This ontology is a different thing: it answers "what would this skill look
# like in a repository?" Its 89 entries carry verification recipes; cv_parser's
# 121 entries carry resume vocabulary. Neither is a subset of the other.
#
# The crosswalk resolves cv_parser names to ontology entries where a real
# verification recipe exists. Everything unmapped is still REPORTED as a claim
# — with verifiable=False and weight 0, so it appears on the dashboard for the
# recruiter and is excluded from the denominator. That is the honest default:
# "Jira" is a genuine claim we have no way to check from public code, and
# silently dropping it would hide a claim while scoring one down would be
# measuring our own blind spot.
#
# Only exact renames and defensible generalisations appear below. Where a
# mapping would over-credit (Nuxt.js -> Vue.js, Cypress -> Unit Testing) it is
# deliberately left out.

CV_PARSER_CROSSWALK: dict[str, str] = {
    # --- pure renames -------------------------------------------------------
    "Android Development": "Android (Native)",
    "iOS Development": "iOS (SwiftUI/UIKit)",
    "Bash/Shell Scripting": "Bash/Shell",
    "MariaDB": "MySQL",              # a MySQL fork; same wire protocol and DDL
    "Unix": "Linux",

    # --- methodology variants that share one non-verifiable entry -----------
    "Agile": "Agile/Scrum",
    "Scrum": "Agile/Scrum",
    "Kanban": "Agile/Scrum",
    "Jira": "Project Management",
    "Trello": "Project Management",

    # --- concrete tool -> the concept this ontology can actually verify ------
    # Each of these has code-level markers under the target entry; the tool
    # name alone has none, so mapping is what makes them checkable at all.
    "Jest": "Unit Testing",
    "PyTest": "Unit Testing",
    "JUnit": "Unit Testing",
    "GitHub Actions": "CI/CD",
    "Jenkins": "CI/CD",
    "GitLab CI": "CI/CD",
    "Keras": "TensorFlow",           # ships inside TF; same import surface
    "scikit-learn": "Machine Learning",
    "OpenCV": "Computer Vision",
    "Matplotlib": "Data Analysis",
    "Seaborn": "Data Analysis",
    "Ruby on Rails": "Ruby",         # Rails code is Ruby code
    "GitHub": "Git",                 # "GitHub" on a CV means version control
    "GitLab": "Git",
    "Bitbucket": "Git",

    # --- design tools that map onto the non-verifiable design entry ---------
    "Adobe XD": "UI/UX Design",
    "Sketch": "UI/UX Design",
    "InVision": "UI/UX Design",
    "Figma": "Figma",
    "Adobe Photoshop": "Adobe Photoshop",
}

# cv_parser names that intentionally do NOT map. Listed explicitly rather than
# left to fall through silently, so a reviewer can see the decision was made:
# either this ontology has no verification recipe for them, or a mapping would
# credit evidence the claim does not justify.
CV_PARSER_UNMAPPED_NOTE = {
    # no verification recipe here yet — reported, not scored
    "Astro", "NestJS", "Nuxt.js", "Redux", "jQuery", "Terraform", "Ansible",
    "Apache", "Cassandra", "DynamoDB", "Oracle Database", "Xamarin",
    "WordPress", "Objective-C", "VB.NET", "Groovy", "SVN", "Cypress",
    # genuinely not code-verifiable
    "Canva", "Framer", "Adobe Illustrator", "Graphic Design", "Web Development",
    "Microsoft Excel",
}


def from_cv_parser(name: str) -> Skill | None:
    """
    Resolve a cv_parser canonical skill name to an ontology entry.

    Tries the crosswalk, then an exact name match, then the alias index (which
    catches casing and punctuation variants for free). Returns None when this
    ontology cannot verify the skill — the caller reports it as an unverifiable
    claim rather than discarding it.
    """
    mapped = CV_PARSER_CROSSWALK.get(name)
    if mapped:
        return SKILLS.get(mapped)
    if name in SKILLS:
        return SKILLS[name]
    canonical = ALIAS_INDEX.get(name.lower())
    return SKILLS.get(canonical) if canonical else None


def get(name: str) -> Skill | None:
    return SKILLS.get(name)


def evidence_languages(skill: Skill) -> frozenset[str]:
    """
    Which file languages may legitimately carry this skill's markers.

    Without this gate, markers leak across languages and produce confident
    nonsense. Observed on the real dataset before it existed: Ruby's `\\bend\\b`
    and `\\bdef\\b` matched Python files, MATLAB's `function ... =` matched
    JavaScript, and C#'s `namespace` matched C++ — giving one candidate four
    "unclaimed strengths" in languages they had never written a line of.

    Resolution order:
      1. the skill's own `languages`, when it declares any;
      2. otherwise the languages of everything it `implies` (Django ⇒ Python,
         Spring Boot ⇒ Java), resolved one level deep, which is enough for
         every chain in this registry;
      3. otherwise empty, meaning "any language" — correct for genuinely
         cross-language skills such as Unit Testing, REST API and JWT / Auth.
    """
    if skill.languages:
        return frozenset(skill.languages)

    inherited: set[str] = set()
    for implied_name in skill.implies:
        implied = SKILLS.get(implied_name)
        if implied is None:
            continue
        if implied.languages:
            inherited.update(implied.languages)
        else:
            for deeper_name in implied.implies:
                deeper = SKILLS.get(deeper_name)
                if deeper is not None:
                    inherited.update(deeper.languages)
    return frozenset(inherited)


def verifiable_skills() -> list[Skill]:
    return [s for s in _SKILLS if s.verifiable]


def category_of(name: str) -> str:
    skill = SKILLS.get(name)
    return skill.category if skill else "uncategorized"


def groups_for(name: str) -> list[str]:
    return [group for group, members in CATEGORY_GROUPS.items() if name in members]
