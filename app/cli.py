"""Command line helpers for local administration and one-off polling."""
from __future__ import annotations

import argparse

from .config import get_settings
from .db import SessionLocal, init_db
from .models import AccessToken, Profile
from .security import create_access_token


def create_admin(label: str, raw: str | None) -> None:
    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        row, actual = create_access_token(db, settings, kind="admin", label=label, created_by="cli", raw=raw)
        db.commit()
        print(f"ADMIN_TOKEN={actual}")


def _reveal(row: AccessToken, settings) -> str:
    from .security import decrypt_secret
    return decrypt_secret(row.encrypted_secret, settings)


def create_profile(label: str, unlimited: bool) -> None:
    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        profile = Profile(label=label, unlimited=unlimited, allowed_channels=[])
        db.add(profile)
        db.flush()
        row, raw = create_access_token(db, settings, kind="profile", label=label, profile_id=profile.id, created_by="cli")
        db.commit()
        print(f"TVS_TOKEN={raw}")
        print(f"PROFILE_ID={profile.id}")


def poll_once() -> None:
    init_db()
    from .poller import Poller
    poller = Poller(SessionLocal)
    count = poller.poll_once()
    print(f"polled={count} errors={poller.stats['errors']}")


def _format_observed(observed: dict) -> str:
    parts = []
    for key, value in observed.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.4g}")
        elif isinstance(value, (list, tuple)):
            parts.append(f"{key}={list(value)}")
        elif isinstance(value, dict):
            continue
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _print_report(report: dict) -> None:
    series = report.get("series") or {}
    print(f"# Детекция накрутки — {report.get('channel')}")
    print(f"Индекс: {report.get('risk_score')} / 100 · confidence {report.get('confidence')} · вердикт {report.get('verdict')}")
    print(f"Окно: {report.get('window_hours')} ч · точек {series.get('expanded_points')} (live {series.get('live_points')}, пропусков {series.get('gap_points')}) · сэмплов {series.get('samples_used')}")
    print(f"Период: {series.get('from')} → {series.get('to')}")
    parts = report.get("confidence_parts") or {}
    print(f"Confidence части: data={parts.get('data_factor')} samples={parts.get('sample_factor')} доступность={parts.get('available_ratio')}")
    factors = report.get("factors") or []
    print(f"\nСработавшие признаки ({len(factors)}):")
    if not factors:
        print("  — ничего не сработало")
    for factor in factors:
        print(f"  [{factor.get('code')}] score={factor.get('score'):.3f} weight={factor.get('weight')}")
        print(f"      {factor.get('note')}")
        print(f"      observed: {_format_observed(factor.get('observed') or {})}")
    unavailable = report.get("unavailable") or []
    if unavailable:
        print(f"\nНедоступные метрики ({len(unavailable)}):")
        for item in unavailable:
            print(f"  - {item.get('metric')}: {item.get('detail')}")
    print("\nПредупреждения:")
    for warning in report.get("warnings") or []:
        print(f"  - {warning}")
    comparison = report.get("ad_vs_nonad") or {}
    print("\nРеклама (инференциальная оценка прокси, adBreak недоступен анонимно):")
    print(f"  доступно={comparison.get('available')} причина={comparison.get('reason') or '—'} вердикт={comparison.get('verdict')}")
    for side in ("ad_window", "rest_window"):
        window = comparison.get(side) or {}
        if window:
            print(
                f"  {side}: минут={window.get('minutes')} рост={window.get('viewer_growth_ratio')} "
                f"chat_ratio={window.get('chat_ratio_median')} followers/ч={window.get('followers_per_hour')}"
            )
    breaks = comparison.get("breaks") or []
    if breaks:
        print(f"  оценок перерывов: {len(breaks)}")
        for item in breaks[:10]:
            print(f"    {item.get('ts')} {item.get('kind')} confidence={item.get('confidence')}")


def detect(login: str, db_path: str | None, hours: float, as_json: bool) -> None:
    """Run the whole detection pipeline against a database and print the report."""
    import json

    from sqlalchemy import create_engine

    from .services.detection import chatters_payload, detection_report

    url = f"sqlite:///{db_path}" if db_path else get_settings().database_url
    engine = create_engine(url)
    try:
        from sqlalchemy.orm import Session

        with Session(engine) as db:
            report = detection_report(db, login.lower(), hours=hours)
            roster = chatters_payload(db, login.lower())
    finally:
        engine.dispose()
    if as_json:
        print(json.dumps({"report": report, "chatters": roster}, ensure_ascii=False, indent=2, default=str))
        return
    _print_report(report)
    sample = roster.get("sample") or {}
    enrichment = roster.get("enrichment") or {}
    print("\nВыборка чаттеров:")
    if not sample:
        print(f"  — нет снимка выборки ({enrichment.get('missing') or 'снимок ещё не собран'})")
    else:
        print(f"  снята {sample.get('observed_at')} · сэмпл {sample.get('sampled')} из count={sample.get('count')}")
        print(f"  обогащено аккаунтов: {enrichment.get('enriched')} (кэш младше {enrichment.get('newest_enriched_at')})")
        print(f"  роли: {sample.get('roles')}")
    print(f"  {roster.get('note')}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--label", default="Admin")
    admin.add_argument("--token", default=None, help="Явный TVS-ключ длиной TVS_ + 128 символов")
    profile = sub.add_parser("create-profile")
    profile.add_argument("--label", default="Профиль")
    profile.add_argument("--unlimited", action="store_true")
    sub.add_parser("poll-once")
    detect_cmd = sub.add_parser("detect", help="Прогнать детекцию накрутки по каналу и напечатать отчёт")
    detect_cmd.add_argument("--login", "-l", required=True, help="Логин канала")
    detect_cmd.add_argument("--db", default=None, help="Путь к SQLite-базе (по умолчанию DATABASE_URL)")
    detect_cmd.add_argument("--hours", type=float, default=168.0, help="Окно наблюдения в часах")
    detect_cmd.add_argument("--json", action="store_true", help="Печать полного отчёта в JSON")
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.label, args.token)
    elif args.command == "create-profile":
        create_profile(args.label, args.unlimited)
    elif args.command == "detect":
        detect(args.login, args.db, args.hours, args.json)
    else:
        poll_once()


if __name__ == "__main__":
    main()
