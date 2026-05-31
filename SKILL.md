---
name: print
description: Print PDF files to Windows printers with duplex and color control. Auto-discovers physical printers and queries their capabilities.
allowed-tools: [Bash, Read, AskUserQuestion]
---

# Print PDF Skill

Print PDF files to physical Windows printers with automatic duplex and color control.

## When to Use

Trigger this skill when the user wants to:
- Print a PDF file (`/print`, `/print file.pdf`, `打印`)
- Print with specific settings (`双面打印`, `黑白打印`, `print duplex`)
- List available printers (`list printers`, `/print --list`)
- Send a document to a printer from the terminal

## Prerequisites Check

Before printing, verify these are available:

1. **Python packages**: `pymupdf` and `Pillow`
   ```bash
   python3 -c "import pymupdf; from PIL import Image; print('OK')"
   ```
   If missing: `pip install pymupdf Pillow`

2. **C# compiler**: Must exist at `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`

3. **Physical printers**: At least one non-virtual printer installed

## Workflow

### Step 1: Discover Printers

Run the print script in list mode to discover printers and their capabilities:

```bash
python3 <skill-dir>/scripts/print.py --list
```

This outputs all physical printers with their IP, driver, duplex support, and color support.

### Step 2: Ask User for Preferences

Use AskUserQuestion to ask the user:

1. **Which printer** to use — list discovered printers as options
2. **Duplex mode** — simplex / vertical (long-edge, like a book) / horizontal (short-edge)
3. **Color mode** — mono (black & white) / color

If only one printer is found, skip the printer selection.

### Step 3: Print

```bash
python3 <skill-dir>/scripts/print.py <pdf_path> \
  --printer "<printer_name>" \
  --duplex <simplex|vertical|horizontal> \
  --color <mono|color>
```

### Step 4: Verify

Check the print queue:
```powershell
Get-PrintJob -PrinterName "<printer_name>" | Format-Table Id, DocumentName, JobStatus, SubmittedTime
```

## How It Works

The printing pipeline:

1. **pymupdf** renders each PDF page to a PNG image (200 DPI by default)
2. **PrintEngine.cs** is compiled to a temporary .exe via `csc.exe`
3. The engine uses **.NET PrintDocument** with triple-layer duplex/color settings:
   - Layer 1: `PrinterSettings.Duplex` / `.DefaultPageSettings` (.NET API)
   - Layer 2: `DocumentProperties` Win32 API (DevMode direct write)
   - Layer 3: `DefaultPageSettings.PrinterSettings.Duplex` confirmation
4. Images are printed one per page, auto-fitted to page margins
5. Temporary files are cleaned up

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| "No physical printers found" | All printers are virtual (PDF, XPS, etc.) | Install a real printer driver |
| Garbled output | Raw PDF bytes sent to printer | This skill uses image-based printing — should not happen |
| Prints single-sided | Duplex setting overridden | Triple-layer setting in PrintEngine.cs handles this |
| Print job not reaching printer | Wrong IP / offline printer | Check `--list` output, verify IP connectivity |
| csc.exe not found | .NET Framework not installed | Install .NET Framework 4.x |

## Flags

```
positional:
  pdf                   Path to PDF file

options:
  --printer, -p         Printer name (auto-detect if omitted)
  --duplex, -d          simplex | vertical | horizontal (default: vertical)
  --color, -c           mono | color (default: mono)
  --dpi                 Render DPI (default: 200)
  --list                List available printers and exit
```

## Adding a New Printer

If the target printer is not listed:

1. Create a TCP/IP port: `Add-PrinterPort -Name "IP_<ip>" -PrinterHostAddress "<ip>"`
2. Add printer: `Add-Printer -Name "<Name>" -PortName "IP_<ip>" -DriverName "<Driver>"`
3. The printer will appear in `--list` output automatically
