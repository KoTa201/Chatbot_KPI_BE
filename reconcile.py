"""
reconcile.py — Reconciliation completeness check for Google Sheets → PostgreSQL ingestion.

Tujuan: memvalidasi KELENGKAPAN data setelah ingestion. Tidak ada objek bisnis
yang hilang (ada di sheet, tak ada di DB) atau ilegal (ada di DB, tak ada di sheet).

Prinsip "fresh code": ekstraksi identitas di sini DITULIS ULANG secara independen
dan TIDAK mengimpor utils/helper/parser/* maupun service ingestion — itulah kode
yang sedang diuji. GoogleSheetService dipakai hanya sebagai data-access (baca sumber),
bukan logika transform.
ponytail: identitas pakai kunci natural, bukan reimplementasi penuh transform.

Cakupan menyeluruh (all data), bukan sampling. Dua jenis rekonsiliasi:
  - Horizontal : jumlah baris sumber (sheet) vs target (DB).  (interim/staging N/A — ingestion langsung)
  - Vertikal   : jumlah per kategori (master) / per orang & per bulan (tracker).

Deliverables: daftar MISSING dan daftar ILLEGAL.

Pakai:
    python reconcile.py master  <sheet_url> [--json out.json]
    python reconcile.py tracker <sheet_url> [--json out.json]
    python reconcile.py --selftest
"""

import argparse
import asyncio
import json
import sys
from collections import Counter

from sqlalchemy import select

from databaseConfig import AsyncSessionLocal, engine
from model.Base import GroupTypeEnum
from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster, kpi_master_users
from model.KPITracker import KPITracker
from model.User import User
from service.googleSheetService import GoogleSheetService


def _norm(val) -> str:
    return "" if val is None else str(val).strip().lower()


def reconcile_keys(source_keys: set, target_keys: set) -> tuple[list, list]:
    """Pure: (missing = source - target, illegal = target - source). Sorted for stable output."""
    missing = sorted(source_keys - target_keys, key=str)
    illegal = sorted(target_keys - source_keys, key=str)
    return missing, illegal


# ================================================================ #
#  SOURCE extraction (fresh — independent of the parser under test) #
# ================================================================ #

_MASTER_KPI_HEADERS = {"kpi", "nama kpi", "kpi name"}
_TRACKER_KPI_HEADERS = {"nama kpi", "name kpi", "kpi name", "nama_kpi", "kpi"}


def _is_master_pic_header(cell: str) -> bool:
    c = _norm(cell)
    return c.startswith("responsib") or c.startswith("rresponsob") or c.startswith("responsob") \
        or c in {"pic", "penanggung jawab", "person in charge"}


def extract_master_source(sheet_url: str) -> list[dict]:
    """
    Baca tab 'KPI' mentah, ambil tiap baris KPI valid (nama + PIC terisi) per kategori.
    Mengembalikan list {"category", "kpi_name"} — inklusi mengikuti kontrak ingestion
    (kpi_name & responsibility_persons wajib) agar tidak ada false-missing.
    """
    svc = GoogleSheetService()
    df, _, _, _ = svc.fetch_sheet_as_dataframe(
        sheet_url=sheet_url, sheet_name="KPI", sheet_index=0, header=None
    )

    rows = df.values.tolist()
    out: list[dict] = []
    category = None
    kpi_col = pic_col = None

    for row in rows:
        cells = [(c if c is not None else "") for c in row]
        first = _norm(cells[0]) if cells else ""
        rest_empty = all(_norm(c) == "" for c in cells[1:])

        if first == "" and rest_empty:                       # blank
            continue
        if first.startswith("kpi ") and rest_empty:          # category header
            category = str(cells[0]).strip()
            kpi_col = pic_col = None
            continue
        if first == "kpi":                                   # column header
            kpi_col = next((i for i, c in enumerate(cells) if _norm(c) in _MASTER_KPI_HEADERS), 0)
            pic_col = next((i for i, c in enumerate(cells) if _is_master_pic_header(c)), None)
            continue

        if category is None or kpi_col is None:
            continue
        kpi_name = str(cells[kpi_col]).strip() if kpi_col < len(cells) else ""
        pic = str(cells[pic_col]).strip() if pic_col is not None and pic_col < len(cells) else ""
        if not _norm(kpi_name) or (pic_col is not None and not _norm(pic)):
            continue
        pic_names = [p.strip() for p in pic.split(",") if p.strip()]
        out.append({"category": category, "kpi_name": kpi_name, "pic": pic_names})

    return out


def extract_tracker_source(sheet_url: str) -> list[dict]:
    """
    Baca semua tab, ambil tiap baris realisasi valid (nama_kpi terisi).
    Identitas: (kpi_name, nama_orang, bulan_num) — nama_orang & bulan dari judul/tab.
    """
    svc = GoogleSheetService()
    sheets = svc.fetch_all_sheets_as_dataframes(sheet_url=sheet_url, skip_on_error=True)

    out: list[dict] = []
    for sh in sheets:
        if sh.get("error") or sh.get("df") is None:
            continue
        df = sh["df"]
        meta = sh.get("meta") or {}
        person = meta.get("nama_orang") or "UNKNOWN"
        bulan = meta.get("bulan_num")

        cols = [str(c).strip() for c in df.columns]
        kpi_col = next((c for c in cols if _norm(c) in _TRACKER_KPI_HEADERS), None)
        if kpi_col is None:
            continue
        for _, r in df.iterrows():
            kpi_name = str(r[kpi_col]).strip() if r[kpi_col] is not None else ""
            if not _norm(kpi_name) or _norm(kpi_name) in ("nan", "none"):
                continue
            out.append({"kpi_name": kpi_name, "nama_orang": person, "bulan_num": bulan})

    return out


# ================================================================ #
#  TARGET extraction (DB)                                          #
# ================================================================ #

async def _resolve_group(session, sheet_url: str, gtype: GroupTypeEnum):
    sheet_id = GoogleSheetService._extract_spreadsheet_id(sheet_url)
    res = await session.execute(
        select(KPIGroup).where(KPIGroup.sheet_id == sheet_id, KPIGroup.group_type == gtype)
    )
    return res.scalar_one_or_none()


async def extract_master_target(session, group_id) -> list[dict]:
    # PIC names per master via the junction table (left join: KPI tanpa PIC tetap muncul).
    res = await session.execute(
        select(KPIMaster.id, KPIMaster.kpi_name, KPIMaster.category, User.full_name)
        .select_from(KPIMaster)
        .join(kpi_master_users, kpi_master_users.c.kpi_master_id == KPIMaster.id, isouter=True)
        .join(User, kpi_master_users.c.user_id == User.id, isouter=True)
        .where(KPIMaster.group_id == group_id)
    )
    by_id: dict = {}
    for r in res.all():
        rec = by_id.setdefault(r.id, {"kpi_name": r.kpi_name, "category": r.category, "pic": []})
        if r.full_name:
            rec["pic"].append(r.full_name)
    return list(by_id.values())


async def extract_tracker_target(session, group_id) -> list[dict]:
    res = await session.execute(
        select(KPIMaster.kpi_name, User.full_name, KPITracker.bulan_num)
        .select_from(KPITracker)
        .join(KPIMaster, KPITracker.kpi_master_id == KPIMaster.id, isouter=True)
        .join(User, KPITracker.user_id == User.id, isouter=True)
        .where(KPITracker.group_id == group_id)
    )
    return [{"kpi_name": r.kpi_name, "nama_orang": r.full_name, "bulan_num": r.bulan_num}
            for r in res.all()]


async def extract_tracker_link_issues(session, group_id) -> list[dict]:
    """Tracker rows di DB dengan mapping ke master rusak (kpi_master_id NULL)."""
    res = await session.execute(
        select(KPITracker.id, KPITracker.bulan_num, User.full_name)
        .select_from(KPITracker)
        .join(User, KPITracker.user_id == User.id, isouter=True)
        .where(KPITracker.group_id == group_id, KPITracker.kpi_master_id.is_(None))
    )
    return [{"tracker_id": str(r.id), "nama_orang": r.full_name, "bulan_num": r.bulan_num}
            for r in res.all()]


async def fetch_all_master_names(session) -> set[str]:
    """Semua kpi_name yang ada di kpi_master_records (lintas group) — target match by name."""
    res = await session.execute(select(KPIMaster.kpi_name))
    return {_norm(r.kpi_name) for r in res.all()}


# ================================================================ #
#  Report                                                          #
# ================================================================ #

def _master_key(rec: dict) -> str:
    return _norm(rec["kpi_name"])


def _tracker_key(rec: dict) -> tuple:
    return (_norm(rec["kpi_name"]), _norm(rec["nama_orang"]), rec.get("bulan_num"))


def build_report(mode: str, source: list[dict], target: list[dict], extras: dict | None = None) -> dict:
    key_fn = _master_key if mode == "master" else _tracker_key
    src_map = {key_fn(r): r for r in source}
    tgt_map = {key_fn(r): r for r in target}

    missing_keys, illegal_keys = reconcile_keys(set(src_map), set(tgt_map))

    pic_mismatch: list[dict] = []
    if mode == "master":
        src_vert = Counter(r["category"] for r in source)
        tgt_vert = Counter(r["category"] for r in target)
        vertical = {c: {"source": src_vert.get(c, 0), "target": tgt_vert.get(c, 0)}
                    for c in sorted(set(src_vert) | set(tgt_vert))}
        # Vertikal PIC: untuk KPI yang ada di kedua sisi, set nama PIC harus sama.
        for k in sorted(set(src_map) & set(tgt_map)):
            s_pic = {_norm(n) for n in src_map[k].get("pic", [])}
            t_pic = {_norm(n) for n in tgt_map[k].get("pic", [])}
            if s_pic != t_pic:
                pic_mismatch.append({
                    "kpi_name": src_map[k]["kpi_name"],
                    "pic_missing": sorted(n for n in src_map[k].get("pic", []) if _norm(n) not in t_pic),
                    "pic_illegal": sorted(n for n in tgt_map[k].get("pic", []) if _norm(n) not in s_pic),
                })
    else:
        src_vert = Counter(r["nama_orang"] for r in source)
        tgt_vert = Counter((r["nama_orang"] or "UNKNOWN") for r in target)
        vertical = {p: {"source": src_vert.get(p, 0), "target": tgt_vert.get(p, 0)}
                    for p in sorted(set(src_vert) | set(tgt_vert))}

    rep = {
        "mode": mode,
        "horizontal": {"source_rows": len(source), "target_rows": len(target),
                       "match": len(source) == len(target)},
        "vertical": vertical,
        "missing": [src_map[k] for k in missing_keys],   # di sheet, tak ada di DB
        "illegal": [tgt_map[k] for k in illegal_keys],   # di DB, tak ada di sheet
        "pic_mismatch": pic_mismatch,                    # mapping responsibility_persons -> kpi_master_users
        "kpi_without_master": [],                        # nama_kpi di sheet tracker tanpa master record
        "master_link_missing": [],                       # tracker rows di DB dgn kpi_master_id NULL
    }
    if extras:
        rep.update(extras)
    return rep


def print_report(rep: dict) -> None:
    h = rep["horizontal"]
    print(f"\n=== RECONCILIATION [{rep['mode']}] ===")
    print(f"Horizontal: source={h['source_rows']} target={h['target_rows']} "
          f"{'OK' if h['match'] else 'MISMATCH'}")
    print("Vertical (source vs target):")
    for k, v in rep["vertical"].items():
        flag = "" if v["source"] == v["target"] else "  <-- diff"
        print(f"  {k:<40} {v['source']:>5} | {v['target']:>5}{flag}")
    print(f"\nMISSING (di sheet, tak ada di DB): {len(rep['missing'])}")
    for r in rep["missing"]:
        print(f"  - {r}")
    print(f"\nILLEGAL (di DB, tak ada di sheet): {len(rep['illegal'])}")
    for r in rep["illegal"]:
        print(f"  - {r}")
    pm = rep.get("pic_mismatch", [])
    kwm = rep.get("kpi_without_master", [])
    mlm = rep.get("master_link_missing", [])
    if rep["mode"] == "master":
        print(f"\nPIC MAPPING MISMATCH (sheet vs kpi_master_users): {len(pm)}")
        for r in pm:
            print(f"  - {r['kpi_name']}: missing={r['pic_missing']} illegal={r['pic_illegal']}")
    else:
        print(f"\nNAMA_KPI TANPA MASTER (di sheet, tak ada master record): {len(kwm)}")
        for n in kwm:
            print(f"  - {n}")
        print(f"\nMASTER LINK MISSING (tracker rows di DB, kpi_master_id NULL): {len(mlm)}")
        for r in mlm:
            print(f"  - {r}")
    ok = (h["match"] and not rep["missing"] and not rep["illegal"]
          and not pm and not kwm and not mlm)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}\n")


# ================================================================ #
#  Entry                                                           #
# ================================================================ #

async def run(mode: str, sheet_url: str, json_out: str | None) -> int:
    gtype = GroupTypeEnum.MASTER if mode == "master" else GroupTypeEnum.TRACKER
    try:
        async with AsyncSessionLocal() as session:
            group = await _resolve_group(session, sheet_url, gtype)
            if group is None:
                sheet_id = GoogleSheetService._extract_spreadsheet_id(sheet_url)
                existing = (await session.execute(
                    select(KPIGroup.group_type, KPIGroup.sheet_id, KPIGroup.nama_grup)
                )).all()
                print(f"ERROR: KPIGroup ({mode}) untuk sheet_id={sheet_id} belum ada di DB. "
                      "Jalankan ingestion dulu, atau cek tipe/URL.", file=sys.stderr)
                print(f"Group yang ada di DB ({len(existing)}):", file=sys.stderr)
                for g in existing:
                    print(f"  - {g.group_type.value:<8} sheet_id={g.sheet_id}  {g.nama_grup}", file=sys.stderr)
                return 2

            extras: dict = {}
            if mode == "master":
                source = extract_master_source(sheet_url)
                target = await extract_master_target(session, group.id)
            else:
                source = extract_tracker_source(sheet_url)
                target = await extract_tracker_target(session, group.id)
                # Mapping ke master: nama_kpi sheet harus punya master record + link DB tak boleh NULL.
                master_names = await fetch_all_master_names(session)
                seen: set[str] = set()
                kpi_without_master = []
                for r in source:
                    k = _norm(r["kpi_name"])
                    if k and k not in master_names and k not in seen:
                        seen.add(k)
                        kpi_without_master.append(r["kpi_name"])
                extras = {
                    "kpi_without_master": sorted(kpi_without_master),
                    "master_link_missing": await extract_tracker_link_issues(session, group.id),
                }
    finally:
        await engine.dispose()

    rep = build_report(mode, source, target, extras)
    print_report(rep)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
        print(f"JSON ditulis ke {json_out}")

    ok = (rep["horizontal"]["match"] and not rep["missing"] and not rep["illegal"]
          and not rep["pic_mismatch"] and not rep["kpi_without_master"]
          and not rep["master_link_missing"])
    return 0 if ok else 1


def _selftest() -> None:
    # missing = source-only, illegal = target-only
    miss, ill = reconcile_keys({"a", "b", "c"}, {"b", "c", "d"})
    assert miss == ["a"] and ill == ["d"], (miss, ill)

    rep = build_report(
        "master",
        source=[{"category": "KPI X", "kpi_name": "Foo", "pic": ["Budi"]},
                {"category": "KPI X", "kpi_name": "Bar", "pic": ["Ani"]}],
        target=[{"category": "KPI X", "kpi_name": "foo ", "pic": ["budi"]},
                {"category": "KPI X", "kpi_name": "Ghost", "pic": []}],
    )
    assert [r["kpi_name"] for r in rep["missing"]] == ["Bar"], rep["missing"]
    assert [r["kpi_name"] for r in rep["illegal"]] == ["Ghost"], rep["illegal"]
    assert rep["horizontal"]["match"] is True   # 2 vs 2
    assert rep["pic_mismatch"] == [], rep["pic_mismatch"]   # "Foo": Budi == budi (case-insensitive)

    # PIC mapping mismatch: nama di sheet tak ter-link, dan ada link asing di DB.
    rep_pic = build_report(
        "master",
        source=[{"category": "KPI X", "kpi_name": "K", "pic": ["Budi", "Ani"]}],
        target=[{"category": "KPI X", "kpi_name": "K", "pic": ["Budi", "Citra"]}],
    )
    pm = rep_pic["pic_mismatch"]
    assert len(pm) == 1 and pm[0]["pic_missing"] == ["Ani"] and pm[0]["pic_illegal"] == ["Citra"], pm

    rep2 = build_report(
        "tracker",
        source=[{"kpi_name": "K", "nama_orang": "Budi", "bulan_num": 1}],
        target=[{"kpi_name": "k", "nama_orang": "budi", "bulan_num": 1},
                {"kpi_name": "K", "nama_orang": "Ani", "bulan_num": 2}],
        extras={"kpi_without_master": ["Ghost KPI"],
                "master_link_missing": [{"tracker_id": "x", "nama_orang": "Budi", "bulan_num": 1}]},
    )
    assert rep2["missing"] == [], rep2["missing"]
    assert len(rep2["illegal"]) == 1, rep2["illegal"]
    assert rep2["kpi_without_master"] == ["Ghost KPI"], rep2["kpi_without_master"]
    assert len(rep2["master_link_missing"]) == 1, rep2["master_link_missing"]
    print("selftest OK")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconciliation Google Sheets -> PostgreSQL ingestion.")
    ap.add_argument("mode", nargs="?", choices=["master", "tracker"])
    ap.add_argument("sheet_url", nargs="?")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return 0
    if not args.mode or not args.sheet_url:
        ap.error("mode dan sheet_url wajib (atau pakai --selftest)")
    # ponytail: Selector loop avoids asyncpg's noisy Proactor __del__ traceback on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args.mode, args.sheet_url, args.json_out))


if __name__ == "__main__":
    sys.exit(main())
