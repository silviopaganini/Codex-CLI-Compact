"""
Find the best SWE-bench Lite instances for a dual-graph demo.
Scores each bug by how well its description matches code symbols.
Run: python pick_instances.py
"""
import json, re, pathlib

GOOD_REPOS = {"django", "requests", "flask", "scikit-learn", "sympy", "astropy"}

def files_touched(patch):
    return re.findall(r"^diff --git a/(.+?) b/", patch, re.MULTILINE)

def symbol_hits(text):
    """Count how many code-like terms (CamelCase, snake_case, dotted) appear in description."""
    camel   = re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z]+\b", text)   # CamelCase
    snake   = re.findall(r"\b[a-z]+_[a-z_]+\b", text)               # snake_case
    dotted  = re.findall(r"\b\w+\.\w+\(\)", text)                    # method.calls()
    return len(camel) + len(snake) + len(dotted)

results = []
path = pathlib.Path("swe_bench_lite.jsonl")
if not path.exists():
    print("swe_bench_lite.jsonl not found. Run the download step first.")
    raise SystemExit(1)

for line in path.open():
    r = json.loads(line)
    repo_short = r["repo"].split("/")[-1]
    if repo_short not in GOOD_REPOS:
        continue
    files = files_touched(r["patch"])
    if len(files) > 2:
        continue   # skip multi-file — harder to demo cleanly

    desc = r["problem_statement"]
    score = symbol_hits(desc)
    results.append({
        "id":    r["instance_id"],
        "repo":  r["repo"],
        "files": files,
        "score": score,
        "desc":  desc[:150].replace("\n", " "),
        "base_commit": r["base_commit"],
    })

results.sort(key=lambda x: -x["score"])

print(f"{'SCORE':>5}  {'INSTANCE':40}  FILES")
print("-" * 90)
for r in results[:15]:
    print(f"{r['score']:>5}  {r['id']:40}  {r['files']}")
    print(f"       {r['desc']}")
    print()

print("\n--- TOP 3 PICKS FOR DEMO ---")
for r in results[:3]:
    print(f"\n{r['id']}")
    print(f"  Repo:   {r['repo']}")
    print(f"  Commit: {r['base_commit']}")
    print(f"  Files:  {r['files']}")
    print(f"  Score:  {r['score']} symbol hits in description")
    print(f"  Clone:  git clone https://github.com/{r['repo']} /tmp/swe/{r['id']}")
    print(f"          cd /tmp/swe/{r['id']} && git checkout {r['base_commit']}")
