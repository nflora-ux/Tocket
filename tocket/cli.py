#!/usr/bin/env python3

import sys
import os
import time
import traceback
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse
import inquirer
from inquirer.themes import GreenPassion
from rich.table import Table
from rich import box
from rich.prompt import Confirm, Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from rich.panel import Panel

from .constants import VERSION, APPNAME
from .db import ConfigDB
from .utils import (
    clear_screen, print_header, read_binary_file,
    display_error, display_success, display_warning, console
)
from .github_api import GitHubClient

ASCII_ART = r"""
TTTTTTTTTT  OOOOO  CCCCC K   K EEEEE TTTTTTTTTT
    TT     O     O C     K  K  E         TT
    TT     O     O C     KKK   EEEE      TT
    TT     O     O C     K  K  E         TT
    TT      OOOOO  CCCCC K   K EEEEE     TT
"""

repo_cache: Dict[str, Tuple[float, list]] = {}
CACHE_TTL = 50

def ensure_db() -> ConfigDB:
    return ConfigDB()

def mask_token(tok: str) -> str:
    if not tok:
        return ""
    if len(tok) <= 8:
        return tok[:2] + "..." + tok[-2:]
    return tok[:4] + "..." + tok[-4:]

def _parse_github_url(url_or_repo: str) -> Tuple[Optional[str], Optional[str]]:
    if not url_or_repo:
        return None, None
    s = url_or_repo.strip()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            p = urlparse(s)
            parts = p.path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
            if len(parts) == 1:
                return parts[0], None
        except Exception:
            return None, None
    if "/" in s:
        parts = s.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    return None, s

def get_repo_default_branch(gh: GitHubClient, owner: str, repo: str) -> Optional[str]:
    try:
        if hasattr(gh, "get_default_branch"):
            b = gh.get_default_branch(owner, repo)
            if b:
                return b
    except Exception:
        pass
    try:
        if hasattr(gh, "get_repo"):
            data = gh.get_repo(owner, repo)
            if data and data.get("default_branch"):
                return data.get("default_branch")
    except Exception:
        pass
    for b in ("main", "master"):
        try:
            r = gh.session.get(f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{b}", timeout=10)
            if r.status_code == 200:
                return b
        except Exception:
            continue
    return None

def login_flow(db: ConfigDB) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    pwd_salt = db.get_kv("pwd_salt")
    password: Optional[str] = None

    if pwd_salt:
        questions = [
            inquirer.Password('pwd', message="Masukkan kata sandi lokal"),
        ]
        attempts = 0
        while attempts < 3:
            answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if answers is None:
                display_warning("Pembatalan input kata sandi.")
                return None, None, None
            pwd = answers['pwd']
            if db.verify_password(pwd):
                password = pwd
                break
            else:
                display_error("Kata sandi yang dimasukkan salah!")
                attempts += 1
        if attempts >= 3 and password is None:
            display_error("Batas percobaan tercapai. Aplikasi akan ditutup!")
            sys.exit(1)
    else:
        display_warning("Tidak ada kata sandi lokal. Anda dapat membuatnya di menu Pengaturan nanti.")

    token: Optional[str] = None
    label: Optional[str] = None

    if db.get_kv("tok_cipher"):
        if password is None:
            display_warning("Token terenkripsi ditemukan, tetapi tidak ada kata sandi. Masukkan kata sandi terlebih dahulu.")
            questions = [
                inquirer.Password('pwd', message="Masukkan kata sandi lokal"),
            ]
            answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if answers is None:
                return None, None, None
            pwd = answers['pwd']
            if not db.verify_password(pwd):
                display_error("Kata sandi salah.")
                return None, None, None
            password = pwd
        token = db.load_token_decrypted(password)
        if token is None:
            display_error("Gagal mendekripsi token. Kemungkinan kata sandi berbeda. Anda dapat mereset token di Pengaturan.")
        else:
            label = db.get_kv("tok_label")
            display_success(f"Token tersedia untuk label: {label or '(tanpa label)'}")
    else:
        while True:
            questions = [
                inquirer.Text('token', message="Masukkan token klasik GitHub (kosongkan untuk lanjut tanpa token)"),
            ]
            answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if answers is None:
                token = None
                break
            t = answers['token'].strip()
            if not t:
                token = None
                break
            try:
                gh = GitHubClient(t)
                info = gh.validate_token()
            except Exception as e:
                display_error(f"Gagal memvalidasi token: {e}")
                continue

            if info:
                display_success(f"Token valid! Nama pengguna: {info['username']}. Scopes: {info['scopes']}")
                questions = [
                    inquirer.Text('label', message="Nama atau catatan untuk token (opsional)"),
                ]
                label_ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
                label = label_ans['label'].strip() if label_ans else ""

                if not db.get_kv("pwd_salt"):
                    questions = [
                        inquirer.Confirm('create_pwd', message="Ingin membuat kata sandi untuk mengenkripsi token?", default=False),
                    ]
                    pwd_ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
                    if pwd_ans and pwd_ans['create_pwd']:
                        questions = [
                            inquirer.Password('pwd', message="Buat kata sandi baru"),
                        ]
                        pwd2_ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
                        if pwd2_ans:
                            pwd = pwd2_ans['pwd']
                            db.set_password(pwd)
                            db.store_token_encrypted(t, pwd)
                            if label:
                                db.set_kv("tok_label", label)
                            db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                            display_success("Token tersimpan dan terenkripsi.")
                            token = t
                            break
                    else:
                        questions = [
                            inquirer.Confirm('session', message="Simpan token hanya untuk sesi ini (tidak disimpan permanen)?", default=False),
                        ]
                        sess_ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
                        if sess_ans and sess_ans['session']:
                            token = t
                            break
                        else:
                            continue
                else:
                    questions = [
                        inquirer.Password('pwd', message="Masukkan kata sandi lokal untuk mengenkripsi token"),
                    ]
                    pwd_ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
                    if pwd_ans and pwd_ans['pwd'] and db.verify_password(pwd_ans['pwd']):
                        db.store_token_encrypted(t, pwd_ans['pwd'])
                        if label:
                            db.set_kv("tok_label", label)
                        db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                        display_success("Token tersimpan dan terenkripsi.")
                        token = t
                        break
                    else:
                        display_error("Kata sandi tidak cocok. Token tidak disimpan.")
                        token = t
                        break
            else:
                display_error("Token tidak valid. Silakan coba lagi.")
                continue
    return password, token, label

def show_help():
    clear_screen()
    console.print(Panel.fit(
        "[bold cyan]PANDUAN PENGGUNAAN TOCKET[/bold cyan]",
        border_style="cyan"
    ))
    help_text = """
[bold]1. Mendapatkan Token Klasik GitHub[/bold]
   - Kunjungi: https://github.com/settings/tokens
   - Klik "Generate new token (classic)"
   - Beri nama token, misal "Tocket"
   - Pilih scopes yang diperlukan:
        • repo (untuk akses penuh ke repositori)
        • delete_repo (jika ingin menghapus repositori)
        • admin:public_key (jika ingin mengelola kunci SSH)
        • workflow (jika ingin memicu GitHub Actions)
   - Klik "Generate token" dan salin token yang muncul (token hanya ditampilkan sekali).

[bold]2. Penyimpanan Token[/bold]
   Token Anda disimpan secara terenkripsi di basis data lokal:
   {db_path}
   Data tidak pernah dikirim ke server lain selain API GitHub.
   Anda dapat mengatur kata sandi untuk mengenkripsi token di menu Pengaturan.

[bold]3. Fitur Utama[/bold]
   • Buat repositori baru dengan opsi README, .gitignore, dan lisensi.
   • Lihat daftar repositori (dengan filter dan cache).
   • Kelola repositori: upload file, hapus, rename, update konten, ubah visibilitas, dll.
   • Upload semua file dalam folder (tanpa subfolder) atau seluruh folder beserta subfolder.
   • Update file repositori dengan konten dari file lokal.
   • Hapus folder beserta isinya.
   • Picu GitHub Actions workflow secara manual.
   • Pengaturan token dan kata sandi lokal.

[bold]4. Privasi dan Keamanan[/bold]
   • Token disimpan terenkripsi dengan AES-GCM, kunci diturunkan dari kata sandi Anda.
   • Basis data terletak di direktori home Anda, hanya dapat diakses oleh pengguna Anda.
   • Koneksi ke GitHub menggunakan HTTPS.
   • Jika Anda lupa kata sandi, token tidak dapat dipulihkan; Anda harus membuat token baru.

[bold]5. Lisensi[/bold]
   Tocket dirilis di bawah lisensi MIT. Lihat file LICENSE untuk informasi lebih lanjut.
"""
    console.print(help_text.format(db_path=Path.home() / f".{APPNAME.lower()}" / "tocket.db"))
    console.print("\n[dim]Tekan Enter untuk kembali ke menu...[/dim]")
    input()

def main_menu_loop(db: ConfigDB, gh_client: Optional[GitHubClient], username: str, password: Optional[str]):
    while True:
        clear_screen()
        print_header(ASCII_ART, VERSION, username or "anonymous")
        questions = [
            inquirer.List('action',
                          message=f"{username}@Tocket $ Pilih aksi",
                          choices=[
                              ('Buat Repositori', '1'),
                              ('List Repositori', '2'),
                              ('Setup Repositori', '3'),
                              ('Hapus Repositori', '4'),
                              ('Pengaturan', '5'),
                              ('Panduan & Privasi', '6'),
                              ('Keluar', '7'),
                          ],
                          carousel=True)
        ]
        try:
            answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if answers is None:
                continue
            choice = answers['action']
        except KeyboardInterrupt:
            print("\n")
            continue

        if choice == '1':
            create_repo_flow(db, gh_client, username, password)
        elif choice == '2':
            list_repos_flow(db, gh_client)
        elif choice == '3':
            setup_repo_flow(db, gh_client, username, password)
        elif choice == '4':
            delete_repo_flow(db, gh_client, username)
        elif choice == '5':
            settings_flow(db, gh_client, password)
        elif choice == '6':
            show_help()
        elif choice == '7':
            display_success("Sampai jumpa!")
            break

def create_repo_flow(db: ConfigDB, gh: Optional[GitHubClient], username: str, password: Optional[str]):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk membuat repositori. Tambahkan token di Pengaturan.")
            input("\nTekan Enter untuk kembali...")
            return

        questions = [
            inquirer.Text('name', message="Nama repositori", validate=lambda _, x: x.strip() != ""),
            inquirer.Text('desc', message="Deskripsi (opsional)"),
            inquirer.Confirm('private', message="Buat repositori privat?", default=False),
            inquirer.Confirm('readme', message="Tambahkan README?", default=True),
            inquirer.Confirm('gitignore', message="Tambahkan .gitignore?", default=False),
            inquirer.Confirm('license', message="Tambahkan Lisensi?", default=False),
        ]
        answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
        if answers is None:
            return

        name = answers['name'].strip()
        desc = answers['desc'].strip()
        private = answers['private']
        auto_init = answers['readme']

        gi_template = None
        if answers['gitignore']:
            try:
                templates = gh.get_gitignore_templates()
                table = Table(title="Template .gitignore", box=box.ROUNDED)
                table.add_column("No", justify="right", style="cyan")
                table.add_column("Nama", style="white")
                for i, t in enumerate(templates[:60], 1):
                    table.add_row(str(i), t)
                console.print(table)
                choices = [(t, t) for t in templates[:60]]
                q = inquirer.List('gi', message="Pilih template .gitignore", choices=choices, carousel=True)
                gi_ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
                if gi_ans:
                    gi_template = gi_ans['gi']
            except Exception as e:
                display_error(f"Gagal mengambil template .gitignore: {e}")

        lic_template = None
        if answers['license']:
            try:
                licenses = gh.get_license_templates()
                table = Table(title="Template Lisensi", box=box.ROUNDED)
                table.add_column("No", justify="right", style="cyan")
                table.add_column("Kunci", style="white")
                table.add_column("Nama", style="white")
                for i, l in enumerate(licenses[:30], 1):
                    table.add_row(str(i), l.get('key'), l.get('name'))
                console.print(table)
                choices = [(f"{l.get('key')} - {l.get('name')}", l.get('key')) for l in licenses[:30]]
                q = inquirer.List('lic', message="Pilih template lisensi", choices=choices, carousel=True)
                lic_ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
                if lic_ans:
                    lic_template = lic_ans['lic']
            except Exception as e:
                display_error(f"Gagal mengambil template lisensi: {e}")

        repo = gh.create_repo(name=name, description=desc, private=private,
                              auto_init=auto_init, gitignore_template=gi_template,
                              license_template=lic_template)
        db.add_history("create_repo", repo.get("full_name"))
        display_success(f"Repositori dibuat: {repo.get('html_url')}")
    except Exception as e:
        display_error(f"Gagal membuat repositori: {e}")
        if "token" in str(e).lower():
            display_warning("Pastikan token memiliki lingkup 'repo'.")
    finally:
        input("\nTekan Enter untuk kembali ke menu...")

def list_repos_flow(db: ConfigDB, gh: Optional[GitHubClient]):
    try:
        gh_local = gh
        repos = None
        owner = None

        if gh_local and getattr(gh_local, "token", None):
            try:
                cache_key = f"user_{gh_local.token[:10]}"
                now = time.time()
                if cache_key in repo_cache and (now - repo_cache[cache_key][0]) < CACHE_TTL:
                    repos = repo_cache[cache_key][1]
                    display_success("Menggunakan cache.")
                else:
                    repos = gh_local.list_repos()
                    repo_cache[cache_key] = (now, repos)
            except Exception as e:
                display_error(f"Gagal mengambil repositori dengan token saat ini: {e}")
                if "401" in str(e) or "unauthorized" in str(e).lower() or "invalid" in str(e).lower():
                    if Confirm.ask("Token tidak valid/kadaluarsa. Ingin memasukkan token baru sekarang?"):
                        new_tok = Prompt.ask("Masukkan token klasik GitHub", default="")
                        if not new_tok:
                            display_warning("Pembatalan memasukkan token baru.")
                            return
                        tmp = GitHubClient(new_tok.strip())
                        try:
                            info = tmp.validate_token()
                        except Exception as e2:
                            display_error(f"Token baru tidak valid: {e2}")
                            return
                        label = Prompt.ask("Nama atau catatan untuk token (opsional)", default="")
                        if db.get_kv("pwd_salt"):
                            pwd = Prompt.ask("Masukkan kata sandi lokal untuk mengenkripsi token", password=True) if Confirm.ask("Enkripsi token dengan kata sandi?") else None
                            if pwd and db.verify_password(pwd):
                                db.store_token_encrypted(new_tok.strip(), pwd)
                                db.set_kv("tok_label", label or "")
                                db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                                display_success("Token tersimpan dan terenkripsi.")
                        else:
                            if Confirm.ask("Ingin membuat kata sandi untuk mengenkripsi token sekarang? (disarankan)"):
                                pwd = Prompt.ask("Buat kata sandi baru", password=True)
                                if pwd:
                                    db.set_password(pwd)
                                    db.store_token_encrypted(new_tok.strip(), pwd)
                                    db.set_kv("tok_label", label or "")
                                    db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                                    display_success("Token tersimpan dan terenkripsi.")
                        try:
                            repos = tmp.list_repos()
                            gh_local = tmp
                        except Exception as e2:
                            display_error(f"Gagal mengambil repositori dengan token baru: {e2}")
                            return
                else:
                    display_error(f"Gagal mengambil repositori: {e}")
                    return

        if repos is None:
            display_warning("Tidak ada token autentikasi. Anda dapat memasukkan token untuk melihat semua repositori (termasuk privat), atau melihat repositori publik dari nama pengguna.")
            if Confirm.ask("Ingin memasukkan token sekarang?"):
                t = Prompt.ask("Masukkan token klasik GitHub", default="")
                if not t:
                    display_warning("Dibatalkan.")
                    return
                tmp = GitHubClient(t.strip())
                try:
                    info = tmp.validate_token()
                except Exception as e:
                    display_error(f"Token tidak valid: {e}")
                    return
                label = Prompt.ask("Nama atau catatan untuk token (opsional)", default="")
                if db.get_kv("pwd_salt"):
                    pwd = Prompt.ask("Masukkan kata sandi lokal untuk mengenkripsi token", password=True) if Confirm.ask("Enkripsi token dengan kata sandi?") else None
                    if pwd and db.verify_password(pwd):
                        db.store_token_encrypted(t.strip(), pwd)
                        db.set_kv("tok_label", label or "")
                        db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                        display_success("Token tersimpan dan terenkripsi.")
                else:
                    if Confirm.ask("Ingin membuat kata sandi untuk mengenkripsi token sekarang? (disarankan)"):
                        pwd = Prompt.ask("Buat kata sandi baru", password=True)
                        if pwd:
                            db.set_password(pwd)
                            db.store_token_encrypted(t.strip(), pwd)
                            db.set_kv("tok_label", label or "")
                            db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                            display_success("Token tersimpan dan terenkripsi.")
                gh_local = tmp
                try:
                    repos = gh_local.list_repos()
                except Exception as e:
                    display_error(f"Gagal mengambil repositori dengan token: {e}")
                    return
            else:
                user = Prompt.ask("Masukkan nama pengguna GitHub untuk melihat repositori publik (kosong untuk batal)", default="")
                if not user:
                    return
                try:
                    gh_public = GitHubClient()
                    repos = gh_public.list_user_public_repos(user)
                except Exception as e:
                    display_error(f"Gagal mengambil repositori publik untuk {user}: {e}")
                    return

        if not repos:
            display_warning("Tidak ada repositori untuk ditampilkan. Coba buat repositori baru atau periksa token/nama pengguna Anda.")
            return

        table = Table(title="My Repository's", box=box.SIMPLE)
        table.add_column("No", justify="right", style="cyan")
        table.add_column("Repositori", style="white", no_wrap=True)
        table.add_column("Visibilitas", justify="center")
        table.add_column("Branch", justify="center")

        for idx, r in enumerate(repos, 1):
            name = r.get("name") or r.get("full_name") or str(r.get("html_url") or "")
            visibility = "privat" if r.get("private") else "publik"
            branch = r.get("default_branch")
            if not branch:
                try:
                    if gh_local and hasattr(gh_local, "get_default_branch"):
                        branch = gh_local.get_default_branch(r.get("owner", {}).get("login") or "", r.get("name") or "")
                    elif gh_local and hasattr(gh_local, "get_repo"):
                        repo_meta = gh_local.get_repo(r.get("owner", {}).get("login") or "", r.get("name") or "")
                        branch = repo_meta.get("default_branch")
                except Exception:
                    branch = "-"
            table.add_row(str(idx), name, visibility, branch or "-")

        console.print(table)

        if Confirm.ask("Ingin mencari repositori berdasarkan nama?", default=False):
            filter_text = Prompt.ask("Masukkan nama repositori").lower()
            filtered = [(i, r) for i, r in enumerate(repos, 1) if filter_text in r.get("name", "").lower()]
            if filtered:
                console.print("[bold]Hasil pencarian:[/bold]")
                for idx, r in filtered:
                    console.print(f"{idx}. {r.get('name')}")
            else:
                display_warning("Tidak dapat menemukan repositori yang cocok!")

    except Exception as e:
        display_error(f"Gagal mengambil daftar repositori: {e}")
        traceback.print_exc()
    finally:
        input("\nTekan Enter untuk kembali ke menu...")

def delete_repo_flow(db: ConfigDB, gh: Optional[GitHubClient], username: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token dengan scopes `repo` untuk menghapus repositori. Tambahkan token di Pengaturan!")
            input("\nTekan Enter...")
            return

        questions = [
            inquirer.Text('name', message=f"Nama repositori (https://github.com/{username}/[nama])"),
            inquirer.Confirm('confirm', message="Yakin ingin menghapus repositori ini? Tindakan ini tidak dapat dibatalkan.", default=False),
        ]
        answers = inquirer.prompt(questions, raise_keyboard_interrupt=True)
        if answers is None or not answers['confirm']:
            display_warning("Dibatalkan.")
            return

        name = answers['name'].strip()
        gh.delete_repo(username, name)
        db.add_history("delete_repo", f"{username}/{name}")
        display_success("Repositori berhasil dihapus!")
    except Exception as e:
        display_error(f"Gagal menghapus repositori: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def setup_repo_flow(db: ConfigDB, gh: Optional[GitHubClient], username: str, password: Optional[str]):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk mengelola repositori. Tambahkan token di Pengaturan.")
            input("\nTekan Enter...")
            return

        questions = [
            inquirer.Text('repo', message=f"Nama repositori (https://github.com/{username}/[nama])"),
        ]
        ans = inquirer.prompt(questions, raise_keyboard_interrupt=True)
        if ans is None:
            return
        repo_name = ans['repo'].strip()
        if not repo_name:
            return

        try:
            found = False
            repos = gh.list_repos()
            found = any(r.get("name") == repo_name for r in repos)
            if not found:
                display_error("Repositori tidak dapat ditemukan di akun Anda!")
                return
        except Exception as e:
            display_error(f"Gagal memeriksa repositori: {e}")
            return

        branch = get_repo_default_branch(gh, username, repo_name) or "main"
        if Confirm.ask(f"Menggunakan cabang default '{branch}'. Ingin mengganti cabang?", default=False):
            branch = Prompt.ask("Masukkan nama cabang", default=branch)

        while True:
            console.print(f"\n[bold cyan]Setup Repositori: {username}/{repo_name} (branch: {branch})[/bold cyan]")
            menu_choices = [
                ('Upload file', '1'),
                ('Hapus file', '2'),
                ('Rename file/folder', '3'),
                ('List file', '4'),
                ('Update file', '5'),
                ('Ubah visibilitas', '6'),
                ('Ubah .gitignore', '7'),
                ('Ubah Lisensi', '8'),
                ('Hapus folder', '9'),
                ('Trigger GitHub Actions', '10'),
                ('Upload folder', '11'),
                ('Kembali', '0'),
            ]
            q = inquirer.List('opt', message="Pilih opsi", choices=menu_choices, carousel=True)
            opt_ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
            if opt_ans is None:
                return
            opt = opt_ans['opt']
            if opt == '1':
                upload_file_flow(db, gh, username, repo_name, branch)
            elif opt == '2':
                delete_file_flow(db, gh, username, repo_name, branch)
            elif opt == '3':
                rename_file_or_folder_flow(db, gh, username, repo_name, branch)
            elif opt == '4':
                list_files_flow(db, gh, username, repo_name, branch)
            elif opt == '5':
                update_file_flow(db, gh, username, repo_name, branch)
            elif opt == '6':
                change_visibility_flow(db, gh, username, repo_name)
            elif opt == '7':
                change_gitignore_flow(db, gh, username, repo_name, branch)
            elif opt == '8':
                change_license_flow(db, gh, username, repo_name, branch)
            elif opt == '9':
                delete_folder_flow(db, gh, username, repo_name, branch)
            elif opt == '10':
                trigger_workflow_flow(db, gh, username, repo_name, branch)
            elif opt == '11':
                upload_folder_flow(db, gh, username, repo_name, branch)
            elif opt == '0':
                break
    except Exception as e:
        display_error(f"Gagal setup repositori: {e}")
    finally:
        input("\nTekan Enter untuk kembali ke menu...")

def display_directory(path: Path):
    files = list(path.iterdir())
    table = Table(title=f"Isi folder: {path}", box=box.ROUNDED)
    table.add_column("No", justify="right", style="cyan")
    table.add_column("Nama", style="white")
    table.add_column("Tipe", justify="center")
    table.add_column("Ukuran", justify="right")
    for idx, p in enumerate(files, start=1):
        nama = p.name
        tipe = "DIR" if p.is_dir() else "FILE"
        ukuran = ""
        if p.is_file():
            size = p.stat().st_size
            if size < 1024:
                ukuran = f"{size} B"
            elif size < 1024**2:
                ukuran = f"{size/1024:.1f} KB"
            else:
                ukuran = f"{size/1024**2:.1f} MB"
        else:
            ukuran = "-"
        table.add_row(str(idx), nama, tipe, ukuran)
    console.print(table)
    console.print("[dim]0: .. (folder sebelumnya)[/dim]")
    console.print("[dim]all: Upload semua file di folder ini (tanpa subfolder)[/dim]")
    console.print("[dim]subfolder: Upload seluruh folder ini beserta subfolder (rekursif)[/dim]")
    console.print("[dim]q: batal[/dim]")

def pick_local_file() -> Optional[Path]:
    start_path = Prompt.ask("Mulai path file (kosong = direktori saat ini)", default=".")
    current = Path(start_path).expanduser().resolve()
    while True:
        display_directory(current)
        sel = Prompt.ask("Pilih nomor / ketik nama file (atau 'q' untuk batal)", default="")
        if sel.lower() == 'q':
            return None
        if sel == "":
            fname = Prompt.ask("Masukkan nama file di folder ini (atau path lengkap)")
            if not fname:
                continue
            path = Path(fname)
            if not path.is_absolute():
                path = current / path
            if not path.exists() or not path.is_file():
                display_error("File tidak dapat ditemukan.")
                continue
            return path
        else:
            try:
                idx = int(sel)
                if idx == 0:
                    if current.parent == current:
                        display_warning("Sudah berada di dalam root.")
                    else:
                        current = current.parent
                else:
                    files = list(current.iterdir())
                    if 1 <= idx <= len(files):
                        chosen = files[idx - 1]
                        if chosen.is_dir():
                            current = chosen
                        else:
                            return chosen
                    else:
                        display_error("Input tidak valid!")
            except ValueError:
                display_error("Input tidak dikenali.")

def pick_local_folder() -> Optional[Path]:
    start_path = Prompt.ask("Mulai path folder (kosong = direktori saat ini)", default=".")
    current = Path(start_path).expanduser().resolve()
    while True:
        display_directory(current)
        sel = Prompt.ask("Pilih nomor folder (atau 'q' untuk batal)", default="")
        if sel.lower() == 'q':
            return None
        try:
            idx = int(sel)
            if idx == 0:
                if current.parent == current:
                    display_warning("Sudah berada di dalam root.")
                else:
                    current = current.parent
            else:
                files = list(current.iterdir())
                if 1 <= idx <= len(files):
                    chosen = files[idx - 1]
                    if chosen.is_dir():
                        return chosen
                    else:
                        display_error("Pilihan bukan folder. Silakan pilih nomor folder.")
                else:
                    display_error("Input tidak valid!")
        except ValueError:
            display_error("Input tidak dikenali. Masukkan nomor folder.")

def upload_file_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk meng-upload file.")
            return

        start_path = Prompt.ask("Mulai path file (kosong = direktori saat ini)", default=".")
        current = Path(start_path).expanduser().resolve()

        while True:
            display_directory(current)
            sel = Prompt.ask("Pilih nomor / ketik nama file (atau 'q' untuk batal)", default="")
            if sel.lower() == 'q':
                return
            if sel.lower() == 'all':
                if not Confirm.ask("Upload semua file di folder ini tanpa subfolder?"):
                    continue
                repo_path = Prompt.ask("Simpan path di repositori (kosong = root, atau folder/ diakhiri '/' untuk folder)", default="")
                try:
                    branch = get_repo_default_branch(gh, owner, repo) or Prompt.ask("Masukkan branch target", default="main")
                except Exception as e:
                    display_error(f"Gagal mendapatkan branch default: {e}")
                    continue
                files_to_upload = [p for p in current.iterdir() if p.is_file()]
                if not files_to_upload:
                    display_warning("Tidak ada file di folder ini.")
                    continue
                success = 0
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn()) as progress:
                    task = progress.add_task("[cyan]Mengupload file...", total=len(files_to_upload))
                    for p in files_to_upload:
                        target = (repo_path.strip() + p.name) if repo_path.strip() else p.name
                        try:
                            content = read_binary_file(str(p))
                            gh.create_or_update_file(owner, repo, target, content, message=f"Tocket: upload {target}", branch=branch)
                            success += 1
                            progress.update(task, advance=1, description=f"[green]Upload {p.name} sukses")
                        except Exception as e:
                            display_error(f"Gagal upload {p.name}: {e}")
                            if not Confirm.ask("Lanjutkan upload file berikutnya?"):
                                break
                display_success(f"Upload selesai: {success} dari {len(files_to_upload)} file berhasil.")
                input("\nTekan Enter untuk kembali...")
                return
            if sel.lower() == 'subfolder':
                if not Confirm.ask(f"Upload seluruh folder {current.name} beserta subfolder ke repositori?"):
                    continue
                repo_path = Prompt.ask("Simpan path di repositori (kosong = root, atau folder/ diakhiri '/' untuk folder)", default="")
                try:
                    branch = get_repo_default_branch(gh, owner, repo) or Prompt.ask("Masukkan branch target", default="main")
                except Exception as e:
                    display_error(f"Gagal mendapatkan branch default: {e}")
                    continue
                all_files = []
                for root, dirs, files in os.walk(current):
                    root_path = Path(root)
                    for file in files:
                        full_path = root_path / file
                        rel_path = full_path.relative_to(current)
                        all_files.append((full_path, rel_path))
                if not all_files:
                    display_warning("Tidak ada file di folder ini.")
                    continue
                success = 0
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn()) as progress:
                    task = progress.add_task("[cyan]Mengupload file...", total=len(all_files))
                    for full_path, rel_path in all_files:
                        if repo_path.strip():
                            target = repo_path.strip().rstrip('/') + '/' + rel_path.as_posix()
                        else:
                            target = rel_path.as_posix()
                        try:
                            content = read_binary_file(str(full_path))
                            gh.create_or_update_file(owner, repo, target, content, message=f"Tocket: upload {target}", branch=branch)
                            success += 1
                            progress.update(task, advance=1, description=f"[green]Upload {rel_path} sukses")
                        except Exception as e:
                            display_error(f"Gagal upload {rel_path}: {e}")
                            if not Confirm.ask("Lanjutkan upload file berikutnya?"):
                                break
                display_success(f"Upload selesai: {success} dari {len(all_files)} file berhasil.")
                input("\nTekan Enter untuk kembali...")
                return
            if sel == "":
                fname = Prompt.ask("Masukkan nama file di folder ini (atau path lengkap)")
                if not fname:
                    continue
                path = Path(fname)
                if not path.is_absolute():
                    path = current / path
                if not path.exists() or not path.is_file():
                    display_error("File tidak ditemukan.")
                    continue
                if path.stat().st_size > 100 * 1024 * 1024:
                    display_error("File terlalu besar untuk di-upload via GitHub Contents API (>100MB).")
                    continue
                repo_path = Prompt.ask("Simpan path di repositori (kosong = root, atau folder/ diakhiri '/' untuk folder)", default="")
                target_path = (repo_path.strip() + path.name) if repo_path.strip() else path.name
                try:
                    try:
                        branch = get_repo_default_branch(gh, owner, repo) or Prompt.ask("Masukkan branch target", default="main")
                    except Exception as e:
                        display_error(f"Gagal mendapatkan branch default: {e}")
                        continue
                    content = read_binary_file(str(path))
                    gh.create_or_update_file(owner, repo, target_path, content, message=f"Tocket: upload {target_path}", branch=branch)
                    db.add_history("upload_file", f"{owner}/{repo}/{target_path}")
                    display_success(f"Upload sukses: {target_path}")
                    return
                except Exception as e:
                    display_error(f"Gagal upload: {e}")
                    continue
            else:
                try:
                    idx = int(sel)
                    if idx == 0:
                        if current.parent == current:
                            display_warning("Sudah berada di root.")
                        else:
                            current = current.parent
                    else:
                        files = list(current.iterdir())
                        if 1 <= idx <= len(files):
                            chosen = files[idx - 1]
                            if chosen.is_dir():
                                current = chosen
                            else:
                                path = chosen
                                if path.stat().st_size > 100 * 1024 * 1024:
                                    display_error("File terlalu besar.")
                                    return
                                repo_path = Prompt.ask("Simpan path di repositori (kosong = root)", default="")
                                target_path = (repo_path.strip() + path.name) if repo_path.strip() else path.name
                                try:
                                    branch = get_repo_default_branch(gh, owner, repo) or Prompt.ask("Masukkan branch target", default="main")
                                except Exception as e:
                                    display_error(f"Gagal mendapatkan branch default: {e}")
                                    continue
                                content = read_binary_file(str(path))
                                gh.create_or_update_file(owner, repo, target_path, content, message=f"Tocket: upload {target_path}", branch=branch)
                                db.add_history("upload_file", f"{owner}/{repo}/{target_path}")
                                display_success(f"Upload sukses: {target_path}")
                                return
                        else:
                            display_error("Nomor tidak valid.")
                except ValueError:
                    display_error("Input tidak dikenali.")
    except Exception as e:
        display_error(f"Terjadi kesalahan saat upload: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def upload_folder_flow(db: ConfigDB, gh: GitHubClient, owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk meng-upload folder.")
            return

        folder_path = pick_local_folder()
        if folder_path is None:
            display_warning("Batal memilih folder.")
            return

        repo_path = Prompt.ask("Simpan path di repositori (kosong = root, atau folder/ diakhiri '/' untuk folder)", default="")
        try:
            branch = get_repo_default_branch(gh, owner, repo) or Prompt.ask("Masukkan branch target", default="main")
        except Exception as e:
            display_error(f"Gagal mendapatkan branch default: {e}")
            return

        all_files = []
        for root, dirs, files in os.walk(folder_path):
            root_path = Path(root)
            for file in files:
                full_path = root_path / file
                rel_path = full_path.relative_to(folder_path)
                all_files.append((full_path, rel_path))

        if not all_files:
            display_warning("Folder kosong. Tidak ada file untuk diupload.")
            return

        if not Confirm.ask(f"Upload folder {folder_path.name} dan seluruh isinya ({len(all_files)} file) ke repositori?"):
            display_warning("Dibatalkan.")
            return

        success = 0
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TaskProgressColumn()) as progress:
            task = progress.add_task("[cyan]Mengupload file...", total=len(all_files))
            for full_path, rel_path in all_files:
                if repo_path.strip():
                    target = repo_path.strip().rstrip('/') + '/' + rel_path.as_posix()
                else:
                    target = rel_path.as_posix()
                try:
                    content = read_binary_file(str(full_path))
                    gh.create_or_update_file(owner, repo, target, content, message=f"Tocket: upload {target}", branch=branch)
                    success += 1
                    progress.update(task, advance=1, description=f"[green]Upload {rel_path} sukses")
                except Exception as e:
                    display_error(f"Gagal upload {rel_path}: {e}")
                    if not Confirm.ask("Lanjutkan upload file berikutnya?"):
                        break
        display_success(f"Upload folder selesai: {success} dari {len(all_files)} file berhasil.")
    except Exception as e:
        display_error(f"Terjadi kesalahan saat upload folder: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def delete_file_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk menghapus file.")
            return
        fname = Prompt.ask("Masukkan nama file (path relatif di repositori) untuk dihapus")
        if not fname:
            return
        if not Confirm.ask(f"Yakin ingin menghapus file {fname}?"):
            display_warning("Dibatalkan.")
            return
        gh.delete_file(owner, repo, fname, message=f"Tocket: delete {fname}", branch=branch)
        db.add_history("delete_file", f"{owner}/{repo}/{fname}")
        display_success("File dihapus.")
    except FileNotFoundError as e:
        display_error(str(e))
    except Exception as e:
        display_error(f"Gagal menghapus file: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def list_files_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        client = gh or GitHubClient()
        tree = client.list_repo_tree(owner, repo, branch=branch)
        table = Table(title=f"File di {owner}/{repo} (cabang={branch})", box=box.MINIMAL)
        table.add_column("Path")
        table.add_column("Tipe")
        table.add_column("Ukuran")
        for t in tree:
            table.add_row(t.get("path", ""), t.get("type", ""), str(t.get("size", "-")))
        console.print(table)
    except Exception as e:
        display_error(f"Gagal mengambil daftar file: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def change_visibility_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk mengubah visibilitas.")
            return
        q = inquirer.List('vis', message="Pilih visibilitas", choices=['public', 'private'], carousel=True)
        ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
        if ans is None:
            return
        vis = ans['vis']
        payload = {"private": (vis == "private")}
        gh.patch_repo(owner, repo, payload)
        db.add_history("change_visibility", f"{owner}/{repo} -> {vis}")
        display_success("Visibilitas berhasil diubah.")
    except Exception as e:
        display_error(f"Gagal mengubah visibilitas: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def rename_file_or_folder_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk mengganti nama file/folder.")
            return
        src = Prompt.ask("Masukkan nama file/folder yang ingin diganti nama (path relatif di repositori)")
        if not src:
            return
        dest = Prompt.ask("Masukkan nama baru untuk file/folder (path relatif di repositori)")
        if not dest:
            return
        tree = gh.list_repo_tree(owner, repo, branch=branch)
        src = src.rstrip("/")
        dest = dest.rstrip("/")
        to_move = [item for item in tree if item.get("path") == src or item.get("path", "").startswith(src + "/")]
        if not to_move:
            display_error(f"{src} tidak ditemukan di {owner}/{repo}")
            return
        for item in to_move:
            if item.get("type") != "blob":
                continue
            old_path = item.get("path")
            if old_path == src:
                new_path = dest
            else:
                suffix = old_path[len(src) + 1:]
                new_path = dest + "/" + suffix if suffix else dest
            contents = gh.get_contents(owner, repo, old_path, ref=branch)
            if not contents:
                continue
            if contents.get("content"):
                import base64
                data = base64.b64decode(contents.get("content"))
            else:
                dl = gh.session.get(contents.get("download_url"))
                data = dl.content
            gh.create_or_update_file(owner, repo, new_path, data, message=f"Tocket: move {old_path} -> {new_path}", branch=branch)
            gh.delete_file(owner, repo, old_path, message=f"Tocket: delete {old_path} (moved)", branch=branch)
            db.add_history("rename_move", f"{owner}/{repo}/{old_path} -> {new_path}")
        display_success("Penggantian nama/pemindahan selesai.")
    except Exception as e:
        display_error(f"Gagal mengganti nama/memindahkan: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def change_gitignore_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk mengubah .gitignore.")
            return
        templates = gh.get_gitignore_templates()
        table = Table(title="Template .gitignore", box=box.ROUNDED)
        table.add_column("No", justify="right", style="cyan")
        table.add_column("Nama", style="white")
        for i, t in enumerate(templates[:100], 1):
            table.add_row(str(i), t)
        console.print(table)
        choices = [(t, t) for t in templates[:100]]
        q = inquirer.List('tmpl', message="Pilih template .gitignore (atau pilih custom)", choices=choices + [('(custom)', 'custom')], carousel=True)
        ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
        if ans is None:
            return
        chosen = ans['tmpl']
        chosen_content = None
        if chosen == 'custom':
            chosen_content = Prompt.ask("Masukkan isi .gitignore (enter untuk batal)", default="")
            if not chosen_content:
                display_warning("Tidak ada isi.")
                return
        else:
            r = gh.session.get(f"https://api.github.com/gitignore/templates/{chosen}")
            if r.status_code == 200:
                chosen_content = r.json().get("source")
        if not chosen_content:
            display_error("Gagal mengambil template.")
            return
        gh.create_or_update_file(owner, repo, ".gitignore", chosen_content.encode("utf-8"), message="Tocket: update .gitignore", branch=branch)
        db.add_history("update_gitignore", f"{owner}/{repo}")
        display_success(".gitignore diperbarui.")
    except Exception as e:
        display_error(f"Gagal memperbarui .gitignore: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def change_license_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk mengubah lisensi.")
            return
        licenses = gh.get_license_templates()
        table = Table(title="Template Lisensi", box=box.ROUNDED)
        table.add_column("No", justify="right", style="cyan")
        table.add_column("Kunci", style="white")
        table.add_column("Nama", style="white")
        for i, l in enumerate(licenses[:60], 1):
            table.add_row(str(i), l.get('key'), l.get('name'))
        console.print(table)
        choices = [(f"{l.get('key')} - {l.get('name')}", l.get('key')) for l in licenses[:60]]
        q = inquirer.List('lic', message="Pilih template lisensi", choices=choices + [('(custom)', 'custom')], carousel=True)
        ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
        if ans is None:
            return
        chosen = ans['lic']
        content = None
        if chosen == 'custom':
            content = Prompt.ask("Masukkan isi lisensi (enter untuk batal)", default="")
            if not content:
                display_warning("Tidak ada isi.")
                return
        else:
            r = gh.session.get(f"https://api.github.com/licenses/{chosen}")
            if r.status_code == 200:
                content = r.json().get("body")
        if not content:
            display_error("Gagal mengambil template.")
            return
        gh.create_or_update_file(owner, repo, "LICENSE", content.encode("utf-8"), message="Tocket: update LICENSE", branch=branch)
        db.add_history("update_license", f"{owner}/{repo}")
        display_success("Lisensi diperbarui.")
    except Exception as e:
        display_error(f"Gagal memperbarui lisensi: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def delete_folder_flow(db: ConfigDB, gh: Optional[GitHubClient], owner: str, repo: str, branch: str):
    try:
        if gh is None or gh.token is None:
            display_error("Diperlukan token untuk menghapus folder.")
            return
        folder = Prompt.ask("Masukkan nama folder yang ingin dihapus (path relatif di repositori)")
        if not folder:
            return
        if not Confirm.ask(f"Yakin ingin menghapus folder {folder} dan seluruh isinya?"):
            display_warning("Dibatalkan.")
            return
        tree = gh.list_repo_tree(owner, repo, branch=branch)
        to_delete = [t for t in tree if t.get("path") == folder or t.get("path", "").startswith(folder.rstrip("/") + "/")]
        for item in sorted(to_delete, key=lambda x: x.get("path"), reverse=True):
            if item.get("type") != "blob":
                continue
            path = item.get("path")
            gh.delete_file(owner, repo, path, message=f"Tocket: delete {path}", branch=branch)
            db.add_history("delete_file", f"{owner}/{repo}/{path}")
        display_success("Folder dan isinya dihapus.")
    except Exception as e:
        display_error(f"Gagal menghapus folder: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def update_file_flow(db: ConfigDB, gh: GitHubClient, owner: str, repo: str, branch: str):
    try:
        tree = gh.list_repo_tree(owner, repo, branch=branch)
        files = [item for item in tree if item.get("type") == "blob"]
        if not files:
            display_warning("Tidak ada file di repositori ini.")
            return

        choices = [(f['path'], f) for f in files]
        q_file = inquirer.List('file', message="Pilih file yang akan diperbarui", choices=choices, carousel=True)
        ans_file = inquirer.prompt([q_file], raise_keyboard_interrupt=True)
        if ans_file is None:
            return
        selected_file = ans_file['file']
        repo_path = selected_file['path']

        local_path = pick_local_file()
        if local_path is None:
            display_warning("Batal memilih file lokal.")
            return

        if not Confirm.ask(f"Perbarui file {repo_path} dengan isi dari {local_path.name}?"):
            display_warning("Dibatalkan.")
            return

        with open(local_path, 'rb') as f:
            new_content = f.read()

        gh.create_or_update_file(owner, repo, repo_path, new_content,
                                 message=f"Tocket: update {repo_path} dengan konten dari {local_path.name}",
                                 branch=branch)
        db.add_history("update_file", f"{owner}/{repo}/{repo_path}")
        display_success(f"File {repo_path} berhasil diperbarui.")
    except Exception as e:
        display_error(f"Gagal memperbarui file: {e}")
    finally:
        input("\nTekan Enter untuk kembali...")

def trigger_workflow_flow(db: ConfigDB, gh: GitHubClient, owner: str, repo: str, branch: str):
    try:
        workflows = gh.list_workflows(owner, repo)
        if not workflows:
            display_warning("Tidak ditemukan workflow di repositori ini.")
            return

        workflow_choices = [(f"{w['name']} ({w['path']})", w) for w in workflows]
        q_workflow = inquirer.List('workflow', message="Pilih workflow yang akan dijalankan", choices=workflow_choices, carousel=True)
        ans_workflow = inquirer.prompt([q_workflow], raise_keyboard_interrupt=True)
        if ans_workflow is None:
            return
        selected_workflow = ans_workflow['workflow']
        workflow_id = selected_workflow['id']

        target_branch = Prompt.ask("Masukkan cabang target", default=branch)

        if not Confirm.ask(f"Jalankan workflow {selected_workflow['name']} pada cabang {target_branch}?"):
            display_warning("Dibatalkan.")
            return

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("[cyan]Memicu workflow...", total=None)
            gh.trigger_workflow(owner, repo, workflow_id, target_branch)
            progress.update(task, description="[green]Workflow berhasil dipicu!")

        db.add_history("trigger_workflow", f"{owner}/{repo} - {selected_workflow['name']} on {target_branch}")
        display_success("Workflow berhasil dipicu. Lihat status di https://github.com/{owner}/{repo}/actions")
    except Exception as e:
        display_error(f"Gagal memicu workflow: {e}")
        if "workflow" in str(e).lower():
            display_warning("Pastikan token memiliki scope 'workflow'.")
    finally:
        input("\nTekan Enter untuk kembali...")

def settings_flow(db: ConfigDB, gh: Optional[GitHubClient], password: Optional[str]):
    try:
        while True:
            console.print("\n[bold cyan]Pengaturan[/bold cyan]")
            menu_choices = [
                ('Tampilkan Token Klasik', '1'),
                ('Ubah token klasik', '2'),
                ('Hapus token klasik', '3'),
                ('Ubah kata sandi', '4'),
                ('Hapus kata sandi', '5'),
                ('Buat kata sandi', '7'),
                ('Kembali', '6'),
            ]
            q = inquirer.List('opt', message="Pilih opsi", choices=menu_choices, carousel=True)
            ans = inquirer.prompt([q], raise_keyboard_interrupt=True)
            if ans is None:
                return
            opt = ans['opt']

            if opt == '1':
                cipher = db.get_kv("tok_cipher")
                if not cipher:
                    display_warning("Tidak ada token tersimpan.")
                else:
                    label = db.get_kv("tok_label") or "(tanpa label)"
                    scopes_db = db.get_kv("tok_scopes") or ""
                    if not password:
                        pwd_q = inquirer.Password('pwd', message="Masukkan kata sandi untuk dekripsi token")
                        pwd_ans = inquirer.prompt([pwd_q], raise_keyboard_interrupt=True)
                        if not pwd_ans or not db.verify_password(pwd_ans['pwd']):
                            display_error("Kata sandi salah.")
                            continue
                        token = db.load_token_decrypted(pwd_ans['pwd'])
                    else:
                        token = db.load_token_decrypted(password)
                    if token:
                        masked = mask_token(token)
                        console.print(f"Label: {label}")
                        console.print(f"Token: {masked}")
                        console.print(f"Scopes: {scopes_db}")
                        if Confirm.ask("Tampilkan token penuh?"):
                            console.print(f"Token: {token}")
                    else:
                        display_error("Gagal mendekripsi token.")
            elif opt == '2':
                t = Prompt.ask("Masukkan token klasik GitHub (kosong untuk batal)", default="")
                if not t:
                    continue
                tmp_client = GitHubClient(t)
                try:
                    info = tmp_client.validate_token()
                except Exception as e:
                    display_error(f"Token tidak valid: {e}")
                    continue
                label = Prompt.ask("Nama atau catatan token (opsional)", default="")
                if not password:
                    pwd_q = inquirer.Password('pwd', message="Masukkan kata sandi lokal untuk mengenkripsi token")
                    pwd_ans = inquirer.prompt([pwd_q], raise_keyboard_interrupt=True)
                    if not pwd_ans or not db.verify_password(pwd_ans['pwd']):
                        display_error("Kata sandi salah. Token tidak disimpan.")
                        continue
                    db.store_token_encrypted(t, pwd_ans['pwd'])
                else:
                    db.store_token_encrypted(t, password)
                if label:
                    db.set_kv("tok_label", label)
                db.set_kv("tok_scopes", ",".join(info.get("scopes") or []))
                display_success("Token tersimpan.")
            elif opt == '3':
                if Confirm.ask("Yakin ingin menghapus token klasik dari penyimpanan?"):
                    db.clear_token()
                    db.delete_kv("tok_label")
                    db.delete_kv("tok_scopes")
                    display_success("Token dihapus dari basis data.")
            elif opt == '4':
                if not db.get_kv("pwd_salt"):
                    display_warning("Belum ada kata sandi. Gunakan 'Buat kata sandi'.")
                    continue
                current_q = inquirer.Password('current', message="Masukkan kata sandi saat ini")
                current_ans = inquirer.prompt([current_q], raise_keyboard_interrupt=True)
                if not current_ans or not db.verify_password(current_ans['current']):
                    display_error("Kata sandi salah.")
                    continue
                new_q = inquirer.Password('new', message="Masukkan kata sandi baru")
                new_ans = inquirer.prompt([new_q], raise_keyboard_interrupt=True)
                if not new_ans or not new_ans['new']:
                    display_warning("Dibatalkan.")
                    continue
                token_val = db.load_token_decrypted(current_ans['current'])
                db.set_password(new_ans['new'])
                if token_val:
                    db.store_token_encrypted(token_val, new_ans['new'])
                display_success("Kata sandi diubah dan token dienkripsi ulang.")
            elif opt == '5':
                if Confirm.ask("Yakin ingin menghapus kata sandi lokal? Ini juga akan menghapus token terenkripsi."):
                    db.clear_password()
                    db.clear_token()
                    db.delete_kv("tok_label")
                    db.delete_kv("tok_scopes")
                    display_success("Kata sandi dan token dihapus dari penyimpanan.")
            elif opt == '7':
                if db.get_kv("pwd_salt"):
                    display_warning("Kata sandi sudah ada. Gunakan 'Ubah kata sandi'.")
                    continue
                new_q = inquirer.Password('new', message="Buat kata sandi baru")
                new_ans = inquirer.prompt([new_q], raise_keyboard_interrupt=True)
                if not new_ans or not new_ans['new']:
                    display_warning("Dibatalkan.")
                    continue
                db.set_password(new_ans['new'])
                display_success("Kata sandi berhasil dibuat.")
            elif opt == '6':
                break
    except KeyboardInterrupt:
        display_warning("Dibatalkan.")
    finally:
        input("\nTekan Enter untuk kembali ke menu...")

def main():
    db = ensure_db()
    pwd, token, label = login_flow(db)
    gh_client: Optional[GitHubClient] = None
    username = "anonymous"
    if token:
        try:
            gh_client = GitHubClient(token)
            info = gh_client.validate_token()
            if info:
                username = info.get("username") or username
            else:
                display_warning("Token tidak valid saat masuk awal.")
                gh_client = None
        except Exception as e:
            display_error(f"Gagal memvalidasi token saat startup: {e}")
            gh_client = None
    else:
        display_warning("Beberapa fitur memerlukan token. Anda dapat menggunakan fitur terbatas tanpa token.")

    try:
        main_menu_loop(db, gh_client, username, pwd)
    finally:
        db.close()

if __name__ == "__main__":
    main()