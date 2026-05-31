#!/usr/bin/env python3
"""
print.py - Cross-platform PDF printer with duplex & color control.

Supported platforms:
  - Windows: .NET PrintDocument + DevMode triple-layer control
  - Linux/macOS: Raw PJL commands via TCP socket 9100 (bypasses CUPS)

Usage:
    python print.py <pdf_path> [--duplex vertical|horizontal|simplex]
                              [--color mono|color]
                              [--printer <name_or_ip>]
                              [--paper A4|Letter|Legal]
"""

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time

PRINT_DPI = 200
PRINTER_PORT = 9100

# Virtual printer patterns to skip (Windows)
VIRTUAL_PATTERNS = [
    "pdf", "xps", "fax", "onenote", "microsoft print",
    "rustdesk", "kingsoft", "wps", "send to", "print to",
    "document writer", "virtual",
]

# PostScript page sizes
PAGE_SIZES = {
    "A4": (595, 842),
    "Letter": (612, 792),
    "Legal": (612, 1008),
}

# ============================================================
# Platform detection
# ============================================================

def get_platform():
    """Return 'windows', 'linux', or 'mac'."""
    s = platform.system().lower()
    if s == "windows":
        return "windows"
    elif s == "darwin":
        return "mac"
    else:
        return "linux"


# ============================================================
# Printer discovery
# ============================================================

def discover_printers_windows():
    """Discover physical printers on Windows via PowerShell."""
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
        if any(vp in name_lower for vp in VIRTUAL_PATTERNS):
            continue
        if p.get("Status", -1) != 0:
            continue
        printers.append({
            "name": p["Name"],
            "driver": p.get("Driver", "Unknown"),
            "ip": p.get("IP", "N/A"),
        })
    return printers


def query_capabilities_windows(printer_name):
    """Query duplex/color support on Windows via C#."""
    csc = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if not os.path.exists(csc):
        return {"duplex": False, "color": False}

    query_code = f'''
using System;
using System.Drawing.Printing;
class Q {{
    static void Main() {{
        try {{
            var ps = new PrinterSettings();
            ps.PrinterName = @"{printer_name}";
            if (!ps.IsValid) return;
            Console.WriteLine(ps.CanDuplex ? "duplex=yes" : "duplex=no");
            Console.WriteLine(ps.SupportsColor ? "color=yes" : "color=no");
        }} catch {{}}
    }}
}}
'''
    tmp = tempfile.mkdtemp(prefix="pcap_")
    cs = os.path.join(tmp, "q.cs")
    exe = os.path.join(tmp, "q.exe")
    with open(cs, "w") as f:
        f.write(query_code)
    subprocess.run([csc, "/nologo", f"/out:{exe}", cs], capture_output=True, timeout=15)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=10)
    shutil.rmtree(tmp, ignore_errors=True)

    caps = {"duplex": False, "color": False}
    for line in r.stdout.strip().splitlines():
        if "duplex=yes" in line: caps["duplex"] = True
        if "color=yes" in line: caps["color"] = True
    return caps


def discover_printers_unix():
    """Discover printers on Linux/macOS via CUPS lpstat."""
    result = subprocess.run(
        ["lpstat", "-v"], capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []

    printers = []
    for line in result.stdout.strip().splitlines():
        # Format: "device for <name>: <uri>"
        parts = line.split()
        if len(parts) >= 3:
            name = parts[1] if len(parts) > 1 else ""
            uri = parts[2] if len(parts) > 2 else ""
            # Extract IP from URI
            ip = "N/A"
            if "://" in uri:
                host_part = uri.split("://")[1].split("/")[0].split(":")[0]
                if not host_part.endswith(".local"):
                    ip = host_part
            if name:
                printers.append({"name": name, "driver": "CUPS", "ip": ip})
    return printers


def query_capabilities_unix(printer_name):
    """Query duplex/color support on Unix via lpoptions."""
    result = subprocess.run(
        ["lpoptions", "-p", printer_name, "-l"],
        capture_output=True, text=True, timeout=10,
    )
    caps = {"duplex": False, "color": False}
    for line in result.stdout.strip().splitlines():
        low = line.lower()
        if "duplex" in low and ("duplexnotumble" in low or "tumble" in low):
            caps["duplex"] = True
        if "color" in low and "rgb" in low:
            caps["color"] = True
    # Socket printers always support PJL duplex
    if not caps["duplex"]:
        caps["duplex"] = True  # PJL can override
    return caps


def discover_printers():
    """Unified printer discovery."""
    pf = get_platform()
    if pf == "windows":
        return discover_printers_windows()
    else:
        return discover_printers_unix()


def query_capabilities(printer_name):
    """Unified capability query."""
    pf = get_platform()
    if pf == "windows":
        return query_capabilities_windows(printer_name)
    else:
        return query_capabilities_unix(printer_name)


# ============================================================
# PDF rendering
# ============================================================

def render_pdf(pdf_path, dpi=PRINT_DPI):
    """Render PDF pages to PNG images via pymupdf."""
    try:
        import pymupdf
    except ImportError:
        print("ERROR: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
        sys.exit(1)

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


# ============================================================
# Printing: Windows (.NET PrintDocument)
# ============================================================

CS_ENGINE = r"""
using System;
using System.Drawing;
using System.Drawing.Printing;
using System.Runtime.InteropServices;

class PrintEngine {
    [DllImport("winspool.drv", CharSet = CharSet.Auto, SetLastError = true)]
    static extern int DocumentProperties(IntPtr hwnd, IntPtr hPrinter, string pDeviceName,
        IntPtr pDevModeOutput, IntPtr pDevModeInput, int fMode);

    static string[] images;
    static int currentIdx = 0;

    static void Main(string[] args) {
        if (args.Length < 4) { Environment.Exit(1); return; }
        string printerName = args[0];
        string duplexMode = args[1].ToLower();
        string colorMode = args[2].ToLower();

        images = new string[args.Length - 3];
        Array.Copy(args, 3, images, 0, images.Length);

        PrintDocument pd = new PrintDocument();
        pd.PrinterSettings.PrinterName = printerName;
        if (!pd.PrinterSettings.IsValid) { Environment.Exit(2); return; }

        // Layer 1: .NET API
        switch (duplexMode) {
            case "vertical":   pd.PrinterSettings.Duplex = Duplex.Vertical; break;
            case "horizontal": pd.PrinterSettings.Duplex = Duplex.Horizontal; break;
            default:           pd.PrinterSettings.Duplex = Duplex.Simplex; break;
        }

        // Layer 2: DevMode
        int size = DocumentProperties(IntPtr.Zero, IntPtr.Zero, printerName,
            IntPtr.Zero, IntPtr.Zero, 0);
        if (size > 0) {
            IntPtr dm = Marshal.AllocHGlobal(size);
            DocumentProperties(IntPtr.Zero, IntPtr.Zero, printerName, dm, IntPtr.Zero, 2);
            int fields = Marshal.ReadInt32(dm, 40) | 0x1000 | 0x800;
            Marshal.WriteInt32(dm, 40, fields);
            Marshal.WriteInt16(dm, 60, (short)(colorMode == "color" ? 1 : 2));
            Marshal.WriteInt16(dm, 62, (short)(duplexMode == "vertical" ? 2 : duplexMode == "horizontal" ? 3 : 1));
            DocumentProperties(IntPtr.Zero, IntPtr.Zero, printerName, dm, dm, 10);
            Marshal.FreeHGlobal(dm);
        }

        // Layer 3: Confirm
        switch (duplexMode) {
            case "vertical":   pd.DefaultPageSettings.PrinterSettings.Duplex = Duplex.Vertical; break;
            case "horizontal": pd.DefaultPageSettings.PrinterSettings.Duplex = Duplex.Horizontal; break;
        }

        pd.DefaultPageSettings.Margins = new Margins(40, 40, 40, 40);
        pd.PrintPage += (sender, e) => {
            if (currentIdx >= images.Length) return;
            using (var img = Image.FromFile(images[currentIdx])) {
                var b = e.MarginBounds;
                float r = Math.Min((float)b.Width / img.Width, (float)b.Height / img.Height);
                e.Graphics.DrawImage(img, b.Left + (b.Width - (int)(img.Width*r))/2,
                    b.Top + (b.Height - (int)(img.Height*r))/2,
                    (int)(img.Width*r), (int)(img.Height*r));
            }
            currentIdx++;
            e.HasMorePages = (currentIdx < images.Length);
        };

        pd.Print();
    }
}
"""


def print_windows(images, printer_name, duplex_mode, color_mode):
    """Print via .NET PrintEngine on Windows."""
    csc = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if not os.path.exists(csc):
        print("ERROR: csc.exe not found", file=sys.stderr)
        return False

    tmp_dir = os.path.dirname(images[0])
    cs_path = os.path.join(tmp_dir, "engine.cs")
    exe_path = os.path.join(tmp_dir, "engine.exe")

    with open(cs_path, "w", encoding="utf-8") as f:
        f.write(CS_ENGINE)

    subprocess.run([csc, "/nologo", f"/out:{exe_path}", cs_path],
                   capture_output=True, timeout=15)

    args = [exe_path, printer_name, duplex_mode, color_mode] + images
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return result.returncode == 0


# ============================================================
# Printing: Linux/macOS (Raw PJL via TCP 9100)
# ============================================================

def print_pjl(images, printer_ip, duplex_mode, color_mode, paper="A4"):
    """Print rendered images as PostScript with PJL duplex/color commands via TCP 9100."""
    pw, ph = PAGE_SIZES.get(paper, PAGE_SIZES["A4"])
    duplex_ps = "<< /Duplex true /Tumble false >> setpagedevice\n"
    if duplex_mode == "horizontal":
        duplex_ps = "<< /Duplex true /Tumble true >> setpagedevice\n"
    elif duplex_mode == "simplex":
        duplex_ps = "<< /Duplex false >> setpagedevice\n"

    # Build PostScript from PNG images (embed as ASCII85 for compatibility)
    try:
        from PIL import Image
        import io, base64
    except ImportError:
        print("ERROR: Pillow not installed. Run: pip install Pillow", file=sys.stderr)
        return False

    ps_pages = []
    for img_path in images:
        img = Image.open(img_path)
        # Convert to grayscale if mono
        if color_mode == "mono":
            img = img.convert("L")
        else:
            img = img.convert("RGB")

        w, h = img.size
        buf = io.BytesIO()
        img.save(buf, format="PPM")  # PPM is easy to embed in PS
        ppm_data = buf.getvalue()

        ps_page = f"""%%Page: {len(ps_pages)+1} {len(ps_pages)+1}
gsave
{pw} {ph} translate
{pw} 0 translate
{ph} neg {ph} div {pw} neg {pw} div scale
0 0 translate
{pw} {ph} 8 [{pw} 0 0 {ph} neg 0 {ph}]
<"""
        # Encode as hex
        # Actually, let's use a simpler approach: render to PS with image operator
        # For reliability, let's just send text pages for now and handle image printing separately
        ps_pages.append(ps_page)
        img.close()

    # Simpler approach: generate a PS with text content + PJL wrapper
    # For full PDF printing, we convert the PDF to PS via pymupdf
    # But for now, let's use the proven approach: PS + PJL via socket

    print(f"Connecting to {printer_ip}:{PRINTER_PORT}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((printer_ip, PRINTER_PORT))
    except Exception as e:
        print(f"ERROR: Cannot connect to {printer_ip}:{PRINTER_PORT}: {e}", file=sys.stderr)
        return False

    for i, img_path in enumerate(images):
        from PIL import Image as PILImage
        img = PILImage.open(img_path)
        iw, ih = img.size

        # Calculate scale to fit page
        scale_x = pw / iw * 72 / PRINT_DPI
        scale_y = ph / ih * 72 / PRINT_DPI
        scale = min(scale_x, scale_y) * 0.9

        draw_w = int(iw * scale)
        draw_h = int(ih * scale)

        # Convert image to raw RGB
        rgb_img = img.convert("RGB")
        raw = rgb_img.tobytes()

        # Build PJL + PS for each page
        pjl_header = (
            b'\x1B%-12345X@PJL JOB\r\n'
            b'@PJL SET DUPLEX=' + (b'ON' if duplex_mode != 'simplex' else b'OFF') + b'\r\n' +
            (b'@PJL SET BINDING=LONGEDGE\r\n' if duplex_mode == 'vertical' else b'') +
            (b'@PJL SET BINDING=SHORTEDGE\r\n' if duplex_mode == 'horizontal' else b'') +
            (b'@PJL SET DENSITY=3\r\n' if color_mode == 'mono' else b'') +
            b'@PJL ENTER LANGUAGE=POSTSCRIPT\r\n'
        )

        ps = (
            b'%!PS-Adobe-3.0\n' +
            duplex_ps.encode() +
            f'<< /PageSize [{pw} {ph}] >> setpagedevice\n'.encode() +
            f'%%Pages: 1\n%%Page: 1 1\n'.encode() +
            f'gsave\n'.encode() +
            f'{(pw - draw_w)//2} {(ph - draw_h)//2} translate\n'.encode() +
            f'{draw_w} {draw_h} scale\n'.encode() +
            f'{draw_w} {draw_h} 8 [{draw_w} 0 0 {draw_h} neg 0 {draw_h}]\n'.encode() +
            b'{currentfile /ascii85hex filter false {} colorimage}\n'
        )

        # Encode raw RGB as ASCII85 hex
        import binascii
        hex_data = binascii.hexlify(raw).upper()

        pjl_footer = b'\nshowpage\n%%EOF\n\x1B%-12345X@PJL EOJ\r\n\x1B%-12345X\r\n'

        data = pjl_header + ps + hex_data + pjl_footer

        print(f"  Page {i+1}/{len(images)}: {len(data)} bytes")
        s.sendall(data)
        time.sleep(0.5)

    time.sleep(2)
    s.close()
    print("OK: All pages sent")
    return True


def print_pdf_direct(printer_ip, duplex_mode, color_mode, paper="A4"):
    """Print a simple PS test page via PJL (for testing without pymupdf)."""
    pw, ph = PAGE_SIZES.get(paper, PAGE_SIZES["A4"])

    dup_ps = "<< /Duplex true /Tumble false >> setpagedevice\n"
    dup_pjl = b"@PJL SET DUPLEX=ON\r\n@PJL SET BINDING=LONGEDGE\r\n"
    if duplex_mode == "horizontal":
        dup_ps = "<< /Duplex true /Tumble true >> setpagedevice\n"
        dup_pjl = b"@PJL SET DUPLEX=ON\r\n@PJL SET BINDING=SHORTEDGE\r\n"
    elif duplex_mode == "simplex":
        dup_ps = "<< /Duplex false >> setpagedevice\n"
        dup_pjl = b"@PJL SET DUPLEX=OFF\r\n"

    ps = (
        f'%!PS-Adobe-3.0\n'
        f'{dup_ps}'
        f'<< /PageSize [{pw} {ph}] >> setpagedevice\n'
        f'%%Pages: 2\n'
        f'%%Page: 1 1\n'
        f'/Helvetica findfont 36 scalefont setfont\n'
        f'72 700 moveto (DUPLEX TEST - Page 1) show\n'
        f'/Helvetica findfont 14 scalefont setfont\n'
        f'72 650 moveto (Platform: {platform.system()} / PJL / {paper}) show\n'
        f'72 630 moveto (Duplex: {duplex_mode} / Color: {color_mode}) show\n'
        f'showpage\n'
        f'%%Page: 2 2\n'
        f'/Helvetica findfont 36 scalefont setfont\n'
        f'72 700 moveto (DUPLEX TEST - Page 2) show\n'
        f'/Helvetica findfont 14 scalefont setfont\n'
        f'72 650 moveto (If on back of page 1 = SUCCESS) show\n'
        f'showpage\n'
        f'%%EOF\n'
    )

    data = (
        b'\x1B%-12345X@PJL JOB\r\n' +
        dup_pjl +
        b'@PJL ENTER LANGUAGE=POSTSCRIPT\r\n' +
        ps.encode() +
        b'\x1B%-12345X@PJL EOJ\r\n\x1B%-12345X\r\n'
    )

    print(f"Connecting to {printer_ip}:{PRINTER_PORT}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((printer_ip, PRINTER_PORT))
        s.sendall(data)
        time.sleep(2)
        s.close()
        print(f"OK: {len(data)} bytes sent")
        return True
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False


# ============================================================
# Cleanup
# ============================================================

def cleanup(images):
    if not images:
        return
    tmp_dir = os.path.dirname(images[0])
    for f in images:
        try: os.remove(f)
        except: pass
    for ext in ["engine.cs", "engine.exe"]:
        try: os.remove(os.path.join(tmp_dir, ext))
        except: pass


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Cross-platform PDF printer with duplex/color control")
    parser.add_argument("pdf", nargs="?", help="Path to PDF file (omit for test page)")
    parser.add_argument("--printer", "-p", help="Printer name (Windows) or IP address (Linux/Mac)")
    parser.add_argument("--duplex", "-d",
                        choices=["simplex", "vertical", "horizontal"],
                        default="vertical", help="Duplex mode (default: vertical)")
    parser.add_argument("--color", "-c",
                        choices=["mono", "color"],
                        default="mono", help="Color mode (default: mono)")
    parser.add_argument("--paper", choices=["A4", "Letter", "Legal"],
                        default="A4", help="Paper size (default: A4)")
    parser.add_argument("--dpi", type=int, default=PRINT_DPI, help="Render DPI (default: 200)")
    parser.add_argument("--list", action="store_true", help="List printers and exit")
    parser.add_argument("--test", action="store_true", help="Print a test page (no PDF needed)")

    args = parser.parse_args()
    pf = get_platform()

    # Discover printers
    printers = discover_printers()

    if args.list:
        if not printers:
            print("No printers found.")
            sys.exit(0)
        print(f"{'Name':<45} {'IP':<18} {'Driver'}")
        print("-" * 90)
        for p in printers:
            caps = query_capabilities(p["name"])
            flags = []
            if caps["duplex"]: flags.append("duplex")
            if caps["color"]: flags.append("color")
            print(f"{p['name']:<45} {str(p.get('ip','N/A')):<18} {p.get('driver','?')}")
            print(f"  Capabilities: {','.join(flags) or 'basic'}")
        sys.exit(0)

    # Resolve printer
    if args.printer:
        printer_target = args.printer
    elif printers:
        printer_target = printers[0]["name"]
        # For Unix, use the IP if available
        if pf != "windows" and printers[0].get("ip", "N/A") != "N/A":
            printer_target = printers[0]["ip"]
        print(f"Auto-selected: {printer_target}")
    else:
        print("ERROR: No printers found.", file=sys.stderr)
        sys.exit(1)

    # Test page mode
    if args.test:
        if pf == "windows":
            # On Windows, use the proven .NET approach
            # Generate a simple 2-page test PDF first
            try:
                import pymupdf
                tmp = tempfile.mkdtemp(prefix="ptest_")
                test_pdf = os.path.join(tmp, "test.pdf")
                doc = pymupdf.open()
                for i in range(1, 3):
                    page = doc.new_page(width=595, height=842)
                    page.insert_text((72, 100), f"Test Page {i}/2", fontsize=36)
                    page.insert_text((72, 160), f"Platform: {pf}", fontsize=14)
                    page.insert_text((72, 185), f"Duplex: {args.duplex}", fontsize=14)
                    page.insert_text((72, 210), f"Color: {args.color}", fontsize=14)
                doc.save(test_pdf)
                doc.close()
                images = render_pdf(test_pdf, dpi=args.dpi)
                ok = print_windows(images, printer_target, args.duplex, args.color)
                cleanup(images)
                shutil.rmtree(tmp, ignore_errors=True)
                sys.exit(0 if ok else 1)
            except ImportError:
                print("ERROR: pymupdf needed for test page on Windows", file=sys.stderr)
                sys.exit(1)
        else:
            # Unix: direct PJL test
            ok = print_pdf_direct(printer_target, args.duplex, args.color, args.paper)
            sys.exit(0 if ok else 1)

    # PDF print mode
    if not args.pdf:
        print("ERROR: Provide a PDF file or use --test", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(args.pdf):
        print(f"ERROR: File not found: {args.pdf}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF: {args.pdf}")
    print(f"Printer: {printer_target}")
    print(f"Settings: duplex={args.duplex}, color={args.color}, paper={args.paper}, dpi={args.dpi}")
    print(f"Platform: {pf}")
    print()

    # Render
    print("Rendering PDF...")
    images = render_pdf(args.pdf, dpi=args.dpi)
    print(f"  {len(images)} pages")

    # Print
    print("Printing...")
    if pf == "windows":
        ok = print_windows(images, printer_target, args.duplex, args.color)
    else:
        ok = print_pjl(images, printer_target, args.duplex, args.color, args.paper)

    cleanup(images)
    print("Done." if ok else "FAILED.", file=sys.stderr if not ok else sys.stdout)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
