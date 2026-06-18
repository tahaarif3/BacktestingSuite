import json
import re

file_path = r"C:\Users\bigbo\.gemini\antigravity\brain\b893ee35-9f09-4e71-9a97-b38f187bcc51\.system_generated\steps\142\content.md"

with open(file_path, "r", encoding="utf-8") as f:
    html_content = f.read()

matches = re.finditer(r'\{"lockupViewModel"', html_content)

for idx, m in enumerate(matches, 1):
    start_idx = m.start()
    brace_count = 0
    end_idx = start_idx
    for i in range(start_idx, len(html_content)):
        char = html_content[i]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break
                
    obj_str = html_content[start_idx:end_idx]
    try:
        obj = json.loads(obj_str)
        vm = obj["lockupViewModel"]
        metadata_vm = vm["metadata"]["lockupMetadataViewModel"]
        print(f"\n--- Item {idx} ---")
        print("Metadata VM Keys:", list(metadata_vm.keys()))
        # Print actual title text if present
        # In newer schema, title text is often inside title -> content or runs
        if "title" in metadata_vm:
            print("Title:", metadata_vm["title"])
    except Exception as e:
        print(f"Error parsing item {idx}: {e}")
