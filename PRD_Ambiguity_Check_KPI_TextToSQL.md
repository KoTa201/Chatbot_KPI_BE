# Product Requirements Document (PRD)

## Fitur Ambiguity Check pada Text-to-SQL untuk Project KPI

---

**Dokumen:** PRD-KPI-AMBISQL-001  
**Versi:** 1.0.0  
**Tanggal:** 20 Mei 2026  
**Status:** Draft  
**Penulis:** Tim Product  
**Referensi:** AmbiSQL — Interactive Ambiguity Detection and Resolution for Text-to-SQL (Ding et al., SIGMOD'26); [github.com/JustinzjDing/AmbiSQL](https://github.com/JustinzjDing/AmbiSQL)

---

## Daftar Isi

1. [Ringkasan Eksekutif](#1-ringkasan-eksekutif)
2. [Latar Belakang & Motivasi](#2-latar-belakang--motivasi)
3. [Tujuan Produk](#3-tujuan-produk)
4. [Scope & Batasan](#4-scope--batasan)
5. [Taksonomi Ambiguitas](#5-taksonomi-ambiguitas)
6. [Arsitektur Sistem](#6-arsitektur-sistem)
7. [Functional Requirements](#7-functional-requirements)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [User Stories & Acceptance Criteria](#9-user-stories--acceptance-criteria)
10. [Desain UI/UX](#10-desain-uiux)
11. [Data Requirements](#11-data-requirements)
12. [Integrasi & Dependensi](#12-integrasi--dependensi)
13. [Metrik Keberhasilan](#13-metrik-keberhasilan)
14. [Risiko & Mitigasi](#14-risiko--mitigasi)
15. [Rencana Implementasi](#15-rencana-implementasi)
16. [Glosarium](#16-glosarium)

---

## 1. Ringkasan Eksekutif

Fitur **Ambiguity Check** adalah komponen kritis dalam sistem Text-to-SQL untuk platform KPI yang memungkinkan pengguna non-teknis melakukan query terhadap data KPI menggunakan bahasa alami (natural language). Ambiguitas dalam query merupakan salah satu penyebab utama SQL yang dihasilkan tidak akurat, menghasilkan data KPI yang salah, dan pada akhirnya mengarah pada pengambilan keputusan bisnis yang keliru.

Berdasarkan penelitian AmbiSQL (SIGMOD'26), fitur ini akan mengimplementasikan sistem deteksi dan resolusi ambiguitas dua tahap — **Ambiguity Identification** dan **Iterative Refinement** — yang secara proaktif mengidentifikasi frasa ambigu dalam query KPI, mengklasifikasikannya berdasarkan taksonomi terstruktur, lalu memandu pengguna melalui pertanyaan klarifikasi berbasis pilihan ganda untuk menghasilkan SQL yang sesuai dengan intent pengguna.

---

## 2. Latar Belakang & Motivasi

### 2.1 Konteks Project KPI

Platform KPI memungkinkan manajer, analis bisnis, dan stakeholder untuk meng-query data performa melalui antarmuka bahasa alami — tanpa harus memahami SQL atau struktur database. Pertanyaan seperti:

- _"Tampilkan performa sales bulan ini"_
- _"Siapa 5 karyawan terbaik tahun lalu?"_
- _"Berapa rata-rata achievement Q3 di semua divisi?"_

Masing-masing pertanyaan di atas mengandung potensi ambiguitas yang dapat menyebabkan SQL yang salah dieksekusi.

### 2.2 Permasalahan yang Ada

Tanpa mekanisme ambiguity check, sistem Text-to-SQL yang digunakan saat ini menghadapi masalah berikut:

- **Misinterpretasi schema**: "Karyawan terbaik" bisa merujuk ke `sales_amount`, `performance_score`, atau `ranking_index` — sistem memilih salah satu tanpa konfirmasi.
- **Ambiguitas temporal**: "Bulan ini", "tahun lalu", atau "Q3" tidak selalu memiliki definisi yang jelas — apakah menggunakan fiscal year atau calendar year.
- **Ambiguitas nilai**: "Regional" bisa berarti kode wilayah, nama kota, atau zona sales.
- **Ambiguitas operasi**: "Tampilkan sales per divisi" bisa bermakna `GROUP BY`, `ORDER BY`, atau `WHERE` untuk divisi tertentu.

### 2.3 Dampak Bisnis

Kesalahan query KPI berdampak langsung pada:

- Laporan performa yang tidak akurat kepada manajemen
- Keputusan bonus/evaluasi karyawan yang keliru
- Target planning yang didasarkan pada angka yang salah
- Menurunnya kepercayaan pengguna terhadap sistem

---

## 3. Tujuan Produk

### 3.1 Tujuan Utama

- Mendeteksi ambiguitas secara otomatis pada query bahasa alami sebelum SQL di-generate.
- Memandu pengguna melalui proses klarifikasi yang intuitif tanpa perlu pengetahuan SQL.
- Meningkatkan akurasi SQL yang dihasilkan untuk query KPI.

### 3.2 Tujuan Terukur

| Tujuan                                                 | Target                                         |
| ------------------------------------------------------ | ---------------------------------------------- |
| Peningkatan akurasi SQL generation pada query ambigu   | ≥ 30% dibanding baseline tanpa ambiguity check |
| Berkurangnya laporan "data tidak sesuai" dari pengguna | Turun ≥ 40% dalam 3 bulan pertama deployment   |
| Waktu rata-rata resolusi per ambiguitas                | ≤ 15 detik per pertanyaan klarifikasi          |
| Tingkat kepuasan pengguna terhadap fitur               | ≥ 4.0/5.0 (survei in-app)                      |

---

## 4. Scope & Batasan

### 4.1 Dalam Scope

- Deteksi dan klasifikasi ambiguitas pada query KPI berbahasa Indonesia dan Inggris.
- Generasi pertanyaan klarifikasi berbasis pilihan ganda untuk setiap ambiguitas yang terdeteksi.
- Penulisan ulang (rewriting) query berdasarkan jawaban pengguna.
- Iterasi multi-putaran hingga semua ambiguitas terselesaikan.
- Penyimpanan preferensi pengguna untuk ambiguitas yang berulang.
- Log interaksi klarifikasi yang dapat diaudit.

### 4.2 Di Luar Scope (v1.0)

- Automatic resolution tanpa konfirmasi pengguna (fully automated mode).
- Dukungan bahasa selain Indonesia dan Inggris.
- Ambiguitas pada query yang melibatkan lebih dari satu database/data source.
- Training ulang model LLM secara real-time berdasarkan feedback pengguna.

### 4.3 Asumsi

- Platform KPI memiliki schema database yang terdefinisi dengan baik dan didokumentasikan.
- Pengguna memiliki pengetahuan domain bisnis (tahu apa yang dimaksud KPI mereka), namun tidak harus paham SQL.
- LLM backend (GPT-4 / model internal) tersedia dan dapat dipanggil via API.

---

## 5. Taksonomi Ambiguitas

Berdasarkan AmbiSQL, taksonomi berikut diadaptasi untuk konteks KPI:

### 5.1 Database-Sourced Ambiguity

Ambiguitas yang muncul karena referensi yang tidak jelas terhadap elemen database KPI.

#### 5.1.1 AmbiSchema

Query tidak memberikan konteks cukup untuk menentukan tabel atau kolom mana yang dimaksud.

**Contoh KPI:**

- _"Tampilkan karyawan dengan nilai tertinggi"_ → apakah `performance_score`, `sales_achievement`, atau `ranking`?
- _"Siapa yang paling produktif?"_ → kolom `units_produced`, `revenue_generated`, atau `tasks_completed`?

**Dampak:** Salah pemetaan sumber data dalam query SQL (salah `JOIN` atau `SELECT` kolom).

#### 5.1.2 AmbiValue

Nilai yang disebutkan dalam query tidak cocok dengan nilai aktual yang tersimpan di database.

**Contoh KPI:**

- _"KPI divisi IT"_ → database menyimpan `"Information Technology"` atau `"IT Dept"`?
- _"Region Jakarta"_ → database menyimpan `"JKT"`, `"Jakarta Raya"`, atau `"DKI"`?

**Dampak:** Query mengembalikan hasil kosong atau tidak mencakup semua data yang relevan.

#### 5.1.3 AmbiIntent

Tidak jelas operasi SQL apa yang diinginkan pengguna.

**Contoh KPI:**

- _"Tampilkan sales per tim"_ → `GROUP BY`, `ORDER BY`, atau filter per tim tertentu?
- _"Data karyawan berdasarkan departemen"_ → apakah listing, grouping, atau filter?

**Dampak:** SQL menggunakan operator yang salah (`ORDER BY` vs `GROUP BY` vs `WHERE`).

### 5.2 LLM-Sourced Ambiguity

Ambiguitas yang muncul karena LLM membutuhkan reasoning di luar konten database.

#### 5.2.2 AmbiContext

Query kekurangan konteks untuk memandu reasoning LLM.

**Contoh KPI:**

- _"Tampilkan data terbaru"_ → terbaru = hari ini, minggu ini, atau bulan ini?
- _"Kurs konversi sales"_ → kurs mata uang apa? Tanggal berapa?

**Dampak:** LLM menggunakan asumsi default yang mungkin berbeda dari ekspektasi pengguna.

#### 5.2.3 AmbiFallacy

Asumsi dalam query bertentangan dengan data aktual atau fakta yang ada.

**Contoh KPI:**

- _"Peserta program X tahun 2024"_ → Program X belum ada di 2024.
- _"KPI divisi Y di Q2"_ → Divisi Y baru dibentuk Q3.

**Dampak:** Query dieksekusi berdasarkan premis yang salah, menghasilkan data yang menyesatkan.

#### 5.2.4 AmbiRef

Referensi spasial atau temporal yang tidak spesifik, berpotensi multi-interpretasi.

**Contoh KPI:**

- _"Setelah merger"_ → apakah tanggal signing, effective date, atau setelah integrasi selesai?
- _"Awal tahun"_ → Januari saja, atau Q1?
- _"Setelah target tercapai"_ → target apa? Kapan tepatnya?

**Dampak:** Filter temporal atau kondisional yang tidak tepat, menghasilkan rentang data yang salah.

---

## 6. Arsitektur Sistem

### 6.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        KPI Platform                             │
│                                                                 │
│   ┌──────────────┐    ┌─────────────────────┐    ┌──────────┐  │
│   │  User Input  │───▶│  Ambiguity Check     │───▶│Text-to-  │  │
│   │  Panel       │    │  Module (AmbiSQL)    │    │SQL Engine│  │
│   └──────────────┘    └─────────────────────┘    └──────────┘  │
│                              │    ▲                    │        │
│                              ▼    │                    ▼        │
│                       ┌──────────────┐         ┌──────────┐    │
│                       │Clarification │         │  KPI DB  │    │
│                       │  UI Panel    │         └──────────┘    │
│                       └──────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Pipeline Dua Tahap

**Tahap 1 — Ambiguity Identification:**

```
Query Input ──▶ Ambiguity Detection ──▶ Ambiguity Classification
                     │                        │
                     ▼                        ▼
              [Frasa Ambigu]          [Tipe per Taksonomi]
                     │                        │
                     └───────────┬────────────┘
                                 ▼
                    CQ Generation (Pertanyaan Klarifikasi)
                                 │
                                 ▼
                    Presentasi ke User (Pilihan Ganda)
```

**Tahap 2 — Iterative Refinement:**

```
User Answers ──▶ Preference Update ──▶ Query Rewriting
                                             │
                                             ▼
                                   Re-check Ambiguity
                                             │
                              ┌──────────────┴────────────┐
                              ▼                           ▼
                    [Ambiguitas Tersisa?]         [Tidak Ada Ambiguitas]
                              │                           │
                              └── Iterasi Ulang           ▼
                                                  Submit ke Text-to-SQL
```

### 6.3 Komponen Teknis

| Komponen             | Fungsi                                                  | Teknologi                              |
| -------------------- | ------------------------------------------------------- | -------------------------------------- |
| Ambiguity Detector   | Identifikasi frasa ambigu via LLM + in-context learning | LLM API (GPT-4/internal model)         |
| Taxonomy Classifier  | Klasifikasi tipe ambiguitas                             | Prompt engineering + few-shot examples |
| CQ Generator         | Generasi pertanyaan klarifikasi berbasis pilihan ganda  | LLM + DB schema lookup                 |
| Preference Store     | Penyimpanan jawaban klarifikasi user                    | Redis / PostgreSQL                     |
| Query Rewriter       | Penulisan ulang query berdasarkan klarifikasi           | LLM + template-based rewriting         |
| Ambiguity Re-checker | Validasi query hasil rewriting                          | Ambiguity Detector (reuse)             |

---

## 7. Functional Requirements

### 7.1 Modul Deteksi Ambiguitas

**FR-01** — Sistem harus secara otomatis menganalisis setiap query input sebelum diteruskan ke engine Text-to-SQL.

**FR-02** — Sistem harus mengidentifikasi satu atau lebih frasa ambigu dalam query berdasarkan taksonomi 7 tipe yang telah didefinisikan (AmbiSchema, AmbiValue, AmbiIntent, AmbiSource, AmbiContext, AmbiFallacy, AmbiRef).

**FR-03** — Sistem harus mengklasifikasikan setiap frasa ambigu ke dalam tipe yang tepat berdasarkan taksonomi.

**FR-04** — Jika tidak ada ambiguitas terdeteksi, sistem langsung meneruskan query ke Text-to-SQL tanpa interaksi tambahan.

**FR-05** — Sistem harus mempertimbangkan schema database KPI aktual (nama tabel, nama kolom, sample values) saat melakukan deteksi.

### 7.2 Modul Generasi Pertanyaan Klarifikasi (CQ)

**FR-06** — Untuk setiap ambiguitas yang terdeteksi, sistem harus menghasilkan satu pertanyaan klarifikasi yang spesifik dan kontekstual.

**FR-07** — Setiap pertanyaan klarifikasi harus disertai minimal 2 dan maksimal 5 opsi pilihan ganda yang relevan.

**FR-08** — Opsi untuk ambiguitas bertipe AmbiSchema dan AmbiValue harus menyertakan snippet data dari database aktual (nama kolom, contoh nilai).

**FR-09** — Opsi untuk ambiguitas bertipe AmbiRef harus menyertakan nilai konkret (misal: tanggal spesifik, bukan hanya deskripsi).

**FR-10** — Setiap pertanyaan klarifikasi harus menyediakan opsi "Lewati" (Abstain) dan "Lainnya" (Others) sebagai opsi default tambahan.

**FR-11** — Opsi "Lainnya" harus membuka input teks bebas untuk pengguna mengisi klarifikasi manual.

### 7.3 Modul Iterative Refinement

**FR-12** — Setelah pengguna menjawab semua pertanyaan klarifikasi, sistem harus menulis ulang query asli menjadi query yang lebih presisi.

**FR-13** — Query yang sudah ditulis ulang harus dijalankan kembali melalui modul deteksi untuk memastikan tidak ada ambiguitas baru yang muncul.

**FR-14** — Proses iterasi harus berlanjut hingga tidak ada ambiguitas tersisa, atau pengguna secara eksplisit memilih untuk melanjutkan tanpa resolusi penuh.

**FR-15** — Pengguna harus dapat menambahkan constraint tambahan (additional constraints) pada setiap iterasi (misal: "filter hanya untuk divisi aktif").

**FR-16** — Sistem harus memprioritaskan constraint tambahan dari pengguna di atas interpretasi default sistem.

### 7.4 Modul Preferensi Pengguna

**FR-17** — Sistem harus menyimpan preferensi klarifikasi pengguna dalam struktur berbasis taksonomi.

**FR-18** — Preferensi yang tersimpan harus digunakan untuk pre-filling opsi pada pertanyaan klarifikasi serupa di sesi berikutnya.

**FR-19** — Ketika jawaban baru dari pengguna berkonflik dengan preferensi tersimpan, sistem harus menggunakan preferensi terbaru.

**FR-20** — Pengguna harus dapat melihat dan menghapus preferensi tersimpan melalui pengaturan profil.

### 7.5 Log & Transparansi

**FR-21** — Sistem harus menyimpan log lengkap per sesi yang mencakup: query asli, ambiguitas yang terdeteksi, pertanyaan klarifikasi, jawaban pengguna, query hasil rewriting, dan SQL final.

**FR-22** — Pengguna harus dapat melihat perbandingan SQL yang dihasilkan sebelum dan sesudah proses ambiguity check.

**FR-23** — Sistem harus menampilkan "perbedaan yang terdeteksi" antara dua versi SQL secara visual (highlighted diff).

---

## 8. Non-Functional Requirements

### 8.1 Performa

**NFR-01** — Latency deteksi ambiguitas (dari submit query hingga pertanyaan klarifikasi pertama muncul) tidak boleh melebihi **5 detik** untuk query dengan panjang ≤ 200 karakter.

**NFR-02** — Waktu rewriting query setelah pengguna menjawab semua klarifikasi tidak boleh melebihi **3 detik**.

**NFR-03** — Sistem harus mendukung setidaknya **100 concurrent users** tanpa degradasi performa yang signifikan.

### 8.2 Akurasi

**NFR-04** — Precision deteksi ambiguitas (ambiguitas yang terdeteksi memang ambigu) harus ≥ **85%** pada dataset KPI internal.

**NFR-05** — Recall deteksi ambiguitas (ambiguitas nyata yang berhasil terdeteksi) harus ≥ **80%** pada dataset KPI internal.

**NFR-06** — Tingkat false positive (query tidak ambigu yang salah dideteksi sebagai ambigu) harus ≤ **15%**.

### 8.3 Keandalan & Availability

**NFR-07** — Sistem harus memiliki uptime ≥ **99.5%** pada jam operasional bisnis (08.00–20.00 WIB).

**NFR-08** — Jika modul ambiguity check mengalami kegagalan, sistem harus gracefully fallback ke Text-to-SQL tanpa ambiguity check dan menampilkan notifikasi kepada pengguna.

### 8.4 Keamanan

**NFR-09** — Query pengguna dan data KPI tidak boleh dikirim ke layanan LLM eksternal tanpa enkripsi (TLS 1.2+).

**NFR-10** — Schema database dan sample data yang dikirim ke LLM untuk konteks harus difilter untuk menghapus data PII (Personally Identifiable Information).

**NFR-11** — Log interaksi harus disimpan minimal 90 hari dan hanya dapat diakses oleh pengguna yang bersangkutan atau admin dengan otorisasi.

### 8.5 Usability

**NFR-12** — Pertanyaan klarifikasi harus menggunakan bahasa yang dapat dipahami oleh pengguna bisnis tanpa latar belakang teknis (tidak menggunakan istilah SQL seperti `JOIN`, `WHERE`, dll).

**NFR-13** — Antarmuka resolusi ambiguitas harus dapat diselesaikan dalam ≤ 3 klik/tindakan untuk kasus ambiguitas tunggal.

---

## 9. User Stories & Acceptance Criteria

### US-01 — Deteksi Otomatis Ambiguitas Schema

**Sebagai** seorang manajer sales yang ingin melihat performa timnya,  
**Saya ingin** sistem mendeteksi ketika query saya tidak jelas merujuk ke kolom mana,  
**Sehingga** SQL yang dihasilkan mengambil data dari kolom yang tepat.

**Acceptance Criteria:**

- [ ] Query _"tampilkan 5 sales terbaik bulan ini"_ memicu deteksi AmbiSchema
- [ ] Sistem menampilkan pertanyaan: _"'Terbaik' merujuk ke metrik apa?"_ dengan opsi seperti: `Total Revenue`, `Units Sold`, `Achievement %`, `Performance Score`, `Lainnya`
- [ ] Setelah pengguna memilih, query ditulis ulang secara eksplisit menyebutkan kolom yang dipilih
- [ ] SQL final menggunakan kolom yang sesuai dengan pilihan pengguna

---

### US-02 — Resolusi Ambiguitas Temporal

**Sebagai** seorang analis HR yang ingin melihat data evaluasi,  
**Saya ingin** sistem mengklarifikasi referensi waktu yang tidak spesifik,  
**Sehingga** data yang ditampilkan sesuai dengan periode yang dimaksud.

**Acceptance Criteria:**

- [ ] Query _"tampilkan evaluasi karyawan tahun lalu"_ memicu deteksi AmbiRef
- [ ] Sistem menampilkan pertanyaan: _"'Tahun lalu' merujuk ke periode mana?"_ dengan opsi: `Fiscal Year 2024 (Apr 2024–Mar 2025)`, `Calendar Year 2024 (Jan–Des 2024)`, `12 bulan terakhir dari hari ini`, `Lainnya`
- [ ] Query diperbarui dengan rentang tanggal eksplisit berdasarkan pilihan
- [ ] SQL menggunakan kondisi `WHERE` dengan tanggal konkret

---

### US-03 — Penanganan AmbiValue untuk Nilai Database

**Sebagai** seorang admin KPI yang ingin menarik data divisi tertentu,  
**Saya ingin** sistem mendeteksi ketika nama yang saya sebutkan tidak cocok dengan data di database,  
**Sehingga** query tidak mengembalikan hasil kosong.

**Acceptance Criteria:**

- [ ] Query _"tampilkan KPI divisi teknologi"_ memicu deteksi AmbiValue
- [ ] Sistem mencari nilai yang mirip di database dan menampilkan: _"'Teknologi' cocok dengan entri mana di database?"_ dengan opsi: `IT & Digital (kode: ITD)`, `Technology Development (kode: TECHDEV)`, `Lainnya`
- [ ] SQL menggunakan nilai eksak dari database sesuai pilihan pengguna

---

### US-04 — Iterasi Multi-Putaran

**Sebagai** pengguna yang mengirimkan query dengan beberapa frasa ambigu,  
**Saya ingin** sistem menyelesaikan semua ambiguitas secara bertahap,  
**Sehingga** SQL akhir benar-benar mencerminkan intent saya.

**Acceptance Criteria:**

- [ ] Sistem menampilkan semua pertanyaan klarifikasi untuk semua ambiguitas yang terdeteksi dalam satu tampilan
- [ ] Setelah pengguna menjawab, sistem melakukan re-check dan menampilkan ambiguitas tambahan jika ada
- [ ] Proses berhenti hanya ketika tidak ada ambiguitas tersisa
- [ ] Pengguna dapat melihat progress resolusi (misal: "2 dari 3 ambiguitas terselesaikan")

---

### US-05 — Bypass Klarifikasi dengan Abstain

**Sebagai** pengguna berpengalaman yang mengirimkan query kompleks,  
**Saya ingin** dapat melewati pertanyaan klarifikasi yang saya anggap tidak relevan,  
**Sehingga** saya tidak terbebani dengan pertanyaan yang tidak perlu.

**Acceptance Criteria:**

- [ ] Setiap pertanyaan klarifikasi menyediakan opsi "Lewati / Abstain"
- [ ] Ketika pengguna memilih Abstain, sistem melanjutkan tanpa resolusi untuk ambiguitas tersebut
- [ ] Sistem memberikan peringatan bahwa SQL yang dihasilkan mungkin tidak akurat untuk ambiguitas yang dilewati
- [ ] Pilihan Abstain dicatat sebagai feedback untuk perbaikan CQ di masa mendatang

---

### US-06 — Tambah Constraint Manual

**Sebagai** pengguna yang ingin mempersempit hasil query,  
**Saya ingin** dapat menambahkan kondisi tambahan selama proses klarifikasi,  
**Sehingga** SQL mencerminkan kebutuhan spesifik saya.

**Acceptance Criteria:**

- [ ] Panel klarifikasi menyediakan field "Constraint Tambahan" yang bisa diisi teks bebas
- [ ] Sistem memproses constraint tambahan dan mengintegrasikannya ke dalam query
- [ ] Jika constraint tambahan sendiri ambigu, sistem mendeteksi dan mengklarifikasi sebelum melanjutkan
- [ ] Constraint tambahan diutamakan di atas interpretasi default sistem

---

### US-07 — Perbandingan SQL Sebelum & Sesudah

**Sebagai** pengguna yang ingin memahami dampak klarifikasi,  
**Saya ingin** melihat perbedaan antara SQL tanpa klarifikasi dan SQL dengan klarifikasi,  
**Sehingga** saya dapat memvalidasi bahwa SQL sudah sesuai harapan.

**Acceptance Criteria:**

- [ ] Panel hasil menampilkan dua versi SQL secara berdampingan (side-by-side)
- [ ] Perbedaan antara dua versi SQL di-highlight secara visual
- [ ] Sistem menampilkan ringkasan perubahan dalam bahasa alami (misal: "Kolom 'revenue' diganti dengan 'achievement_pct', filter tanggal diperbarui ke '2024-01-01 s/d 2024-12-31'")
- [ ] Pengguna dapat memilih untuk menggunakan versi SQL mana yang akan dieksekusi

---

## 10. Desain UI/UX

### 10.1 Alur Pengguna (User Flow)

```
[Input Query]
      │
      ▼
[Loading: "Menganalisis query..."]
      │
      ├─── Tidak ada ambiguitas ──▶ [SQL Generation] ──▶ [Tampilan Hasil KPI]
      │
      └─── Ambiguitas ditemukan ──▶ [Panel Klarifikasi]
                                          │
                                          ▼
                                  [User Menjawab CQ]
                                          │
                                          ├─── Masih ada ambiguitas ──▶ [Panel Klarifikasi (iterasi)]
                                          │
                                          └─── Semua terselesaikan ──▶ [SQL Generation]
                                                                              │
                                                                              ▼
                                                                   [Tampilan Hasil KPI + SQL Diff]
```

### 10.2 Komponen Panel Klarifikasi

Panel klarifikasi menampilkan elemen-elemen berikut:

**Header:**

- Judul: "Klarifikasi Diperlukan"
- Indikator progress: "Ambiguitas 1 dari N terselesaikan"
- Badge tipe ambiguitas (misal: "Schema", "Temporal", "Nilai")

**Body (per ambiguitas):**

- Frasa yang ambigu di-highlight pada teks query asli
- Pertanyaan klarifikasi yang jelas dan kontekstual
- Opsi pilihan dalam bentuk radio button atau dropdown
- Snippet data dari database (jika relevan) untuk membantu pengguna memilih
- Input teks bebas (muncul saat pengguna memilih "Lainnya")

**Footer:**

- Field "Constraint Tambahan" (optional)
- Tombol "Submit Klarifikasi"
- Link "Lanjutkan Tanpa Klarifikasi" (dengan peringatan)

### 10.3 Prinsip UX

- **Non-technical language**: Semua teks menggunakan bahasa bisnis, bukan SQL.
- **Progressive disclosure**: Tampilkan satu atau beberapa ambiguitas dalam satu layar — hindari membanjiri pengguna.
- **Contextual hints**: Tampilkan contoh nilai nyata dari database untuk membantu pengguna membuat keputusan.
- **Undo-friendly**: Pengguna dapat kembali dan mengubah jawaban sebelum submit final.
- **Transparency**: Selalu tampilkan query asli dan query hasil rewriting agar pengguna dapat memvalidasi.

---

## 11. Data Requirements

### 11.1 Input Data

| Data                    | Sumber           | Format                         | Keterangan                                        |
| ----------------------- | ---------------- | ------------------------------ | ------------------------------------------------- |
| Natural language query  | User input       | String (≤ 500 karakter)        | Query dalam Bahasa Indonesia atau Inggris         |
| Database schema         | KPI DB           | JSON (tabel, kolom, tipe data) | Dikompilasi saat aplikasi start                   |
| Sample values per kolom | KPI DB           | JSON array                     | Maks 10 sample values per kolom untuk context LLM |
| User preference history | Preference Store | JSON                           | Preferensi klarifikasi sebelumnya                 |

### 11.2 Output Data

| Data                         | Tujuan             | Format                                            |
| ---------------------------- | ------------------ | ------------------------------------------------- |
| Identified ambiguous phrases | CQ Generator       | JSON array of {phrase, type, position}            |
| Clarification questions      | UI                 | JSON array of {question, options, ambiguity_type} |
| User answers                 | Query Rewriter     | JSON key-value                                    |
| Rewritten query              | Text-to-SQL Engine | String                                            |
| Interaction log              | Audit & Analytics  | JSON                                              |

### 11.3 Data Schema — Interaction Log

```json
{
  "session_id": "uuid",
  "user_id": "string",
  "timestamp": "ISO8601",
  "original_query": "string",
  "detected_ambiguities": [
    {
      "phrase": "string",
      "type": "AmbiSchema | AmbiValue | AmbiIntent | AmbiSource | AmbiContext | AmbiFallacy | AmbiRef",
      "position": { "start": 0, "end": 10 }
    }
  ],
  "clarification_rounds": [
    {
      "round": 1,
      "questions": [...],
      "answers": {...},
      "rewritten_query": "string"
    }
  ],
  "final_query": "string",
  "sql_without_ambisql": "string",
  "sql_with_ambisql": "string",
  "user_executed_version": "with | without | cancelled"
}
```

---

## 12. Integrasi & Dependensi

### 12.1 Integrasi Internal

| Sistem                        | Tipe Integrasi                 | Keterangan                                                          |
| ----------------------------- | ------------------------------ | ------------------------------------------------------------------- |
| Text-to-SQL Engine (existing) | API call                       | Ambiguity check adalah pre-processing step sebelum engine dipanggil |
| KPI Database                  | Read-only schema & sample data | Untuk konteks deteksi dan generasi CQ                               |
| User Management Service       | Auth token                     | Untuk identifikasi user dan akses preference store                  |
| Audit Log Service             | Event publish                  | Log setiap sesi ambiguity check                                     |

### 12.2 Integrasi Eksternal

| Layanan                                           | Fungsi                                                  | Catatan                                      |
| ------------------------------------------------- | ------------------------------------------------------- | -------------------------------------------- |
| LLM API (misal: OpenAI GPT-4 atau model internal) | Deteksi ambiguitas, klasifikasi, generasi CQ, rewriting | Semua data harus di-sanitize sebelum dikirim |

### 12.3 Dependensi Teknis

- **Backend**: Python 3.10+ (mengikuti referensi implementasi AmbiSQL)
- **Frontend**: React.js / Vue.js dengan komponen dropdown dan text input
- **Cache**: Redis untuk menyimpan preferensi user dan session state
- **Database preferensi**: PostgreSQL
- **LLM SDK**: OpenAI Python SDK atau ModelScope SDK (sesuai AmbiSQL reference)

---

## 13. Metrik Keberhasilan

### 13.1 Metrik Teknis

| Metrik                        | Definisi                                                 | Target    |
| ----------------------------- | -------------------------------------------------------- | --------- |
| Ambiguity Detection Precision | TP / (TP + FP)                                           | ≥ 85%     |
| Ambiguity Detection Recall    | TP / (TP + FN)                                           | ≥ 80%     |
| SQL Accuracy Improvement      | (Acc. with AmbiCheck - Acc. without) / Acc. without      | ≥ 30%     |
| Average CQ per Query          | Rata-rata jumlah pertanyaan klarifikasi per query ambigu | ≤ 3       |
| Latency P95 (detection)       | 95th percentile waktu deteksi                            | ≤ 5 detik |

### 13.2 Metrik Produk

| Metrik                      | Definisi                                       | Target              |
| --------------------------- | ---------------------------------------------- | ------------------- |
| Ambiguity Resolution Rate   | % sesi di mana pengguna menyelesaikan semua CQ | ≥ 75%               |
| Abstain Rate                | % CQ yang di-skip pengguna                     | ≤ 20%               |
| User Satisfaction Score     | Rating in-app post-interaction                 | ≥ 4.0 / 5.0         |
| Data Error Report Reduction | Penurunan laporan "data tidak sesuai"          | ≥ 40% dalam 3 bulan |
| Feature Adoption Rate       | % active users yang menggunakan fitur          | ≥ 60% dalam 2 bulan |

### 13.3 Monitoring & Alerting

- Alert ketika Ambiguity Detection False Positive Rate > 20% selama 1 jam
- Alert ketika latency P99 > 10 detik
- Dashboard harian menampilkan distribusi tipe ambiguitas yang paling sering terdeteksi
- Weekly report distribusi Abstain per tipe CQ (untuk memprioritaskan perbaikan CQ)

---

## 14. Risiko & Mitigasi

| ID   | Risiko                                                                          | Probabilitas | Dampak        | Mitigasi                                                                                                       |
| ---- | ------------------------------------------------------------------------------- | ------------ | ------------- | -------------------------------------------------------------------------------------------------------------- |
| R-01 | LLM menghasilkan CQ yang tidak relevan, membingungkan pengguna                  | Sedang       | Tinggi        | Evaluasi CQ quality dengan panel pengguna internal sebelum go-live; tambahkan opsi feedback per CQ             |
| R-02 | False positive tinggi menyebabkan friction berlebih pada query yang sudah jelas | Sedang       | Tinggi        | Set confidence threshold; hanya tampilkan CQ jika skor ambiguitas > threshold; A/B test threshold              |
| R-03 | Latency LLM tinggi di jam peak                                                  | Tinggi       | Sedang        | Implementasi caching untuk query serupa; async processing dengan streaming UI                                  |
| R-04 | Schema database KPI berubah tanpa sinkronisasi ke modul                         | Sedang       | Tinggi        | Schema refresh otomatis setiap 24 jam; webhook notifikasi jika ada DDL change                                  |
| R-05 | Pengguna tidak memahami pertanyaan klarifikasi meskipun sudah disederhanakan    | Rendah       | Sedang        | User testing dengan 5+ non-technical users sebelum launch; iterasi copy teks CQ                                |
| R-06 | Data sensitif KPI bocor ke LLM eksternal                                        | Rendah       | Sangat Tinggi | Review ketat data yang dikirim ke LLM; gunakan model internal/on-premise jika tersedia; data masking untuk PII |
| R-07 | Pengguna bypass klarifikasi terlalu sering, mengurangi manfaat fitur            | Sedang       | Sedang        | Analisis pola Abstain; perbaiki CQ yang sering di-skip; edukasi pengguna tentang manfaat klarifikasi           |

---

## 15. Rencana Implementasi

### 15.1 Milestone & Timeline

| Fase                              | Durasi   | Deliverable                                                                                        |
| --------------------------------- | -------- | -------------------------------------------------------------------------------------------------- |
| **Fase 0 — Discovery**            | 2 minggu | Inventarisasi query KPI historis; identifikasi pola ambiguitas umum; mapping schema database       |
| **Fase 1 — Core Detection**       | 3 minggu | Implementasi Ambiguity Detection + Taxonomy Classifier; unit test dengan 50+ query KPI sample      |
| **Fase 2 — CQ Generation**        | 2 minggu | Implementasi CQ Generator dengan integrasi schema; evaluasi kualitas CQ dengan user panel internal |
| **Fase 3 — Iterative Refinement** | 3 minggu | Implementasi Query Rewriter + Re-checker + Preference Store; integration test end-to-end           |
| **Fase 4 — UI Integration**       | 2 minggu | Implementasi komponen UI Panel Klarifikasi; SQL diff view; user testing dengan 10 pengguna         |
| **Fase 5 — Pilot**                | 2 minggu | Deploy ke subset pengguna (20%); monitoring metrik; iterasi berdasarkan feedback                   |
| **Fase 6 — Full Launch**          | 1 minggu | Rollout ke semua pengguna; dokumentasi; training material                                          |

**Total estimasi: ±15 minggu**

### 15.2 Definition of Done (per Fase)

**Fase 1 selesai jika:**

- Precision ≥ 85% dan Recall ≥ 80% pada test set internal 50 query
- False positive rate ≤ 15%
- Unit tests coverage ≥ 80%

**Fase 3 selesai jika:**

- End-to-end test: query ambigu → klarifikasi → SQL akurat, pass rate ≥ 90%
- Re-check tidak mendeteksi ambiguitas baru pada 95% query hasil rewriting

**Fase 4 selesai jika:**

- 5 dari 5 user test participants dapat menyelesaikan sesi klarifikasi tanpa bantuan
- Semua US (User Stories) Acceptance Criteria terpenuhi

---

## 16. Glosarium

| Istilah                     | Definisi                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| Text-to-SQL                 | Proses mengubah pertanyaan bahasa alami menjadi query SQL                                   |
| Ambiguitas                  | Kondisi di mana sebuah frasa atau query dapat diinterpretasikan dengan lebih dari satu cara |
| Taksonomi Ambiguitas        | Klasifikasi terstruktur dari tipe-tipe ambiguitas berdasarkan AmbiSQL                       |
| CQ (Clarification Question) | Pertanyaan yang dihasilkan sistem untuk mengklarifikasi intent pengguna                     |
| Intent                      | Tujuan atau maksud yang sebenarnya dari pengguna ketika mengirimkan query                   |
| Schema                      | Struktur database yang mendefinisikan tabel, kolom, dan relasi antar keduanya               |
| In-context Learning         | Teknik LLM di mana contoh-contoh disertakan dalam prompt untuk memandu output               |
| False Positive              | Query yang tidak ambigu namun salah terdeteksi sebagai ambigu oleh sistem                   |
| Rewriting                   | Proses penulisan ulang query bahasa alami menjadi versi yang lebih presisi                  |
| Preference Store            | Penyimpanan preferensi klarifikasi pengguna untuk digunakan pada sesi berikutnya            |
| AmbiSQL                     | Sistem referensi dari paper SIGMOD'26 yang menjadi dasar implementasi fitur ini             |
| KPI                         | Key Performance Indicator — metrik yang digunakan untuk mengukur performa bisnis/karyawan   |

---

## Appendix A — Contoh Prompt Deteksi Ambiguitas

Berikut adalah contoh struktur prompt yang diadaptasi dari AmbiSQL untuk konteks KPI:

```
Kamu adalah sistem deteksi ambiguitas untuk platform KPI.

Schema database KPI:
- tabel employees: id, name, department_id, join_date, status
- tabel kpi_scores: id, employee_id, metric_type, score, period, recorded_at
- tabel departments: id, name, region, manager_id

Tipe ambiguitas yang harus dideteksi:
1. AmbiSchema: frasa yang bisa merujuk ke lebih dari satu tabel/kolom
2. AmbiValue: nilai yang tidak cocok dengan data aktual di database
3. AmbiIntent: operasi SQL yang tidak jelas (sort vs group vs filter)
4. AmbiRef: referensi temporal/spasial yang tidak spesifik

Contoh:
Query: "Siapa karyawan terbaik tahun ini?"
Ambiguitas:
- "terbaik" → AmbiSchema (score? achievement_pct? ranking?)
- "tahun ini" → AmbiRef (calendar year? fiscal year? 12 bulan terakhir?)

Sekarang analisis query berikut dan identifikasi semua frasa ambigu beserta tipenya:
Query: "{user_query}"
Database sample values: {schema_with_samples}

Respond dalam format JSON.
```

---

## Appendix B — Mapping Tipe Ambiguitas ke Strategi CQ

| Tipe Ambiguitas | Strategi CQ                                      | Sumber Opsi                                      |
| --------------- | ------------------------------------------------ | ------------------------------------------------ |
| AmbiSchema      | "Metrik/kolom mana yang dimaksud?"               | Nama kolom dari schema + deskripsi bisnis        |
| AmbiValue       | "Entri mana yang cocok?"                         | Fuzzy-match hasil dari database aktual           |
| AmbiIntent      | "Operasi apa yang diinginkan?"                   | Template pilihan: urutkan / kelompokkan / filter |
| AmbiSource      | "Data dari database atau perhitungan eksternal?" | Binary choice + penjelasan implikasi             |
| AmbiContext     | "Berikan konteks tambahan"                       | Free-text + contoh format                        |
| AmbiFallacy     | "Data ini mungkin tidak tersedia, lanjutkan?"    | Konfirmasi + alternatif query                    |
| AmbiRef         | "Periode/lokasi mana yang dimaksud?"             | Nilai konkret dari kalender/data lokasi          |

---

_Dokumen ini merupakan living document dan akan diperbarui seiring perkembangan implementasi dan feedback dari stakeholder._

**Referensi Utama:**

- Ding et al. (2026). _AmbiSQL: Interactive Ambiguity Detection and Resolution for Text-to-SQL._ SIGMOD-Companion '26.
- Repository: [https://github.com/JustinzjDing/AmbiSQL](https://github.com/JustinzjDing/AmbiSQL)

