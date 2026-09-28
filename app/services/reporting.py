"""Small dependency-free CSV and report helpers."""
from __future__ import annotations

import csv
import hashlib
import io
import json


def csv_bytes(points: list[dict]) -> bytes:
    # Semicolon delimiter makes Excel (RU/EU locale) split every field into its
    # own column on double-click. UTF-8 BOM keeps Cyrillic readable, CRLF keeps
    # Windows Excel happy and csv.QUOTE_MINIMAL protects values that contain a
    # delimiter, quote or newline.
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["ts", "is_live", "viewers", "chatters", "guests", "chat_ratio"])
    for point in points:
        writer.writerow([point.get("ts"), point.get("is_live"), point.get("total"), point.get("authorized"), point.get("guests"), point.get("chat_ratio")])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def report_digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def html_report(login: str, data: dict) -> str:
    rows = "".join(f"<tr><td>{item}</td><td>{value}</td></tr>" for item, value in data.get("summary", {}).items())
    factors = "".join(f"<li><b>{item.get('code')}</b>: {item.get('note', '')}</li>" for item in data.get("score", {}).get("factors", []))
    return f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Отчёт {login}</title><style>body{{font:14px system-ui;background:#0d0d12;color:#eee;padding:32px}}main{{max-width:960px;margin:auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #303044;padding:8px;text-align:left}}small{{color:#9aa}}</style></head><body><main><h1>TVS Analytics · {login}</h1><p>Период: {data.get('period', '—')}</p><table>{rows}</table><h2>Факторы score</h2><ul>{factors}</ul><p><small>Методология: оценка необычности поведения, не вероятность накрутки. SHA-256: {data.get('digest')}</small></p></main></body></html>"""


_PDF_TRANSLIT = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "Zh", "З": "Z",
    "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R",
    "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "—": "-", "–": "-", "·": "-", "«": '"', "»": '"', "…": "...", "№": "No.",
})


def _pdf_safe(text: str) -> str:
    """The base-14 Helvetica font only supports latin-1, so transliterate."""
    return text.translate(_PDF_TRANSLIT)


def simple_pdf(title: str, lines: list[str]) -> bytes:
    """Generate a valid one-page text PDF without an external dependency."""
    escaped = [_pdf_safe(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines[:35]]
    content = ["BT", "/F1 10 Tf", "50 800 Td", "14 TL"]
    for line in escaped:
        content.append(f"({line}) Tj")
        content.append("T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)
