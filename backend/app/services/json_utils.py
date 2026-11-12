"""
JSON utilities dùng chung cho toàn bộ hệ thống agent.
"""
import re
import json


def extract_pure_json(text: str) -> str:
    """Decode actual JSON first, preserving commas/control sequences inside source strings."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty JSON response")
    decoder = json.JSONDecoder(strict=False)
    start = re.search(r"[\{\[]", text)
    candidates = [start.start()] if start else []
    for position in candidates:
        try:
            data, _ = decoder.raw_decode(text, position)
            if isinstance(data, (dict, list)):
                return json.dumps(data, ensure_ascii=False)
        except json.JSONDecodeError:
            continue
    # Repair trailing commas only outside quoted source code.
    chars, quoted, escaped = [], False, False
    for index, char in enumerate(text):
        if quoted:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        else:
            if char == '"':
                quoted = True
            if char == "," and text[index + 1:].lstrip().startswith(("}", "]")):
                continue
            chars.append(char)
    repaired = "".join(chars)
    repaired_start = re.search(r"[\{\[]", repaired)
    for position in ([repaired_start.start()] if repaired_start else []):
        try:
            data, _ = decoder.raw_decode(repaired, position)
            if isinstance(data, (dict, list)):
                return json.dumps(data, ensure_ascii=False)
        except json.JSONDecodeError:
            continue
    raise ValueError("Invalid or truncated JSON response")


# Alias ngắn để tương thích với code cũ
_extract_pure_json = extract_pure_json


def merge_code_files(current: str, patch: str) -> str:
    """Apply a partial agent response without dropping unchanged files."""
    files = {}
    for payload in (current, patch):
        data = json.loads(payload)
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            raise ValueError("Agent response must contain a files list")
        for item in data["files"]:
            if not isinstance(item, dict) or not isinstance(item.get("file_path"), str):
                raise ValueError("Invalid source file")
            content = item.get("code", item.get("content"))
            if not item["file_path"] or not isinstance(content, str):
                raise ValueError("Invalid source file content")
            files[item["file_path"]] = {"file_path": item["file_path"], "code": content}
    return json.dumps({"files": list(files.values())}, ensure_ascii=False)
