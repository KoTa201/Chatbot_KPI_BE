"""
Prompt Service — membangun semua prompt yang dikirim ke GitHub Models API.
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


DB_SCHEMA = """
-- users (akses login)
users(
  id UUID PK,
  full_name VARCHAR,
  email VARCHAR,
  role ENUM('admin','hrd','kepala_divisi','karyawan'),
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
  tahun INT,
  bulan_num INT NULL,
  realisasi VARCHAR NULL,
  nama_orang VARCHAR NULL,
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
Rekrutmen Karyawan Baru     | KPI HRD     | 2025  | 10

kpi_tracker_records:
nama_orang   | kpi_master_id | tahun | bulan_num | realisasi
Budi Santoso | <uuid-kpi-1>  | 2025  | 3         | 480
Sari Dewi    | <uuid-kpi-2>  | 2025  | 3         | 12
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
  kt.nama_orang,
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
WHERE kt.tahun = EXTRACT(YEAR FROM CURRENT_DATE)::int
  AND kt.bulan_num = EXTRACT(MONTH FROM CURRENT_DATE)::int
GROUP BY kt.nama_orang
ORDER BY avg_persen DESC NULLS LAST
LIMIT 10;
"""


def build_nl_to_sql_prompt(
    user_query: str,
    user_id: str,
    user_role: str,
    divisi: str | None,
) -> str:
    """
    Membangun prompt NL-to-SQL untuk Stage 1.
    Menyertakan: schema, contoh data, few-shot, konteks user.
    """

    # Tentukan scope akses berdasarkan role
    if user_role == "Karyawan":
        data_access_scope = "Prioritaskan data milik user yang sedang login."
    elif user_role == "HRD":
        data_access_scope = "Semua karyawan (semua divisi)"
    elif user_role == "Owner":
        data_access_scope = "Semua karyawan dan semua divisi (akses penuh read-only)"
    else:  # Admin
        data_access_scope = "Semua data (akses penuh read-only)"

    prompt = f"""[SYSTEM PROMPT]
Kamu adalah asisten SQL expert yang mengkonversi pertanyaan bahasa Indonesia menjadi query SQL PostgreSQL.

ATURAN WAJIB:
1. Hanya generate query SELECT — DILARANG KERAS menggunakan INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, EXEC, atau perintah apapun selain SELECT.
2. Selalu gunakan tabel, view, dan kolom yang ada di schema yang diberikan di bawah.
3. Tambahkan LIMIT 1000 jika tidak ada limit spesifik dalam pertanyaan.
4. Gunakan alias yang deskriptif dan mudah dipahami pada kolom hasil.
5. Utamakan JOIN antara kpi_tracker_records dan kpi_master_records melalui kpi_master_id.
6. Format output: HANYA SQL mentah, tanpa penjelasan, tanpa markdown backtick, tanpa komentar.
7. Jika pertanyaan tidak dapat dijawab dengan data yang tersedia, keluarkan: SELECT 'Data tidak tersedia untuk pertanyaan ini' AS pesan;
8. nama orang selalu uppercase di database, pastikan untuk menyesuaikan filter jika pertanyaan menggunakan lowercase.
9. data di kpi_tracker_records itu insertannya bisa jadi lanjutan progress kpi tracker sebelumnya pastikan distinct atau group by jika untuk hitung jumlah orang atau pekerjaan
10. gunakan LIKE untuk pencarian nama orang agar lebih fleksibel, karena user bisa saja menyebutkan nama dengan format berbeda (misal: "Sari" saja, bukan "Sari Dewi")

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

    prompt = f"""[SYSTEM PROMPT]
Kamu adalah analis data KPI yang bertugas menyajikan dan menjelaskan data secara akurat dalam Bahasa Indonesia.
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
) -> str:
    """
    Membangun prompt untuk LLM-based ambiguity detection.
    Menilai tingkat ambiguitas query pada skala 0-1 dan mengidentifikasi jenis ambiguitas.
    """
    prompt = f"""[SYSTEM PROMPT — AMBIGUITY ASSESSOR]
Kamu adalah sistem deteksi ambiguitas untuk chatbot KPI perusahaan.
Tugasmu: menilai apakah pertanyaan pengguna memiliki lebih dari satu interpretasi 
yang berbeda secara material pada data KPI.

Konteks domain:
- Data KPI mencakup: KPI Master (target per aktivitas) dan KPI Tracker (realisasi per bulan)
- Dimensi data: karyawan, divisi, aktivitas KPI, periode (bulan/tahun), metrik (target, realisasi, persentase)
- Role pengguna saat ini: {user_role}

Jenis ambiguitas yang mungkin:
- "temporal": periode waktu tidak jelas (bulan ini vs. bulan terakhir data, tahun ini vs. tahun lalu, dll)
- "scope": entitas/siapa/apa yang ditampilkan tidak jelas (per individu vs. per divisi, semua vs. subset)
- "aggregation": cara menggabungkan data tidak jelas (total vs. rata-rata, sum vs. count)
- "metric": metrik mana yang diminta tidak jelas (target vs. realisasi, persentase vs. nilai absolut)
- "referential": referensi orang/divisi tidak jelas (divisi saya vs. semua divisi, KPI saya vs. semua KPI)

Pertanyaan pengguna: "{user_query}"

Evaluasi dengan menjawab JSON berikut (HANYA JSON, tidak ada penjelasan):
{{
  "ambiguity_score": <float 0.0-1.0>,
  "is_ambiguous": <boolean>,
  "ambiguity_type": <string dari daftar di atas, atau "none">,
  "possible_interpretations": [
    {{"interpretation": "deskripsi interpretasi 1", "sql_dimension": "dimensi yang berbeda"}},
    {{"interpretation": "deskripsi interpretasi 2", "sql_dimension": "dimensi yang berbeda"}}
  ],
  "suggested_clarifying_question": <string atau null>,
  "answer_options": [<list string dengan 2-4 opsi>]
}}

ATURAN PENILAIAN:
- Skor ≥ 0.7: jelas ambigu, perlu klarifikasi
- Skor 0.55–0.69: borderline, default ke TIDAK ambigu (langsung jawab)
- Skor < 0.55: tidak ambigu
- Jika role=Karyawan dan query menyebut "saya"/"milik saya", anggap TIDAK ambigu (scope sudah terbatas)
- Jika query menyebutkan bulan/tahun eksplisit, anggap temporal TIDAK ambigu

HANYA BERIKAN JSON, TANPA PENJELASAN LAIN."""

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
        f"  {i+1}. {interp['interpretation']}"
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
2. Menawarkan 2-4 pilihan konkret (BUKAN pertanyaan ya/tidak atau terbuka)
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
    clarifying_question: str,
    clarification_answer: str,
) -> str:
    """
    Membangun prompt untuk query disambiguator.
    Menggabungkan query asal dengan jawaban klarifikasi menjadi query yang lebih jelas.
    """
    prompt = f"""[SYSTEM PROMPT — QUERY DISAMBIGUATOR]
Pengguna awalnya bertanya: "{original_query}"
Pertanyaan klarifikasi yang diajukan: "{clarifying_question}"
Jawaban klarifikasi pengguna: "{clarification_answer}"

Buat query yang sudah disambiguasi (satu kalimat, dalam Bahasa Indonesia) yang 
menggabungkan pertanyaan asal dengan jawaban klarifikasi secara eksplisit dan spesifik.

CONTOH:
- Asal: "Siapa yang performanya paling bagus?"
- Klarifikasi: "Maksudnya bulan ini saja"
- Disambiguasi: "Tampilkan karyawan dengan persentase pencapaian KPI tertinggi pada bulan April 2025"

Jawab HANYA dengan kalimat query yang sudah disambiguasi, TANPA JSON, TANPA penjelasan lain."""

    return prompt


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
