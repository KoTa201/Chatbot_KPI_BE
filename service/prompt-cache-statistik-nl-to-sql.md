# Task: Implementasi Cache Statistik Kolom untuk NL-to-SQL

## Konteks

Saat ini `ColumnStatisticsService.build_nl_to_sql_statistics()` menjalankan ~38 query SQL setiap kali dipanggil (agregasi numeric, distinct values text, count boolean) untuk membangun teks statistik yang disuntikkan ke prompt LLM pada tahap text-to-SQL.

Kolom yang dipakai selalu sama (didefinisikan statis di `numeric_columns`, `text_columns`, `boolean_columns`), dan statistik ini secara logis hanya berubah saat ada **ingestion data baru** — bukan setiap kali user bertanya. Query berat ini seharusnya tidak dijalankan ulang di setiap request inference.

## Tujuan

Ubah service ini menjadi model **compute-once, read-many**:
1. Statistik dihitung sekali di akhir pipeline ingestion, lalu disimpan.
2. Saat inference (text-to-SQL), sistem cukup membaca hasil yang sudah tersimpan — tanpa menjalankan ulang 38 query tersebut.
3. Statistik otomatis di-refresh setiap kali ingestion baru selesai.

## Constraint penting

- **Jangan gunakan `CREATE VIEW` atau `CREATE MATERIALIZED VIEW`.** Caching dilakukan di level aplikasi (tabel biasa + kolom JSON/TEXT), bukan fitur database view. Alasan: hasil butuh diubah jadi format teks siap-prompt, dan solusi ini harus tetap portable lintas database engine.
- Ikuti gaya kode yang sudah ada di project: SQLAlchemy async (`AsyncSession`), type hints Python, struktur folder `model/` dan `service/` yang sudah ada.
- Jangan ubah nama kolom/tabel yang sudah dipakai di `numeric_columns`, `text_columns`, `boolean_columns` — daftar ini tetap jadi single source of truth untuk kolom mana yang dihitung statistiknya.

## Task Breakdown

### 1. Buat model baru: tabel cache statistik

Buat model SQLAlchemy baru (misalnya `model/NlSqlStatsCache.py`) untuk menyimpan hasil statistik sebagai **satu baris (singleton row)**:

- `id` (primary key, selalu `1` — hanya ada satu baris di tabel ini)
- `stats_json` (TEXT/JSON, berisi hasil statistik dalam bentuk JSON string)
- `computed_at` (DATETIME with timezone, kapan terakhir dihitung)

Buat migration (cek dulu apakah project ini pakai Alembic — kalau ya, generate migration file-nya; kalau tidak, sesuaikan dengan cara migrasi yang dipakai project).

### 2. Refactor `ColumnStatisticsService`

Pecah method lama menjadi tiga method dengan tanggung jawab jelas:

- **`_compute_statistics() -> dict`**
  Logic inti yang sekarang ada di `build_nl_to_sql_statistics()` (loop numeric/text/boolean columns, jalankan query). Bedanya: hasil dikumpulkan sebagai `dict` terstruktur (bukan langsung string), supaya bisa di-serialize ke JSON. Struktur per kolom minimal:
  ```
  {
    "table.column": {
      "type": "numeric" | "text" | "boolean",
      "mean": ..., "min": ..., "max": ...,   # khusus numeric
      "unique": [...],                        # khusus text/boolean
      "non_null": int,
      "non_zero": int
    },
    ...
  }
  ```

- **`refresh_statistics() -> dict`**
  Panggil `_compute_statistics()`, serialize ke JSON, lalu upsert ke tabel `NlSqlStatsCache` (baris id=1). Update `computed_at`. Method ini yang akan dipanggil dari pipeline ingestion.

- **`get_statistics_text() -> str`**
  Baca baris dari `NlSqlStatsCache`. Kalau ada, parse JSON dan format jadi teks (fungsi format teks yang sama seperti output lama `build_nl_to_sql_statistics()`, supaya prompt LLM tidak berubah formatnya). Kalau belum ada baris sama sekali (first run / belum pernah ingestion), fallback panggil `refresh_statistics()` dulu baru format.

- Pertahankan `_format_value()` seperti sekarang (rounding float, handle enum via `.value`, dst).

- **Optimasi tambahan (opsional tapi disarankan):** gabungkan query `non_null` dan `non_zero` untuk text/boolean columns yang sekarang terpisah jadi 2-3 query per kolom menjadi 1 query per kolom (pakai `func.count()` + `func.sum(case(...))` sekaligus, seperti yang sudah dilakukan di bagian numeric).

### 3. Integrasi ke pipeline ingestion

Cari file/service yang menjalankan proses ingestion (tempat data KPI/user/dsb selesai di-load ke database). Tambahkan pemanggilan `await ColumnStatisticsService(db).refresh_statistics()` di **akhir** pipeline tersebut, setelah semua data selesai commit.

Kalau ingestion berjalan sebagai job/background task terpisah, pastikan `refresh_statistics()` dipanggil di langkah paling akhir job tersebut, bukan di tengah proses.

### 4. Integrasi ke flow inference (text-to-SQL)

Cari semua tempat yang sekarang memanggil `build_nl_to_sql_statistics()` (method lama), ganti menjadi `get_statistics_text()`. Pastikan tidak ada lagi pemanggilan method lama yang tersisa di codebase.

### 5. Concurrency safety

Karena hanya ada satu baris (id=1), pastikan `refresh_statistics()` melakukan **upsert** yang aman kalau dipanggil bersamaan dari beberapa proses ingestion (misal pakai `INSERT ... ON CONFLICT DO UPDATE` kalau Postgres, atau pattern get-then-update dengan commit yang benar sesuai ORM yang dipakai). Tidak perlu row-level locking kompleks — cukup pastikan tidak error kalau baris sudah ada.

### 6. Testing

Tambahkan test (sesuaikan dengan framework test yang sudah dipakai di project) untuk:
- `refresh_statistics()` menghasilkan JSON valid dan tersimpan dengan benar di tabel cache.
- `get_statistics_text()` mengembalikan teks yang sama persis formatnya dengan output lama `build_nl_to_sql_statistics()` (regression check, supaya prompt LLM tidak berubah perilaku).
- `get_statistics_text()` saat tabel cache masih kosong (first run) tetap menghasilkan output benar (via fallback ke `refresh_statistics()`).
- Update/hapus test lama yang menguji `build_nl_to_sql_statistics()` langsung, arahkan ke method baru.

## Acceptance Criteria

- [ ] Tidak ada `CREATE VIEW` / `CREATE MATERIALIZED VIEW` di migration manapun.
- [ ] Saat request text-to-SQL/inference dijalankan, tidak ada lagi ~38 query statistik yang dieksekusi — hanya 1 query baca ke tabel cache.
- [ ] `refresh_statistics()` dipanggil otomatis di akhir setiap proses ingestion.
- [ ] Format teks statistik yang disuntikkan ke prompt LLM tidak berubah dibanding sebelumnya (tidak mempengaruhi kualitas text-to-SQL yang sudah berjalan).
- [ ] Ada migration untuk tabel `NlSqlStatsCache` (atau nama yang disepakati sesuai konvensi project).
- [ ] Semua pemanggilan method lama (`build_nl_to_sql_statistics`) sudah diganti ke `get_statistics_text()`.
- [ ] Test lulus, termasuk skenario first-run (cache kosong).
