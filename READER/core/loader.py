import os
import os.path as osp
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple

from READER.core.scanner import is_image_file

LOGGER = logging.getLogger('READER.loader')

# Attempt to import TextBlock and ProjImgTrans from ballontranslator
HAS_BALLONTRANSLATOR = False
try:
    from ballontranslator.utils.proj_imgtrans import ProjImgTrans
    from ballontranslator.utils.textblock import TextBlock
    HAS_BALLONTRANSLATOR = True
except ImportError:
    TextBlock = None
    ProjImgTrans = None


@dataclass
class MangaPage:
    """Represents a single manga page with its images and text blocks.

    >>> page = MangaPage('001.png', '/path/001.png')
    >>> page.page_name
    '001.png'
    """
    page_name: str
    image_path: str
    inpainted_image_path: Optional[str] = None
    blocks: List[Any] = field(default_factory=list)
    has_inpainted: bool = False

    @property
    def best_background_path(self) -> str:
        """Returns inpainted background image path if available, else raw image path."""
        if self.has_inpainted and self.inpainted_image_path and osp.exists(self.inpainted_image_path):
            return self.inpainted_image_path
        return self.image_path


@dataclass
class MangaProjectData:
    """Loaded manga project containing all pages and text block translation data."""
    manga_dir: str
    title: str
    json_path: Optional[str] = None
    pages: List[MangaPage] = field(default_factory=list)
    page_name_to_idx: Dict[str, int] = field(default_factory=dict)
    raw_dict: Optional[Dict] = None
    verification_status: str = "unverified"
    notes: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def get_page(self, idx: int) -> Optional[MangaPage]:
        if 0 <= idx < len(self.pages):
            return self.pages[idx]
        return None

    def save(self) -> bool:
        """Save text block updates and modifications back to project JSON."""
        if not self.json_path:
            title = osp.basename(self.manga_dir)
            self.json_path = osp.join(self.manga_dir, f"imgtrans_{title}.json")

        # Sync verification_status & notes to metadata.json for fast scanner lookup
        try:
            meta_path = osp.join(self.manga_dir, 'metadata.json')
            meta = {}
            if osp.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            if not isinstance(meta, dict):
                meta = {}
            meta['verification_status'] = self.verification_status
            meta['notes'] = self.notes
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            LOGGER.warning(f"Failed writing metadata.json status: {e}")

        if HAS_BALLONTRANSLATOR and ProjImgTrans:
            try:
                proj = ProjImgTrans()
                proj.directory = self.manga_dir
                proj.proj_path = self.json_path
                pages_dict = {}
                for page in self.pages:
                    pages_dict[page.page_name] = page.blocks
                proj.pages = pages_dict
                
                if hasattr(proj, '_image_info'):
                    proj._image_info['verification_status'] = self.verification_status
                    proj._image_info['notes'] = self.notes
                proj.save()
                LOGGER.info(f"Saved project JSON to {self.json_path}")
                return True
            except Exception as e:
                LOGGER.warning(f"ProjImgTrans save failed, using fallback json writer: {e}")

        # Fallback JSON save
        try:
            pages_dict = {}
            for page in self.pages:
                serialized_blocks = []
                for blk in page.blocks:
                    if hasattr(blk, 'to_dict'):
                        serialized_blocks.append(blk.to_dict())
                    elif isinstance(blk, dict):
                        serialized_blocks.append(blk)
                pages_dict[page.page_name] = serialized_blocks

            data = {
                'directory': self.manga_dir,
                'pages': pages_dict,
                'verification_status': self.verification_status,
                'notes': self.notes,
            }
            tmp_path = self.json_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.json_path)
            LOGGER.info(f"Saved project JSON to {self.json_path}")
            return True
        except Exception as e:
            LOGGER.error(f"Failed saving json to {self.json_path}: {e}")
            return False


def _read_project_status_and_notes(manga_dir: str, json_path: Optional[str] = None) -> Tuple[str, str]:
    """Helper to extract verification status and notes from metadata or translation json."""
    status = "unverified"
    notes = ""

    # 1. Check metadata.json
    meta_path = osp.join(manga_dir, 'metadata.json')
    if osp.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                if isinstance(meta, dict):
                    status = meta.get('verification_status', status)
                    notes = meta.get('notes', notes)
        except Exception:
            pass

    # 2. Check translation json
    if json_path and osp.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    status = data.get('verification_status', data.get('image_info', {}).get('verification_status', status))
                    notes = data.get('notes', data.get('image_info', {}).get('notes', notes))
        except Exception:
            pass

    return status, notes


def load_manga_project(manga_dir: str, json_path: Optional[str] = None) -> MangaProjectData:
    """Load a manga project from directory and optional json path.

    Uses ProjImgTrans if available, falling back to permissive JSON parsing.
    """
    manga_dir = osp.abspath(manga_dir)
    title = osp.basename(manga_dir)

    # Search for json if not supplied
    if not json_path or not osp.exists(json_path):
        json_candidates = [
            osp.join(manga_dir, f"imgtrans_{title}.json"),
        ]
        for f in os.listdir(manga_dir) if osp.exists(manga_dir) else []:
            if f.endswith('.json') and f != 'metadata.json':
                json_candidates.append(osp.join(manga_dir, f))
        
        for cand in json_candidates:
            if osp.exists(cand):
                json_path = cand
                break

    status, notes = _read_project_status_and_notes(manga_dir, json_path)

    # Try loading via ProjImgTrans if available
    if HAS_BALLONTRANSLATOR and json_path and osp.exists(json_path):
        try:
            proj = ProjImgTrans()
            proj.load(manga_dir, json_path=json_path)
            
            pages_list: List[MangaPage] = []
            page_map: Dict[str, int] = {}

            inpainted_dir = osp.join(manga_dir, 'inpainted')

            for idx, pagename in enumerate(proj.pages.keys()):
                raw_img_path = osp.join(manga_dir, pagename)
                
                # Check inpainted directory
                base_name = osp.splitext(pagename)[0]
                inpainted_path = None
                has_inp = False
                for ext in ['.webp', '.png', '.jpg', '.jxl']:
                    candidate = osp.join(inpainted_dir, base_name + ext)
                    if osp.exists(candidate):
                        inpainted_path = candidate
                        has_inp = True
                        break

                blks = proj.pages.get(pagename, [])
                mpage = MangaPage(
                    page_name=pagename,
                    image_path=raw_img_path,
                    inpainted_image_path=inpainted_path,
                    blocks=blks,
                    has_inpainted=has_inp,
                )
                pages_list.append(mpage)
                page_map[pagename] = idx

            if pages_list:
                return MangaProjectData(
                    manga_dir=manga_dir,
                    title=title,
                    json_path=json_path,
                    pages=pages_list,
                    page_name_to_idx=page_map,
                    verification_status=status,
                    notes=notes,
                )
        except Exception as e:
            LOGGER.warning(f"ProjImgTrans load failed for {manga_dir}, using fallback parser: {e}")

    # Fallback JSON parser
    return _load_manga_fallback(manga_dir, json_path)


def _load_manga_fallback(manga_dir: str, json_path: Optional[str] = None) -> MangaProjectData:
    """Fallback loader when ProjImgTrans is unavailable or fails."""
    title = osp.basename(manga_dir)
    img_files = sorted([f for f in os.listdir(manga_dir) if is_image_file(f)]) if osp.exists(manga_dir) else []

    pages_dict: Dict[str, List] = {}
    raw_dict = None
    status, notes = _read_project_status_and_notes(manga_dir, json_path)

    if json_path and osp.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                raw_dict = json.load(f)
                if isinstance(raw_dict, dict) and 'pages' in raw_dict:
                    pages_data = raw_dict['pages']
                    for p_name, b_list in pages_data.items():
                        if HAS_BALLONTRANSLATOR and TextBlock:
                            blocks = [TextBlock(**blk) if isinstance(blk, dict) else blk for blk in b_list]
                        else:
                            blocks = b_list
                        pages_dict[p_name] = blocks
        except Exception as e:
            LOGGER.warning(f"Failed parsing json {json_path}: {e}")

    # Build page list
    pages_list: List[MangaPage] = []
    page_map: Dict[str, int] = {}
    inpainted_dir = osp.join(manga_dir, 'inpainted')

    # Add all images discovered in dir (preserving order)
    all_pagenames = list(img_files)
    for p_name in pages_dict.keys():
        if p_name not in all_pagenames and osp.exists(osp.join(manga_dir, p_name)):
            all_pagenames.append(p_name)

    for idx, pagename in enumerate(all_pagenames):
        raw_img_path = osp.join(manga_dir, pagename)
        base_name = osp.splitext(pagename)[0]
        inpainted_path = None
        has_inp = False
        for ext in ['.webp', '.png', '.jpg', '.jxl']:
            candidate = osp.join(inpainted_dir, base_name + ext)
            if osp.exists(candidate):
                inpainted_path = candidate
                has_inp = True
                break

        blks = pages_dict.get(pagename, [])
        mpage = MangaPage(
            page_name=pagename,
            image_path=raw_img_path,
            inpainted_image_path=inpainted_path,
            blocks=blks,
            has_inpainted=has_inp,
        )
        pages_list.append(mpage)
        page_map[pagename] = idx

    return MangaProjectData(
        manga_dir=manga_dir,
        title=title,
        json_path=json_path,
        pages=pages_list,
        page_name_to_idx=page_map,
        raw_dict=raw_dict,
        verification_status=status,
        notes=notes,
    )
