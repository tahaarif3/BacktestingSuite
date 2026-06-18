import re

file_path = r"C:\Users\bigbo\.gemini\antigravity\brain\b893ee35-9f09-4e71-9a97-b38f187bcc51\.system_generated\steps\142\content.md"

with open(file_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Let's search for "videoId" and see what values it has
video_ids = re.findall(r'"videoId":\s*"([^"]+)"', html_content)
print(f"Found {len(video_ids)} videoId matches:")
print(set(video_ids))

# Let's search for watchEndpoint urls or watch?v=
watch_urls = re.findall(r'/watch\?v=([a-zA-Z0-9_-]+)', html_content)
print(f"Found {len(watch_urls)} watch url matches:")
print(set(watch_urls))

# Let's search for any text surrounding "videoId" in the text
for m in re.finditer(r'"videoId":\s*"([^"]+)"', html_content):
    start = max(0, m.start() - 100)
    end = min(len(html_content), m.end() + 200)
    print("--- SNIPPET ---")
    print(html_content[start:end])
    break # Just show one
