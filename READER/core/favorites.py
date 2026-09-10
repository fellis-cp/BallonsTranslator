import os
import os.path as osp
import json
import logging
from typing import Set

LOGGER = logging.getLogger('READER.favorites')


class FavoritesManager:
    """Manages persistent list of favorited manga directories."""

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            reader_dir = osp.abspath(osp.join(osp.dirname(__file__), '..'))
            storage_path = osp.join(reader_dir, 'favorites.json')
        self.storage_path = storage_path
        self._favorites: Set[str] = set()
        self.load()

    def load(self) -> None:
        """Load favorite relative paths from disk."""
        if osp.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._favorites = set(data)
            except Exception as e:
                LOGGER.warning(f"Failed loading favorites from {self.storage_path}: {e}")

    def save(self) -> None:
        """Save favorite paths back to disk."""
        try:
            tmp_path = self.storage_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(sorted(list(self._favorites)), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
        except Exception as e:
            LOGGER.warning(f"Failed saving favorites to {self.storage_path}: {e}")

    def _get_keys(self, identifier: str) -> Set[str]:
        if not identifier:
            return set()
        norm = osp.normpath(identifier)
        base = osp.basename(norm)
        return {identifier, norm, base}

    def is_favorite(self, identifier: str) -> bool:
        """Check if a manga (by relative path, full path, or folder name) is favorited."""
        if not identifier:
            return False
        keys = self._get_keys(identifier)
        return any(k in self._favorites for k in keys)

    def set_favorite(self, identifier: str, favorite: bool) -> bool:
        """Add or remove an identifier from favorites."""
        if not identifier:
            return False
        keys = self._get_keys(identifier)
        if favorite:
            self._favorites.update(keys)
        else:
            self._favorites.difference_update(keys)
        self.save()
        return favorite

    def toggle_favorite(self, identifier: str) -> bool:
        """Toggle favorite state for identifier and save."""
        new_state = not self.is_favorite(identifier)
        self.set_favorite(identifier, new_state)
        return new_state


# Global singleton instance
FAVORITES = FavoritesManager()
