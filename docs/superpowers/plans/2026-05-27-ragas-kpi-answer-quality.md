# RAGAS KPI Answer Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve KPI progress answer correctness and relevancy by tightening NL-to-SQL and analysis prompts.

**Architecture:** Keep prompt logic in `template/promptTemplate.py`. Update tests in `tests/promptTemplate_test.py` first, then modify prompt text to pass them. No repository, service, or deterministic row enrichment changes.

**Tech Stack:** Python, pytest, FastAPI backend prompt templates, RAGAS eval runner.

---

## File Structure

- Modify: `tests/promptTemplate_test.py`
  - Owns focused assertions for NL-to-SQL and analysis prompt behavior.
- Modify: `template/promptTemplate.py`
  - Owns prompt text used by SQL generation and final result analysis.

---

### Task 1: Update Prompt Tests

**Files:**
- Modify: `tests/promptTemplate_test.py:5-42`

- [ ] **Step 1: Replace existing prompt tests with stricter expectations**

Replace file content with:

```python
from uuid import uuid4

from template.promptTemplate import build_analysis_prompt, build_nl_to_sql_prompt


def test_nl_to_sql_prompt_forbids_direct_realization_threshold_equality():
    prompt = build_nl_to_sql_prompt(
        user_query="KPI tim saya yang realisasinya sudah mencapai target atau mendekati target sampai bulan terakhir apa saja?",
        user_id=uuid4(),
        user_role="kepala_divisi",
        divisi=None,
    )

    assert "DILARANG membandingkan kt.realisasi langsung dengan km.achieve" in prompt
    assert "km.partial" in prompt
    assert "km.fail" in prompt
    assert "threshold" in prompt.lower()


def test_nl_to_sql_prompt_requires_latest_kpi_progress_fields():
    prompt = build_nl_to_sql_prompt(
        user_query="KPI tim saya yang realisasinya sudah mencapai target atau mendekati target sampai bulan terakhir apa saja?",
        user_id=uuid4(),
        user_role="kepala_divisi",
        divisi=None,
    )

    assert "kt.bulan_num" in prompt
    assert "km.kpi_name" in prompt
    assert "kt.realisasi" in prompt
    assert "km.target" in prompt
    assert "km.achieve" in prompt
    assert "km.partial" in prompt
    assert "km.fail" in prompt
    assert "kt.keterangan" in prompt
    assert "sampai bulan terakhir" in prompt
    assert "MAX(bulan_num)" in prompt


def test_analysis_prompt_answers_concisely_without_mandatory_full_table():
    prompt = build_analysis_prompt(
        user_query="KPI tim saya yang sudah mencapai target apa saja?",
        executed_sql="SELECT kt.realisasi, km.target, km.achieve, km.partial, km.fail FROM kpi_tracker_records kt JOIN kpi_master_records km ON kt.kpi_master_id = km.id;",
        query_result=[
            {
                "kpi_name": "Product Launch",
                "realisasi": "3",
                "target": "3",
                "achieve": "≥100%",
                "partial": "80–99%",
                "fail": "<80%",
                "keterangan": "Maintenance berjalan baik.",
            }
        ],
        rows_count=1,
    )

    assert "Jawab pertanyaan pengguna secara langsung terlebih dahulu" in prompt
    assert "Jangan tampilkan tabel lengkap kecuali pengguna memintanya" in prompt
    assert "maksimal 3–6 bullet" in prompt
    assert "LANGKAH 1 — TAMPILKAN TABEL DATA" not in prompt
    assert "INSIGHT DARI DATA" not in prompt


def test_analysis_prompt_guides_numeric_and_trl_target_comparison():
    prompt = build_analysis_prompt(
        user_query="KPI tim saya yang sudah mencapai target apa saja?",
        executed_sql="SELECT kt.realisasi, km.target, km.achieve, km.partial, km.fail FROM kpi_tracker_records kt JOIN kpi_master_records km ON kt.kpi_master_id = km.id;",
        query_result=[
            {
                "kpi_name": "Product Readiness",
                "realisasi": "TRL 7",
                "target": "TRL 7",
                "achieve": "≥100%",
                "partial": "85–99%",
                "fail": "<85%",
            }
        ],
        rows_count=1,
    )

    assert "realisasi == target" in prompt
    assert "target tercapai" in prompt
    assert "TRL N" in prompt
    assert "Jangan menyatakan status tidak diketahui hanya karena keterangan tidak memuat kata ACHIEVE" in prompt
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/promptTemplate_test.py -v
```

Expected: at least one test fails because current analysis prompt still requires table-first output and lacks new concise/TRL wording.

---

### Task 2: Update Prompt Template

**Files:**
- Modify: `template/promptTemplate.py:117-239`
- Test: `tests/promptTemplate_test.py`

- [ ] **Step 1: Update NL-to-SQL rules**

In `template/promptTemplate.py`, inside `build_nl_to_sql_prompt()`, replace rules 16-18 with:

```text
    16. Kolom km.target, km.achieve, km.partial, dan km.fail adalah definisi threshold KPI, bukan nilai realisasi. DILARANG membandingkan kt.realisasi langsung dengan km.achieve, km.partial, atau km.fail menggunakan =, IN, atau perbandingan string lain.
    17. Untuk pertanyaan tentang mencapai target, mendekati target, achieve, partial, fail, progress, atau kinerja, ambil data mentah untuk dianalisis: kt.user_id, kt.bulan_num, km.kpi_name, kt.realisasi, km.target, km.achieve, km.partial, km.fail, kt.keterangan.
    18. Untuk konteks "sampai bulan terakhir", "terbaru", atau "latest", ambil realisasi terbaru berdasarkan bulan_num untuk KPI/karyawan yang relevan, biasanya dengan MAX(bulan_num); jangan menyaring hasil dengan kt.realisasi = km.achieve atau kt.realisasi = km.partial.
```

- [ ] **Step 2: Update analysis prompt**

In `template/promptTemplate.py`, inside `build_analysis_prompt()`, replace the `prompt = f"""..."""` block from `[SYSTEM PROMPT]` through `[MULAI RESPONS...]` with:

```python
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

[PERTANYAAN PENGGUNA]
{user_query}

[SQL YANG DIEKSEKUSI]
{executed_sql}

[DATA MENTAH — {row_count_hint} — {truncation_note}]
{result_str}

[MULAI RESPONS]"""
```

- [ ] **Step 3: Run prompt tests**

Run:

```bash
pytest tests/promptTemplate_test.py -v
```

Expected: all 4 tests pass.

---

### Task 3: Verify RAGAS Case

**Files:**
- Read only: `evals/ragas/cases.yaml`
- Runtime output: `evals/ragas/results/`

- [ ] **Step 1: Run RAGAS eval**

Run:

```bash
python evals/ragas/runner.py
```

Expected: command completes and writes latest result under `evals/ragas/results/`.

- [ ] **Step 2: Inspect latest metrics**

Open `evals/ragas/results/latest.json` and check `team_kpi_progress_against_target` values for:

```json
"answer_correctness": 0.8,
"answer_relevancy": 0.8
```

Expected: both metrics improve versus previous `0.5952528436450018` correctness and `0.5628508667308318` relevancy. If either stays below 0.8, report exact values and final answer text; do not claim target reached.

---

## Self-Review

- Spec coverage: Tasks cover NL-to-SQL prompt, analysis prompt, tests, and RAGAS verification.
- Placeholder scan: No placeholders remain.
- Type consistency: Only existing functions `build_nl_to_sql_prompt()` and `build_analysis_prompt()` are used.
