"""Select short, page-addressed excerpts from local teaching PDFs."""

import io
import re
import uuid

from pypdf import PdfReader, PdfWriter

from .models import Material


MAX_SELECTED_MATERIALS = 5
MAX_EXPLICIT_PAGES = 8
MAX_TEXT_CHARS = 14000
MAX_PDF_SNIPPET_BYTES = 20 * 1024 * 1024


def page_numbers(raw, total):
    if not isinstance(raw, str) or len(raw) > 100:
        raise ValueError("Укажите страницы в формате 12-15, 18")
    values = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            raise ValueError("Укажите страницы в формате 12-15, 18")
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise ValueError("Укажите страницы в формате 12-15, 18")
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= total or end - start > MAX_EXPLICIT_PAGES:
            raise ValueError("Выбранных страниц нет в PDF или их слишком много")
        values.update(range(start, end + 1))
        if len(values) > MAX_EXPLICIT_PAGES:
            raise ValueError("Можно выбрать не более 8 страниц за запрос")
    return sorted(values)


def selected_context(selections, owner, query):
    """Return (page-addressed text, small PDF slices, source labels)."""
    if selections in (None, []):
        return "", [], []
    if not isinstance(selections, list) or len(selections) > MAX_SELECTED_MATERIALS:
        raise ValueError("Выберите не более пяти материалов")
    seen = set()
    excerpts, files, refs = [], [], []
    explicit_total = 0
    snippet_bytes = 0
    tokens = [word[:5] for word in re.findall(r"[\wё]{4,}", query.casefold())]
    for row in selections:
        if not isinstance(row, dict) or set(row) - {"id", "pages"}:
            raise ValueError("Некорректный выбор материала")
        try:
            item_id = uuid.UUID(str(row.get("id")))
        except (TypeError, ValueError):
            raise ValueError("Некорректный ID материала") from None
        if item_id in seen:
            raise ValueError("Материал выбран дважды")
        seen.add(item_id)
        material = Material.objects.filter(id=item_id, **owner).first()
        if material is None:
            raise ValueError("Материал не относится к выбранной карточке")
        raw_pages = row.get("pages", "")
        if raw_pages:
            numbers = page_numbers(raw_pages, material.page_count)
            explicit_total += len(numbers)
            if explicit_total > MAX_EXPLICIT_PAGES:
                raise ValueError("Укажите не более 8 страниц суммарно")
            page_texts = dict(material.pages.filter(number__in=numbers).values_list("number", "text"))
            fragments = [f"[{material.title}, стр. {number}]\n{page_texts.get(number, '')}"
                         for number in numbers]
            if all(page_texts.get(number) for number in numbers) and sum(map(len, excerpts + fragments)) <= MAX_TEXT_CHARS:
                excerpts.extend(fragments)
                refs.append({"title": material.title, "pages": numbers})
                continue
            writer = PdfWriter()
            with material.file.open("rb") as source:
                reader = PdfReader(source)
                for number in numbers:
                    writer.add_page(reader.pages[number - 1])
            output = io.BytesIO()
            writer.write(output)
            if output.tell() > 15 * 1024 * 1024:
                raise ValueError("Выбранные страницы слишком велики для запроса")
            snippet_bytes += output.tell()
            if snippet_bytes > MAX_PDF_SNIPPET_BYTES:
                raise ValueError("Выбранные PDF вместе слишком велики для запроса")
            files.append((f"{material.title[:80]}.pdf", output.getvalue()))
            refs.append({"title": material.title, "pages": numbers})
            continue
        candidates = []
        for page in material.pages.exclude(text=""):
            lower = page.text.casefold()
            score = sum(lower.count(token) for token in set(tokens))
            if score:
                candidates.append((score, page.number, page.text))
        candidates.sort(key=lambda row: (-row[0], row[1]))
        chosen = sorted(candidates[:3], key=lambda row: row[1])
        if not chosen:
            raise ValueError(f"В материале «{material.title}» не найдена тема. Укажите нужные страницы вручную (для сканов это обязательно).")
        refs.append({"title": material.title, "pages": [number for _, number, _ in chosen]})
        excerpts.extend(f"[{material.title}, стр. {number}]\n{value[:4000]}" for _, number, value in chosen)
    return "\n\n".join(excerpts)[:MAX_TEXT_CHARS], files, refs
