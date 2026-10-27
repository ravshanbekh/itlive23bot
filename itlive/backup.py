"""Consistent SQLite online backup and restore verification.

Run against a stopped copy for restore; never overwrite a live database.
"""
import argparse
import sqlite3
from pathlib import Path


def backup(source: Path, destination: Path):
    source=Path(source); destination=Path(destination)
    if not source.is_file(): raise FileNotFoundError(source)
    if destination.exists(): raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            destination.unlink(missing_ok=True)
            raise RuntimeError("Backup tekshiruvidan o‘tmadi")


def verify(path: Path):
    with sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro",uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0]!="ok": raise RuntimeError("SQLite tekshiruvi xato")
        required={"leads","staff","reminders","notification_outbox"}
        actual={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required<=actual: raise RuntimeError("Bu ITLIVE zaxirasi emas")


def main():
    parser=argparse.ArgumentParser(description="ITLIVE SQLite zaxira va tekshiruv")
    sub=parser.add_subparsers(dest="command",required=True)
    create=sub.add_parser("create"); create.add_argument("source",type=Path); create.add_argument("destination",type=Path)
    check=sub.add_parser("verify"); check.add_argument("path",type=Path)
    args=parser.parse_args()
    if args.command=="create":
        backup(args.source,args.destination); verify(args.destination); print("Backup tayyor va tekshirildi")
    else:
        verify(args.path); print("Backup yaroqli")


if __name__=="__main__": main()
