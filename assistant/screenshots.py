"""Read temporary screenshot uploads and prepare bounded image inputs."""

import io
import json
import base64
import math
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from students.views import body


MAX_SCREENSHOTS = 6
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024


def generation_data(request):
    if request.content_type != "multipart/form-data":
        return body(request)
    if set(request.FILES) - {"screenshots"}:
        raise ValueError("Прикрепите скриншоты в формате PNG, JPEG или WebP")
    raw = request.POST.get("payload", "")
    if not raw or len(raw.encode("utf-8")) > 1_000_000:
        raise ValueError("Размер запроса недопустим")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Некорректные параметры генерации") from None
    if not isinstance(data, dict):
        raise ValueError("Ожидались параметры генерации")
    return data


def prepare_screenshots(uploads):
    if len(uploads) > MAX_SCREENSHOTS:
        raise ValueError("Можно прикрепить не более 6 скриншотов")
    if sum(upload.size for upload in uploads) > MAX_TOTAL_BYTES:
        raise ValueError("Общий размер скриншотов должен быть не больше 30 МБ")
    images = []
    for index, upload in enumerate(uploads, 1):
        background = screenshot_image(upload, index)
        background.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        background.save(output, format="PNG", optimize=True)
        mime = "image/png"
        if output.tell() > MAX_IMAGE_BYTES:
            mime = "image/jpeg"
            for _ in range(4):
                output = io.BytesIO()
                background.save(output, format="JPEG", quality=88, optimize=True)
                if output.tell() <= MAX_IMAGE_BYTES:
                    break
                background.thumbnail((round(background.width * .8), round(background.height * .8)), Image.Resampling.LANCZOS)
        if output.tell() > MAX_IMAGE_BYTES:
            raise ValueError(f"Скриншот {index}: не удалось уменьшить изображение")
        images.append((mime, output.getvalue()))
    return images


def screenshot_image(upload, index=1):
    """Decode the original at full resolution, orient it and remove metadata."""
    if not 0 < upload.size <= MAX_FILE_BYTES:
        raise ValueError(f"Скриншот {index}: файл должен быть не больше 10 МБ")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as original:
                if original.format not in {"PNG", "JPEG", "WEBP"} or getattr(original, "n_frames", 1) != 1:
                    raise ValueError(f"Скриншот {index}: нужен PNG, JPEG или WebP без анимации")
                if min(original.size) < 32 or original.width * original.height > 24_000_000:
                    raise ValueError(f"Скриншот {index}: недопустимый размер изображения")
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGBA")
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                return background
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError(f"Не удалось прочитать скриншот {index}. Выберите PNG, JPEG или WebP") from None


def crop_screenshot(upload, data):
    from assignments.figures import MAX_FIGURE_BYTES, figure_data

    try:
        bounds = [float(data.get(key)) for key in ("x", "y", "width", "height")]
    except (TypeError, ValueError):
        raise ValueError("Выделите область рисунка на скриншоте") from None
    x, y, width, height = bounds
    if not all(map(math.isfinite, bounds)) or not (
        0 <= x < 1 and 0 <= y < 1 and .02 <= width <= 1 - x + 1e-9 and .02 <= height <= 1 - y + 1e-9
    ):
        raise ValueError("Выделите область рисунка на скриншоте")
    image = screenshot_image(upload)
    crop = image.crop((round(x * image.width), round(y * image.height),
                       round((x + width) * image.width), round((y + height) * image.height)))
    if min(crop.size) < 60:
        raise ValueError("Выделенная область слишком мала. Выделите рисунок целиком")
    crop.thumbnail((4000, 4000), Image.Resampling.LANCZOS)
    for _ in range(8):
        output = io.BytesIO()
        crop.save(output, format="PNG", optimize=True)
        if output.tell() <= MAX_FIGURE_BYTES:
            break
        crop.thumbnail((round(crop.width * .8), round(crop.height * .8)), Image.Resampling.LANCZOS)
    result = {"png": base64.b64encode(output.getvalue()).decode("ascii"),
              "source_title": f"Скриншот: {upload.name}"[:160], "source_page": 1}
    figure_data(result)
    return result
