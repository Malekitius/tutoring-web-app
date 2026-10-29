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
            formatted.append(r"\(\displaystyle " + validate_math(part[1:-1]) + r"\)")
        else:
            formatted.append(escape_text(part).replace("\n", r"\par " + "\n"))
    return "".join(formatted)


def format_body(value):
    """Give paragraphs, lettered subparts and standalone formulas room to breathe."""
    paragraphs = []
    for line in (value or "").splitlines():
        line = line.strip()
        if not line:
            paragraphs.append(r"\smallskip")
            continue
        equation = re.fullmatch(r"\$([^$]+)\$\s*([.,;:]?)", line)
        if equation:
            paragraphs.append(r"\noindent\hspace*{7mm}\(\displaystyle " + validate_math(equation[1]) + equation[2] + r"\)\par")
        else:
            hanging = r"\hangindent=7mm\hangafter=1 " if re.match(r"^(?:[а-яa-z]|\d{1,2})\)\s", line, re.I) else ""
            paragraphs.append(hanging + format_text(line) + r"\par")
    return "\n".join(paragraphs)


def build_source(worksheet, include_answers=False, figure_paths=None):
    title = escape_text(worksheet.title)
    owner = getattr(worksheet, "school_class", None) or worksheet.student
    owner_label = "Класс" if getattr(worksheet, "school_class_id", None) else "Ученик"
    label = "Домашняя работа" if worksheet.kind == "homework" else "Задания на урок"
    metadata = [r"\textbf{" + owner_label + ":} " + escape_text(owner.name)]
    if getattr(worksheet, "lesson_id", None):
        metadata.append(r"\textbf{Занятие:} " + worksheet.lesson.date.strftime("%d.%m.%Y"))
    if worksheet.due_date:
        metadata.append(r"\textbf{Срок сдачи:} " + worksheet.due_date.strftime("%d.%m.%Y"))
    items = list(worksheet.items.prefetch_related("figures").all())
    blocks = [r"\documentclass[12pt,a4paper,fleqn]{article}",
              r"\usepackage{fontspec}", r"\usepackage{amsmath,amssymb,xcolor,graphicx}",
              r"\usepackage[russian]{babel}",
              r"\usepackage{needspace,fancyhdr}",
              r"\usepackage[left=19mm,right=19mm,top=18mm,bottom=22mm,footskip=11mm]{geometry}",
              r"\setmainfont{Arial}",
              r"\setsansfont{Arial}", r"\definecolor{forest}{HTML}{285A43}",
              r"\definecolor{muted}{HTML}{66716A}", r"\definecolor{rulegray}{HTML}{DCE3DD}",
              r"\DeclareMathSizes{12}{15}{10.5}{8}",
              r"\linespread{1.12}", r"\setlength{\parindent}{0pt}", r"\setlength{\parskip}{5pt}",
              r"\setlength{\mathindent}{7mm}",
              r"\setlength{\abovedisplayskip}{7pt}\setlength{\belowdisplayskip}{7pt}",
              r"\setlength{\abovedisplayshortskip}{4pt}\setlength{\belowdisplayshortskip}{7pt}",
              r"\emergencystretch=2em\raggedbottom\frenchspacing",
              r"\clubpenalty=10000\widowpenalty=10000\displaywidowpenalty=10000",
              r"\newbox\taskbox",
              r"\newenvironment{taskblock}{\par\addvspace{4mm}\setbox\taskbox=\vbox\bgroup\hsize=\linewidth}{\par\egroup\ifdim\dimexpr\ht\taskbox+\dp\taskbox\relax<.85\textheight\Needspace{\dimexpr\ht\taskbox+\dp\taskbox\relax}\box\taskbox\else\Needspace{40mm}\unvbox\taskbox\fi\par}",
              r"\pagestyle{fancy}\fancyhf{}\renewcommand{\headrulewidth}{0pt}",
              r"\renewcommand{\footrulewidth}{0.3pt}",
              r"\fancyfoot[L]{\footnotesize\color{muted} " + label + (" / Решения" if include_answers else "") + "}",
              r"\fancyfoot[R]{\footnotesize\color{muted}\thepage}",
              r"\begin{document}",
              r"{\fontsize{10}{13}\selectfont\bfseries\color{forest} " + label.upper() + (" / РЕШЕНИЯ" if include_answers else "") + r"}\par\vspace{2mm}",
              r"{\fontsize{23}{28}\selectfont\bfseries " + title + r"}\par",
              r"\vspace{2mm}{\small\color{muted} " + r"\par ".join(metadata) + r"\par}",
              r"\vspace{4mm}{\color{forest}\hrule height 1pt}\vspace{5mm}"]
    if worksheet.instructions:
        blocks += [r"{\small\bfseries\color{forest} КАК РАБОТАТЬ}\par", format_body(worksheet.instructions), r"\vspace{4mm}"]
    for index, item in enumerate(items, start=1):
        figures = list(item.figures.all())
        blocks += [r"\begin{taskblock}",
                   r"\noindent\begin{minipage}[t]{10mm}\vspace{0pt}{\color{forest}\fontsize{16}{19}\selectfont\bfseries " + f"{index:02}" + r"}\end{minipage}%",
                   r"\begin{minipage}[t]{\dimexpr\linewidth-10mm\relax}\vspace{0pt}{\fontsize{13}{17}\selectfont\bfseries " + escape_text(item.title) + r"}\end{minipage}\par\nobreak\vspace{2mm}",
                   format_body(item.prompt)]
        for figure in figures:
            path = (figure_paths or {}).get(str(figure.id))
            if path:
                blocks += [r"\par\vspace{2mm}{\centering\includegraphics[width=.90\linewidth,height=68mm,keepaspectratio]{" + path + r"}\par}\vspace{3mm}"]
        if include_answers:
            blocks += [r"\par\nobreak\vspace{2mm}{\small\bfseries\color{forest} РЕШЕНИЕ И ОТВЕТ}\par\nobreak",
                       format_body(item.answer) if item.answer else "Решение не добавлено.\\par"]
            if item.source_ref:
                blocks += [r"{\footnotesize\color{muted} Источник: " + escape_text(item.source_ref) + r"\par}"]
        blocks += [r"\end{taskblock}"]
    if not items:
        blocks.append("Задачи пока не добавлены.")
    blocks += [r"\end{document}"]
    return "\n".join(blocks)


def build_pdf(worksheet, include_answers=False):
    compiler = which("xelatex")
    if not compiler:
        raise ValueError("Для экспорта PDF установите XeLaTeX")
    with tempfile.TemporaryDirectory(prefix="tutor-pdf-") as directory:
        figures_dir = Path(directory) / "figures"
        figures_dir.mkdir()
        figure_paths = {}
        for item in worksheet.items.all():
            for figure in item.figures.all():
                name = f"figures/{figure.id}.png"
                with figure.file.open("rb") as source_image:
                    (Path(directory) / name).write_bytes(source_image.read())
                figure_paths[str(figure.id)] = name
        source = build_source(worksheet, include_answers, figure_paths)
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
