# Tocket

**Tocket** adalah *command-line interface* modern, aman, dan terstruktur untuk mengelola repositori GitHub langsung dari terminal.  
Dirancang untuk **Developer** yang hidup di terminal, males buka browser, tapi tetap mengutamakan **keamanan**, **kecepatan**, dan **alur kerja yang bersih**.

---

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13%2B-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-green" />
  <img src="https://img.shields.io/badge/CLI-Terminal--Native-black" />
  <img src="https://img.shields.io/github/stars/nflora-ux/Tocket?style=social" />
</p>

---

## Kenapa harus Tocket?

GitHub memiliki antarmuka web yang kuat, tetapi tidak dirancang untuk alur kerja cepat di terminal.  
Tocket hadir untuk menjawab kebutuhan sederhana:

- **Bekerja tanpa keluar terminal** – semua operasi GitHub dari satu tempat.
- **Token tidak pernah disimpan dalam bentuk teks biasa** – keamanan adalah prioritas.
- **Antarmuka informatif namun tidak berlebihan** – fokus pada informasi yang penting.
- **Alur kerja yang jelas dan dapat diprediksi** – setiap langkah terstruktur.

Tocket bukan sekadar pembungkus API. Ini adalah alat yang memiliki pendapat tentang bagaimana seharusnya *workflow* GitHub di terminal.

---

## Fitur Utama

### Manajemen Repositori
- Membuat repositori baru dengan opsi README, `.gitignore`, dan lisensi.
- Melihat daftar repositori (milik sendiri atau publik milik pengguna lain).
- Menghapus repositori.
- Mengubah visibilitas (publik ↔ privat).

### Operasi Berkas (GitHub Contents API)
- Mengunggah satu berkas atau seluruh isi folder (dengan subfolder atau tanpa subfolder).
- Memperbarui konten berkas yang sudah ada di repositori dengan konten dari berkas lokal.
- Menghapus berkas.
- Mengganti nama berkas atau folder (termasuk memindahkan isi folder).
- Menampilkan pohon direktori repositori.
- Menghapus folder beserta seluruh isinya (rekursif).

### Keamanan Prioritas Utama
- Token GitHub **dienkripsi menggunakan AES‑GCM**.
- Kunci enkripsi diturunkan dari kata sandi lokal melalui **PBKDF2‑HMAC‑SHA256**.
- Tidak ada token dalam bentuk teks biasa yang disimpan di disk.
- **Tidak ada pemulihan kata sandi palsu** – jika lupa kata sandi, token tidak dapat dipulihkan (keputusan desain untuk keamanan maksimal).

### Pengalaman Pengguna & CLI
- Antarmuka terminal berbasis **Rich** dengan warna dan tata letak yang nyaman.
- Menu utama dengan format dua kolom yang konsisten.
- Navigasi folder interaktif untuk memilih berkas lokal.
- *Progress bar* saat mengunggah banyak berkas.
- *Cache* daftar repositori (5 menit) untuk mempercepat akses berulang.
- Pemilihan cabang (*branch*) sebelum melakukan operasi berkas.

---

## Persyaratan Sistem

- Python **3.14 atau lebih baru** (direkomendasikan).
- Sistem operasi: Linux, Windows (Terminal / CMD), MacOS.

### Dependensi Utama
| Paket | Keterangan |
|-------|------------|
| `rich` | Tampilan terminal |
| `requests` | Komunikasi dengan API GitHub |
| `cryptography` | Enkripsi token |
| `inquirer` | Dialog interaktif |
| `prompt_toolkit` | (Opsional) |

---

## Instalasi

```bash
# Clone repositori
git clone https://github.com/neveerlabs/Tocket.git
cd Tocket

# Buat virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate    # Windows

# Pasang dependensi
pip install -r requirements.txt

# Jalankan aplikasi
python3 main.py
```

## Cara mendapatkan Token Classic Github:
  1. Buka GitHub Settings > Tokens (classic).
  2. Klik Generate new token (classic).
  3. Beri nama token, misalnya "Tocket".
  4. Pilih scopes yang diperlukan:
  5. repo – akses penuh ke repositori (termasuk privat).
  6. delete_repo – jika ingin menghapus repositori.
  7. admin:public_key – jika diperlukan untuk mengelola kunci SSH.
  8. Klik Generate token.
  9. Salin token yang muncul.

## Mulai cepat:
Saat pertama kali menjalankan Tocket:
  1. Anda akan diminta kata sandi lokal (opsional, tetapi sangat disarankan untuk keamanan token).
  2. Masukkan token classic GitHub.
  3. Token akan divalidasi dan dienkripsi secara otomatis.

## Menu Utama
```bash
Buat Repositori       Hapus Repositori
Lihat Repositori      Pengaturan
Setup Repositori      Keluar
```
> *Gunakan tombol panah untuk memilih, lalu Enter untuk konfirmasi.*

