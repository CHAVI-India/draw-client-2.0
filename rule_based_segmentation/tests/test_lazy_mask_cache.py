"""Tests for ``LazyMaskCache`` — the engine's mask store that decodes ROI
contours on demand instead of up-front, so a rule only pays for the structures
it actually references (the dominant cost in a pipeline step).
"""

import tempfile
import uuid

import numpy as np
import SimpleITK as sitk
from django.test import TestCase

from rule_based_segmentation.utils.engine import LazyMaskCache
from .helpers import create_synthetic_ct_series


class _SpyRTStruct:
    """Duck-typed RTStructBuilder that counts ``get_roi_mask_by_name`` calls so
    a test can prove decoding happens lazily (and only on demand)."""

    def __init__(self, names_to_masks):
        self._masks = names_to_masks  # name -> (Y, X, Z) bool array
        self.decoded = []

    def get_roi_names(self):
        return list(self._masks.keys())

    def get_roi_mask_by_name(self, name):
        self.decoded.append(name)
        return self._masks[name]


class LazyMaskCacheTests(TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.series_uid = str(uuid.uuid4())
        self.study_uid = str(uuid.uuid4())
        ct = create_synthetic_ct_series(
            self.temp, num_slices=4, rows=8, cols=8,
            series_uid=self.series_uid, study_uid=self.study_uid,
        )
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(sorted(ct))
        self.ct = reader.Execute()

    def _spy(self):
        a = np.zeros((8, 8, 4), dtype=bool)
        a[1:3, 1:3, 1:3] = True
        b = np.zeros((8, 8, 4), dtype=bool)
        b[0:2, 0:2, 0:2] = True
        return _SpyRTStruct({"A": a, "B": b}), 8, 8

    def test_no_eager_decode_and_keys_are_free(self):
        spy, _, _ = self._spy()
        cache = LazyMaskCache(spy, self.ct)
        self.assertEqual(spy.decoded, [])  # nothing decoded at construction
        self.assertEqual(set(cache.keys()), {"A", "B"})
        self.assertEqual(spy.decoded, [])  # keys() did not decode either

    def test_contains(self):
        spy, _, _ = self._spy()
        cache = LazyMaskCache(spy, self.ct)
        self.assertIn("A", cache)
        self.assertIn("B", cache)
        self.assertNotIn("C", cache)
        self.assertEqual(spy.decoded, [])

    def test_decode_on_access_and_cache(self):
        spy, _, a_count = self._spy()
        cache = LazyMaskCache(spy, self.ct)
        m_a = cache["A"]
        self.assertEqual(spy.decoded, ["A"])  # decoded once, on first access
        self.assertIsInstance(m_a, sitk.Image)
        self.assertEqual(int(sitk.GetArrayFromImage(m_a).sum()), a_count)
        m_a_again = cache["A"]
        self.assertEqual(spy.decoded, ["A"])  # cached: no second decode
        self.assertIs(m_a, m_a_again)

    def test_setitem_stores_rule_output_without_decode(self):
        spy, _, _ = self._spy()
        cache = LazyMaskCache(spy, self.ct)
        m = cache["A"]
        cache["Produced"] = m
        self.assertIn("Produced", cache)
        self.assertIn("Produced", cache.keys())
        self.assertIs(cache["Produced"], m)
        self.assertEqual(spy.decoded, ["A"])  # setitem did not decode

    def test_get_default_and_missing_keyerror(self):
        spy, _, _ = self._spy()
        cache = LazyMaskCache(spy, self.ct)
        self.assertIsNone(cache.get("missing"))
        with self.assertRaises(KeyError):
            cache["missing"]
        self.assertEqual(spy.decoded, [])  # a miss never decodes
