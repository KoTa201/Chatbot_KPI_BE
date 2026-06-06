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
        session_context: str | None = None,
) -> str:
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
    column_statistics_block = (
        (column_statistics or "").strip()
        or (
            "Statistik kolom belum tersedia. Tetap gunakan schema dan pertanyaan pengguna; "
            "jangan mengarang nilai unik, mean, maksimum, minimum, non-zero, atau non-null."
        )
    )

    session_context_block = (session_context or "").strip() or "Tidak ada konteks percakapan sebelumnya."

    prompt = f"""[SYSTEM]
    Kamu adalah SQL expert. Konversi pertanyaan bahasa Indonesia ke PostgreSQL SELECT query.
    {addon_prompt_block}

    [SESSION CONTEXT]
    {session_context_block}

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
    - Periode & Tahun: gunakan bulan_num (1=Jan..12=Des) untuk bulan. Untuk filter tahun, gunakan `kg.tahun` (JOIN kpi_groups kg ON kt.group_id = kg.id atau km.group_id = kg.id) — WAJIB ditambahkan ke query HANYA jika prompt menyebutkan tahun spesifik (contoh: "2024", "tahun lalu", "tahun ini"). Jika prompt tidak menyebut tahun, JANGAN tambahkan filter kg.tahun. JANGAN gunakan EXTRACT(YEAR FROM kt.created_at) karena created_at adalah tanggal input data ke DB. "Bulan terakhir" = MAX(bulan_num).
    - Tambahkan LIMIT 1000 jika tidak ada limit spesifik.
    - Gunakan alias deskriptif. DISTINCT/GROUP BY jika menghitung orang atau item unik.
    - Rata-rata & Performa: JANGAN langsung menggunakan fungsi agregasi SQL (seperti AVG) jika pertanyaan menanyakan rata-rata/performa campuran dari berbagai KPI (yang mungkin berisi nilai TRL). Lebih baik SELECT data detail per baris (km.kpi_name, kt.realisasi, km.target, kt.bulan_num) agar LLM pada tahap analisis dapat menghitung rata-rata untuk KPI numerik dan melaporkan status TRL secara terpisah.
    
    PILIHAN TABEL:
    - GUNAKAN kpi_tracker_records kt untuk realisasi/progress/capaian/tren
        JOIN kpi_master_records km ON kt.kpi_master_id = km.id
        JOIN users u ON u.id = kt.user_id  ← jika perlu nama
        JOIN kpi_groups kg ON kt.group_id = kg.id  ← jika perlu filter tahun/group
    - GUNAKAN kpi_master_users kmu untuk assignment/daftar KPI per orang
        JOIN users u ON u.id = kmu.user_id
        JOIN kpi_master_records km ON km.id = kmu.kpi_master_id
        JOIN kpi_groups kg ON km.group_id = kg.id  ← jika perlu filter tahun/group
    
    KOLOM KPI:
    - km.target/achieve/partial/fail = threshold definisi, BUKAN nilai realisasi.
      Dilarang membandingkan kt.realisasi dengan nilai-nilai ini via =, IN, atau string.
    - Untuk pertanyaan kinerja, sertakan: km.kpi_name, kt.realisasi, km.target,
      kt.keterangan, kt.bulan_num. Jika pertanyaan menanyakan orang/karyawan/individu tertentu (misal Adiansyah, Andi, dll.), wajib sertakan juga nama lengkap karyawan (`u.full_name`) pada SELECT clause agar LLM dapat mengidentifikasi subjeknya di data mentah. Tambah km.achieve/partial/fail hanya jika
      pertanyaan eksplisit minta threshold/status/kategori.
    
    CAST NUMERIK — kt.realisasi dan km.target bertipe TEXT, bisa berisi "TRL 7", ">90%", dll.
    - DILARANG KERAS melakukan cast langsung ::NUMERIC atau CAST(... AS NUMERIC) pada kt.realisasi/km.target.
    - JANGAN cast ke NUMERIC dalam bentuk apapun (::NUMERIC, CAST(... AS NUMERIC), dsb.)
    - JANGAN lakukan kalkulasi persentase (/ target * 100) di query ini
    
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
       - Jika pertanyaan menyebut "progress" atau "keterangan", gunakan format daftar berikut:
         1. [Nama KPI]
            - Progress: realisasi [nilai] dari target [nilai]
            - Keterangan: [keterangan dari data]
       - Jika pertanyaan menyebut "karyawan", sertakan nama karyawan jika kolom nama karyawan tersedia di [DATA MENTAH].
       - Pertanyaan progress/kinerja → boleh tambahkan keterangan dari data.
       - Pertanyaan level tim/agregat → rangkum per KPI, bukan per orang, kecuali pertanyaan eksplisit menyebut karyawan/per orang.
       - Pertanyaan per-individu → tampilkan per orang.
       Jangan tampilkan field yang tidak relevan dengan pertanyaan.
    5. Jangan tambahkan rekomendasi, saran tindakan, atau opini.
    6. Output hanya berupa teks. Tidak ada pengecualian untuk format lain.
    7. Jangan sebut keterbatasan sistem, grafik, atau visualisasi — cukup jawab pertanyaan.
    8. Jawaban data disajikan lebih dahulu, baru insight/kesimpulan di bagian akhir 
       (lihat ATURAN INSIGHT di bawah).

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
      hitung persentase untuk SEMUA jenis KPI dengan cara:
      ekstrak angka dari realisasi dan target (abaikan teks/satuan seperti 
      "TRL", "/Hari", ">", "%"), lalu hitung: (angka_realisasi / angka_target) × 100%.
      Contoh: TRL 7 dari target TRL 7 = (7/7) × 100% = 100% (tercapai)
              TRL 5 dari target TRL 7 = (5/7) × 100% = 71.43% (belum tercapai)
              Realisasi 3 dari target 3 = (3/3) × 100% = 100% (tercapai)
      Selalu tampilkan angka persentase eksplisit, diikuti status "(tercapai)" 
      atau "(belum tercapai)".
      Jangan skip perhitungan untuk KPI apapun selama angka bisa diekstrak.
      dan tambahkan keterangan status "(tercapai)" atau "(belum tercapai)".
    - Tampilkan hasil persentase akhir saja (misal: 100%), 
      jangan sertakan formula kalkulasi seperti "(3/3) × 100%".
    - Jangan menghitung persentase jika target atau realisasi tidak ada di data.

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ATURAN INSIGHT & KESIMPULAN:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Setelah menyajikan data, tambahkan satu blok insight singkat HANYA jika 
    pertanyaan pengguna secara eksplisit atau implisit membutuhkan pemahaman lebih 
    (misalnya: "bagaimana kinerja?", "apa yang perlu diperhatikan?", "analisis", 
    "evaluasi", "tren", "perbandingan", atau pertanyaan yang bersifat open-ended).

    FORMAT BLOK INSIGHT:
    ---
    💡 Insight: [insight kritis dan memberikan value bagi HRD berdasarkan data]

    ATURAN ISI INSIGHT:
    - Insight harus relevan langsung dengan konteks pertanyaan pengguna ([PERTANYAAN PENGGUNA]).
    - Hanya gunakan fakta yang ada di [DATA MENTAH] — jangan mengarang atau mengasumsikan 
      data di luar yang tersedia.
    - Boleh menyebut pola, kesenjangan, atau hal yang menonjol dari data 
      (misal: KPI yang paling jauh dari target, tren naik/turun antar bulan, 
      individu dengan capaian tertinggi/terendah).
    - Jangan ulangi angka yang sudah disajikan di atas — cukup simpulkan polanya.
    - Jangan tambahkan saran tindakan, rekomendasi, atau opini subjektif.
    - Gunakan bahasa yang faktual dan netral.

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
        session_context: str | None = None,
) -> str:
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)

    prompt = f"""You are a strict question classifier and ambiguity detector for a data analytics system.

    Session context: {session_context}
    Addon constraints: {addon_prompt_block}

    INPUT:
      Question : "{user_query}"
      Role     : {user_role}
      Schema   : {DB_SCHEMA}
      Evidence : {kpi_context}

    ════════════════════════════════════════════
    STEP 0 — SESSION CONTEXT PRE-RESOLUTION (runs before everything)
    ════════════════════════════════════════════

    Before any scope check or ambiguity analysis, scan the session context above for
    information that can resolve potential ambiguities in the current question.

    A dimension/metric/filter is considered ALREADY RESOLVED if:
      ✓ It was explicitly stated or answered in a prior turn
      ✓ It was used as a parameter in a prior query (e.g. a chart or table was already shown for it)
      ✓ The current question is a follow-up that clearly continues the prior context
        (e.g. "mana yang lebih baik", "simpulkan", "bandingkan lagi" after a prior analysis)

    Pre-resolution rules:
      - If prior turn already established the time period  → do NOT raise AmbiView for period
      - If prior turn already established the KPI/metric  → do NOT raise AmbiView for metric/aspect
      - If prior turn already established the employee(s) → do NOT raise AmbiValue for names
      - If the current question is a follow-up/summary of prior results → inherit all prior context silently

    Example:
      Prior turn : user asked "bandingkan performa KPI karyawan A vs B bulan ini"
                   → system returned a comparison table (period=bulan ini, metric=KPI achievement)
      Current Q  : "mana yang lebih baik?"
      Resolution : period and metric are already established → NO ambiguity questions needed
                   → directly answer or return {{"has_ambiguity": false, "is_out_of_scope": false, "question_set": []}}

    Only proceed to STEP 1 after exhausting all resolvable context from the session.

    ════════════════════════════════════════════
    STEP 1 — SCOPE CHECK (runs first, no exceptions)
    ════════════════════════════════════════════

    A question is IN SCOPE if its topic could plausibly map to any table, column, or KPI —
    even if specific values (names, dates, entities) are unrecognized or ambiguous.
    Unknown/unclear specific values are NOT a scope failure; they are ambiguities (→ STEP 2).

    A question is OUT OF SCOPE only if its topic is completely unrelated to the database domain.

    Examples:
      IN SCOPE  → "bagaimana perkembangan andi"   ("andi" unrecognized = AmbiValue, not scope fail)
      IN SCOPE  → "siapa karyawan terbaik bulan ini"
      IN SCOPE  → "tunjukkan data divisi X"
      OUT SCOPE → "apa resep nasi goreng yang enak"
      OUT SCOPE → "berapa harga saham Apple hari ini"

    If OUT OF SCOPE → output EXACTLY this JSON and stop:
      {{"has_ambiguity": false, "is_out_of_scope": true, "question_set": []}}

    If IN SCOPE → proceed to STEP 2.

    ════════════════════════════════════════════
    STEP 2 — AMBIGUITY ANALYSIS
    ════════════════════════════════════════════

    ## Taxonomy

    level_1:
      - "Database-sourced ambiguity"  — causes incorrect/incomplete DB retrieval
      - "LLM-sourced ambiguity"       — causes misuse of LLM external knowledge

    level_2 (Database-sourced):
      - AmbiSchema : unclear which table/column to use
                     e.g. "oldest user" → age column vs registration_date column
      - AmbiValue  : name/term cannot be uniquely matched to a DB record
                     e.g. "coronavirus" → multiple stored forms ('COVID-19', 'coronavirus', 'SARS-CoV-2')
                     NOTE: employee names are NEVER AmbiValue — always resolved via full name OR email match
      - AmbiView   : intended SQL operation, metric, or aggregation is unclear
                     e.g. "perkembangan" → KPI achievement? trend? vs-target comparison?
                     NOTE: if the metric/operation was already used in a prior turn → NOT AmbiView

    level_2 (LLM-sourced):
      - AmbiContext : insufficient context for LLM reasoning
      - AmbiFallacy : question contradicts real-world facts (treat as typo, offer corrections)
      - AmbiRef     : temporal/spatial reference is underspecified
                      NOTE: if time period was already established in a prior turn → NOT AmbiRef

    ## Non-negotiable Rules

    RULE A: Employee/person name in query → NEVER raise AmbiValue. Always resolve by searching
            both full name AND email columns simultaneously. Do not ask the user about this.
    RULE B: Action/metric word mappable to more than one SQL op or KPI → always AmbiView. Ask the user.
            EXCEPTION: if session context already shows which metric/op was used → inherit it, do NOT ask.
    RULE C: Never self-resolve non-name ambiguities. Never assume the most likely interpretation.
            Never use general knowledge to skip asking.
    RULE D: Session context has higher priority than ambiguity detection. If an ambiguity can be
            resolved from prior turns, it MUST be resolved silently — never ask the user again.

    ## Per-ambiguity output

    For each ambiguity identified:
      - Assign exactly one level_1 and one level_2 label
      - Write a clarification question in Bahasa Indonesia
      - Provide 2–5 complete, mutually exclusive candidate options in description.options
        (these are raw context/evidence strings, not final user-facing choices)

    Option format by type:
      AmbiSchema  → "table_name::column_name" with schema description
      AmbiValue   → 2–3 possible WHERE clause interpretations
      AmbiView    → 2–3 possible SQL operations or KPI metrics
      AmbiContext → 2–3 possible values, ranges, or constraints
      AmbiFallacy → 2–3 best-guess corrections
      AmbiRef     → 2–3 interpretations of the temporal/spatial reference

    Completeness rules:
      - List ALL plausible options — never use "dll." / "etc."
      - Only one plausible column for a term → NOT AmbiSchema
      - Employee/person names are self-resolved (full name OR email) — never listed as an ambiguity
      - Ambiguities already resolved by session context → skip permanently, do not re-raise
      - Evidence marked "Abstain" → skip that ambiguity permanently
      - Zero ambiguities remaining → return empty question_set

    ════════════════════════════════════════════
    FEW-SHOT EXAMPLES
    ════════════════════════════════════════════

    --- EXAMPLE 1: Multiple ambiguities (employee name present) ---
    Question: "bagaimana perkembangan andi"
      "andi"         → employee name → self-resolved via full name OR email, NOT an ambiguity
      "perkembangan" → unclear metric → AmbiView (period) + AmbiView (aspect)

    Output:
    {{
      "has_ambiguity": true,
      "is_out_of_scope": false,
      "question_set": [
        {{
          "question": "Progress KPI Andi ingin dilihat pada periode atau waktu apa?",
          "level_1_label": "Database-sourced ambiguity",
          "level_2_label": "AmbiView",
          "description": {{
            "options": [
              "Tahun ini — menampilkan data tahun ini",
              "Tahun lalu — menampilkan data tahun lalu"
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
              "Tren performa dari waktu ke waktu — melihat naik/turunnya nilai KPI antar periode"
            ]
          }}
        }}
      ]
    }}

    --- EXAMPLE 2: Unambiguous ---
    Question: "tampilkan total penjualan bulan Januari 2024"
    Output:
    {{"has_ambiguity": false, "is_out_of_scope": false, "question_set": []}}

    --- EXAMPLE 3: Out of scope ---
    Question: "apa rekomendasi saham yang bagus minggu ini"
    Output:
    {{"has_ambiguity": false, "is_out_of_scope": true, "question_set": []}}

    --- EXAMPLE 4: Follow-up resolved by session context ---
    Session: user previously asked "bandingkan KPI karyawan A vs B bulan ini" → comparison table shown
    Question: "coba simpulkan siapa yang lebih baik dalam progress pengerjaan KPI"
      "siapa yang lebih baik" → follow-up of prior comparison → period & metric already established
      → NO ambiguity questions needed

    Output:
    {{"has_ambiguity": false, "is_out_of_scope": false, "question_set": []}}

    ════════════════════════════════════════════
    OUTPUT FORMAT — STRICT JSON, NO MARKDOWN
    ════════════════════════════════════════════

    OUT OF SCOPE:
      {{"has_ambiguity": false, "is_out_of_scope": true, "question_set": []}}

    IN SCOPE + AMBIGUOUS:
      {{
        "has_ambiguity": true,
        "is_out_of_scope": false,
        "question_set": [
          {{
            "question": "<pertanyaan klarifikasi dalam Bahasa Indonesia>",
            "level_1_label": "<Database-sourced ambiguity | LLM-sourced ambiguity>",
            "level_2_label": "<AmbiSchema | AmbiValue | AmbiView | AmbiContext | AmbiFallacy | AmbiRef>",
            "description": {{"options": ["<opsi 1>", "<opsi 2>", "<opsi 3>"]}}
          }}
        ]
      }}

    IN SCOPE + UNAMBIGUOUS:
      {{"has_ambiguity": false, "is_out_of_scope": false, "question_set": []}}

    ABSOLUTE RULES:
      - STEP 0 always runs first — resolve from session context before raising any ambiguity
      - STEP 1 runs second — unknown specific values → AmbiValue, never out-of-scope
      - Employee/person names are NEVER AmbiValue — always resolved via full name OR email
      - Never self-resolve non-name ambiguities; always ask the user (RULE B, C)
      - Session context resolves silently — NEVER re-ask something already answered in prior turns
      - All three output cases return valid JSON — no plain-string output, no code fences
      - "is_out_of_scope" always present; true only when topic is entirely unrelated
      - "description" has only one key: "options" (array of strings)
      - question_set items have exactly: question, level_1_label, level_2_label, description
      - No "metadata" field; no extra fields anywhere
      - Data source is always the database — never create source-selection ambiguity
      - "Abstain" in evidence = skip that ambiguity permanently"""

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
    Tugasmu HANYA mendeteksi apakah user secara EKSPLISIT meminta visualisasi grafik.

    ATURAN KETAT:
    1. Set is_visualize=true HANYA jika user secara eksplisit menyebut kata seperti:
       "grafik", "chart", "diagram", "line", "garis", "bar", "donut", "visualisasi", "tampilkan grafik", dll.
    2. Jika user hanya bertanya data/angka/informasi TANPA meminta visualisasi → is_visualize=false.
    3. Jangan berasumsi user ingin grafik hanya karena pertanyaan bersifat statistik atau komparatif.
    4. Jika user secara eksplisit meminta tipe grafik tertentu yang tidak didukung (seperti "radar", "3d", "surface", "bubble", dll.), tetap set is_visualize=true dan isi chart_type dengan tipe tersebut (misal: "radar", "3d_surface").
    5. Jika tipe grafik yang diminta didukung, chart_type wajib salah satu dari: "bar", "donut", "line", atau null.
    6. Jika is_visualize=true tapi tipe tidak disebutkan:
       - Jika query mengandung kata yang menunjukkan perubahan/perkembangan/tren dari waktu ke waktu (seperti "tren", "perkembangan", "timeline", "historis", "kronologis", atau menyebutkan rentang periode seperti "Januari hingga Mei", "dari bulan ke bulan"), gunakan chart_type "line".
       - Jika query mengandung kata yang menunjukkan pembagian/proporsi/komposisi dari keseluruhan (seperti "persentase sebaran", "sebaran status", "komposisi", "proporsi", "kontribusi", "persentase kategori"), gunakan chart_type "donut".
       - Selain itu, gunakan default chart_type "bar".
    7. Jika is_visualize=false → chart_type wajib null.
    8. Output HANYA JSON. Tidak boleh ada teks, penjelasan, atau markdown lain.

    CONTOH:
    - "Tampilkan grafik penjualan bulan ini" → {{"is_visualize": true, "chart_type": "bar"}}
    - "Buatkan line chart dari tren performa Andi" → {{"is_visualize": true, "chart_type": "line"}}
    - "Berapa total penjualan bulan ini?" → {{"is_visualize": false, "chart_type": null}}
    - "Bandingkan KPI Q1 dan Q2" → {{"is_visualize": false, "chart_type": null}}
    - "Siapa top 5 sales terbaik?" → {{"is_visualize": false, "chart_type": null}}
    - "Tampilkan visualisasi persentase sebaran status KPI karyawan" → {{"is_visualize": true, "chart_type": "donut"}}
    - "Tampilkan visualisasi tren perkembangan realisasi Andi" → {{"is_visualize": true, "chart_type": "line"}}

    Pertanyaan user:
    {user_query}

    Output JSON wajib:
    {{"is_visualize": true|false, "chart_type": "bar"|"donut"|"line"|null}}"""

    return prompt



def build_context() -> str:
    """
    Membangun KPI domain context string untuk digunakan oleh LLM ambiguity detection.
    """
    return """
        Domain KPI chatbot:
        - KPI Master: definisi KPI, aktivitas, kategori, target, satuan, dan operational definition.
        - KPI Tracker: realisasi KPI per bulan/tahun, status pencapaian, nilai aktual, dan persentase achievement.
        - Dimensi organisasi: karyawan, kepala divisi, dan cakupan seluruh organisasi.
        - Dimensi waktu: bulan, tahun, kuartal, tahun berjalan, tahun lalu, bulan ini, dan bulan terakhir data.
        - Metrik umum: target, realisasi, achievement percentage, performance score, jumlah KPI, total, rata-rata.
        - Status umum: achieved, partial, failed, tercapai, belum tercapai.
        """.strip()