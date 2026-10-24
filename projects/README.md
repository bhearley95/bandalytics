# Research projects

Each folder holds the research and articles for one topic. Reusable API clients
and other shared tools live in `src/cards_tracker/`; project-specific searches
and analysis live here and import those tools.

Start each project with this layout:

```text
projects/<project_name>/
    README.md           Research question, approach, and commands
    analysis/           Python searches and analysis scripts
    data/
        raw/            Original query results and source snapshots
        processed/      Cleaned data and calculated results
    figures/            Charts and images for articles
    articles/           Markdown article drafts, one file per article
```

Use lowercase folder names with underscores. For additional projects, create a
new folder with this structure and write its research question in its README.
Use descriptive article filenames such as `01_initial_findings.md`.

Run scripts from the repository root using the existing environment:

```powershell
.\.env\Scripts\python.exe .\projects\<project_name>\analysis\<script_name>.py
```

Scripts can import shared tools with `from cards_tracker import NBAClient`.
Resolve data and output paths relative to the script so outputs always stay in
the project, regardless of the working directory:

```python
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = PROJECT_DIR / "data" / "raw"
```

Keep original query results separate from derived data. Record the player IDs,
date range, season type, retrieval date, and source alongside each saved search
so article numbers can be traced back to the research. Store source links and
methodology in drafts, including any limitations affecting the conclusions.
