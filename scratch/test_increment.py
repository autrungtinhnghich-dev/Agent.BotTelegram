def increment_tag(tag: str) -> str:
    if not tag:
        return "v1.0.0"
        
    prefix = ""
    if tag.lower().startswith("v"):
        prefix = tag[0]
        tag_num = tag[1:]
    else:
        tag_num = tag
        
    parts = tag_num.split(".")
    if len(parts) != 3:
        return prefix + tag_num + ".1"
        
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])
    except ValueError:
        return prefix + tag_num + ".1"
        
    if patch == 9:
        minor += 1
        patch = 0
    else:
        patch += 1
        
    return f"{prefix}{major}.{minor}.{patch}"

# Test cases
test_cases = [
    ("v1.0.0", "v1.0.1"),
    ("v1.0.9", "v1.1.0"),
    ("1.0.9", "1.1.0"),
    ("v1.5.9", "v1.6.0"),
    ("v1.1.3", "v1.1.4"),
    ("", "v1.0.0"),
    (None, "v1.0.0"),
]

all_passed = True
for inp, expected in test_cases:
    out = increment_tag(inp)
    if out == expected:
        print(f"PASS: {inp} -> {out}")
    else:
        print(f"FAIL: {inp} -> Expected {expected}, got {out}")
        all_passed = False

if all_passed:
    print("All tests passed!")
