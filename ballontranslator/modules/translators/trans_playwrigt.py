import threading
import time
import re
import json
import queue
import uuid
import os
import logging
import sys
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright
from .base import BaseTranslator, register_translator

# --- Logger Setup ---
# Module-scoped logger only; do not reconfigure the root logger.
logger = logging.getLogger("PlaywrightTranslator")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s'
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# --- Shared Helpers ---

# --- Shared Helpers ---

def _extract_json_block(text: str) -> Optional[str]:
    """
    Extract the outermost JSON object or array from *text*, stripping code fences
    and LLM prose. Uses bracket/brace depth counting instead of a greedy regex.

    >>> _extract_json_block('```json\\n{"a": 1}\\n```')
    '{"a": 1}'
    >>> _extract_json_block('Here is the array: [{"id": 1}]')
    '[{"id": 1}]'
    >>> _extract_json_block('no json here') is None
    True
    """
    if not text:
        return None

    # Strip markdown code fences
    stripped = re.sub(r'```(?:json)?\s*', '', text)
    stripped = stripped.replace('```', '')

    pos_brace = stripped.find('{')
    pos_bracket = stripped.find('[')

    if pos_brace == -1 and pos_bracket == -1:
        return None

    if pos_brace != -1 and pos_bracket != -1:
        if pos_brace < pos_bracket:
            start = pos_brace
            open_ch, close_ch = '{', '}'
        else:
            start = pos_bracket
            open_ch, close_ch = '[', ']'
    elif pos_brace != -1:
        start = pos_brace
        open_ch, close_ch = '{', '}'
    else:
        start = pos_bracket
        open_ch, close_ch = '[', ']'

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return stripped[start:i + 1]

    # Unclosed structure — return what we have for repair attempts
    return stripped[start:]


def _normalize_translations(translations_raw: list) -> list:
    """
    Normalize list of translation items into a standardized list of dicts:
    [{"id": Optional[int], "translation": str}, ...]
    Handles dicts with varied key names (id, index, translation, text, target),
    string IDs ("1"), raw string items, and missing fields.

    >>> _normalize_translations([{"id": "1", "text": "hello"}])
    [{'id': 1, 'translation': 'hello'}]
    """
    if not isinstance(translations_raw, list):
        return []

    normalized = []
    for idx, item in enumerate(translations_raw, start=1):
        if isinstance(item, str):
            normalized.append({"id": idx, "translation": item})
        elif isinstance(item, dict):
            # Extract ID
            item_id = None
            for id_key in ["id", "index", "num", "no"]:
                if id_key in item and item[id_key] is not None:
                    val = item[id_key]
                    try:
                        if isinstance(val, str):
                            digit_match = re.search(r'\d+', val)
                            if digit_match:
                                item_id = int(digit_match.group(0))
                        elif isinstance(val, (int, float)):
                            item_id = int(val)
                    except (ValueError, TypeError):
                        pass
                    if item_id is not None:
                        break

            # Extract Translation text
            trans_text = None
            for trans_key in ["translation", "translated", "text", "target", "result", "output", "dst", "translated_text"]:
                if trans_key in item and item[trans_key] is not None:
                    trans_text = str(item[trans_key])
                    break

            if trans_text is None:
                # Fallback: find first string value in dict that is not the ID
                for k, v in item.items():
                    if k not in ["id", "index", "num", "no"] and isinstance(v, str):
                        trans_text = v
                        break

            if trans_text is None:
                trans_text = ""

            normalized.append({"id": item_id, "translation": trans_text})
        else:
            normalized.append({"id": idx, "translation": str(item) if item is not None else ""})

    return normalized


def _enhanced_local_repair(raw_json: str) -> Optional[dict]:
    """
    Perform multi-pass repair on malformed JSON strings from LLM output.
    Returns dict with key 'translations' containing normalized translation items.

    >>> data = _enhanced_local_repair('{"translations": [{"id": 1, "translation": "hello"},]}')
    >>> data['translations'][0]['translation']
    'hello'
    >>> data = _enhanced_local_repair('[{"id": "1", "text": "array item"}]')
    >>> data['translations'][0]['translation']
    'array item'
    """
    if not raw_json or not raw_json.strip():
        return None

    def _extract_translations_from_data(data) -> Optional[dict]:
        if isinstance(data, list):
            return {"translations": _normalize_translations(data)}
        if isinstance(data, dict):
            if "translations" in data and isinstance(data["translations"], list):
                return {"translations": _normalize_translations(data["translations"])}
            for key in ["data", "results", "items", "result", "translation"]:
                if key in data and isinstance(data[key], list):
                    return {"translations": _normalize_translations(data[key])}
            if "translation" in data or "translated" in data or "text" in data:
                return {"translations": _normalize_translations([data])}
        return None

    # Step 1: Direct parse attempt
    try:
        data = json.loads(raw_json)
        res = _extract_translations_from_data(data)
        if res:
            return res
    except json.JSONDecodeError:
        pass

    # Step 2: Fix trailing commas & unclosed structures
    fixed = re.sub(r',\s*([}\]])', r'\1', raw_json)
    fixed = re.sub(r',\s*\{\s*["\']?id["\']?\s*:\s*\d+.*$', '', fixed)
    fixed = fixed.rstrip(',').rstrip()
    if not fixed.endswith(']}') and not fixed.endswith('}'):
        if fixed.startswith('['):
            if not fixed.endswith(']'):
                fixed += ']'
        else:
            if not fixed.endswith(']}'):
                if not fixed.endswith(']'):
                    fixed += ']}'
                else:
                    fixed += '}'
    try:
        data = json.loads(fixed)
        res = _extract_translations_from_data(data)
        if res:
            return res
    except json.JSONDecodeError:
        pass

    # Step 3: Item-by-item extraction for unescaped quotes & broken syntax
    items = []
    parts = re.split(r'(?=\{\s*["\']?id["\']?)', raw_json)
    for p in parts:
        id_match = re.search(r'["\']?id["\']?\s*:\s*["\']?(\d+)["\']?', p)
        if not id_match:
            continue
        item_id = int(id_match.group(1))

        trans_match = re.search(r'["\']?(?:translation|translated|text|target|result)["\']?\s*:\s*"(.*)', p, re.DOTALL)
        if trans_match:
            raw_text = trans_match.group(1).rstrip()
            raw_text = re.sub(r'"\s*\}?\s*,?\s*\]?\s*\}?\s*$', '', raw_text)
            items.append({"id": item_id, "translation": raw_text})
        else:
            trans_match_sq = re.search(r'["\']?(?:translation|translated|text|target|result)["\']?\s*:\s*\'(.*)', p, re.DOTALL)
            if trans_match_sq:
                raw_text = trans_match_sq.group(1).rstrip()
                raw_text = re.sub(r'\'\s*\}?\s*,?\s*\]?\s*\}?\s*$', '', raw_text)
                items.append({"id": item_id, "translation": raw_text})

    if items:
        seen_ids = set()
        unique_items = []
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                unique_items.append(item)
        unique_items.sort(key=lambda x: x["id"])
        return {"translations": unique_items}

    return None


def _parse_or_repair_json(raw_json: str, instance_id: int) -> Optional[dict]:
    """
    Try to parse *raw_json*; on failure, attempt incremental multi-pass repair
    (truncated trailing entries, unescaped quotes, missing closing brackets).
    Returns the parsed dict or None.

    >>> data = _parse_or_repair_json('{"translations": [{"id": 1, "translation": "hi"}]}', 1)
    >>> data['translations'][0]['translation']
    'hi'
    """
    if not raw_json:
        return None

    try:
        data = json.loads(raw_json)
        if isinstance(data, list):
            logger.info(f"Instance {instance_id}: [JSON_SUCCESS] (array)")
            return {"translations": _normalize_translations(data)}
        if isinstance(data, dict):
            if "translations" in data and isinstance(data["translations"], list):
                logger.info(f"Instance {instance_id}: [JSON_SUCCESS]")
                return {"translations": _normalize_translations(data["translations"])}
            for key in ["data", "results", "items", "result", "translation"]:
                if key in data and isinstance(data[key], list):
                    logger.info(f"Instance {instance_id}: [JSON_SUCCESS] (key '{key}')")
                    return {"translations": _normalize_translations(data[key])}
    except json.JSONDecodeError:
        pass

    logger.warning(f"Instance {instance_id}: [REPAIRING_JSON]")
    data = _enhanced_local_repair(raw_json)
    if data:
        logger.info(f"Instance {instance_id}: [REPAIR_SUCCESS]")
        return data

    logger.error(f"Instance {instance_id}: [REPAIR_FAILED]")
    return None


class RepairTask:
    """
    Data carrier holding malformed JSON text and repair completion signaling.

    >>> task = RepairTask(raw_json='{"translations": [{"id": 1, "translation": "hello"}]}', expected_count=1)
    >>> task.expected_count
    1
    """
    def __init__(self, raw_json: str, expected_count: int, batch_token: str = ""):
        self.raw_json = raw_json
        self.expected_count = expected_count
        self.batch_token = batch_token
        self.result: Optional[dict] = None
        self.done_event = threading.Event()


class JsonRepairWorker(threading.Thread):
    """
    Dedicated worker thread tasked with repairing damaged translation JSON strings.

    >>> worker = JsonRepairWorker(instance_id=1)
    >>> res = worker.repair('{"translations": [{"id": 1, "translation": "ok"},]}', 1)
    >>> res['translations'][0]['translation']
    'ok'
    """
    def __init__(self, instance_id: int = 1):
        super().__init__(daemon=True, name=f"JsonRepairWorker-{instance_id}")
        self.instance_id = instance_id
        self.task_queue = queue.Queue()
        self.running = True

    def run(self):
        while self.running:
            task = None
            try:
                task = self.task_queue.get(timeout=1)
                task.result = self.repair(task.raw_json, task.expected_count)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"JsonRepairWorker-{self.instance_id} error: {e}")
            finally:
                if task is not None:
                    self.task_queue.task_done()
                    task.done_event.set()

    def repair(self, raw_json: str, expected_count: int) -> Optional[dict]:
        data = _enhanced_local_repair(raw_json)
        if data and "translations" in data and len(data["translations"]) > 0:
            count = len(data["translations"])
            if count == expected_count:
                logger.info(f"JsonRepairWorker-{self.instance_id}: [REPAIR_SUCCESS] Restored all {expected_count} items.")
            else:
                logger.warning(f"JsonRepairWorker-{self.instance_id}: [PARTIAL_REPAIR] Restored {count}/{expected_count} items.")
            return data
        logger.error(f"JsonRepairWorker-{self.instance_id}: [REPAIR_FAILED]")
        return None


def _build_results(task_src_list: List[str], translations: List[dict]) -> List[str]:
    """
    Re-assemble translated parts back into the ## -delimited structure
    expected by the base translator. Robust to string/int IDs, missing IDs,
    and length mismatches between input elements and translated outputs.

    >>> _build_results(["Hello ## World"], [{"id": 1, "translation": "Halo"}, {"id": 2, "translation": "Dunia"}])
    ['Halo ## Dunia']
    >>> _build_results(["Hello"], [{"id": "1", "translation": "Halo"}])
    ['Halo']
    """
    norm_translations = _normalize_translations(translations)

    # Pre-index translations by explicit integer ID
    id_map: Dict[int, str] = {}
    unmatched_items: List[str] = []

    for item in norm_translations:
        item_id = item.get("id")
        trans_text = item.get("translation", "")
        if isinstance(item_id, int) and item_id > 0 and item_id not in id_map:
            id_map[item_id] = trans_text
        else:
            unmatched_items.append(trans_text)

    unmatched_idx = 0
    results = []
    curr_id = 1

    for text in task_src_list:
        parts = text.split('##')
        p_translated = []
        for p in parts:
            src_stripped = p.strip()
            if curr_id in id_map:
                val = id_map[curr_id]
                p_translated.append(val if val != "" else src_stripped)
            elif unmatched_idx < len(unmatched_items):
                val = unmatched_items[unmatched_idx]
                unmatched_idx += 1
                p_translated.append(val if val != "" else src_stripped)
            else:
                p_translated.append(src_stripped)
            curr_id += 1
        results.append(" ## ".join(p_translated))

    return results


# --- Data Carrier ---

class TranslationTask:
    """
    Data carrier holding input source strings and output translated results.
    """
    def __init__(self, src_list: List[str], target_lang: str, custom_prompt: str, source_lang: str, needs_refresh: bool = False):
        self.src_list = src_list
        self.target_lang = target_lang
        self.custom_prompt = custom_prompt
        self.source_lang = source_lang
        self.result: Optional[List[str]] = None
        self.needs_refresh = needs_refresh 
        self.done_event = threading.Event()

# --- Gemini Browser Worker ---

class GeminiBrowserWorker(threading.Thread):
    """
    Worker automating the Google Gemini interface to perform translations.
    """
    def __init__(self, profile_dir: str, instance_id: int, repair_worker: Optional[JsonRepairWorker] = None):
        super().__init__(daemon=True, name=f"GeminiWorker-{instance_id}")
        self.profile_dir = profile_dir
        self.instance_id = instance_id
        self.repair_worker = repair_worker
        self.task_queue = queue.Queue()
        self.running = True

    def run(self):
        try:
            import subprocess
            logger.info(f"Instance {self.instance_id}: Installing/checking Playwright Chromium...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except Exception as e:
                logger.error(f"Instance {self.instance_id}: Failed to run playwright install chromium: {e}")
            with sync_playwright() as p:
                logger.info(f"Instance {self.instance_id}: Launching Browser...")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = browser.pages[0]
                self._safe_goto(page, "https://gemini.google.com", wait_extra=True)

                while self.running:
                    task = None
                    try:
                        task = self.task_queue.get(timeout=1)
                        if task.needs_refresh:
                            logger.info(f"Instance {self.instance_id}: Retry detected. Refreshing page...")
                            self._safe_goto(page, "https://gemini.google.com", wait_extra=True)
                        
                        task.result = self._do_translate(page, task)
                        
                        if task.result:
                            logger.info(f"Instance {self.instance_id}: Task completed successfully.")
                            time.sleep(1) 
                        else:
                            logger.warning(f"Instance {self.instance_id}: Task error/failed. Cooldown 5s...")
                            time.sleep(5)
                    except queue.Empty:
                        continue
                    except Exception as e:
                        logger.error(f"Instance {self.instance_id}: Worker loop error: {e}")
                    finally:
                        # Always unblock the caller and mark the queue item done.
                        # task_done() first so queue bookkeeping is consistent
                        # before the caller wakes and potentially submits more work.
                        if task is not None:
                            self.task_queue.task_done()
                            task.done_event.set()
                
                browser.close()
        except Exception as e:
            logger.critical(f"Instance {self.instance_id}: Fatal Error: {e}")
        finally:
            self.running = False

    def _safe_goto(self, page, url: str, wait_extra: bool = False):
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector("div[contenteditable='true']", timeout=30000)
            if wait_extra:
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Instance {self.instance_id}: Navigation failed ({e}). Reloading...")
            try:
                page.reload()
                time.sleep(5)
            except Exception as reload_err:
                logger.debug(f"Instance {self.instance_id}: Reload also failed: {reload_err}")

    def _do_translate(self, page, task: TranslationTask) -> Optional[List[str]]:
        input_sel = "div[contenteditable='true']"
        try:
            page.wait_for_selector(input_sel, timeout=15000)
            batch_token = f"BTCH_{uuid.uuid4().hex[:6]}"
            
            input_elements = []
            current_global_id = 1
            for text in task.src_list:
                parts = text.split('##')
                for part in parts:
                    input_elements.append({"id": current_global_id, "text": part.strip()})
                    current_global_id += 1
            
            input_json_str = json.dumps(input_elements, ensure_ascii=False)
            
            prompt_parts = []
            prompt_parts.extend([
                f"IDENTIFIER: {batch_token}",
                f"TASK: Translate from {task.source_lang} to {task.target_lang}.",
                "FORMAT: Respond ONLY with a valid JSON object. No prose.",
                f'SCHEMA: {{"batch_id": "{batch_token}", "translations": [{{"id": number, "translation": "string"}}]}}',
                f"INPUT:\n{input_json_str}"
            ])
            full_prompt = "\n".join(prompt_parts)

            logger.info("-" * 50)
            logger.info(f"Instance {self.instance_id}: [SENDING_DATA] Batch: {batch_token}")
            logger.info(f"Input Count: {len(input_elements)} items")
            logger.info("-" * 50)

            page.click(input_sel)
            time.sleep(0.5)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.keyboard.insert_text(full_prompt)
            time.sleep(1)
            page.keyboard.press("Enter")

            start_wait = time.time()
            last_length = 0
            last_growth_time = time.time()
            max_poll_time = 10
            stable_threshold_s = 1.0
            
            logger.info(f"Instance {self.instance_id}: Waiting for response (Max {max_poll_time}s)...")

            while (time.time() - start_wait) < max_poll_time:
                time.sleep(0.3) 
                responses = page.query_selector_all(".markdown, .message-content")
                if not responses:
                    continue
                
                current_text = responses[-1].inner_text()
                current_length = len(current_text)
                
                # Fast path: if complete valid JSON is detected with the batch token, return immediately
                if batch_token in current_text:
                    raw_json = _extract_json_block(current_text)
                    if raw_json:
                        data = _parse_or_repair_json(raw_json, self.instance_id)
                        if data and "translations" in data and len(data["translations"]) == len(input_elements):
                            logger.info(f"Instance {self.instance_id}: [FAST-RESULT] Complete valid response received.")
                            return _build_results(task.src_list, data["translations"])

                if current_length > last_length:
                    logger.info(f"Instance {self.instance_id}: Gemini is typing... ({current_length} chars)")
                    last_length = current_length
                    last_growth_time = time.time()
                    continue

                wall_stable = time.time() - last_growth_time
                if wall_stable < stable_threshold_s or current_length == 0:
                    continue

                if batch_token not in current_text:
                    continue

                logger.info(f"Instance {self.instance_id}: [STABLE] Analyzing JSON...")

                raw_json = _extract_json_block(current_text)
                if not raw_json:
                    continue

                data = _parse_or_repair_json(raw_json, self.instance_id)
                if data is None and self.repair_worker:
                    logger.info(f"Instance {self.instance_id}: Dispatching to JsonRepairWorker...")
                    repair_task = RepairTask(raw_json, expected_count=len(input_elements), batch_token=batch_token)
                    self.repair_worker.task_queue.put(repair_task)
                    if repair_task.done_event.wait(timeout=5) and repair_task.result:
                        data = repair_task.result

                if data is None:
                    logger.warning(f"Instance {self.instance_id}: Sending LLM JSON repair prompt...")
                    repair_prompt = (
                        f"IDENTIFIER: {batch_token}\n"
                        "FIX MALFORMED JSON: The previous response had invalid JSON syntax. "
                        "Output ONLY valid JSON matching schema:\n"
                        f'{{"batch_id": "{batch_token}", "translations": [{{"id": number, "translation": "string"}}]}}\n'
                        f"RAW OUTPUT TO FIX:\n{current_text[:2000]}"
                    )
                    try:
                        page.click(input_sel)
                        time.sleep(0.3)
                        page.keyboard.press("Control+A")
                        page.keyboard.press("Backspace")
                        page.keyboard.insert_text(repair_prompt)
                        time.sleep(0.5)
                        page.keyboard.press("Enter")

                        repair_start = time.time()
                        while (time.time() - repair_start) < 6:
                            time.sleep(0.3)
                            resp_els = page.query_selector_all(".markdown, .message-content")
                            if not resp_els: continue
                            rep_text = resp_els[-1].inner_text()
                            if batch_token in rep_text:
                                rep_json = _extract_json_block(rep_text)
                                if rep_json:
                                    data = _parse_or_repair_json(rep_json, self.instance_id)
                                    if data: break
                    except Exception as rep_err:
                        logger.error(f"Instance {self.instance_id}: LLM repair prompt error: {rep_err}")

                if data is None:
                    return None

                translations = data.get("translations", [])
                logger.info(f"Instance {self.instance_id}: [RESULT] Received {len(translations)} items.")
                return _build_results(task.src_list, translations)
            
            logger.error(f"Instance {self.instance_id}: [TIMEOUT] No stable response in {max_poll_time}s")
            return None
        except Exception as e:
            logger.error(f"Instance {self.instance_id}: [LOGIC_ERROR] {e}")
            return None

# --- DeepSeek Browser Worker ---

class DeepSeekBrowserWorker(threading.Thread):
    """
    Worker automating the DeepSeek interface to translate text batches with refusal checks.
    """
    REFRESH_EVERY = 5

    def __init__(self, profile_dir: str, instance_id: int, repair_worker: Optional[JsonRepairWorker] = None):
        super().__init__(daemon=True, name=f"DeepSeekWorker-{instance_id}")
        self.profile_dir = profile_dir
        self.instance_id = instance_id
        self.repair_worker = repair_worker
        self.task_queue = queue.Queue()
        self.running = True
        self.translate_count = 0

    def run(self):
        try:
            import subprocess
            logger.info(f"DeepSeek Instance {self.instance_id}: Installing/checking Playwright Chromium...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except Exception as e:
                logger.error(f"DeepSeek Instance {self.instance_id}: Failed to run playwright install chromium: {e}")
            with sync_playwright() as p:
                logger.info(f"DeepSeek Instance {self.instance_id}: Launching Browser...")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = browser.pages[0]
                self._safe_goto(page, "https://chat.deepseek.com", wait_extra=True)

                while self.running:
                    task = None
                    try:
                        task = self.task_queue.get(timeout=1)
                        if task.needs_refresh:
                            logger.info(f"DeepSeek Instance {self.instance_id}: Resetting chat history...")
                            self._start_new_chat(page)
                        
                        task.result = self._do_translate(page, task)
                        self.translate_count += 1
                        
                        if task.result:
                            logger.info(f"DeepSeek Instance {self.instance_id}: Task completed successfully.")
                            time.sleep(1)
                        else:
                            logger.warning(f"DeepSeek Instance {self.instance_id}: Task error/failed. Cooldown 5s...")
                            time.sleep(5)
                    except queue.Empty:
                        continue
                    except Exception as e:
                        logger.error(f"DeepSeek Instance {self.instance_id}: Worker error: {e}")
                        try:
                            self._safe_goto(page, "https://chat.deepseek.com", wait_extra=True)
                            self.translate_count = 0
                        except Exception as nav_err:
                            logger.debug(f"DeepSeek Instance {self.instance_id}: Recovery navigation failed: {nav_err}")
                    finally:
                        if task is not None:
                            self.task_queue.task_done()
                            task.done_event.set()
                
                browser.close()
        except Exception as e:
            logger.critical(f"DeepSeek Instance {self.instance_id}: Fatal Error: {e}")
        finally:
            self.running = False

    def _start_new_chat(self, page):
        try:
            new_chat_btn = page.query_selector("div[class*='new-chat'], button[class*='new-chat'], a[href='/']")
            if new_chat_btn:
                new_chat_btn.click()
                time.sleep(1)
                page.wait_for_selector("textarea[placeholder='Message DeepSeek']", timeout=10000)
                return
        except Exception as e:
            logger.debug(f"DeepSeek Instance {self.instance_id}: New chat button failed: {e}")
        self._safe_goto(page, "https://chat.deepseek.com", wait_extra=False)

    def _safe_goto(self, page, url: str, wait_extra: bool = False):
        INPUT_SEL = "textarea[placeholder='Message DeepSeek']"
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector(INPUT_SEL, timeout=30000)
            if wait_extra: time.sleep(1)
        except Exception as e:
            logger.warning(f"DeepSeek Instance {self.instance_id}: Navigation setup warning: {e}")
            try:
                page.reload()
                time.sleep(5)
            except Exception as reload_err:
                logger.debug(f"DeepSeek Instance {self.instance_id}: Reload also failed: {reload_err}")

    REFUSAL_PATTERNS = [
        "这个问题我暂时无法回答", "让我们换个话题", "我无法回答", "无法提供",
        "I cannot answer", "I'm unable to", "I can't assist", "Let's change the topic",
        "违反了我的使用政策", "不符合我的服务条款", "作为AI助手", "作为一个AI",
    ]

    def _is_refusal(self, text: str) -> bool:
        for pattern in self.REFUSAL_PATTERNS:
            if pattern in text:
                return True
        return False

    def _do_translate(self, page, task: TranslationTask) -> Optional[List[str]]:
        INPUT_SEL = "textarea[placeholder='Message DeepSeek']"
        SELECTORS = ".ds-markdown, .ds-assistant-message-main-content, .markdown, .message-content"

        # --- Retry state kept outside the loop to avoid recursion ---
        is_retry = False
        rate_limit_retries = 0
        MAX_RATE_RETRIES = 3

        while True:
            try:
                current_url = page.url
                if "sign_in" in current_url or "accounts.google.com" in current_url or not page.query_selector(INPUT_SEL):
                    page.wait_for_selector(INPUT_SEL, timeout=90000)

                page.wait_for_selector(INPUT_SEL, timeout=15000)
                
                existing_responses = page.query_selector_all(SELECTORS)
                if existing_responses:
                    try:
                        existing_responses[-1].evaluate("el => el.setAttribute('data-luna-old', 'true')")
                    except Exception:
                        pass

                batch_token = f"BTCH_{uuid.uuid4().hex[:6]}"
                
                input_elements = []
                current_global_id = 1
                for text in task.src_list:
                    parts = text.split('##')
                    for part in parts:
                        input_elements.append({"id": current_global_id, "text": part.strip()})
                        current_global_id += 1
                
                input_json_str = json.dumps(input_elements, ensure_ascii=False)
                
                prompt_parts = []
                prompt_parts.extend([
                    f"IDENTIFIER: {batch_token}",
                    f"TASK: Translate from {task.source_lang} to {task.target_lang}.",
                    "FORMAT: Respond ONLY with a valid JSON object. No prose.",
                    f'SCHEMA: {{"batch_id": "{batch_token}", "translations": [{{"id": number, "translation": "string"}}]}}',
                    f"INPUT:\n{input_json_str}"
                ])
                full_prompt = "\n".join(prompt_parts)

                page.click(INPUT_SEL)
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(full_prompt)
                time.sleep(0.1)
                page.keyboard.press("Enter")

                start_wait = time.time()
                last_length = 0
                stable_checks = 0
                while (time.time() - start_wait) < 10:
                    time.sleep(0.2)
                    
                    # Only check for rate-limit text when the response has stalled
                    # (avoids expensive full-body serialization every 200ms).
                    if stable_checks >= 2:
                        try:
                            # Use a targeted selector for toast/error elements first
                            error_els = page.query_selector_all(".ds-toast, .ant-message, [class*='error'], [class*='toast']")
                            error_text = " ".join(
                                el.inner_text().lower() for el in error_els
                            ) if error_els else ""
                            if not error_text:
                                # Fallback: scan body only when stalled, not every cycle
                                error_text = page.inner_text("body").lower()
                            if "messages too frequent" in error_text or "try again later" in error_text or "发送消息过于频繁" in error_text:
                                logger.warning("DeepSeek: Rate limit / frequency error detected in page text.")
                                if rate_limit_retries < MAX_RATE_RETRIES:
                                    rate_limit_retries += 1
                                    logger.info(f"DeepSeek: Sleeping 30 seconds before retrying (attempt {rate_limit_retries}/{MAX_RATE_RETRIES})...")
                                    time.sleep(30)
                                    self._start_new_chat(page)
                                    self.translate_count = 0
                                    break  # Re-enter the outer while True to retry
                                else:
                                    logger.error("DeepSeek: Exceeded rate limit retry limit.")
                                    return None
                        except Exception:
                            pass

                    try:
                        responses = page.query_selector_all(SELECTORS)
                    except Exception:
                        continue
                    
                    if not responses:
                        continue
                    last_response = responses[-1]
                    try:
                        if last_response.evaluate("el => el.hasAttribute('data-luna-old')"):
                            continue
                    except Exception:
                        continue
                    
                    try:
                        current_text = last_response.inner_text().strip()
                    except Exception:
                        continue
                    
                    # Fast path: if complete valid JSON is detected with the batch token, return immediately
                    if batch_token in current_text:
                        raw_json = _extract_json_block(current_text)
                        if raw_json:
                            data = _parse_or_repair_json(raw_json, self.instance_id)
                            if data and "translations" in data and len(data["translations"]) == len(input_elements):
                                logger.info(f"DeepSeek Instance {self.instance_id}: [FAST-RESULT] Complete valid response received.")
                                return _build_results(task.src_list, data["translations"])

                    if len(current_text) > last_length:
                        last_length = len(current_text)
                        stable_checks = 0
                        continue
                    
                    if current_text:
                        stable_checks += 1
                        if stable_checks >= 2:
                            
                            if self._is_refusal(current_text):
                                logger.warning(f"DeepSeek: Refusal detected: \"{current_text[:80]}...\"")
                                if not is_retry:
                                    self._start_new_chat(page)
                                    self.translate_count = 0
                                    is_retry = True
                                    break  # Re-enter the outer while True to retry
                                else:
                                    return None

                            raw_json = _extract_json_block(current_text)
                            if raw_json:
                                data = _parse_or_repair_json(raw_json, self.instance_id)
                                if data is None and self.repair_worker:
                                    logger.info(f"DeepSeek Instance {self.instance_id}: Dispatching to JsonRepairWorker...")
                                    repair_task = RepairTask(raw_json, expected_count=len(input_elements), batch_token=batch_token)
                                    self.repair_worker.task_queue.put(repair_task)
                                    if repair_task.done_event.wait(timeout=5) and repair_task.result:
                                        data = repair_task.result

                                if data is None:
                                    return None
                                
                                translations = data.get("translations", [])
                                return _build_results(task.src_list, translations)
                else:
                    # Inner while loop finished without break → timeout
                    return None

                # If we reach here, we broke out of the inner loop for a retry.
                # The outer `while True` re-enters to resubmit the prompt.
                continue

            except Exception as e:
                logger.error(f"DeepSeek Translation Error: {e}")
                return None

# --- DeepL Browser Worker ---

class DeepLBrowserWorker(threading.Thread):
    """
    Worker automating the DeepL web translator.
    """
    REFRESH_EVERY = 10

    def __init__(self, profile_dir: str, instance_id: int):
        super().__init__(daemon=True, name=f"DeepLWorker-{instance_id}")
        self.profile_dir = profile_dir
        self.instance_id = instance_id
        self.task_queue = queue.Queue()
        self.running = True
        self.translate_count = 0

    def run(self):
        try:
            import subprocess
            logger.info(f"DeepL Instance {self.instance_id}: Installing/checking Playwright Chromium...")
            try:
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            except Exception as e:
                logger.error(f"DeepL Instance {self.instance_id}: Failed to run playwright install chromium: {e}")
            with sync_playwright() as p:
                logger.info(f"DeepL Instance {self.instance_id}: Launching Browser...")
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    channel="chrome",
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                page = browser.pages[0]
                self._safe_goto(page, "https://www.deepl.com/translator#auto/id", wait_extra=True)

                while self.running:
                    task = None
                    try:
                        task = self.task_queue.get(timeout=1)
                        if task.needs_refresh:
                            lang_code = self._map_lang_code(task.target_lang)
                            self._safe_goto(page, f"https://www.deepl.com/translator#auto/{lang_code}", wait_extra=True)
                        
                        task.result = self._do_translate(page, task)
                        self.translate_count += 1
                        
                        if task.result:
                            logger.info(f"DeepL Instance {self.instance_id}: Task completed successfully.")
                            time.sleep(1)
                        else:
                            logger.warning(f"DeepL Instance {self.instance_id}: Task error/failed. Cooldown 5s...")
                            time.sleep(5)
                    except queue.Empty:
                        continue
                    except Exception as e:
                        logger.error(f"DeepL Instance {self.instance_id}: Worker error: {e}")
                        try:
                            lang_code = self._map_lang_code(task.target_lang) if task is not None else "id"
                            self._safe_goto(page, f"https://www.deepl.com/translator#auto/{lang_code}", wait_extra=True)
                            self.translate_count = 0
                        except Exception as nav_err:
                            logger.debug(f"DeepL Instance {self.instance_id}: Recovery navigation failed: {nav_err}")
                    finally:
                        if task is not None:
                            self.task_queue.task_done()
                            task.done_event.set()
                
                browser.close()
        except Exception as e:
            logger.critical(f"DeepL Instance {self.instance_id}: Fatal Error: {e}")
        finally:
            self.running = False

    def _map_lang_code(self, lang_name: str) -> str:
        lang_lower = lang_name.lower().strip()
        mapping = {
            "english": "en", "en": "en",
            "indonesian": "id", "id": "id",
            "japanese": "ja", "ja": "ja",
            "chinese": "zh", "zh": "zh",
            "korean": "ko", "ko": "ko",
            "spanish": "es", "es": "es",
            "french": "fr", "fr": "fr",
            "german": "de", "de": "de",
            "russian": "ru", "ru": "ru",
            "portuguese": "pt", "pt": "pt",
            "italian": "it", "it": "it",
        }
        return mapping.get(lang_lower, "id")

    def _safe_goto(self, page, url: str, wait_extra: bool = False):
        INPUT_SEL = 'd-textarea[data-testid="translator-source-input"]'
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector(INPUT_SEL, timeout=30000)
            if wait_extra: time.sleep(3)
        except Exception as e:
            logger.warning(f"DeepL Instance {self.instance_id}: Navigation setup warning: {e}")
            try:
                page.reload()
                time.sleep(5)
            except Exception as reload_err:
                logger.debug(f"DeepL Instance {self.instance_id}: Reload also failed: {reload_err}")

    def _do_translate(self, page, task: TranslationTask) -> Optional[List[str]]:
        input_sel = 'd-textarea[data-testid="translator-source-input"]'
        output_sel = 'd-textarea[data-testid="translator-target-input"]'
        try:
            page.wait_for_selector(input_sel, timeout=15000)

            lang_code = self._map_lang_code(task.target_lang)
            if f"#auto/{lang_code}" not in page.url:
                self._safe_goto(page, f"https://www.deepl.com/translator#auto/{lang_code}", wait_extra=True)

            page.click(input_sel)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            
            # Wait for target input to clear
            start_clear = time.time()
            while time.time() - start_clear < 3:
                try:
                    target_text = page.query_selector(output_sel).inner_text().strip()
                    if not target_text: break
                except Exception:
                    pass
                time.sleep(0.1)

            # DeepL paragraph preservation: join with double newlines
            joined_input = "\n\n".join(task.src_list)
            page.keyboard.insert_text(joined_input)

            start_wait = time.time()
            last_length = 0
            stable_checks = 0
            while (time.time() - start_wait) < 10:
                time.sleep(0.2)
                try:
                    target_el = page.query_selector(output_sel)
                    if not target_el: continue
                    current_text = target_el.inner_text().strip()
                except Exception:
                    continue

                if len(current_text) > last_length:
                    last_length = len(current_text)
                    stable_checks = 0
                    continue

                if current_text and current_text != joined_input:
                    stable_checks += 1
                    if stable_checks >= 2:
                        
                        # Process translation outputs
                        paragraphs = current_text.split("\n\n")
                        if len(paragraphs) != len(task.src_list):
                            paragraphs = current_text.split("\n")
                        
                        results = []
                        for i, src in enumerate(task.src_list):
                            if i < len(paragraphs) and paragraphs[i].strip():
                                results.append(paragraphs[i].strip())
                            else:
                                results.append(src)
                        return results

            # Timeout — return None so the caller knows translation failed
            logger.warning(f"DeepL Instance {self.instance_id}: [TIMEOUT] No translation in 10s")
            return None
        except Exception as e:
            logger.error(f"DeepL Translation Error: {e}")
            return None

# --- Translator Registration ---

@register_translator("Gemini Playwright")
class TransGemini(BaseTranslator):
    """
    Playwright browser automation translator supporting Gemini, DeepSeek, and DeepL.
    
    >>> t = TransGemini(lang_source="English", lang_target="Bahasa Indonesia", raise_unsupported_lang=False)
    >>> t.provider
    'Gemini'
    """
    concate_text = True
    supported_src_list = ["Japan", "English", "Bahasa Indonesia", "Chinese", "Auto-detect", "Korean"]
    supported_tgt_list = ["Japan", "English", "Bahasa Indonesia", "Chinese", "Korean"]
    dependencies = ["playwright"]
    
    params: Dict = {
        "provider": {
            "type": "selector",
            "options": ["Gemini", "DeepSeek", "DeepL"],
            "value": "Gemini",
            "description": "Select the browser automation provider.",
        },
        "prompt": {
            "value": "",
            "description": "Custom prompt to guide LLM translation (Gemini & DeepSeek)."
        }
    }

    def __init__(self, *args, **kwargs):
        self.worker: Optional[threading.Thread] = None
        self.repair_worker: Optional[JsonRepairWorker] = None
        self.instance_id = self._acquire_instance_id()
        super().__init__(*args, **kwargs)

    @property
    def provider(self) -> str:
        prov = self.get_param_value("provider")
        if isinstance(prov, dict):
            return prov.get("value", "Gemini")
        return prov or "Gemini"

    @property
    def profile_path(self) -> str:
        return os.path.abspath(f"{self.provider.lower()}_profile_instance_{self.instance_id}")

    def _acquire_instance_id(self) -> int:
        """
        Atomically acquire a lock file slot (1-3) using O_CREAT|O_EXCL
        to prevent TOCTOU races between concurrent processes.
        """
        for i in range(1, 4):
            lock_file = f"instance_{i}.lock"

            # If lock file exists, check whether the owning process is alive
            if os.path.exists(lock_file):
                try:
                    with open(lock_file, 'r') as f:
                        pid = int(f.read().strip())
                    os.kill(pid, 0)  # raises OSError if dead
                    continue  # Process alive, slot is taken
                except (OSError, ValueError):
                    # Stale lock — remove it so we can re-acquire atomically
                    try:
                        os.remove(lock_file)
                    except OSError:
                        continue

            # Atomic creation: O_CREAT|O_EXCL fails if file was created
            # between our exists() check and this open() call.
            try:
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)

                import atexit
                def remove_lock(path=lock_file):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                atexit.register(remove_lock)
                return i
            except FileExistsError:
                # Another process grabbed this slot between our check and open
                continue
            except OSError as e:
                logger.debug(f"Could not acquire lock slot {i}: {e}")
                continue

        logger.warning("All browser profile instances (1-3) are locked. Falling back to instance 3.")
        return 3

    def _setup_translator(self):
        self.lang_map = {
            "Japan": "Japanese", "English": "English", 
            "Bahasa Indonesia": "Indonesian", "Chinese": "Chinese",
            "Auto-detect": "Auto-detect", "Korean" : "Korean"
        }
        
        active_provider = self.provider
        # If worker exists but is for a different provider, stop it
        if self.worker:
            worker_provider = "Gemini"
            if "DeepSeek" in type(self.worker).__name__:
                worker_provider = "DeepSeek"
            elif "DeepL" in type(self.worker).__name__:
                worker_provider = "DeepL"
            
            if worker_provider != active_provider:
                logger.info(f"Stopping worker for {worker_provider} to switch to {active_provider}")
                self.worker.running = False
                self.worker = None

        if self.worker and self.worker.is_alive(): return

        # Clear stale worker reference so the new worker starts clean
        self.worker = None

        if not self.repair_worker or not self.repair_worker.is_alive():
            self.repair_worker = JsonRepairWorker(instance_id=self.instance_id)
            self.repair_worker.start()

        if active_provider == "DeepSeek":
            self.worker = DeepSeekBrowserWorker(self.profile_path, self.instance_id, repair_worker=self.repair_worker)
        elif active_provider == "DeepL":
            self.worker = DeepLBrowserWorker(self.profile_path, self.instance_id)
        else:
            self.worker = GeminiBrowserWorker(self.profile_path, self.instance_id, repair_worker=self.repair_worker)
            
        self.worker.start()

    def updateParam(self, param_key: str, param_content):
        super().updateParam(param_key, param_content)
        # Restart worker if provider changed
        if param_key == "provider":
            self._setup_translator()

    def _translate(self, src_list: List[str]) -> List[str]:
        if not src_list: return src_list
        
        self._setup_translator()
        source = self.lang_map.get(self.lang_source, self.lang_source)
        target = self.lang_map.get(self.lang_target, self.lang_target)
        custom_prompt = self.get_param_value("prompt")
        if isinstance(custom_prompt, dict):
            custom_prompt = custom_prompt.get("value", "")
        custom_prompt = (custom_prompt or "").strip()

        logger.info(f"Instance {self.instance_id} ({self.provider}): Starting batch translation ({len(src_list)} blocks)...")

        # Retry loop (max 2 attempts) instead of recursion to keep
        # the call stack shallow and the timeout predictable.
        max_retries = 1
        for attempt in range(max_retries + 1):
            needs_refresh = attempt > 0
            if needs_refresh:
                logger.warning(f"Instance {self.instance_id} ({self.provider}): [TIMEOUT/FAIL] Retrying ({attempt}/{max_retries})...")

            task = TranslationTask(src_list, target, custom_prompt, source, needs_refresh=needs_refresh)
            self.worker.task_queue.put(task)
            
            if task.done_event.wait(timeout=60) and task.result:
                return task.result

        logger.error(f"Instance {self.instance_id} ({self.provider}): [FAILED] Returning original text.")
        return src_list