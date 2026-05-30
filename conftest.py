import sys
import os
import pytest
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


def _wait_for_fresh_html_report(html_path: str, run_started_at_ns: int, timeout_seconds: int = 20) -> bool:
    """Wait until report HTML is updated by the current test run and file write is stable."""
    deadline = time.time() + timeout_seconds
    last_snapshot = None
    stable_checks = 0

    while time.time() < deadline:
        if os.path.exists(html_path):
            stat = os.stat(html_path)
            snapshot = (stat.st_mtime_ns, stat.st_size)

            if stat.st_mtime_ns >= run_started_at_ns and stat.st_size > 0:
                if snapshot == last_snapshot:
                    stable_checks += 1
                else:
                    last_snapshot = snapshot
                    stable_checks = 0

                if stable_checks >= 2:
                    return True

        time.sleep(0.2)

    return False


def pytest_html_report_title(report):
    report.title = "Laporan Hasil Testing"


# ✅ Simpan deskripsi sebelum report dibuat
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__).strip() \
        if item.function.__doc__ else "-"


# ✅ Tambah header kolom Deskripsi
def pytest_html_results_table_header(cells):
    cells.insert(2, "<th>Deskripsi</th>")


# ✅ Tambah isi kolom Deskripsi — dengan fallback aman
def pytest_html_results_table_row(report, cells):
    description = getattr(report, "description", "-")
    cells.insert(2, f"<td>{description}</td>")


def pytest_sessionstart(session):
    # Store current run start time so we can detect a fresh report file.
    session._report_run_started_at_ns = time.time_ns()


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_sessionfinish(session, exitstatus):
    yield

    base_dir = os.path.abspath(os.path.dirname(__file__))
    reports_dir = os.path.join(base_dir, "reports")
    html_path = os.path.abspath(os.path.join(reports_dir, "report.html"))
    pdf_path = os.path.abspath(os.path.join(reports_dir, "report.pdf"))
    run_started_at_ns = getattr(session, "_report_run_started_at_ns", 0)

    try:
        if not os.path.exists(html_path):
            print(f"\n[WARN] File HTML tidak ditemukan di: {html_path}")
            return

        report_is_fresh = _wait_for_fresh_html_report(
            html_path=html_path,
            run_started_at_ns=run_started_at_ns,
        )
        if not report_is_fresh:
            print(
                "\n[WARN] Report HTML belum terdeteksi sebagai file terbaru; lanjut konversi dengan file yang ada.")

        print("\n[INFO] Mengkonversi laporan HTML ke PDF via Playwright...")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            # Add cache buster to ensure we always load the latest report contents.
            report_url = Path(html_path).resolve().as_uri()
            page.goto(f"{report_url}?ts={time.time_ns()}",
                      wait_until="networkidle")

            # Tunggu tabel benar-benar terisi (JS selesai render)
            page.wait_for_selector("tbody tr", timeout=10000)

            # Ekspor ke PDF
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "1cm", "bottom": "1cm",
                        "left": "1cm", "right": "1cm"}
            )
            browser.close()

        print(f"[SUCCESS] Laporan PDF berhasil disimpan di: {pdf_path}")

    except Exception as e:
        print(f"\n[ERROR] Gagal konversi PDF. Error: {e}")
