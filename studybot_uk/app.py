import os, json, uuid, shutil, tempfile
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
import anthropic
import chromadb
import duckdb
from indexer import init_db, index_single_pdf, CHROMA_PATH, DUCKDB_PATH

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    raise RuntimeError("Set ANTHROPIC_API_KEY environment variable")

claude = anthropic.Anthropic(api_key=API_KEY)
chroma = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma.get_or_create_collection("studybot_docs")

app = FastAPI(title="StudyBot UK")

# ── CCEA GCSE Curriculum Structure ───────────────────────────────────────────
CCEA_CURRICULUM = {
    "chemistry": {
        "Unit 1: Structures, Trends and Chemical Reactions": [
            "Atomic Structure and the Periodic Table",
            "Ionic Bonding and Ionic Compounds",
            "Covalent Bonding and Molecular Substances",
            "Metallic Bonding",
            "Group 1 – Alkali Metals",
            "Group 7 – Halogens",
            "Acids, Bases and Salts",
            "Quantitative Chemistry – Moles and Formulae",
            "Chemical Analysis and Testing",
        ],
        "Unit 2: Further Chemical Reactions, Rates and Organic Chemistry": [
            "Rates of Reaction",
            "Reversible Reactions and Equilibrium",
            "Electrochemistry and Electrolysis",
            "Alkanes – Saturated Hydrocarbons",
            "Alkenes – Unsaturated Hydrocarbons",
            "Alcohols and Esters",
            "Addition and Condensation Polymers",
            "Further Quantitative Chemistry Calculations",
        ],
        "Unit 3 (Practical): Chemistry in Context": [
            "Laboratory Techniques and Safety",
            "Titration and Volumetric Analysis",
            "Chromatography",
            "Industrial Chemistry – Haber and Contact Process",
        ],
    },
    "physics": {
        "Unit 1: Motion, Forces and Energy": [
            "Speed, Velocity and Acceleration",
            "Distance–Time and Velocity–Time Graphs",
            "Newton's Laws of Motion",
            "Momentum and Impulse",
            "Work, Energy and Power",
            "Pressure in Fluids",
            "Density",
            "Hooke's Law and Elasticity",
        ],
        "Unit 2: Waves, Electricity and Magnetism": [
            "Properties of Waves (Amplitude, Frequency, Wavelength)",
            "Reflection and Refraction of Light",
            "Total Internal Reflection and Optical Fibres",
            "Electromagnetic Spectrum",
            "Sound Waves",
            "Static Electricity",
            "Current, Voltage and Resistance (Ohm's Law)",
            "Series and Parallel Circuits",
            "Domestic Electricity and Electrical Safety",
            "Magnetism and Magnetic Fields",
            "Electromagnetic Induction and Transformers",
        ],
        "Unit 3: Radioactivity and the Universe": [
            "Atomic Structure – Protons, Neutrons, Electrons",
            "Isotopes and Radioactive Decay",
            "Alpha, Beta and Gamma Radiation",
            "Half-Life and Decay Curves",
            "Nuclear Fission and Chain Reactions",
            "Nuclear Fusion and Stars",
            "The Solar System and Planets",
            "Stars – Life Cycle",
            "The Universe – Big Bang Theory",
        ],
    },
    "maths_m4": {
        "Unit 1: Number": [
            "Fractions, Decimals and Percentages",
            "Ratio and Proportion",
            "Indices and Standard Form",
            "Rounding, Estimation and Significant Figures",
            "Calculator and Non-Calculator Methods",
        ],
        "Unit 2: Algebra": [
            "Simplifying Expressions and Expanding Brackets",
            "Solving Linear Equations",
            "Inequalities on a Number Line",
            "nth Term of a Sequence",
            "Straight-Line Graphs (y = mx + c)",
            "Substitution into Formulae",
        ],
        "Unit 3: Geometry and Measures": [
            "Angles – Types, Parallel Lines, Polygons",
            "Area and Perimeter of 2D Shapes",
            "Volume and Surface Area of 3D Shapes",
            "Pythagoras' Theorem",
            "Basic Trigonometry (SOH CAH TOA)",
            "Transformations – Rotation, Reflection, Translation, Enlargement",
            "Circles – Circumference and Area",
        ],
        "Unit 4: Statistics and Probability": [
            "Mean, Median, Mode and Range",
            "Bar Charts, Pie Charts and Frequency Diagrams",
            "Scatter Graphs and Correlation",
            "Probability – Basic and Combined Events",
            "Cumulative Frequency",
        ],
    },
    "maths_m8": {
        "Unit 1: Number (Higher)": [
            "Fractions, Decimals and Percentages (Higher)",
            "Indices, Surds and Standard Form",
            "Ratio, Proportion and Rates of Change",
            "Recurring Decimals and Exact Values",
        ],
        "Unit 2: Algebra (Higher)": [
            "Quadratic Equations – Factorising and Formula",
            "Simultaneous Equations (Linear and Quadratic)",
            "Functions – Domain, Range, Composite, Inverse",
            "Sequences – nth Term and Geometric",
            "Inequalities and Regions on a Graph",
            "Algebraic Proof",
            "Iteration and Numerical Methods",
        ],
        "Unit 3: Geometry (Higher)": [
            "Circle Theorems",
            "Trigonometry – Sine Rule and Cosine Rule",
            "3D Trigonometry and Pythagoras",
            "Vectors – Adding, Subtracting, Scalar Multiple",
            "Loci and Construction",
            "Similarity and Congruence",
            "Mensuration – Sectors and Segments",
        ],
        "Unit 4: Statistics and Probability (Higher)": [
            "Histograms and Frequency Density",
            "Cumulative Frequency and Box Plots",
            "Conditional Probability and Venn Diagrams",
            "Correlation – Pearson's Coefficient",
        ],
    },
}


@app.get("/curriculum/{subject}")
def get_curriculum(subject: str):
    data = CCEA_CURRICULUM.get(subject.lower())
    if not data:
        return {"error": f"No curriculum found for '{subject}'"}
    return {
        "subject": subject,
        "units": [
            {"unit": unit, "topics": topics}
            for unit, topics in data.items()
        ],
    }


SAMPLE_STUDENTS = [
    ("ST001", "Alice Johnson",  "1234"),
    ("ST002", "Ben Murphy",     "2345"),
    ("ST003", "Chloe Davies",   "3456"),
    ("ST004", "Daniel Smith",   "4567"),
    ("ST005", "Emma Wilson",    "5678"),
]


def db():
    con = duckdb.connect(DUCKDB_PATH)
    init_db(con)
    return con


def seed_students():
    con = db()
    for sid, name, pin in SAMPLE_STUDENTS:
        existing = con.execute("SELECT 1 FROM students WHERE student_id=?", [sid]).fetchone()
        if not existing:
            con.execute("INSERT INTO students VALUES (?,?,?)", [sid, name, pin])
    con.close()


seed_students()


# ── Helpers ───────────────────────────────────────────────────────────────────

def search_context(subject: str, topic: str, n: int = 15) -> str:
    try:
        where  = {"subject": subject}
        res    = collection.query(query_texts=[topic], n_results=n, where=where)
        chunks = res["documents"][0] if res["documents"] else []
        return "\n\n---\n\n".join(chunks[:10]) if chunks else ""
    except Exception:
        return ""


def parse_json(text: str):
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith(("[", "{")):
                text = part
                break
    return json.loads(text)


def ask_claude(prompt: str, max_tokens: int = 3000) -> str:
    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), subject: str = Form("chemistry")):
    """Upload a PDF and index it immediately."""
    suffix   = os.path.splitext(file.filename)[1]
    tmp_path = tempfile.mktemp(suffix=suffix)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    chunks = index_single_pdf(tmp_path, subject)
    os.unlink(tmp_path)
    return {"filename": file.filename, "subject": subject, "chunks_indexed": chunks}


@app.post("/ingest/all")
def ingest_all():
    """Re-index all PDFs from the configured subject folders."""
    from indexer import build_index
    build_index()
    return {"status": "complete", "total_chunks": collection.count()}


@app.post("/quiz/generate")
def generate_quiz(body: dict):
    subject    = body.get("subject", "chemistry")
    topic      = body.get("topic", "")
    count      = int(body.get("count", 10))
    count      = min(count, 50)
    student_id = body.get("student_id", "")

    context = search_context(subject, topic, n=15)
    ctx_block = f"\nReference material from study documents:\n{context}\n" if context else \
                "\n(No indexed documents found — using general GCSE knowledge)\n"

    prompt = f"""You are a GCSE UK exam question generator.

Subject: {subject.upper()}
Topic: {topic if topic else "general revision"}
Number of questions: {count}
{ctx_block}
Generate exactly {count} exam-style questions. Mix types:
- mcq  = multiple choice (A B C D)
- short = written short answer
- calc  = calculation with working

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "q": "Full question text",
    "type": "mcq|short|calc",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "answer": "correct answer or option letter",
    "marks": 1
  }}
]
For non-mcq questions omit "options". Include "marks" (1-4) for each question."""

    raw       = ask_claude(prompt, max_tokens=4000)
    questions = parse_json(raw)

    session_id = str(uuid.uuid4())
    con = db()
    con.execute(
        """INSERT INTO quiz_sessions
           (session_id,subject,topic,question_count,questions_json,created_at,student_id)
           VALUES (?,?,?,?,?,?,?)""",
        [session_id, subject, topic, count, json.dumps(questions), datetime.now(), student_id]
    )
    con.close()
    return {"session_id": session_id, "questions": questions, "subject": subject, "topic": topic}


@app.post("/quiz/answer")
def check_answer(body: dict):
    session_id   = body.get("session_id")
    question_idx = int(body.get("question_idx", 0))
    student_ans  = body.get("answer", "").strip()

    con = db()
    row = con.execute(
        "SELECT questions_json FROM quiz_sessions WHERE session_id = ?",
        [session_id]
    ).fetchone()
    con.close()

    if not row:
        return {"error": "Session not found"}

    question = json.loads(row[0])[question_idx]
    marks    = question.get("marks", 1)

    prompt = f"""You are a strict but fair GCSE examiner.

Question: {question["q"]}
Correct answer: {question["answer"]}
Student's answer: {student_ans}
Maximum marks: {marks}

Assess the student's answer. Accept equivalent correct answers.

Respond ONLY with JSON (no markdown):
{{
  "is_correct": true/false,
  "marks_awarded": 0-{marks},
  "feedback": "one-sentence feedback",
  "explanation": "2-4 sentence explanation of the correct answer with working if calculation",
  "tip": "one memorable tip or mnemonic to remember this"
}}"""

    raw    = ask_claude(prompt, max_tokens=600)
    result = parse_json(raw)

    con = db()
    con.execute(
        "INSERT INTO quiz_results VALUES (?,?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), session_id, question_idx,
         question["q"], student_ans, result.get("is_correct", False),
         result.get("explanation", ""), datetime.now()]
    )
    con.close()
    return result


@app.get("/quiz/summary/{session_id}")
def quiz_summary(session_id: str):
    con = db()
    rows = con.execute(
        "SELECT question_idx, is_correct, feedback FROM quiz_results WHERE session_id = ? ORDER BY question_idx",
        [session_id]
    ).fetchall()
    session = con.execute(
        "SELECT subject, topic, question_count FROM quiz_sessions WHERE session_id = ?",
        [session_id]
    ).fetchone()
    con.close()
    if not session:
        return {"error": "Session not found"}
    answered = len(rows)
    correct  = sum(1 for r in rows if r[1])
    return {
        "subject": session[0], "topic": session[1],
        "total_questions": session[2],
        "answered": answered, "correct": correct,
        "score_pct": round(correct / answered * 100) if answered else 0,
    }


@app.get("/flashcards/{subject}")
def flashcards(subject: str, topic: str = ""):
    context = search_context(subject, topic or subject, n=12)
    ctx_block = f"\nReference material:\n{context}\n" if context else ""

    prompt = f"""Create 10 GCSE flashcards for {subject.upper()} — topic: {topic or "key concepts"}.
{ctx_block}
Return ONLY a JSON array:
[
  {{
    "front": "Key term or question",
    "back": "Definition, formula, or answer",
    "category": "definition|formula|process|fact"
  }}
]"""

    raw   = ask_claude(prompt, max_tokens=2000)
    cards = parse_json(raw)
    return {"subject": subject, "topic": topic, "flashcards": cards}


@app.get("/notes/{subject}")
def revision_notes(subject: str, topic: str = "", unit: str = ""):
    query   = f"{unit} {topic}".strip() if (unit or topic) else subject
    context = search_context(subject, query, n=12)
    ctx_block = f"\nReference material from student's documents:\n{context}\n" if context else \
                "\n(No indexed documents — using CCEA GCSE curriculum knowledge)\n"

    unit_line  = f"Unit: {unit}\n"   if unit  else ""
    topic_line = f"Topic: {topic}\n" if topic else ""

    prompt = f"""You are an expert CCEA GCSE {subject.upper()} teacher writing revision notes for a student.

{unit_line}{topic_line}{ctx_block}
Write thorough yet concise revision notes. Use this exact structure:

## Key Definitions
- Term: definition (include units where applicable)
(list ALL important terms for this topic)

## Key Formulas / Equations
- Formula name: equation (state each symbol and its unit)
(omit this section if topic has no formulae)

## Step-by-Step Method (if calculation topic)
1. Step one
2. Step two …
(omit this section if not applicable)

## Important Facts to Remember
- (5-8 specific, examinable facts with numbers/values)

## Worked Example
Show one short worked example relevant to this topic.

## Common Exam Mistakes
- (3-4 bullet points of typical student errors)

## Quick Summary
(2-3 sentences wrapping up the core idea)

Include specific CCEA GCSE values, units, equations and real examples. Write in plain text with bullet points."""

    notes = ask_claude(prompt, max_tokens=2000)
    return {"subject": subject, "unit": unit, "topic": topic, "notes": notes}


@app.post("/login")
def login(body: dict):
    sid  = body.get("student_id", "").strip().upper()
    pin  = body.get("pin", "").strip()
    con  = db()
    row  = con.execute(
        "SELECT name FROM students WHERE student_id=? AND pin=?", [sid, pin]
    ).fetchone()
    con.close()
    if row:
        return {"success": True, "student_id": sid, "name": row[0]}
    return {"success": False, "error": "Invalid Student ID or PIN"}


@app.get("/performance/{student_id}")
def get_performance(student_id: str):
    con = db()
    rows = con.execute("""
        SELECT qs.created_at, qs.subject, qs.topic, qs.question_count,
               COUNT(qr.result_id)                                           AS answered,
               SUM(CASE WHEN qr.is_correct THEN 1 ELSE 0 END)               AS correct
        FROM   quiz_sessions qs
        LEFT JOIN quiz_results qr ON qs.session_id = qr.session_id
        WHERE  qs.student_id = ?
        GROUP  BY qs.session_id, qs.created_at, qs.subject, qs.topic, qs.question_count
        ORDER  BY qs.created_at DESC
    """, [student_id]).fetchall()
    con.close()

    results = []
    for r in rows:
        answered  = int(r[4] or 0)
        correct   = int(r[5] or 0)
        score_pct = round(correct / answered * 100) if answered > 0 else 0
        results.append({
            "date":       str(r[0])[:16].replace("T", " "),
            "subject":    r[1],
            "topic":      r[2] or "General Revision",
            "questions":  r[3],
            "answered":   answered,
            "correct":    correct,
            "score_pct":  score_pct,
        })

    subj_totals: dict = {}
    for r in results:
        s = r["subject"]
        if s not in subj_totals:
            subj_totals[s] = {"answered": 0, "correct": 0, "sessions": 0}
        subj_totals[s]["answered"]  += r["answered"]
        subj_totals[s]["correct"]   += r["correct"]
        subj_totals[s]["sessions"]  += 1

    subject_avg = {
        k: round(v["correct"] / v["answered"] * 100) if v["answered"] > 0 else 0
        for k, v in subj_totals.items()
    }
    overall = round(sum(r["score_pct"] for r in results) / len(results)) if results else 0

    return {
        "student_id":      student_id,
        "results":         results,
        "subject_stats":   subj_totals,
        "subject_avg":     subject_avg,
        "overall_avg":     overall,
        "total_sessions":  len(results),
    }


@app.get("/stats")
def stats():
    con = db()
    docs = con.execute(
        "SELECT subject, COUNT(*) as files, SUM(chunk_count) as chunks FROM documents GROUP BY subject"
    ).fetchall()
    con.close()
    return {
        "total_chunks_in_chroma": collection.count(),
        "by_subject": [{"subject": r[0], "files": r[1], "chunks": r[2]} for r in docs],
    }


# ── Web UI ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>StudyBot UK — GCSE Revision</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e;min-height:100vh}
header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:18px 32px;
       display:flex;align-items:center;gap:14px}
header h1{font-size:1.4rem;font-weight:700}
header span{font-size:1.8rem}
.tabs{display:flex;background:#16213e;padding:0 32px}
.tab{padding:12px 22px;cursor:pointer;color:#aaa;font-weight:600;font-size:14px;
     border-bottom:3px solid transparent;transition:.2s}
.tab:hover{color:#fff}
.tab.active{color:#4fc3f7;border-bottom-color:#4fc3f7}
.page{display:none;padding:28px 32px;max-width:900px;margin:0 auto}
.page.active{display:block}
.card{background:white;border-radius:12px;padding:22px;margin-bottom:18px;
      box-shadow:0 2px 8px rgba(0,0,0,.08)}
h2{font-size:1.15rem;font-weight:700;margin-bottom:14px;color:#1a1a2e}
label{font-size:13px;font-weight:600;color:#555;display:block;margin-bottom:5px}
input[type=text]{width:100%;padding:10px 13px;border:1.5px solid #ddd;border-radius:8px;
                  font-size:14px;outline:none;transition:.2s}
input[type=text]:focus{border-color:#4fc3f7}
.pill-group{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px}
.pill{padding:7px 16px;border-radius:20px;border:2px solid #e0e0e0;background:white;
      cursor:pointer;font-size:13px;font-weight:600;transition:.2s;color:#555}
.pill:hover{border-color:#4fc3f7;color:#0288d1}
.pill.sel{background:#4fc3f7;color:white;border-color:#4fc3f7}
.btn{padding:10px 22px;border:none;border-radius:8px;cursor:pointer;font-size:14px;
     font-weight:600;transition:.2s}
.btn-primary{background:#4fc3f7;color:white}
.btn-primary:hover{background:#0288d1}
.btn-success{background:#66bb6a;color:white}
.btn-success:hover{background:#388e3c}
.btn-warn{background:#ffa726;color:white}
.btn-warn:hover{background:#ef6c00}
.btn:disabled{background:#ccc;cursor:not-allowed}
.q-card{background:#f8f9ff;border:1.5px solid #e8ecff;border-radius:10px;padding:18px;margin-bottom:14px}
.q-num{font-size:12px;font-weight:700;color:#7986cb;margin-bottom:6px}
.q-text{font-size:14px;font-weight:600;margin-bottom:10px;line-height:1.5}
.options label{display:flex;align-items:center;gap:8px;padding:6px 0;cursor:pointer;
               font-size:14px;font-weight:400}
.options input[type=radio]{accent-color:#4fc3f7;width:16px;height:16px}
.q-input{width:100%;padding:8px 11px;border:1.5px solid #ddd;border-radius:7px;
          font-size:14px;margin-top:6px}
.feedback-box{margin-top:10px;padding:12px;border-radius:8px;font-size:13px;line-height:1.5}
.fb-correct{background:#e8f5e9;border-left:4px solid #66bb6a}
.fb-wrong{background:#fce4ec;border-left:4px solid #ef5350}
.marks-badge{display:inline-block;background:#7986cb;color:white;border-radius:12px;
             font-size:11px;padding:2px 8px;margin-left:8px;font-weight:700}
.score-bar{height:12px;background:#e0e0e0;border-radius:6px;overflow:hidden;margin:8px 0}
.score-fill{height:100%;background:linear-gradient(90deg,#4fc3f7,#66bb6a);border-radius:6px;transition:1s}
.flash-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.flash-card{height:160px;perspective:600px;cursor:pointer}
.flash-inner{position:relative;width:100%;height:100%;
             transform-style:preserve-3d;transition:.5s;border-radius:10px}
.flash-card.flipped .flash-inner{transform:rotateY(180deg)}
.flash-front,.flash-back{position:absolute;width:100%;height:100%;backface-visibility:hidden;
                          border-radius:10px;display:flex;align-items:center;justify-content:center;
                          padding:16px;text-align:center;font-size:13px;line-height:1.5}
.flash-front{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;font-weight:600}
.flash-back{background:#e8f5e9;transform:rotateY(180deg);color:#1a1a2e;font-weight:500}
.cat-badge{position:absolute;top:8px;right:8px;font-size:10px;padding:2px 7px;
           border-radius:10px;background:rgba(255,255,255,.2);color:white;font-weight:600}
.flash-back .cat-badge{background:rgba(0,0,0,.1);color:#555}
.notes-body{font-size:14px;line-height:1.7;white-space:pre-wrap}
.notes-body h2,h3{margin:14px 0 6px;color:#1a1a2e}
.upload-zone{border:2px dashed #ccc;border-radius:10px;padding:28px;text-align:center;
             color:#999;cursor:pointer;transition:.2s}
.upload-zone:hover{border-color:#4fc3f7;color:#0288d1}
#toast{position:fixed;bottom:24px;right:24px;background:#1a1a2e;color:white;
       padding:12px 20px;border-radius:8px;font-size:13px;opacity:0;transition:.3s;z-index:99}
#toast.show{opacity:1}
.stat-row{display:flex;gap:8px;align-items:center;padding:6px 0;font-size:13px;
          border-bottom:1px solid #f0f0f0}
.stat-label{font-weight:600;width:100px}
.global-subj{background:#0f3460;padding:10px 32px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.gs-label{color:#aaa;font-size:13px;font-weight:600;white-space:nowrap}
.gs-pill{padding:6px 16px;border-radius:20px;border:2px solid rgba(255,255,255,.2);
         color:rgba(255,255,255,.7);cursor:pointer;font-size:13px;font-weight:600;transition:.2s}
.gs-pill:hover{border-color:#4fc3f7;color:#4fc3f7}
.gs-pill.sel{background:#4fc3f7;color:#0f3460;border-color:#4fc3f7}
.notes-layout{display:grid;grid-template-columns:270px 1fr;gap:18px;align-items:start}
@media(max-width:720px){.notes-layout{grid-template-columns:1fr}}
.topic-pill{display:inline-block;padding:5px 12px;margin:3px 3px 3px 0;border-radius:14px;
            border:1.5px solid #b3e5fc;background:#e1f5fe;cursor:pointer;
            font-size:12px;color:#0288d1;font-weight:600;transition:.2s}
.topic-pill:hover{background:#0288d1;color:white;border-color:#0288d1}
.nt-loading-card{background:white;border-radius:12px;padding:22px;box-shadow:0 2px 8px rgba(0,0,0,.08);
                  color:#999;font-size:14px;display:flex;align-items:center;gap:10px}
.unit-row{display:flex;align-items:center;justify-content:space-between;
          padding:11px 14px;margin-bottom:6px;border-radius:8px;cursor:pointer;
          border:2px solid #e8ecff;background:#f8f9ff;transition:.2s;font-size:13px;font-weight:600;color:#3949ab}
.unit-row:hover{border-color:#7986cb;background:#eef0ff}
.unit-row.unit-sel{border-color:#4fc3f7;background:#e1f5fe;color:#0288d1}
.unit-num{display:inline-block;background:#7986cb;color:white;border-radius:4px;
          font-size:11px;padding:2px 7px;margin-right:8px;font-weight:700}
.unit-row.unit-sel .unit-num{background:#0288d1}
.unit-arrow{font-size:18px;color:#bbb;font-weight:300}
.unit-row.unit-sel .unit-arrow{color:#0288d1;transform:rotate(90deg);display:inline-block}
.topic-chip{display:inline-block;padding:7px 14px;margin:4px;border-radius:20px;
            border:2px solid #e0e0e0;background:white;cursor:pointer;
            font-size:13px;color:#555;transition:.2s}
.topic-chip:hover{border-color:#4fc3f7;color:#0288d1}
.topic-chip.topic-sel{background:#0288d1;color:white;border-color:#0288d1}
.login-btn{padding:7px 16px;border-radius:20px;border:2px solid rgba(255,255,255,.3);
           background:transparent;color:rgba(255,255,255,.85);cursor:pointer;
           font-size:13px;font-weight:600;transition:.2s}
.login-btn:hover{border-color:#4fc3f7;color:#4fc3f7}
.student-badge{display:flex;align-items:center;gap:8px;color:white;font-size:13px}
.student-name{font-weight:700;color:#4fc3f7}
.logout-btn{padding:4px 10px;border-radius:12px;border:1.5px solid rgba(255,255,255,.3);
            background:transparent;color:rgba(255,255,255,.7);cursor:pointer;font-size:12px}
.logout-btn:hover{border-color:#ef5350;color:#ef5350}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:200;
               display:flex;align-items:center;justify-content:center}
.modal-box{background:white;border-radius:14px;padding:30px 28px;width:340px;
           box-shadow:0 8px 32px rgba(0,0,0,.25)}
.modal-box h3{margin:0 0 18px;font-size:1.1rem;color:#1a1a2e}
.modal-input{width:100%;padding:10px 13px;border:1.5px solid #ddd;border-radius:8px;
             font-size:14px;margin-bottom:10px;outline:none;box-sizing:border-box}
.modal-input:focus{border-color:#4fc3f7}
.modal-hint{background:#f0f8ff;border-radius:8px;padding:10px 12px;font-size:12px;
            color:#555;margin-bottom:14px;line-height:1.6}
.modal-hint b{color:#0288d1}
.modal-err{color:#ef5350;font-size:13px;margin-bottom:8px;min-height:18px}
.perf-stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-bottom:20px}
.perf-stat{background:white;border-radius:10px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,.07);text-align:center}
.perf-stat-val{font-size:1.8rem;font-weight:800;color:#1a1a2e;line-height:1}
.perf-stat-lbl{font-size:12px;color:#888;margin-top:4px;font-weight:600}
.subj-bar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.subj-bar-label{width:90px;font-size:13px;font-weight:600;color:#1a1a2e;text-align:right}
.subj-bar-track{flex:1;height:14px;background:#e0e0e0;border-radius:7px;overflow:hidden}
.subj-bar-fill{height:100%;border-radius:7px;transition:width 1s}
.subj-bar-pct{width:38px;font-size:13px;font-weight:700;color:#1a1a2e}
.perf-table{width:100%;border-collapse:collapse;font-size:13px}
.perf-table th{background:#f8f9ff;padding:9px 12px;text-align:left;font-weight:700;
               color:#3949ab;border-bottom:2px solid #e8ecff}
.perf-table td{padding:9px 12px;border-bottom:1px solid #f0f0f0;vertical-align:middle}
.perf-table tr:hover td{background:#fafbff}
.grade-badge{display:inline-block;padding:3px 9px;border-radius:10px;font-size:11px;font-weight:700}
.grade-a{background:#e8f5e9;color:#2e7d32}
.grade-b{background:#e3f2fd;color:#1565c0}
.grade-c{background:#fff3e0;color:#e65100}
.grade-d{background:#fce4ec;color:#c62828}
</style>
</head>
<body>
<header style="display:flex;align-items:center">
  <span>📚</span>
  <div>
    <h1>StudyBot UK</h1>
    <div style="font-size:12px;color:#aaa">GCSE Revision • Chemistry · Physics · Maths</div>
  </div>
  <div style="margin-left:auto">
    <div id="login-widget">
      <button class="login-btn" onclick="showLoginModal()">👤 Student Login</button>
    </div>
    <div id="student-badge" class="student-badge" style="display:none">
      <span>👤</span>
      <span id="student-name-hdr" class="student-name"></span>
      <button class="logout-btn" onclick="doLogout()">Logout</button>
    </div>
  </div>
</header>

<div class="global-subj">
  <span class="gs-label">Subject:</span>
  <div id="gs-group" style="display:flex;gap:8px;flex-wrap:wrap">
    <div class="gs-pill sel" onclick="selSubject(this,'chemistry')">🧪 Chemistry</div>
    <div class="gs-pill" onclick="selSubject(this,'physics')">⚡ Physics</div>
    <div class="gs-pill" onclick="selSubject(this,'maths_m4')">📐 Maths M4</div>
    <div class="gs-pill" onclick="selSubject(this,'maths_m8')">📐 Maths M8</div>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showPage('quiz',this)">🧪 Quiz</div>
  <div class="tab" onclick="showPage('flash',this)">🃏 Flashcards</div>
  <div class="tab" onclick="showPage('notes',this)">📝 Notes</div>
  <div class="tab" onclick="showPage('upload',this)">⬆️ Upload</div>
  <div class="tab" onclick="showPage('stats',this)">📊 Stats</div>
  <div class="tab" onclick="showPage('perf',this)">📈 Performance</div>
</div>

<!-- LOGIN MODAL -->
<div id="login-modal" class="modal-overlay" style="display:none" onclick="if(event.target===this)hideLoginModal()">
  <div class="modal-box">
    <h3>👤 Student Login</h3>
    <div class="modal-hint">
      <b>Sample accounts:</b><br>
      ST001 Alice Johnson — PIN 1234<br>
      ST002 Ben Murphy — PIN 2345<br>
      ST003 Chloe Davies — PIN 3456<br>
      ST004 Daniel Smith — PIN 4567<br>
      ST005 Emma Wilson — PIN 5678
    </div>
    <input class="modal-input" id="login-id" type="text" placeholder="Student ID (e.g. ST001)" maxlength="5"
           oninput="this.value=this.value.toUpperCase()">
    <input class="modal-input" id="login-pin" type="password" placeholder="PIN"
           maxlength="4" onkeydown="if(event.key==='Enter')doLogin()">
    <div class="modal-err" id="login-err"></div>
    <div style="display:flex;gap:10px">
      <button class="btn btn-primary" style="flex:1" onclick="doLogin()">Login</button>
      <button class="btn" style="flex:1;background:#eee;color:#555" onclick="hideLoginModal()">Cancel</button>
    </div>
  </div>
</div>

<!-- QUIZ PAGE -->
<div class="page active" id="page-quiz">
  <div class="card">
    <h2>Configure Your Quiz</h2>
    <div style="margin-bottom:14px">
      <label>Number of Questions</label>
      <div class="pill-group" id="count-group" style="margin-top:6px">
        <div class="pill" onclick="selPill(this,'count-group',10)">10</div>
        <div class="pill sel" onclick="selPill(this,'count-group',15)">15</div>
        <div class="pill" onclick="selPill(this,'count-group',20)">20</div>
        <div class="pill" onclick="selPill(this,'count-group',30)">30</div>
        <div class="pill" onclick="selPill(this,'count-group',50)">50</div>
      </div>
    </div>
    <div style="margin-top:14px">
      <label>Topic (optional — leave blank for general revision)</label>
      <input id="quiz-topic" type="text" placeholder="e.g. Rates of Reaction, Quadratic Equations, Forces…">
    </div>
    <div style="margin-top:14px;display:flex;gap:10px">
      <button class="btn btn-primary" id="gen-btn" onclick="generateQuiz()">🎯 Generate Quiz</button>
      <button class="btn btn-warn" onclick="submitAll()" id="submit-btn" style="display:none">✅ Submit All &amp; Check</button>
    </div>
  </div>

  <div id="quiz-area"></div>
  <div class="card" id="score-card" style="display:none">
    <h2>Quiz Results</h2>
    <div id="score-summary"></div>
  </div>
</div>

<!-- FLASHCARDS PAGE -->
<div class="page" id="page-flash">
  <div class="card">
    <h2>Flashcards</h2>
    <div style="margin-bottom:14px">
      <label>Topic (optional)</label>
      <input id="fl-topic" type="text" placeholder="e.g. Atomic Structure, Fractions…" style="margin-top:6px">
    </div>
    <button class="btn btn-primary" onclick="loadFlashcards()">🃏 Load Flashcards</button>
  </div>
  <div class="flash-grid" id="flash-area"></div>
</div>

<!-- NOTES PAGE -->
<div class="page" id="page-notes">
  <div class="notes-layout">

    <!-- Left: unit list -->
    <div class="card" style="margin-bottom:0;position:sticky;top:18px">
      <h2 style="margin-bottom:4px">Units</h2>
      <div style="font-size:12px;color:#999;margin-bottom:12px">CCEA GCSE — click any unit</div>
      <div id="nt-unit-list"><span style="color:#bbb;font-size:13px">Select a subject above</span></div>
    </div>

    <!-- Right: notes output -->
    <div>
      <div class="nt-loading-card" id="nt-loading" style="display:none">
        <span style="font-size:20px">⏳</span> Generating notes — please wait…
      </div>
      <div class="card" id="notes-area" style="display:none;margin-bottom:0">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px">
          <div>
            <div id="notes-breadcrumb" style="font-size:11px;color:#7986cb;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px"></div>
            <h2 id="notes-title" style="margin:0;font-size:1.2rem"></h2>
          </div>
          <button class="btn btn-warn" style="font-size:12px;padding:6px 14px;flex-shrink:0" onclick="printNotes()">🖨️ Print</button>
        </div>
        <div id="notes-topics-bar" style="margin-bottom:14px;display:none">
          <div style="font-size:11px;font-weight:700;color:#7986cb;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Topics in this unit — click for focused notes</div>
          <div id="notes-topic-pills"></div>
        </div>
        <hr style="border:none;border-top:1px solid #eee;margin-bottom:14px">
        <div class="notes-body" id="notes-content"></div>
      </div>
    </div>

  </div>
</div>

<!-- UPLOAD PAGE -->
<div class="page" id="page-upload">
  <div class="card">
    <h2>Upload Study Documents</h2>
    <p style="font-size:13px;color:#666;margin-bottom:14px">
      Upload PDFs (text, numbers, images, math symbols all supported). They will be indexed into ChromaDB for quiz/flashcard generation.
    </p>
    <div style="font-size:13px;color:#0288d1;font-weight:600;margin-bottom:10px">
      Uploading for: <span id="upload-subj-label">Chemistry</span> (change via Subject bar above)
    </div>
    <div>
      <input type="file" id="pdf-file" accept=".pdf" multiple style="display:none" onchange="uploadFiles()">
      <div class="upload-zone" onclick="document.getElementById('pdf-file').click()">
        📄 Click to select PDF(s) — or drag &amp; drop<br>
        <small style="font-size:12px">Supports: text · numbers · images · maths symbols</small>
      </div>
    </div>
    <div id="upload-log" style="margin-top:12px;font-size:13px"></div>
  </div>
  <div class="card">
    <h2>Re-index All (Folder Scan)</h2>
    <p style="font-size:13px;color:#666;margin-bottom:12px">
      Scan all configured subject folders and index any new PDFs into ChromaDB.
    </p>
    <button class="btn btn-warn" onclick="ingestAll()">🔄 Run Full Ingest</button>
    <div id="ingest-status" style="margin-top:10px;font-size:13px"></div>
  </div>
</div>

<!-- STATS PAGE -->
<div class="page" id="page-stats">
  <div class="card">
    <h2>Index Statistics</h2>
    <button class="btn btn-primary" onclick="loadStats()" style="margin-bottom:14px">Refresh</button>
    <div id="stats-area">Click Refresh to load stats.</div>
  </div>
</div>

<!-- PERFORMANCE PAGE -->
<div class="page" id="page-perf">
  <div id="perf-login-notice" class="card" style="text-align:center;padding:40px">
    <div style="font-size:2.5rem;margin-bottom:12px">📈</div>
    <h2 style="margin-bottom:8px">Student Performance</h2>
    <p style="color:#888;margin-bottom:16px;font-size:14px">Please log in to view your performance dashboard.</p>
    <button class="btn btn-primary" onclick="showLoginModal()">👤 Login</button>
  </div>
  <div id="perf-content" style="display:none">
    <div class="perf-stat-grid" id="perf-stats"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px">
      <div class="card" style="margin:0">
        <h2 style="margin-bottom:14px">Performance by Subject</h2>
        <div id="perf-subj-bars"></div>
      </div>
      <div class="card" style="margin:0">
        <h2 style="margin-bottom:14px">Score Trend</h2>
        <canvas id="perf-trend-canvas" width="400" height="180"></canvas>
      </div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h2 style="margin:0">Quiz History</h2>
        <button class="btn btn-primary" style="font-size:12px;padding:6px 14px" onclick="loadPerformance()">🔄 Refresh</button>
      </div>
      <div style="overflow-x:auto">
        <table class="perf-table" id="perf-table">
          <thead><tr>
            <th>Date &amp; Time</th><th>Subject</th><th>Topic</th>
            <th>Score</th><th>Correct</th><th>Grade</th>
          </tr></thead>
          <tbody id="perf-tbody"></tbody>
        </table>
      </div>
      <div id="perf-empty" style="display:none;text-align:center;padding:30px;color:#bbb;font-size:14px">
        No quizzes completed yet. Take a quiz to see your results here!
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const state = { subject:'chemistry', count:15, sessionId:null, questions:[], student:null };
let ntCurriculum = [];

function selSubject(el, subject){
  document.querySelectorAll('#gs-group .gs-pill').forEach(p=>p.classList.remove('sel'));
  el.classList.add('sel');
  state.subject = subject;
  // keep upload label in sync
  const lbl = document.getElementById('upload-subj-label');
  if(lbl) lbl.innerText = el.innerText.trim();
  // if notes tab is open, reload units immediately
  if(document.getElementById('page-notes').classList.contains('active')) loadUnits();
}

function showPage(name, tab){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  tab.classList.add('active');
  if(name==='notes') loadUnits();
}

function selPill(el, groupId, val){
  document.querySelectorAll('#'+groupId+' .pill').forEach(p=>p.classList.remove('sel'));
  el.classList.add('sel');
  if(groupId==='count-group') state.count=val;
}

function toast(msg){
  const t=document.getElementById('toast');
  t.innerText=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2500);
}

function loading(el,msg){el.disabled=true;el.dataset.orig=el.innerText;el.innerText=msg;}
function done(el){el.disabled=false;el.innerText=el.dataset.orig;}

// ── QUIZ ──────────────────────────────────────────────────────────────────────
async function generateQuiz(){
  const btn=document.getElementById('gen-btn');
  loading(btn,'⏳ Generating…');
  document.getElementById('quiz-area').innerHTML='';
  document.getElementById('score-card').style.display='none';
  document.getElementById('submit-btn').style.display='none';

  const topic=document.getElementById('quiz-topic').value.trim();
  try{
    const r=await fetch('/quiz/generate',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({subject:state.subject,topic,count:state.count,
                           student_id:state.student?state.student.student_id:''})
    });
    const d=await r.json();
    if(d.error){toast('❌ '+d.error);return;}
    state.sessionId=d.session_id;
    state.questions=d.questions;
    renderQuestions(d.questions);
    document.getElementById('submit-btn').style.display='inline-block';
    toast('✅ '+d.questions.length+' questions ready!');
  }catch(e){toast('❌ '+e.message);}
  finally{done(btn);}
}

function renderQuestions(qs){
  const area=document.getElementById('quiz-area');
  area.innerHTML=qs.map((q,i)=>{
    const marks=q.marks||1;
    let ansHtml='';
    if(q.type==='mcq' && q.options && q.options.length){
      ansHtml='<div class="options">'+q.options.map((opt,j)=>`
        <label><input type="radio" name="q${i}" value="${opt}"> ${opt}</label>`).join('')+'</div>';
    } else {
      ansHtml=`<input class="q-input" id="ans-${i}" type="text" placeholder="Your answer…">`;
    }
    return `<div class="q-card" id="qc-${i}">
      <div class="q-num">Q${i+1} <span class="marks-badge">${marks} mark${marks>1?'s':''}</span></div>
      <div class="q-text">${q.q}</div>
      ${ansHtml}
      <div class="feedback-box" id="fb-${i}" style="display:none"></div>
    </div>`;
  }).join('');
}

function getStudentAnswer(i){
  const q=state.questions[i];
  if(q.type==='mcq'){
    const checked=document.querySelector(`input[name="q${i}"]:checked`);
    return checked?checked.value:'';
  }
  return (document.getElementById('ans-'+i)||{value:''}).value.trim();
}

async function submitAll(){
  const btn=document.getElementById('submit-btn');
  loading(btn,'⏳ Checking…');
  let correct=0, total=state.questions.length;

  for(let i=0;i<total;i++){
    const ans=getStudentAnswer(i);
    if(!ans){
      document.getElementById('fb-'+i).style.display='block';
      document.getElementById('fb-'+i).className='feedback-box fb-wrong';
      document.getElementById('fb-'+i).innerHTML='<b>No answer provided.</b>';
      continue;
    }
    try{
      const r=await fetch('/quiz/answer',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:state.sessionId,question_idx:i,answer:ans})
      });
      const d=await r.json();
      if(d.is_correct) correct++;
      const fb=document.getElementById('fb-'+i);
      fb.style.display='block';
      fb.className='feedback-box '+(d.is_correct?'fb-correct':'fb-wrong');
      fb.innerHTML=(d.is_correct?'✅ ':'❌ ')+'<b>'+d.feedback+'</b>'
        +(d.is_correct?'':('<br><br><b>Explanation:</b> '+d.explanation
          +'<br><br>💡 <b>Tip:</b> '+d.tip));
    }catch(e){}
  }
  done(btn);
  showScore(correct, total);
}

function showScore(correct,total){
  const sc=document.getElementById('score-card');
  sc.style.display='block';
  const pct=Math.round(correct/total*100);
  const grade=pct>=70?'🏆 Excellent!':pct>=55?'👍 Good effort':pct>=40?'📖 Keep revising':'💪 More practice needed';
  document.getElementById('score-summary').innerHTML=`
    <div style="font-size:2rem;font-weight:700;color:#1a1a2e">${correct}/${total} <span style="font-size:1rem;color:#666">(${pct}%)</span></div>
    <div style="font-size:1.1rem;margin:6px 0">${grade}</div>
    <div class="score-bar"><div class="score-fill" style="width:${pct}%"></div></div>
    <div style="font-size:13px;color:#666;margin-top:8px">Wrong answers show explanation + tip above — review them!</div>`;
  sc.scrollIntoView({behavior:'smooth'});
}

// ── FLASHCARDS ────────────────────────────────────────────────────────────────
async function loadFlashcards(){
  const topic=document.getElementById('fl-topic').value.trim();
  const area=document.getElementById('flash-area');
  area.innerHTML='<div style="padding:20px;color:#999">Loading flashcards…</div>';
  try{
    const r=await fetch(`/flashcards/${state.subject}?topic=${encodeURIComponent(topic)}`);
    const d=await r.json();
    if(!d.flashcards||!d.flashcards.length){area.innerHTML='<p>No flashcards returned.</p>';return;}
    area.innerHTML=d.flashcards.map(c=>`
      <div class="flash-card" onclick="this.classList.toggle('flipped')">
        <div class="flash-inner">
          <div class="flash-front">
            <span class="cat-badge">${c.category}</span>
            ${c.front}
          </div>
          <div class="flash-back">
            <span class="cat-badge" style="background:rgba(0,0,0,.08);color:#555">${c.category}</span>
            ${c.back}
          </div>
        </div>
      </div>`).join('');
    toast('🃏 '+d.flashcards.length+' cards loaded — click to flip!');
  }catch(e){area.innerHTML='<p style="color:red">Error: '+e.message+'</p>';}
}

// ── NOTES ─────────────────────────────────────────────────────────────────────
async function loadUnits(){
  const unitList = document.getElementById('nt-unit-list');
  unitList.innerHTML = '<span style="color:#999;font-size:13px">Loading…</span>';
  document.getElementById('notes-area').style.display = 'none';
  document.getElementById('nt-loading').style.display = 'none';
  try{
    const r = await fetch('/curriculum/'+state.subject);
    const d = await r.json();
    if(d.error){ unitList.innerHTML='<span style="color:red">'+d.error+'</span>'; return; }
    ntCurriculum = d.units;
    unitList.innerHTML = d.units.map((u,i)=>`
      <div class="unit-row" id="nt-unit-${i}" onclick="loadUnitNotes(${i},this)">
        <div>
          <div class="unit-num">Unit ${i+1}</div>
          <div style="font-size:13px;margin-top:3px">${u.unit.replace(/^Unit [0-9]+[:.\\s]*/i,'')}</div>
        </div>
        <span class="unit-arrow">›</span>
      </div>`).join('');
  }catch(e){ unitList.innerHTML='<span style="color:red">'+e.message+'</span>'; }
}

async function loadUnitNotes(idx, el){
  document.querySelectorAll('.unit-row').forEach(r=>r.classList.remove('unit-sel'));
  el.classList.add('unit-sel');
  const unit = ntCurriculum[idx];
  document.getElementById('nt-loading').style.display = 'block';
  document.getElementById('notes-area').style.display = 'none';
  try{
    const params = new URLSearchParams({ unit: unit.unit });
    const r = await fetch('/notes/'+state.subject+'?'+params);
    const d = await r.json();
    // topic pills for drill-down
    const pbar = document.getElementById('notes-topics-bar');
    const ppills = document.getElementById('notes-topic-pills');
    ppills.innerHTML = unit.topics.map((t,j)=>
      `<span class="topic-pill" onclick="loadTopicNotes(${idx},${j})">${t}</span>`
    ).join('');
    pbar.style.display = 'block';
    document.getElementById('notes-breadcrumb').innerText =
      state.subject.replace('_',' ').toUpperCase() + '  ›  ' + unit.unit;
    document.getElementById('notes-title').innerText =
      unit.unit.replace(/^Unit [0-9]+[:.\\s]*/i,'');
    document.getElementById('notes-content').innerHTML = formatNotes(d.notes||'');
    document.getElementById('notes-area').style.display = 'block';
    toast('📝 Notes ready!');
  }catch(e){
    document.getElementById('notes-content').innerText = 'Error: '+e.message;
    document.getElementById('notes-area').style.display = 'block';
  }finally{
    document.getElementById('nt-loading').style.display = 'none';
  }
}

async function loadTopicNotes(unitIdx, topicIdx){
  const unit = ntCurriculum[unitIdx];
  const topic = unit.topics[topicIdx];
  document.getElementById('nt-loading').style.display = 'block';
  document.getElementById('notes-area').style.display = 'none';
  try{
    const params = new URLSearchParams({ unit: unit.unit, topic });
    const r = await fetch('/notes/'+state.subject+'?'+params);
    const d = await r.json();
    document.getElementById('notes-topics-bar').style.display = 'none';
    document.getElementById('notes-breadcrumb').innerText =
      state.subject.replace('_',' ').toUpperCase() + '  ›  ' + unit.unit;
    document.getElementById('notes-title').innerText = topic;
    document.getElementById('notes-content').innerHTML = formatNotes(d.notes||'');
    document.getElementById('notes-area').style.display = 'block';
    toast('📝 Notes ready — '+topic);
  }catch(e){
    document.getElementById('notes-content').innerText = 'Error: '+e.message;
    document.getElementById('notes-area').style.display = 'block';
  }finally{
    document.getElementById('nt-loading').style.display = 'none';
  }
}

function formatNotes(text){
  return text
    .replace(/^## (.+)$/gm,'<h3 style="margin:18px 0 7px;color:#1a1a2e;font-size:15px">$1</h3>')
    .replace(/^- (.+)$/gm,'<li style="margin:3px 0 3px 18px">$1</li>')
    .replace(/^[0-9]+[.] (.+)$/gm,'<li style="margin:3px 0 3px 18px;list-style:decimal">$1</li>')
    .replace(/[*][*](.+?)[*][*]/g,'<b>$1</b>');
}

function printNotes(){
  const content = document.getElementById('notes-area').innerHTML;
  const w = window.open('','_blank');
  w.document.write('<html><head><title>Notes</title><style>body{font-family:sans-serif;padding:24px;font-size:13px;line-height:1.6}h3{color:#1a1a2e}li{margin:3px 0}</style></head><body>'+content+'</body></html>');
  w.print();
}

// ── UPLOAD ────────────────────────────────────────────────────────────────────
async function uploadFiles(){
  const files=document.getElementById('pdf-file').files;
  const log=document.getElementById('upload-log');
  log.innerHTML='';
  for(const file of files){
    log.innerHTML+=`<div>⏳ Uploading ${file.name}…</div>`;
    const fd=new FormData();
    fd.append('file',file);
    fd.append('subject',state.upSubject);
    try{
      const r=await fetch('/upload',{method:'POST',body:fd});
      const d=await r.json();
      if(d.chunks_indexed!==undefined)
        log.innerHTML+=`<div style="color:green">✅ ${file.name} → ${d.chunks_indexed} chunks indexed</div>`;
      else
        log.innerHTML+=`<div style="color:red">❌ ${file.name}: ${d.error||JSON.stringify(d)}</div>`;
    }catch(e){log.innerHTML+=`<div style="color:red">❌ ${file.name}: ${e.message}</div>`;}
  }
}

async function ingestAll(){
  document.getElementById('ingest-status').innerText='⏳ Running ingest — this may take several minutes…';
  try{
    const r=await fetch('/ingest/all',{method:'POST'});
    const d=await r.json();
    document.getElementById('ingest-status').innerHTML=
      `<span style="color:green">✅ Done. Total chunks: ${d.total_chunks}</span>`;
  }catch(e){
    document.getElementById('ingest-status').innerHTML=`<span style="color:red">❌ ${e.message}</span>`;
  }
}

// ── STATS ─────────────────────────────────────────────────────────────────────
async function loadStats(){
  const area=document.getElementById('stats-area');
  area.innerHTML='Loading…';
  try{
    const r=await fetch('/stats');
    const d=await r.json();
    area.innerHTML=`
      <div class="stat-row"><span class="stat-label">Total chunks</span> ${d.total_chunks_in_chroma}</div>
      ${(d.by_subject||[]).map(s=>`
      <div class="stat-row">
        <span class="stat-label">${s.subject}</span>
        ${s.files} file(s) · ${s.chunks} chunks
      </div>`).join('')}`;
  }catch(e){area.innerHTML='<span style="color:red">'+e.message+'</span>';}
}

// ── LOGIN ─────────────────────────────────────────────────────────────────────
function showLoginModal(){
  document.getElementById('login-modal').style.display='flex';
  document.getElementById('login-id').focus();
  document.getElementById('login-err').innerText='';
}
function hideLoginModal(){
  document.getElementById('login-modal').style.display='none';
}
async function doLogin(){
  const sid = document.getElementById('login-id').value.trim().toUpperCase();
  const pin = document.getElementById('login-pin').value.trim();
  if(!sid||!pin){ document.getElementById('login-err').innerText='Enter Student ID and PIN.'; return; }
  try{
    const r = await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},
                                    body:JSON.stringify({student_id:sid,pin})});
    const d = await r.json();
    if(d.success){
      state.student = {student_id:d.student_id, name:d.name};
      document.getElementById('login-widget').style.display='none';
      document.getElementById('student-badge').style.display='flex';
      document.getElementById('student-name-hdr').innerText=d.name;
      document.getElementById('login-pin').value='';
      hideLoginModal();
      toast('Welcome, '+d.name+'!');
      // refresh performance if on that tab
      if(document.getElementById('page-perf').classList.contains('active')) loadPerformance();
    } else {
      document.getElementById('login-err').innerText = d.error || 'Login failed.';
    }
  }catch(e){ document.getElementById('login-err').innerText='Error: '+e.message; }
}
function doLogout(){
  state.student = null;
  document.getElementById('student-badge').style.display='none';
  document.getElementById('login-widget').style.display='block';
  document.getElementById('login-id').value='';
  document.getElementById('login-pin').value='';
  document.getElementById('perf-content').style.display='none';
  document.getElementById('perf-login-notice').style.display='block';
  toast('Logged out.');
}

// ── PERFORMANCE ───────────────────────────────────────────────────────────────
function gradeInfo(pct){
  if(pct>=70) return {label:'A*–A', cls:'grade-a'};
  if(pct>=55) return {label:'B–C',  cls:'grade-b'};
  if(pct>=40) return {label:'D–E',  cls:'grade-c'};
  return            {label:'U',     cls:'grade-d'};
}
function subjColor(subj){
  const m={'chemistry':'#26c6da','physics':'#7986cb','maths_m4':'#66bb6a','maths_m8':'#ffa726'};
  return m[subj]||'#4fc3f7';
}

async function loadPerformance(){
  if(!state.student){
    document.getElementById('perf-login-notice').style.display='block';
    document.getElementById('perf-content').style.display='none';
    return;
  }
  document.getElementById('perf-login-notice').style.display='none';
  document.getElementById('perf-content').style.display='block';

  const r = await fetch('/performance/'+state.student.student_id);
  const d = await r.json();

  // Stat cards
  const bestSubj = Object.entries(d.subject_avg||{}).sort((a,b)=>b[1]-a[1])[0];
  document.getElementById('perf-stats').innerHTML=`
    <div class="perf-stat">
      <div class="perf-stat-val">${d.total_sessions}</div>
      <div class="perf-stat-lbl">Total Quizzes</div>
    </div>
    <div class="perf-stat">
      <div class="perf-stat-val" style="color:${d.overall_avg>=55?'#2e7d32':'#c62828'}">${d.overall_avg}%</div>
      <div class="perf-stat-lbl">Overall Average</div>
    </div>
    <div class="perf-stat">
      <div class="perf-stat-val" style="font-size:1.1rem">${bestSubj?bestSubj[0].replace('_',' ').toUpperCase():'—'}</div>
      <div class="perf-stat-lbl">Best Subject</div>
    </div>
    <div class="perf-stat">
      <div class="perf-stat-val">${d.results.reduce((s,r)=>s+r.answered,0)}</div>
      <div class="perf-stat-lbl">Questions Answered</div>
    </div>`;

  // Subject bars
  document.getElementById('perf-subj-bars').innerHTML =
    Object.entries(d.subject_avg||{}).map(([subj,pct])=>`
      <div class="subj-bar-row">
        <div class="subj-bar-label">${subj.replace('_',' ')}</div>
        <div class="subj-bar-track">
          <div class="subj-bar-fill" style="width:${pct}%;background:${subjColor(subj)}"></div>
        </div>
        <div class="subj-bar-pct">${pct}%</div>
      </div>`).join('') || '<span style="color:#bbb;font-size:13px">No data yet</span>';

  // Trend mini-chart (canvas sparkline)
  const scores = d.results.slice().reverse().map(r=>r.score_pct);
  drawSparkline(scores);

  // Table
  const tbody = document.getElementById('perf-tbody');
  if(!d.results.length){
    tbody.innerHTML='';
    document.getElementById('perf-empty').style.display='block';
    document.getElementById('perf-table').style.display='none';
  } else {
    document.getElementById('perf-empty').style.display='none';
    document.getElementById('perf-table').style.display='table';
    tbody.innerHTML = d.results.map(r=>{
      const g=gradeInfo(r.score_pct);
      return `<tr>
        <td style="color:#888;white-space:nowrap">${r.date}</td>
        <td><span style="font-weight:600;color:${subjColor(r.subject)}">${r.subject.replace('_',' ').toUpperCase()}</span></td>
        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.topic}</td>
        <td><b>${r.correct}/${r.answered}</b></td>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <div style="width:60px;height:8px;background:#eee;border-radius:4px;overflow:hidden">
              <div style="width:${r.score_pct}%;height:100%;background:${subjColor(r.subject)};border-radius:4px"></div>
            </div>
            <b>${r.score_pct}%</b>
          </div>
        </td>
        <td><span class="grade-badge ${g.cls}">${g.label}</span></td>
      </tr>`;}).join('');
  }
}

function drawSparkline(scores){
  const canvas = document.getElementById('perf-trend-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(!scores.length){ ctx.fillStyle='#bbb'; ctx.font='13px sans-serif';
    ctx.fillText('No data yet',140,95); return; }
  const W=canvas.width, H=canvas.height, pad=24;
  const n=scores.length, maxV=100, minV=0;
  const xStep=(W-2*pad)/(Math.max(n-1,1));
  // grid lines
  ctx.strokeStyle='#eee'; ctx.lineWidth=1;
  [0,25,50,75,100].forEach(v=>{
    const y=pad+(H-2*pad)*(1-v/100);
    ctx.beginPath(); ctx.moveTo(pad,y); ctx.lineTo(W-pad,y); ctx.stroke();
    ctx.fillStyle='#bbb'; ctx.font='10px sans-serif'; ctx.fillText(v+'%',2,y+4);
  });
  // line
  ctx.beginPath(); ctx.strokeStyle='#4fc3f7'; ctx.lineWidth=2.5;
  scores.forEach((v,i)=>{
    const x=pad+i*xStep, y=pad+(H-2*pad)*(1-v/100);
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  ctx.stroke();
  // dots
  scores.forEach((v,i)=>{
    const x=pad+i*xStep, y=pad+(H-2*pad)*(1-v/100);
    ctx.beginPath(); ctx.arc(x,y,4,0,2*Math.PI);
    ctx.fillStyle=v>=55?'#66bb6a':'#ef5350'; ctx.fill();
  });
}

// auto-load performance when tab is opened
const _origShowPage = showPage;
function showPage(name,tab){
  _origShowPage(name,tab);
  if(name==='perf') loadPerformance();
}
</script>
</body>
</html>"""
