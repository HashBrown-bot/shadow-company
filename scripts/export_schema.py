import json
from pathlib import Path

from packages.contracts.config import Configuration

if __name__ == "__main__":
    path = Path("packages/contracts/schema.v0.2.json")
    path.write_text(json.dumps(Configuration.model_json_schema(), ensure_ascii=False, indent=2) + "\n")
    print(path)
