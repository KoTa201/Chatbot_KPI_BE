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
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
    column_statistics_block = (
        (column_statistics or "").strip()
        or (
            "Statistik kolom belum tersedia. Tetap gunakan schema dan pertanyaan pengguna; "
            "jangan mengarang nilai unik, mean, maksimum, minimum, non-zero, atau non-null."
        )
    )

    prompt = f"""[SYSTEM]
Kamu adalah SQL expert. Konversi pertanyaan bahasa Indonesia ke PostgreSQL SELECT query.
{addon_prompt_block}

[PERTANYAAN ASLI PENGGUNA (q)]
{user_query}

[SKEMA DATABASE (S)]
{DB_SCHEMA}

[STATISTIK SETIAP KOLOM]
{column_statistics_block}

[ATURAN]
OUTPUT: Hanya SQL mentah — tanpa markdown, tanpa komentar, tanpa penjelasan.
        Jika tidak bisa dijawab: SELECT 'Data tidak tersedia untuk pertanyaan ini' AS pesan;

KEAMANAN:
- Hanya generate query SELECT. Dilarang: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC.
- user_id di [CONTEXT] adalah user login, BUKAN filter default. Pakai filter hanya jika user menyebut "saya/milik saya/KPI saya".
  Abaikan untuk pertanyaan tim atau orang lain.

QUERY:
- Gunakan tabel/kolom dari schema. Inferensi via (pertanyaan + schema + statistik kolom). Untuk numerik manfaatkan mean, maksimum, minimum, non-zero, non-null; untuk string/boolean manfaatkan nilai unik, non-zero, non-null.
- Nama: UPPER(u.full_name) LIKE UPPER('%nama%'). JOIN users u ON u.id = kt.user_id.
- Periode: gunakan bulan_num (1=Jan..12=Des). "Bulan terakhir" = MAX(bulan_num).
- Tambahkan LIMIT 1000 jika tidak ada limit spesifik.
- Gunakan alias deskriptif. DISTINCT/GROUP BY jika menghitung orang atau item unik.

PILIHAN TABEL:
- GUNAKAN kpi_tracker_records kt untuk realisasi/progress/capaian/tren
    JOIN kpi_master_records km ON kt.kpi_master_id = km.id
    JOIN users u ON u.id = kt.user_id  ← jika perlu nama
- GUNAKAN kpi_master_users kmu untuk assignment/daftar KPI per orang
    JOIN users u ON u.id = kmu.user_id
    JOIN kpi_master_records km ON km.id = kmu.kpi_master_id

KOLOM KPI:
- km.target/achieve/partial/fail = threshold definisi, BUKAN nilai realisasi.
  Dilarang membandingkan kt.realisasi dengan nilai-nilai ini via =, IN, atau string.
- Untuk pertanyaan kinerja, sertakan: km.kpi_name, kt.realisasi, km.target,
  kt.keterangan, kt.bulan_num. Tambah km.achieve/partial/fail hanya jika
  pertanyaan eksplisit minta threshold/status/kategori.

CAST NUMERIK — kt.realisasi dan km.target bertipe TEXT, bisa berisi "TRL 7", ">90%", dll.
- DILARANG KERAS melakukan cast langsung ::NUMERIC. Untuk kalkulasi numerik wajib pakai:
    CASE WHEN kt.realisasi ~ '^[0-9]+(\\.[0-9]+)?$'
          AND km.target    ~ '^[0-9]+(\\.[0-9]+)?$'
         THEN kt.realisasi::NUMERIC / NULLIF(km.target::NUMERIC, 0) * 100
         ELSE NULL END AS persen_pencapaian
- Jika hanya menampilkan nilai, SELECT as TEXT — tidak perlu cast.

[CONTEXT]
Role: {user_role} | user_id: {user_id} | Tahun: {datetime.now().year}

SQL:"""

    return prompt


def build_analysis_prompt(
    user_query: str,
    executed_sql: str,
    query_result: list[dict],
    rows_count: int,
    addon_prompt: str | None = None,
) -> str:
    compact_rows = query_result

    result_str = json.dumps(
        compact_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default_serializer,
    )

    truncation_note = f"Total: {rows_count} baris."

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
    Kamu menyajikan semua jawaban dalam format teks.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ATURAN WAJIB — IKUTI PERSIS:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    1. Jawab pertanyaan pengguna secara langsung terlebih dahulu.
    2. Gunakan hanya data dalam [DATA MENTAH]. Jangan menambah nama, angka, atau periode 
       yang tidak ada di data.
    3. Jangan tampilkan tabel lengkap kecuali pengguna memintanya secara eksplisit.
    4. Sesuaikan detail dengan scope pertanyaan:
       - Pertanyaan "apa saja" / daftar → nama KPI + realisasi + target saja.
       - Pertanyaan progress/kinerja → boleh tambahkan keterangan dari data.
       - Pertanyaan level tim/agregat → rangkum per KPI, bukan per orang.
       - Pertanyaan per-individu → tampilkan per orang.
       Jangan tampilkan field yang tidak relevan dengan pertanyaan.
    5. Jika data kosong: tulis "Mohon maaf, tidak ada data valid untuk pertanyaan anda 
       atau pertanyaan anda diluar konteks domain sistem ini" dan berhenti.
    6. Jangan tambahkan rekomendasi, saran tindakan, atau opini.
    7. Jangan tambahkan insight umum kecuali pengguna memintanya.
    8. Output hanya berupa teks. Tidak ada pengecualian untuk format lain.
    9. Jangan sebut keterbatasan sistem, grafik, atau visualisasi — cukup jawab pertanyaan.
    10. Jangan menambahkan kalimat penutup, ringkasan akhir, atau kesimpulan 
        generatif di luar data. Jawaban berhenti setelah data terakhir disajikan.

    ATURAN KHUSUS KPI TARGET / PROGRESS:
    - Tampilkan nilai realisasi dan target dari data apa adanya.
    - Jika realisasi dan target tersedia dan bisa dibandingkan secara langsung, 
      kamu BOLEH menambahkan frasa singkat seperti "(tercapai)" atau "(belum tercapai)" 
      — hanya berdasarkan perbandingan nilai realisasi vs target di data.
    - Untuk nilai numerik: realisasi >= target → tercapai.
    - Untuk format TRL N: angka N >= angka target → tercapai.
    - Jangan tulis label status jika salah satu dari realisasi atau target tidak ada di data.
    - Kolom achieve, partial, fail hanya boleh disebut jika kolom tersebut ada di [DATA MENTAH] 
      dan nilainya eksplisit ada di baris data.
    - Jika kolom bulan_num tersedia di [DATA MENTAH], kamu boleh menyebut periode 
      sebagai "bulan [angka]" atau nama bulannya (1=Januari, 2=Februari, dst.).
    - Jika kolom bulan_num TIDAK ada di [DATA MENTAH], jangan sebutkan periode 
      apapun — cukup tulis "bulan terakhir" saja tanpa angka.
    - Jika pertanyaan menanyakan capaian/performa individu tanpa batas waktu 
         eksplisit, tampilkan minimal bulan terakhir. Jika data historis tersedia 
         dan relevan untuk menggambarkan tren, tampilkan maksimal 3 bulan terakhir.
    - Jika pertanyaan mengandung kata "persen", "%" atau "persentase capaian", 
      dan data mengandung realisasi serta target numerik yang bisa dibandingkan, 
      hitung dan tampilkan persentase: (realisasi / target) × 100%.
    - Untuk KPI non-numerik seperti TRL, nyatakan sebagai "tercapai" atau 
      "belum tercapai" tanpa persentase, karena tidak bisa dihitung secara linier.
    - Jangan menghitung persentase jika target atau realisasi tidak ada di data.
    

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
    Output JSON mengikuti spec ketat: has_ambiguity + is_out_of_scope + question_set.

    Fixes applied:
    - Scope check hanya gagal jika topik tidak relevan, bukan jika nilai spesifik tidak dikenal
    - LLM dilarang self-resolve ambiguity (nama tidak unik → AmbiValue, metric ambigu → AmbiView)
    - Few-shot examples konkret untuk kasus seperti "bagaimana perkembangan andi"
    - Instruksi analisis diperkuat agar tidak bias ke false negative
    - Out-of-scope kini mengembalikan JSON (bukan plain string) agar parsing konsisten
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
      │ → NOT a scope failure → they are AMBIGUITIES → go to STEP 2 │
      │                                                             │
      │ Topic entirely unrelated to any table/column/KPI            │
      │ → IS a scope failure → return out-of-scope JSON             │
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
      ✓ Output EXACTLY this JSON and nothing else:
        {{
          "has_ambiguity": false,
          "is_out_of_scope": true,
          "question_set": []
        }}

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
      "is_out_of_scope": false,
      "question_set": [
        {{
          "question": "Andi yang dimaksud merujuk ke karyawan yang mana?",
          "level_1_label": "Database-sourced ambiguity",
          "level_2_label": "AmbiValue",
          "description": {{
            "options": [
              "Berdasarkan nama lengkap — nama karyawan yang mengandung kata Andi",
              "Berdasarkan nama kpi — nama kpi mengandung kata Andi"
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
      "is_out_of_scope": false,
      "question_set": []
    }}

    --- EXAMPLE 3: Out of scope ---

    Question : "apa rekomendasi saham yang bagus minggu ini"
    Analysis :
      - Topic = stock investment recommendation → no table/column/KPI covers this

    Expected output:
    {{
      "has_ambiguity": false,
      "is_out_of_scope": true,
      "question_set": []
    }}

    ════════════════════════════════════════════════════════════════
    OUTPUT FORMAT — THREE POSSIBLE OUTPUTS, ALL STRICT JSON:
    ════════════════════════════════════════════════════════════════

    OUT OF SCOPE:
      {{
        "has_ambiguity": false,
        "is_out_of_scope": true,
        "question_set": []
      }}

    IN SCOPE + AMBIGUOUS:
      {{
        "has_ambiguity": true,
        "is_out_of_scope": false,
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

    IN SCOPE + UNAMBIGUOUS:
      {{
        "has_ambiguity": false,
        "is_out_of_scope": false,
        "question_set": []
      }}

    ════════════════════════════════════════════════════════════════
    CRITICAL RULES (must be followed in every response):
    ════════════════════════════════════════════════════════════════
      - STEP 1 always runs first — unknown specific values → AmbiValue, NOT out of scope
      - NEVER self-resolve ambiguities; always ask the user (see RULE A, B, C above)
      - ALL three output cases must return valid JSON — there is NO plain-string output
      - "is_out_of_scope" must always be present: true only when topic is entirely unrelated
      - "description" must be an object with ONLY an "options" key (array of candidate context/evidence strings)
      - description.options are raw candidate context/evidence, not final user-facing choices
      - NO "metadata" field, NO extra fields anywhere in the JSON
      - question_set items must have exactly: question, level_1_label, level_2_label, description
      - Return ONLY valid JSON — no markdown formatting, no code fences, no explanation text, no comments
      - Data source is ALWAYS the database — never create source-selection ambiguity
      - "Abstain" in evidence = skip that specific ambiguity permanently and do not re-identify it"""

    return prompt


def build_clarification_choice_generation_prompt(
    question: str,
    description,
    templates: str = "",
) -> str:
    return f'''## Task
    You are helping a non-technical user answer a clarification question by generating a set of clear, plain-language choices.
    Your goal is to make each choice immediately understandable — no jargon, no technical terms, no raw column/table names.
    
    ## Core Rules
    1. **Plain language only** — Write as if explaining to someone unfamiliar with databases, code, or technical systems.
       - Bad: "revenue::sales_table — the revenue column from the sales table"
       - Good: "Total Revenue — the overall income earned from all sales transactions"
    
    2. **Consistent format** — Every choice must follow the same pattern:
       - **[Short Label]** — [One sentence explaining what this means or why a user would pick it]
       - Example: "Last 30 Days — shows data from the most recent month up to today"
    
    3. **Self-contained** — Each choice must make sense on its own, without needing to read the question again.
    
    4. **Concrete and specific** — Avoid vague choices. If a choice refers to a metric, time range, or category, name it explicitly.
    
    5. **Choice must be use same language as the question 
    
    ## Input
    - **Question**: The clarification question that needs to be answered.
    - **Description**: Context or data that contains the potential choices. May be a plain string or a JSON object.
    - **Templates** *(optional)*: Pre-defined formats to guide how choices should be structured.
    
    ## Output Format
    Respond with ONLY a valid JSON object — no explanation, no markdown, no extra text.
    
    {{
      "choices": [
        "Choice One — brief plain-language explanation of what this means",
        "Choice Two — brief plain-language explanation of what this means",
        ...,
      ]
    }}
    
    ---
    **Templates:**
    {templates}
    ---
    **Question:** {question}
    **Description:** {description}
    ---
    **Choices:**
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
    Gabungkan `original_question` dengan `additional_information` menjadi satu pertanyaan analitik KPI yang koheren, lengkap, dan mudah dipahami.

    ## Core Principles
    1.  **Absolute Preservation**: PERTAHANKAN semua metrik, dimensi, periode waktu, dan filter dari `original_question`. Tidak ada yang boleh dihilangkan atau diubah, kecuali jika secara langsung dan eksplisit bertentangan dengan `additional_information`.
    2.  **Full Integration**: Integrasikan SEMUA segmentasi, filter, target, atau konteks bisnis baru dari `additional_information` ke dalam pertanyaan baru secara mulus.
    3.  **Conflict Resolution**: Jika ada bagian dari `additional_information` yang secara langsung bertentangan dengan `original_question` (misalnya periode waktu yang berbeda, metrik yang diganti), maka `additional_information` yang berlaku. Ini adalah **satu-satunya** kondisi di mana informasi original boleh dimodifikasi.
    4.  **Natural Language**: Output akhir harus berupa satu pertanyaan analitik yang terdengar natural, bukan daftar kriteria.

    ## Examples
    Original question: Tampilkan total revenue per region untuk Q3 2024.
    Additional information: Hanya tampilkan region dengan revenue di atas 500 juta dan bandingkan dengan Q3 2023.
    Rewritten question: Tampilkan total revenue per region untuk Q3 2024 yang melebihi 500 juta, beserta perbandingannya dengan Q3 2023.

    Original question: Berapa rata-rata customer acquisition cost (CAC) per channel marketing bulan ini?
    Additional information: Fokus hanya pada channel digital, dan sertakan juga nilai customer lifetime value (CLV) untuk menghitung rasio CLV:CAC.
    Rewritten question: Berapa rata-rata CAC per channel marketing digital bulan ini, beserta nilai CLV masing-masing channel untuk menghitung rasio CLV:CAC?

    Original question: Tampilkan tren tingkat retensi pelanggan selama 6 bulan terakhir berdasarkan segmen produk.
    Additional information: Saya hanya tertarik pada segmen produk premium, dan tambahkan churn rate sebagai metrik pembanding.
    Rewritten question: Tampilkan tren tingkat retensi dan churn rate pelanggan segmen produk premium selama 6 bulan terakhir.

    ## Response Format
    - Kembalikan **hanya** teks pertanyaan yang telah ditulis ulang.
    - Jangan sertakan preamble, label (seperti "Rewritten question:"), atau penjelasan apapun.

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