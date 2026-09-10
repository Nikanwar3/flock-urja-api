"""Regenerate openapi.json from the FastAPI app's own schema.

Run whenever routes/models change:

    python scripts/export_openapi.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

if __name__ == "__main__":
    schema = app.openapi()
    out_path = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {out_path}")
