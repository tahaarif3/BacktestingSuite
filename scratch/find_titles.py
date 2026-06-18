import re

file_path = r"C:\Users\bigbo\.gemini\antigravity\brain\b893ee35-9f09-4e71-9a97-b38f187bcc51\.system_generated\steps\142\content.md"

with open(file_path, "r", encoding="utf-8") as f:
    html_content = f.read()

video_ids = ['oIyfZTYQbtk', 'gBd5cg5ELN0', 'TE2BVmeVhJw', 'yAjzj2eShXU', '4LIAHVXnpbY', 'gnKbAAVUzro', 'PbKOrSottRQ', 'OryO301RmX8', 'eQAuGKayM80']

for vid in video_ids:
    # Find occurrences of vid
    for match in re.finditer(re.escape(vid), html_content):
        # Scan backward and forward to find "title":{"runs":[{"text":"..."}] or similar
        start = max(0, match.start() - 1000)
        end = min(len(html_content), match.end() + 1000)
        snippet = html_content[start:end]
        
        # Let's search for "title" in the snippet
        # Look for "title":{"runs":[{"text":"..."}]}
        title_match = re.search(r'"title":\s*\{\s*"runs":\s*\[\s*\{\s*"text":\s*"([^"]+)"', snippet)
        if title_match:
            print(f"Video ID: {vid} -> Title: {title_match.group(1)}")
            break
        
        # Try another title pattern
        title_match = re.search(r'"title":\s*\{\s*"accessibility":\s*\{\s*"accessibilityData":\s*\{\s*"label":\s*"([^"]+)"', snippet)
        if title_match:
            print(f"Video ID: {vid} -> Title/Label: {title_match.group(1)}")
            break
            
        # Try finding standard link title: title="..."
        title_match = re.search(r'title="([^"]+)"', snippet)
        if title_match:
            print(f"Video ID: {vid} -> title attribute: {title_match.group(1)}")
            break
            
        # Try general title quotes
        title_match = re.search(r'"title":\s*"([^"]+)"', snippet)
        if title_match:
            print(f"Video ID: {vid} -> Title: {title_match.group(1)}")
            break
