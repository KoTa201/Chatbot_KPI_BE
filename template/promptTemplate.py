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
  tahun INT,
  category VARCHAR,
  kpi_name VARCHAR,
  definisi_operasional TEXT,
  target VARCHAR,
  achieve VARCHAR,
  partial VARCHAR,
  fail VARCHAR,
  responsibility_persons TEXT,
  created_at TIMESTAMP
)

-- realisasi KPI
kpi_tracker_records(
  id UUID PK,
  group_id UUID FK -> kpi_groups.id,
  kpi_master_id UUID FK -> kpi_master_records.id,
  user_id UUID FK -> users.id,
  tahun INT,
  bulan_num INT NULL,
  realisasi VARCHAR NULL,
  keterangan TEXT NULL,
  source_row INT NULL,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
"""

SAMPLE_DATA = """
kpi_master_records:
kpi_name                    | category    | tahun | target
Peningkatan Penjualan       | KPI Sales   | 2025  | 500
Rekrutmen Karyawan Baru     | KPI kepala_divisi     | 2025  | 10

kpi_tracker_records:
user_id      | kpi_master_id | tahun | bulan_num | realisasi
<uuid-user-1>| <uuid-kpi-1>  | 2025  | 3         | 480
<uuid-user-2>| <uuid-kpi-2>  | 2025  | 3         | 12
"""

FEW_SHOT_EXAMPLES = """
[CONTOH QUERY 1]
Pertanyaan: "Tampilkan semua KPI saya di bulan Maret 2025"
SQL:
SELECT
  km.kpi_name,
  km.target,
  kt.realisasi,
  kt.tahun,
  kt.bulan_num
FROM kpi_tracker_records kt
JOIN kpi_master_records km ON km.id = kt.kpi_master_id
WHERE kt.tahun = 2025 AND kt.bulan_num = 3
ORDER BY km.kpi_name
LIMIT 1000;

[CONTOH QUERY 2]
Pertanyaan: "Siapa karyawan dengan performa terbaik bulan ini?"
SQL:
SELECT
  u.full_name AS nama_karyawan,
  AVG(
    CASE
      WHEN NULLIF(km.target, '') ~ '^[0-9]+(\.[0-9]+)?$'
       AND NULLIF(kt.realisasi, '') ~ '^[0-9]+(\.[0-9]+)?$'
       AND NULLIF(km.target, '')::numeric != 0
      THEN (kt.realisasi::numeric / km.target::numeric) * 100
      ELSE NULL
    END
  ) AS avg_persen
FROM kpi_tracker_records kt
JOIN kpi_master_records km ON km.id = kt.kpi_master_id
JOIN users u ON u.id = kt.user_id
WHERE kt.tahun = EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND kt.bulan_num = EXTRACT(MONTH FROM CURRENT_DATE)::int
GROUP BY u.full_name
ORDER BY avg_persen DESC NULLS LAST
LIMIT 10;
"""


def build_nl_to_sql_prompt(
    user_query: str,
    user_id: UUID,
    user_role: str,
    divisi: str | None,
    addon_prompt: str | None = None,
) -> str:
    """
    Membangun prompt NL-to-SQL untuk Stage 1.
    Menyertakan: schema, contoh data, few-shot, konteks user.
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

    prompt = f"""[SYSTEM PROMPT]
Kamu adalah asisten SQL expert yang mengkonversi pertanyaan bahasa Indonesia menjadi query SQL PostgreSQL.
{addon_prompt_block}
ATURAN WAJIB:
1. Hanya generate query SELECT — DILARANG KERAS menggunakan INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC, atau perintah apapun selain SELECT.
2. Selalu gunakan tabel, view, dan kolom yang ada di schema yang diberikan di bawah.
3. Tambahkan LIMIT 1000 jika tidak ada limit spesifik dalam pertanyaan.
4. Gunakan alias yang deskriptif dan mudah dipahami pada kolom hasil.
5. Utamakan JOIN antara kpi_tracker_records dan kpi_master_records melalui kpi_master_id.
6. Format output: HANYA SQL mentah, tanpa penjelasan, tanpa markdown backtick, tanpa komentar.
7. Jika pertanyaan tidak dapat dijawab dengan data yang tersedia, keluarkan: SELECT 'Data tidak tersedia untuk pertanyaan ini' AS pesan;
8. Nama karyawan ada di users.full_name; join users u ON u.id = kt.user_id untuk filter atau menampilkan nama.
9. Data di kpi_tracker_records bisa berupa lanjutan progress KPI tracker sebelumnya; gunakan DISTINCT atau GROUP BY jika menghitung jumlah orang atau pekerjaan.
10. Gunakan UPPER(u.full_name) LIKE untuk pencarian nama orang agar fleksibel, karena user bisa menyebut nama sebagian.

[DATABASE SCHEMA]
{DB_SCHEMA}

[CONTOH DATA]
{SAMPLE_DATA}

[FEW-SHOT EXAMPLES]
{FEW_SHOT_EXAMPLES}

[CONTEXT PENGGUNA]
Role: {user_role}
Karyawan ID: {user_id}
Divisi: {divisi or 'N/A'}
Akses data: {data_access_scope}

[PERTANYAAN PENGGUNA]
{user_query}

SQL:"""

    return prompt


def build_analysis_prompt(
    user_query: str,
    executed_sql: str,
    query_result: list[dict],
    rows_count: int,
    addon_prompt: str | None = None,
) -> str:
    max_rows = 20
    max_cols = 8
    compact_rows = []
    for row in query_result[:max_rows]:
        keys = list(row.keys())[:max_cols]
        compact_rows.append({k: row.get(k) for k in keys})

    result_str = json.dumps(
        compact_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_json_default_serializer,
    )

    truncation_note = (
        f"⚠️ Data dipotong: ditampilkan {max_rows} dari {rows_count} baris total."
        if rows_count > max_rows
        else f"Total: {rows_count} baris."
    )

    # Build explicit column + row preview so model knows exact shape
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

    prompt = f"""[SYSTEM PROMPT — KPI AMBISQL AMBIGUITY ASSESSOR]
Kamu adalah sistem deteksi ambiguitas untuk chatbot KPI Text-to-SQL menggunakan AmbiSQL framework.
Tugasmu: identifikasi SEMUA frasa ambigu yang dapat mengubah SQL atau hasil KPI secara material.
{addon_prompt_block}
════════════════════════════════════════════════════════════════
INPUT ELEMENTS:
════════════════════════════════════════════════════════════════

Question: "{user_query}"
Role: {user_role}
Schema: {DB_SCHEMA}
Evidence: {kpi_context}

════════════════════════════════════════════════════════════════
AMBIGUITY TAXONOMY (AmbiSQL):
════════════════════════════════════════════════════════════════

LEVEL 1 — Ambiguity Source:
- Database-sourced ambiguity: Ketidakjelasan berasal dari struktur/semantik database
- LLM-sourced ambiguity: Ketidakjelasan berasal dari NL interpretation

⚠️ CRITICAL: Data selalu bersumber dari database. Jangan membuat kategori pemilihan sumber data.

LEVEL 2 — Ambiguity Type:
- AmbiSchema: Frasa dapat merujuk ke >1 tabel/kolom/metrik KPI
  Contoh: "terbaik" = achievement%, realisasi, target, atau score
- AmbiValue: Nilai user tidak jelas atau tidak cocok dengan data aktual
  Contoh: nama divisi, KPI, karyawan, status, periode
- AmbiIntent: Operasi bisnis tidak jelas
  Contoh: daftar vs ranking vs grouping vs filter vs perbandingan vs total vs rata-rata
- AmbiContext: Konteks bisnis kurang
  Contoh: cakupan aktif/nonaktif, mata uang, organisasi, aturan KPI
- AmbiFallacy: Asumsi user bertentangan dengan data tersedia
  Contoh: mereferensi data yang tidak ada atau karyawan yang tidak aktif
- AmbiRef: Referensi temporal/spasial tidak spesifik
  Contoh: bulan ini, tahun lalu, Q3, awal tahun, setelah target tercapai

════════════════════════════════════════════════════════════════
INSTRUCTIONS:
════════════════════════════════════════════════════════════════

1. Identifikasi maksimal 5 ambiguitas, urutkan dari dampak terbesar ke SQL
2. Untuk setiap ambiguitas, tentukan Level 1 dan Level 2 type
3. Untuk setiap ambiguity, sediakan 2-5 interpretasi konkret (opsi jawaban)
4. Gunakan Bahasa Indonesia bisnis, bukan istilah SQL, untuk clarifying questions
5. Jika ambiguitas tidak ada, return has_ambiguity=false dan question_set kosong array
6. Jika user memilih Abstain pada ambiguitas sebelumnya, jangan identifikasi lagi

════════════════════════════════════════════════════════════════
OUTPUT FORMAT (Strict JSON — FOLLOW EXACTLY):
════════════════════════════════════════════════════════════════

CONTOH OUTPUT AMBIGUOUS:
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
- NO top-level "ambiguity_score" field
- NO per-item "ambiguity_score" field
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


def build_clarifying_question_prompt(
    user_query: str,
    ambiguity_type: str,
    possible_interpretations: list[dict],
    user_role: str,
) -> str:
    """
    Membangun prompt untuk generator pertanyaan klarifikasi.
    Menghasilkan satu pertanyaan spesifik dengan 2-4 pilihan konkret.
    """
    interpretations_str = "\n".join(
        f"  {i+1}. {interp.get('interpretation') or interp.get('label') or interp if isinstance(interp, dict) else interp}"
        for i, interp in enumerate(possible_interpretations)
    )

    prompt = f"""[SYSTEM PROMPT — CLARIFICATION QUESTION GENERATOR]
Kamu adalah asisten KPI yang perlu meminta klarifikasi kepada pengguna.

Pertanyaan pengguna: "{user_query}"
Aspek ambigu: {ambiguity_type}
Role pengguna: {user_role}
Interpretasi yang teridentifikasi:
{interpretations_str}

Buat SATU pertanyaan klarifikasi dalam Bahasa Indonesia yang:
1. Langsung merujuk pada aspek ambigu yang spesifik
2. Menawarkan 3-4 pilihan konkret (BUKAN pertanyaan ya/tidak atau terbuka)
3. Singkat (maksimal 2 kalimat)
4. Menggunakan bahasa yang dipahami {user_role}
5. Menggunakan terminologi domain KPI (periode, target, realisasi, divisi, dll.)

CONTOH BAIK:
"Apakah Anda ingin melihat performa bulan ini saja, atau akumulasi sepanjang tahun 2025?"

CONTOH BURUK:
"Bisakah Anda menjelaskan lebih lanjut pertanyaan Anda?"

Jawab HANYA dalam format JSON (TANPA PENJELASAN LAIN):
{{
  "clarifying_question": <string pertanyaan klarifikasi>,
  "options": [<list string dengan 2-4 opsi>],
  "default_if_no_answer": <string interpretasi default jika tidak dijawab>
}}"""

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