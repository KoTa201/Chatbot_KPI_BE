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
    addon_prompt: str | None = None,
    column_statistics: str | None = None,
) -> str:
    """
    Membangun prompt NL-to-SQL untuk Stage 1.
    Menyertakan: pertanyaan asli, schema, statistik kolom, contoh data, few-shot, konteks user.
    """

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
    16. Kolom km.target, km.achieve, km.partial, dan km.fail adalah definisi threshold KPI, bukan nilai realisasi. DILARANG membandingkan kt.realisasi langsung dengan km.achieve, km.partial, atau km.fail menggunakan =, IN, atau perbandingan string lain.
    17. Untuk pertanyaan tentang mencapai target, mendekati target, achieve, partial, fail, progress, atau kinerja, ambil data mentah untuk dianalisis: kt.user_id, kt.bulan_num, km.kpi_name, kt.realisasi, km.target, km.achieve, km.partial, km.fail, kt.keterangan.
    18. Untuk konteks "sampai bulan terakhir", "terbaru", atau "latest", ambil realisasi terbaru berdasarkan bulan_num untuk KPI/karyawan yang relevan, biasanya dengan MAX(bulan_num); jangan menyaring hasil dengan kt.realisasi = km.achieve atau kt.realisasi = km.partial.

    [PERTANYAAN ASLI PENGGUNA (q)]
    {user_query}
    
    [SKEMA DATABASE (S)]
    {DB_SCHEMA}
    
    [STATISTIK SETIAP KOLOM]
    {column_statistics_block}
    
    [CONTEXT PENGGUNA]
    Role: {user_role}
    
    [TAHUN SEKARANG]
    {datetime.now().year}
    
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
    Kamu adalah analis data KPI yang menyajikan jawaban akurat, langsung, dan ringkas dalam Bahasa Indonesia.
    {addon_prompt_block}
    Tugasmu HANYA menjawab pertanyaan pengguna berdasarkan data mentah hasil SQL.
    
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ATURAN WAJIB — IKUTI PERSIS:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    
    1. Jawab pertanyaan pengguna secara langsung terlebih dahulu.
    2. Gunakan hanya data dalam [DATA MENTAH]. Jangan menambah nama, angka, status, atau periode yang tidak ada di data.
    3. Jangan tampilkan tabel lengkap kecuali pengguna memintanya secara eksplisit.
    4. Jika perlu daftar, gunakan maksimal 3–6 bullet dan sertakan nilai relevan seperti nama KPI, realisasi/progress, target, dan keterangan.
    5. Jika data kosong: tulis "Tidak ada data." dan berhenti.
    6. Jangan tambahkan seksi rekomendasi, saran tindakan, atau opini.
    7. Jangan tambahkan seksi insight umum kecuali pengguna memintanya.
    
    ATURAN KHUSUS KPI TARGET / PROGRESS:
    - Jika pertanyaan menanyakan pencapaian target, mendekati target, achieve, partial, fail, progress, atau kinerja, bandingkan kolom realisasi dengan target jika keduanya tersedia dan bisa dibandingkan.
    - Untuk nilai numerik, realisasi == target atau realisasi > target berarti target tercapai.
    - Untuk format TRL N, bandingkan angka N; TRL yang sama atau lebih tinggi dari target berarti target tercapai.
    - Kolom achieve, partial, dan fail adalah deskripsi threshold. Gunakan sebagai konteks penjelasan, bukan sebagai label wajib yang harus muncul di keterangan.
    - Jangan menyatakan status tidak diketahui hanya karena keterangan tidak memuat kata ACHIEVE jika realisasi dan target membuktikan target tercapai.
    - Jika realisasi dan target tidak bisa dibandingkan secara pasti, sebutkan keterbatasan singkat dan tampilkan data mentah yang relevan.
    - PENTING: Sistem sudah otomatis membuatkan dan menampilkan grafik ke layar pengguna. Tugasmu HANYA menganalisis data dalam bentuk teks. DILARANG KERAS menuliskan kalimat apa pun yang menyinggung soal grafik (misalnya: "Ini grafiknya", "Saya tidak bisa membuat grafik", dll). Cukup langsung berikan analisis angkanya.

    [PERTANYAAN PENGGUNA]
    {user_query}
    
    [SQL YANG DIEKSEKUSI]
    {executed_sql}
    
    [DATA MENTAH — {row_count_hint} — {truncation_note}]
    {result_str}
    

    
    [MULAI RESPONS]"""

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

    Fixes applied:
    - Scope check hanya gagal jika topik tidak relevan, bukan jika nilai spesifik tidak dikenal
    - LLM dilarang self-resolve ambiguity (nama tidak unik → AmbiValue, metric ambigu → AmbiView)
    - Few-shot examples konkret untuk kasus seperti "bagaimana perkembangan andi"
    - Instruksi analisis diperkuat agar tidak bias ke false negative
    """
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)

    prompt = f"""You are a strict question classifier and ambiguity detector for a data analytics system.
{addon_prompt_block}

════════════════════════════════════════════════════════════════
INPUT ELEMENTS:
════════════════════════════════════════════════════════════════

Question : "{user_query}"
Role     : {user_role}
Schema   : {DB_SCHEMA}
Evidence : {kpi_context}

════════════════════════════════════════════════════════════════
STEP 1 — SCOPE CHECK (EXECUTE THIS FIRST, NO EXCEPTIONS):
════════════════════════════════════════════════════════════════

Evaluate whether the DOMAIN/TOPIC of the question is answerable
using the schema, evidence, or KPI definitions.

CRITICAL DISTINCTION — these are NOT the same:
  ┌─────────────────────────────────────────────────────────────┐
  │ Unknown/unclear specific values (names, dates, terms)       │
  │ → NOT a scope failure → they are AMBIGUITIES → go to STEP 2│
  │                                                             │
  │ Topic entirely unrelated to any table/column/KPI            │
  │ → IS a scope failure → return out-of-scope string           │
  └─────────────────────────────────────────────────────────────┘

A question is IN SCOPE if:
  ✓ The topic could plausibly map to at least one table, column, or KPI
  ✓ Even if specific values (names, dates, entities) are unrecognized or ambiguous

A question is OUT OF SCOPE only if:
  ✗ The topic is completely unrelated to the database domain
  ✗ No table, column, KPI, or evidence could even partially answer it

Scope check examples:
  ✓ IN SCOPE  → "bagaimana perkembangan andi"
                Topic = employee progress → matches schema domain
                "andi" being unrecognized = AmbiValue, NOT a scope failure

  ✓ IN SCOPE  → "siapa karyawan terbaik bulan ini"
                Topic = employee performance → matches schema

  ✓ IN SCOPE  → "tunjukkan data divisi X"
                Topic matches schema even if "divisi X" is unclear

  ✗ OUT OF SCOPE → "apa resep nasi goreng yang enak"
                   Topic = cooking → zero relation to schema

  ✗ OUT OF SCOPE → "berapa harga saham Apple hari ini"
                   Topic = stock market → no table/KPI covers this

If OUT OF SCOPE:
  ✗ Do NOT analyze ambiguity
  ✗ Do NOT generate clarifying questions
  ✗ Do NOT output JSON
  ✓ Output EXACTLY this string and nothing else:
    The question is out of my scope

If IN SCOPE → proceed to STEP 2.

════════════════════════════════════════════════════════════════
STEP 2 — AMBIGUITY ANALYSIS (only if in scope):
════════════════════════════════════════════════════════════════

## Ambiguity Taxonomy:

level_1 types:
  - "Database-sourced ambiguity": Causes incorrect/incomplete DB retrieval
  - "LLM-sourced ambiguity": Causes misuse of LLM external knowledge

level_2 types under Database-sourced:
  - "AmbiSchema": Unclear which table or column to use for the operation
    (e.g., "oldest user" → 'users::age' column vs 'users::registration_date' column)
  - "AmbiValue": A name, term, or value in the question cannot be uniquely matched
    to a specific record or value stored in the database
    (e.g., "andi" → multiple employees named Andi exist, unclear which one)
    (e.g., "New York City" → stored as 'NYC', 'New York', or 'New York City'?)
    (e.g., "coronavirus" → stored as 'COVID-19', 'coronavirus', 'SARS-CoV-2'?)
  - "AmbiView": The intended SQL operation, metric, or aggregation is unclear
    (e.g., "perkembangan" → KPI achievement? trend over time? comparison vs target?)
    (e.g., "terbaik" → highest total? highest average? most consistent?)

level_2 types under LLM-sourced:
  - "AmbiContext": Insufficient context for LLM reasoning
    (e.g., "nilai tukar saat ini" without specifying currencies or reference date)
  - "AmbiFallacy": Question references something that contradicts real-world facts
    (e.g., "Olimpiade 2001" — no such event exists)
  - "AmbiRef": Spatial or temporal reference is underspecified
    (e.g., "setelah Piala Dunia 2018" → after the final match vs after the whole year)
    (e.g., "wilayah Asia Tenggara" → exact country list varies by source)

## Analysis Instructions:

1. Carefully read the question and identify every phrase that could be interpreted
   in more than one way relative to the schema, evidence, and KPI definitions.

2. CRITICAL — Do NOT self-resolve ambiguities. Apply these rules strictly:
   ┌──────────────────────────────────────────────────────────────────────┐
   │ RULE A: If a person/entity name appears but cannot be matched to     │
   │ exactly ONE record in the DB → it is ALWAYS AmbiValue. Ask the user. │
   │                                                                      │
   │ RULE B: If an action/metric word ("perkembangan", "progress",        │
   │ "performa", "terbaik", "terbanyak") can map to more than one SQL     │
   │ operation or KPI → it is ALWAYS AmbiView. Ask the user.             │
   │                                                                      │
   │ RULE C: Never assume the most likely interpretation and skip asking. │
   │ Never use general knowledge to resolve what should be asked.         │
   └──────────────────────────────────────────────────────────────────────┘

3. For each unresolved ambiguity:
   - Assign exactly one level_1 and one level_2 label
   - Write a concise clarification question in Bahasa Indonesia
   - Put 2–5 complete, mutually exclusive candidate option contexts/evidence in description.options
   - These description.options are NOT final user-facing choices; a separate clarification-choice generator will rewrite them

4. Option format per ambiguity type:
   - AmbiSchema  → list all plausible columns as 'table_name::column_name'
                   with relevant descriptive info from the schema
   - AmbiValue   → 2–3 possible WHERE clause interpretations with explanation
   - AmbiView    → 2–3 possible SQL operations or KPI metrics with explanation
   - AmbiContext → 2–3 possible values, ranges, or constraints with explanation
   - AmbiFallacy → 2–3 best-guess corrections treating the reference as a typo
   - AmbiRef     → 2–3 interpretations of the temporal/spatial reference

5. Completeness rules:
   - List ALL plausible options — never use "dll." or "etc." to omit options
   - If only one column is plausible for a term → NOT an AmbiSchema
   - Evidence marked "Abstain" → skip that specific ambiguity permanently
   - If genuinely zero ambiguities remain → return empty question_set

════════════════════════════════════════════════════════════════
FEW-SHOT EXAMPLES:
════════════════════════════════════════════════════════════════

--- EXAMPLE 1: Multiple ambiguities (typical case) ---

Question : "bagaimana perkembangan andi"
Analysis :
  - "andi" → cannot be matched to a single unique employee → AmbiValue
  - "perkembangan" → unclear metric/operation → AmbiView

Expected output:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Andi yang dimaksud merujuk ke karyawan yang mana?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiValue",
      "description": {{
        "options": [
              "Berdasarkan nama lengkap — nama karyawan yang mengandung kata Andi,
              "Berdasarkan nama kpi - nama kpi mengandung kata Andi",
        ]
      }}
    }},
    {{
      "question": "Perkembangan Andi ingin dilihat dari aspek apa?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiView",
      "description": {{
        "options": [
          "Pencapaian KPI per periode — membandingkan target vs nilai aktual setiap periode",
          "Tren performa dari waktu ke waktu — melihat naik/turunnya nilai KPI antar periode",
          "Perbandingan performa terhadap rata-rata tim — posisi Andi relatif terhadap rekan satu divisi"
        ]
      }}
    }}
  ]
}}

--- EXAMPLE 2: Unambiguous question ---

Question : "tampilkan total penjualan bulan Januari 2024"
Analysis :
  - "total penjualan" → maps clearly to one aggregation
  - "Januari 2024" → specific and unambiguous time range

Expected output:
{{
  "has_ambiguity": false,
  "question_set": []
}}

--- EXAMPLE 3: Out of scope ---

Question : "apa rekomendasi saham yang bagus minggu ini"
Analysis :
  - Topic = stock investment recommendation → no table/column/KPI covers this

Expected output:
  The question is out of my scope

════════════════════════════════════════════════════════════════
OUTPUT FORMAT — THREE POSSIBLE OUTPUTS ONLY:
════════════════════════════════════════════════════════════════

OUT OF SCOPE → plain string, no JSON:
  The question is out of my scope

IN SCOPE + AMBIGUOUS → strict JSON:
  {{
    "has_ambiguity": true,
    "question_set": [
      {{
        "question": "<pertanyaan klarifikasi dalam Bahasa Indonesia>",
        "level_1_label": "<Database-sourced ambiguity | LLM-sourced ambiguity>",
        "level_2_label": "<AmbiSchema | AmbiValue | AmbiView | AmbiContext | AmbiFallacy | AmbiRef>",
        "description": {{
          "options": [
            "<opsi 1 dengan deskripsi singkat>",
            "<opsi 2 dengan deskripsi singkat>",
            "<opsi 3 dengan deskripsi singkat>"
          ]
        }}
      }}
    ]
  }}

IN SCOPE + UNAMBIGUOUS → strict JSON:
  {{
    "has_ambiguity": false,
    "question_set": []
  }}

════════════════════════════════════════════════════════════════
CRITICAL RULES (must be followed in every response):
════════════════════════════════════════════════════════════════
  - STEP 1 always runs first — unknown specific values → AmbiValue, NOT out of scope
  - NEVER self-resolve ambiguities; always ask the user (see RULE A, B, C above)
  - "description" must be an object with ONLY an "options" key (array of candidate context/evidence strings)
  - description.options are raw candidate context/evidence, not final user-facing choices
  - NO "metadata" field, NO extra fields anywhere in the JSON
  - question_set items must have exactly: question, level_1_label, level_2_label, description
  - Return ONLY valid JSON for in-scope questions
  - Return ONLY the plain scope string for out-of-scope questions
  - NO markdown formatting, NO code fences, NO explanation text, NO comments
  - Data source is ALWAYS the database — never create source-selection ambiguity
  - "Abstain" in evidence = skip that specific ambiguity permanently and do not re-identify it"""

    return prompt


def build_clarification_choice_generation_prompt(
    question: str,
    description,
    templates: str = "",
) -> str:
    return f'''## Task
    Your task is to analyze a clarification question and its accompanying description, and then generate a list of choices for the clarification question.
    Each choice should be a self-contained, natural language sentence that is easy for a non-technical user to understand and select.
    
    ## Instructions:
    - Make sure all choices follow similar formats (e.g, choice + a concise and clear explanation/evidence for the choice)
    - If there are columns to be chosen, list each column choice as "column_name::table_name, column_description" in a descriptive sentence.
    - Choose the most appropriate question template to formulate choices based on the given templates.
    - You MUST always add two compulsory choices: "Abstain" and "Others" into the choice list.
    
    ## Input
    - **Question**: The clarification question that needs to be answered.
    - **Description**: The context, explanations or data evidences containing the potential choices for the clarification question. This can be a simple string or a structured JSON object.
    
    ## Output format
    You MUST respond with ONLY a single, valid JSON string without any additional text, explanations, or markdown formatting. The string must contain a single key, "choices", which is a list of strings as follows:
    {{
      "choices": [
        "choice1",
        "choice2",
        "choice3",
        ...,
        "Abstain",
        "Others"
      ]
    }}
    ---
    **Templates:**
    {templates}
    ---
    **Input:**
    Input question: {question}
    Input description: {description}
    ---
    The choices are:
    '''


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