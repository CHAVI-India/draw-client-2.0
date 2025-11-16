# DICOM Viewer with RT Structure Overlay - Implementation Guide

## Overview
This document describes the implementation of an interactive DICOM viewer with RT Structure overlay capabilities using matplotlib, pydicom, and rt-utils. The viewer allows users to visualize DICOM images with RT Structure contours overlaid, with interactive controls for slice navigation, window/level adjustment, and ROI selection.

## Architecture

### Components Created

1. **Views** (`dicom_handler/dicom_viewer_views.py`)
   - `view_rt_structure_list()` - Lists all RT Structures for a series
   - `dicom_viewer()` - Main viewer interface
   - `load_dicom_data()` - API endpoint to load DICOM files into temp directory
   - `get_dicom_slice()` - API endpoint to render slice with overlays
   - `cleanup_temp_files()` - API endpoint to cleanup temporary files

2. **Templates**
   - `templates/dicom_handler/rt_structure_list.html` - RT Structure selection page
   - `templates/dicom_handler/dicom_viewer.html` - Interactive viewer interface

3. **URL Patterns** (`dicom_handler/urls.py`)
   - `/dicom-handler/rt-structures/<series_uid>/` - RT Structure list
   - `/dicom-handler/dicom-viewer/<series_uid>/<rt_structure_id>/` - Viewer
   - `/dicom-handler/api/dicom-viewer/load-data/` - Load data API
   - `/dicom-handler/api/dicom-viewer/get-slice/` - Get slice API
   - `/dicom-handler/api/dicom-viewer/cleanup/` - Cleanup API

## User Workflow

### Step 1: View RT Structure List
User clicks "View RT Structures" button on series processing status page → navigates to RT Structure list page showing all available RT Structure sets for the series.

### Step 2: Open Viewer
User clicks "Open Viewer" button for a specific RT Structure → opens interactive DICOM viewer.

### Step 3: Interact with Viewer
- **Scroll through slices**: Use mouse wheel, slider, or prev/next buttons
- **Adjust window/level**: Use sliders or preset buttons (Soft Tissue, Lung, Bone, Brain, Liver)
- **Select ROIs**: Check/uncheck structures in the right panel
- **Apply overlay**: Click "Apply Overlay" to render selected contours

## Technical Implementation

### File Management

Files are copied to a temporary directory when the viewer loads to ensure fast access and avoid conflicts: 


```python
# Files are copied to temporary directory when viewer loads
temp_dir = tempfile.mkdtemp(prefix='dicom_viewer_')

# DICOM instances copied from database paths
for instance in instances:
    temp_file = os.path.join(temp_dir, f'instance_{idx:04d}.dcm')
    shutil.copy2(instance.instance_path, temp_file)

# RT Structure file copied
temp_rt_struct = os.path.join(temp_dir, 'rtstruct.dcm')
shutil.copy2(rt_struct_path, temp_rt_struct)

# Temp directory path stored in session
request.session['dicom_temp_dir'] = temp_dir
```

### DICOM Image Rendering

```python
# Load DICOM file
ds = pydicom.dcmread(dicom_file)
pixel_array = ds.pixel_array.astype(float)

# Apply rescale slope and intercept
if hasattr(ds, 'RescaleSlope') and hasattr(ds, 'RescaleIntercept'):
    pixel_array = pixel_array * ds.RescaleSlope + ds.RescaleIntercept

# Apply windowing
windowed_array = apply_windowing(pixel_array, window_center, window_width)
```

### Window/Level Application

```python
def apply_windowing(pixel_array, window_center, window_width):
    """Apply window/level to pixel array"""
    img_min = window_center - window_width / 2
    img_max = window_center + window_width / 2
    
    windowed = np.clip(pixel_array, img_min, img_max)
    windowed = (windowed - img_min) / (img_max - img_min)
    
    return windowed
```
### RT Structure Overlay

```python
# Load RT Structure using rt-utils
rtstruct = RTStructBuilder.create_from(
    dicom_series_path=temp_dir,
    rt_struct_path=rt_struct_path
)

# Get ROI names
roi_names = rtstruct.get_roi_names()

# For each selected ROI
for roi_name in selected_rois:
    # Get 3D mask
    mask_3d = rtstruct.get_roi_mask_by_name(roi_name)
    
    # Extract slice
    mask_slice = mask_3d[:, :, slice_index]
    
    # Find and draw contours
    contours = find_contours(mask_slice)
    for contour in contours:
        ax.plot(contour[:, 1], contour[:, 0], 
               color=colors[idx], linewidth=2, label=roi_name)
```

### Contour Detection

```python
def find_contours(mask_slice, level=0.5):
    """Find contours in a binary mask slice"""
    try:
        from skimage import measure
        contours = measure.find_contours(mask_slice, level)
        return contours
    except ImportError:
        # Fallback: simple edge detection
        edges = np.zeros_like(mask_slice)
        edges[:-1, :] |= (mask_slice[:-1, :] != mask_slice[1:, :])
        edges[:, :-1] |= (mask_slice[:, :-1] != mask_slice[:, 1:])
        
        y, x = np.where(edges)
        if len(x) > 0:
            points = np.column_stack([y, x])
            return [points]
        return []
```

## Key Features

### 1. Interactive Slice Navigation
- Mouse wheel scrolling through slices
- Slider for quick navigation
- Previous/Next buttons
- Real-time slice information display

### 2. Window/Level Control
- Adjustable window center and width sliders
- Preset buttons for common tissue types:
  - **Soft Tissue**: WC=40, WW=400
  - **Lung**: WC=-600, WW=1500
  - **Bone**: WC=400, WW=1800
  - **Brain**: WC=50, WW=350
  - **Liver**: WC=60, WW=360

### 3. ROI Selection
- Checkbox list of all available structures
- Select All / Deselect All buttons
- Color-coded contour overlays
- Legend showing structure names

### 4. Performance Optimization
- Files loaded into temporary directory on viewer open
- Session-based temporary file management
- Automatic cleanup on page unload
- Base64-encoded image transmission

## Dependencies

```
pydicom==3.0.1          # DICOM file reading
matplotlib==3.10.7      # Image rendering and plotting
rt-utils==0.3           # RT Structure parsing
numpy==2.3.4            # Array operations
scikit-image==0.24.0    # Contour detection
pillow==12.0.0          # Image processing
```

## Database Models Used

```python
# DICOMSeries - Main series information
series = DICOMSeries.objects.get(series_instance_uid=series_uid)

# RTStructureFileImport - RT Structure file information
rt_structure = RTStructureFileImport.objects.get(id=rt_structure_id)
# Fields: reidentified_rt_structure_file_path, deidentified_rt_structure_file_path

# DICOMInstance - Individual DICOM image files
instances = DICOMInstance.objects.filter(series_instance_uid=series)
# Fields: sop_instance_uid, instance_path
```

## Usage Examples

### Basic Matplotlib DICOM Viewing

```python
import matplotlib.pyplot as plt
import pydicom

# Load single DICOM file
dicom_file_path = "path/to/your/dicom/file.dcm"
ds = pydicom.dcmread(dicom_file_path)

# Get window/level from DICOM metadata
window_center = ds.WindowCenter
window_width = ds.WindowWidth

# Apply windowing and display
windowed_data = apply_windowing(ds.pixel_array, window_center, window_width)
plt.imshow(windowed_data, cmap='gray')
plt.show()
```

### RT Structure Loading with RTUtils

```python
from rt_utils import RTStructBuilder
import matplotlib.pyplot as plt

# Load RT Structure with series
rtstruct = RTStructBuilder.create_from(
    dicom_series_path="path/to/your/dicom/series", 
    rt_struct_path="path/to/your/rt-struct.dcm"
)

# Get all ROI names
roi_names = rtstruct.get_roi_names()
print(f"Available ROIs: {roi_names}")

# Load 3D mask for specific ROI
mask_3d = rtstruct.get_roi_mask_by_name("ROI NAME")

# Display one slice
first_mask_slice = mask_3d[:, :, 0]
plt.imshow(first_mask_slice, cmap='jet', alpha=0.5)
plt.show()
```

## Security Considerations

1. **Authentication Required**: All views decorated with `@login_required`
2. **CSRF Protection**: All POST requests require CSRF token
3. **Session-based Access**: Temporary files tied to user session
4. **Automatic Cleanup**: Temporary files removed on page unload
5. **Path Validation**: File paths validated before access

## Troubleshooting

### Issue: RT Structure not displaying
- **Check**: RT Structure file path exists in database
- **Check**: File is accessible from application
- **Check**: ROIs are selected in the panel
- **Solution**: Verify `reidentified_rt_structure_file_path` or fallback to `deidentified_rt_structure_file_path`

### Issue: Contours not matching images
- **Cause**: UID mismatch between RT Structure and DICOM images
- **Solution**: RT-utils handles spatial coordinate matching automatically
- **Note**: Z-coordinate matching used for proper slice alignment

### Issue: Slow performance
- **Cause**: Large number of slices or complex contours
- **Solution**: Optimize by caching rendered slices or reducing overlay complexity
- **Tip**: Deselect unused ROIs to improve rendering speed

### Issue: Session expired error
- **Cause**: Temporary files cleaned up or session timeout
- **Solution**: Reload the page to reinitialize the viewer
