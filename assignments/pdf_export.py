"""Compile a worksheet to a printable PDF without sending data off this computer."""

import re
import subprocess
import tempfile
from pathlib import Path
from shutil import which


ALLOWED_MATH_COMMANDS = {
    "frac", "dfrac", "tfrac", "sqrt", "cdot", "times", "div", "pm", "mp",
    "leq", "geq", "neq", "approx", "equiv", "pi", "alpha", "beta", "gamma",
    "delta", "Delta", "theta", "lambda", "mu", "sigma", "omega", "infty",
    "sum", "prod", "int", "sin", "cos", "tan", "log", "ln", "lim",
    "angle", "triangle", "perp", "parallel", "circ", "degree", "ldots",
    "overline", "underline", "vec", "widehat", "left", "right", "text",
    "mathrm", "mathbf", "mathbb", "mathcal", "overrightarrow", "to", "rightarrow",
    "in", "notin", "subset", "subseteq", "cup", "cap", "emptyset", "cdots",
    "boxed", "quad", "qquad", "displaystyle", "le", "ge", "ne", "Rightarrow",
    "Leftrightarrow", "implies", "iff",
}


def escape_text(value):
    mapping = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
               "&": r"\&", "#": r"\#", "%": r"\%", "_": r"\_",
               "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(mapping.get(char, char) for char in value)


def validate_math(value):
    if any(char in value for char in ("%", "#", "&", "~", "`")) or "^^" in value:
        raise ValueError("В формуле есть неподдерживаемые символы")
    for command in re.findall(r"\\([A-Za-z]+)", value):
        if command not in ALLOWED_MATH_COMMANDS:
            raise ValueError(f"В формуле используется неподдерживаемая команда \\{command}")
    if re.search(r"\\[^A-Za-z ,;:!]", value):
        raise ValueError("В формуле есть неподдерживаемая команда")
    if value.count("{") != value.count("}"):
        raise ValueError("Проверьте скобки в формуле")
    return value


def format_text(value):
    """Only $...$ segments are interpreted as TeX; ordinary text is escaped."""
    parts = re.split(r"(\$[^$\n]+\$)", value or "")
    formatted = []
    for part in parts:
        if part.startswith("$") and part.endswith("$") and len(part) > 2:
            formatted.append(r"\(" + validate_math(part[1:-1]) + r"\)")
        else:
            formatted.append(escape_text(part).replace("\n", r"\par " + "\n"))
    return "".join(formatted)


def build_source(worksheet, include_answers=False):
    title = escape_text(worksheet.title)
    student = escape_text(worksheet.student.name)
    label = "Домашняя работа" if worksheet.kind == "homework" else "Задания на урок"
    metadata = [r"\textbf{Ученик:} " + student]
    if worksheet.lesson_id:
        metadata.append(r"\textbf{Занятие:} " + worksheet.lesson.date.strftime("%d.%m.%Y"))
    if worksheet.due_date:
        metadata.append(r"\textbf{Срок сдачи:} " + worksheet.due_date.strftime("%d.%m.%Y"))
    blocks = [r"\documentclass[11pt,a4paper]{article}",
              r"\usepackage{fontspec}", r"\usepackage{amsmath,amssymb,xcolor}",
              r"\usepackage[margin=20mm]{geometry}", r"\setmainfont{Arial}",
              r"\setsansfont{Arial}", r"\definecolor{forest}{HTML}{285A43}",
              r"\setlength{\parindent}{0pt}", r"\setlength{\parskip}{5pt}",
              r"\begin{document}",
              r"{\small\bfseries\color{forest} " + label.upper() + (" / РЕШЕНИЯ" if include_answers else "") + r"}\par\vspace{2mm}",
              r"{\LARGE\bfseries " + title + r"}\par",
              r"\vspace{3mm}", r"\small " + r"\quad \textbar{} \quad ".join(metadata) + r"\normalsize",
              r"\vspace{4mm}\hrule\vspace{4mm}"]
    if worksheet.instructions:
        blocks += [r"\textbf{Инструкция.} " + format_text(worksheet.instructions) + r"\par", r"\vspace{3mm}"]
    for index, item in enumerate(worksheet.items.all(), start=1):
        blocks += [r"\textbf{Задача " + str(index) + r". " + escape_text(item.title) + r"}\par",
                   format_text(item.prompt) + r"\par", r"\vspace{5mm}"]
        if include_answers:
            blocks += [r"\textbf{Решение:} " + (format_text(item.answer) if item.answer else "Не добавлено") + r"\par", r"\vspace{4mm}"]
        else:
            blocks += [r"\vspace{13mm}"]
    if not worksheet.items.exists():
        blocks.append("Задачи пока не добавлены.")
    blocks += [r"\end{document}"]
    return "\n".join(blocks)


def build_pdf(worksheet, include_answers=False):
    compiler = which("xelatex")
    if not compiler:
        raise ValueError("Для экспорта PDF установите XeLaTeX")
    source = build_source(worksheet, include_answers)
    with tempfile.TemporaryDirectory(prefix="tutor-pdf-") as directory:
        tex_path = Path(directory) / "worksheet.tex"
        tex_path.write_text(source, encoding="utf-8")
        try:
            result = subprocess.run(
                [compiler, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", directory, str(tex_path)],
                cwd=directory, capture_output=True, timeout=30, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("Сборка PDF заняла слишком много времени") from None
        pdf_path = Path(directory) / "worksheet.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            raise ValueError("Не удалось собрать PDF. Проверьте формулы TeX в задачах.")
        return pdf_path.read_bytes()
