"""Sandbox demo accounts, shared by every client (ADR 0013).

The web app signs in with one; an MCP client passes the same name or id as
``asker_name``, so one person's requests are the same records whichever
client they use. Invented names, no real people, no real identity.
"""

from __future__ import annotations

import re

from courts_analyst.core.desk.models import Actor, Role

DEMO_ACCOUNTS: dict[str, Actor] = {
    a.account_id: a
    for a in (
        Actor(account_id="priya", name="Priya Shah", role="congressional_staff"),
        Actor(account_id="sam", name="Sam Ortega", role="journalist"),
        Actor(account_id="rae", name="Rae Kim", role="researcher"),
        Actor(account_id="alex", name="Alex Doe", role="public"),
    )
}


def resolve(name: str, role: Role = "public") -> Actor:
    """A demo account by id, full name or first name; anyone else gets an
    account of their own, keyed by their name."""
    key = name.strip().lower()
    for a in DEMO_ACCOUNTS.values():
        if key in {a.account_id, a.name.lower(), a.name.split()[0].lower()}:
            return a
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "user"
    return Actor(account_id=f"mcp:{slug}", name=name.strip(), role=role)
