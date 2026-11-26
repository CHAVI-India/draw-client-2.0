"""
DICOM Viewer Views with RT Structure Overlay
Provides interactive visualization of DICOM images with RT Structure contours
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from .models import DICOMSeries, RTStructureFileImport, DICOMInstance, RTStructureFileVOIData, ContourModificationTypeChoices
import os
import json
import base64
import hashlib
from io import BytesIO
import logging
import pickle
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from .utils.log_masking import mask_sensitive_data

logger = logging.getLogger(__name__)

# Import DICOM and visualization libraries
try:
    import pydicom
    import numpy as np
    from PIL import Image
    from rt_utils import RTStructBuilder
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg
except ImportError as e:
    logger.error(f"Failed to import required libraries: {e}")
    raise


@login_required
def view_rt_structure_list(request, series_uid):
    """
    View to display all RT Structures available for a given series
    Step 1: User clicks "View RT Structure" button and sees list of RT Structures
    """
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    
    # Get all RT Structure imports for this series
    rt_structures = RTStructureFileImport.objects.filter(
        deidentified_series_instance_uid=series
    ).order_by('-created_at')
    
    # Prepare RT Structure data
    rt_structure_data = []
    for rt_struct in rt_structures:
        # Get VOI count
        voi_count = rt_struct.rtstructurefilevoiData_set.count() if hasattr(rt_struct, 'rtstructurefilevoiData_set') else 0
        
        rt_structure_data.append({
            'id': rt_struct.id,
            'reidentified_path': rt_struct.reidentified_rt_structure_file_path,
            'deidentified_path': rt_struct.deidentified_rt_structure_file_path,
            'created_at': rt_struct.created_at,
            'voi_count': voi_count,
            'segmentation_status': rt_struct.server_segmentation_status,
        })
    
    context = {
        'series': series,
        'patient_name': series.study.patient.patient_name,
        'patient_id': series.study.patient.patient_id,
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'rt_structures': rt_structure_data,
        'instance_count': series.instance_count,
    }
    
    return render(request, 'dicom_handler/rt_structure_list.html', context)


@login_required
def dicom_viewer(request, series_uid, rt_structure_id):
    """
    Interactive DICOM viewer with RT Structure overlay
    Step 2: User clicks on specific RT Structure to open viewer
    """
    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)
    
    # Get all DICOM instances for this series
    instances = DICOMInstance.objects.filter(
        series_instance_uid=series
    ).order_by('sop_instance_uid')
    
    # Prepare instance data
    instance_data = []
    for idx, instance in enumerate(instances):
        instance_data.append({
            'index': idx,
            'sop_instance_uid': instance.sop_instance_uid,
            'instance_path': instance.instance_path,
        })
    
    # Get available modification types
    modification_types = ContourModificationTypeChoices.objects.all().order_by('modification_type')
    
    # Check if this RT Structure has already been rated
    has_existing_rating = rt_structure.date_contour_reviewed is not None
    
    # Get existing VOI ratings if they exist
    existing_voi_ratings = {}
    if has_existing_rating:
        voi_data_list = RTStructureFileVOIData.objects.filter(
            rt_structure_file_import=rt_structure
        ).prefetch_related('contour_modification_type')
        
        for voi_data in voi_data_list:
            # Get modification type IDs
            mod_type_ids = [str(mod_type.id) for mod_type in voi_data.contour_modification_type.all()]
            
            existing_voi_ratings[voi_data.volume_name] = {
                'modification': voi_data.contour_modification,
                'modification_types': mod_type_ids,
                'comments': voi_data.contour_modification_comments or '',
            }
    
    context = {
        'series': series,
        'rt_structure': rt_structure,
        'patient_name': series.study.patient.patient_name,
        'patient_id': series.study.patient.patient_id,
        'study_date': series.study.study_date,
        'series_description': series.series_description,
        'instance_count': len(instance_data),
        'series_uid': series_uid,
        'rt_structure_id': str(rt_structure_id),
        'modification_types': modification_types,
        'has_existing_rating': has_existing_rating,
        'existing_assessor': rt_structure.assessor_name,
        'existing_date_reviewed': rt_structure.date_contour_reviewed,
        'existing_modification_time': rt_structure.contour_modification_time_required,
        'existing_overall_rating': rt_structure.overall_rating,
        'existing_voi_ratings_json': json.dumps(existing_voi_ratings),
    }
    
    return render(request, 'dicom_handler/dicom_viewer.html', context)


def _roi_cache_filename(roi_name, ext):
    """
    Return a filesystem-safe cache filename for an ROI name.

    ROI names are attacker-influenceable (they come from RT Structure files and
    are echoed back in the request body), so they are hashed rather than used
    verbatim to prevent path traversal in the mask cache.
    """
    digest = hashlib.sha256(str(roi_name).encode('utf-8')).hexdigest()[:32]
    return f"{digest}{ext}"


SLICE_ORDER_FILENAME = 'slice_order.json'


def _resolve_rt_struct_path(rt_structure):
    """Return an existing path for the RT Structure file of this import."""
    path = rt_structure.reidentified_rt_structure_file_path
    if not path or not os.path.exists(path):
        path = rt_structure.deidentified_rt_structure_file_path
    if not path or not os.path.exists(path):
        raise RuntimeError('RT Structure file not found')
    return path


def _viewer_cache_dir(rt_structure):
    """
    Per-RT-Structure viewer cache directory, created next to the RT
    Structure file itself on the shared datastore volume so that both the
    web and the Celery containers can see it. Holds the slice ordering
    (``slice_order.json``) and the mask cache pickles, and intentionally
    outlives a single viewer session so the next open is faster.
    """
    rt_path = _resolve_rt_struct_path(rt_structure)
    cache_dir = os.path.join(
        os.path.dirname(rt_path) or '.', f"dicom_viewer_cache_{rt_structure.id}"
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _rtstruct_signature(path):
    """
    Small signature of an RT Structure file's (mtime, size). Used to
    namespace the mask cache so a re-segmented file (same path, new
    contents) can never be served stale mask pickles.
    """
    try:
        st = os.stat(path)
        return hashlib.sha256(
            f"{st.st_mtime_ns}:{st.st_size}".encode('utf-8')
        ).hexdigest()[:12]
    except OSError:
        return None


def _mask_cache_dir(temp_dir, rt_struct_path):
    """Mask cache directory, namespaced by the RT Structure signature."""
    sig = _rtstruct_signature(rt_struct_path)
    if sig:
        cache_dir = os.path.join(temp_dir, 'mask_cache', sig)
    else:
        cache_dir = os.path.join(temp_dir, 'mask_cache')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


# Process-level cache of ordered slice paths: {temp_dir: [paths]}
_SLICE_PATHS_CACHE = {}


def _get_slice_paths(temp_dir):
    """
    Return the DICOM file paths in viewer order for a prepared series.

    Modern viewer cache directories carry ``slice_order.json`` written by
    ``prepare_dicom_viewer_data``; the paths point at the original files on
    the datastore (nothing is copied). Legacy directories that still hold
    ``instance_NNNN.dcm`` copies fall back to filename order.
    """
    cached = _SLICE_PATHS_CACHE.get(temp_dir)
    if cached is not None:
        return cached

    order_file = os.path.join(temp_dir, SLICE_ORDER_FILENAME)
    if os.path.exists(order_file):
        with open(order_file) as f:
            paths = [entry['path'] for entry in json.load(f)['slices']]
    else:
        paths = sorted([
            os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
            if f.startswith('instance_') and f.endswith('.dcm')
        ])

    if len(_SLICE_PATHS_CACHE) >= 4:
        _SLICE_PATHS_CACHE.pop(next(iter(_SLICE_PATHS_CACHE)))
    _SLICE_PATHS_CACHE[temp_dir] = paths
    return paths


# ---------------------------------------------------------------------------
# Shared helpers: RT structure caching, image encoding, contour geometry
# ---------------------------------------------------------------------------

# Process-level cache of RT structure bundles. Keyed by (temp_dir, rt_struct_path)
# and invalidated when the RT Structure file's mtime changes, so
# RTStructBuilder.create_from runs once per series instead of per slice request.
_RTSTRUCT_CACHE = {}


def _get_rtstruct_bundle(temp_dir, rt_struct_path):
    """
    Return a cached bundle of parsed RT structure data:
    {'rtstruct', 'series_data', 'sop_to_rt_index', 'roi_color_map', 'available_rois'}
    """
    key = (temp_dir, rt_struct_path)
    try:
        mtime = os.path.getmtime(rt_struct_path)
    except OSError:
        mtime = None

    entry = _RTSTRUCT_CACHE.get(key)
    if entry is not None and entry['mtime'] == mtime:
        logger.debug(f"Using cached RT structure bundle for {temp_dir}")
        return entry['bundle']

    logger.info(f"Building RT structure bundle from {rt_struct_path}")
    # Load the CT series from its original files (viewer order from
    # slice_order.json); rt_utils accepts a list of in-memory datasets.
    series_paths = _get_slice_paths(temp_dir)
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 1) * 2)) as executor:
        series_datasets = list(executor.map(
            lambda p: pydicom.dcmread(p, force=True), series_paths
        ))
    rtstruct = RTStructBuilder.create_from(
        dicom_series_path=series_datasets,
        rt_struct_path=rt_struct_path,
        force=True,
    )
    available_rois = rtstruct.get_roi_names()
    series_data = rtstruct.series_data
    sop_to_rt_index = {
        rt_slice.SOPInstanceUID: rt_idx for rt_idx, rt_slice in enumerate(series_data)
    }

    # Extract ROI colors from the RT Structure file (rainbow fallback)
    roi_color_map = {}
    rt_ds = pydicom.dcmread(rt_struct_path, force=True)
    if hasattr(rt_ds, 'StructureSetROISequence') and hasattr(rt_ds, 'ROIContourSequence'):
        roi_number_to_name = {}
        for roi_item in rt_ds.StructureSetROISequence:
            roi_number_to_name[int(roi_item.ROINumber)] = str(roi_item.ROIName)

        for contour_item in rt_ds.ROIContourSequence:
            roi_name = roi_number_to_name.get(int(contour_item.ReferencedROINumber))
            if roi_name and hasattr(contour_item, 'ROIDisplayColor'):
                color_values = contour_item.ROIDisplayColor
                roi_color_map[roi_name] = (
                    color_values[0] / 255.0,
                    color_values[1] / 255.0,
                    color_values[2] / 255.0,
                )

    if available_rois:
        rainbow_colors = plt.cm.rainbow(np.linspace(0, 1, len(available_rois)))
        for i, roi_name in enumerate(available_rois):
            if roi_name not in roi_color_map:
                roi_color_map[roi_name] = rainbow_colors[i]

    bundle = {
        'rtstruct': rtstruct,
        'series_data': series_data,
        'sop_to_rt_index': sop_to_rt_index,
        'roi_color_map': roi_color_map,
        'available_rois': available_rois,
    }

    # Bound memory: keep at most 2 series bundles in memory
    while len(_RTSTRUCT_CACHE) >= 2:
        _RTSTRUCT_CACHE.pop(next(iter(_RTSTRUCT_CACHE)))
    _RTSTRUCT_CACHE[key] = {'mtime': mtime, 'bundle': bundle}
    logger.info(f"Cached RT structure bundle ({len(available_rois)} ROIs) for {temp_dir}")
    return bundle


def _rgb_to_hex(color):
    """Convert a 0-1 RGB tuple (matplotlib format) to a #rrggbb string."""
    return '#{:02x}{:02x}{:02x}'.format(*(int(round(c * 255)) for c in color[:3]))


def _encode_windowed_png(windowed_array):
    """
    Encode a 0-1 windowed grayscale array as base64 PNG without matplotlib
    (much faster than plt.savefig for plain grayscale slices).
    """
    arr = (np.clip(windowed_array, 0, 1) * 255.0).astype(np.uint8)
    img = Image.fromarray(arr, mode='L')
    buf = BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _simplify_contour(contour, tolerance=0.5):
    """
    Douglas-Peucker simplification of a find_contours point list.
    Returns a flat [x, y, ...] array (2dp) - small enough for JSON transport.
    """
    pts = np.asarray(contour, dtype=np.float64)
    n = len(pts)
    if n <= 4:
        return [round(float(v), 2) for v in pts.ravel().tolist()]
    
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        sub = pts[i + 1:j]
        seg = pts[j] - pts[i]
        seg_len = np.hypot(seg[0], seg[1])
        if seg_len < 1e-12:
            dists = np.hypot(sub[:, 0] - pts[i][0], sub[:, 1] - pts[i][1])
        else:
            # Perpendicular distance of each point to line i->j (cross product)
            dists = np.abs(
                (pts[i][0] - sub[:, 0]) * seg[1] - (pts[i][1] - sub[:, 1]) * seg[0]
            ) / seg_len
        k = i + 1 + int(np.argmax(dists))
        if dists[k - i - 1] > tolerance:
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    
    return [round(float(v), 2) for v in pts[keep].ravel().tolist()]


# Process-level in-memory cache of sparse per-slice ROI masks:
# {(cache_dir, roi_name): {slice_index: (packed_uint8_array, (height, width))}}
# Only non-empty slices are stored, bit-packed (~32x smaller than raw uint8;
# a full 3D mask would be ~64 MB per ROI).
_MASK_MEMORY_CACHE = {}


def _pack_mask_slice(mask_slice):
    """Bit-pack a 2D uint8 mask slice; returns (packed_array, shape)."""
    return (
        np.packbits(mask_slice.astype(np.uint8, copy=False).ravel()),
        tuple(mask_slice.shape),
    )


def _save_sparse_mask_cache(cache_file, sparse):
    with open(cache_file, 'wb') as f:
        pickle.dump(sparse, f)


# Cache of viewer-order SOP lists: {temp_dir: [sop_instance_uid or None, ...]}
_VIEWER_SOP_CACHE = {}


def _get_viewer_sops(temp_dir):
    """
    Return the SOP Instance UIDs in viewer order (instance_NNNN.dcm).
    Used to map RT-structure slice indices onto viewer slice indices -
    the two orderings can differ, even be reversed.
    """
    cached = _VIEWER_SOP_CACHE.get(temp_dir)
    if cached is not None:
        return cached

    order_file = os.path.join(temp_dir, SLICE_ORDER_FILENAME)
    if os.path.exists(order_file):
        with open(order_file) as f:
            sops = [entry.get('sop_instance_uid') for entry in json.load(f)['slices']]
    else:
        # Legacy viewer directories: read SOP UIDs from instance_NNNN.dcm
        dicom_files = sorted([
            os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
            if f.startswith('instance_') and f.endswith('.dcm')
        ])

        def _read_sop(path):
            try:
                return pydicom.dcmread(path, stop_before_pixels=True).SOPInstanceUID
            except Exception as e:
                logger.warning(f"Failed to read SOP Instance UID from {os.path.basename(path)}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=16) as executor:
            sops = list(executor.map(_read_sop, dicom_files))

    if len(_VIEWER_SOP_CACHE) >= 4:
        _VIEWER_SOP_CACHE.pop(next(iter(_VIEWER_SOP_CACHE)))
    _VIEWER_SOP_CACHE[temp_dir] = sops
    return sops


def _load_roi_sparse_mask(rtstruct, roi_name, cache_dir):
    """
    Return the sparse per-slice mask for an ROI:
    {slice_index: (packed_uint8_array, (height, width))}.

    Lookup order: process memory cache -> small disk file (packed sparse dict).
    Legacy full 3D pickles are converted on first access.
    Raises on failure; callers record a '.failed' marker to avoid retries.
    """
    memory_key = (cache_dir, roi_name)
    entry = _MASK_MEMORY_CACHE.get(memory_key)
    if entry is not None:
        return entry

    cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.pkl'))
    if os.path.exists(cache_file):
        with open(cache_file, 'rb') as f:
            data = pickle.load(f)

        if isinstance(data, dict) and data and isinstance(next(iter(data.values())), tuple):
            # Already packed sparse form
            sparse = {int(k): v for k, v in data.items()}
        elif isinstance(data, dict):
            # Sparse but unpacked (older revision): pack and rewrite
            sparse = {int(k): _pack_mask_slice(v) for k, v in data.items()}
            _save_sparse_mask_cache(cache_file, sparse)
            logger.info(f"Converted sparse mask for {roi_name} to packed form")
        else:
            # Legacy full 3D mask: convert to packed sparse and rewrite the file
            mask_3d = np.asarray(data)
            sparse = {}
            if mask_3d.ndim == 3 and mask_3d.any():
                for z in np.where(mask_3d.any(axis=(0, 1)))[0]:
                    sparse[int(z)] = _pack_mask_slice(mask_3d[:, :, z])
            _save_sparse_mask_cache(cache_file, sparse)
            logger.info(f"Converted legacy full mask for {roi_name} to packed sparse cache")

        _MASK_MEMORY_CACHE[memory_key] = sparse
        while len(_MASK_MEMORY_CACHE) >= 64:
            _MASK_MEMORY_CACHE.pop(next(iter(_MASK_MEMORY_CACHE)))
        return sparse

    # Build from the RT structure
    mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
    sparse = {}
    if mask_3d.ndim == 3 and mask_3d.any():
        for z in np.where(mask_3d.any(axis=(0, 1)))[0]:
            sparse[int(z)] = _pack_mask_slice(mask_3d[:, :, z])

    _save_sparse_mask_cache(cache_file, sparse)
    logger.info(f"Cached packed sparse mask for {roi_name} ({len(sparse)} non-empty slices)")

    _MASK_MEMORY_CACHE[memory_key] = sparse
    while len(_MASK_MEMORY_CACHE) >= 64:
        _MASK_MEMORY_CACHE.pop(next(iter(_MASK_MEMORY_CACHE)))
    return sparse


def _roi_geometry_for_slice(sparse_mask, rt_slice_index):
    """
    Return simplified contour geometry for one 2D mask slice:
    a list of contours, each a flat [x, y, ...] array (empty if no data).

    sparse_mask: {slice_index: (packed_uint8_array, (height, width))}
    """
    if rt_slice_index is None:
        return []
    entry = sparse_mask.get(int(rt_slice_index))
    if entry is None:
        return []
    packed, shape = entry
    mask_slice = np.unpackbits(packed, axis=None)[: shape[0] * shape[1]].reshape(shape)

    contours = []
    for contour in find_contours(mask_slice):
        if len(contour) > 2:
            # find_contours returns (row, col) = (y, x); emit (x, y) for the client
            contours.append(_simplify_contour(contour[:, ::-1]))
    return contours


def prepare_dicom_viewer_data(series_uid, rt_structure_id, progress=None):
    """
    Prepare viewer data for a series + RT Structure pair.

    No CT files are copied: slices are read on demand from their original
    location on the shared datastore. The preparation work is (1) reading
    every slice header to build a deterministic viewer ordering, (2)
    persisting that ordering as ``slice_order.json`` next to the RT
    Structure file, and (3) pre-building the per-ROI mask cache pickles in
    the same directory.

    Runs the (potentially long) preparation work. Used both by the
    synchronous ``load_dicom_data`` endpoint and by the Celery task
    ``dicom_handler.prepare_dicom_viewer``.

    progress: optional callback ``progress(stage, done, total)`` where stage
    is one of ``'copy'`` (header scan), ``'sort'`` or ``'structures'``.

    Returns a dict with ``temp_dir`` (the shared cache directory),
    ``temp_rt_struct``, ``instance_files``, ``roi_names`` and ``roi_colors``.
    """
    def _emit(stage, done, total):
        if progress is not None:
            progress(stage, done, total)

    series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
    rt_structure = get_object_or_404(RTStructureFileImport, id=rt_structure_id)

    rt_struct_path = _resolve_rt_struct_path(rt_structure)

    # Shared cache directory next to the RT Structure file (visible to both
    # web and Celery containers); it outlives the session on purpose.
    temp_dir = _viewer_cache_dir(rt_structure)
    order_path = os.path.join(temp_dir, SLICE_ORDER_FILENAME)

    try:
        # Get DICOM instances from database
        instances = list(DICOMInstance.objects.filter(series_instance_uid=series))

        # STEP 1: Read headers only (stop before pixel data) from the
        # original files on the datastore, in parallel, to get sort keys
        max_workers = min(16, (os.cpu_count() or 1) * 4)
        logger.info(f"Scanning {len(instances)} DICOM file headers in parallel using {max_workers} workers")

        def _scan_instance(instance):
            if not instance.instance_path or not os.path.exists(instance.instance_path):
                return None
            try:
                ds = pydicom.dcmread(instance.instance_path, stop_before_pixels=True, force=True)
                return {
                    'sop_instance_uid': instance.sop_instance_uid,
                    'path': instance.instance_path,
                    'instance_number': int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else 0,
                    'slice_location': float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else 0.0,
                    'image_position': float(ds.ImagePositionPatient[2]) if hasattr(ds, 'ImagePositionPatient') else 0.0,
                }
            except Exception as e:
                logger.warning(f"Failed to read header for {instance.sop_instance_uid}: {e}")
                return None

        entries = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_scan_instance, inst) for inst in instances]
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                if done_count % 5 == 0 or done_count == len(futures):
                    _emit('copy', done_count, len(futures))
                result = future.result()
                if result is not None:
                    entries.append(result)

        logger.info(f"Scanned {len(entries)} out of {len(instances)} DICOM file headers")

        if not entries:
            raise RuntimeError('No DICOM files could be read for this series')

        # STEP 2: Sort and persist the viewer ordering. Nothing is copied or
        # renamed: slice N resolves to slices[N]['path'] via
        # slice_order.json, which both web and worker processes read.
        entries.sort(key=lambda x: (x['instance_number'], x['slice_location'], x['image_position']))
        logger.info(f"Sorted {len(entries)} DICOM slices by instance number and slice location")

        _emit('sort', 0, 1)
        instance_files = []
        for idx, entry in enumerate(entries):
            instance_files.append({
                'index': idx,
                'path': entry['path'],
                'sop_instance_uid': entry['sop_instance_uid'],
            })
        with open(order_path + '.tmp', 'w') as f:
            json.dump({
                'series_uid': series.series_instance_uid,
                'slices': instance_files,
            }, f)
        os.replace(order_path + '.tmp', order_path)

        _emit('sort', 1, 1)
        logger.info(f"Prepared {len(instance_files)} sorted DICOM slices (order in {order_path})")

        # Load RT Structure to get ROI names and colors (cached for later slice requests)
        try:
            bundle = _get_rtstruct_bundle(temp_dir, rt_struct_path)
            roi_names = bundle['available_rois']
            roi_colors = {
                name: {
                    'r': int(round(c[0] * 255)),
                    'g': int(round(c[1] * 255)),
                    'b': int(round(c[2] * 255)),
                }
                for name, c in bundle['roi_color_map'].items()
            }
        except Exception as e:
            logger.error(f"Failed to load RT Structure: {e}")
            roi_names = []
            roi_colors = {}

        # Pre-build the sparse mask cache for every structure up front so the
        # viewer is fully ready before the first slice is shown
        if roi_names:
            cache_dir = _mask_cache_dir(temp_dir, rt_struct_path)
            total = len(roi_names)
            for i, roi_name in enumerate(roi_names, start=1):
                cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.pkl'))
                failed_cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.failed'))
                if os.path.exists(cache_file) or os.path.exists(failed_cache_file):
                    continue
                try:
                    _load_roi_sparse_mask(bundle['rtstruct'], roi_name, cache_dir)
                except Exception as e:
                    logger.error(f"Failed to pre-build mask for {roi_name}: {e}")
                    with open(failed_cache_file, 'w') as f:
                        f.write(str(e))
                _emit('structures', i, total)

        return {
            'temp_dir': temp_dir,
            'temp_rt_struct': rt_struct_path,
            'instance_files': instance_files,
            'roi_names': roi_names,
            'roi_colors': roi_colors,
        }
    except Exception:
        # Drop only the ordering file: the mask cache next to the RT
        # Structure is intentionally kept for reuse.
        for p in (order_path, order_path + '.tmp'):
            try:
                os.remove(p)
            except OSError:
                pass
        raise


@login_required
@require_http_methods(["POST"])
def load_dicom_data(request):
    """
    Synchronous API endpoint to load DICOM files and RT Structure into a
    temporary directory. The page normally uses the Celery flow
    (``start_dicom_load`` + ``get_dicom_load_progress``); this endpoint is
    kept for direct usage and tests.
    """
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        rt_structure_id = data.get('rt_structure_id')

        if not series_uid or not rt_structure_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            }, status=400)

        try:
            result = prepare_dicom_viewer_data(series_uid, rt_structure_id)
        except Http404:
            return JsonResponse({
                'success': False,
                'error': 'Series or RT Structure not found'
            }, status=404)

        request.session['dicom_temp_dir'] = result['temp_dir']
        request.session['rt_struct_path'] = result['temp_rt_struct']
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'temp_dir': result['temp_dir'],
            'instance_count': len(result['instance_files']),
            'roi_names': result['roi_names'],
            'roi_colors': result['roi_colors'],
        })

    except Exception as e:
        logger.error("Error loading DICOM data", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to load DICOM data'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def start_dicom_load(request):
    """
    Start the Celery task that prepares the viewer data (file copy, slice
    sorting, structure parsing and mask pre-warm) and return immediately.
    The page then polls ``get_dicom_load_progress`` for progress.
    """
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        rt_structure_id = data.get('rt_structure_id')

        if not series_uid or not rt_structure_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            }, status=400)

        get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        get_object_or_404(RTStructureFileImport, id=rt_structure_id)

        from .viewer_tasks import prepare_dicom_viewer_task

        progress_key = f"viewer_progress_{request.session.session_key}"
        cache.set(progress_key, {
            'stage': 'queued',
            'copy': {'done': 0, 'total': 0},
            'structures': {'done': 0, 'total': 0},
        }, timeout=3600)

        task = prepare_dicom_viewer_task.delay(
            request.session.session_key, series_uid, rt_structure_id
        )
        return JsonResponse({'success': True, 'task_id': task.id})

    except Http404:
        return JsonResponse({
            'success': False,
            'error': 'Series or RT Structure not found'
        }, status=404)
    except Exception as e:
        logger.error("Error starting DICOM load task", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to start DICOM load'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def get_dicom_load_progress(request):
    """Return the progress record of the viewer preparation task."""
    progress_key = f"viewer_progress_{request.session.session_key}"
    progress = cache.get(progress_key)
    if progress is None:
        return JsonResponse({
            'success': False,
            'error': 'No load in progress. Please reload the page.'
        }, status=404)
    return JsonResponse({'success': True, 'progress': progress})



@login_required
@require_http_methods(["POST"])
def get_dicom_slice(request):
    """
    API endpoint to get a specific DICOM slice with RT Structure overlay
    Returns base64-encoded image
    """
    try:
        data = json.loads(request.body)
        slice_index = int(data.get('slice_index', 0))
        window_center = float(data.get('window_center', 40))
        window_width = float(data.get('window_width', 400))
        selected_rois = data.get('selected_rois', [])
        
        # Get temp directory from session
        temp_dir = request.session.get('dicom_temp_dir')
        rt_struct_path = request.session.get('rt_struct_path')
        
        if not temp_dir:
            return JsonResponse({
                'success': False,
                'error': 'Session expired. Please reload the page.'
            }, status=400)
        if not os.path.exists(temp_dir):
            return JsonResponse({
                'success': False,
                'error': 'Viewer data not found on this server. Please reload the page.'
            }, status=400)

        # Ordered slice paths (originals on the datastore, via slice_order.json)
        dicom_files = _get_slice_paths(temp_dir)

        if slice_index < 0 or slice_index >= len(dicom_files):
            return JsonResponse({
                'success': False,
                'error': 'Invalid slice index'
            }, status=400)
        
        # Load DICOM file
        dicom_file = dicom_files[slice_index]
        ds = pydicom.dcmread(dicom_file, force = True)
        
        # Log current slice information
        instance_number = int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else None
        slice_location = float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None
        image_position = ds.ImagePositionPatient[2] if hasattr(ds, 'ImagePositionPatient') else None
        logger.info(f"Current DICOM slice {slice_index}: InstanceNumber={instance_number}, SliceLocation={slice_location}, ImagePosition Z={image_position}")
        
        # Get pixel array
        pixel_array = ds.pixel_array.astype(float)
        
        # Apply rescale slope and intercept if available
        if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
            pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept
        
        # Apply windowing
        windowed_array = apply_windowing(pixel_array, window_center, window_width)
        
        # Base image: windowed grayscale PNG (no matplotlib overhead)
        image_base64 = _encode_windowed_png(windowed_array)
        
        # Track failed ROIs; contour geometry is drawn client-side on a canvas
        failed_rois = []
        geometry = {}
        
        # Extract RT Structure contour geometry if selected (drawn in the browser)
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                logger.info(f"Selected ROIs: {selected_rois}")
                
                cache_dir = _mask_cache_dir(temp_dir, rt_struct_path)
                
                # Cached RT structure bundle (built once per series, not per slice)
                bundle = _get_rtstruct_bundle(temp_dir, rt_struct_path)
                rtstruct = bundle['rtstruct']
                available_rois = bundle['available_rois']
                roi_color_map = bundle['roi_color_map']
                sop_to_rt_index = bundle['sop_to_rt_index']
                
                # Find which rt-utils slice index corresponds to our current DICOM file
                current_sop_uid = ds.SOPInstanceUID
                rt_slice_index = sop_to_rt_index.get(current_sop_uid)
                
                if rt_slice_index is None:
                    logger.warning(f"Could not find matching slice for SOP UID {current_sop_uid}")
                    # Fallback: use the slice index as-is
                    rt_slice_index = slice_index
                
                contours_found = 0
                for idx, roi_name in enumerate(selected_rois):
                    if roi_name not in available_rois:
                        logger.warning(f"Skipping requested ROI not present in RT Structure: {roi_name}")
                        failed_rois.append(roi_name)
                        continue
                    try:
                        failed_cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.failed'))
                        
                        # Check if this ROI failed previously
                        if os.path.exists(failed_cache_file):
                            logger.info(f"Skipping {roi_name} (previously failed)")
                            failed_rois.append(roi_name)
                            continue
                        
                        # Load the sparse per-slice mask (memory cache, then file)
                        try:
                            sparse_mask = _load_roi_sparse_mask(rtstruct, roi_name, cache_dir)
                        except Exception as mask_error:
                            logger.error(f"Failed to load mask for ROI '{roi_name}': {mask_error}")
                            logger.error(f"Skipping ROI '{roi_name}' and continuing with other structures")
                            failed_rois.append(roi_name)
                            
                            # Mark as failed so we don't retry
                            with open(failed_cache_file, 'w') as f:
                                f.write(str(mask_error))
                            continue
                        
                        contours = _roi_geometry_for_slice(sparse_mask, rt_slice_index)
                        contours_found += len(contours)
                        geometry[roi_name] = {
                            'color': _rgb_to_hex(roi_color_map[roi_name]),
                            'contours': contours,
                        }
                            
                    except Exception as e:
                        logger.error(f"Failed to extract geometry for ROI {roi_name}: {e}", exc_info=True)
                        continue
                
                logger.info(f"Total contours extracted: {contours_found}")
                    
            except Exception as e:
                logger.error(f"Failed to extract RT Structure geometry: {e}", exc_info=True)
        
        # Get slice metadata
        metadata = {
            'slice_location': float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None,
            'instance_number': int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else slice_index + 1,
            'slice_thickness': float(ds.SliceThickness) if hasattr(ds, 'SliceThickness') else None,
        }
        
        return JsonResponse({
            'success': True,
            'image': image_base64,
            'geometry': geometry,
            'metadata': metadata,
            'slice_index': slice_index,
            'total_slices': len(dicom_files),
            'failed_rois': failed_rois,
        })
        
    except Exception as e:
        logger.error("Error getting DICOM slice", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to get DICOM slice'
        }, status=500)
@login_required
@require_http_methods(["POST"])
def get_structure_geometry(request):
    """
    API endpoint to get contour geometry (all slices) for the requested ROIs.
    Compact JSON: only slices where the structure is present are included.
    """
    try:
        data = json.loads(request.body)
        selected_rois = data.get('selected_rois', [])
        
        temp_dir = request.session.get('dicom_temp_dir')
        rt_struct_path = request.session.get('rt_struct_path')
        
        if not temp_dir:
            return JsonResponse({
                'success': False,
                'error': 'Session expired. Please reload the page.'
            }, status=400)
        if not os.path.exists(temp_dir):
            return JsonResponse({
                'success': False,
                'error': 'Viewer data not found on this server. Please reload the page.'
            }, status=400)

        failed_rois = []
        structures = {}
        
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                bundle = _get_rtstruct_bundle(temp_dir, rt_struct_path)
                available_rois = bundle['available_rois']
                roi_color_map = bundle['roi_color_map']
                sop_to_rt_index = bundle['sop_to_rt_index']
                
                # Map RT-structure slice indices to viewer slice indices (the
                # two orderings can differ, even be reversed)
                rt_to_viewer = {}
                for viewer_idx, sop in enumerate(_get_viewer_sops(temp_dir)):
                    rt_idx = sop_to_rt_index.get(sop)
                    if rt_idx is not None:
                        rt_to_viewer[rt_idx] = viewer_idx
                
                cache_dir = _mask_cache_dir(temp_dir, rt_struct_path)
                
                for roi_name in selected_rois:
                    if roi_name not in available_rois:
                        logger.warning(f"Skipping requested ROI not present in RT Structure: {roi_name}")
                        failed_rois.append(roi_name)
                        continue
                    
                    failed_cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.failed'))
                    if os.path.exists(failed_cache_file):
                        logger.info(f"Skipping {roi_name} (previously failed)")
                        failed_rois.append(roi_name)
                        continue
                    
                    try:
                        sparse_mask = _load_roi_sparse_mask(bundle['rtstruct'], roi_name, cache_dir)
                    except Exception as e:
                        logger.error(f"Failed to load mask for ROI '{roi_name}': {e}")
                        failed_rois.append(roi_name)
                        with open(failed_cache_file, 'w') as f:
                            f.write(str(e))
                        continue
                    
                    slices = {}
                    for z in sparse_mask:
                        contours = _roi_geometry_for_slice(sparse_mask, z)
                        if contours:
                            # Key by VIEWER slice index so contours land on the
                            # correct slice regardless of series ordering
                            slices[str(rt_to_viewer.get(z, z))] = contours
                    if slices:
                        structures[roi_name] = {
                            'color': _rgb_to_hex(roi_color_map[roi_name]),
                            'slices': slices,
                        }
            except Exception as e:
                logger.error(f"Failed to extract structure geometry: {e}", exc_info=True)
        
        return JsonResponse({
            'success': True,
            'structures': structures,
            'failed_rois': failed_rois,
        })
        
    except Exception as e:
        logger.error("Error getting structure geometry", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to get structure geometry'
        }, status=500)



@login_required
@require_http_methods(["POST"])
def render_all_slices(request):
    """
    API endpoint to pre-render all DICOM slices for browser caching.
    Returns array of base64-encoded images for all slices.
    """
    try:
        data = json.loads(request.body)
        window_center = float(data.get('window_center', 40))
        window_width = float(data.get('window_width', 400))
        selected_rois = data.get('selected_rois', [])
        
        # Get temp directory from session
        temp_dir = request.session.get('dicom_temp_dir')
        rt_struct_path = request.session.get('rt_struct_path')
        
        if not temp_dir:
            return JsonResponse({
                'success': False,
                'error': 'Session expired. Please reload the page.'
            }, status=400)
        if not os.path.exists(temp_dir):
            return JsonResponse({
                'success': False,
                'error': 'Viewer data not found on this server. Please reload the page.'
            }, status=400)

        # Ordered slice paths (originals on the datastore, via slice_order.json)
        dicom_files = _get_slice_paths(temp_dir)

        logger.info(f"Pre-rendering {len(dicom_files)} slices with window C/W: {window_center}/{window_width}")
        
        # Prepare RT Structure data if needed (cached bundle, built once per series)
        rtstruct = None
        series_data = None
        roi_color_map = {}
        sop_to_rt_index = {}
        
        if selected_rois and rt_struct_path and os.path.exists(rt_struct_path):
            try:
                bundle = _get_rtstruct_bundle(temp_dir, rt_struct_path)
                rtstruct = bundle['rtstruct']
                series_data = bundle['series_data']
                roi_color_map = bundle['roi_color_map']
                sop_to_rt_index = bundle['sop_to_rt_index']
                available_rois = bundle['available_rois']
                
                # Pre-load masks
                cache_dir = _mask_cache_dir(temp_dir, rt_struct_path)
                
                for roi_name in selected_rois:
                    if roi_name not in available_rois:
                        logger.warning(f"Skipping requested ROI not present in RT Structure: {roi_name}")
                        continue
                    failed_cache_file = os.path.join(cache_dir, _roi_cache_filename(roi_name, '.failed'))
                    if os.path.exists(failed_cache_file):
                        continue
                    try:
                        _load_roi_sparse_mask(rtstruct, roi_name, cache_dir)
                    except Exception as e:
                        logger.error(f"Failed to cache mask for {roi_name}: {e}")
                        with open(failed_cache_file, 'w') as f:
                            f.write(str(e))
                            
            except Exception as e:
                logger.error(f"Failed to prepare RT Structure: {e}")
                rtstruct = None
        
        # Render all slices in parallel
        def render_single_slice(slice_idx):
            try:
                dicom_file = dicom_files[slice_idx]
                ds = pydicom.dcmread(dicom_file, force=True)
                
                # Get pixel array
                pixel_array = ds.pixel_array.astype(float)
                
                # Apply rescale
                if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
                    pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept
                
                # Apply windowing and encode the base image (no matplotlib)
                windowed_array = apply_windowing(pixel_array, window_center, window_width)
                image_base64 = _encode_windowed_png(windowed_array)
                
                # Collect contour geometry (drawn client-side on a canvas)
                geometry = {}
                if rtstruct and selected_rois:
                    rt_slice_index = sop_to_rt_index.get(ds.SOPInstanceUID)
                    if rt_slice_index is None:
                        rt_slice_index = slice_idx
                    
                    cache_dir = _mask_cache_dir(temp_dir, rt_struct_path)
                    
                    for roi_name in selected_rois:
                        if roi_name not in roi_color_map:
                            continue
                        try:
                            sparse_mask = _load_roi_sparse_mask(rtstruct, roi_name, cache_dir)
                            contours = _roi_geometry_for_slice(sparse_mask, rt_slice_index)
                            if contours:
                                geometry[roi_name] = {
                                    'color': _rgb_to_hex(roi_color_map[roi_name]),
                                    'contours': contours,
                                }
                        except Exception as e:
                            logger.error(f"Failed to extract {roi_name} on slice {slice_idx}: {e}")
                
                # Get metadata
                metadata = {
                    'slice_location': float(ds.SliceLocation) if hasattr(ds, 'SliceLocation') else None,
                    'instance_number': int(ds.InstanceNumber) if hasattr(ds, 'InstanceNumber') else slice_idx + 1,
                }
                
                return {
                    'index': slice_idx,
                    'image': image_base64,
                    'geometry': geometry,
                    'metadata': metadata,
                }
            except Exception as e:
                logger.error(f"Failed to render slice {slice_idx}: {e}")
                return None
        
        # Render all slices in parallel
        max_workers = min(8, (os.cpu_count() or 1) * 2)
        rendered_slices = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(render_single_slice, idx): idx for idx in range(len(dicom_files))}
            
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    rendered_slices.append(result)
        
        # Sort by index
        rendered_slices.sort(key=lambda x: x['index'])
        
        logger.info(f"Successfully rendered {len(rendered_slices)} out of {len(dicom_files)} slices")
        
        return JsonResponse({
            'success': True,
            'slices': rendered_slices,
            'total_slices': len(dicom_files),
        })
        
    except Exception as e:
        logger.error("Error rendering all slices", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to render slices'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def cleanup_temp_files(request):
    """
    API endpoint to cleanup temporary files when viewer is closed
    """
    try:
        # Clear session variables. The shared cache (slice order + mask
        # pickles) next to the RT Structure is intentionally kept so the
        # next viewer session for the same series/structure pair can reuse it.
        request.session.pop('dicom_temp_dir', None)
        request.session.pop('rt_struct_path', None)
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'message': 'Temporary files cleaned up'
        })
        
    except Exception as e:
        logger.error("Error cleaning up temp files", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to clean up temporary files'
        }, status=500)


def apply_windowing(pixel_array, window_center, window_width):
    """
    Apply window/level to pixel array
    """
    img_min = window_center - window_width / 2
    img_max = window_center + window_width / 2
    
    windowed = np.clip(pixel_array, img_min, img_max)
    windowed = (windowed - img_min) / (img_max - img_min)
    
    return windowed


def find_contours(mask_slice, level=0.5):
    """
    Find contours in a binary mask slice
    """
    try:
        from skimage import measure
        contours = measure.find_contours(mask_slice, level)
        return contours
    except ImportError:
        # Fallback: use matplotlib's contour finding
        import matplotlib._contour as _contour
        # Simple edge detection
        edges = np.zeros_like(mask_slice)
        edges[:-1, :] |= (mask_slice[:-1, :] != mask_slice[1:, :])
        edges[:, :-1] |= (mask_slice[:, :-1] != mask_slice[:, 1:])
        
        # Find coordinates of edges
        y, x = np.where(edges)
        if len(x) > 0:
            points = np.column_stack([y, x])
            return [points]
        return []


@login_required
@require_http_methods(["POST"])
def save_contour_ratings(request):
    """
    Save contour quality ratings from the DICOM viewer
    """
    try:
        data = json.loads(request.body)
        series_uid = data.get('series_uid')
        overall_rating = data.get('overall_rating')
        assessor_name = data.get('assessor_name')
        modification_time = data.get('modification_time')
        date_reviewed = data.get('date_reviewed')
        structure_ratings = data.get('structure_ratings', {})
        
        # Validate required fields
        if not assessor_name or not assessor_name.strip():
            return JsonResponse({
                'success': False,
                'error': 'Assessor name is required'
            }, status=400)
        
        if modification_time is None:
            return JsonResponse({
                'success': False,
                'error': 'Time required (in minutes) is required'
            }, status=400)
        
        if not date_reviewed:
            return JsonResponse({
                'success': False,
                'error': 'Date contour reviewed is required'
            }, status=400)
        
        # Validate modification_time is a positive number
        try:
            modification_time = int(modification_time)
            if modification_time < 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Time required must be a positive number'
                }, status=400)
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'Time required must be a valid number'
            }, status=400)
        
        logger.info(f"Saving ratings for series {series_uid}")
        
        # Get the series
        series = get_object_or_404(DICOMSeries, series_instance_uid=series_uid)
        
        # Get the RT Structure import for this series
        rt_import = RTStructureFileImport.objects.filter(
            deidentified_series_instance_uid=series
        ).first()
        
        if not rt_import:
            return JsonResponse({
                'success': False,
                'error': 'No RT Structure found for this series'
            }, status=404)
        
        # Update RT Structure level data
        rt_import.overall_rating = overall_rating
        rt_import.assessor_name = request.user.get_full_name() or request.user.username
        rt_import.date_contour_reviewed = timezone.now().date()
        if modification_time is not None:
            rt_import.contour_modification_time_required = modification_time
        rt_import.save()
        
        logger.info(f"Updated RT Structure {rt_import.id} with overall rating {overall_rating}")
        
        # Save individual structure ratings
        saved_count = 0
        for roi_name, rating_data in structure_ratings.items():
            # Get or create VOI data
            voi_data, created = RTStructureFileVOIData.objects.get_or_create(
                rt_structure_file_import=rt_import,
                volume_name=roi_name,
                defaults={
                    'contour_modification': rating_data.get('modification', 'NO_MODIFICATION'),
                    'contour_modification_comments': rating_data.get('comments', '')
                }
            )
            
            if not created:
                # Update existing
                voi_data.contour_modification = rating_data.get('modification', 'NO_MODIFICATION')
                voi_data.contour_modification_comments = rating_data.get('comments', '')
                voi_data.save()
            
            # Handle modification types (M2M relationship)
            modification_type_ids = rating_data.get('modification_types', [])
            if modification_type_ids:
                # Clear existing and set new
                voi_data.contour_modification_type.clear()
                for type_id in modification_type_ids:
                    try:
                        mod_type = ContourModificationTypeChoices.objects.get(id=type_id)
                        voi_data.contour_modification_type.add(mod_type)
                    except ContourModificationTypeChoices.DoesNotExist:
                        logger.warning(f"Modification type {type_id} not found")
            else:
                # Clear all if none selected
                voi_data.contour_modification_type.clear()
            
            saved_count += 1
            logger.info(f"Saved rating for {roi_name}: {rating_data.get('modification')} with {len(modification_type_ids)} modification types")
        
        return JsonResponse({
            'success': True,
            'message': f'Saved ratings for {saved_count} structures',
            'rt_import_id': str(rt_import.id)
        })
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error("Error saving ratings", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to save ratings'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_modification_types(request):
    """
    API endpoint to fetch all available contour modification types
    """
    try:
        modification_types = ContourModificationTypeChoices.objects.all().order_by('modification_type')
        
        types_list = [
            {
                'id': str(mod_type.id),
                'name': mod_type.modification_type
            }
            for mod_type in modification_types
        ]
        
        return JsonResponse({
            'success': True,
            'modification_types': types_list
        })
    except Exception as e:
        logger.error("Error fetching modification types", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Failed to fetch modification types'
        }, status=500)
