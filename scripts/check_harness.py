from pathlib import Path

REQUIRED_FILES = [
    "AGENTS.md",
    "docs/architecture.md",
    "docs/roadmap.md",
    "docs/status.md",
    "docs/operator_semantics.md",
    "docs/decisions.md",
]

def main() -> None:
    missing = [path for path in REQUIRED_FILES if not Path(path).exists()]
    if missing:
        raise SystemExit("Missing harness files: " + ", ".join(missing))

    status = Path("docs/status.md").read_text(encoding="utf-8")
    roadmap = Path("docs/roadmap.md").read_text(encoding="utf-8")
    semantics = Path("docs/operator_semantics.md").read_text(encoding="utf-8")

    required_terms = [
        "M0",
        "M1",
        "M2",
        "M2.5",
        "M3",
        "Recursive",
        "GroupBy",
        "OrderBy",
        "Projection",
    ]

    for term in required_terms:
        if term not in roadmap + status + semantics:
            raise SystemExit(f"Harness term missing from docs: {term}")

    print("Harness check passed.")

if __name__ == "__main__":
    main()
