"""Optical Character Recognition (OCR) module with preprocessing and page-level control.

Provides a fully local OCR pipeline using PyMuPDF rendering, Pillow/NumPy image
preprocessing (grayscale conversion, upscaling low-resolution inputs, orientation
correction when reliable, contrast enhancement, and selective denoising/thresholding),
and pytesseract interfacing with local Tesseract.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pymupdf
import pytesseract
from PIL import Image, ImageFilter, ImageOps

from app.document_processing.pdf_reader import PageContent
from app.document_processing.security import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_PAGES,
    OCRProcessingError,
    validate_pdf_file,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def _find_tesseract_binary() -> Optional[str]:
    """Locate local tesseract executable across standard system paths."""
    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        "/opt/anaconda3/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        os.path.abspath(".venv/bin/tesseract"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _compute_otsu_threshold(gray_arr: np.ndarray) -> int:
    """Compute global Otsu threshold cleanly using NumPy without OpenCV."""
    hist, _ = np.histogram(gray_arr.ravel(), bins=256, range=(0, 256))
    total = gray_arr.size
    if total == 0:
        return 128

    sum_total = float(np.dot(np.arange(256), hist))
    sum_bg = 0.0
    weight_bg = 0
    max_var = -1.0
    best_thresh = 128

    for t in range(256):
        weight_bg += int(hist[t])
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * float(hist[t])
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        var_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if var_between > max_var:
            max_var = var_between
            best_thresh = t

    return int(best_thresh)


@dataclass
class OCRConfig:
    """Configuration options controlling rendering DPI and Pillow preprocessing."""

    default_dpi: int = 300
    tesseract_config: str = "--oem 3 --psm 3"
    language: str = "eng"
    enable_preprocessing: bool = True
    grayscale: bool = True
    enhance_contrast: bool = True
    autocontrast_cutoff: int = 1
    upscale_low_res: bool = True
    min_upscale_width: int = 1200
    max_image_dimension: int = 4500
    selective_denoise: bool = True
    selective_threshold: bool = True
    auto_orient: bool = True
    min_osd_confidence: float = 2.0
    timeout_seconds: int = 30
    cache_enabled: bool = True
    max_cache_entries: int = 128


@dataclass
class OCRPageResult:
    """Detailed OCR output and telemetry for a single processed page/image."""

    page_number: int
    text: str
    char_count: int
    success: bool
    error: Optional[str] = None
    dpi: int = 300
    orientation_corrected_deg: int = 0
    preprocessing_steps: List[str] = field(default_factory=list)
    from_cache: bool = False


class OCRProcessor:
    """Handles configurable local OCR on images and selected PDF pages."""

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        default_dpi: int = 300,
        tesseract_config: str = "--oem 3 --psm 3",
        config: Optional[OCRConfig] = None,
    ) -> None:
        """Initialize OCRProcessor with local Tesseract configuration."""
        if config is not None:
            self.config = config
        else:
            self.config = OCRConfig(
                default_dpi=default_dpi,
                tesseract_config=tesseract_config,
            )

        self.default_dpi = self.config.default_dpi
        self.tesseract_config = self.config.tesseract_config
        self._ocr_cache: Dict[str, OCRPageResult] = {}

        cmd = tesseract_cmd or _find_tesseract_binary()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
            logger.info("OCRProcessor initialized with Tesseract at: %s", cmd)
        else:
            logger.warning(
                "Tesseract executable not found in PATH or standard locations. "
                "OCR calls may fail."
            )

    def _to_pil_image(self, image: Any) -> Image.Image:
        """Normalize PIL Image, bytes, or numpy array into a loaded PIL Image."""
        if image is None:
            raise ValueError("Cannot process None image in OCRProcessor.")

        if isinstance(image, Image.Image):
            return image.copy()

        try:
            if isinstance(image, (bytes, bytearray)):
                loaded = Image.open(io.BytesIO(image))
                loaded.load()
                return loaded
            converted = Image.fromarray(image)
            return converted
        except Exception as exc:
            err_msg = f"Failed to convert image for OCR: {exc}"
            logger.error("%s", err_msg)
            raise ValueError(err_msg) from exc

    def _detect_reliable_orientation(self, image: Image.Image) -> int:
        """Detect clockwise correction angle using Tesseract OSD when reliable."""
        if not self.config.auto_orient:
            return 0
        if image.width < 300 or image.height < 300:
            return 0
        try:
            osd_text = pytesseract.image_to_osd(
                image, config="--psm 0", timeout=min(10, self.config.timeout_seconds)
            )
            rot_match = re.search(r"Rotate:\s*(\d+)", osd_text)
            conf_match = re.search(r"Orientation confidence:\s*([0-9.]+)", osd_text)
            if not rot_match or not conf_match:
                return 0
            rotate_cw = int(rot_match.group(1))
            osd_conf = float(conf_match.group(1))
            if rotate_cw in (90, 180, 270) and osd_conf >= self.config.min_osd_confidence:
                return rotate_cw
        except Exception:
            # OSD can fail safely on sparse text or blank blocks; do not fail OCR.
            return 0
        return 0

    def preprocess_image(self, image: Image.Image) -> Tuple[Image.Image, List[str], int]:
        """Apply conservative Pillow preprocessing suitable for financial documents."""
        steps: List[str] = []
        orientation_deg = 0
        work = ImageOps.exif_transpose(image)

        if not self.config.enable_preprocessing:
            if work.mode not in ("RGB", "L"):
                work = work.convert("RGB")
            return work, steps, orientation_deg

        # 1. Upscale low-resolution inputs while enforcing memory upper bound
        if self.config.upscale_low_res and 0 < work.width < self.config.min_upscale_width:
            scale = min(3.0, self.config.min_upscale_width / float(work.width))
            new_w = min(int(round(work.width * scale)), self.config.max_image_dimension)
            new_h = min(int(round(work.height * scale)), self.config.max_image_dimension)
            if new_w > work.width and new_h > work.height:
                work = work.resize((new_w, new_h), Image.Resampling.LANCZOS)
                steps.append(f"upscale({new_w}x{new_h})")

        # 2. Downscale unexpectedly huge dimensions safely
        max_dim = max(work.width, work.height)
        if max_dim > self.config.max_image_dimension:
            shrink = self.config.max_image_dimension / float(max_dim)
            new_w = max(1, int(round(work.width * shrink)))
            new_h = max(1, int(round(work.height * shrink)))
            work = work.resize((new_w, new_h), Image.Resampling.LANCZOS)
            steps.append(f"clamp_size({new_w}x{new_h})")

        # 3. Grayscale conversion
        if self.config.grayscale and work.mode != "L":
            work = ImageOps.grayscale(work)
            steps.append("grayscale")

        # 4. Safe orientation correction before contrast thresholding
        rot_cw = self._detect_reliable_orientation(work)
        if rot_cw in (90, 180, 270):
            # PIL rotate() rotates counter-clockwise; negative turns clockwise rotation upright
            work = work.rotate(-rot_cw, expand=True, fillcolor=255)
            orientation_deg = rot_cw
            steps.append(f"rotate_cw_{rot_cw}")

        # 5. Contrast normalization when image spread or brightness is compressed
        arr = np.asarray(work)
        if self.config.enhance_contrast and arr.size > 0:
            p5, p95 = np.percentile(arr, [5, 95])
            if (p95 - p5) < 220 or p5 > 20:
                work = ImageOps.autocontrast(
                    work, cutoff=self.config.autocontrast_cutoff
                )
                arr = np.asarray(work)
                steps.append("autocontrast")

        # 6. Gentle selective denoising / thresholding only on low-contrast or noisy inputs
        if arr.size > 0 and work.mode == "L":
            dynamic_range = int(arr.max()) - int(arr.min())
            std_dev = float(arr.std())
            was_upscaled = any(s.startswith("upscale(") for s in steps)

            if self.config.selective_denoise and was_upscaled and std_dev > 15.0:
                work = work.filter(ImageFilter.MedianFilter(size=3))
                arr = np.asarray(work)
                steps.append("median_denoise")

            # Apply Otsu binarization when greyscale background is tinted/washed out
            bg_median = float(np.median(arr))
            if (
                self.config.selective_threshold
                and 15 < dynamic_range < 230
                and 40.0 < bg_median < 235.0
                and std_dev >= 8.0
            ):
                thresh = _compute_otsu_threshold(arr)
                work = work.point(lambda px: 255 if px >= thresh else 0, mode="L")
                steps.append(f"otsu_threshold({thresh})")

        return work, steps, orientation_deg

    def _make_cache_key(self, payload: bytes, dpi: int) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        return f"{digest}:{dpi}:{self.tesseract_config}:{self.config.enable_preprocessing}"

    def process_image_with_details(
        self,
        image: Any,
        page_number: int = 1,
        dpi: Optional[int] = None,
    ) -> OCRPageResult:
        """Run preprocessing and local Tesseract OCR with telemetry and caching."""
        resolution = dpi or self.default_dpi
        pil_img = self._to_pil_image(image)

        buf = io.BytesIO()
        try:
            pil_img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        finally:
            buf.close()

        cache_key = self._make_cache_key(img_bytes, resolution)
        if self.config.cache_enabled and cache_key in self._ocr_cache:
            cached = self._ocr_cache[cache_key]
            return OCRPageResult(
                page_number=page_number,
                text=cached.text,
                char_count=cached.char_count,
                success=cached.success,
                error=cached.error,
                dpi=resolution,
                orientation_corrected_deg=cached.orientation_corrected_deg,
                preprocessing_steps=list(cached.preprocessing_steps),
                from_cache=True,
            )

        processed_img: Optional[Image.Image] = None
        try:
            processed_img, steps, orient_deg = self.preprocess_image(pil_img)
            text = (
                pytesseract.image_to_string(
                    processed_img,
                    lang=self.config.language,
                    config=self.tesseract_config,
                    timeout=self.config.timeout_seconds,
                )
                or ""
            )
            result = OCRPageResult(
                page_number=page_number,
                text=text,
                char_count=len(text.strip()),
                success=True,
                error=None,
                dpi=resolution,
                orientation_corrected_deg=orient_deg,
                preprocessing_steps=steps,
                from_cache=False,
            )
            if self.config.cache_enabled:
                if len(self._ocr_cache) >= self.config.max_cache_entries:
                    self._ocr_cache.pop(next(iter(self._ocr_cache)))
                self._ocr_cache[cache_key] = result
            return result
        except Exception as exc:
            err_msg = f"OCR execution failed on page {page_number}: {exc}"
            logger.error("%s", err_msg)
            raise OCRProcessingError(err_msg) from exc
        finally:
            pil_img.close()
            if processed_img is not None:
                processed_img.close()

    def process_image(self, image: Any) -> str:
        """Extract text from an image using preprocessing and local Tesseract OCR."""
        try:
            res = self.process_image_with_details(image)
            return res.text
        except OCRProcessingError as exc:
            # Preserve RuntimeError inheritance compatibility for existing callers
            raise RuntimeError(str(exc)) from exc

    def ocr_page_with_details(
        self,
        page: pymupdf.Page,
        page_number: int = 1,
        dpi: Optional[int] = None,
    ) -> OCRPageResult:
        """Render one PyMuPDF page and perform OCR returning structured telemetry."""
        resolution = dpi or self.default_dpi
        pix = page.get_pixmap(dpi=resolution)
        img: Optional[Image.Image] = None
        try:
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.load()
            return self.process_image_with_details(
                img, page_number=page_number, dpi=resolution
            )
        finally:
            pix = None
            if img is not None:
                img.close()

    def ocr_page(self, page: pymupdf.Page, dpi: Optional[int] = None) -> str:
        """Render a single PyMuPDF page as a raster image and return OCR text."""
        try:
            return self.ocr_page_with_details(page, page_number=1, dpi=dpi).text
        except OCRProcessingError as exc:
            raise RuntimeError(str(exc)) from exc

    def ocr_pages(
        self,
        file_path: str,
        page_numbers: Optional[Sequence[int]] = None,
        dpi: Optional[int] = None,
    ) -> List[OCRPageResult]:
        """Run OCR selectively on specified 1-indexed pages (or all pages if None)."""
        validate_pdf_file(file_path, max_file_size_bytes=DEFAULT_MAX_FILE_SIZE_BYTES)
        resolution = dpi or self.default_dpi
        results: List[OCRPageResult] = []
        doc = pymupdf.open(file_path)
        try:
            if getattr(doc, "needs_pass", False):
                raise OCRProcessingError(
                    f"Cannot run OCR on password-protected PDF: {os.path.basename(file_path)}"
                )
            total_pages = len(doc)
            if total_pages > DEFAULT_MAX_PAGES:
                raise OCRProcessingError(
                    f"PDF page count ({total_pages}) exceeds OCR limit ({DEFAULT_MAX_PAGES})"
                )

            target_pages = (
                [p for p in page_numbers if 1 <= p <= total_pages]
                if page_numbers is not None
                else list(range(1, total_pages + 1))
            )

            for page_num in target_pages:
                page = doc[page_num - 1]
                try:
                    page_res = self.ocr_page_with_details(
                        page, page_number=page_num, dpi=resolution
                    )
                    results.append(page_res)
                except Exception as exc:
                    err = f"OCR failed for page {page_num} of {os.path.basename(file_path)}: {exc}"
                    logger.warning("%s", err)
                    results.append(
                        OCRPageResult(
                            page_number=page_num,
                            text="",
                            char_count=0,
                            success=False,
                            error=err,
                            dpi=resolution,
                        )
                    )
            return results
        finally:
            doc.close()

    def ocr_pdf(self, file_path: str, dpi: Optional[int] = None) -> List[PageContent]:
        """Perform OCR across all pages of a PDF document returning PageContent objects."""
        page_results = self.ocr_pages(file_path, page_numbers=None, dpi=dpi)
        pages: List[PageContent] = []
        for res in page_results:
            stripped = res.text.strip()
            alnum_count = sum(1 for ch in stripped if ch.isalnum())
            pages.append(
                PageContent(
                    page_number=res.page_number,
                    text=res.text,
                    char_count=len(stripped),
                    is_scanned=True,
                    has_images=True,
                    alnum_char_count=alnum_count,
                    extraction_method="ocr" if res.success else "error",
                    needs_ocr=False,
                    is_blank=res.success and alnum_count == 0,
                    error=res.error,
                )
            )
        return pages


__all__ = ["OCRConfig", "OCRPageResult", "OCRProcessor", "OCRProcessingError"]
