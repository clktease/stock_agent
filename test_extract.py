import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_server import _extract_response

# Test 1: Anthropic content blocks (the broken case)
anthropic_result = {
    "messages": [
        type("Msg", (), {"content": [
            {"type": "text", "text": "# AAPL Analysis\n\nPrice: $291", "annotations": [], "id": "msg_xxx"},
        ]})()
    ]
}
out = _extract_response(anthropic_result)
print("Test 1 (Anthropic blocks):")
print(repr(out[:80]))
assert out.startswith("# AAPL Analysis"), f"FAIL: {out[:60]}"
print("  PASSED")

# Test 2: Plain string content
plain_result = {
    "messages": [type("Msg", (), {"content": "Hello world"})()]
}
out = _extract_response(plain_result)
print("\nTest 2 (plain string):", repr(out))
assert out == "Hello world", f"FAIL: {out}"
print("  PASSED")

# Test 3: Multiple text blocks merged
multi_result = {
    "messages": [type("Msg", (), {"content": [
        {"type": "text", "text": "Part one"},
        {"type": "tool_use", "id": "x"},   # should be skipped
        {"type": "text", "text": "Part two"},
    ]})()]
}
out = _extract_response(multi_result)
print("\nTest 3 (multi blocks):", repr(out))
assert "Part one" in out and "Part two" in out, f"FAIL: {out}"
print("  PASSED")

print("\nAll tests passed!")
