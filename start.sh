source venv/bin/activate
export $(grep -v ^s*# .env | xargs)
python mcp_pipe.py
