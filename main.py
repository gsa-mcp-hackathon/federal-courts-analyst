"""Root entry point for local development.

Run locally:
    uv run python main.py

Or via the installed script:
    uv run courts-analyst
"""

from courts_analyst.app import main

if __name__ == "__main__":
    main()
