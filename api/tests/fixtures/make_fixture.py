"""Regenerates fixture_3p.pdf: 3 pages, two headings, no table of contents, invented notes only."""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).with_name("fixture_3p.pdf")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=15)
HEADING = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=8)

PAGE_1 = [
    "A process is a program that is currently being executed by the operating system.",
    "Each process owns a private address space that other processes cannot read directly.",
    "The process control block stores the saved registers and the state of a process.",
]
PAGE_2 = [
    "A context switch saves the state of the running process and restores the state of another.",
    "Time spent on a context switch does no useful work for any user program.",
    "A process in the waiting state cannot run until the event it needs has occurred.",
]
PAGE_3 = [
    "Round-robin scheduling gives each process a fixed time quantum on the processor.",
    "A preempted process moves to the back of the ready queue under round-robin scheduling.",
    "Shortest job first scheduling picks the process with the smallest expected burst time.",
    "Priority scheduling can starve low priority processes unless ageing raises their priority.",
]


def _paragraphs(sentences: list[str]) -> list:
    out = []
    for sentence in sentences:
        out += [Paragraph(sentence, BODY), Spacer(1, 8)]
    return out


def main() -> None:
    story = [Paragraph("Process Management", HEADING)]
    story += _paragraphs(PAGE_1) + [PageBreak()]
    story += _paragraphs(PAGE_2) + [PageBreak()]
    story += [Paragraph("CPU Scheduling", HEADING)] + _paragraphs(PAGE_3)
    SimpleDocTemplate(str(OUT), pagesize=A4, invariant=1).build(story)


if __name__ == "__main__":
    main()
