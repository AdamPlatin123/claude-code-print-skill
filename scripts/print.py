#!/usr/bin/env python3
"""
print.py - Generic Windows PDF printer with duplex & color control.

Workflow: PDF → pymupdf render → PNG images → C# PrintEngine → Windows spooler

Usage (standalone):
    python print.py <pdf_path> [--duplex vertical|horizontal|simplex] [--color mono|color] [--printer <name>]

When called without --printer, discovers all physical printers and prints to the first suitable one.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

# --- Constants ---
CSC_PATH = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
CS_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "PrintEngine.cs")
PRINT_DPI = 200

# Virtual printer patterns to skip
VIRTUAL_PATTERNS = [
    "pdf", "xps", "fax", "onenote", "microsoft print",
    "rustdesk", "kingsoft", "wps", "send to", "print to",
    "document writer", "virtual",
]


def check_dependencies():
    """Verify all required tools are available."""
    errors = []

    if not os.path.exists(CSC_PATH):
        errors.append(f"C# compiler not found: {CSC_PATH}")

    try:
        import pymupdf
    except ImportError:
        errors.append("pymupdf not installed. Run: pip install pymupdf")

    try:
        from PIL import Image
    except ImportError:
        errors.append("Pillow not installed. Run: pip install Pillow")

    return errors


def discover_printers():
    """Discover all physical (non-virtual) printers with capabilities.

    Returns list of dicts: [{name, driver, port, ip, duplex_supported, color_supported}, ...]
    """
    cmd = (
        'Get-Printer | ForEach-Object {'
        '  $p = $_;'
        '  $port = Get-PrinterPort -Name $p.PortName -ErrorAction SilentlyContinue;'
        '  [PSCustomObject]@{'
        '    Name=$p.Name;'
        '    Driver=$p.DriverName;'
        '    PortName=$p.PortName;'
        '    Status=$p.PrinterStatus;'
        '    IP=$(if($port){$port.PrinterHostAddress}else{"N/A"})'
        '  }'
        '} | ConvertTo-Json -Compress'
    )
    result = subprocess.run(
        ["powershell", "-Command", cmd],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    raw = json.loads(result.stdout.strip())
    if isinstance(raw, dict):
        raw = [raw]

    printers = []
    for p in raw:
        name_lower = p["Name"].lower()
        # Skip virtual printers
        if any(vp in name_lower for vp in VIRTUAL_PATTERNS):
            continue
        if p.get("Status", -1) != 0:  # 0 = Normal
            continue

        printers.append({
            "name": p["Name"],
            "driver": p.get("Driver", "Unknown"),
            "port": p.get("PortName", ""),
            "ip": p.get("IP", "N/A"),
        })

    return printers


def query_printer_capabilities(printer_name):
    """Query duplex and color support via C# helper.

    Returns dict: {duplex: bool, color: bool}
    """
    # Build a small C# program to query capabilities
    query_code = f'''
using System;
using System.Drawing.Printing;
class Q {{
    static void Main() {{
        try {{
            var ps = new PrinterSettings();
            ps.PrinterName = @"{printer_name}";
            if (!ps.IsValid) {{ Console.WriteLine("invalid"); return; }}
            bool dup = ps.CanDuplex;
            bool col = ps.SupportsColor;
            Console.WriteLine(dup ? "duplex=yes" : "duplex=no");
            Console.WriteLine(col ? "color=yes" : "color=no");
        }} catch (Exception ex) {{
            Console.WriteLine("error:" + ex.Message);
        }}
    }}
}}
'''
    tmp_dir = tempfile.mkdtemp(prefix="printquery_")
    cs_path = os.path.join(tmp_dir, "query.cs")
    exe_path = os.path.join(tmp_dir, "query.exe")

    with open(cs_path, "w", encoding="utf-8") as f:
        f.write(query_code)

    subprocess.run(
        [CSC_PATH, "/nologo", f"/out:{exe_path}", cs_path],
        capture_output=True, timeout=15,
    )

    result = subprocess.run([exe_path], capture_output=True, text=True, timeout=15)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    caps = {"duplex": False, "color": False}
    for line in result.stdout.strip().splitlines():
        if "duplex=yes" in line:
            caps["duplex"] = True
        if "color=yes" in line:
            caps["color"] = True

    return caps


def render_pdf(pdf_path, dpi=PRINT_DPI):
    """Render PDF pages to PNG images. Returns list of image file paths."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    tmp_dir = tempfile.mkdtemp(prefix="pdfprint_")
    images = []

    for i, page in enumerate(doc):
        mat = pymupdf.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_path = os.path.join(tmp_dir, f"page_{i:04d}.png")
        pix.save(img_path)
        images.append(img_path)

    doc.close()
    return images


def compile_print_engine(output_path):
    """Compile PrintEngine.cs to exe. Returns True on success."""
    cs_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "src", "PrintEngine.cs"))
    result = subprocess.run(
        [CSC_PATH, "/nologo", f"/out:{output_path}", cs_path],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


def print_images(images, printer_name, duplex_mode, color_mode):
    """Print images via compiled PrintEngine.exe."""
    # Compile engine to same temp dir as images
    engine_dir = os.path.dirname(images[0])
    engine_exe = os.path.join(engine_dir, "PrintEngine.exe")

    if not compile_print_engine(engine_exe):
        print("ERROR: Failed to compile PrintEngine.cs", file=sys.stderr)
        return False

    args = [engine_exe, printer_name, duplex_mode, color_mode] + images
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)

    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    return result.returncode == 0


def cleanup(images):
    """Remove temporary image files and compiled exe."""
    if not images:
        return
    tmp_dir = os.path.dirname(images[0])
    for f in images:
        try:
            os.remove(f)
        except OSError:
            pass
    # Remove compiled exe if exists
    exe = os.path.join(tmp_dir, "PrintEngine.exe")
    try:
        os.remove(exe)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(description="Print PDF with duplex/color control")
    parser.add_argument("pdf", nargs="?", help="Path to PDF file (not needed with --list)")
    parser.add_argument("--printer", "-p", help="Printer name (auto-detect if omitted)")
    parser.add_argument("--duplex", "-d",
                        choices=["simplex", "vertical", "horizontal"],
                        default="vertical", help="Duplex mode (default: vertical)")
    parser.add_argument("--color", "-c",
                        choices=["mono", "color"],
                        default="mono", help="Color mode (default: mono)")
    parser.add_argument("--dpi", type=int, default=PRINT_DPI, help="Render DPI (default: 200)")
    parser.add_argument("--list", action="store_true", help="List available printers and exit")

    args = parser.parse_args()

    # Check dependencies
    errors = check_dependencies()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Discover printers
    printers = discover_printers()

    if args.list:
        if not printers:
            print("No physical printers found.")
            sys.exit(0)
        print(f"{'Name':<45} {'IP':<18} {'Driver'}")
        print("-" * 90)
        for p in printers:
            caps = query_printer_capabilities(p["name"])
            flags = []
            if caps["duplex"]:
                flags.append("duplex")
            if caps["color"]:
                flags.append("color")
            cap_str = ",".join(flags) if flags else "basic"
            print(f"{p['name']:<45} {str(p.get('ip','N/A')):<18} {p.get('driver','Unknown')}")
            print(f"  Capabilities: {cap_str}")
        sys.exit(0)

    # Select printer
    if args.printer:
        printer_name = args.printer
    elif printers:
        # Auto-select first available printer
        printer_name = printers[0]["name"]
        print(f"Auto-selected printer: {printer_name}")
    else:
        print("ERROR: No physical printers found.", file=sys.stderr)
        sys.exit(1)

    # Validate PDF
    if not os.path.isfile(args.pdf):
        print(f"ERROR: File not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF: {args.pdf}")
    print(f"Printer: {printer_name}")
    print(f"Settings: duplex={args.duplex}, color={args.color}, dpi={args.dpi}")
    print()

    # Step 1: Render PDF
    print("Step 1: Rendering PDF to images...")
    images = render_pdf(args.pdf, dpi=args.dpi)
    print(f"  {len(images)} pages rendered")
    print()

    # Step 2: Print
    print("Step 2: Sending to printer...")
    success = print_images(images, printer_name, args.duplex, args.color)
    print()

    # Step 3: Cleanup
    print("Step 3: Cleaning up...")
    cleanup(images)

    if success:
        print("Done.")
    else:
        print("ERROR: Printing failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
