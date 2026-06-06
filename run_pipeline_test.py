#!/usr/bin/env python3
"""
Interactive test script for ROI generation pipeline operations.

This script provides an easy way to test pipeline operations with your CT and RT Structure data.
"""

import os
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django
django.setup()

from test_pipeline_operations import PipelineExecutor
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    print("=" * 70)
    print("ROI Generation Pipeline Test Script")
    print("=" * 70)
    print()
    
    # Get CT directory
    print("Step 1: CT Series")
    print("-" * 70)
    ct_dir = input("Enter path to CT DICOM series directory: ").strip()
    if not os.path.isdir(ct_dir):
        print(f"ERROR: Directory not found: {ct_dir}")
        return 1
    print(f"✓ Found CT directory: {ct_dir}")
    print()
    
    # Get RT Struct file
    print("Step 2: RT Structure Set")
    print("-" * 70)
    rtstruct_path = input("Enter path to RT Structure Set file: ").strip()
    if not os.path.isfile(rtstruct_path):
        print(f"ERROR: File not found: {rtstruct_path}")
        return 1
    print(f"✓ Found RT Struct file: {rtstruct_path}")
    print()
    
    # Load data
    print("Step 3: Loading Data")
    print("-" * 70)
    try:
        executor = PipelineExecutor(ct_dir, rtstruct_path)
        print(f"✓ Loaded CT series")
        print(f"✓ Loaded RT Structure Set")
        print()
    except Exception as e:
        print(f"ERROR: Failed to load data: {e}")
        return 1
    
    # Show available structures
    print("Available Structures:")
    print("-" * 70)
    for idx, name in enumerate(executor.original_structures.keys(), 1):
        print(f"  {idx}. {name}")
    print()
    
    # Choose pipeline method
    print("Step 4: Pipeline Definition")
    print("-" * 70)
    print("Choose how to define the pipeline:")
    print("  1. Load from JSON file")
    print("  2. Use example pipeline (expand CTV by 5mm)")
    print("  3. Create custom pipeline interactively")
    choice = input("Enter choice (1-3): ").strip()
    print()
    
    pipeline_json = None
    
    if choice == '1':
        # Load from file
        pipeline_file = input("Enter path to pipeline JSON file: ").strip()
        if not os.path.isfile(pipeline_file):
            print(f"ERROR: File not found: {pipeline_file}")
            return 1
        try:
            with open(pipeline_file, 'r') as f:
                pipeline_json = json.load(f)
            print(f"✓ Loaded pipeline from: {pipeline_file}")
        except Exception as e:
            print(f"ERROR: Failed to load pipeline: {e}")
            return 1
            
    elif choice == '2':
        # Example pipeline
        structure_name = input("Enter structure name to expand (e.g., CTV): ").strip()
        if structure_name not in executor.original_structures:
            print(f"ERROR: Structure '{structure_name}' not found")
            print(f"Available: {list(executor.original_structures.keys())}")
            return 1
        
        margin = input("Enter margin in mm (default: 5.0): ").strip()
        margin = float(margin) if margin else 5.0
        
        pipeline_json = {
            "operations": [
                {
                    "type": "expand",
                    "structures": [structure_name],
                    "parameters": {
                        "margin_mm": margin,
                        "kernel_type": "ball"
                    }
                },
                {
                    "type": "smooth",
                    "parameters": {
                        "smoothing_mm": 2.0,
                        "iterations": 1
                    }
                }
            ]
        }
        print(f"✓ Created pipeline: Expand {structure_name} by {margin}mm + smooth")
        
    elif choice == '3':
        # Interactive pipeline builder
        print("Interactive Pipeline Builder")
        print("-" * 70)
        operations = []
        
        while True:
            print("\nAvailable operation types:")
            print("  1. expand - Expand structure by margin")
            print("  2. contract - Contract structure by margin")
            print("  3. union - Combine multiple structures")
            print("  4. intersection - Keep overlapping region")
            print("  5. subtract - Remove structures")
            print("  6. smooth - Smooth surface")
            print("  7. fill_holes - Fill internal cavities")
            print("  0. Done - Finish pipeline")
            
            op_choice = input("\nSelect operation (0-7): ").strip()
            
            if op_choice == '0':
                break
            
            if op_choice == '1':  # Expand
                struct = input("Structure name: ").strip()
                if struct not in executor.original_structures:
                    print(f"WARNING: Structure '{struct}' not found")
                    continue
                margin = float(input("Margin (mm): ").strip())
                operations.append({
                    "type": "expand",
                    "structures": [struct],
                    "parameters": {"margin_mm": margin, "kernel_type": "ball"}
                })
                print(f"✓ Added: Expand {struct} by {margin}mm")
                
            elif op_choice == '2':  # Contract
                struct = input("Structure name: ").strip()
                if struct not in executor.original_structures:
                    print(f"WARNING: Structure '{struct}' not found")
                    continue
                margin = float(input("Margin (mm): ").strip())
                operations.append({
                    "type": "contract",
                    "structures": [struct],
                    "parameters": {"margin_mm": margin, "kernel_type": "ball"}
                })
                print(f"✓ Added: Contract {struct} by {margin}mm")
                
            elif op_choice == '3':  # Union
                print("Enter structure names (comma-separated):")
                structs = input().strip().split(',')
                structs = [s.strip() for s in structs]
                operations.append({
                    "type": "union",
                    "structures": structs
                })
                print(f"✓ Added: Union of {structs}")
                
            elif op_choice == '4':  # Intersection
                print("Enter structure names (comma-separated):")
                structs = input().strip().split(',')
                structs = [s.strip() for s in structs]
                operations.append({
                    "type": "intersection",
                    "structures": structs
                })
                print(f"✓ Added: Intersection of {structs}")
                
            elif op_choice == '5':  # Subtract
                print("Enter structure names to subtract (comma-separated):")
                structs = input().strip().split(',')
                structs = [s.strip() for s in structs]
                operations.append({
                    "type": "subtract",
                    "structures": structs
                })
                print(f"✓ Added: Subtract {structs}")
                
            elif op_choice == '6':  # Smooth
                smoothing = float(input("Smoothing (mm, default 2.0): ").strip() or "2.0")
                operations.append({
                    "type": "smooth",
                    "parameters": {"smoothing_mm": smoothing, "iterations": 1}
                })
                print(f"✓ Added: Smooth {smoothing}mm")
                
            elif op_choice == '7':  # Fill holes
                operations.append({"type": "fill_holes"})
                print(f"✓ Added: Fill holes")
        
        if not operations:
            print("ERROR: No operations defined")
            return 1
            
        pipeline_json = {"operations": operations}
        print(f"\n✓ Created pipeline with {len(operations)} operations")
    
    else:
        print("ERROR: Invalid choice")
        return 1
    
    print()
    
    # Show pipeline
    print("Pipeline to Execute:")
    print("-" * 70)
    print(json.dumps(pipeline_json, indent=2))
    print()
    
    # Confirm execution
    confirm = input("Execute this pipeline? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return 0
    print()
    
    # Execute pipeline
    print("Step 5: Executing Pipeline")
    print("-" * 70)
    try:
        executor.execute_pipeline(pipeline_json)
        print("✓ Pipeline executed successfully")
        print()
    except Exception as e:
        print(f"ERROR: Pipeline execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Save result
    print("Step 6: Saving Result")
    print("-" * 70)
    output_path = input("Enter output RT Struct path (default: output_rtstruct.dcm): ").strip()
    output_path = output_path if output_path else "output_rtstruct.dcm"
    
    structure_name = input("Enter name for generated structure (default: Generated_Structure): ").strip()
    structure_name = structure_name if structure_name else "Generated_Structure"
    
    color_input = input("Enter RGB color (default: 255,0,0 for red): ").strip()
    if color_input:
        try:
            color = [int(c) for c in color_input.split(',')]
        except:
            print("Invalid color format, using red")
            color = [255, 0, 0]
    else:
        color = [255, 0, 0]
    
    try:
        executor.save_result(output_path, structure_name, color)
        print()
        print("=" * 70)
        print("SUCCESS!")
        print("=" * 70)
        print(f"Output saved to: {output_path}")
        print(f"Generated structure: {structure_name}")
        print(f"Color: RGB{tuple(color)}")
        print()
        print("Next steps:")
        print("  1. Open the output file in your DICOM viewer")
        print("  2. Verify the generated structure looks correct")
        print("  3. Compare with original structures")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"ERROR: Failed to save result: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
