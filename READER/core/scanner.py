import os
import os.path as osp
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

IMAGE_EXTENSIONS = {'.webp', '.jpg', '.jpeg', '.png', '.jxl', '.bmp'}
IGNORE_DIRS = {'mask', 'inpainted', 'result', 'assets', '.btrans_cache', '.git'}


@dataclass
class MangaItem:
    """Represents a discovered translated manga folder.

    >>> manga = MangaItem('Chapter 1', '/path/to/chap1', 'chap1', 10, True)
    >>> manga.title
    'Chapter 1'
    >>> manga.page_count
    10
    """
    title: str
    path: str
    relative_path: str
    page_count: int
    has_translation: bool
    cover_image_path: Optional[str] = None
    json_path: Optional[str] = None
    author: str = "Unknown"
    artists: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    verification_status: str = "unverified"  # "unverified", "needs_fix", "verified"
    notes: str = ""
    mtime: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'path': self.path,
            'relative_path': self.relative_path,
            'page_count': self.page_count,
            'has_translation': self.has_translation,
            'cover_image_path': self.cover_image_path,
            'json_path': self.json_path,
            'author': self.author,
            'artists': self.artists,
            'tags': self.tags,
            'verification_status': self.verification_status,
            'notes': self.notes,
            'mtime': self.mtime,
        }


def is_image_file(filename: str) -> bool:
    """Check if a filename ends with a supported image extension.

    >>> is_image_file('001.webp')
    True
    >>> is_image_file('doc.pdf')
    False
    """
    ext = osp.splitext(filename)[1].lower()
    return ext in IMAGE_EXTENSIONS


def find_manga_in_dir(dir_path: str, root_dir: str) -> Optional[MangaItem]:
    """Inspect a directory to see if it is a manga folder.

    A valid manga directory contains at least one image file.
    """
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return None

    img_files = sorted([e for e in entries if is_image_file(e)])
    if not img_files:
        return None

    # Check for translation JSON
    json_files = [e for e in entries if e.endswith('.json')]
    json_path = None
    has_translation = False
    verification_status = "unverified"
    notes = ""

    # Prefer imgtrans_*.json matching folder name or any imgtrans_*.json
    folder_name = osp.basename(dir_path)
    preferred_json = f"imgtrans_{folder_name}.json"
    if preferred_json in entries:
        json_path = osp.join(dir_path, preferred_json)
        has_translation = True
    else:
        # Search for any imgtrans_*.json or json file containing "pages"
        for jf in json_files:
            if jf == 'metadata.json':
                continue
            jp = osp.join(dir_path, jf)
            try:
                with open(jp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'pages' in data:
                        json_path = jp
                        has_translation = True
                        verification_status = data.get('verification_status', verification_status)
                        notes = data.get('notes', notes)
                        break
            except Exception:
                continue

    # Metadata extraction & Author detection
    artists = []
    tags = []
    title = folder_name
    rel_path = osp.relpath(dir_path, root_dir)
    rel_parts = rel_path.split(os.sep)

    # Deriving author:
    # 1. From metadata.json artists list if available
    # 2. From directory structure (e.g. TRANSLATED/Hiryu Ran/Chapter 1 -> Author: "Hiryu Ran")
    author = "Unknown"
    if len(rel_parts) > 1:
        author = rel_parts[0]

    meta_path = osp.join(dir_path, 'metadata.json')
    if osp.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
                if isinstance(meta, dict):
                    if meta.get('title'):
                        title = meta['title']
                    if isinstance(meta.get('artists'), list) and meta['artists']:
                        artists = [str(a) for a in meta['artists']]
                        author = artists[0].title()
                    if isinstance(meta.get('tags'), list):
                        tags = [t.get('tag') if isinstance(t, dict) else str(t) for t in meta['tags']]
                    if meta.get('verification_status'):
                        verification_status = meta['verification_status']
                    if meta.get('notes'):
                        notes = meta['notes']
        except Exception:
            pass

    cover_path = osp.join(dir_path, img_files[0])
    
    # Use newest mtime between directory and json
    mtime = osp.getmtime(dir_path)
    if json_path and osp.exists(json_path):
        mtime = max(mtime, osp.getmtime(json_path))

    return MangaItem(
        title=title,
        path=osp.abspath(dir_path),
        relative_path=rel_path,
        page_count=len(img_files),
        has_translation=has_translation,
        cover_image_path=cover_path,
        json_path=json_path,
        author=author,
        artists=artists,
        tags=tags,
        verification_status=verification_status,
        notes=notes,
        mtime=mtime,
    )



def scan_translated_directory(root_dir: str) -> List[MangaItem]:
    """Recursively scan root_dir for all translated manga directories.

    >>> import tempfile, os
    >>> with tempfile.TemporaryDirectory() as tmpdir:
    ...     manga_dir = os.path.join(tmpdir, 'TestManga')
    ...     os.makedirs(manga_dir)
    ...     with open(os.path.join(manga_dir, '01.png'), 'w') as f: f.write('')
    ...     items = scan_translated_directory(tmpdir)
    ...     len(items)
    1
    """
    if not osp.exists(root_dir) or not osp.isdir(root_dir):
        return []

    items: List[MangaItem] = []
    visited_dirs = set()

    for current_root, dirs, files in os.walk(root_dir):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

        item = find_manga_in_dir(current_root, root_dir)
        if item and item.path not in visited_dirs:
            visited_dirs.add(item.path)
            items.append(item)

    # Sort by mtime descending (most recently modified first)
    items.sort(key=lambda x: x.mtime, reverse=True)
    return items
