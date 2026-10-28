"""Icon palette for student subjects. IDs are stored; symbols are presentation data."""

SUBJECT_ICONS = [
    {"id": "general", "symbol": "◇", "label": "Любой предмет", "names": []},
    {"id": "math", "symbol": "∑", "label": "Математика", "names": ["математика"]},
    {"id": "algebra", "symbol": "x²", "label": "Алгебра", "names": ["алгебра"]},
    {"id": "geometry", "symbol": "△", "label": "Геометрия", "names": ["геометрия"]},
    {"id": "physics", "symbol": "φ", "label": "Физика", "names": ["физика"]},
    {"id": "chemistry", "symbol": "⚗", "label": "Химия", "names": ["химия"]},
    {"id": "informatics", "symbol": "⌨", "label": "Информатика", "names": ["информатика", "программирование"]},
    {"id": "russian", "symbol": "Я", "label": "Русский язык", "names": ["русский язык"]},
    {"id": "literature", "symbol": "✒", "label": "Литература", "names": ["литература"]},
    {"id": "languages", "symbol": "Aa", "label": "Иностранные языки", "names": ["английский язык", "немецкий язык", "французский язык", "испанский язык", "китайский язык", "иностранный язык"]},
    {"id": "history", "symbol": "⌛", "label": "История", "names": ["история"]},
    {"id": "social", "symbol": "⚖", "label": "Обществознание", "names": ["обществознание"]},
    {"id": "geography", "symbol": "🌍", "label": "География", "names": ["география"]},
    {"id": "biology", "symbol": "🧬", "label": "Биология", "names": ["биология"]},
    {"id": "ecology", "symbol": "🌱", "label": "Экология", "names": ["экология"]},
    {"id": "astronomy", "symbol": "✦", "label": "Астрономия", "names": ["астрономия"]},
    {"id": "world", "symbol": "🌿", "label": "Окружающий мир", "names": ["окружающий мир"]},
    {"id": "economics", "symbol": "₽", "label": "Экономика", "names": ["экономика"]},
    {"id": "law", "symbol": "§", "label": "Право", "names": ["право"]},
    {"id": "art", "symbol": "🎨", "label": "ИЗО", "names": ["изо", "изобразительное искусство"]},
    {"id": "music", "symbol": "♫", "label": "Музыка", "names": ["музыка"]},
    {"id": "technology", "symbol": "⚙", "label": "Технология", "names": ["технология", "труд"]},
    {"id": "sport", "symbol": "🏃", "label": "Физкультура", "names": ["физкультура", "физическая культура"]},
    {"id": "safety", "symbol": "🛡", "label": "ОБЗР", "names": ["обзр", "обж", "основы безопасности и защиты родины"]},
]

SUBJECT_ICON_IDS = {icon["id"] for icon in SUBJECT_ICONS}


def default_icon_for_name(name):
    normalized = name.strip().casefold()
    return next(
        (icon["id"] for icon in SUBJECT_ICONS if normalized in icon["names"]),
        "general",
    )
