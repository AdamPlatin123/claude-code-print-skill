// PrintEngine.cs - Generic Windows PDF/image printer via .NET PrintDocument
// Accepts command-line args: <printer_name> <duplex_mode> <color_mode> <image1> [image2] ...
// duplex_mode: simplex | vertical | horizontal
// color_mode: mono | color
// Images are printed one per page, auto-fitted to page margins.

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
    static string duplexMode;   // simplex | vertical | horizontal
    static string colorMode;    // mono | color

    static void Main(string[] args) {
        if (args.Length < 4) {
            Console.WriteLine("Usage: PrintEngine.exe <printer> <duplex> <color> <img1> [img2 ...]");
            Console.WriteLine("  duplex: simplex | vertical | horizontal");
            Console.WriteLine("  color:  mono | color");
            Environment.Exit(1);
        }

        string printerName = args[0];
        duplexMode = args[1].ToLower();
        colorMode = args[2].ToLower();

        images = new string[args.Length - 3];
        Array.Copy(args, 3, images, 0, images.Length);

        PrintDocument pd = new PrintDocument();
        pd.PrinterSettings.PrinterName = printerName;

        if (!pd.PrinterSettings.IsValid) {
            Console.WriteLine("ERROR: Printer not valid: " + printerName);
            Environment.Exit(2);
        }

        // === Layer 1: .NET API ===
        switch (duplexMode) {
            case "vertical":   pd.PrinterSettings.Duplex = Duplex.Vertical; break;
            case "horizontal": pd.PrinterSettings.Duplex = Duplex.Horizontal; break;
            default:           pd.PrinterSettings.Duplex = Duplex.Simplex; break;
        }

        // === Layer 2: DevMode (Win32 API) ===
        SetDevMode(printerName, duplexMode, colorMode);

        // === Layer 3: DefaultPageSettings confirm ===
        switch (duplexMode) {
            case "vertical":   pd.DefaultPageSettings.PrinterSettings.Duplex = Duplex.Vertical; break;
            case "horizontal": pd.DefaultPageSettings.PrinterSettings.Duplex = Duplex.Horizontal; break;
        }

        pd.DefaultPageSettings.Margins = new Margins(40, 40, 40, 40);
        pd.DefaultPageSettings.Landscape = false;

        pd.PrintPage += OnPrintPage;

        Console.WriteLine("Printing " + images.Length + " pages [" +
            duplexMode + ", " + colorMode + "] to " + printerName);
        pd.Print();
        Console.WriteLine("OK: Print job sent");
    }

    static void OnPrintPage(object sender, PrintPageEventArgs e) {
        if (currentIdx >= images.Length) return;

        using (var img = Image.FromFile(images[currentIdx])) {
            var bounds = e.MarginBounds;
            float ratio = Math.Min(
                (float)bounds.Width / img.Width,
                (float)bounds.Height / img.Height);
            int w = (int)(img.Width * ratio);
            int h = (int)(img.Height * ratio);
            int x = bounds.Left + (bounds.Width - w) / 2;
            int y = bounds.Top + (bounds.Height - h) / 2;
            e.Graphics.DrawImage(img, x, y, w, h);
        }

        currentIdx++;
        e.HasMorePages = (currentIdx < images.Length);
    }

    static void SetDevMode(string printer, string duplex, string color) {
        // DM_OUT_BUFFER=2, DM_IN_BUFFER=8, DM_IN_OUT=10
        const int DM_DUPLEX = 0x1000;
        const int DM_COLOR  = 0x800;

        int size = DocumentProperties(IntPtr.Zero, IntPtr.Zero, printer,
            IntPtr.Zero, IntPtr.Zero, 0);
        if (size <= 0) return;

        IntPtr dm = Marshal.AllocHGlobal(size);
        try {
            // Read current DevMode
            if (DocumentProperties(IntPtr.Zero, IntPtr.Zero, printer,
                dm, IntPtr.Zero, 2) != 1) return;

            int fields = Marshal.ReadInt32(dm, 40);

            // Duplex (offset 62): 1=simplex, 2=vertical, 3=horizontal
            fields |= DM_DUPLEX;
            short dupVal = duplex switch {
                "vertical"   => 2,
                "horizontal" => 3,
                _            => 1
            };
            Marshal.WriteInt16(dm, 62, dupVal);

            // Color (offset 60): 1=color, 2=monochrome
            fields |= DM_COLOR;
            short colVal = color == "color" ? (short)1 : (short)2;
            Marshal.WriteInt16(dm, 60, colVal);

            Marshal.WriteInt32(dm, 40, fields);

            // Write back
            DocumentProperties(IntPtr.Zero, IntPtr.Zero, printer,
                dm, dm, 10);
        } finally {
            Marshal.FreeHGlobal(dm);
        }
    }
}
