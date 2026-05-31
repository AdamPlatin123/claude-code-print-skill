from setuptools import setup

setup(
    name="claude-code-print-skill",
    version="1.0.0",
    description="Print PDF files to Windows printers with duplex and color control",
    py_modules=["print"],
    packages=["scripts"],
    install_requires=[
        "pymupdf>=1.24.0",
        "Pillow>=10.0.0",
    ],
    entry_points={
        "console_scripts": [
            "ccprint=scripts.print:main",
        ],
    },
    python_requires=">=3.10",
)
