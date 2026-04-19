import os
import hashlib
import fitz  # pymupdf
import chromadb
import duckdb
from datetime import datetime

CHROMA_PATH = "./chroma_db"
DUCKDB_PATH  = "./studybot.duckdb"

BASE_FOLDER = "/Users/ramesh/Downloads/GCSE_SCIENCE_MATHS"

SUBJECT_FOLDERS = {
    "chemistry": os.path.join(BASE_FOLDER, "Chemistry"),
    "physics":   os.path.join(BASE_FOLDER, "Physics"),
    "maths_m4":  os.path.join(BASE_FOLDER, "Maths"),
    "maths_m8":  os.path.join(BASE_FOLDER, "Maths"),
}

# For maths sub-types: only index files whose name contains the code
MATHS_CODES = {
    "maths_m4": "m4",
    "maths_m8": "m8",
}

CHUNK_SIZE = 700
OVERLAP    = 120


def init_db(con: duckdb.DuckDBPyConnection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            doc_id       VARCHAR PRIMARY KEY,
            filename     VARCHAR,
            subject      VARCHAR,
            paper_code   VARCHAR,
            page_count   INTEGER,
            chunk_count  INTEGER,
            ingested_at  TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS quiz_sessions (
            session_id     VARCHAR PRIMARY KEY,
            subject        VARCHAR,
            topic          VARCHAR,
            question_count INTEGER,
            questions_json TEXT,
            created_at     TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS quiz_results (
            result_id      VARCHAR PRIMARY KEY,
            session_id     VARCHAR,
            question_idx   INTEGER,
            question       TEXT,
            student_answer TEXT,
            is_correct     BOOLEAN,
            feedback       TEXT,
            answered_at    TIMESTAMP
        )
    """)


def _chunks(text: str):
    parts = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if len(chunk) > 80:
            parts.append(chunk)
        start += CHUNK_SIZE - OVERLAP
    return parts


def extract_chunks(filepath: str):
    doc = fitz.open(filepath)
    result = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")
        for chunk in _chunks(text):
            result.append({"page": page_num, "text": chunk})
    doc.close()
    return result


def ingest_file(filepath: str, subject: str, collection, con: duckdb.DuckDBPyConnection):
    filename = os.path.basename(filepath)
    doc_id   = hashlib.md5(filepath.encode()).hexdigest()

    if con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone():
        print(f"  ⏩  Already indexed: {filename}")
        return 0

    print(f"  📄  Indexing: {filename} …", end="", flush=True)
    chunks = extract_chunks(filepath)
    if not chunks:
        print(" (no text found, skipped)")
        return 0

    # Detect paper code from filename
    paper_code = ""
    for code in ["m4", "m8", "t4", "t6"]:
        if code in filename.lower():
            paper_code = code
            break

    ids   = [f"{doc_id}_{i}" for i in range(len(chunks))]
    texts = [c["text"] for c in chunks]
    metas = [
        {"subject": subject, "filename": filename,
         "page": c["page"], "paper_code": paper_code}
        for c in chunks
    ]

    # ChromaDB add in batches of 500 to stay within limits
    batch = 500
    for i in range(0, len(ids), batch):
        collection.add(
            documents=texts[i:i+batch],
            metadatas=metas[i:i+batch],
            ids=ids[i:i+batch],
        )

    page_count = fitz.open(filepath).page_count
    con.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?)",
        [doc_id, filename, subject, paper_code, page_count, len(chunks), datetime.now()]
    )
    print(f" ✅ {len(chunks)} chunks")
    return len(chunks)


def build_index():
    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection("studybot_docs")
    con        = duckdb.connect(DUCKDB_PATH)
    init_db(con)

    total = 0
    for subject, folder in SUBJECT_FOLDERS.items():
        if not os.path.exists(folder):
            print(f"❌  Folder not found: {folder}")
            continue
        required_code = MATHS_CODES.get(subject)
        print(f"\n📚  Subject: {subject}  →  {folder}")
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith(".pdf"):
                continue
            if required_code and required_code not in filename.lower():
                continue
            filepath = os.path.join(folder, filename)
            size_mb  = os.path.getsize(filepath) / (1024 * 1024)
            if size_mb > 120:
                print(f"  ⚠️   Skipping {filename} — {size_mb:.1f} MB (too large)")
                continue
            total += ingest_file(filepath, subject, collection, con)

    print(f"\n✅  Done. Total chunks indexed: {total}")
    con.close()


def index_single_pdf(filepath: str, subject: str):
    client     = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection("studybot_docs")
    con        = duckdb.connect(DUCKDB_PATH)
    init_db(con)
    result = ingest_file(filepath, subject, collection, con)
    con.close()
    return result


if __name__ == "__main__":
    build_index()
