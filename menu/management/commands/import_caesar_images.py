import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from menu.models import Dish


DEFAULT_SOURCE_URL = "https://www.caesarandcompany.com/"

DISH_IMAGE_ALIASES = {
    "caesar salata menu": "caesar salad",
    "caesar salata, avoya icecek": "caesar salad",
    "cold brew no 1": "cold brew (finca milan & washed nitro)",
    "hypatia & americano": "hypatia",
    "pompei magnus & ev yapımı limonata": "pompei magnus",
    "vanilya latte": "vanilla latte",
}


def normalize_name(value):
    normalized = unicodedata.normalize(
        "NFKD",
        (value or "").strip().casefold(),
    )

    return "".join(
        char
        for char in normalized
        if not unicodedata.combining(char)
    )


def decode_js_string(value):
    return json.loads(f'"{value}"')


def extract_script_url(html, base_url):
    match = re.search(r'<script[^>]+src="([^"]+\.js)"', html)

    if match is None:
        return None

    return urljoin(base_url, match.group(1))


def extract_products(js_text):
    product_pattern = re.compile(
        r'\{name:"(?P<name>(?:\\.|[^"\\])*)",'
        r'displayName:"(?P<display_name>(?:\\.|[^"\\])*)",'
        r'description:(?:"(?:\\.|[^"\\])*"|null),'
        r'imageUrl:"(?P<image_url>https?://[^"]+)",'
        r'category:"(?P<category>(?:\\.|[^"\\])*)"\}'
    )

    products = []

    for match in product_pattern.finditer(js_text):
        products.append(
            {
                "name": decode_js_string(match.group("name")),
                "display_name": decode_js_string(
                    match.group("display_name")
                ),
                "image_url": match.group("image_url"),
                "category": decode_js_string(match.group("category")),
            }
        )

    return products


def build_session():
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.7,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; resto-image-importer/1.0)"
            ),
        }
    )

    return session


def get_extension_from_url(url):
    suffix = Path(urlparse(url).path).suffix.lower()

    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return suffix

    return ".webp"


class Command(BaseCommand):
    help = (
        "Downloads Caesar & Company dish images from the official menu "
        "site and attaches them to matching Dish records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-url",
            default=DEFAULT_SOURCE_URL,
            help="Official Caesar & Company menu URL.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Replace existing dish images.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print matches without saving images.",
        )

    def handle(self, *args, **options):
        source_url = options["source_url"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        session = build_session()

        self.stdout.write(f"Fetching {source_url}")
        html_response = session.get(source_url, timeout=30)
        html_response.raise_for_status()

        script_url = extract_script_url(html_response.text, source_url)

        if script_url is None:
            self.stderr.write("Could not find JS bundle on source page.")
            return

        self.stdout.write(f"Fetching {script_url}")
        js_response = session.get(script_url, timeout=30)
        js_response.raise_for_status()

        products = extract_products(js_response.text)
        products_by_name = {}

        for product in products:
            for key in (
                normalize_name(product["name"]),
                normalize_name(product["display_name"]),
            ):
                if key:
                    products_by_name.setdefault(key, product)

        matched = 0
        downloaded = 0
        skipped = 0

        for dish in Dish.objects.order_by("name"):
            dish_key = normalize_name(dish.name)
            product = products_by_name.get(dish_key)

            if product is None:
                product = products_by_name.get(
                    DISH_IMAGE_ALIASES.get(dish_key, "")
                )

            if product is None:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"No image match: {dish.name}"
                    )
                )
                continue

            matched += 1

            if dish.image and not overwrite:
                self.stdout.write(
                    f"Already has image: {dish.name} -> {dish.image.name}"
                )
                continue

            image_url = product["image_url"]
            filename = (
                f"{slugify(dish.name) or dish.pk}"
                f"{get_extension_from_url(image_url)}"
            )
            upload_name = f"caesar/{filename}"

            self.stdout.write(
                f"Match: {dish.name} -> {image_url}"
            )

            if dry_run:
                continue

            image_response = session.get(image_url, timeout=30)
            image_response.raise_for_status()

            dish.image.save(
                upload_name,
                ContentFile(image_response.content),
                save=True,
            )
            downloaded += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Image import finished. "
                f"Matched: {matched}. "
                f"Downloaded: {downloaded}. "
                f"Unmatched: {skipped}."
            )
        )
