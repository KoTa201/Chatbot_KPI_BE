# Database Schema & Relasi

---

## Tabel Baru (Perlu Diimplementasikan)

### 1. `ChatSession`

| Kolom          | Tipe           | Keterangan       |
|----------------|----------------|------------------|
| `session_id`   | VARCHAR(255)   | Primary Key (U)  |
| `session_name` | VARCHAR(255)   |                  |
| `start_at`     | TIMESTAMP      |                  |
| `end_at`       | TIMESTAMP      |                  |
| `user_id`      | VARCHAR(255)   | FK → `User`      |
| `chatbot_id`   | VARCHAR(255)   | FK → `Chatbot`   |

---

### 2. `ChatMessage`

| Kolom             | Tipe         | Keterangan            |
|-------------------|--------------|-----------------------|
| `message_id`      | VARCHAR(255) | Primary Key (U)       |
| `message`         | VARCHAR(255) |                       |
| `isSenderChatbot` | TINYINT(1)   | 0 = User, 1 = Chatbot |
| `send_at`         | TIMESTAMP    |                       |
| `session_id`      | VARCHAR(255) | FK → `ChatSession`    |

---

### 3. `clarificationQuestion`

| Kolom                      | Tipe         | Keterangan          |
|----------------------------|--------------|---------------------|
| `clarification_question_id`| VARCHAR(255) | Primary Key (U)     |
| `ambiguous_phrase`         | VARCHAR(255) |                     |
| `ambiguity_type`           | VARCHAR(20)  |                     |
| `clarification_question`   | VARCHAR(255) |                     |
| `answer_options`           | VARCHAR(255) |                     |
| `user_answer`              | INTEGER(10)  |                     |
| `created_at`               | TIMESTAMP    |                     |
| `message_id`               | VARCHAR(255) | FK → `ChatMessage`  |

---

## Tabel Sudah Ada (Referensi)

- `User` — sudah diimplementasikan
- `Chatbot` — sudah diimplementasikan

---

## Relasi Antar Tabel

| Dari                    | Ke               | Tipe Relasi  | Keterangan                                            |
|-------------------------|------------------|--------------|-------------------------------------------------------|
| `User`                  | `ChatSession`    | One-to-Many  | Satu user dapat memiliki banyak sesi chat             |
| `Chatbot`               | `ChatSession`    | One-to-One   | Satu sesi chat terhubung ke tepat satu chatbot        |
| `ChatSession`           | `ChatMessage`    | One-to-Many  | Satu sesi berisi banyak pesan                         |
| `ChatMessage`           | `clarificationQuestion` | One-to-Many | Satu pesan dapat menghasilkan banyak pertanyaan klarifikasi |

---

## Diagram Relasi (Teks)

```
User ──────────────< ChatSession >────────────── Chatbot
                          │
                          │ (one-to-many)
                          ▼
                     ChatMessage
                          │
                          │ (one-to-many)
                          ▼
               clarificationQuestion
```

---

## Catatan

- Simbol **`U`** pada ERD menandakan kolom bersifat **Unique**.
- Semua primary key menggunakan tipe `VARCHAR(255)` — pertimbangkan menggunakan `UUID` atau `BIGINT AUTO_INCREMENT` untuk performa query yang lebih baik.
- Kolom `answer_options` bertipe `VARCHAR(255)` — jika menyimpan multiple option, pertimbangkan menggunakan tipe `JSON` atau tabel terpisah.
