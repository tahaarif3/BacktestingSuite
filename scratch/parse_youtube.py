import re

file_path = r"C:\Users\bigbo\.gemini\antigravity\brain\b893ee35-9f09-4e71-9a97-b38f187bcc51\.system_generated\steps\142\content.md"

with open(file_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Let's search for "title": in a simpler way, or print out some snippets of the HTML
print("HTML Length:", len(html_content))

# Look for titles in video renderers or json
# Standard format: "title":{"runs":[{"text":"..."}]
matches = re.findall(r'"title":\s*\{\s*"runs":\s*\[\s*\{\s*"text":\s*"([^"]+)"', html_content)
if not matches:
    # Try another pattern
    matches = re.findall(r'"title":\s*\{\s*"accessibility":\s*\{\s*"accessibilityData":\s*\{\s*"label":\s*"([^"]+)"', html_content)

if not matches:
    # Try searching for video titles in og:title or similar meta tags
    matches = re.findall(r'<meta name="title" content="([^"]+)"', html_content)
    
if not matches:
    # Try finding any occurrences of "title":
    matches = re.findall(r'"title":\s*"([^"]+)"', html_content)

print(f"Found {len(matches)} matches:")
for idx, m in enumerate(matches[:50], 1):
    print(f"{idx}. {m}")
