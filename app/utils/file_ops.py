#app/utils/file_ops.py
import os
import json

def ensure_dir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)

def write_json_file(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
