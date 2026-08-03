"""
Vercel build step (see pyproject.toml [tool.vercel.scripts]).

Vercel's Flask docs say Flask's own static_folder shouldn't be relied on
for static assets there — files under public/** are served directly by
Vercel's CDN instead, ahead of the Python function. Rather than duplicate
every static/ file by hand (and risk it going stale after a future edit),
this copies static/ -> public/static/ automatically on every deploy. The
result lands at the exact same URL Flask's url_for('static', filename=...)
already generates (default static_url_path is /static), so no template
changes were needed anywhere in the project.

static/uploads/ is intentionally excluded — there's no real upload feature
built yet, and even if there were, user-uploaded content shouldn't ship as
part of the deployed code bundle; that needs external storage (S3-style)
on a serverless host, since nothing written to disk at runtime persists
here anyway.

Only runs as part of `vercel.json`'s build hook — has no effect on local
`flask run`, which serves straight from static/ as normal.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "static"
DEST = ROOT / "public" / "static"


def main():
    if not SRC.exists():
        print("No static/ directory found — nothing to copy.")
        return

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in SRC.iterdir():
        if item.name == "uploads":
            continue
        target = DEST / item.name
        if item.is_dir():
            shutil.copytree(item, target)
            copied += sum(1 for _ in target.rglob("*") if _.is_file())
        else:
            shutil.copy2(item, target)
            copied += 1

    print(f"Copied {copied} static file(s) to public/static/ for Vercel's CDN.")


if __name__ == "__main__":
    main()
