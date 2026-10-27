from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "snapshots"


def success(data: dict, source: str) -> dict:
    return {"success": True, "data": data, "source": source, "ts": datetime.now(timezone.utc).isoformat()}


def failure(message: object, source: str) -> dict:
    return {"success": False, "error": str(message), "source": source, "ts": datetime.now(timezone.utc).isoformat()}


def _sqlite_authorizer(action, _arg1, _arg2, _database, _trigger):
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", -1),
    }
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def csv_sql(input_data: dict, dataset: dict) -> dict:
    source = dataset.get("filename", "uploaded.csv")
    connection = None
    try:
        sql = str(input_data.get("sql", "")).strip()
        if not sql or len(sql) > 2_000 or not re.match(r"^select\b", sql, re.IGNORECASE):
            raise ValueError("Only one read-only SELECT query is accepted (up to 2,000 characters).")
        epoch_pattern = re.compile(
            r"EXTRACT\s*\(\s*EPOCH\s+FROM\s+\(?\s*"
            r'("(?:[^"]|"")*"|[A-Za-z_][\w]*)\s*-\s*'
            r'("(?:[^"]|"")*"|[A-Za-z_][\w]*)\s*\)?\s*\)',
            re.IGNORECASE,
        )
        sql = epoch_pattern.sub(
            lambda match: f"((julianday({match.group(1)}) - julianday({match.group(2)})) * 86400.0)",
            sql,
        )
        headers = dataset["headers"]
        if not headers or len(set(name.lower() for name in headers)) != len(headers):
            raise ValueError("CSV headers must be non-empty and unique, ignoring letter case.")
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        quoted_headers = [quote(name) for name in headers]
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(f"CREATE TABLE trips ({', '.join(name + ' TEXT' for name in quoted_headers)})")
        placeholders = ",".join("?" for _ in headers)
        connection.executemany(
            f"INSERT INTO trips VALUES ({placeholders})",
            [[row.get(header, "") for header in headers] for row in dataset["rows"]],
        )
        connection.set_authorizer(_sqlite_authorizer)
        connection.set_progress_handler(lambda: 1, 5_000_000)
        cursor = connection.execute(sql)
        rows, row_count = [], 0
        for row in cursor:
            row_count += 1
            if len(rows) < 500:
                rows.append(dict(row))
        return success({"rows": rows, "row_count": row_count, "source": source}, "uploaded.csv")
    except Exception as exc:
        return failure(exc, "uploaded.csv")
    finally:
        if connection is not None:
            connection.close()


def calculate(expression: str, units: str | None = None) -> dict:
    source = "calculator"
    try:
        s = re.sub(r"\s+", "", str(expression or ""))
        if not s or len(s) > 200 or not re.fullmatch(r"[0-9+*/().-]+", s):
            raise ValueError("Expression must contain only numbers and + - * / ( ).")
        index = 0

        def eat(char: str) -> bool:
            nonlocal index
            if index < len(s) and s[index] == char:
                index += 1
                return True
            return False

        def atom() -> float:
            nonlocal index
            if eat("+"):
                return atom()
            if eat("-"):
                return -atom()
            if eat("("):
                value = sum_expr()
                if not eat(")"):
                    raise ValueError("Missing closing parenthesis.")
                return value
            match = re.match(r"(?:\d+(?:\.\d*)?|\.\d+)", s[index:])
            if not match:
                raise ValueError(f"Expected a number at position {index}.")
            index += len(match.group(0))
            return float(match.group(0))

        def product() -> float:
            nonlocal index
            value = atom()
            while index < len(s) and s[index] in "*/":
                operator = s[index]
                index += 1
                right = atom()
                if operator == "/" and right == 0:
                    raise ValueError("Division by zero.")
                value = value * right if operator == "*" else value / right
            return value

        def sum_expr() -> float:
            nonlocal index
            value = product()
            while index < len(s) and s[index] in "+-":
                operator = s[index]
                index += 1
                right = product()
                value = value + right if operator == "+" else value - right
            return value

        value = sum_expr()
        if index != len(s) or not (float("-inf") < value < float("inf")):
            raise ValueError("Invalid arithmetic expression.")
        data = {"value": value}
        if units:
            data["units"] = str(units)
        return success(data, source)
    except Exception as exc:
        return failure(exc, source)


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1
        if tag in {"br", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _VisibleText()
    parser.feed(markup)
    joined = "".join(parser.parts)
    lines = [re.sub(r"\s+", " ", line).strip() for line in joined.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _ensure_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a public http(s) pricing page URL.")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Local and private network URLs are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
        if not addresses or any(not ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses):
            raise ValueError("Local and private network URLs are not allowed.")
    except socket.gaierror as exc:
        raise ValueError("Could not resolve the pricing page host.") from exc
    return parsed.geturl()


async def retrieve_policy(input_data: dict) -> dict:
    original_url = str(input_data.get("url", ""))
    try:
        current_url = original_url
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, headers={"User-Agent": "PedalPlanStudentProject/1.0"}) as client:
            for _ in range(5):
                safe_url = _ensure_public_url(current_url)
                response = await client.get(safe_url)
                if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("location"):
                    current_url = urljoin(safe_url, response.headers["location"])
                    continue
                if response.status_code >= 300:
                    raise ValueError(f"Pricing page returned HTTP {response.status_code}.")
                if len(response.content) > 5_000_000:
                    raise ValueError("Pricing page is larger than 5 MB.")
                markup = response.text
                break
            else:
                raise ValueError("Pricing page redirected too many times.")

        text = html_to_text(markup)
        fetched_at = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        basename = f"{fetched_at.replace(':', '-').replace('.', '-')}-{digest[:12]}"
        (SNAPSHOT_DIR / f"{basename}.txt").write_text(text, encoding="utf-8")
        metadata = {"sourceUrl": safe_url, "accessedAt": fetched_at, "sha256": digest, "textFile": f"{basename}.txt"}
        (SNAPSHOT_DIR / f"{basename}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        terms = [term for term in re.split(r"[^a-z0-9]+", str(input_data.get("query", "")).lower()) if len(term) > 2]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidates: list[str] = []

        #keep product headings with their adjacent table values
        #otherwise separates a fare heading from its price and makes citations poor.
        anchors = ("single ride", "divvy annual", "classic bike prices", "ebike prices", "e-bike prices", "scooter prices", "additional pricing")
        for index, line in enumerate(lines):
            lowered = line.lower()
            if any(anchor in lowered for anchor in anchors):
                window = "\n".join(lines[index:min(len(lines), index + 9)])
                if window and window not in candidates:
                    candidates.append(window[:900])

        #add focused context around any other fare or ride-time rule.
        for index, line in enumerate(lines):
            lowered = line.lower()
            if "$" not in line and not any(term in lowered for term in ("minute free", "minutes free", "overage", "unlock")):
                continue
            window = "\n".join(lines[max(0, index - 2):min(len(lines), index + 3)])
            if window and window not in candidates:
                candidates.append(window[:900])

        def relevance(candidate: str) -> float:
            lowered = candidate.lower()
            score = sum(1 for term in terms if term in lowered)
            score += 2.0 * lowered.count("$")
            score += 2.0 * sum(term in lowered for term in ("annual", "single ride", "45 min", "unlock", "per minute", "overage"))
            if lowered.startswith(("skip to", "how it works", "pricing\nexplore")):
                score -= 5
            return score

        candidates.sort(key=relevance, reverse=True)
        k = max(1, min(8, int(input_data.get("k", 5) or 5)))
        passages = [
            {"text": candidate, "source": safe_url, "score": relevance(candidate)}
            for candidate in candidates[:k]
        ]
        snapshot = {"sourceUrl": safe_url, "accessedAt": fetched_at, "sha256": digest, "filename": f"{basename}.txt"}
        return success({"passages": passages[:k], "snapshot": snapshot}, safe_url)
    except Exception as exc:
        return failure(exc, original_url or "pricing page")

