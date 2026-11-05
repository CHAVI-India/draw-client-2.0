"""
Read-only report of duplicate rows in the DICOM hierarchy.

This command does NOT change any data. It reports exactly the groups that the
migration ``0057_merge_duplicate_dicom_uids_add_unique_constraints`` will merge
before adding the unique constraints:

    1. Studies duplicated by  (patient, study_instance_uid)
    2. Series duplicated by   (study,   series_instance_uid)
    3. Instances duplicated by (series,  sop_instance_uid)

Run it BEFORE the migration to see how many rows will be affected:

    python manage.py detect_dicom_dupes
    python manage.py detect_dicom_dupes --limit 500
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from ...models import DICOMStudy, DICOMSeries, DICOMInstance, Patient


class Command(BaseCommand):
    help = "Report duplicate DICOM study/series/instance UID rows (read-only, changes nothing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of individual groups to print per category (default: 100).",
        )

    def _pk_labels(self, model, pks):
        """Map primary keys to a human-readable label (patient/study/series UID)."""
        pks = list({pk for pk in pks if pk is not None})
        if not pks:
            return {}
        if model is Patient:
            field = "patient_id"
        elif model is DICOMStudy:
            field = "study_instance_uid"
        elif model is DICOMSeries:
            field = "series_instance_uid"
        else:
            return {pk: pk for pk in pks}
        return {pk: val for pk, val in model.objects.filter(id__in=pks).values_list("id", field)}

    def handle(self, *args, **options):
        limit = options["limit"]
        print("=" * 80)
        print("DICOM DUPLICATE DETECTION (read-only)")
        print("=" * 80)

        # 1) Studies -------------------------------------------------------------
        study_groups = list(
            DICOMStudy.objects.values("patient", "study_instance_uid")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("patient", "study_instance_uid")
        )
        self._report(
            title="STUDIES  (unique key: patient + study_instance_uid)",
            groups=study_groups,
            limit=limit,
            label_fn=lambda g: self._pk_labels(Patient, [g["patient"]]).get(g["patient"], "?"),
            uid_key="study_instance_uid",
            parent_key="patient",
        )

        # 2) Series --------------------------------------------------------------
        series_groups = list(
            DICOMSeries.objects.values("study", "series_instance_uid")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("study", "series_instance_uid")
        )
        self._report(
            title="SERIES  (unique key: study + series_instance_uid)",
            groups=series_groups,
            limit=limit,
            label_fn=lambda g: self._pk_labels(DICOMStudy, [g["study"]]).get(g["study"], "?"),
            uid_key="series_instance_uid",
            parent_key="study",
        )

        # 3) Instances -----------------------------------------------------------
        inst_groups = list(
            DICOMInstance.objects.values("series_instance_uid", "sop_instance_uid")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("series_instance_uid", "sop_instance_uid")
        )
        self._report(
            title="INSTANCES  (unique key: series + sop_instance_uid)",
            groups=inst_groups,
            limit=limit,
            label_fn=lambda g: self._pk_labels(DICOMSeries, [g["series_instance_uid"]]).get(g["series_instance_uid"], "?"),
            uid_key="sop_instance_uid",
            parent_key="series_instance_uid",
        )

        # Summary ----------------------------------------------------------------
        print("=" * 80)
        total_removed = sum(g["n"] - 1 for g in study_groups) + \
            sum(g["n"] - 1 for g in series_groups) + \
            sum(g["n"] - 1 for g in inst_groups)
        print(
            "SUMMARY: duplicate groups = "
            f"{len(study_groups)} study / {len(series_groups)} series / {len(inst_groups)} instance. "
            f"Rows that would be removed by the migration: {total_removed}"
        )
        if total_removed == 0:
            print("No duplicates found. It is safe to run the migration as-is.")
        else:
            print("Run the migration to merge these, then re-run this command to confirm 0 remain.")
        print("=" * 80)

    def _report(self, title, groups, limit, label_fn, uid_key, parent_key):
        print("")
        print(f"[{title}]  ->  {len(groups)} duplicate group(s)")
        shown = 0
        for g in groups[:limit]:
            parent_label = label_fn(g)
            print(f"  parent={parent_label!r}  uid={g[uid_key]!r}  count={g['n']}")
            shown += 1
        if len(groups) > limit:
            print(f"  ... and {len(groups) - limit} more group(s) not shown "
                  f"(re-run with --limit {len(groups)} to see all)")
