from dotenv import load_dotenv
import os
load_dotenv("/mnt/f/deep_agent/.env")
k = os.environ.get("OPENAI_API_KEY", "")
print("OPENAI_API_KEY set:", bool(k) and not k.startswith("your_"))
print("Key prefix:", k[:10] if k else "none")
k2 = os.environ.get("ANTHROPIC_API_KEY", "")
print("ANTHROPIC_API_KEY set:", bool(k2) and not k2.startswith("your_"))
