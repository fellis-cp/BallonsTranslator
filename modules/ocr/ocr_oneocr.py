import re
import numpy as np
import time
import cv2
import os
from typing import List
import ctypes
from ctypes import (
    Structure,
    byref,
    POINTER,
    c_int64,
    c_int32,
    c_float,
    c_ubyte,
    c_char,
    c_char_p,
)
from PIL import Image as PilImage
from contextlib import contextmanager
import logging

from .base import register_OCR, OCRBase, TextBlock


ONE_OCR_PATH = os.path.join("data", "models", "one-ocr")
MODEL_NAME = "oneocr.onemodel"
DLL_NAME = "oneocr.dll"
MODEL_KEY = b'kj)TGtrK>f]b[Piow.gU+nC@s""""""4'


c_int64_p = POINTER(c_int64)
c_float_p = POINTER(c_float)
c_ubyte_p = POINTER(c_ubyte)


class ImageStructure(Structure):
    _fields_ = [
        ("type", c_int32),
        ("width", c_int32),
        ("height", c_int32),
        ("_reserved", c_int32),
        ("step_size", c_int64),
        ("data_ptr", c_ubyte_p),
    ]


class BoundingBox(Structure):
    _fields_ = [("x1", c_float), ("y1", c_float), ("x2", c_float), ("y2", c_float)]


BoundingBox_p = POINTER(BoundingBox)

DLL_FUNCTIONS = [
    ("CreateOcrInitOptions", [c_int64_p], c_int64),
    ("OcrInitOptionsSetUseModelDelayLoad", [c_int64, c_char], c_int64),
    ("CreateOcrPipeline", [c_char_p, c_char_p, c_int64, c_int64_p], c_int64),
    ("CreateOcrProcessOptions", [c_int64_p], c_int64),
    ("OcrProcessOptionsSetMaxRecognitionLineCount", [c_int64, c_int64], c_int64),
    ("RunOcrPipeline", [c_int64, POINTER(ImageStructure), c_int64, c_int64_p], c_int64),
    ("GetImageAngle", [c_int64, c_float_p], c_int64),
    ("GetOcrLineCount", [c_int64, c_int64_p], c_int64),
    ("GetOcrLine", [c_int64, c_int64, c_int64_p], c_int64),
    ("GetOcrLineContent", [c_int64, POINTER(c_char_p)], c_int64),
    ("GetOcrLineBoundingBox", [c_int64, POINTER(BoundingBox_p)], c_int64),
    ("GetOcrLineWordCount", [c_int64, c_int64_p], c_int64),
    ("GetOcrWord", [c_int64, c_int64, c_int64_p], c_int64),
    ("GetOcrWordContent", [c_int64, POINTER(c_char_p)], c_int64),
    ("GetOcrWordBoundingBox", [c_int64, POINTER(BoundingBox_p)], c_int64),
    ("GetOcrWordConfidence", [c_int64, c_float_p], c_int64),
    ("ReleaseOcrResult", [c_int64], None),
    ("ReleaseOcrInitOptions", [c_int64], None),
    ("ReleaseOcrPipeline", [c_int64], None),
    ("ReleaseOcrProcessOptions", [c_int64], None),
]


@contextmanager
def suppress_output():
    devnull = os.open(os.devnull, os.O_WRONLY)
    original_stdout = os.dup(1)
    original_stderr = os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(original_stdout, 1)
        os.dup2(original_stderr, 2)
        os.close(original_stdout)
        os.close(original_stderr)
        os.close(devnull)


class OcrEngine:
    def __init__(self, config_dir, logger=None):
        self.ocr_dll = None
        self.init_options = None
        self.pipeline = None
        self.process_options = None
        self.config_dir = config_dir
        self.model_path = os.path.join(self.config_dir, MODEL_NAME)
        self.dll_path = os.path.join(self.config_dir, DLL_NAME)
        self.logger = logger or logging.getLogger(self.__class__.__name__)

        self._load_and_bind_dll()
        self.init_options = self._create_init_options()
        self.pipeline = self._create_pipeline()
        self.process_options = self._create_process_options()
        self.empty_result = {"text": "", "text_angle": None, "lines": []}

    def _load_and_bind_dll(self):
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if hasattr(kernel32, "SetDllDirectoryW"):
                kernel32.SetDllDirectoryW(str(self.config_dir))

            self.ocr_dll = ctypes.WinDLL(str(self.dll_path), use_last_error=True)
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.debug(f"DLL loaded successfully from: {self.dll_path}")

            for name, argtypes, restype in DLL_FUNCTIONS:
                try:
                    func = getattr(self.ocr_dll, name)
                    func.argtypes = argtypes
                    func.restype = restype
                except AttributeError as e:
                    raise RuntimeError(f"Missing DLL function: {name}") from e
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.debug("DLL functions bound successfully.")

        except (OSError, RuntimeError, AttributeError) as e:
            error_code = ctypes.get_last_error() if os.name == "nt" else 0
            raise RuntimeError(
                f"Failed to load/bind DLL ({self.dll_path}) or its dependencies from {self.config_dir}. Code: {error_code}. Error: {e}"
            ) from e

    def __del__(self):
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("OcrEngine destructor called. Releasing resources...")
        if self.ocr_dll:
            try:
                if self.process_options:
                    self.ocr_dll.ReleaseOcrProcessOptions(self.process_options)
                    if self.logger and getattr(
                        self.logger, "isEnabledFor", lambda level: False
                    )(logging.DEBUG):
                        self.logger.debug("Released OcrProcessOptions.")
                if self.pipeline:
                    self.ocr_dll.ReleaseOcrPipeline(self.pipeline)
                    if self.logger and getattr(
                        self.logger, "isEnabledFor", lambda level: False
                    )(logging.DEBUG):
                        self.logger.debug("Released OcrPipeline.")
                if self.init_options:
                    self.ocr_dll.ReleaseOcrInitOptions(self.init_options)
                    if self.logger and getattr(
                        self.logger, "isEnabledFor", lambda level: False
                    )(logging.DEBUG):
                        self.logger.debug("Released OcrInitOptions.")
            except Exception as e:
                log_func = self.logger.error if self.logger else print
                log_func(f"Error during resource release in OcrEngine destructor: {e}")
        elif self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug(
                "OcrEngine destructor: No DLL handle, nothing to release."
            )

    def _create_init_options(self):
        init_options = c_int64()
        self._check_dll_result(
            self.ocr_dll.CreateOcrInitOptions(byref(init_options)),
            "Init options creation failed",
        )
        self._check_dll_result(
            self.ocr_dll.OcrInitOptionsSetUseModelDelayLoad(init_options, 0),
            "Model loading config failed",
        )
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("Init options created.")
        return init_options

    def _create_pipeline(self):
        model_buf = ctypes.create_string_buffer(self.model_path.encode("utf-8"))
        key_buf = ctypes.create_string_buffer(MODEL_KEY)
        pipeline = c_int64()
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug(f"Creating pipeline with model: {self.model_path}")
        with suppress_output():
            self._check_dll_result(
                self.ocr_dll.CreateOcrPipeline(
                    model_buf, key_buf, self.init_options, byref(pipeline)
                ),
                f"Pipeline creation failed (model: {self.model_path})",
            )
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("Pipeline created successfully.")
        return pipeline

    def _create_process_options(self):
        process_options = c_int64()
        self._check_dll_result(
            self.ocr_dll.CreateOcrProcessOptions(byref(process_options)),
            "Process options creation failed",
        )
        self._check_dll_result(
            self.ocr_dll.OcrProcessOptionsSetMaxRecognitionLineCount(
                process_options, 1000
            ),
            "Line count config failed",
        )
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("Process options created.")
        return process_options

    def recognize_pil(self, image: PilImage.Image):
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        try:
            b, g, r, a = image.split()
            bgra_image = PilImage.merge("RGBA", (b, g, r, a))
        except ValueError:
            if self.logger:
                self.logger.warning(
                    "Could not split image into 4 channels for BGRA conversion, attempting RGB first."
                )
            rgb_image = image.convert("RGB")
            r, g, b = rgb_image.split()
            bgra_image = PilImage.merge("RGB", (b, g, r)).convert("RGBA")

        return self._process_image(
            cols=bgra_image.width,
            rows=bgra_image.height,
            step=bgra_image.width * 4,
            data=bgra_image.tobytes(),
        )

    def recognize_cv2(self, image_buffer: bytes):
        import cv2

        img = cv2.imdecode(np.frombuffer(image_buffer, np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError("cv2.imdecode failed to decode image buffer")

        channels = img.shape[2] if len(img.shape) == 3 else 1
        if channels == 1:
            img_bgra = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif channels == 3:
            img_bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        elif channels == 4:
            img_bgra = img
        else:
            raise ValueError(f"Unsupported number of channels in cv2 image: {channels}")

        return self._process_image(
            cols=img_bgra.shape[1],
            rows=img_bgra.shape[0],
            step=img_bgra.strides[0],
            data=img_bgra.ctypes.data,
        )

    def _process_image(self, cols, rows, step, data):
        if isinstance(data, bytes):
            data_array = (c_ubyte * len(data)).from_buffer_copy(data)
            data_ptr = data_array
        else:
            data_ptr = ctypes.cast(data, c_ubyte_p)

        img_struct = ImageStructure(
            type=3,
            width=cols,
            height=rows,
            _reserved=0,
            step_size=step,
            data_ptr=data_ptr,
        )
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug(
                f"Prepared ImageStructure: type={img_struct.type}, width={img_struct.width}, height={img_struct.height}, step={img_struct.step_size}"
            )
        return self._perform_ocr(img_struct)

    def _perform_ocr(self, image_struct: ImageStructure):
        ocr_result = c_int64()
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("Running OCR pipeline...")
        result_code = self.ocr_dll.RunOcrPipeline(
            self.pipeline, byref(image_struct), self.process_options, byref(ocr_result)
        )

        if result_code != 0:
            if self.logger:
                self.logger.warning(
                    f"RunOcrPipeline failed with native code: {result_code}"
                )
            return self.empty_result

        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("OCR pipeline finished successfully. Parsing results...")
        parsed_result = self._parse_ocr_results(ocr_result)
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("Releasing OCR result handle...")
        self.ocr_dll.ReleaseOcrResult(ocr_result)
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug("OCR result handle released.")
        return parsed_result

    def _parse_ocr_results(self, ocr_result: c_int64):
        line_count = c_int64()
        if self.ocr_dll.GetOcrLineCount(ocr_result, byref(line_count)) != 0:
            if self.logger:
                self.logger.warning("Failed to get OCR line count.")
            return self.empty_result

        num_lines = line_count.value
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug(f"Found {num_lines} lines in OCR result.")

        lines_data = self._get_lines(ocr_result, line_count)
        text_angle = self._get_text_angle(ocr_result)

        # Return raw lines, text construction will happen later
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            angle_str = f"{text_angle:.2f}" if text_angle is not None else "N/A"
            self.logger.debug(
                f"Parsed results: angle={angle_str}, {len(lines_data)} lines extracted."
            )

        return {
            "text": None,  # Text will be constructed in the main class
            "text_angle": text_angle,
            "lines": lines_data,
        }

    def _get_text_angle(self, ocr_result: c_int64):
        text_angle = c_float()
        if self.ocr_dll.GetImageAngle(ocr_result, byref(text_angle)) != 0:
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.debug("Failed to get image angle.")
            return None
        return text_angle.value

    def _get_lines(self, ocr_result: c_int64, line_count: c_int64):
        lines = []
        for idx in range(line_count.value):
            lines.append(self._process_line(ocr_result, idx))
        return lines

    def _process_line(self, ocr_result: c_int64, line_index: int):
        line_handle = c_int64()
        if self.ocr_dll.GetOcrLine(ocr_result, line_index, byref(line_handle)) != 0:
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.warning(
                    f"Failed to get handle for line index {line_index}."
                )
            return {"text": None, "bounding_rect": None, "words": []}

        line_text = self._get_line_text(line_handle)
        line_bbox = self._get_bounding_box(
            line_handle, self.ocr_dll.GetOcrLineBoundingBox
        )
        words = self._get_words(line_handle)
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            log_text = (
                (line_text[:50] + "...")
                if line_text and len(line_text) > 50
                else line_text
            )
            self.logger.debug(
                f"Processed line {line_index}: text='{log_text}', bbox={line_bbox}, words={len(words)}"
            )
        return {"text": line_text, "bounding_rect": line_bbox, "words": words}

    def _get_words(self, line_handle: c_int64):
        word_count = c_int64()
        if self.ocr_dll.GetOcrLineWordCount(line_handle, byref(word_count)) != 0:
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.debug("Failed to get word count for line.")
            return []
        num_words = word_count.value
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            self.logger.debug(f"Found {num_words} words in line.")
        words_data = []
        for idx in range(num_words):
            words_data.append(self._process_word(line_handle, idx))
        return words_data

    def _process_word(self, line_handle: c_int64, word_index: int):
        word_handle = c_int64()
        if self.ocr_dll.GetOcrWord(line_handle, word_index, byref(word_handle)) != 0:
            if self.logger and getattr(
                self.logger, "isEnabledFor", lambda level: False
            )(logging.DEBUG):
                self.logger.warning(
                    f"Failed to get handle for word index {word_index}."
                )
            return {"text": None, "bounding_rect": None, "confidence": None}

        word_text = self._get_word_text(word_handle)
        word_bbox = self._get_bounding_box(
            word_handle, self.ocr_dll.GetOcrWordBoundingBox
        )
        word_conf = self._get_word_confidence(word_handle)
        if self.logger and getattr(self.logger, "isEnabledFor", lambda level: False)(
            logging.DEBUG
        ):
            conf_str = f"{word_conf:.3f}" if word_conf is not None else "N/A"
            self.logger.debug(
                f"  Processed word {word_index}: text='{word_text}', bbox={word_bbox}, conf={conf_str}"
            )
        return {"text": word_text, "bounding_rect": word_bbox, "confidence": word_conf}

    def _get_line_text(self, line_handle: c_int64):
        content = c_char_p()
        if (
            self.ocr_dll.GetOcrLineContent(line_handle, byref(content)) == 0
            and content.value
        ):
            try:
                return content.value.decode("utf-8", errors="ignore")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error decoding line text: {e}")
                return None
        return None

    def _get_word_text(self, word_handle: c_int64):
        content = c_char_p()
        if (
            self.ocr_dll.GetOcrWordContent(word_handle, byref(content)) == 0
            and content.value
        ):
            try:
                return content.value.decode("utf-8", errors="ignore")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error decoding word text: {e}")
                return None
        return None

    def _get_word_confidence(self, word_handle: c_int64):
        confidence = c_float()
        if self.ocr_dll.GetOcrWordConfidence(word_handle, byref(confidence)) == 0:
            return confidence.value
        return None

    def _get_bounding_box(self, handle: c_int64, bbox_function):
        bbox_ptr = BoundingBox_p()
        if bbox_function(handle, byref(bbox_ptr)) == 0 and bbox_ptr:
            bbox = bbox_ptr.contents
            return {"x1": bbox.x1, "y1": bbox.y1, "x2": bbox.x2, "y2": bbox.y2}
        return None

    def _check_dll_result(self, result_code, error_message):
        if result_code != 0:
            raise RuntimeError(f"{error_message} (Native Code: {result_code})")


@register_OCR("one_ocr")
class OCROneAPI(OCRBase):
    params = {
        "newline_handling": {
            "type": "selector",
            "options": ["preserve", "remove"],
            "value": "preserve",
            "description": "Newline character handling in OCR result (preserve/remove)",
        },
        "reverse_line_order": {
            "type": "checkbox",
            "value": False,
            "description": "Reverse the order of detected text lines (for vertical CJK text)",
        },
        "no_uppercase": {
            "type": "checkbox",
            "value": False,
            "description": "Convert text to lowercase (except first letter of sentences)",
        },
        "description": "Local OCR using OneOCR library (Windows Only)",
    }

    @property
    def newline_handling(self):
        value = self.get_param_value("newline_handling")
        return value if value in ["preserve", "remove"] else "preserve"

    @property
    def no_uppercase(self):
        value = self.get_param_value("no_uppercase")
        return bool(value) if value is not None else False

    @property
    def reverse_line_order(self):
        value = self.get_param_value("reverse_line_order")
        return bool(value) if value is not None else False

    def __init__(self, **params) -> None:
        super().__init__(**params)

        self.engine = None
        self.available = False
        self.config_dir = ONE_OCR_PATH

        if os.name != "nt":
            if self.logger:
                self.logger.warning("OneOCR is Windows-only. system is not supported.")
            return

        try:
            if self.debug_mode and self.logger:
                self.logger.debug(f"Checking OneOCR data directory: {self.config_dir}")
            os.makedirs(self.config_dir, exist_ok=True)

            dll_path = os.path.join(self.config_dir, DLL_NAME)
            model_path = os.path.join(self.config_dir, MODEL_NAME)

            dll_exists = os.path.exists(dll_path)
            model_exists = os.path.exists(model_path)

            if not dll_exists or not model_exists:
                log_msg = "OneOCR initialization failed:"
                if not dll_exists:
                    log_msg += f" DLL not found at '{dll_path}'."
                if not model_exists:
                    log_msg += f" Model not found at '{model_path}'."
                log_msg += " Instructions for extracting these files can be found here: https://gist.github.com/bropines/063b822e6eb274151c512ef7a311f259"
                if self.logger:
                    self.logger.warning(log_msg)
                return

            if self.debug_mode and self.logger:
                self.logger.debug("DLL and Model found. Initializing OcrEngine...")

            self.engine = OcrEngine(self.config_dir, self.logger)
            self.available = True
            if self.logger:
                self.logger.info("OneOCR engine initialized successfully.")

        except Exception as e:
            if self.logger:
                log_level = logging.DEBUG if self.debug_mode else logging.ERROR
                self.logger.log(
                    log_level,
                    f"Failed to create OcrEngine instance: {e}",
                    exc_info=self.debug_mode,
                )
            self.engine = None
            self.available = False

    def _ocr_blk_list(
        self, img: np.ndarray, blk_list: List[TextBlock], *args, **kwargs
    ):
        if not self.available:
            if self.debug_mode and self.logger:
                self.logger.warning(
                    "OCR engine is not available, skipping block processing."
                )
            for blk in blk_list:
                blk.text = ""
            return

        im_h, im_w = img.shape[:2]
        if self.debug_mode and self.logger:
            self.logger.debug(
                f"Processing {len(blk_list)} blocks on image size: {im_h}x{im_w}"
            )

        for i, blk in enumerate(blk_list):
            x1, y1, x2, y2 = blk.xyxy
            if self.debug_mode and self.logger:
                self.logger.debug(
                    f"Block {i+1}/{len(blk_list)}: Coords ({x1, y1, x2, y2})"
                )

            if 0 <= y1 < y2 <= im_h and 0 <= x1 < x2 <= im_w:
                cropped_img = img[y1:y2, x1:x2]

                if cropped_img.size == 0:
                    if self.debug_mode and self.logger:
                        self.logger.warning(
                            f"Block {i+1}: Cropped image is empty for coords {blk.xyxy}. Skipping."
                        )
                    blk.text = ""
                    continue

                if self.debug_mode and self.logger:
                    self.logger.debug(
                        f"Block {i+1}: Cropped image size: {cropped_img.shape}"
                    )

                try:
                    processed_text = self.ocr(cropped_img, apply_postprocessing=True)
                    blk.text = processed_text

                    if self.debug_mode and self.logger:
                        log_text_proc = (
                            (processed_text[:50] + "...")
                            if processed_text and len(processed_text) > 50
                            else processed_text
                        )
                        self.logger.debug(
                            f'Block {i+1}: Final processed text: "{log_text_proc}"'
                        )
                except Exception as e:
                    if self.logger:
                        self.logger.error(
                            f"OCR error for block {i+1} at coords {blk.xyxy}: {e}",
                            exc_info=self.debug_mode,
                        )
                    blk.text = ""
            else:
                if self.debug_mode and self.logger:
                    self.logger.warning(
                        f"Block {i+1}: Invalid coords ({blk.xyxy}) relative to image ({im_h}x{im_w}). Skipping."
                    )
                blk.text = ""

    def ocr_img(self, img: np.ndarray) -> str:
        if not self.available:
            if self.debug_mode and self.logger:
                self.logger.warning("OCR engine is not available, skipping ocr_img.")
            return ""
        if self.debug_mode and self.logger:
            self.logger.debug(f"ocr_img called for image shape: {img.shape}")
        return self.ocr(img, apply_postprocessing=True)

    def ocr(self, img: np.ndarray, apply_postprocessing: bool = True) -> str:
        if not self.available:
            if self.debug_mode and self.logger:
                self.logger.warning("OCR engine is not available, skipping ocr.")
            return ""

        if self.debug_mode and self.logger:
            self.logger.debug(f"Starting OCR for image shape: {img.shape}")

        if img is None or img.size == 0:
            if self.debug_mode and self.logger:
                self.logger.warning("Received empty image for OCR.")
            return ""

        if self.engine is None:
            if self.logger:
                self.logger.error(
                    "OCR engine is None unexpectedly, cannot perform OCR."
                )
            return ""

        try:
            start_time = time.time()
            if len(img.shape) == 2:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            elif img.shape[2] == 3:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            elif img.shape[2] == 4:
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            else:
                raise ValueError(
                    f"Unsupported number of image channels: {img.shape[2]}"
                )

            pil_image = PilImage.fromarray(img_rgb).convert("RGBA")
            prep_time = time.time()
            if self.debug_mode and self.logger:
                self.logger.debug(
                    f"Image converted to PIL RGBA: {pil_image.size} (took {prep_time - start_time:.3f}s)"
                )

            result_dict = self.engine.recognize_pil(pil_image)
            ocr_time = time.time()

            lines_data = result_dict.get("lines", [])

            if self.debug_mode and self.logger:
                num_lines = len(lines_data)
                angle = result_dict.get("text_angle")
                angle_str = f"{angle:.2f}" if angle is not None else "N/A"
                self.logger.debug(
                    f"OcrEngine result: {num_lines} line(s), angle {angle_str} degrees. (took {ocr_time - prep_time:.3f}s)"
                )

            line_texts = [line["text"] for line in lines_data if line.get("text")]

            if self.reverse_line_order:
                line_texts.reverse()
                if self.debug_mode and self.logger:
                    self.logger.debug(" -> Applied reverse line order.")

            full_text = "\n".join(line_texts)

            if apply_postprocessing:
                full_text = self._apply_text_postprocessing(full_text)
                post_time = time.time()
                if self.debug_mode and self.logger:
                    log_processed_text = (
                        (full_text[:100] + "...")
                        if full_text and len(full_text) > 100
                        else full_text
                    )
                    self.logger.debug(
                        f'Text after postprocessing: "{log_processed_text}" (took {post_time - ocr_time:.3f}s)'
                    )
            elif self.debug_mode and self.logger:
                self.logger.debug(f"Skipping text postprocessing as per request.")

            total_time = time.time() - start_time
            if self.debug_mode and self.logger:
                self.logger.debug(f"Total OCR process completed in {total_time:.3f}s")

            return full_text

        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"Critical error during OCR process: {e}", exc_info=self.debug_mode
                )
            return ""

    def _apply_text_postprocessing(self, text: str) -> str:
        if not text:
            return ""

        original_text = text
        if self.debug_mode and self.logger:
            self.logger.debug("Applying text postprocessing...")

        if self.newline_handling == "remove":
            text = text.replace("\n", " ").replace("\r", "")
            if self.debug_mode and self.logger:
                self.logger.debug(" -> Applied newline removal (replaced with space).")
        elif self.newline_handling == "preserve":
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if self.debug_mode and self.logger:
                self.logger.debug(
                    " -> Applied newline preservation (normalized to \\n)."
                )

        text = self._apply_punctuation_and_spacing(text)
        if self.debug_mode and self.logger:
            self.logger.debug(" -> Applied punctuation and spacing rules.")

        if self.no_uppercase:
            text = self._apply_no_uppercase(text)
            if self.debug_mode and self.logger:
                self.logger.debug(" -> Applied 'no_uppercase' conversion.")

        if self.debug_mode and self.logger and text != original_text:
            log_orig = (
                (original_text[:100] + "...")
                if original_text and len(original_text) > 100
                else original_text
            )
            log_proc = (text[:100] + "...") if text and len(text) > 100 else text
            self.logger.debug(
                f'Postprocessing changed text:\n  Original (trunc): "{log_orig}"\n  Processed (trunc): "{log_proc}"'
            )
        elif self.debug_mode and self.logger:
            self.logger.debug("Postprocessing did not change the text.")

        return text

    def _apply_no_uppercase(self, text: str) -> str:
        if not text:
            return ""
        sentences = re.split(r"(?<=[.!?…])\s+", text)
        processed_sentences = []
        for sentence in sentences:
            if not sentence:
                continue
            first_char = sentence[0].upper()
            rest_chars = sentence[1:].lower()
            processed_sentences.append(first_char + rest_chars)
        return " ".join(processed_sentences)

    def _apply_punctuation_and_spacing(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\s+([,.!?…;:])", r"\1", text)
        text = re.sub(r"([,.!?…;:])(?=[^\s,.!?…;:])", r"\1 ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        if self.debug_mode and self.logger:
            self.logger.debug(
                f"Parameter '{param_key}' updated in OCROneAPI. No engine re-initialization needed for this key."
            )

    def __del__(self):
        if self.debug_mode and self.logger:
            self.logger.debug(f"OCROneAPI destructor called for instance {id(self)}.")
