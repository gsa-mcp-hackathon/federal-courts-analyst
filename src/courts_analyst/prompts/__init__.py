"""Prompts: canned analyses that appear in clients as slash commands.

Each renders instructions that steer the model to the right tools and to the
server's reporting rules (cite editions, never mix them, label inference,
stay neutral).
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from courts_analyst.core.courts import COURTS

RULES = (
    "Rules: cite the edition and table for every figure; when editions disagree, "
    "give both and say which is current; never average or mix editions; label "
    "anything marked 'inferred' as inference, not an official statement; report n "
    "with cohort statistics and say when there are too few cases; stay neutral "
    "(explain the statistics, don't argue for policy outcomes such as new "
    "judgeships); never rank or profile individual judges."
)


def _name(code: str) -> str:
    c = COURTS.get(code)
    return f"{c.citation or c.name} ({code})" if c else code


def register_prompts(mcp: FastMCP) -> None:
    """Register all prompts with the MCP server."""

    @mcp.prompt(
        name="district_caseload_profile",
        title="District caseload profile",
        description="A sourced profile of one district's civil caseload for a year.",
    )
    def district_caseload_profile(
        court: Annotated[str, Field(description="District code, e.g. FL-N.")],
        fiscal_year: Annotated[str, Field(description="Fiscal year, e.g. 2024.")],
    ) -> str:
        return (
            f"Profile the civil caseload of {_name(court)} in FY{fiscal_year}.\n\n"
            "1. get_official_figure for civil_cases_filed, civil_cases_terminated, "
            "civil_cases_pending and civil_median_months_to_disposition.\n"
            "2. judgeship_context for weighted filings per judgeship against the "
            "Judicial Conference thresholds.\n"
            f"3. explain_change for civil_cases_filed from FY{int(fiscal_year) - 1} "
            f"to FY{fiscal_year}.\n"
            "4. find_cases for the year and summarise the top case types.\n\n"
            "Write a short, neutral profile with a table of the figures and their "
            f"editions.\n\n{RULES}"
        )

    @mcp.prompt(
        name="what_changed_and_why",
        title="What changed and why",
        description="Explain the change in a measure between two fiscal years.",
    )
    def what_changed_and_why(
        measure: Annotated[
            str, Field(description="e.g. civil_cases_filed or civil_filings.")
        ],
        period_from: Annotated[str, Field(description="Earlier fiscal year.")],
        period_to: Annotated[str, Field(description="Later fiscal year.")],
        court: Annotated[str, Field(description="US or a court code.")] = "US",
    ) -> str:
        return (
            f"Explain what changed in {measure} for {_name(court)} between "
            f"FY{period_from} and FY{period_to}, and why.\n\n"
            "1. explain_change with these arguments (if the server asks whether "
            "you mean a count or per-judgeship figure, ask the user).\n"
            "2. For the key contributors, say how much of the change each explains "
            "and what drove it; separate official facts, IDB-derived counts and "
            "inferences.\n"
            "3. If a driver says the figure was revised between editions, give "
            "both values with their editions.\n"
            "4. reconcile the later year's count if the IDB and official change "
            f"differ.\n\n{RULES}"
        )

    @mcp.prompt(
        name="judgeship_briefing",
        title="Judgeship briefing",
        description="A neutral, source-tagged briefing on one court's judgeship "
        "workload.",
    )
    def judgeship_briefing(
        court: Annotated[str, Field(description="District code, e.g. TX-E.")],
    ) -> str:
        return (
            f"Prepare a neutral briefing on judgeship workload in {_name(court)}.\n\n"
            "1. judgeship_context for the latest year and the four years before.\n"
            "2. compare_courts for weighted_total_filings_per_judgeship in the "
            "latest year, to place the court among all districts.\n"
            "3. State the Judicial Conference's thresholds and its own "
            "recommendation for the court, with sources. Don't say whether the "
            "court needs judgeships, and don't claim a judicial emergency (that "
            f"depends on vacancies, which the server doesn't track).\n\n{RULES}"
        )

    @mcp.prompt(
        name="compare_editions",
        title="Compare editions",
        description="Every published value of one statistic for one year, and how "
        "the editions differ.",
    )
    def compare_editions(
        measure: Annotated[
            str, Field(description="e.g. weighted_civil_filings_per_judgeship.")
        ],
        fiscal_year: Annotated[str, Field(description="Fiscal year, e.g. 2020.")],
        court: Annotated[str, Field(description="US or a court code.")] = "US",
    ) -> str:
        return (
            f"Show every published value of {measure} for {_name(court)} in "
            f"FY{fiscal_year}.\n\n"
            "1. get_official_figure (latest edition): it lists every edition that "
            "printed the figure and its revision status.\n"
            "2. If it was revised, get_official_figure with "
            "edition='first_published' as well, and explain_change for the "
            "surrounding years to see what the revision might concern.\n"
            "3. Present a table: edition, table, value. Say which is the current "
            "official figure and that the tables' notes don't explain the "
            f"revision unless they do.\n\n{RULES}"
        )

    @mcp.prompt(
        name="keep_this_answer",
        title="Keep this answer (request desk)",
        description="Save the last answer as a verified copy, ask the statistics "
        "office why a figure changed, or get notified if its numbers change.",
    )
    def keep_this_answer(
        option: Annotated[
            str,
            Field(description="ask_office, verified_copy or notify."),
        ] = "ask_office",
    ) -> str:
        return (
            "The user wants to keep your last answer on the request desk "
            f"(option '{option}'). It's a sandbox: nothing is sent to the AO or "
            "the FJC.\n\n"
            "1. If the option is ask_office, call check_inquiry_eligibility for "
            "the revised figure the answer is about. If it isn't eligible, say "
            "why and offer verified_copy instead.\n"
            "2. Call keep_answer with the question, your answer text exactly as "
            "you gave it, a citation (measure, court, fiscal_year, edition, value) "
            "for each official figure it quotes, and tool_calls: the read tools "
            "and arguments you used for the answer. Let the user confirm.\n"
            "3. If it isn't saved, show each problem the server lists, fix the "
            "answer (use the server's suggested figure, or label an earlier "
            "edition's value as first published), and try again.\n"
            "4. When it's saved, give the request number and the stamp, and say "
            "the user can follow it with my_requests.\n\n"
            "Never call keep_answer unless the user asked to keep the answer."
        )


__all__ = ["register_prompts"]
