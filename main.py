from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from hashlib import sha256
from datetime import datetime
import re

app = FastAPI(title="Stage 1 - Bot-Proof String Analyzer")

# -------------------------
# In-memory storage
# -------------------------
db: Dict[str, dict] = {}

# -------------------------
# Pydantic request model
# -------------------------
class StringRequest(BaseModel):
    value: str

# -------------------------
# Helper functions
# -------------------------
def compute_properties(value: str):
    lower_val = value.lower()
    hash_value = sha256(lower_val.encode()).hexdigest()
    char_freq = {c: lower_val.count(c) for c in set(lower_val)}
    return {
        "length": len(value),
        "is_palindrome": lower_val == lower_val[::-1],
        "unique_characters": len(set(lower_val)),
        "word_count": len(value.split()),
        "sha256_hash": hash_value,
        "character_frequency_map": char_freq
    }

def parse_natural_language(query: str):
    q = query.lower()
    filters = {}

    if "palindrome" in q or "palindromic" in q:
        filters["is_palindrome"] = True
    if "single word" in q or "one word" in q:
        filters["word_count"] = 1
    min_len_match = re.search(r"strings longer than (\d+)", q)
    if min_len_match:
        filters["min_length"] = int(min_len_match.group(1)) + 1
    contains_letter_match = re.search(r"contains letter (\w)", q)
    if contains_letter_match:
        filters["contains_character"] = contains_letter_match.group(1).lower()

    if not filters:
        return {}
    return filters

def filter_strings(filters: dict):
    results = []
    for record in db.values():
        props = record["properties"]
        match = True
        if "is_palindrome" in filters and props["is_palindrome"] != filters["is_palindrome"]:
            match = False
        if "word_count" in filters and props["word_count"] != filters["word_count"]:
            match = False
        if "min_length" in filters and props["length"] < filters["min_length"]:
            match = False
        if "max_length" in filters and props["length"] > filters["max_length"]:
            match = False
        if "contains_character" in filters and filters["contains_character"].lower() not in record["value"].lower():
            match = False
        if match:
            results.append(record)
    return results

# -------------------------
# POST /strings
# -------------------------
@app.post("/strings", status_code=201)
def create_string(payload: StringRequest):
    value = payload.value
    if value is None or not isinstance(value, str):
        raise HTTPException(status_code=422, detail="'value' must be a string")

    key = sha256(value.lower().encode()).hexdigest()
    if key in db:
        raise HTTPException(status_code=409, detail="String already exists")

    props = compute_properties(value)
    record = {
        "id": key,
        "value": value,
        "properties": props,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    db[key] = record
    return record

# -------------------------
# GET /strings/{string_value}
# -------------------------
@app.get("/strings/{string_value}")
def get_string(string_value: str):
    key = sha256(string_value.lower().encode()).hexdigest()
    if key not in db:
        raise HTTPException(status_code=404, detail="String does not exist")
    return db[key]

# -------------------------
# GET /strings (with filters)
# -------------------------
@app.get("/strings")
def get_strings(
    is_palindrome: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    word_count: Optional[int] = None,
    contains_character: Optional[str] = None
):
    filters = {}
    if is_palindrome is not None:
        filters["is_palindrome"] = is_palindrome
    if min_length is not None:
        filters["min_length"] = min_length
    if max_length is not None:
        filters["max_length"] = max_length
    if word_count is not None:
        filters["word_count"] = word_count
    if contains_character is not None:
        filters["contains_character"] = contains_character.lower()

    results = filter_strings(filters)
    return {
        "data": results,
        "count": len(results),
        "filters_applied": filters
    }

# -------------------------
# GET /strings/filter-by-natural-language
# -------------------------
@app.get("/strings/filter-by-natural-language")
def filter_by_nl(query: str):
    filters = parse_natural_language(query)
    results = filter_strings(filters)
    return {
        "data": results,
        "count": len(results),
        "interpreted_query": {
            "original": query,
            "parsed_filters": filters
        }
    }

# -------------------------
# DELETE /strings/{string_value}
# -------------------------
@app.delete("/strings/{string_value}", status_code=204)
def delete_string(string_value: str):
    key = sha256(string_value.lower().encode()).hexdigest()
    if key not in db:
        raise HTTPException(status_code=404, detail="String does not exist")
    del db[key]
