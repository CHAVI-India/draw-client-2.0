#!/usr/bin/env python
"""
Log Management Script for DRAW Client
Provides utilities to manage, monitor, and analyze log files
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import gzip
import shutil

# Add Django project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draw_client.settings')
import django
django.setup()

from django.conf import settings

def get_log_files():
    """Get all log files in the logs directory"""
    logs_dir = settings.LOGS_DIR
    if not logs_dir.exists():
        print(f"Logs directory does not exist: {logs_dir}")
        return []
    
    log_files = []
    for file_path in logs_dir.glob('*.log*'):
        stat = file_path.stat()
        log_files.append({
            'name': file_path.name,
            'path': file_path,
            'size_mb': stat.st_size / (1024 * 1024),
            'modified': datetime.fromtimestamp(stat.st_mtime)
        })
    
    return sorted(log_files, key=lambda x: x['modified'], reverse=True)

def show_log_status():
    """Display status of all log files"""
    print("="*80)
    print("DRAW CLIENT - LOG FILE STATUS")
    print("="*80)
    
    log_files = get_log_files()
    if not log_files:
        print("No log files found.")
        return
    
    total_size = 0
    print(f"{'File Name':<30} {'Size (MB)':<12} {'Last Modified':<20}")
    print("-" * 80)
    
    for log_file in log_files:
        size_mb = log_file['size_mb']
        total_size += size_mb
        modified_str = log_file['modified'].strftime('%Y-%m-%d %H:%M:%S')
        print(f"{log_file['name']:<30} {size_mb:<12.2f} {modified_str:<20}")
    
    print("-" * 80)
    print(f"Total log size: {total_size:.2f} MB")
    print(f"Logs directory: {settings.LOGS_DIR}")

def tail_log(log_name, lines=50):
    """Display last N lines of a log file"""
    logs_dir = settings.LOGS_DIR
    log_path = logs_dir / f"{log_name}.log"
    
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return
    
    print(f"="*80)
    print(f"TAIL - {log_name}.log (last {lines} lines)")
    print(f"="*80)
    
    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
            for line in all_lines[-lines:]:
                print(line.rstrip())
    except Exception as e:
        print(f"Error reading log file: {e}")

def follow_log(log_name):
    """Follow a log file in real-time (like tail -f)"""
    logs_dir = settings.LOGS_DIR
    log_path = logs_dir / f"{log_name}.log"
    
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return
    
    print(f"Following {log_name}.log (Press Ctrl+C to stop)")
    print("="*80)
    
    try:
        import time
        with open(log_path, 'r') as f:
            # Go to end of file
            f.seek(0, 2)
            
            while True:
                line = f.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped following log file.")
    except Exception as e:
        print(f"Error following log file: {e}")

def search_logs(pattern, log_name=None, days=7):
    """Search for pattern in log files"""
    logs_dir = settings.LOGS_DIR
    
    if log_name:
        log_files = [logs_dir / f"{log_name}.log"]
    else:
        log_files = list(logs_dir.glob('*.log'))
    
    print(f"Searching for pattern: '{pattern}'")
    print("="*80)
    
    total_matches = 0
    for log_file in log_files:
        if not log_file.exists():
            continue
            
        matches = 0
        try:
            with open(log_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    if pattern.lower() in line.lower():
                        matches += 1
                        total_matches += 1
                        print(f"{log_file.name}:{line_num}: {line.rstrip()}")
        except Exception as e:
            print(f"Error searching {log_file}: {e}")
        
        if matches > 0:
            print(f"\nFound {matches} matches in {log_file.name}")
            print("-" * 40)
    
    print(f"\nTotal matches found: {total_matches}")

def clean_old_logs(days=30):
    """Clean log files older than specified days"""
    logs_dir = settings.LOGS_DIR
    cutoff_date = datetime.now() - timedelta(days=days)
    
    print(f"Cleaning log files older than {days} days...")
    
    cleaned_files = 0
    cleaned_size = 0
    
    for log_file in logs_dir.glob('*.log.*'):  # Rotated logs
        if log_file.stat().st_mtime < cutoff_date.timestamp():
            size_mb = log_file.stat().st_size / (1024 * 1024)
            print(f"Removing: {log_file.name} ({size_mb:.2f} MB)")
            log_file.unlink()
            cleaned_files += 1
            cleaned_size += size_mb
    
    print(f"Cleaned {cleaned_files} files, freed {cleaned_size:.2f} MB")

def compress_old_logs(days=7):
    """Compress log files older than specified days"""
    logs_dir = settings.LOGS_DIR
    cutoff_date = datetime.now() - timedelta(days=days)
    
    print(f"Compressing log files older than {days} days...")
    
    compressed_files = 0
    for log_file in logs_dir.glob('*.log.*'):
        if (log_file.stat().st_mtime < cutoff_date.timestamp() and 
            not log_file.name.endswith('.gz')):
            
            compressed_path = log_file.with_suffix(log_file.suffix + '.gz')
            print(f"Compressing: {log_file.name} -> {compressed_path.name}")
            
            with open(log_file, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            log_file.unlink()
            compressed_files += 1
    
    print(f"Compressed {compressed_files} files")

def main():
    parser = argparse.ArgumentParser(description='DRAW Client Log Management')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Status command
    subparsers.add_parser('status', help='Show log file status')
    
    # Tail command
    tail_parser = subparsers.add_parser('tail', help='Show last N lines of a log')
    tail_parser.add_argument('log_name', help='Log name (without .log extension)')
    tail_parser.add_argument('-n', '--lines', type=int, default=50, help='Number of lines to show')
    
    # Follow command
    follow_parser = subparsers.add_parser('follow', help='Follow log file in real-time')
    follow_parser.add_argument('log_name', help='Log name (without .log extension)')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for pattern in logs')
    search_parser.add_argument('pattern', help='Pattern to search for')
    search_parser.add_argument('-l', '--log', help='Specific log to search (optional)')
    search_parser.add_argument('-d', '--days', type=int, default=7, help='Days to search back')
    
    # Clean command
    clean_parser = subparsers.add_parser('clean', help='Clean old log files')
    clean_parser.add_argument('-d', '--days', type=int, default=30, help='Remove files older than N days')
    
    # Compress command
    compress_parser = subparsers.add_parser('compress', help='Compress old log files')
    compress_parser.add_argument('-d', '--days', type=int, default=7, help='Compress files older than N days')
    
    args = parser.parse_args()
    
    if args.command == 'status':
        show_log_status()
    elif args.command == 'tail':
        tail_log(args.log_name, args.lines)
    elif args.command == 'follow':
        follow_log(args.log_name)
    elif args.command == 'search':
        search_logs(args.pattern, args.log, args.days)
    elif args.command == 'clean':
        clean_old_logs(args.days)
    elif args.command == 'compress':
        compress_old_logs(args.days)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
