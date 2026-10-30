"""Read temporary screenshot uploads and prepare bounded image inputs."""

import io
import json
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
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError(f"Не удалось прочитать скриншот {index}. Выберите PNG, JPEG или WebP") from None
    return images
