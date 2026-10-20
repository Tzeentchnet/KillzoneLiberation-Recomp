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

Export string xrefs, then recover and apply evidence-backed library/class names:

```powershell
& $headless out\ghidra KZL -process KZL.PRX -noanalysis `
  -scriptPath tools\ghidra `
  -postScript ExportKzlStringXrefs.java "$PWD\out\ghidra\kzl_string_xrefs.tsv"

python tools\kzl\class_recovery.py `
  --functions out\ghidra\kzl_functions.csv `
  --string-xrefs out\ghidra\kzl_string_xrefs.tsv `
  --symbols out\ghidra\kzl_class_symbols.csv `
  --report research\kzl_class_recovery.txt

& $headless out\ghidra KZL -process KZL.PRX -noanalysis `
  -scriptPath tools\ghidra `
  -postScript ApplyKzlSymbols.java "$PWD\out\ghidra\kzl_class_symbols.csv"
```

The scripts fail on missing functions or malformed labels instead of silently
creating a success-shaped report.
