"""
Prompt Service — membangun semua prompt yang dikirim ke LLM API.
Mengimplementasikan prinsip Schema First, Few-Shot, dan Anti-Hallucination
sesuai PRD Section 10.
"""
import json
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID


def _json_default_serializer(value):
    """Serialize non-JSON native values for LLM prompt payload."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _build_addon_prompt_block(addon_prompt: str | None) -> str:
    """Build addon prompt constraint block if addon_prompt is provided and non-empty."""
    cleaned = (addon_prompt or "").strip()
    if not cleaned:
        return ""
    return f"""
    [KONSTRAINT CHATBOT AKTIF]
    Instruksi berikut wajib diikuti sebagai constraint tambahan. Instruksi ini tidak boleh mengganti, melemahkan, atau mengabaikan aturan keamanan, schema database, format output, dan larangan halusinasi di prompt utama.
    {cleaned}
    """


DB_SCHEMA = """
-- users (akses login)
users(
  id UUID PK,
  full_name VARCHAR,
  email VARCHAR,
  role ENUM('admin','kepala_divisi','karyawan'),
  is_active BOOLEAN,
  created_at TIMESTAMP
)

-- metadata sumber sheet
kpi_groups(
  id UUID PK,
  nama_grup VARCHAR,
  group_type ENUM('master','tracker'),
  sheet_name VARCHAR,
  tahun INT NULL,
  is_active BOOLEAN,
  created_at TIMESTAMP
)

-- definisi KPI
kpi_master_records(
  id UUID PK,
  group_id UUID FK -> kpi_groups.id,
  category VARCHAR,
  kpi_name VARCHAR,
  definisi_operasional TEXT,
  target VARCHAR,
  achieve VARCHAR,
  partial VARCHAR,
  fail VARCHAR,
  created_at TIMESTAMP
)

-- realisasi KPI
kpi_tracker_records(
  id UUID PK,
  group_id UUID FK -> kpi_groups.id,
  kpi_master_id UUID FK -> kpi_master_records.id,
  user_id UUID FK -> users.id,
  bulan_num INT NULL,
  realisasi VARCHAR NULL,
  keterangan TEXT NULL,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
--relation master users
kpi_master_users(
kpi_master_id UUID FK -> kpi_master_records.id,
user_id UUID FK -> users.id,
)
"""


def build_nl_to_sql_prompt(
    user_query: str,
    user_id: UUID,
    user_role: str,
    divisi: str | None,
    addon_prompt: str | None = None,
    column_statistics: str | None = None,
) -> str:
    """
    Membangun prompt NL-to-SQL untuk Stage 1.
    Menyertakan: pertanyaan asli, schema, statistik kolom, contoh data, few-shot, konteks user.
    """

    # Tentukan scope akses berdasarkan role
    if user_role == "Karyawan":
        data_access_scope = "Prioritaskan data milik user yang sedang login."
    elif user_role == "kepala_divisi":
        data_access_scope = "Semua karyawan (semua divisi)"
    elif user_role == "Owner":
        data_access_scope = "Semua karyawan dan semua divisi (akses penuh read-only)"
    else:  # Admin
        data_access_scope = "Semua data (akses penuh read-only)"

    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
    column_statistics_block = (column_statistics or "").strip() or "Statistik kolom belum tersedia. Jika statistik tidak tersedia, tetap gunakan schema database dan pertanyaan asli pengguna; jangan mengarang nilai unik, mean, min, max, non-zero, atau non-null."

    prompt = f"""[SYSTEM PROMPT]
    Kamu adalah asisten SQL expert yang mengkonversi pertanyaan bahasa Indonesia menjadi query SQL PostgreSQL.
    {addon_prompt_block}
    
    ATURAN WAJIB:
    1. Hanya generate query SELECT — DILARANG KERAS menggunakan INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC, atau perintah apapun selain SELECT.
    2. Selalu gunakan tiga input utama untuk inference S-RAG: Pertanyaan Asli Pengguna (q), Skema Database (S), dan Statistik Setiap Kolom.
    3. Selalu gunakan tabel, view, dan kolom yang ada di schema yang diberikan di bawah.
    4. Gunakan statistik kolom untuk memetakan maksud pengguna ke filter leksikal atau nilai penulisan yang persis sama dengan data database.
    5. Untuk atribut numerik, manfaatkan mean, maksimum, minimum, non-zero, dan non-null bila tersedia.
    6. Untuk atribut string dan boolean, manfaatkan nilai unik, non-zero, dan non-null bila tersedia.
    7. Tambahkan LIMIT 1000 jika tidak ada limit spesifik dalam pertanyaan.
    8. Gunakan alias yang deskriptif dan mudah dipahami pada kolom hasil.
    9. Utamakan JOIN antara kpi_tracker_records dan kpi_master_records melalui kpi_master_id.
    10. Format output: HANYA SQL mentah, tanpa penjelasan, tanpa markdown backtick, tanpa komentar.
    11. Jika pertanyaan tidak dapat dijawab dengan data yang tersedia, keluarkan: SELECT 'Data tidak tersedia untuk pertanyaan ini' AS pesan;
    12. Nama karyawan ada di users.full_name; join users u ON u.id = kt.user_id untuk filter atau menampilkan nama.
    13. Data di kpi_tracker_records bisa berupa lanjutan progress KPI tracker sebelumnya; gunakan DISTINCT atau GROUP BY jika menghitung jumlah orang atau pekerjaan.
    14. Gunakan UPPER(u.full_name) LIKE untuk pencarian nama orang agar fleksibel, karena user bisa menyebut nama sebagian.
    15. Selalu gunakan kolom bulan_num sebagai acuan utama untuk menentukan konteks periode data pada KPI Tracker. Nilai bulan_num harus diinterpretasikan sebagai nomor bulan (contoh: Januari = 1, Februari = 2, Maret = 3, dan seterusnya) agar analisis atau jawaban dapat mengidentifikasi data KPI berasal dari bulan yang tepat.
    
    [PERTANYAAN ASLI PENGGUNA (q)]
    {user_query}
    
    [SKEMA DATABASE (S)]
    {DB_SCHEMA}
    
    [STATISTIK SETIAP KOLOM]
    {column_statistics_block}
    
    [CONTEXT PENGGUNA]
    Role: {user_role}
    Karyawan ID: {user_id}
    Divisi: {divisi or 'N/A'}
    Akses data: {data_access_scope}
    
    SQL:"""

    return prompt


def build_analysis_prompt(
    user_query: str,
    executed_sql: str,
    query_result: list[dict],
    rows_count: int,
    addon_prompt: str | None = None,
) -> str:
    # No truncation
    compact_rows = query_result

    result_str = json.dumps(
        compact_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default_serializer,
    )

    truncation_note = f"Total: {rows_count} baris."

    # Build explicit column + row preview
    if compact_rows:
        columns = list(compact_rows[0].keys())
        col_preview = ", ".join(f'"{c}"' for c in columns)
        row_count_hint = f"{len(compact_rows)} baris dengan kolom: {col_preview}"
    else:
        col_preview = "-"
        row_count_hint = "0 baris (kosong)"
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)

    prompt = f"""[SYSTEM PROMPT]
Kamu adalah analis data KPI yang bertugas menyajikan dan menjelaskan data secara akurat dalam Bahasa Indonesia.
{addon_prompt_block}
Tugasmu HANYA: sajikan data → jelaskan apa yang terlihat. Kamu BUKAN pengambil keputusan.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ATURAN WAJIB — IKUTI PERSIS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LANGKAH 1 — TAMPILKAN TABEL DATA (WAJIB, LAKUKAN DULUAN)
Cetak SELURUH isi data hasil query ke dalam tabel Markdown.
Data memiliki {row_count_hint}.
- Gunakan nama kolom asli sebagai header tabel.
- Tampilkan SETIAP baris apa adanya, tanpa diringkas, tanpa dibuang.
- Format angka: titik (.) pemisah ribuan, koma (,) desimal.
- Tambahkan baris catatan di bawah tabel: "{truncation_note}"
- Jika data kosong: tulis "Tidak ada data." dan BERHENTI di sini.

LANGKAH 2 — JAWAB PERTANYAAN PENGGUNA
Jawab pertanyaan secara langsung dan ringkas (2–4 kalimat).
Gunakan HANYA angka/nama yang ada di tabel Langkah 1.

LANGKAH 3 — INSIGHT DARI DATA
Jelaskan temuan penting yang terlihat dari data. Contoh:
- Nilai tertinggi / terendah (sebutkan baris & nilainya).
- Perbandingan antar baris jika relevan.
- Anomali atau pola yang terlihat.
Setiap klaim HARUS menyebut nilai eksak dari tabel. Jangan generalisasi.

TIDAK ADA LANGKAH LAIN. Jangan tambahkan rekomendasi, saran tindakan, atau opini.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LARANGAN KERAS:
- JANGAN sebut angka/nama yang tidak ada di data.
- JANGAN karang, asumsikan, atau interpolasi data apapun.
- JANGAN tambahkan seksi "Rekomendasi", "Saran", atau sejenisnya.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[PERTANYAAN PENGGUNA]
{user_query}

[SQL YANG DIEKSEKUSI]
{executed_sql}

[DATA MENTAH — {row_count_hint} — {truncation_note}]
{result_str}

[MULAI RESPONS — LANGKAH 1: TABEL DATA]"""

    return prompt


# ================================================================ #
#  CLARIFICATION PROMPTS                                           #
# ================================================================ #


def build_ambiguity_assessment_prompt(
    user_query: str,
    user_role: str,
    kpi_context: str = "",
    addon_prompt: str | None = None,
) -> str:
    """
    Membangun prompt untuk LLM-based ambiguity detection dengan format AmbiSQL.
    Menggunakan question_set format dengan level-1 dan level-2 ambiguity taxonomy.
    Output JSON mengikuti spec ketat: has_ambiguity + question_set dengan structure yang tepat.
    """
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)

    prompt = f"""Given a user question, database schema, and optional evidence, identify ambiguities in the user question and generate clarification questions to resolve them.
Contents in the evidence are user provided clarifications to resolve previous detected ambiguities.
Note that the user question might use both data inside the database and external parametrized knowledge from the Large Language Model (LLM).
{addon_prompt_block}
════════════════════════════════════════════════════════════════
INPUT ELEMENTS:
════════════════════════════════════════════════════════════════

Question: "{user_query}"
Role: {user_role}
Schema: {DB_SCHEMA}
Evidence: {kpi_context}




## Ambiguity Definition & Taxonomy:
A user question is identifies as ambiguous when there is more than one reasonable interpretation due to unclear, incomplete, or conflicting information.
The ambiguity in a user question are defined as two different levels.
- level_1 ambiguity type are defined from two different dimensions, database and LLM repectively:
    - "Database-sourced ambiguity": Ambiguity that leads to incorrect or incomplete data retrieval directly from the database, due to unclear or underspecified aspects of the user query with respect to the database schema or content.
    - "LLM-sourced ambiguity": Ambiguity that results in the misuse of LLM external knowledge, causing difficulties in correctly retrieving or applying information beyond the database.
- level_2 ambiguity type are defined under each level_1 ambiguity type as follows:
    - Database-sourced ambiguity:
      - "AmbiSchema": The question lacks sufficient context to determine which table or specific column to use for operations(e.g., filtering, grouping, ranking, joining, aggregation, etc.), resulting in multiple plausible interpretations.
        - (e.g., "the oldest user" could refer to 'age' column or 'registration_date' column, representing different aspects of user's age or registration date).
      - "AmbiValue": The question refers to a value that does not correctly correspond to the actual values stored in the database, making it unclear how to formulate the WHERE clause condition and potentially causing relevant results to be omitted or producing inaccurate results.
        - (e.g., querying posts mentioning the "R programming language", the WHERE clause might be "posts.Body LIKE '%R%'", or "posts.Body = 'programming language'", etc)
        - (e.g., querying for users living in "New York City", the WHERE clause might be "users.City = 'New York City'", or "users.City = 'NYC'", etc)
        - (e.g., querying for posts about coronavirus, the WHERE clause might be "posts.Body LIKE '%COVID-19%'", or "posts.Body = 'coronavirus'", etc)
      - "AmbiView": Key terms clarifying the intended operation are absent, leading to ambiguity about the desired SQL operation 
        - (e.g., query as 'Top 5 popular tags's star', which can list each tag's star or the amount of stars).
    - LLM-sourced ambiguity:
      - "AmbiContext": The question lacks adequate information to guide LLM reasoning effectively.
        - (e.g., requesting dynamic or time-sensitive external information like "current exchange rate" without specifying the target currencies or date).
      - "AmbiFallacy": Knowledge assumptions embedded within the question contradicts real-world facts or database contents 
        - (e.g., querying entities or participants in events that never occurred, like 2001 Olympic Games).
      - "AmbiRef": Spatial or temporal constraints are underspecified, resulting in multiple possible interpretations at different granularities 
        - (e.g., querying for records "after the 2018 World Cup" could mean immediately after the final match or after the entire tournament year).
        - (e.g., querying for records in the 'Middle East Region' might cause missing countries in the list for "Middle East" due to vague or imprecise geographic constraints from different sources).
      
## Instructions
1. Analyze user question, database schema and evidence(if provided) to identify all possible ambiguous phrases in the user question.
2. For each unresolved ambiguity: **(1)** Assign exactly one level-1 and one level-2 label. **(2)** Write a multi-choice question for user to further clarify their intent.
3. For each multi-choice question: provide several possible options for users to choose from, add a description for each option, and add an explanation for the whole question through thinking. Formulate options and corresponding description based on the ambiguity type detected as follows:
  i. For "AmbiSchema", list all plausible columns with the format of 'table_name::column_name', with relevant descriptive schema info retrieved from the input database schema.
  ii. For "AmbiValue", list most likely 2-3 possible interpretations of WHERE clause, with concise explanation for each interpretation.
  iii. For "AmbiView", list most likely 2-3 possible interpretations of SQL operations, with concise explanation for each interpretation.
  v. For "AmbiContext", list most likely 2-3 possible values, ranges or constraints with concise explanation for each interpretation.
  vi. For "AmbiFallacy", list most likely 2-3 best-guessing interpretations of the 'fallacy' info considering it as a typo.
  vii. For "AmbiRef", list most likey 2-3 interpretations according to the reference part in the original user query.
**Important Note**: 
- All possible options should be in complete with concise description for user to select(Do not use such as or etc to omit some necessary options).
- Not each input question is ambiguous. If all ambiguities are resolved or the original user input is unambiguous, return an empty question_set. (e.g., If only one column in the database is plausible, it should not be an unclear schema reference)
- If the user's response in evidence to a specific ambiguity is 'Abstain', it means the identified ambiguity is not an actual ambiguity, and you can skip this ambiguity and not identify it again.

════════════════════════════════════════════════════════════════
OUTPUT FORMAT (Strict JSON — FOLLOW EXACTLY):
════════════════════════════════════════════════════════════════

{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Progress KPI Akmal ingin dilihat dari sisi apa?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiIntent",
      "description": {{
        "options": [
          "Realisasi KPI terbaru",
          "Persentase pencapaian terhadap target",
          "Tren progress dari waktu ke waktu"
        ]
      }}
    }},
    {{
      "question": "Akmal merujuk ke karyawan atau KPI yang mana?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiValue",
      "description": {{
        "options": [
          "Karyawan bernama Akmal",
          "KPI yang mengandung kata Akmal"
        ]
      }}
    }}
  ]
}}

CONTOH OUTPUT TIDAK AMBIGUOUS:
{{
  "has_ambiguity": false,
  "question_set": []
}}

CRITICAL JSON STRUCTURE RULES:
- NO per-item "metadata" field
- "description" MUST be an object with ONLY "options" key containing array of strings
- "options" array contains ONLY the clarifying options (2-5 items)
- question_set is array of objects, each with exactly: question, level_1_label, level_2_label, description

════════════════════════════════════════════════════════════════
REMEMBER:
════════════════════════════════════════════════════════════════
- Data source ALWAYS database. DO NOT create source-selection ambiguity category.
- "Abstain" means: skip that ambiguity type and do not identify it again in future queries
- Return ONLY valid JSON. NO markdown, NO explanation, NO comments.
- Respect the strict JSON shape above. Do not add extra fields."""

    return prompt

def build_query_disambiguation_prompt(
    original_query: str,
    clarification_answers: list,
    additional_constraints: str | None = None,
    additional_information: str | None = None,
) -> str:
    if additional_information is None:
        answer_lines = []
        for answer in clarification_answers:
            selected = getattr(answer, "selected_option", None) or answer.get("selected_option")
            free_text = getattr(answer, "free_text", None) if not isinstance(answer, dict) else answer.get("free_text")
            question_id = getattr(answer, "question_id", None) or answer.get("question_id")
            effective_answer = free_text if selected == "Lainnya" and free_text else selected
            if effective_answer == "Lewati":
                continue
            answer_lines.append(f"- {question_id}: {effective_answer}")
        if additional_constraints:
            answer_lines.append(f"- Constraint tambahan: {additional_constraints}")
        additional_information = "\n".join(answer_lines) if answer_lines else "Tidak ada informasi tambahan."

    return f'''## Task
To combine an `original_question` with `additional_information` into a single, coherent, and complete new question that is logically sound and easy to understand.

## Core Principles
1.  **Absolute Preservation**: You MUST preserve ALL constraints, details, and intents from the `original_question`. Nothing from the original should be omitted or altered unless it is directly and explicitly contradicted by the `additional_information`.
2.  **Full Integration**: You MUST seamlessly integrate ALL new requirements and constraints from the `additional_information` into the new question.
3.  **Conflict Resolution**: If a piece of `additional_information` directly conflicts with a part of the `original_question`, the `additional_information` takes precedence and should be used to update or replace the conflicting part. This is the **only** scenario where original information may be modified.
4.  **Natural Language**: The final output must be a single, natural-sounding question, not a list of criteria.

## Examples
Original question: List all novels published after 2000 that won a Booker Prize.
Additional information: Only include novels published after 2010 that were also adapted into movies and written by female authors.
Rewritten question: List all novels published after 2010 that won a Booker Prize, were adapted into movies, and were written by female authors.

Original question: Which Asian countries have a GDP per capita above $30,000 and a population under 10 million?
Additional information: Exclude countries that are island nations and with a population more than 10 million.
Rewritten question: Which Asian countries that are not island nations have a GDP per capita above $30,000 and a population more than 10 million?

Original question: Provide the list of Olympic gold medalists in swimming events for the last three Summer Olympics, including their ages at the time of winning.
Additional information: I am only interested in male athletes from North America, and only in individual events.
Rewritten question: Provide the list of male North American Olympic gold medalists in individual swimming events for the last three Summer Olympics, including their ages at the time of winning.

## Response Format
- Return **only** the text of the rewritten question.
- Do not include any preamble, labels (like "Rewritten question:"), or explanations.

---
**Input:**
Original question: {original_query}
Additional information: {additional_information}

The rewritten question is:
'''


def build_node_merge_prompt(old_list: list[dict], new_pair: dict) -> str:
    import json

    return f'''## Task
Merge a new question-answer pair into an existing list of question-answer pairs.

## Input
- old_list: existing list of objects, each with a `question` and `answer` field.
- new_pair: object with a `question` and `answer` field.

old_list:
{json.dumps(old_list, ensure_ascii=False)}

new_pair:
{json.dumps(new_pair, ensure_ascii=False)}

## Merge Instructions
1. Compare the `question` field of `new_pair` with each item in `old_list`. If any question in `old_list` has the same or highly similar meaning as `new_pair` (same intent, possibly different wording), treat it as a conflict.
2. If there is a conflict, remove the conflicting item and replace it with `new_pair`.
3. If there is no conflict, append `new_pair` at the end.
4. Ensure the output list contains no duplicate questions by meaning.
5. Return ONLY the merged list as a valid JSON array: [{{"question": "...", "answer": "..."}}, ...]
6. Do NOT return any explanation or text outside the JSON array.
'''


def build_graphic_generation_prompt(
    user_query: str,
) -> str:
    """
    Membangun prompt untuk LLM-based graphic generation.
    Menilai jenis grafik terbaik untuk data dan menghasilkan instruksi pembuatan grafik.
    """
    prompt = f"""[SYSTEM PROMPT]
Kamu adalah intent-classifier untuk chatbot KPI.
Tentukan apakah pertanyaan user meminta hasil dalam bentuk grafik.

ATURAN:
1. Jika user meminta grafik/diagram/chart/visualisasi, set is_visualize=true.
2. Chart type wajib salah satu: "bar", "pie", "donut".
3. Jika user tidak meminta visualisasi, set is_visualize=false dan chart_type=null.
4. Jika user meminta visualisasi tapi tipe tidak spesifik, default chart_type="bar".
5. DILARANG output selain JSON.

Pertanyaan user:
{user_query}

Output JSON wajib:
{{"is_visualize": true|false, "chart_type": "bar"|"pie"|"donut"|null}}"""

    return prompt


def build_context() -> str:
    """
    Membangun KPI domain context string untuk digunakan oleh LLM ambiguity detection.
    """
    return """
        Domain KPI chatbot:
        - KPI Master: definisi KPI, aktivitas, kategori, target, satuan, dan operational definition.
        - KPI Tracker: realisasi KPI per bulan/tahun, status pencapaian, nilai aktual, dan persentase achievement.
        - Dimensi organisasi: karyawan, kepala divisi, divisi/departemen, dan cakupan seluruh organisasi.
        - Dimensi waktu: bulan, tahun, kuartal, tahun berjalan, tahun lalu, bulan ini, dan bulan terakhir data.
        - Metrik umum: target, realisasi, achievement percentage, performance score, jumlah KPI, total, rata-rata.
        - Status umum: achieved, partial, failed, tercapai, belum tercapai.
        AmbiSchema candidates: kata seperti terbaik/performa/nilai dapat merujuk ke achievement percentage, realisasi, target, atau score.
        AmbiValue candidates: nama divisi, nama KPI, kategori KPI, nama karyawan, periode, dan status harus cocok dengan nilai data aktual bila tersedia.
        AmbiIntent candidates: tampilkan dapat berarti list, ranking, filter, grouping, comparison, atau aggregation.
        """.strip()