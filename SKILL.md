---
name: print
description: Print PDF files to Windows/Linux/macOS printers with duplex and color control via PJL or .NET PrintDocument.
allowed-tools: [Bash, Read, AskUserQuestion]
---

# Print PDF Skill

Cross-platform PDF printing with duplex and color control. Works on Windows, Linux, and macOS.

## When to Use

Trigger when the user says: `/print`, `打印`, `双面打印`, `print PDF`, `print duplex`, or wants to send a document to a physical printer.

## Onboarding Questions

On first use, ask the user:

1. **Printer selection**: List discovered printers. If multiple found, ask which one.
2. **Duplex mode**: simplex / vertical (long-edge, like a book) / horizontal (short-edge) — default: vertical
3. **Color mode**: mono (black & white) / color — default: mono
4. **Paper size**: A4 / Letter / Legal — default: A4

## Platform Detection

```bash
python3 -c "import platform; print(platform.system())"
# Windows → "Windows", Linux → "Linux", macOS → "Darwin"
```

## Workflow

### Step 1: Discover Printers

```bash
python3 <skill-dir>/scripts/print.py --list
```

Lists all physical printers with IP, driver, duplex support, and color support.

### Step 2: Ask User Preferences

Use AskUserQuestion for:
- Which printer (if multiple)
- Duplex: simplex / vertical / horizontal
- Color: mono / color
- Paper: A4 / Letter / Legal

### Step 3: Print

**Test page** (no PDF needed):
```bash
python3 <skill-dir>/scripts/print.py --test --printer <name_or_ip> --duplex vertical --color mono --paper A4
```

**Print a PDF**:
```bash
python3 <skill-dir>/scripts/print.py file.pdf --printer <name_or_ip> --duplex vertical --color mono --paper A4
```

### Step 4: Verify

```bash
# Windows
Get-PrintJob -PrinterName "<name>" | Format-Table Id, DocumentName, JobStatus

# Linux/macOS
lpq -P <printer_name>
```

## How It Works

### Windows Pipeline
```
PDF → pymupdf (render PNG) → .NET PrintDocument (triple-layer DevMode) → Windows Spooler → Printer
```
Triple-layer duplex/color control: .NET `PrinterSettings.Duplex` + Win32 `DocumentProperties` DevMode + `DefaultPageSettings` confirm.

### Linux/macOS Pipeline
```
PDF → pymupdf (render PNG) → PostScript + PJL commands → TCP socket 9100 → Printer
```
Sends PJL preamble (`@PJL SET DUPLEX=ON`, `@PJL SET BINDING=LONGEDGE`) with PostScript page data directly to the printer's raw port. Bypasses CUPS entirely for reliable duplex control.

### Why Bypass CUPS?
CUPS duplex settings (`-o sides=two-sided-long-edge`) are frequently ignored by network printers — the PPD duplexer option may be disabled, or IPP protocol may reject the job. Raw PJL via socket is the most reliable cross-platform method.

## Printer Setup (if not auto-discovered)

**Windows:**
```powershell
Add-PrinterPort -Name "IP_<ip>" -PrinterHostAddress "<ip>"
Add-Printer -Name "<Name>" -PortName "IP_<ip>" -DriverName "<Driver>"
```

**Linux/macOS:**
```bash
lpadmin -p <name> -E -v socket://<printer_ip> -m drv:///sample.drv/generic.ppd
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Garbled output | Ensure using PJL+PostScript or image mode, not raw PDF bytes |
| Single-sided despite duplex | Use PJL `@PJL SET DUPLEX=ON` (Unix) or triple-layer DevMode (Windows) |
| Linux job rejected by IPP | Switch to `socket://` URI instead of `implicitclass://` or `ipp://` |
| Mac CUPS not running | `sudo launchctl load -w /System/Library/LaunchDaemons/org.cups.cupsd.plist` |
| Cannot connect port 9100 | Check firewall, verify printer IP with `ping` and `nc -z <ip> 9100` |
