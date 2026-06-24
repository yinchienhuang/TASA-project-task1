#!/usr/bin/env python3
"""
Convert MHTML files to plain text.

Extracts text content from all MHTML reports in data/JCO report/
and saves as .txt files in output directory.

Usage:
    python benchmark/mhtml_to_text.py                    # Convert all, output to ./text_reports/
    python benchmark/mhtml_to_text.py --output /path/to/dir   # Specify output directory
    python benchmark/mhtml_to_text.py --single file.mhtml     # Convert single file
"""
import sys
import argparse
from pathlib import Path

# Add backend to path
backend_root = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_root))

from modules.knowledge_graph.mhtml_reader import read_mhtml


def convert_single_file(mhtml_path, output_path):
    """Convert a single MHTML file to text."""
    try:
        text = read_mhtml(mhtml_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        return True, None
    except Exception as e:
        return False, str(e)


def convert_all_reports(output_dir=None):
    """Convert all MHTML reports in data/JCO report/ to text files."""
    if output_dir is None:
        output_dir = Path(__file__).parent / "text_reports"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all MHTML files
    report_dir = Path(__file__).parent.parent / "data" / "JCO report"

    if not report_dir.exists():
        print(f"Error: Report directory not found: {report_dir}")
        return False

    mhtml_files = sorted(report_dir.glob("*.mhtml"))

    if not mhtml_files:
        print(f"Error: No MHTML files found in {report_dir}")
        return False

    print(f"Found {len(mhtml_files)} MHTML files")
    print(f"Output directory: {output_dir}")
    print()

    success_count = 0
    error_count = 0

    for i, mhtml_path in enumerate(mhtml_files, 1):
        # Create output filename: replace .mhtml with .txt
        output_filename = mhtml_path.stem + ".txt"
        output_path = output_dir / output_filename

        print(f"[{i:2d}/{len(mhtml_files)}] {mhtml_path.name}...", end=" ", flush=True)

        success, error = convert_single_file(mhtml_path, output_path)

        if success:
            # Get file size
            size_kb = output_path.stat().st_size / 1024
            print(f"[OK] {size_kb:.1f} KB")
            success_count += 1
        else:
            print(f"[ERROR] {error}")
            error_count += 1

    print()
    print("=" * 70)
    print(f"Conversion complete: {success_count} success, {error_count} failed")
    print(f"Output directory: {output_dir}")
    print("=" * 70)

    return error_count == 0


def main():
    parser = argparse.ArgumentParser(
        description="Convert MHTML files to plain text",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python benchmark/mhtml_to_text.py                           # Convert all to ./text_reports/
  python benchmark/mhtml_to_text.py --output /tmp/texts       # Specify output dir
  python benchmark/mhtml_to_text.py --single "data/JCO report/file.mhtml"  # Convert one file
        """
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output directory for .txt files (default: ./text_reports/)"
    )
    parser.add_argument(
        "--single",
        type=str,
        help="Convert a single MHTML file and save as text"
    )

    args = parser.parse_args()

    if args.single:
        # Single file conversion
        mhtml_path = Path(args.single)
        if not mhtml_path.exists():
            print(f"Error: File not found: {mhtml_path}")
            sys.exit(1)

        # Output to same name with .txt extension
        output_path = mhtml_path.parent / (mhtml_path.stem + ".txt")
        print(f"Converting: {mhtml_path}")
        print(f"Output: {output_path}")

        success, error = convert_single_file(mhtml_path, output_path)
        if success:
            print(f"[OK] Conversion successful")
            sys.exit(0)
        else:
            print(f"[ERROR] {error}")
            sys.exit(1)
    else:
        # Convert all reports
        success = convert_all_reports(args.output)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
