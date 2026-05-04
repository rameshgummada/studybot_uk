import os, json, uuid, shutil, tempfile, hashlib, secrets, random, string
from datetime import datetime, date
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
    {"sid": "ST000001", "first": "Alice",  "last": "Johnson", "email": "alice@demo.studybot.uk",  "dob": "2009-03-15", "year": 11},
    {"sid": "ST000002", "first": "Ben",    "last": "Murphy",  "email": "ben@demo.studybot.uk",    "dob": "2008-07-22", "year": 11},
    {"sid": "ST000003", "first": "Chloe",  "last": "Davies",  "email": "chloe@demo.studybot.uk",  "dob": "2008-11-08", "year": 11},
    {"sid": "ST000004", "first": "Daniel", "last": "Smith",   "email": "daniel@demo.studybot.uk", "dob": "2008-02-14", "year": 11},
    {"sid": "ST000005", "first": "Emma",   "last": "Wilson",  "email": "emma@demo.studybot.uk",   "dob": "2009-09-30", "year": 11},
]
_DEMO_PASSWORD = "Study123!"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
    return f"{salt}:{pw_hash}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, pw_hash = stored.split(":", 1)
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex() == pw_hash
    except Exception:
        return False


def generate_student_id(con) -> str:
    while True:
        sid = "ST" + "".join(random.choices(string.digits, k=6))
        if not con.execute("SELECT 1 FROM students WHERE student_id=?", [sid]).fetchone():
            return sid


def db():
    con = duckdb.connect(DUCKDB_PATH)
    init_db(con)
    return con


def seed_students():
    con = db()
    now = datetime.now()
    for s in SAMPLE_STUDENTS:
        if not con.execute("SELECT 1 FROM students WHERE student_id=?", [s["sid"]]).fetchone():
            ph = hash_password(_DEMO_PASSWORD)
            con.execute("""
                INSERT INTO students (student_id, first_name, last_name, email, date_of_birth, school_year,
                                     password_hash, is_active, gdpr_consent, consent_date, created_at)
                VALUES (?,?,?,?,?,?,?,TRUE,TRUE,?,?)
            """, [s["sid"], s["first"], s["last"], s["email"], s["dob"], s["year"], ph, now, now])
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

    context = search_context(subject, topic or subject, n=20)
    ctx_block = f"\nExtracted content from indexed past papers and study documents:\n{context}\n" if context else \
                "\n(No indexed documents — using CCEA GCSE curriculum knowledge)\n"

    prompt = f"""You are a CCEA GCSE {subject.upper()} examiner setting an exam paper.

Subject: {subject.upper()}
Topic: {topic if topic else "general revision — draw from all topics present in the material"}
Number of questions: {count}
{ctx_block}
TASK: Extract or closely adapt exam questions FROM the reference material above.
Ground every question in facts, values, equations, or examples present in that material.
Do NOT invent content that is absent from the material.

Use a mix of question types:
- mcq  = multiple choice with 4 options (A B C D), 1 mark
- short = written short answer, 1–4 marks
- calc  = calculation requiring working shown, 2–5 marks

For each question also produce a MARK SCHEME — one bullet per mark, each bullet is the
minimum keyword or phrase an examiner accepts for that mark.

Return ONLY a JSON array (no markdown, no preamble):
[
  {{
    "q": "Full question text as it would appear on the exam paper",
    "type": "mcq|short|calc",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "answer": "correct answer text or option letter",
    "mark_scheme": [
      "key word / accepted phrase that earns mark 1",
      "key word / accepted phrase that earns mark 2"
    ],
    "marks": 2
  }}
]
Rules:
- Omit "options" for short/calc questions.
- mark_scheme length MUST equal marks.
- For mcq, mark_scheme = ["Correct: X) <option text>"].
- marks for mcq = 1, short = 1–4, calc = 2–5."""

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

    question    = json.loads(row[0])[question_idx]
    marks       = question.get("marks", 1)
    mark_scheme = question.get("mark_scheme", [question.get("answer", "")])
    q_type      = question.get("type", "short")

    scheme_lines = "\n".join(f"  • {p}" for p in mark_scheme)

    prompt = f"""You are a strict CCEA GCSE examiner marking a student's answer against the official mark scheme.

Question: {question["q"]}
Question type: {q_type}
Maximum marks: {marks}

Mark scheme — award 1 mark per bullet point if the student's answer includes that keyword/concept:
{scheme_lines}

Student's answer: {student_ans}

Marking rules:
- For MCQ: award {marks} mark if student chose the correct option, else 0.
- For short/calc: check EACH bullet independently. Award 1 mark per bullet if the student's
  answer contains the required keyword, value, equation or concept (accept correct equivalents,
  rearranged equations, alternative correct wording, and correct numerical answers with or
  without full working shown).
- Do NOT penalise spelling errors unless the word is unrecognisable.
- is_correct = true only if marks_awarded equals {marks}.

Return ONLY JSON (no markdown):
{{
  "is_correct": true/false,
  "marks_awarded": 0–{marks},
  "points": [
    {{"text": "exact bullet from mark scheme", "awarded": true/false}}
  ],
  "feedback": "one-sentence overall feedback mentioning the score",
  "explanation": "2–4 sentences explaining the full correct answer with any working",
  "tip": "one memorable mnemonic or memory tip"
}}"""

    raw    = ask_claude(prompt, max_tokens=700)
    result = parse_json(raw)

    # Ensure is_correct reflects full marks
    result["is_correct"] = result.get("marks_awarded", 0) >= marks

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


# ── Predicted Papers ──────────────────────────────────────────────────────────

@app.post("/predicted-papers/generate")
def generate_predicted_papers(body: dict):
    subject = body.get("subject", "chemistry")
    force   = body.get("force", False)

    con = db()
    # Return cached papers unless force-regenerate requested
    if not force:
        existing = con.execute(
            "SELECT paper_id, paper_number, title, questions_json, rationale, generated_at "
            "FROM predicted_papers WHERE subject=? ORDER BY paper_number",
            [subject]
        ).fetchall()
        if existing:
            con.close()
            return _format_predicted(subject, existing)

    # Delete stale papers for this subject
    con.execute("DELETE FROM predicted_papers WHERE subject=?", [subject])
    con.close()

    # Gather broad context: query several angles to get diverse chunks
    ctx_parts = []
    for q in [subject, "exam question calculation", "definition formula", "describe explain"]:
        chunk = search_context(subject, q, n=12)
        if chunk:
            ctx_parts.append(chunk)
    ctx_block = ("\n\n".join(ctx_parts[:3])[:6000]) if ctx_parts else \
                "(No indexed documents — generating from CCEA GCSE curriculum knowledge)"

    subj_label = subject.replace("_", " ").upper()

    prompt = f"""You are a senior CCEA GCSE {subj_label} examiner producing five predicted model papers.

You have studied the following content extracted from real past papers for {subj_label}:
---
{ctx_block}
---

Task:
Analyse the content above. Identify:
- Topics that recur frequently (mark as "HIGH" likelihood)
- Core curriculum topics tested almost every year ("HIGH")
- Topics seen once or twice ("MEDIUM")
- Topics that haven't appeared recently but are in syllabus ("WATCH")

Then generate EXACTLY 5 predicted papers. Each paper must have EXACTLY 10 questions
covering a balanced spread of the syllabus, mixing:
- 4 MCQ questions (type "mcq", 1 mark each, options A–D)
- 4 short-answer questions (type "short", 2–3 marks each)
- 2 calculation questions (type "calc", 3–5 marks each)

Each question MUST include:
- A realistic mark scheme (one bullet per mark, keyword/phrase the examiner accepts)
- The topic name it tests
- A likelihood rating: "HIGH", "MEDIUM", or "WATCH"

Vary the questions across the 5 papers so students see the full syllabus.

Return ONLY a valid JSON array of exactly 5 objects (no markdown, no explanation):
[
  {{
    "paper_number": 1,
    "title": "Predicted Paper 1 — {subj_label}",
    "rationale": "2-sentence explanation of the focus of this paper and why these topics are predicted",
    "questions": [
      {{
        "q": "Full exam question text",
        "type": "mcq",
        "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
        "answer": "correct option letter and text",
        "mark_scheme": ["Correct: A) ..."],
        "marks": 1,
        "topic": "Topic Name",
        "likelihood": "HIGH"
      }},
      {{
        "q": "Full exam question text",
        "type": "short",
        "answer": "full correct answer",
        "mark_scheme": ["keyword for mark 1", "keyword for mark 2"],
        "marks": 2,
        "topic": "Topic Name",
        "likelihood": "MEDIUM"
      }}
    ]
  }}
]
Rules: omit "options" for non-mcq. mark_scheme length MUST equal marks."""

    raw  = ask_claude(prompt, max_tokens=7000)
    papers = parse_json(raw)

    con = db()
    now = datetime.now()
    for p in papers:
        con.execute(
            "INSERT INTO predicted_papers (paper_id, subject, paper_number, title, questions_json, rationale, generated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [str(uuid.uuid4()), subject, p["paper_number"], p["title"],
             json.dumps(p["questions"]), p.get("rationale", ""), now]
        )
    con.close()
    return {"subject": subject, "papers": papers, "generated": True,
            "generated_at": str(now)[:16]}


def _format_predicted(subject: str, rows):
    papers = []
    for r in rows:
        qs = json.loads(r[3])
        papers.append({
            "paper_id":      r[0],
            "paper_number":  r[1],
            "title":         r[2],
            "questions":     qs,
            "rationale":     r[4],
            "generated_at":  str(r[5])[:16],
            "total_marks":   sum(q.get("marks", 1) for q in qs),
            "question_count": len(qs),
        })
    return {"subject": subject, "papers": papers, "generated": False,
            "generated_at": papers[0]["generated_at"] if papers else ""}


@app.get("/predicted-papers/{subject}")
def get_predicted_papers(subject: str):
    con = db()
    rows = con.execute(
        "SELECT paper_id, paper_number, title, questions_json, rationale, generated_at "
        "FROM predicted_papers WHERE subject=? ORDER BY paper_number",
        [subject]
    ).fetchall()
    con.close()
    if not rows:
        return {"subject": subject, "papers": [], "generated_at": ""}
    return _format_predicted(subject, rows)


@app.post("/quiz/from-paper")
def quiz_from_paper(body: dict):
    paper_id   = body.get("paper_id")
    student_id = body.get("student_id", "")

    con = db()
    row = con.execute(
        "SELECT subject, title, questions_json FROM predicted_papers WHERE paper_id=?",
        [paper_id]
    ).fetchone()
    con.close()
    if not row:
        return {"error": "Paper not found"}

    questions  = json.loads(row[2])
    session_id = str(uuid.uuid4())
    con = db()
    con.execute(
        "INSERT INTO quiz_sessions (session_id,subject,topic,question_count,questions_json,created_at,student_id) "
        "VALUES (?,?,?,?,?,?,?)",
        [session_id, row[0], row[1], len(questions), row[2], datetime.now(), student_id]
    )
    con.close()
    return {"session_id": session_id, "questions": questions,
            "subject": row[0], "topic": row[1]}


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
    identifier = body.get("student_id", "").strip()
    password   = body.get("password", "").strip()

    con = db()
    row = con.execute(
        "SELECT student_id, first_name, last_name, password_hash FROM students WHERE UPPER(student_id)=? AND is_active=TRUE",
        [identifier.upper()]
    ).fetchone()
    if not row:
        row = con.execute(
            "SELECT student_id, first_name, last_name, password_hash FROM students WHERE LOWER(email)=? AND is_active=TRUE",
            [identifier.lower()]
        ).fetchone()
    con.close()

    if row and verify_password(password, row[3]):
        return {"success": True, "student_id": row[0], "name": f"{row[1]} {row[2]}"}
    return {"success": False, "error": "Invalid Student ID/email or password"}


@app.post("/register")
def register_student(body: dict):
    first_name   = body.get("first_name",    "").strip()
    last_name    = body.get("last_name",     "").strip()
    email        = body.get("email",         "").strip().lower()
    dob_str      = body.get("date_of_birth", "").strip()
    school_year  = int(body.get("school_year", 10))
    password     = body.get("password",      "").strip()
    gdpr_consent = body.get("gdpr_consent",  False)

    parent_name    = body.get("parent_name",    "").strip()
    parent_email   = body.get("parent_email",   "").strip().lower()
    parent_phone   = body.get("parent_phone",   "").strip()
    parent_consent = body.get("parent_consent", False)

    if not all([first_name, last_name, email, dob_str, password]):
        return {"success": False, "error": "All required fields must be filled in."}
    if not gdpr_consent:
        return {"success": False, "error": "You must accept the GDPR privacy notice to register."}
    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters."}

    try:
        dob_date = date.fromisoformat(dob_str)
    except ValueError:
        return {"success": False, "error": "Invalid date of birth."}

    today = date.today()
    age = today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))

    if age < 13:
        return {"success": False, "error": "You must be at least 13 years old to register."}
    if age < 16 and not parent_consent:
        return {"success": False, "error": "Parental consent is required for students under 16."}
    if age < 16 and not all([parent_name, parent_email]):
        return {"success": False, "error": "Parent name and email are required for students under 16."}

    con = db()
    if con.execute("SELECT 1 FROM students WHERE LOWER(email)=?", [email]).fetchone():
        con.close()
        return {"success": False, "error": "This email address is already registered."}

    sid = generate_student_id(con)
    ph  = hash_password(password)
    now = datetime.now()
    con.execute("""
        INSERT INTO students (student_id, first_name, last_name, email, date_of_birth, school_year,
                              password_hash, is_active, gdpr_consent, consent_date, created_at)
        VALUES (?,?,?,?,?,?,?,TRUE,TRUE,?,?)
    """, [sid, first_name, last_name, email, dob_date, school_year, ph, now, now])

    if age < 16 and parent_consent:
        con.execute("""
            INSERT INTO parent_consent (consent_id, student_id, parent_name, parent_email, parent_phone, consent_given, consent_date)
            VALUES (?,?,?,?,?,TRUE,?)
        """, [str(uuid.uuid4()), sid, parent_name, parent_email, parent_phone, now])

    con.close()
    return {"success": True, "student_id": sid, "name": f"{first_name} {last_name}"}


@app.delete("/account/{student_id}")
def delete_account(student_id: str):
    con = db()
    con.execute("DELETE FROM parent_consent WHERE student_id=?", [student_id])
    con.execute("UPDATE quiz_sessions SET student_id='' WHERE student_id=?", [student_id])
    con.execute("DELETE FROM students WHERE student_id=?", [student_id])
    con.close()
    return {"success": True, "message": "Account deleted. Quiz history anonymised."}


@app.get("/performance/{student_id}")
def get_performance(student_id: str):
    con = db()

    rows = con.execute("""
        SELECT qs.created_at, qs.subject, qs.topic, qs.question_count,
               COUNT(qr.result_id)                                         AS answered,
               SUM(CASE WHEN qr.is_correct THEN 1 ELSE 0 END)             AS correct
        FROM   quiz_sessions qs
        LEFT JOIN quiz_results qr ON qs.session_id = qr.session_id
        WHERE  qs.student_id = ?
        GROUP  BY qs.session_id, qs.created_at, qs.subject, qs.topic, qs.question_count
        ORDER  BY qs.created_at DESC
    """, [student_id]).fetchall()

    daily_rows = con.execute("""
        SELECT CAST(qs.created_at AS DATE)                                 AS day,
               COUNT(DISTINCT qs.session_id)                               AS sessions,
               COUNT(qr.result_id)                                         AS answered,
               SUM(CASE WHEN qr.is_correct THEN 1 ELSE 0 END)             AS correct
        FROM   quiz_sessions qs
        LEFT JOIN quiz_results qr ON qs.session_id = qr.session_id
        WHERE  qs.student_id = ?
        GROUP  BY CAST(qs.created_at AS DATE)
        ORDER  BY day DESC
    """, [student_id]).fetchall()

    monthly_rows = con.execute("""
        SELECT substr(CAST(CAST(qs.created_at AS DATE) AS VARCHAR), 1, 7) AS month,
               COUNT(DISTINCT qs.session_id)                               AS sessions,
               COUNT(qr.result_id)                                         AS answered,
               SUM(CASE WHEN qr.is_correct THEN 1 ELSE 0 END)             AS correct
        FROM   quiz_sessions qs
        LEFT JOIN quiz_results qr ON qs.session_id = qr.session_id
        WHERE  qs.student_id = ?
        GROUP  BY substr(CAST(CAST(qs.created_at AS DATE) AS VARCHAR), 1, 7)
        ORDER  BY month DESC
    """, [student_id]).fetchall()

    con.close()

    results = []
    for r in rows:
        answered  = int(r[4] or 0)
        correct   = int(r[5] or 0)
        score_pct = round(correct / answered * 100) if answered > 0 else 0
        results.append({
            "date":      str(r[0])[:16].replace("T", " "),
            "subject":   r[1],
            "topic":     r[2] or "General Revision",
            "questions": r[3],
            "answered":  answered,
            "correct":   correct,
            "score_pct": score_pct,
        })

    def _agg(rows_in):
        out = []
        for r in rows_in:
            answered  = int(r[2] or 0)
            correct   = int(r[3] or 0)
            out.append({
                "label":    str(r[0]),
                "sessions": int(r[1]),
                "answered": answered,
                "correct":  correct,
                "score_pct": round(correct / answered * 100) if answered > 0 else 0,
            })
        return out

    subj_totals: dict = {}
    for r in results:
        s = r["subject"]
        if s not in subj_totals:
            subj_totals[s] = {"answered": 0, "correct": 0, "sessions": 0}
        subj_totals[s]["answered"] += r["answered"]
        subj_totals[s]["correct"]  += r["correct"]
        subj_totals[s]["sessions"] += 1

    subject_avg = {
        k: round(v["correct"] / v["answered"] * 100) if v["answered"] > 0 else 0
        for k, v in subj_totals.items()
    }
    overall = round(sum(r["score_pct"] for r in results) / len(results)) if results else 0

    return {
        "student_id":      student_id,
        "results":         results,
        "daily_results":   _agg(daily_rows),
        "monthly_results": _agg(monthly_rows),
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
.fb-partial{background:#fff8e1;border-left:4px solid #ffa726}
.fb-wrong{background:#fce4ec;border-left:4px solid #ef5350}
.ms-box{margin-top:10px;background:rgba(0,0,0,.04);border-radius:6px;padding:8px 10px}
.ms-list{list-style:none;margin:5px 0 0;padding:0}
.ms-pt{display:flex;align-items:flex-start;gap:6px;padding:3px 0;font-size:12px;border-bottom:1px solid rgba(0,0,0,.05)}
.ms-pt:last-child{border:none}
.ms-icon{font-weight:900;font-size:13px;flex-shrink:0;width:16px}
.ms-ok{color:#2e7d32}
.ms-ok .ms-icon{color:#2e7d32}
.ms-no{color:#c62828}
.ms-no .ms-icon{color:#c62828}
.ms-score{display:inline-block;background:#7986cb;color:white;border-radius:10px;
          font-size:11px;padding:1px 7px;margin:0 6px 0 0;font-weight:700;vertical-align:middle}
.ms-explain{margin-top:8px;font-size:12.5px;line-height:1.6;color:#333}
.ms-tip{margin-top:6px;font-size:12px;color:#555;font-style:italic}
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
.modal-tabs{display:flex;border-bottom:2px solid #eee;margin:-4px -4px 18px;gap:0}
.modal-tab{flex:1;padding:11px;text-align:center;cursor:pointer;font-weight:600;font-size:14px;
           color:#888;border-bottom:3px solid transparent;transition:.2s;margin-bottom:-2px}
.modal-tab:hover{color:#0288d1}
.modal-tab.active{color:#0288d1;border-bottom-color:#0288d1}
.modal-tab-pane{display:none}
.modal-tab-pane.active{display:block}
.gdpr-notice{background:#f0f8ff;border:1px solid #b3e5fc;border-radius:8px;padding:10px 12px;
             font-size:11px;color:#444;line-height:1.65;margin-bottom:10px;
             max-height:110px;overflow-y:auto}
.required-star{color:#ef5350}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
.parent-section{background:#fff3e0;border:1.5px solid #ffb74d;border-radius:8px;padding:12px;margin-top:8px}
.perf-sub-tabs{display:flex;gap:0;margin-bottom:14px;background:#f0f2f5;border-radius:8px;padding:3px}
.perf-sub-tab{flex:1;padding:7px;text-align:center;cursor:pointer;font-size:13px;font-weight:600;
              color:#888;border-radius:6px;transition:.2s}
.perf-sub-tab.active{background:white;color:#0288d1;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.pred-paper-card{background:white;border-radius:12px;margin-bottom:14px;
                 box-shadow:0 2px 8px rgba(0,0,0,.07);overflow:hidden}
.pred-paper-hdr{display:flex;align-items:center;gap:14px;padding:18px 20px;cursor:pointer;transition:.15s}
.pred-paper-hdr:hover{background:#f8f9ff}
.pred-paper-title{font-size:1rem;font-weight:700;color:#1a1a2e;margin-bottom:5px}
.pred-paper-meta{font-size:12px;color:#888;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.pred-paper-body{border-top:1px solid #eee;padding:18px 20px}
.pred-rationale{font-size:13px;color:#555;background:#f8f9ff;border-left:4px solid #7986cb;
                padding:10px 14px;border-radius:0 8px 8px 0;margin-bottom:16px;line-height:1.6}
.pred-q-row{border:1.5px solid #e8ecff;border-radius:8px;padding:14px;margin-bottom:10px;background:#fafbff}
.pred-q-meta{display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.pred-q-num{font-size:11px;font-weight:700;color:#7986cb;background:#e8ecff;
            padding:2px 7px;border-radius:4px}
.pred-q-text{font-size:13.5px;font-weight:600;line-height:1.5;color:#1a1a2e;margin-bottom:8px}
.pred-q-opts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.pred-opt{font-size:12px;padding:3px 10px;background:#f0f2f5;border-radius:6px;color:#555}
.pred-ms{font-size:12px;color:#555;background:#f0f8ff;border-radius:6px;padding:8px 10px;border-left:3px solid #b3e5fc}
.pred-ms-list{margin:4px 0 0 16px;padding:0}
.pred-ms-list li{margin:2px 0;color:#333}
.lh-HIGH{background:#ffcdd2;color:#b71c1c;border-radius:8px;padding:2px 7px;font-size:11px;font-weight:700}
.lh-MEDIUM{background:#fff9c4;color:#e65100;border-radius:8px;padding:2px 7px;font-size:11px;font-weight:700}
.lh-WATCH{background:#e3f2fd;color:#0d47a1;border-radius:8px;padding:2px 7px;font-size:11px;font-weight:700}
.pred-arrow{font-size:20px;color:#bbb;transition:transform .25s;display:inline-block}
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
  <div class="tab" onclick="showPage('predicted',this)">📋 Predicted Papers</div>
</div>

<!-- AUTH MODAL -->
<div id="login-modal" class="modal-overlay" style="display:none" onclick="if(event.target===this)hideLoginModal()">
  <div class="modal-box" style="width:500px;max-height:88vh;overflow-y:auto;padding:22px 24px">
    <div class="modal-tabs">
      <div class="modal-tab active" id="mtab-login" onclick="switchAuthTab('login')">👤 Login</div>
      <div class="modal-tab" id="mtab-register" onclick="switchAuthTab('register')">📝 Register</div>
    </div>

    <!-- LOGIN TAB -->
    <div class="modal-tab-pane active" id="mpane-login">
      <div class="modal-hint">
        <b>Demo accounts</b> — password: <b>Study123!</b><br>
        ST000001 — Alice Johnson &nbsp;|&nbsp; ST000002 — Ben Murphy<br>
        ST000003 — Chloe Davies &nbsp;|&nbsp; ST000004 — Daniel Smith
      </div>
      <input class="modal-input" id="login-id" type="text" placeholder="Student ID (e.g. ST000001) or email"
             onkeydown="if(event.key==='Enter')doLogin()">
      <input class="modal-input" id="login-pin" type="password" placeholder="Password"
             onkeydown="if(event.key==='Enter')doLogin()">
      <div class="modal-err" id="login-err"></div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-primary" style="flex:1" onclick="doLogin()">Login</button>
        <button class="btn" style="flex:1;background:#eee;color:#555" onclick="hideLoginModal()">Cancel</button>
      </div>
      <div style="text-align:center;margin-top:12px;font-size:13px;color:#888">
        New student? <a href="#" onclick="switchAuthTab('register');return false" style="color:#0288d1;font-weight:600">Register here</a>
      </div>
    </div>

    <!-- REGISTER TAB -->
    <div class="modal-tab-pane" id="mpane-register">
      <div class="form-row">
        <div>
          <label style="font-size:12px;font-weight:600;color:#555">First Name <span class="required-star">*</span></label>
          <input class="modal-input" id="reg-first" type="text" placeholder="First name" style="margin-top:4px">
        </div>
        <div>
          <label style="font-size:12px;font-weight:600;color:#555">Last Name <span class="required-star">*</span></label>
          <input class="modal-input" id="reg-last" type="text" placeholder="Last name" style="margin-top:4px">
        </div>
      </div>
      <label style="font-size:12px;font-weight:600;color:#555;display:block;margin-bottom:4px">Email <span class="required-star">*</span></label>
      <input class="modal-input" id="reg-email" type="email" placeholder="your@email.com">
      <div class="form-row" style="margin-top:8px">
        <div>
          <label style="font-size:12px;font-weight:600;color:#555">Date of Birth <span class="required-star">*</span></label>
          <input class="modal-input" id="reg-dob" type="date" style="margin-top:4px" onchange="checkAge()">
        </div>
        <div>
          <label style="font-size:12px;font-weight:600;color:#555">School Year <span class="required-star">*</span></label>
          <select class="modal-input" id="reg-year" style="margin-top:4px">
            <option value="10">Year 10</option>
            <option value="11">Year 11</option>
            <option value="12">Year 12 / AS</option>
          </select>
        </div>
      </div>
      <label style="font-size:12px;font-weight:600;color:#555;display:block;margin-top:8px;margin-bottom:4px">
        Password <span class="required-star">*</span> <small style="color:#aaa;font-weight:400">(min 8 characters)</small>
      </label>
      <input class="modal-input" id="reg-pw" type="password" placeholder="Create a password">
      <input class="modal-input" id="reg-pw2" type="password" placeholder="Confirm password" style="margin-top:8px">

      <div class="gdpr-notice" style="margin-top:12px">
        <b>📋 Privacy Notice (UK GDPR)</b><br>
        StudyBot UK collects your name, email and date of birth to manage your account and track revision progress.
        Your data is stored locally and is not shared with third parties. You have the right to access, rectify or
        erase your personal data at any time (contact your teacher or delete your account in settings).
        For students under 16, parental/guardian consent is required under UK GDPR Article 8.
        Data will be retained for the duration of your studies.
      </div>
      <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;cursor:pointer;margin-bottom:10px">
        <input type="checkbox" id="reg-gdpr" style="margin-top:2px;min-width:16px;height:16px">
        <span>I have read and agree to the <b>Privacy Notice</b> above <span class="required-star">*</span></span>
      </label>

      <!-- Parental consent (shown when age < 16) -->
      <div id="parent-section" class="parent-section" style="display:none">
        <div style="font-weight:700;font-size:13px;color:#e65100;margin-bottom:8px">
          👨‍👩‍👧 Parental Consent Required (under 16)
        </div>
        <p style="font-size:12px;color:#666;margin-bottom:10px;line-height:1.5">
          As you are under 16, a parent or guardian must give consent for you to use this service (UK GDPR Article 8).
        </p>
        <div class="form-row">
          <div>
            <label style="font-size:12px;font-weight:600;color:#555">Parent/Guardian Name <span class="required-star">*</span></label>
            <input class="modal-input" id="reg-parent-name" type="text" placeholder="Full name" style="margin-top:4px">
          </div>
          <div>
            <label style="font-size:12px;font-weight:600;color:#555">Parent Email <span class="required-star">*</span></label>
            <input class="modal-input" id="reg-parent-email" type="email" placeholder="parent@email.com" style="margin-top:4px">
          </div>
        </div>
        <label style="font-size:12px;font-weight:600;color:#555;display:block;margin-top:6px;margin-bottom:4px">Parent Phone (optional)</label>
        <input class="modal-input" id="reg-parent-phone" type="tel" placeholder="+44 7700 000000">
        <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;cursor:pointer;margin-top:10px">
          <input type="checkbox" id="reg-parent-consent" style="margin-top:2px;min-width:16px;height:16px">
          <span>I am the parent/guardian and I give consent for this student to use StudyBot UK <span class="required-star">*</span></span>
        </label>
      </div>

      <div class="modal-err" id="reg-err" style="margin-top:10px"></div>
      <div id="reg-success" style="display:none;background:#e8f5e9;border-radius:8px;padding:12px;margin-top:10px;font-size:13px;line-height:1.6">
        <b style="color:#2e7d32">✅ Registration successful!</b><br>
        Your Student ID: <b id="reg-student-id" style="font-size:1.15rem;color:#1565c0;letter-spacing:1px"></b><br>
        <small style="color:#666">Please save this ID — you need it to log in. You can now log in using the Login tab.</small>
      </div>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn btn-primary" style="flex:1" id="reg-btn" onclick="doRegister()">📝 Create Account</button>
        <button class="btn" style="flex:1;background:#eee;color:#555" onclick="hideLoginModal()">Cancel</button>
      </div>
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
      <div class="perf-sub-tabs">
        <div class="perf-sub-tab active" onclick="switchPerfTab('all',this)">All Sessions</div>
        <div class="perf-sub-tab" onclick="switchPerfTab('day',this)">By Day</div>
        <div class="perf-sub-tab" onclick="switchPerfTab('month',this)">By Month</div>
      </div>

      <!-- All sessions -->
      <div id="perf-view-all">
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

      <!-- By day -->
      <div id="perf-view-day" style="display:none">
        <div style="overflow-x:auto">
          <table class="perf-table">
            <thead><tr>
              <th>Date</th><th>Sessions</th><th>Correct</th><th>Score</th><th>Grade</th>
            </tr></thead>
            <tbody id="perf-day-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- By month -->
      <div id="perf-view-month" style="display:none">
        <div style="overflow-x:auto">
          <table class="perf-table">
            <thead><tr>
              <th>Month</th><th>Sessions</th><th>Correct</th><th>Score</th><th>Grade</th>
            </tr></thead>
            <tbody id="perf-month-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- PREDICTED PAPERS PAGE -->
<div class="page" id="page-predicted">
  <div class="card">
    <h2 style="margin-bottom:8px">📋 Predicted Papers</h2>
    <p style="font-size:13px;color:#666;margin-bottom:16px;line-height:1.6">
      AI-generated model papers built by analysing your indexed past papers.<br>
      Questions are selected based on topic frequency, exam importance and predicted likelihood of appearing this year.
    </p>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <button class="btn btn-primary" id="pred-gen-btn" onclick="generatePredicted(false)">
        🔮 Generate 5 Papers — <span id="pred-subj-label">Chemistry</span>
      </button>
      <button class="btn btn-warn" id="pred-regen-btn" style="display:none" onclick="generatePredicted(true)">
        🔄 Regenerate
      </button>
      <span id="pred-gen-date" style="font-size:12px;color:#aaa"></span>
    </div>
    <div style="margin-top:12px;font-size:12px;color:#aaa;display:flex;gap:16px;flex-wrap:wrap">
      <span><span class="lh-HIGH">HIGH</span> Appeared 3+ times / core topic</span>
      <span><span class="lh-MEDIUM">MEDIUM</span> Seen 1–2 times</span>
      <span><span class="lh-WATCH">WATCH</span> Due to appear — not seen recently</span>
    </div>
  </div>

  <div id="pred-loading" style="display:none;text-align:center;padding:50px 20px;color:#888">
    <div style="font-size:2.5rem;margin-bottom:14px">🔮</div>
    <div style="font-size:15px;font-weight:600;margin-bottom:8px">Analysing past papers…</div>
    <div style="font-size:13px">Identifying repeated topics, critical questions and exam patterns.<br>
    Generating 5 predicted papers — this takes 30–60 seconds.</div>
  </div>

  <div id="pred-empty" style="display:none;text-align:center;padding:40px;color:#aaa;font-size:14px">
    No papers generated yet. Select a subject above and click Generate.
  </div>

  <div id="pred-papers-area"></div>
</div>

<div id="toast"></div>

<script>
const state = { subject:'chemistry', count:15, sessionId:null, questions:[], student:null };
let ntCurriculum = [];

function selSubject(el, subject){
  document.querySelectorAll('#gs-group .gs-pill').forEach(p=>p.classList.remove('sel'));
  el.classList.add('sel');
  state.subject = subject;
  const lbl = document.getElementById('upload-subj-label');
  if(lbl) lbl.innerText = el.innerText.trim();
  const predLbl = document.getElementById('pred-subj-label');
  if(predLbl) predLbl.innerText = el.innerText.trim();
  if(document.getElementById('page-notes').classList.contains('active')) loadUnits();
  if(document.getElementById('page-predicted').classList.contains('active')) loadPredicted();
}

function showPage(name, tab){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  tab.classList.add('active');
  if(name==='notes')     loadUnits();
  if(name==='perf')      loadPerformance();
  if(name==='predicted') loadPredicted();
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
  let awarded=0, possible=0;

  for(let i=0;i<state.questions.length;i++){
    const q=state.questions[i];
    const qMarks=q.marks||1;
    possible+=qMarks;
    const ans=getStudentAnswer(i);
    const fb=document.getElementById('fb-'+i);
    fb.style.display='block';
    if(!ans){
      fb.className='feedback-box fb-wrong';
      fb.innerHTML='<b>No answer provided.</b>';
      continue;
    }
    try{
      const r=await fetch('/quiz/answer',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:state.sessionId,question_idx:i,answer:ans})
      });
      const d=await r.json();
      const got=d.marks_awarded||0;
      awarded+=got;
      const partial=got>0&&got<qMarks;
      fb.className='feedback-box '+(d.is_correct?'fb-correct':partial?'fb-partial':'fb-wrong');

      // Mark scheme points breakdown
      let schemeHtml='';
      if(d.points&&d.points.length){
        schemeHtml='<div class="ms-box"><b>Mark scheme:</b><ul class="ms-list">'+
          d.points.map(p=>`<li class="ms-pt ${p.awarded?'ms-ok':'ms-no'}">
            <span class="ms-icon">${p.awarded?'✓':'✗'}</span>${p.text}</li>`).join('')+
          '</ul></div>';
      }

      const scoreBadge=`<span class="ms-score">${got}/${qMarks}</span>`;
      const icon=d.is_correct?'✅':partial?'🟡':'❌';
      fb.innerHTML=`${icon} ${scoreBadge} <b>${d.feedback||''}</b>`+schemeHtml+
        (got<qMarks?`<div class="ms-explain"><b>Full answer:</b> ${d.explanation||''}</div>`+
         `<div class="ms-tip">💡 <b>Tip:</b> ${d.tip||''}</div>`:'');
    }catch(e){fb.className='feedback-box fb-wrong';fb.innerHTML='<b>Error checking answer.</b>';}
  }
  done(btn);
  showScore(awarded, possible);
}

function showScore(awarded,possible){
  const sc=document.getElementById('score-card');
  sc.style.display='block';
  const pct=possible>0?Math.round(awarded/possible*100):0;
  const grade=pct>=70?'🏆 Excellent!':pct>=55?'👍 Good effort':pct>=40?'📖 Keep revising':'💪 More practice needed';
  document.getElementById('score-summary').innerHTML=`
    <div style="font-size:2rem;font-weight:700;color:#1a1a2e">${awarded}/${possible}
      <span style="font-size:1rem;color:#666;font-weight:400"> marks (${pct}%)</span></div>
    <div style="font-size:1.1rem;margin:6px 0">${grade}</div>
    <div class="score-bar"><div class="score-fill" style="width:${pct}%"></div></div>
    <div style="font-size:13px;color:#666;margin-top:8px">
      Coloured mark scheme below each answer — ✓ marks awarded, ✗ marks missed.</div>`;
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
    fd.append('subject',state.subject);
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

// ── AUTH MODAL ─────────────────────────────────────────────────────────────────
function showLoginModal(){
  document.getElementById('login-modal').style.display='flex';
  switchAuthTab('login');
  setTimeout(()=>document.getElementById('login-id').focus(),50);
  document.getElementById('login-err').innerText='';
}
function hideLoginModal(){
  document.getElementById('login-modal').style.display='none';
}
function switchAuthTab(tab){
  document.querySelectorAll('.modal-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.modal-tab-pane').forEach(p=>p.classList.remove('active'));
  document.getElementById('mtab-'+tab).classList.add('active');
  document.getElementById('mpane-'+tab).classList.add('active');
}
function checkAge(){
  const dob = document.getElementById('reg-dob').value;
  if(!dob) return;
  const age = Math.floor((Date.now() - new Date(dob)) / (365.25*24*3600*1000));
  document.getElementById('parent-section').style.display = age < 16 ? 'block' : 'none';
}
async function doLogin(){
  const sid = document.getElementById('login-id').value.trim();
  const pw  = document.getElementById('login-pin').value.trim();
  if(!sid||!pw){ document.getElementById('login-err').innerText='Enter Student ID and password.'; return; }
  try{
    const r = await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},
                                    body:JSON.stringify({student_id:sid,password:pw})});
    const d = await r.json();
    if(d.success){
      state.student = {student_id:d.student_id, name:d.name};
      document.getElementById('login-widget').style.display='none';
      document.getElementById('student-badge').style.display='flex';
      document.getElementById('student-name-hdr').innerText=d.name;
      document.getElementById('login-pin').value='';
      hideLoginModal();
      toast('Welcome, '+d.name+'!');
      if(document.getElementById('page-perf').classList.contains('active')) loadPerformance();
    } else {
      document.getElementById('login-err').innerText = d.error || 'Login failed.';
    }
  }catch(e){ document.getElementById('login-err').innerText='Error: '+e.message; }
}
async function doRegister(){
  const btn = document.getElementById('reg-btn');
  loading(btn,'⏳ Creating account…');
  document.getElementById('reg-err').innerText='';
  document.getElementById('reg-success').style.display='none';

  const pw  = document.getElementById('reg-pw').value;
  const pw2 = document.getElementById('reg-pw2').value;
  if(pw !== pw2){
    document.getElementById('reg-err').innerText='Passwords do not match.';
    done(btn); return;
  }
  const body = {
    first_name:    document.getElementById('reg-first').value.trim(),
    last_name:     document.getElementById('reg-last').value.trim(),
    email:         document.getElementById('reg-email').value.trim(),
    date_of_birth: document.getElementById('reg-dob').value,
    school_year:   parseInt(document.getElementById('reg-year').value),
    password:      pw,
    gdpr_consent:  document.getElementById('reg-gdpr').checked,
  };
  const parentSec = document.getElementById('parent-section');
  if(parentSec.style.display !== 'none'){
    body.parent_name    = document.getElementById('reg-parent-name').value.trim();
    body.parent_email   = document.getElementById('reg-parent-email').value.trim();
    body.parent_phone   = document.getElementById('reg-parent-phone').value.trim();
    body.parent_consent = document.getElementById('reg-parent-consent').checked;
  }
  try{
    const r = await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},
                                        body:JSON.stringify(body)});
    const d = await r.json();
    if(d.success){
      document.getElementById('reg-student-id').innerText = d.student_id;
      document.getElementById('reg-success').style.display = 'block';
      btn.style.display = 'none';
      toast('Account created! Student ID: '+d.student_id);
    } else {
      document.getElementById('reg-err').innerText = d.error || 'Registration failed.';
    }
  }catch(e){ document.getElementById('reg-err').innerText='Error: '+e.message; }
  finally{ done(btn); }
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
function switchPerfTab(view, el){
  document.querySelectorAll('.perf-sub-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  ['all','day','month'].forEach(v=>{
    const el2=document.getElementById('perf-view-'+v);
    if(el2) el2.style.display = v===view?'block':'none';
  });
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

  // Trend sparkline
  drawSparkline(d.results.slice().reverse().map(r=>r.score_pct));

  // All sessions table
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

  // By-day table
  function renderAggTable(rows, bodyId){
    const tb = document.getElementById(bodyId);
    if(!tb) return;
    if(!rows.length){
      tb.innerHTML='<tr><td colspan="5" style="text-align:center;color:#bbb;padding:20px">No data yet</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(r=>{
      const g=gradeInfo(r.score_pct);
      return `<tr>
        <td style="color:#888;white-space:nowrap">${r.label}</td>
        <td style="font-weight:600">${r.sessions}</td>
        <td><b>${r.correct}/${r.answered}</b></td>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <div style="width:60px;height:8px;background:#eee;border-radius:4px;overflow:hidden">
              <div style="width:${r.score_pct}%;height:100%;background:#4fc3f7;border-radius:4px"></div>
            </div>
            <b>${r.score_pct}%</b>
          </div>
        </td>
        <td><span class="grade-badge ${g.cls}">${g.label}</span></td>
      </tr>`;
    }).join('');
  }
  renderAggTable(d.daily_results||[],   'perf-day-tbody');
  renderAggTable(d.monthly_results||[], 'perf-month-tbody');
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

// ── PREDICTED PAPERS ──────────────────────────────────────────────────────────
async function loadPredicted(){
  document.getElementById('pred-empty').style.display='none';
  document.getElementById('pred-papers-area').innerHTML='';
  document.getElementById('pred-regen-btn').style.display='none';
  document.getElementById('pred-gen-date').innerText='';
  try{
    const r=await fetch('/predicted-papers/'+state.subject);
    const d=await r.json();
    if(!d.papers||!d.papers.length){
      document.getElementById('pred-empty').style.display='block';
    } else {
      renderPredictedPapers(d.papers);
      document.getElementById('pred-regen-btn').style.display='inline-block';
      document.getElementById('pred-gen-date').innerText='Generated: '+d.generated_at;
    }
  }catch(e){}
}

async function generatePredicted(force){
  const btn=document.getElementById('pred-gen-btn');
  loading(btn,'⏳ Analysing…');
  document.getElementById('pred-loading').style.display='block';
  document.getElementById('pred-papers-area').innerHTML='';
  document.getElementById('pred-empty').style.display='none';
  document.getElementById('pred-regen-btn').style.display='none';
  document.getElementById('pred-gen-date').innerText='';
  try{
    const r=await fetch('/predicted-papers/generate',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({subject:state.subject,force:!!force})
    });
    const d=await r.json();
    if(d.papers&&d.papers.length){
      renderPredictedPapers(d.papers);
      document.getElementById('pred-regen-btn').style.display='inline-block';
      document.getElementById('pred-gen-date').innerText='Generated: '+(d.generated_at||'just now');
      toast('✅ 5 predicted papers ready!');
    } else {
      document.getElementById('pred-empty').style.display='block';
    }
  }catch(e){toast('❌ '+e.message);}
  finally{done(btn);document.getElementById('pred-loading').style.display='none';}
}

function renderPredictedPapers(papers){
  const area=document.getElementById('pred-papers-area');
  area.innerHTML=papers.map((p,idx)=>{
    const qs=p.questions||[];
    const total=p.total_marks||qs.reduce((s,q)=>s+(q.marks||1),0);
    const high=qs.filter(q=>q.likelihood==='HIGH').length;
    const med=qs.filter(q=>q.likelihood==='MEDIUM').length;
    const watch=qs.filter(q=>q.likelihood==='WATCH').length;
    const pid=p.paper_id||'';
    return `
<div class="pred-paper-card">
  <div class="pred-paper-hdr" onclick="togglePaper(${idx})">
    <div style="flex:1;min-width:0">
      <div class="pred-paper-title">${p.title||'Predicted Paper '+(idx+1)}</div>
      <div class="pred-paper-meta">
        ${qs.length} questions &nbsp;·&nbsp; ${total} marks
        &nbsp;&nbsp;
        <span class="lh-HIGH">${high} High</span>
        <span class="lh-MEDIUM">${med} Medium</span>
        <span class="lh-WATCH">${watch} Watch</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
      <button class="btn btn-primary" style="font-size:13px;padding:7px 16px"
              onclick="event.stopPropagation();takePaper('${pid}')">
        📝 Take Paper
      </button>
      <span class="pred-arrow" id="pred-arrow-${idx}">›</span>
    </div>
  </div>
  <div class="pred-paper-body" id="pred-body-${idx}" style="display:none">
    <div class="pred-rationale">💡 ${p.rationale||''}</div>
    <div>
      ${qs.map((q,qi)=>{
        const opts=q.type==='mcq'&&q.options?
          '<div class="pred-q-opts">'+q.options.map(o=>`<span class="pred-opt">${o}</span>`).join('')+'</div>':'';
        const ms='<div class="pred-ms"><b>Mark scheme:</b><ul class="pred-ms-list">'+
          (q.mark_scheme||[q.answer||'']).map(s=>`<li>${s}</li>`).join('')+'</ul></div>';
        return `<div class="pred-q-row">
          <div class="pred-q-meta">
            <span class="pred-q-num">Q${qi+1}</span>
            <span class="marks-badge">${q.marks||1}m</span>
            <span class="lh-${q.likelihood||'MEDIUM'}">${q.likelihood||'MEDIUM'}</span>
            <span style="font-size:11px;color:#999">${q.topic||''}</span>
          </div>
          <div class="pred-q-text">${q.q}</div>
          ${opts}${ms}
        </div>`;
      }).join('')}
    </div>
  </div>
</div>`;
  }).join('');
}

function togglePaper(idx){
  const body=document.getElementById('pred-body-'+idx);
  const arrow=document.getElementById('pred-arrow-'+idx);
  const open=body.style.display!=='none';
  body.style.display=open?'none':'block';
  arrow.style.transform=open?'':'rotate(90deg)';
}

async function takePaper(paperId){
  if(!paperId){toast('❌ Paper ID missing');return;}
  try{
    const r=await fetch('/quiz/from-paper',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({paper_id:paperId,student_id:state.student?state.student.student_id:''})
    });
    const d=await r.json();
    if(d.error){toast('❌ '+d.error);return;}
    state.sessionId=d.session_id;
    state.questions=d.questions;
    // Switch to Quiz tab
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.getElementById('page-quiz').classList.add('active');
    document.querySelector('.tabs .tab').classList.add('active');
    // Reset quiz area with paper questions
    document.getElementById('quiz-area').innerHTML='';
    document.getElementById('score-card').style.display='none';
    document.getElementById('submit-btn').style.display='inline-block';
    renderQuestions(d.questions);
    window.scrollTo({top:0,behavior:'smooth'});
    toast('📋 '+d.topic+' loaded — answer all questions then Submit!');
  }catch(e){toast('❌ '+e.message);}
}

</script>
</body>
</html>"""
