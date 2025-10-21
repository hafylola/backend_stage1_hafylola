from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import hashlib
import re

app = FastAPI(title="Backend Wizards - Stage 1 (String Analyzer Service)")

# In-memory storage: sha256_hash -> stored object (matches required response shape)
STORE: Dict[str, Dict[str, Any]] = {}

# ---- Helpers -------------------------------------------------------------
def utc_now_iso_z() -> str:
    """Return current UTC time in ISO 8601 format ending with 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def character_frequency_map(value: str) -> Dict[str, int]:
    freq: Dict[str, int] = {}
    for ch in value:
        freq[ch] = freq.get(ch, 0) + 1
    return freq

def analyze_properties(value: str) -> Dict[str, Any]:
    """Compute the properties required by the spec for a string value."""
    length = len(value)
    is_pal = value.lower() == value[::-1].lower()
    unique_chars = len(set(value))
    word_count = 0 if value.strip() == "" else len(value.strip().split())
    sha_hash = sha256_of(value)
    freq_map = character_frequency_map(value)
    return {
        "length": length,
        "is_palindrome": is_pal,
        "unique_characters": unique_chars,
        "word_count": word_count,
        "sha256_hash": sha_hash,
        "character_frequency_map": freq_map,
    }

def make_item(value: str) -> Dict[str, Any]:
    """Build stored item matching success response format."""
    props = analyze_properties(value)
    return {
        "id": props["sha256_hash"],
        "value": value,
        "properties": props,
        "created_at": utc_now_iso_z(),
    }

# ---- Request models -----------------------------------------------------
class StringIn(BaseModel):
    value: str

# ---- 1) Create / Analyze String -----------------------------------------
@app.post("/strings")
def create_string(payload: Dict[str, Any]):
    # Validate request body presence
    if not isinstance(payload, dict) or "value" not in payload:
        raise HTTPException(status_code=400, detail='Invalid request body or missing "value" field')

    value = payload["value"]

    # Validate type
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail='"value" must be a string')

    # Compute id (sha256 of exact string)
    item_id = sha256_of(value)

    # Conflict if exists
    if item_id in STORE:
        # 409 Conflict when string already exists
        raise HTTPException(status_code=409, detail="String already exists in the system")

    # Build and store
    item = make_item(value)
    STORE[item_id] = item

    # Return 201 Created with exact schema
    return JSONResponse(status_code=201, content=item, media_type="application/json")

# ---- 2) Get Specific String ---------------------------------------------
@app.get("/strings/{string_value}")
def get_string(string_value: str):
    # look up by sha of provided string_value
    item_id = sha256_of(string_value)
    item = STORE.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    return JSONResponse(content=item, media_type="application/json")

# ---- 3) Get All Strings with Filtering ----------------------------------
@app.get("/strings")
def get_all_strings(
    is_palindrome: Optional[bool] = Query(None),
    min_length: Optional[int] = Query(None),
    max_length: Optional[int] = Query(None),
    word_count: Optional[int] = Query(None),
    contains_character: Optional[str] = Query(None),
):
    # Validate query params types / constraints
    if contains_character is not None:
        if not isinstance(contains_character, str) or len(contains_character) != 1:
            raise HTTPException(status_code=400, detail="contains_character must be a single character")

    results: List[Dict[str, Any]] = list(STORE.values())
    filters_applied: Dict[str, Any] = {}

    if is_palindrome is not None:
        results = [r for r in results if r["properties"]["is_palindrome"] == is_palindrome]
        filters_applied["is_palindrome"] = is_palindrome

    if min_length is not None:
        if not isinstance(min_length, int):
            raise HTTPException(status_code=400, detail="min_length must be an integer")
        results = [r for r in results if r["properties"]["length"] >= min_length]
        filters_applied["min_length"] = min_length

    if max_length is not None:
        if not isinstance(max_length, int):
            raise HTTPException(status_code=400, detail="max_length must be an integer")
        results = [r for r in results if r["properties"]["length"] <= max_length]
        filters_applied["max_length"] = max_length

    if word_count is not None:
        if not isinstance(word_count, int):
            raise HTTPException(status_code=400, detail="word_count must be an integer")
        results = [r for r in results if r["properties"]["word_count"] == word_count]
        filters_applied["word_count"] = word_count

    if contains_character is not None:
        ch = contains_character
        results = [r for r in results if ch in r["value"]]
        filters_applied["contains_character"] = contains_character

    response = {
        "data": results,
        "count": len(results),
        "filters_applied": filters_applied,
    }
    return JSONResponse(content=response, media_type="application/json")

# ---- 4) Natural Language Filtering --------------------------------------
@app.get("/strings/filter-by-natural-language")
def natural_language_filter(query: str = Query(..., min_length=1)):
    """
    Parse simple natural language queries and return matching strings.

    Supported heuristics (from spec examples):
    - "all single word palindromic strings" -> word_count=1, is_palindrome=True
    - "strings longer than 10 characters" -> min_length = 11
    - "palindromic strings that contain the first vowel" -> is_palindrome=True, contains_character='a'
    - "strings containing the letter z" -> contains_character='z'
    """
    original = query
    q = query.lower().strip()

    parsed_filters: Dict[str, Any] = {}

    # Palindrome detection: accept 'palindrom' or 'palindrome' forms
    if "palindrom" in q or "palindrome" in q:
        parsed_filters["is_palindrome"] = True

    # Single word (explicit)
    if "single word" in q or "single-word" in q:
        parsed_filters["word_count"] = 1

    # "longer than N" -> min_length = N + 1
    m = re.search(r"longer than\s+(\d+)", q)
    if m:
        try:
            n = int(m.group(1))
            parsed_filters["min_length"] = n + 1
        except ValueError:
            pass

    # "strings containing the letter x" or "containing x"
    m2 = re.search(r"letter\s+([a-z])", q)
    if m2:
        parsed_filters["contains_character"] = m2.group(1)

    # "containing the character x" (alternate phrasing)
    m3 = re.search(r"containing\s+([a-z])\b", q)
    if m3 and "contains_character" not in parsed_filters:
        parsed_filters["contains_character"] = m3.group(1)

    # "first vowel" heuristic -> choose 'a' as first vowel
    if "first vowel" in q or ("first" in q and "vowel" in q):
        parsed_filters["contains_character"] = parsed_filters.get("contains_character", "a")
        parsed_filters["is_palindrome"] = parsed_filters.get("is_palindrome", False) or ("palindrom" in q or "palindrome" in q)

    # If we didn't parse anything useful
    if not parsed_filters:
        raise HTTPException(status_code=400, detail="Unable to parse natural language query")

    # Basic consistency checks (conflicting filters)
    if "min_length" in parsed_filters and "max_length" in parsed_filters:
        if parsed_filters["min_length"] > parsed_filters["max_length"]:
            raise HTTPException(status_code=422, detail="Query parsed but resulted in conflicting filters")

    # Apply parsed filters directly to STORE
    results = list(STORE.values())

    if "is_palindrome" in parsed_filters:
        results = [r for r in results if r["properties"]["is_palindrome"] == parsed_filters["is_palindrome"]]

    if "min_length" in parsed_filters:
        results = [r for r in results if r["properties"]["length"] >= parsed_filters["min_length"]]

    if "max_length" in parsed_filters:
        results = [r for r in results if r["properties"]["length"] <= parsed_filters["max_length"]]

    if "word_count" in parsed_filters:
        results = [r for r in results if r["properties"]["word_count"] == parsed_filters["word_count"]]

    if "contains_character" in parsed_filters:
        ch = parsed_filters["contains_character"].lower()
        results = [r for r in results if ch in r["value"].lower()]

    # Prepare interpreted_query exactly as spec expects
    interpreted_query = {
        "original": original,
        "parsed_filters": parsed_filters
    }

    response = {
        "data": results,
        "count": len(results),
        "interpreted_query": interpreted_query
    }

    return JSONResponse(content=response, media_type="application/json")

# ---- 5) Delete String ---------------------------------------------------
@app.delete("/strings/{string_value}", status_code=204)
def delete_string(string_value: str):
    item_id = sha256_of(string_value)
    if item_id not in STORE:
        raise HTTPException(status_code=404, detail="String does not exist in the system")
    del STORE[item_id]
    # 204 No Content -> empty body
    return JSONResponse(status_code=204, content=None, media_type="application/json")
