"""Reusability check for the persisted synthetic known-box RTStruct.

The synthetic fixture (``tests/dicom_data/synthetic/synthetic_boxes_rtstruct.dcm``)
is a committed, reusable artifact: a copy of the de-identified RTStruct whose ROIs
are the known boxes in :mod:`synthetic_fixture`, linked to the de-identified CT.
This test confirms it loads and that every box still matches its definition, so
the fixture can be reused directly (e.g. opened in a viewer, or as a fixed input
for ad-hoc pipeline runs) without rebuilding.

DB-free and fast (no CT-series import / engine run).
"""

import os
import tempfile

from django.test import SimpleTestCase

from .synthetic_fixture import (
    KNOWN_BOXES,
    SYNTHETIC_FIXTURE_PATH,
    find_deidentified_dataset,
    generate_persistent_fixture,
    verify_fixture_boxes,
)


class CommittedSyntheticFixtureTests(SimpleTestCase):
    def test_committed_fixture_is_reusable(self):
        ct_dir, _ct_files, _rt = find_deidentified_dataset()

        if os.path.exists(SYNTHETIC_FIXTURE_PATH):
            # Use the committed artifact.
            path = SYNTHETIC_FIXTURE_PATH
        else:
            # Not committed in this checkout: build a throwaway copy and check it,
            # so the suite stays meaningful without writing into the repo.
            path = os.path.join(tempfile.mkdtemp(prefix="syn_fixture_"), "syn.dcm")
            generate_persistent_fixture(out_path=path)

        self.assertTrue(os.path.exists(path))
        results = verify_fixture_boxes(path, ct_dir)
        for name in KNOWN_BOXES:
            with self.subTest(box=name):
                self.assertTrue(
                    results.get(name),
                    f"{name} in the synthetic fixture does not match its definition",
                )
