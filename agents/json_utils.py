"""
json_utils — shared helpers for turning a Claude response into a single, clean
JSON string ready for model_validate_json / json.loads.

These live in one place because several agents (email_triage, email_digest,
weekly_report) parse Claude JSON the same way, and the old per-file copies had
drifted — most notably an unbalanced text.index("{")/text.rindex("}") slice that
spanned two JSON blocks when Claude self-corrected mid-response and produced
"Extra data" parse errors. clean_json_response below extracts only the FIRST
complete, balanced object via brace-counting so that failure mode can't recur.
"""


def strip_code_fences(text: str) -> str:
    """
    Removes ```json and ``` wrappers if present.
    Claude sometimes adds these despite being told not to.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```"
                         else lines[1:])
    return text.strip()


def clean_json_response(text: str) -> str:
    """
    Extracts the FIRST complete, balanced JSON object from text.

    Uses brace-counting rather than text.index("{")/text.rindex("}").
    The rindex approach fails when Claude emits two JSON blocks
    (self-correction behavior) because it spans from the first {
    to the last } across BOTH blocks, producing "Extra data" errors
    when the parser finds valid JSON followed by more content.

    Brace-counting stops exactly when the first opening brace is
    matched by its closing brace, returning only that first object
    regardless of what follows.

    Raises ValueError with a clear message if no complete JSON
    object is found, which base.py's run() catches and marks as
    an error run.
    """
    if "{" not in text:
        raise ValueError(
            "No JSON object found in Claude response. "
            "Response may be plain text or empty."
        )

    start = text.index("{")
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                # Found the end of the first complete JSON object
                return text[start:i + 1]

    raise ValueError(
        f"No complete JSON object found — response may be truncated. "
        f"Response length: {len(text)} chars, "
        f"starts with: {text[start:start+100]!r}"
    )
