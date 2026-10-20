# Headless KZL Ghidra analysis

The project database contains ISO-derived code and stays under ignored `out/ghidra/`.
Only the scripts and non-copyrighted reports are committed.

Validated toolchain:

- Ghidra 12.1.3
- ghidra-allegrex v21.4 package built for Ghidra 12.1.3
- Java 21

Generate the canonical import/export labels:

```powershell
python tools\kzl\ghidra_symbols.py --output out\ghidra\kzl_symbols.csv
```

Create the project. `PspElfLoader` and the image-base option are both required;
an automatic import without the option loads this relocatable PRX at zero.

```powershell
$env:JAVA_HOME = 'C:\path\to\jdk-21'
$headless = 'C:\path\to\ghidra_12.1.3_PUBLIC\support\analyzeHeadless.bat'
& $headless out\ghidra KZL `
  -import build\kzl\disc\KZL.PRX `
  -loader PspElfLoader `
  -loader-imagebase 08804000 `
  -analysisTimeoutPerFile 1800
```

Apply labels and export reports:

```powershell
& $headless out\ghidra KZL -process KZL.PRX -noanalysis `
  -scriptPath tools\ghidra `
  -postScript ApplyKzlSymbols.java "$PWD\out\ghidra\kzl_symbols.csv" `
  -postScript ExportKzlReport.java "$PWD\out\ghidra\kzl_report.txt" `
  -postScript ExportKzlFunctions.java "$PWD\out\ghidra\kzl_functions.csv"
```

The scripts fail on missing functions or malformed labels instead of silently
creating a success-shaped report.
