# claude-code-print-skill

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill for printing PDF files with automatic duplex and color control. Works on **Windows**, **Linux**, and **macOS**.

## Features

- **Cross-platform**: Windows (.NET PrintDocument), Linux/macOS (raw PJL via TCP 9100)
- **Auto-discovery** of physical printers (filters out virtual printers)
- **Capability detection** — duplex and color support per printer
- **Reliable duplex control**:
  - Windows: triple-layer .NET + Win32 DevMode + DefaultPageSettings
  - Linux/macOS: PJL `SET DUPLEX=ON` commands via raw TCP socket (bypasses CUPS)
- **Configurable paper size**: A4, Letter, Legal

## Prerequisites

| Platform | Requirements |
|----------|-------------|
| **Windows** | Python 3.10+, `pymupdf`, `Pillow`, .NET Framework 4.x (`csc.exe`) |
| **Linux** | Python 3.10+, network printer with TCP port 9100 open |
| **macOS** | Python 3.10+, network printer with TCP port 9100 open |

```bash
pip install pymupdf Pillow
```

## Usage

```bash
# List available printers with capabilities
python scripts/print.py --list

# Print test page (no PDF needed)
python scripts/print.py --test --printer 10.123.45.145 --duplex vertical --color mono --paper A4

# Print a PDF (auto-detect printer)
python scripts/print.py document.pdf

# Print with all options
python scripts/print.py document.pdf --printer "HP M401dn" --duplex vertical --color mono --paper A4 --dpi 300
```

## How It Works

### Windows
```
PDF → pymupdf (PNG) → C# PrintEngine.exe (triple-layer DevMode) → Windows Spooler → Printer
```

### Linux / macOS
```
PDF → pymupdf (PNG) → PostScript + PJL DUPLEX=ON → TCP socket 9100 → Printer
```

**Why bypass CUPS?** CUPS duplex settings (`-o sides=two-sided-long-edge`) are frequently ignored by network printers — the PPD duplexer option may be disabled, or IPP may reject the job. Raw PJL via socket is the most reliable cross-platform method.

## Options

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--printer, -p` | Name or IP | Auto-detect | Target printer |
| `--duplex, -d` | `simplex`, `vertical`, `horizontal` | `vertical` | Duplex mode |
| `--color, -c` | `mono`, `color` | `mono` | Color mode |
| `--paper` | `A4`, `Letter`, `Legal` | `A4` | Paper size |
| `--dpi` | Integer | `200` | Render resolution |
| `--list` | — | — | List printers and exit |
| `--test` | — | — | Print test page |

## Install as Claude Code Skill

```bash
# Symlink into skills directory
ln -s "$(pwd)" ~/.claude/skills/print        # Linux/Mac
mklink /D "%USERPROFILE%\.claude\skills\print" "%CD%"  # Windows
```

Then in Claude Code: `/print`, `/print file.pdf`, or say "打印这个PDF".

## Adding a Network Printer

**Windows:**
```powershell
Add-PrinterPort -Name "IP_10.x.x.x" -PrinterHostAddress "10.x.x.x"
Add-Printer -Name "Printer" -PortName "IP_10.x.x.x" -DriverName "Driver Name"
```

**Linux/macOS:**
```bash
lpadmin -p Printer -E -v socket://10.x.x.x -m drv:///sample.drv/generic.ppd
```

## License

MIT
