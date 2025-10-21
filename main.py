from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import hashlib

app = FastAPI(title="Backend Wizards - Stage 1")

# In-memory storage: sha256_hash -> stored object
STORE: Dict[str, Dict[str, Any]] = {}

# Fallback / helper
def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def analyze_string_value(value: str) -> Dict[str, Any]:
    value_stripped = value  # keep original spacing intentionally
    length = len(value_stripped)
    # palindrome check (ignores case)
    is_palindrome = value_stripped.lower() == value_stripped[::-1].lower()
    unique_characters = len(set(value_stripped))
    word_count = 0 if value_stripped.strip() == "" else len(value_stripped.split())
    sha_hash = sha256_of(value_stripped)
    # frequency map (counts characters exactly as they appear)
    freq: Dict[str, int] = {}
    for ch in value_stripped:
        freq[ch] = freq.get(ch, 0) + 1

    return {
        "length": length,
        "is_palindrome": is_palindrome,
        "unique_characters": unique_characters,
        "word_count": word_count,
        "sha256_hash": sha_hash,
        "character_frequency_map": freq,
    }

# Request model for POST /strings
class StringIn(BaseModel):
    value: str

# --- 1) Create / Analyze String ---
@app.post("/strings", status_code=201)
def create_string(payload: Dict[str, Any]):
    # Validate presence
    if "value" not in payload:
        raise HTTPException(status_code=400, detail="Missing 'value' field")
    value = payload["value"]
    # Validate type
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="'value' must be a string")

    # compute sha
    hash_value = sha256_of(value)
    # Check if exists (409)
    if hash_value in STORE:
        raise HTTPException(status_code=409, detail="String already exists in the system")

    # Analyze
    properties = analyze_string_value(value)
    item = {
        "id": hash_value,
        "value": value,
        "properties": properties,
        "created_at": utc_now_iso()
    }

    # store
    STORE[hash_value] = item
    return JSONResponse(status_code=201, content=item)

# --- 2) Get Specific String ---
@app.get("/strings/{string_value}")
def get_string(string_value: str):
    hash_value = sha256_of(string_value)
    item = STORE.get(hash_value)
    if not item:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    return item

# --- 3) Get All Strings with Filtering ---
@app.get("/strings")
def get_all_strings(
    is_palindrome: Optional[bool] = Query(None),
    min_length: Optional[int] = Query(None, ge=0),
    max_length: Optional[int] = Query(None, ge=0),
    word_count: Optional[int] = Query(None, ge=0),
    contains_character: Optional[str] = Query(None, min_length=1, max_length=1)
):
    results: List[Dict[str, Any]] = list(STORE.values())

    filters_applied = {}
    if is_palindrome is not None:
        results = [r for r in results if r["properties"]["is_palindrome"] == is_palindrome]
        filters_applied["is_palindrome"] = is_palindrome
    if min_length is not None:
        results = [r for r in results if r["properties"]["length"] >= min_length]
        filters_applied["min_length"] = min_length
    if max_length is not None:
        results = [r for r in results if r["properties"]["length"] <= max_length]
        filters_applied["max_length"] = max_length
    if word_count is not None:
        results = [r for r in results if r["properties"]["word_count"] == word_count]
        filters_applied["word_count"] = word_count
    if contains_character is not None:
        results = [r for r in results if contains_character in r["value"]]
        filters_applied["contains_character"] = contains_character

    return {
        "data": results,
        "count": len(results),
        "filters_applied": filters_applied
    }

# --- 4) Natural Language Filtering (simple heuristics) ---
@app.get("/strings/filter-by-natural-language")
def natural_language_filter(query: str = Query(..., min_length=1)):
    original = query
    q = query.lower()

    parsed: Dict[str, Any] = {}
    # Very basic heuristics based on examples:
    if "palindrom" in q:
        parsed["is_palindrome"] = True
    if "single word" in q or "single-word" in q:
        parsed["word_count"] = 1
    # strings longer than N characters -> "longer than 10" -> min_length = N+1
    # look for "longer than <number>" or "longer than <number> characters"
    import re
    m = re.search(r"longer than\s+(\d+)", q)
    if m:
        try:
            n = int(m.group(1))
            parsed["min_length"] = n + 1
        except:
            pass
    # "strings containing the letter z" -> contains_character=z
    m2 = re.search(r"letter\s+([a-z])", q)
    if m2:
        parsed["contains_character"] = m2.group(1)
    # "first vowel" heuristic -> check 'a', but we keep it simple and look for 'vowel' -> choose 'a'
    if "vowel" in q:
        parsed["contains_character"] = parsed.get("contains_character", "a")

    # If we didn't parse anything useful, return 400
    if not parsed:
        raise HTTPException(status_code=400, detail="Unable to parse natural language query")

    # Now apply parsed filters using get_all_strings logic
    try:
        filtered = get_all_strings(
            is_palindrome=parsed.get("is_palindrome"),
            min_length=parsed.get("min_length"),
            max_length=parsed.get("max_length"),
            word_count=parsed.get("word_count"),
            contains_character=parsed.get("contains_character")
        )["data"]
    except Exception:
        raise HTTPException(status_code=422, detail="Query parsed but resulted in conflicting filters")

    return {
        "data": filtered,
        "count": len(filtered),
        "interpreted_query": {
            "original": original,
            "parsed_filters": parsed
        }
    }

# --- 5) Delete String ---
@app.delete("/strings/{string_value}", status_code=204)
def delete_string(string_value: str):
    hash_value = sha256_of(string_value)
    if hash_value not in STORE:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    del STORE[hash_value]
    # 204 No Content => return nothing
    return
