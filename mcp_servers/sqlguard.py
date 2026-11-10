"""Only plain SELECT queries get through to the database tool."""
import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|call|do|vacuum|set|reset"
    r"|pg_sleep|pg_read_file|scenario_runs)\b",
    re.I,
)


def validate_sql(sql: str) -> str:
    s = re.sub(r"--.*?$", "", sql, flags=re.M)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = s.strip().rstrip(";").strip()
    if not s:
        raise ValueError("empty query")
    if ";" in s:
        raise ValueError("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise ValueError("only SELECT queries are allowed")
    found = FORBIDDEN.search(s)
    if found:
        raise ValueError(f"forbidden keyword: {found.group(1)}")
    return s
