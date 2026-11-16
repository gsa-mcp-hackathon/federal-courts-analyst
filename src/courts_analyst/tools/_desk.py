"""What the request desk tools share: who the caller is.

MCP clients have no accounts, so a public caller is identified by the name
it passes: a demo account's name ("Priya") maps to the same account the web
app uses, so a request made from Claude Desktop shows in that person's My
requests (demo identity, no real identity collected). The two
staff tools exist only when ``desk_staff_mode`` is on, and act as the
simulated statistics office.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from courts_analyst.core.desk.accounts import resolve
from courts_analyst.core.desk.models import Actor

PublicRole = Literal["congressional_staff", "journalist", "researcher", "public"]

AskerName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=60,
        description="A display name for the asker (demo identity; the same name "
        "must be used for every call about one request).",
    ),
]
AskerRole = Annotated[PublicRole, Field(description="Who is asking.")]
IdempotencyKey = Annotated[
    str | None,
    Field(
        default=None,
        max_length=80,
        description="Any unique string; a retried call with the same key returns "
        "the first result instead of writing again.",
    ),
]
Confirm = Annotated[
    bool,
    Field(
        description="True once the user has agreed to this write. False (default) "
        "asks the user, or returns a preview if the client can't ask."
    ),
]

OFFICE = Actor(
    account_id="mcp-staff",
    name="Statistics office (simulated)",
    role="statistics_office",
    staff=True,
)


def public_actor(name: str, role: PublicRole = "public") -> Actor:
    """The demo account with this name (the same one the web app signs in
    with), or an account of the caller's own."""
    return resolve(name, role)
